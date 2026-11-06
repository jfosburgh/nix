"""Synthetic root metadata / fake bus only, never privileged provisioning."""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.cgroup_mount import CgroupMount
from coordinator.provisioning import load_pins, observe_fence, write_pins
from coordinator.supervision import SupervisionError
from test_systemd_jobs import FakeBus, FENCE


class FenceObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_observation_fixed_bus_no_mutating_methods(self):
        bus = FakeBus()
        with patch('coordinator.provisioning.MessageBus', return_value=bus) as factory:
            self.assertEqual(await observe_fence(), FENCE)
        factory.assert_called_once_with(bus_address='unix:path=/run/dbus/system_bus_socket')
        self.assertTrue(bus.disconnected.is_set())
        self.assertFalse(any(m.member in ('StartUnit','StopUnit','Subscribe','LoadUnit','GetAll') for m in bus.calls))

    async def test_unsupported_version_refused_and_connection_closed(self):
        bus = FakeBus()
        bus.version = '263'
        with patch('coordinator.provisioning.MessageBus', return_value=bus):
            with self.assertRaises(SupervisionError):
                await observe_fence()
        self.assertTrue(bus.disconnected.is_set())


class PinFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-pins-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.mount = CgroupMount(123,0,28,1)
        self.boot = 'b'*32

    @contextmanager
    def fixture(self):
        actual_stat, actual_fstat = os.stat, os.fstat
        def root_info(info):
            fields = ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
            return SimpleNamespace(st_uid=0, **{k:getattr(info,k) for k in fields})
        with patch('coordinator.provisioning._directory', side_effect=lambda path: os.open(
                self.root,os.O_RDONLY|os.O_DIRECTORY)), patch('coordinator.provisioning.boot_id',return_value=self.boot), patch(
                'coordinator.provisioning.os.fstat',side_effect=lambda fd:root_info(actual_fstat(fd))), patch(
                'coordinator.provisioning.os.stat',side_effect=lambda *a,**k:root_info(actual_stat(*a,**k))):
            yield

    def write(self):
        write_pins(str(self.root),deployment='a'*64,fence=FENCE,mount=self.mount)

    def test_exclusive_roundtrip_and_descriptor_cleanup(self):
        before=len(os.listdir('/proc/self/fd'))
        with self.fixture():
            self.write()
            self.assertEqual(load_pins(str(self.root),deployment='a'*64),(FENCE,self.mount,self.boot))
            with self.assertRaises(FileExistsError):
                self.write()
        self.assertEqual(len(os.listdir('/proc/self/fd')),before)

    def test_wrong_boot_deployment_malformed_duplicate_and_unsafe_metadata(self):
        with self.fixture():
            self.write()
            original=(self.root/'pins.json').read_bytes()
            value=json.loads(original)
            for changes in (dict(boot_id='c'*32),dict(deployment='wrong'),dict(units_load_usec=True),
                            dict(manager_version='263'),dict(mount=dict(mount_id=0,device_major=0,device_minor=28,root_inode=1))):
                altered={**value,**changes}
                (self.root/'pins.json').write_text(json.dumps(altered))
                with self.subTest(changes=changes),self.assertRaises(SupervisionError):
                    load_pins(str(self.root),deployment='a'*64)
            (self.root/'pins.json').write_bytes(b'{"version":1,"version":1}\n')
            with self.assertRaises(SupervisionError):
                load_pins(str(self.root),deployment='a'*64)
            (self.root/'pins.json').write_bytes(original)
            (self.root/'pins.json').chmod(0o644)
            with self.assertRaises(SupervisionError):
                load_pins(str(self.root),deployment='a'*64)

    def test_symlink_and_partial_pin_refused_without_repair(self):
        with self.fixture():
            self.write()
            path=self.root/'pins.json'
            path.write_bytes(b'{')
            with self.assertRaises(SupervisionError):
                load_pins(str(self.root),deployment='a'*64)
            self.assertEqual(path.read_bytes(),b'{')
            path.unlink()
            path.symlink_to('/etc/passwd')
            with self.assertRaises(SupervisionError):
                load_pins(str(self.root),deployment='a'*64)


if __name__ == '__main__':
    unittest.main()
