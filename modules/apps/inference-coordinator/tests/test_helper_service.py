"""Helper entrypoint boundaries with fake clients; no root or service actions."""
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.backend_http import LifecycleError
from coordinator.helper_service import parse_manifest, ready_api
from coordinator.supervision import APIState, SupervisionError


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_exec_completion_before_http_bind_retries_reads_only(self):
        control=SimpleNamespace(request=AsyncMock(side_effect=[LifecycleError('unavailable'),
            (200,{'version':'0.40.11'}),(200,{'models':[]})]))
        async with asyncio.timeout(1):
            self.assertEqual(await ready_api(control,'0.40.11',poll_interval=0.001),APIState('0.40.11',()))
        self.assertEqual([call.args for call in control.request.await_args_list],
                         [('GET','/api/version'),('GET','/api/version'),('GET','/api/ps')])

    async def test_valid_wrong_version_or_resident_model_never_retries(self):
        for version,residents in (('other',[]),('0.40.11',[{'name':'unexpected'}])):
            control=SimpleNamespace(request=AsyncMock(side_effect=[(200,{'version':version}),(200,{'models':residents})]))
            with self.assertRaises(SupervisionError):
                await ready_api(control,'0.40.11',poll_interval=0.001)
            self.assertEqual(control.request.await_count,2)

    async def test_outer_deadline_stops_unavailable_reads_without_mutation(self):
        control=SimpleNamespace(request=AsyncMock(side_effect=LifecycleError('unavailable')))
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.01):
                await ready_api(control,'0.40.11',poll_interval=0.001)
        self.assertTrue(all(call.args==('GET','/api/version') for call in control.request.await_args_list))


class ManifestTests(unittest.TestCase):
    def value(self):
        return dict(unit='ollama.service',cgroup='/system.slice/ollama.service',
                    fragment=dict(path='/nix/store/'+'a'*32+'-unit/ollama.service',sha256='b'*64),configuration=[],
                    upstream='http://127.0.0.1:12434',backend_version='0.40.11',backend='ollama',
                    allowed_user='inference-coordinator',busctl='/nix/store/'+'c'*32+'-systemd/bin/busctl',
                    stop_timeout=90,phase_timeout=120,total_timeout=270)

    def test_data_only_manifest_fingerprint(self):
        value,deployment,contract=parse_manifest(json.dumps(self.value()).encode())
        self.assertEqual(contract.identity,deployment.identity)
        self.assertTrue(contract.lazy_start)
        self.assertEqual(contract.stop_timeout,90)

    def test_unknown_fields_and_versions_not_blessed(self):
        for changes in (dict(unknown='value'),dict(backend_version='other')):
            with self.assertRaises((SupervisionError,ValueError)):
                parse_manifest(json.dumps({**self.value(),**changes}).encode())


if __name__=='__main__':
    unittest.main()
