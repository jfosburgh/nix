"""Synthetic sysfs/procfs fixtures; never reads real hardware or changes allocations."""
import asyncio
from pathlib import Path
import sys
import tempfile
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.memory import (MemoryAdmissionError, MemoryRequirement, MemorySnapshot,
                                read_linux_memory, wait_for_memory)


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.device = Path(self.tmp.name) / 'gpu'
        self.device.mkdir()
        self.meminfo = Path(self.tmp.name) / 'meminfo'
        self.write('vendor', '0x1002\n')
        self.write('mem_info_vram_total', '16000\n')
        self.write('mem_info_vram_used', '2000\n')
        self.meminfo.write_text('MemTotal:       32000 kB\nMemFree: 500 kB\nMemAvailable:   24000 kB\n')

    def write(self, name, value):
        (self.device / name).write_text(value)

    def read(self):
        return read_linux_memory(self.device, self.meminfo)

    def test_explicit_gpu_and_memavailable_units(self):
        sample = self.read()
        self.assertEqual(sample.vram_free, 14000)
        self.assertEqual(sample.ram_available, 24000 * 1024)
        self.assertEqual(sample.ram_total, 32000 * 1024)
        self.assertGreaterEqual(time.monotonic(), sample.sampled_at)

    def test_telemetry_missing_or_non_amd_fails_closed(self):
        self.write('vendor', '0x10de')
        with self.assertRaises(MemoryAdmissionError):
            self.read()
        self.write('vendor', '0x1002')
        (self.device / 'mem_info_vram_used').unlink()
        with self.assertRaises(MemoryAdmissionError):
            self.read()

    def test_invalid_gpu_numbers_and_accounting_rejected(self):
        for value in ('-1', 'nan', '16001', 'true'):
            self.write('mem_info_vram_used', value)
            with self.assertRaises(MemoryAdmissionError):
                self.read()

    def test_no_fallback_to_memfree_or_invalid_units(self):
        for content in ['MemTotal: 32000 kB\nMemFree: 24000 kB\n',
                        'MemTotal: 32000 kB\nMemAvailable: 24 MB\n',
                        'MemTotal: 32000 kB\nMemAvailable: 33000 kB\n',
                        'MemTotal: 32000 kB\nMemAvailable: 24000 kB\nMemAvailable: 24000 kB\n']:
            self.meminfo.write_text(content)
            with self.assertRaises(MemoryAdmissionError):
                self.read()

    async def test_admission_checks_both_ram_and_gpu(self):
        sample = await wait_for_memory(self.read, MemoryRequirement(14000, 24000 * 1024), timeout=0.1)
        self.assertEqual(sample.vram_free, 14000)
        for requirement in [MemoryRequirement(14001, 1), MemoryRequirement(1, 24001 * 1024)]:
            with self.assertRaisesRegex(MemoryAdmissionError, 'deadline'):
                await wait_for_memory(self.read, requirement, timeout=0.005, poll_interval=0.001)

    async def test_release_settling_polls_new_samples(self):
        calls = []
        def reader():
            calls.append(1)
            return MemorySnapshot(16000, 15000 if len(calls) == 1 else 2000,
                                  32000, 24000, time.monotonic())
        sample = await wait_for_memory(reader, MemoryRequirement(14000, 24000),
                                       timeout=0.1, poll_interval=0.001)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sample.vram_free, 14000)

    async def test_stale_sample_is_not_admission(self):
        def reader():
            return MemorySnapshot(16000, 0, 32000, 32000, time.monotonic() - 5)
        with self.assertRaisesRegex(MemoryAdmissionError, 'Stale'):
            await wait_for_memory(reader, MemoryRequirement(1, 1), timeout=0.1)

    async def test_unavailable_telemetry_is_not_a_waiting_success(self):
        self.meminfo.unlink()
        with self.assertRaisesRegex(MemoryAdmissionError, 'unavailable'):
            await wait_for_memory(self.read, MemoryRequirement(1, 1), timeout=0.1)

    async def test_memory_wait_is_cancellable(self):
        task = asyncio.create_task(wait_for_memory(self.read, MemoryRequirement(16000, 1),
                                                   timeout=60, poll_interval=10))
        await asyncio.sleep(0.005)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    def test_no_guessed_or_nonpositive_requirements(self):
        for values in [(0, 1), (1, -1), (True, 1), (1.5, 1)]:
            with self.assertRaises(ValueError):
                MemoryRequirement(*values)


if __name__ == '__main__':
    unittest.main()
