"""Synthetic store tree / proc-free deployment fixtures, no real unit access."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.deployment import StoreArtifact, StoreUnitDeployment, verify_artifact
from coordinator.supervision import SupervisionError

PIN = '/nix/store/' + 'a' * 32 + '-unit'
DATA = b'[Service]\nExecStart=/nix/store/example/bin/ollama serve\n'


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-store-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'nix/store').mkdir(parents=True)
        self.file = self.root / PIN.lstrip('/')
        self.file.write_bytes(DATA)
        self.file.chmod(0o444)
        self.artifact = StoreArtifact(PIN, hashlib.sha256(DATA).hexdigest())

    @contextmanager
    def fixture(self, *, owner=0):
        actual_open, actual_stat = os.open, os.fstat
        def opened(path, flags, *args, **kwargs):
            if path == '/':
                path = str(self.root)
            return actual_open(path, flags, *args, **kwargs)
        def info(fd):
            value = actual_stat(fd)
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            return SimpleNamespace(st_uid=owner, **{k: getattr(value, k) for k in fields})
        with patch('coordinator.deployment.os.open', side_effect=opened), patch(
                'coordinator.deployment.os.fstat', side_effect=info):
            yield

    def test_exact_immutable_root_file_and_descriptor_cleanup(self):
        before = len(os.listdir('/proc/self/fd'))
        with self.fixture():
            for _ in range(20):
                verify_artifact(self.artifact)
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)

    def test_wrong_hash_owner_writable_or_empty_refused(self):
        with self.fixture():
            with self.assertRaises(SupervisionError):
                verify_artifact(replace(self.artifact, sha256='f' * 64))
        with self.fixture(owner=1234), self.assertRaises(SupervisionError):
            verify_artifact(self.artifact)
        for mode, data in ((0o644, DATA), (0o444, b''), (0o444, b'x' * 65537)):
            self.file.chmod(0o644)
            self.file.write_bytes(data)
            self.file.chmod(mode)
            with self.fixture(), self.assertRaises(SupervisionError):
                verify_artifact(self.artifact)

    def test_symlink_file_directory_and_special_file_refused(self):
        self.file.unlink()
        self.file.symlink_to('/etc/passwd')
        with self.fixture(), self.assertRaises(SupervisionError):
            verify_artifact(self.artifact)
        self.file.unlink()
        os.mkfifo(self.file)
        with self.fixture(), self.assertRaises(SupervisionError):
            verify_artifact(self.artifact)
        self.file.unlink()
        (self.root / 'nix/store').rmdir()
        (self.root / 'nix/store').symlink_to('/tmp')
        with self.fixture(), self.assertRaises(SupervisionError):
            verify_artifact(self.artifact)

    def test_unsafe_directory_refused(self):
        (self.root / 'nix').chmod(0o777)
        with self.fixture(), self.assertRaises(SupervisionError):
            verify_artifact(self.artifact)

    def test_invalid_pins_before_io(self):
        for path in ('/tmp/a', PIN + '/../other', PIN + '/link/../file', PIN + '\n', '/nix/store/a'):
            with self.assertRaises(SupervisionError):
                StoreArtifact(path, 'a' * 64)
        with self.assertRaises(SupervisionError):
            StoreArtifact(PIN, 'bad')


class ManifestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.artifact = StoreArtifact(PIN, hashlib.sha256(DATA).hexdigest())
        self.manifest = StoreUnitDeployment('ollama.service', self.artifact, ())
        self.values = dict(FragmentPath='/etc/systemd/system/ollama.service', SourcePath='',
                           DropInPaths=(), NeedDaemonReload=False)
        self.session = SimpleNamespace(unit='ollama.service', unit_files=AsyncMock(return_value=self.values),
                                       check=AsyncMock())

    async def test_exact_manifest_and_fresh_fence(self):
        with patch('coordinator.deployment.Path.resolve', return_value=Path(PIN)), patch(
                'coordinator.deployment.verify_artifact') as verify:
            await self.manifest.check(self.session)
        verify.assert_called_once_with(self.artifact)
        self.session.check.assert_awaited_once()
        self.assertEqual(self.manifest.identity, self.manifest.identity)
        self.assertNotEqual(self.manifest.identity, replace(
            self.manifest, fragment=replace(self.artifact, sha256='f' * 64)).identity)

    async def test_wrong_unit_generator_dropin_reload_and_origin_refused(self):
        for key, value in dict(SourcePath='/etc/init.d/ollama', DropInPaths=('override.conf',),
                               NeedDaemonReload=True, FragmentPath='/wrong').items():
            original = self.values[key]
            self.values[key] = value
            with patch('coordinator.deployment.Path.resolve', return_value=Path('/nix/store/wrong')):
                with self.subTest(key=key), self.assertRaises(SupervisionError):
                    await self.manifest.check(self.session)
            self.values[key] = original
        self.session.unit = 'other.service'
        with self.assertRaises(SupervisionError):
            await self.manifest.check(self.session)

    async def test_artifact_failure_and_fence_change_propagate(self):
        with patch('coordinator.deployment.Path.resolve', return_value=Path(PIN)), patch(
                'coordinator.deployment.verify_artifact', side_effect=SupervisionError('fixture')):
            with self.assertRaises(SupervisionError):
                await self.manifest.check(self.session)
        self.session.check.side_effect = SupervisionError('fixture')
        with patch('coordinator.deployment.Path.resolve', return_value=Path(PIN)), patch(
                'coordinator.deployment.verify_artifact'):
            with self.assertRaises(SupervisionError):
                await self.manifest.check(self.session)

    async def test_invalid_manifests(self):
        for changes in (dict(unit='bad'), dict(configuration=[]),
                        dict(configuration=(self.artifact,)), dict(fragment=None)):
            with self.assertRaises(SupervisionError):
                replace(self.manifest, **changes)


if __name__ == '__main__':
    unittest.main()
