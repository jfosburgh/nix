"""Startup probe fixtures: no real credentials, service execution or GPU I/O."""
import contextlib
from dataclasses import replace
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from coordinator.credentials import CredentialError
from coordinator.supervision import SupervisionError
from test_config import fixture
from coordinator.config import parse_config
import json
import struct

spec = importlib.util.spec_from_file_location('api_startup_probe',
    Path(__file__).resolve().parents[1] / 'scripts/check-api-startup.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class StartupProbeTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, file_error=None, credential_error=None, uid=987,
                       acl=struct.pack('<IHHI', 2, 2, 4, 987)):
        config = parse_config(json.dumps(fixture()).encode())
        config = replace(config, limits=replace(config.limits, lifecycle_timeout=300))
        stat = SimpleNamespace(st_uid=0, st_gid=981, st_mode=0o100440, st_nlink=1)
        self.output = io.StringIO()
        self.assembly = MagicMock(return_value=SimpleNamespace(app=object()))
        self.runner = MagicMock()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(self.output))
            stack.enter_context(contextlib.redirect_stderr(self.output))
            stack.enter_context(patch('pwd.getpwnam', return_value=SimpleNamespace(pw_uid=987)))
            stack.enter_context(patch.object(probe.os, 'geteuid', return_value=uid))
            stack.enter_context(patch.dict(probe.os.environ,
                CREDENTIALS_DIRECTORY='/run/credentials/inference-startup-check.service'))
            files = stack.enter_context(patch.object(probe, 'read_operator_file',
                return_value=b'fixture', side_effect=file_error))
            stack.enter_context(patch.object(probe, 'load_calibrated', return_value=config))
            stack.enter_context(patch.object(probe.os, 'stat', side_effect=[stat, stat,
                SimpleNamespace(st_uid=0, st_mode=0o140660)]))
            stack.enter_context(patch.object(probe.stat, 'S_ISSOCK', return_value=True))
            stack.enter_context(patch.object(probe.os, 'access', return_value=True))
            stack.enter_context(patch.object(probe.os, 'getxattr', return_value=acl))
            self.credentials = stack.enter_context(patch.object(probe, 'load_systemd_credentials',
                return_value=object(), side_effect=credential_error))
            stack.enter_context(patch.object(probe, 'assemble', self.assembly))
            stack.enter_context(patch.object(probe, 'create_runner', self.runner))
            stack.enter_context(patch.object(probe, 'read_linux_memory'))
            result = await probe.check()
            self.files_called = files.call_count
            return result

    async def test_success_uses_disposable_snapshots_without_runner_setup(self):
        self.assertEqual(await self.exercise(), 0)
        config = self.credentials.call_args.args[0]
        self.assertEqual(config.token_file, '/run/credentials/inference-startup-check.service/client')
        self.assertEqual(config.admin_token_file, '/run/credentials/inference-startup-check.service/admin')
        self.runner.return_value.setup.assert_not_called()
        self.runner.return_value.cleanup.assert_not_called()
        self.assertIn('CHECK PASSED', self.output.getvalue())

    async def test_credential_failure_names_stage_not_secret_message(self):
        self.assertEqual(await self.exercise(credential_error=CredentialError('DO NOT LOG')), 1)
        self.assertIn('secure credential snapshot load: CredentialError', self.output.getvalue())
        self.assertNotIn('DO NOT LOG', self.output.getvalue())
        self.assembly.assert_not_called()

    async def test_operator_file_failure_has_safe_stage(self):
        self.assertEqual(await self.exercise(file_error=SupervisionError('DO NOT LOG')), 1)
        self.assertIn('root-owned config/template read: SupervisionError', self.output.getvalue())
        self.assertNotIn('DO NOT LOG', self.output.getvalue())
        self.credentials.assert_not_called()

    async def test_malformed_acl_metadata_stops_before_loading_secrets(self):
        self.assertEqual(await self.exercise(acl=b'bad'), 1)
        self.assertIn('at credential snapshot metadata', self.output.getvalue())
        self.credentials.assert_not_called()

    async def test_wrong_identity_refused_before_reading_files(self):
        self.assertEqual(await self.exercise(uid=1000), 1)
        self.assertEqual(self.files_called, 0)
        self.assertIn('at identity', self.output.getvalue())
