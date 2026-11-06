"""Production boundary with data/telemetry fixtures only, never real backends."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.calibrate import derive_budget
from coordinator.memory import MemorySnapshot
from coordinator.operator_files import read_operator_file
from coordinator.production import CalibratedMemory, load_calibrated
from coordinator.supervision import SupervisionError
from test_config import fixture


def artifacts():
    config = fixture()
    config['backends'][1]['input_policy'] = 'native-reject-trial'
    template = dict(configuration=copy.deepcopy(config), deployment='a'*64,
                    device='/sys/bus/pci/devices/0000:08:00.0')
    observations = {}
    for backend in template['configuration']['backends']:
        targets = [backend] if backend['adapter'] == 'strata' else backend['models'].values()
        for target in targets:
            observations[backend['id']] = dict(cold=target['cold'], resident=target['resident'])
            target['cold'] = target['resident'] = None
    raw = json.dumps(template).encode()
    envelope = dict(template_sha256=hashlib.sha256(raw).hexdigest(), configuration=config,
                    calibration=dict(device=template['device'], profile=config['profile'],
                                     deployment=template['deployment'], native_oversize_rejection=True,
                                     measured_at_unix=123456, observations=observations))
    return template, raw, envelope


class CalibrationTests(unittest.TestCase):
    def test_measured_configuration_is_bound_to_template_device_and_rejection(self):
        template, raw, value = artifacts()
        config = load_calibrated(json.dumps(value).encode(), raw, template['device'])
        self.assertEqual(config.backends[1].input_policy, 'native-reject-trial')
        self.assertEqual(config.backends[0].cold.vram_free, 1234)

    def test_tampering_wrong_profile_device_identity_and_missing_proof_refused(self):
        template, raw, original = artifacts()
        mutations = [lambda v: v.update(template_sha256='bad'),
                     lambda v: v['configuration']['backends'][0].update(upstream='http://127.0.0.1:9999'),
                     lambda v: v['configuration']['backends'][0]['cold'].update(vram_free=1),
                     lambda v: v['calibration'].update(deployment='other'),
                     lambda v: v['calibration'].update(profile='headless'),
                     lambda v: v['calibration'].update(native_oversize_rejection=False),
                     lambda v: v['calibration'].update(native_oversize_rejection=1),
                     lambda v: v['calibration'].update(measured_at_unix=True),
                     lambda v: v['calibration']['observations'].update(extra={})]
        for mutate in mutations:
            value = copy.deepcopy(original)
            # Break fixture aliasing: real JSON serialization has no shared objects.
            value = json.loads(json.dumps(value))
            mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, KeyError)):
                load_calibrated(json.dumps(value).encode(), raw, template['device'])
        with self.assertRaises(ValueError):
            load_calibrated(json.dumps(original).encode(), raw, '/wrong/device')

    def test_budgets_derive_from_peaks_plus_explicit_margins(self):
        gib = 1024**3
        baseline = MemorySnapshot(16*gib, gib, 32*gib, 28*gib, time.monotonic())
        samples = [MemorySnapshot(16*gib, 13*gib, 32*gib, 18*gib, time.monotonic())]
        budget = derive_budget(baseline, samples)
        self.assertEqual(budget['cold']['vram_free'], 12*gib + gib//2)
        self.assertEqual(budget['cold']['ram_available'], 16*gib)
        self.assertEqual(budget['resident']['ram_available'], 6*gib)
        with self.assertRaises(SupervisionError):
            derive_budget(baseline, [])
        with self.assertRaises(SupervisionError):
            derive_budget(baseline, [MemorySnapshot(16*gib, 16*gib, 32*gib, 2*gib, time.monotonic())])


class CalibrationDiagnosticTests(unittest.TestCase):
    def sample(self, *, used=8, available=8):
        gib = 1024**3
        return MemorySnapshot(16*gib, used*gib, 32*gib, available*gib, time.monotonic())

    def test_ram_failure_names_resource_and_keeps_both_telemetry_budgets(self):
        with self.assertRaises(SupervisionError) as caught:
            derive_budget(self.sample(used=1, available=28), [self.sample(available=5)])
        message = str(caught.exception)
        self.assertIn('availability (RAM)', message)
        self.assertIn('RAM cold required=29696.0 MiB', message)
        self.assertIn('baseline available=28672.0 MiB', message)
        self.assertIn('minimum observed available=5120.0 MiB', message)
        self.assertIn('margin=6144 MiB', message)
        self.assertIn('VRAM cold required=7680.0 MiB', message)
        self.assertIn('margin=512 MiB', message)

    def test_vram_failure_names_resource_and_preserves_original_gate(self):
        with self.assertRaises(SupervisionError) as caught:
            derive_budget(self.sample(used=1, available=28), [self.sample(used=16)])
        self.assertIn('availability (VRAM)', str(caught.exception))
        self.assertIn('baseline free=15360.0 MiB', str(caught.exception))
        self.assertIn('peak used=16384.0 MiB', str(caught.exception))

    def test_both_failed_resources_are_reported(self):
        with self.assertRaisesRegex(SupervisionError, r'availability \(VRAM, RAM\)'):
            derive_budget(self.sample(used=1, available=28), [self.sample(used=16, available=5)])

    def test_approved_two_gib_floor_passes_and_is_recorded(self):
        gib = 1024**3
        result = derive_budget(self.sample(used=1, available=28),
                               [self.sample(available=2)], ram_headroom=2*gib)
        self.assertEqual(result['cold']['ram_available'], 28*gib)
        self.assertEqual(result['resident']['ram_available'], 2*gib)
        self.assertEqual(result['ram_headroom_bytes'], 2*gib)
        self.assertEqual(result['resident']['vram_free'], gib//2)
        with self.assertRaisesRegex(SupervisionError, 'margin=2048 MiB'):
            derive_budget(self.sample(used=1, available=28),
                          [self.sample(available=1)], ram_headroom=2*gib)

    def test_default_stays_six_gib_and_unapproved_floors_refused(self):
        gib = 1024**3
        with self.assertRaisesRegex(SupervisionError, 'availability \\(RAM\\)'):
            derive_budget(self.sample(used=1, available=28), [self.sample(available=2)])
        for value in (0, 1*gib, 3*gib, True, 2.0*gib):
            with self.subTest(value=value), self.assertRaises(SupervisionError):
                derive_budget(self.sample(), [self.sample()], ram_headroom=value)

    def test_exact_margin_boundary_passes_without_relaxation(self):
        gib = 1024**3
        baseline = self.sample(used=1, available=28)
        sample = MemorySnapshot(16*gib, 16*gib-gib//2, 32*gib, 6*gib, time.monotonic())
        result = derive_budget(baseline, [sample])
        self.assertEqual(result['cold']['vram_free'], baseline.vram_free)
        self.assertEqual(result['cold']['ram_available'], baseline.ram_available)
        self.assertEqual(result['resident']['ram_available'], 6*gib)
        self.assertEqual(result['resident']['vram_free'], gib//2)


class MemoryWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_exact_profile_budgets_reach_real_memory_waiter(self):
        template, raw, value = artifacts()
        config = load_calibrated(json.dumps(value).encode(), raw, template['device'])
        memory = CalibratedMemory(template['device'])
        with patch('coordinator.production.wait_for_memory') as wait:
            await memory.check(config.backends[0], model=config.backends[0].model,
                               context=131072, resident=False)
            self.assertEqual(wait.call_args.args[1].vram_free, 1234)
            await memory.check(config.backends[1], model='small', context=8192, resident=True)
            self.assertEqual(wait.await_count, 2)
            with self.assertRaises(ValueError):
                await memory.check(config.backends[1], model='small', context=4096, resident=False)
            with self.assertRaises(ValueError):
                await memory.check(config.backends[0], model='wrong', context=131072, resident=False)
            self.assertEqual(wait.await_count, 2)


class OperatorFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-operator-file-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.file = self.root / 'configuration'
        self.file.write_bytes(b'fixture')
        self.file.chmod(0o600)

    def test_bounded_owner_file_descriptor_cleanup(self):
        before = len(os.listdir('/proc/self/fd'))
        for _ in range(20):
            self.assertEqual(read_operator_file(str(self.file), owner=os.geteuid()), b'fixture')
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)
        with self.assertRaises(SupervisionError):
            read_operator_file(str(self.file), owner=os.geteuid(), limit=2)

    def test_symlinks_world_writes_wrong_owner_and_special_files_refused(self):
        self.file.chmod(0o666)
        with self.assertRaises(SupervisionError):
            read_operator_file(str(self.file), owner=os.geteuid())
        self.file.unlink()
        self.file.symlink_to('/etc/passwd')
        with self.assertRaises(SupervisionError):
            read_operator_file(str(self.file), owner=os.geteuid())
        self.file.unlink()
        os.mkfifo(self.file)
        with self.assertRaises(SupervisionError):
            read_operator_file(str(self.file), owner=os.geteuid())


if __name__ == '__main__':
    unittest.main()
