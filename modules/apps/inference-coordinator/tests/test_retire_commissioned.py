"""Healthy-state retirement refuses uncertainty; fixtures never change services."""
import errno
import os
import tempfile
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from coordinator.supervision import SupervisionError

spec = importlib.util.spec_from_file_location('retire_commissioned',
    Path(__file__).resolve().parents[1] / 'scripts/retire-commissioned-state.py')
retire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)


class RetirementTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_journal_only(self):
        retire.clean(SimpleNamespace(pending=None))
        for intent in (object(), SimpleNamespace(result='done')):
            with self.assertRaises(SupervisionError):
                retire.clean(SimpleNamespace(pending=intent))

    def test_only_independently_stopped_units(self):
        stopped = dict(ActiveState='inactive', MainPID='0', ControlPID='0', Job='')
        retire.stopped(stopped)
        retire.stopped(dict(stopped, ActiveState='failed'))
        for changes in (dict(ActiveState='active'), dict(MainPID='1'), dict(ControlPID='1'),
                        dict(Job='123'), dict(MainPID='')):
            with self.subTest(changes=changes), self.assertRaises(SupervisionError):
                retire.stopped(dict(stopped, **changes))

    def test_move_preserves_whole_state_and_config_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, config, archive = root/'state', root/'config', root/'archive'
            state.mkdir(mode=0o700)
            config.mkdir()
            (state/'jobs.jsonl').write_bytes(b'original journal fixture\n')
            (state/'pins.json').write_bytes(b'original pins fixture\n')
            (config/'config.json').write_bytes(b'{"synthetic":"config"}\n')
            before = state.stat().st_ino
            descriptors = [os.open(path, os.O_RDONLY | os.O_DIRECTORY) for path in (state,config,root)]
            try:
                with patch.object(retire,'STATE',str(state)), patch.object(retire,'ARCHIVE',str(archive)):
                    retire.move_state(*descriptors)
                    with self.assertRaises(FileExistsError):
                        retire.move_state(*descriptors)
            finally:
                for fd in descriptors: os.close(fd)
            self.assertEqual((archive/'supervisor').stat().st_ino, before)
            self.assertEqual((archive/'supervisor/jobs.jsonl').read_bytes(), b'original journal fixture\n')
            self.assertEqual((archive/'config.json').read_bytes(), b'{"synthetic":"config"}\n')
            self.assertEqual(list(state.iterdir()), [])
            self.assertEqual(state.stat().st_mode & 0o777, 0o700)
            self.assertFalse((config/'config.json').exists())

    async def test_unresolved_journal_refuses_before_any_filesystem_mutation(self):
        journal = MagicMock()
        journal.__enter__.return_value = SimpleNamespace(pending=object())
        fence = SimpleNamespace(bus=object(), units_load_usec=123, version='262')
        with patch.object(retire.os, 'geteuid', return_value=0), \
             patch.object(retire.os.path, 'realpath', return_value=retire.ACTIVE), \
             patch.object(retire.os.path, 'lexists', return_value=False), \
             patch.object(retire.os, 'umask'), patch.object(retire, 'read_operator_file'), \
             patch.object(retire, 'parse_manifest', return_value=(None,SimpleNamespace(identity='fixture'),SimpleNamespace(unit='ollama.service'))), \
             patch.object(retire, 'load_pins', return_value=(fence, object(), 'boot')), \
             patch.object(retire, 'boot_id', return_value='boot'), \
             patch.object(retire, 'JobJournal', return_value=journal), \
             patch.object(retire.os, 'mkdir') as mkdir, patch.object(retire.os, 'rename') as rename:
            with self.assertRaises(SupervisionError):
                await retire.retire()
        mkdir.assert_not_called()
        rename.assert_not_called()

    async def test_cold_check_reads_only_and_refuses_populated_group(self):
        fence, mount = object(), object()
        result = SimpleNamespace(stdout=b'ActiveState=inactive\nMainPID=0\nControlPID=0\nJob=\n', stderr=b'')
        with patch.object(retire, 'observe_fence', AsyncMock(return_value=fence)), \
             patch.object(retire, 'observe_mount', return_value=mount), \
             patch.object(retire, 'VerifiedCgroupReader', return_value=lambda path:True), \
             patch.object(retire.subprocess, 'run', return_value=result) as run:
            with self.assertRaises(SupervisionError):
                await retire.cold(fence, mount)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][1], 'show')

    async def test_two_fence_observations_and_only_readonly_commands_on_cold_success(self):
        fence, mount = object(), object()
        def command(args, **kwargs):
            output = (b'ActiveState=inactive\nMainPID=0\nControlPID=0\nJob=\n'
                      if args[1]=='show' else b'')
            return SimpleNamespace(stdout=output, stderr=b'')
        probe = MagicMock()
        probe.__enter__.return_value.connect_ex.return_value = errno.ECONNREFUSED
        with patch.object(retire, 'observe_fence', AsyncMock(return_value=fence)) as observe, \
             patch.object(retire, 'observe_mount', return_value=mount), \
             patch.object(retire, 'VerifiedCgroupReader', return_value=lambda path:False), \
             patch.object(retire.subprocess, 'run', side_effect=command) as run, \
             patch.object(retire.socket, 'socket', return_value=probe):
            await retire.cold(fence, mount)
        self.assertEqual(observe.await_count, 2)
        self.assertTrue(all(call.args[0][1] in ('show','list-jobs') for call in run.call_args_list))
