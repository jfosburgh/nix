"""Temporary local files only. No systemd transport or service mutations."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.job_journal import JobIntent, JobJournal
from coordinator.bus_identity import BusIdentity
from coordinator.supervision import SupervisionError


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-jobs-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'jobs.jsonl'
        self.nonce = 'a' * 32
        self.journal = self.new()
        self.addCleanup(self.journal.close)

    def new(self, **changes):
        options = dict(unit='ollama.service', identity='synthetic-fingerprint', boot_id='1' * 32,
                       bus_identity=BusIdentity('a' * 32, ':1.99'))
        options.update(changes)
        return JobJournal(str(self.path), **options)

    def reopen(self):
        self.journal.close()
        self.journal.open()
        return self.journal.pending

    def initialize(self):
        self.journal.open(initialize=True)
        self.assertIsNone(self.journal.pending)

    def test_construction_no_io_missing_not_implicitly_initialized(self):
        self.assertFalse(self.path.exists())
        with self.assertRaises(SupervisionError):
            self.journal.open()
        self.assertFalse(self.path.exists())
        self.initialize()
        self.journal.close()
        with self.assertRaises(SupervisionError):
            self.journal.open(initialize=True)
        self.assertIsNone(self.reopen())

    def test_full_correlated_sequence_persists_each_phase(self):
        self.initialize()
        intent = self.journal.begin('stop', self.nonce)
        self.assertEqual(self.reopen(), intent)
        intent = self.journal.submitted(intent, 123)
        self.assertEqual(self.reopen(), intent)
        intent = self.journal.completed(intent, 'done')
        self.assertEqual(self.reopen(), intent)  # Even done remains unresolved.
        self.journal.acknowledge(intent)
        self.assertIsNone(self.reopen())
        next_intent = self.journal.begin('start', 'b' * 32)
        self.assertEqual(self.reopen(), next_intent)

    def test_unacknowledged_intent_blocks_new_work_after_restart(self):
        self.initialize()
        intent = self.journal.begin('stop', self.nonce)
        for phase in ('intent', 'submitted', 'completed'):
            if phase == 'submitted':
                intent = self.journal.submitted(intent, 12)
            elif phase == 'completed':
                intent = self.journal.completed(intent, 'failed')
            self.assertEqual(self.reopen(), intent)
            with self.subTest(phase=phase), self.assertRaises(SupervisionError):
                self.journal.begin('start', 'c' * 32)

    def test_write_and_file_fsync_happen_before_state_publication(self):
        self.initialize()
        original = os.fsync
        observed = []
        # pending() detects size change while commit is in progress; inspect
        # private state here instead of requesting a concurrent snapshot.
        def sync(fd):
            observed.append(self.journal._pending)
            original(fd)
        with patch('coordinator.job_journal.os.fsync', side_effect=sync):
            intent = self.journal.begin('stop', self.nonce)
        self.assertEqual(observed, [None])
        self.assertEqual(self.journal.pending, intent)

    def test_initialization_fsyncs_file_then_directory(self):
        original = os.fsync
        calls = []
        def sync(fd):
            calls.append(fd)
            original(fd)
        with patch('coordinator.job_journal.os.fsync', side_effect=sync):
            self.initialize()
        self.assertEqual(calls, [self.journal._fd, self.journal._directory])

    def test_lock_excludes_second_instance_and_is_released_on_close(self):
        self.initialize()
        second = self.new()
        self.addCleanup(second.close)
        with self.assertRaises(SupervisionError):
            second.open()
        self.journal.close()
        second.open()
        self.assertIsNone(second.pending)

    def test_invalid_metadata_and_mutation_order_do_not_append(self):
        self.initialize()
        before = self.path.read_bytes()
        for action, nonce in [('restart', self.nonce), ('stop', 'invalid'), ('stop', None)]:
            with self.subTest(action=action, nonce=nonce), self.assertRaises(SupervisionError):
                self.journal.begin(action, nonce)
            self.assertEqual(self.path.read_bytes(), before)
        intent = self.journal.begin('stop', self.nonce)
        for action in [lambda: self.journal.completed(intent, 'done'),
                       lambda: self.journal.acknowledge(intent),
                       lambda: self.journal.submitted(replace(intent, nonce='b' * 32), 1),
                       lambda: self.journal.submitted(intent, True),
                       lambda: self.journal.submitted(intent, 0),
                       lambda: self.journal.submitted(intent, 2**32),
                       lambda: self.journal.acknowledge(None)]:
            before = self.path.read_bytes()
            with self.assertRaises(SupervisionError):
                action()
            self.assertEqual(self.path.read_bytes(), before)
        submitted = self.journal.submitted(intent, 1)
        with self.assertRaises(SupervisionError):
            self.journal.completed(submitted, 'unknown')
        done = self.journal.completed(submitted, 'done')
        with self.assertRaises(SupervisionError):
            self.journal.completed(submitted, 'done')
        self.journal.acknowledge(done)
        with self.assertRaises(SupervisionError):
            self.journal.begin('stop', self.nonce)  # Nonces cannot be reused.
        self.assertIsNone(self.reopen())
        with self.assertRaises(SupervisionError):
            self.journal.begin('start', self.nonce)

    def test_failed_write_or_sync_poison_instance_and_preserve_uncertainty(self):
        for operation in ('write', 'fsync'):
            with self.subTest(operation=operation):
                if not self.path.exists():
                    self.initialize()
                with patch(f'coordinator.job_journal.os.{operation}', side_effect=OSError('private path')):
                    with self.assertRaises(SupervisionError) as error:
                        self.journal.begin('stop', self.nonce)
                self.assertNotIn('private path', str(error.exception))
                with self.assertRaises(SupervisionError):
                    _ = self.journal.pending
                with self.assertRaises(SupervisionError):
                    self.journal.begin('start', 'b' * 32)
                # A write failure before writing leaves no intent; a failed sync
                # may leave one visible, but never silently grants job completion.
                recovered = self.reopen()
                if operation == 'fsync':
                    self.assertEqual(recovered, JobIntent(self.nonce, 'stop'))
                self.journal.close()
                self.path.unlink()

    def test_partial_write_and_zero_write(self):
        self.initialize()
        original = os.write
        def short(fd, data):
            return original(fd, data[:3])
        with patch('coordinator.job_journal.os.write', side_effect=short):
            intent = self.journal.begin('stop', self.nonce)
        self.assertEqual(self.reopen(), intent)
        self.journal.close()
        self.path.unlink()
        self.initialize()
        with patch('coordinator.job_journal.os.write', return_value=0):
            with self.assertRaises(SupervisionError):
                self.journal.begin('stop', self.nonce)
        self.assertIsNone(self.reopen())

    def test_process_exit_preserves_pending_intent_and_releases_lock(self):
        self.initialize()
        self.journal.close()
        source = str(Path(__file__).resolve().parents[1])
        code = '''
import os, sys
sys.path.insert(0, sys.argv[1])
from coordinator.job_journal import JobJournal
from coordinator.bus_identity import BusIdentity
journal = JobJournal(sys.argv[2], unit='ollama.service',
                     identity='synthetic-fingerprint', boot_id='1' * 32,
                     bus_identity=BusIdentity('a' * 32, ':1.99')).open()
journal.begin('stop', 'a' * 32)
os._exit(23)
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, source, str(self.path)],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(self.reopen(), JobIntent(self.nonce, 'stop'))
        with self.assertRaises(SupervisionError):
            self.journal.begin('start', 'b' * 32)

    def test_interrupted_partial_append_is_not_repaired_or_reused(self):
        self.initialize()
        original = os.write
        calls = 0
        def interrupted(fd, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                return original(fd, data[:5])
            raise KeyboardInterrupt()
        with patch('coordinator.job_journal.os.write', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.journal.begin('stop', self.nonce)
        with self.assertRaises(SupervisionError):
            _ = self.journal.pending
        broken = self.path.read_bytes()
        with self.assertRaises(SupervisionError):
            self.reopen()
        self.assertEqual(self.path.read_bytes(), broken)

    def test_torn_tail_and_invalid_replay_fail_closed_without_repair(self):
        self.initialize()
        header = self.path.read_bytes()
        self.journal.close()
        invalid = [b'', header[:-1], header + b'{', header + b'{}\n',
                   header + b'\xff\n', header + b'{"event":"begin","event":"begin"}\n',
                   header + b'x' * 2049 + b'\n', header * 2]
        for data in invalid:
            self.path.write_bytes(data)
            with self.subTest(data=data[:100]), self.assertRaises(SupervisionError):
                self.journal.open()
            self.assertEqual(self.path.read_bytes(), data)

    def test_replay_rejects_wrong_deployment_and_unordered_events(self):
        self.initialize()
        header = self.path.read_bytes()
        self.journal.close()
        for change in (dict(unit='strata.service'), dict(identity='other'), dict(boot_id='2' * 32),
                       dict(bus_identity=BusIdentity('b' * 32, ':1.99')),
                       dict(bus_identity=BusIdentity('a' * 32, ':1.100'))):
            other = self.new(**change)
            self.addCleanup(other.close)
            with self.assertRaises(SupervisionError):
                other.open()
        event = dict(event='submitted', intent=dict(nonce=self.nonce, action='stop', job_id=1, result=None))
        self.path.write_bytes(header + json.dumps(event).encode() + b'\n')
        with self.assertRaises(SupervisionError):
            self.journal.open()

    def test_size_bound_and_external_modification_block_access(self):
        self.initialize()
        with patch.object(self.journal, 'MAX_BYTES', self.path.stat().st_size + 1):
            with self.assertRaises(SupervisionError):
                self.journal.begin('stop', self.nonce)
        self.reopen()
        with self.path.open('ab') as out:
            out.write(b'corruption\n')
        with self.assertRaises(SupervisionError):
            _ = self.journal.pending
        with self.assertRaises(SupervisionError):
            self.reopen()

    def test_replaced_inode_symlink_hardlink_and_special_files_rejected(self):
        self.initialize()
        moved = self.root / 'old'
        self.path.rename(moved)
        self.path.write_bytes(moved.read_bytes())
        self.path.chmod(0o600)
        with self.assertRaises(SupervisionError):
            _ = self.journal.pending
        self.journal.close()
        self.path.unlink()
        self.path.symlink_to(moved)
        with self.assertRaises(SupervisionError):
            self.journal.open()
        self.path.unlink()
        os.link(moved, self.path)
        with self.assertRaises(SupervisionError):
            self.journal.open()
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(SupervisionError):
            self.journal.open()

    def test_permissions_and_untrusted_directory_are_rejected(self):
        self.initialize()
        self.journal.close()
        for mode in (0o644, 0o400, 0o660):
            self.path.chmod(mode)
            with self.subTest(mode=mode), self.assertRaises(SupervisionError):
                self.journal.open()
        self.path.chmod(0o600)
        try:
            for mode in (0o755, 0o770, 0o777):
                self.root.chmod(mode)
                with self.subTest(mode=mode), self.assertRaises(SupervisionError):
                    self.journal.open()
        finally:
            self.root.chmod(0o700)
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(SupervisionError):
            JobJournal(str(alias / 'jobs.jsonl'), unit='ollama.service', identity='test',
                       boot_id='1' * 32, bus_identity=BusIdentity('a' * 32, ':1.99')).open()

    def test_old_unpinned_journal_is_never_silently_migrated_or_repaired(self):
        self.initialize()
        self.journal.begin('stop', self.nonce)
        self.journal.close()
        lines = self.path.read_bytes().splitlines()
        header = json.loads(lines[0])
        self.assertEqual(header['version'], 2)
        self.assertEqual(header['bus_id'], 'a' * 32)
        self.assertEqual(header['manager_owner'], ':1.99')
        header['version'] = 1
        del header['bus_id'], header['manager_owner']
        old = json.dumps(header).encode() + b'\n' + b'\n'.join(lines[1:]) + b'\n'
        self.path.write_bytes(old)
        with self.assertRaises(SupervisionError):
            self.journal.open()
        self.assertEqual(self.path.read_bytes(), old)

    def test_bus_pin_is_required_before_any_filesystem_operations(self):
        for identity in (None, {'bus_id': 'a' * 32, 'manager_owner': ':1.99'}):
            with self.subTest(identity=identity), self.assertRaises(SupervisionError):
                self.new(bus_identity=identity)
        self.assertFalse(self.path.exists())

    def test_failed_open_and_repeated_reads_do_not_leak_descriptors(self):
        self.initialize()
        self.journal.close()
        before = len(os.listdir('/proc/self/fd'))
        for _ in range(30):
            self.journal.open()
            self.assertIsNone(self.journal.pending)
            self.journal.close()
            other = self.new(identity='wrong')
            with self.assertRaises(SupervisionError):
                other.open()
        self.assertEqual(before, len(os.listdir('/proc/self/fd')))


if __name__ == '__main__':
    unittest.main()
