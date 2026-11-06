"""Synthetic mount/proc evidence only; never mounts or controls real services."""
from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.cgroup_mount import CgroupMount, VerifiedCgroupReader, _read_proc
from coordinator.supervision import SupervisionError


class MountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-mount-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.group = self.root / 'system.slice/ollama.service'
        self.group.mkdir(parents=True)
        (self.group / 'cgroup.events').write_text('populated 0\nfrozen 0\n')
        status = self.root.stat()
        self.identity = CgroupMount(42, os.major(status.st_dev), os.minor(status.st_dev), status.st_ino)
        self.reader = VerifiedCgroupReader(str(self.root), expected=self.identity)
        self.mountinfo = self.mount_line()
        self.fdinfo = 'pos:\t0\nflags:\t0100000\nmnt_id:\t42\nino:\t1\n'
        self.calls = []
        self.override = None
        self.mock = patch('coordinator.cgroup_mount._read_proc', side_effect=self.evidence)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def mount_line(self, *, mount_id=42, root='/', point=None, fs='cgroup2', device=None):
        point = str(self.root) if point is None else point
        point = point.replace('\\', '\\134').replace(' ', '\\040')
        device = device or f'{self.identity.device_major}:{self.identity.device_minor}'
        return f'{mount_id} 1 {device} {root} {point} rw,nosuid - {fs} cgroup rw\n'

    def evidence(self, path, limit):
        self.calls.append(path)
        if self.override:
            result = self.override(path)
            if result is not None:
                return result
        return self.mountinfo if path.endswith('mountinfo') else self.fdinfo

    def test_construction_no_io_and_valid_population_and_disappearance(self):
        self.assertEqual(self.calls, [])
        self.assertFalse(self.reader('/system.slice/ollama.service'))
        (self.group / 'cgroup.events').write_text('populated 1\n')
        self.assertTrue(self.reader('/system.slice/ollama.service'))
        self.assertIsNone(self.reader('/missing.service'))
        self.assertEqual(self.calls.count('/proc/self/mountinfo'), 6)

    def test_wrong_or_stacked_mounts_rejected(self):
        mutations = [self.mount_line(fs='tmpfs'), self.mount_line(mount_id=43),
                     self.mount_line(root='/delegated'), self.mount_line(point='/elsewhere'),
                     self.mount_line(device='999:999'), '', 'malformed\n',
                     self.mount_line() + self.mount_line(mount_id=43),
                     self.mount_line() + self.mount_line(point='/other'),
                     self.mount_line(point='/bad\\escape')]
        for value in mutations:
            with self.subTest(value=value):
                self.mountinfo = value
                with self.assertRaises(SupervisionError):
                    self.reader('/system.slice/ollama.service')

    def test_explicit_identity_types_and_root_required(self):
        for changes in [dict(mount_id=True), dict(mount_id=0), dict(root_inode=0),
                        dict(device_minor=-1), dict(device_major='0')]:
            with self.subTest(changes=changes), self.assertRaises(SupervisionError):
                VerifiedCgroupReader(str(self.root), expected=replace(self.identity, **changes))
        with self.assertRaises(SupervisionError):
            VerifiedCgroupReader('/', expected=self.identity)
        with self.assertRaises(SupervisionError):
            VerifiedCgroupReader(str(self.root), expected=None)

    def test_root_inode_and_descriptor_device_mismatch(self):
        original = self.identity
        for identity in [replace(original, root_inode=original.root_inode + 1),
                         replace(original, device_major=original.device_major + 1)]:
            self.identity = identity
            self.mountinfo = self.mount_line()
            with self.assertRaises(SupervisionError):
                VerifiedCgroupReader(str(self.root), expected=identity)('/system.slice/ollama.service')

    def test_fdinfo_missing_duplicate_or_wrong_mount_fails(self):
        for value in ['', 'mnt_id:\t43\n', 'mnt_id:\t42\nmnt_id:\t42\n',
                      'mnt_id:\t+42\n', 'mnt_id:\t0\n']:
            self.fdinfo = value
            with self.subTest(value=value), self.assertRaises(SupervisionError):
                self.reader('/system.slice/ollama.service')

    def test_each_descendant_and_events_descriptor_checked(self):
        # root, system.slice, unit directory, then cgroup.events.
        for reject in (2, 3, 4):
            seen = 0
            def changed(path):
                nonlocal seen
                if '/fdinfo/' in path:
                    seen += 1
                    if seen == reject:
                        return 'mnt_id:\t99\n'
            self.override = changed
            with self.subTest(reject=reject), self.assertRaises(SupervisionError):
                self.reader('/system.slice/ollama.service')
            self.assertEqual(seen, reject)

    def test_mount_replaced_during_read_or_disappearance_fails(self):
        for group in ('/system.slice/ollama.service', '/missing.service'):
            seen = 0
            def changed(path):
                nonlocal seen
                if path.endswith('mountinfo'):
                    seen += 1
                    if seen == 2:
                        return self.mount_line(mount_id=43)
            self.override = changed
            with self.subTest(group=group), self.assertRaises(SupervisionError):
                self.reader(group)

    def test_escaped_mountpoint(self):
        spaced = self.root / 'space dir'
        spaced.mkdir()
        (spaced / 'unit.service').mkdir()
        (spaced / 'unit.service/cgroup.events').write_text('populated 0\n')
        self.identity = replace(self.identity, root_inode=spaced.stat().st_ino)
        self.mountinfo = self.mount_line(point=str(spaced))
        self.assertFalse(VerifiedCgroupReader(str(spaced), expected=self.identity)('/unit.service'))

    def test_symlinks_and_repeated_failures_do_not_leak_descriptors(self):
        (self.root / 'alias.service').symlink_to(self.group, target_is_directory=True)
        before = len(os.listdir('/proc/self/fd'))
        for _ in range(30):
            with self.assertRaises(SupervisionError):
                self.reader('/alias.service')
            self.fdinfo = 'mnt_id:\t99\n'
            with self.assertRaises(SupervisionError):
                self.reader('/missing.service')
            self.fdinfo = 'mnt_id:\t42\n'
        self.assertEqual(before, len(os.listdir('/proc/self/fd')))


class ProcReadTests(unittest.TestCase):
    def test_bounded_ascii_regular_fixture_and_symlink_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'evidence'
            path.write_bytes(b'1234')
            self.assertEqual(_read_proc(str(path), 4), '1234')
            for data in (b'12345', b'\xff'):
                path.write_bytes(data)
                with self.assertRaises(SupervisionError):
                    _read_proc(str(path), 4)
            link = Path(temp) / 'link'
            link.symlink_to(path)
            with self.assertRaises(SupervisionError):
                _read_proc(str(link), 4)
            with self.assertRaises(SupervisionError):
                _read_proc(str(Path(temp) / 'missing'), 4)


if __name__ == '__main__':
    unittest.main()
