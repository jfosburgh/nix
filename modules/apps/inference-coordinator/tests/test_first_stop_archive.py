"""One-off recovery filesystem fixtures only; never run live root recovery."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('first_stop_archive',
    Path(__file__).resolve().parents[1] / 'scripts/archive-first-stop.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class ColdBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def check_boundary(self, *, active='inactive', populated=None, jobs=b'', connect=None):
        fence = SimpleNamespace(bus='fixture bus')
        mount = object()
        evidence = SimpleNamespace(active=active, main_pid=0, control_pid=0,
            job_id=0, control_group='', triggered_by=(), delegated=False,
            restart='no', kill_mode='control-group')
        inspector = MagicMock()
        inspector.inspect = AsyncMock(return_value=evidence)
        sock = MagicMock()
        sock.__enter__.return_value.connect_ex.return_value = (
            recovery.errno.ECONNREFUSED if connect is None else connect)
        with patch.object(recovery, 'observe_fence', AsyncMock(return_value=fence)), \
             patch.object(recovery, 'observe_mount', return_value=mount), \
             patch.object(recovery, 'SystemdInspector', return_value=inspector), \
             patch.object(recovery, 'VerifiedCgroupReader', return_value=lambda _: populated), \
             patch.object(recovery.subprocess, 'run', return_value=SimpleNamespace(stdout=jobs, stderr=b'')), \
             patch.object(recovery.socket, 'socket', return_value=sock), \
             patch.object(recovery.os.path, 'lexists', return_value=False):
            await recovery.cold_boundary(fence, mount)

    async def test_stopped_units_and_empty_recursive_cgroups_pass(self):
        await self.check_boundary()
        await self.check_boundary(populated=False, active='failed')

    async def test_active_unit_refused(self):
        with self.assertRaises(recovery.SupervisionError):
            await self.check_boundary(active='active')

    async def test_populated_cgroup_refused(self):
        with self.assertRaises(recovery.SupervisionError):
            await self.check_boundary(populated=True)

    async def test_outstanding_job_refused(self):
        with self.assertRaises(recovery.SupervisionError):
            await self.check_boundary(jobs=b'60919 ollama.service stop running')

    async def test_listener_or_network_check_uncertainty_refused(self):
        for code in (0, recovery.errno.EACCES, recovery.errno.ETIMEDOUT):
            with self.subTest(code=code), self.assertRaises(recovery.SupervisionError):
                await self.check_boundary(connect=code)


class FirstStopArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='first-stop-archive-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state_path = self.root / recovery.STATE
        self.state_path.mkdir(mode=0o700)
        (self.state_path / 'jobs.jsonl').write_bytes(recovery.EXPECTED)
        (self.state_path / 'pins.json').write_bytes(b'fixture pins\n')
        for path in self.state_path.iterdir():
            path.chmod(0o600)
        self.owner = os.geteuid()
        self.parent = os.open(self.root, recovery.FLAGS | os.O_DIRECTORY)
        self.addCleanup(os.close, self.parent)
        self.state = os.open(self.state_path, recovery.FLAGS | os.O_DIRECTORY)
        self.addCleanup(os.close, self.state)
        self.journal = recovery.locked_journal(self.state, owner=self.owner)
        self.addCleanup(os.close, self.journal)
        self.pins = os.open(self.state_path / 'pins.json', recovery.FLAGS)
        self.addCleanup(os.close, self.pins)

    def check(self):
        recovery.unchanged(self.parent, self.state, self.journal, self.pins, owner=self.owner)

    def archive(self):
        recovery.archive(self.parent, self.state, self.journal, self.pins, owner=self.owner)

    def test_check_does_not_mutate_and_archive_preserves_whole_directory_and_inode(self):
        before = self.state_path.stat().st_ino
        self.check()
        self.assertEqual(self.state_path.stat().st_ino, before)
        self.archive()
        archived = self.root / recovery.ARCHIVE / 'state'
        self.assertEqual(archived.stat().st_ino, before)
        self.assertEqual((archived / 'jobs.jsonl').read_bytes(), recovery.EXPECTED)
        self.assertEqual((archived / 'pins.json').read_bytes(), b'fixture pins\n')
        self.assertEqual(list(self.state_path.iterdir()), [])
        self.assertEqual(self.state_path.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / recovery.ARCHIVE).stat().st_mode & 0o777, 0o700)

    def test_exclusive_journal_lock_refuses_another_writer(self):
        with self.assertRaises(BlockingIOError):
            recovery.locked_journal(self.state, owner=self.owner)

    def test_changed_journal_refused_without_archive(self):
        (self.state_path / 'jobs.jsonl').write_bytes(recovery.EXPECTED + b'new event\n')
        with self.assertRaises(recovery.SupervisionError):
            self.archive()
        self.assertFalse((self.root / recovery.ARCHIVE).exists())

    def test_same_size_different_intent_refused(self):
        other = self.root / 'different'
        other.mkdir(mode=0o700)
        file = other / 'jobs.jsonl'
        file.write_bytes(recovery.EXPECTED.replace(b'60919', b'60920'))
        file.chmod(0o600)
        directory = os.open(other, recovery.FLAGS | os.O_DIRECTORY)
        try:
            with self.assertRaises(recovery.SupervisionError):
                recovery.locked_journal(directory, owner=self.owner)
        finally:
            os.close(directory)

    def test_replaced_pin_file_refused(self):
        (self.state_path / 'pins.json').unlink()
        (self.state_path / 'pins.json').write_bytes(b'fixture pins\n')
        (self.state_path / 'pins.json').chmod(0o600)
        with self.assertRaises(recovery.SupervisionError):
            self.archive()

    def test_extra_state_file_refused(self):
        (self.state_path / 'extra').touch()
        with self.assertRaises(recovery.SupervisionError):
            self.archive()

    def test_unsafe_permissions_and_hardlink_refused(self):
        (self.state_path / 'pins.json').chmod(0o644)
        with self.assertRaises(recovery.SupervisionError):
            self.archive()
        (self.state_path / 'pins.json').chmod(0o600)
        os.link(self.state_path / 'pins.json', self.root / 'hardlink')
        with self.assertRaises(recovery.SupervisionError):
            self.archive()

    def test_replaced_state_directory_refused(self):
        self.state_path.rename(self.root / 'other')
        self.state_path.mkdir(mode=0o700)
        with self.assertRaises(recovery.SupervisionError):
            self.archive()

    def test_existing_archive_or_dangling_symlink_never_overwritten(self):
        archive = self.root / recovery.ARCHIVE
        archive.symlink_to(self.root / 'nonexistent')
        with self.assertRaises(recovery.SupervisionError):
            self.archive()
        self.assertTrue(archive.is_symlink())
        self.assertTrue(self.state_path.exists())

    def test_fsync_failure_before_rename_preserves_state(self):
        with patch.object(recovery.os, 'fsync', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                self.archive()
        self.assertEqual((self.state_path / 'jobs.jsonl').read_bytes(), recovery.EXPECTED)
        self.assertFalse((self.root / recovery.ARCHIVE).exists())

    def test_failure_after_rename_preserves_archive_without_rollback(self):
        mkdir = os.mkdir
        def fail_fresh(path, *args, **kwargs):
            if path == recovery.STATE:
                raise OSError('fixture')
            return mkdir(path, *args, **kwargs)
        with patch.object(recovery.os, 'mkdir', side_effect=fail_fresh):
            with self.assertRaises(OSError):
                self.archive()
        self.assertFalse(self.state_path.exists())
        self.assertEqual((self.root / recovery.ARCHIVE / 'state/jobs.jsonl').read_bytes(), recovery.EXPECTED)

    def test_run_refuses_nonroot_before_any_filesystem_operation(self):
        import asyncio
        with patch.object(recovery.os, 'geteuid', return_value=1000):
            with self.assertRaises(recovery.SupervisionError):
                asyncio.run(recovery.run(True))
