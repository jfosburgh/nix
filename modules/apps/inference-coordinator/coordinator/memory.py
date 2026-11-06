"""Read-only AMD/Linux telemetry and bounded memory admission, not lifecycle proof.

Requirements must be supplied from measurements for the operation/residency state.
There are intentionally no guessed model budgets or deployable defaults here.
"""
import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Callable


class MemoryAdmissionError(Exception):
    """Missing/invalid telemetry or insufficient measured headroom."""


@dataclass(frozen=True)
class MemorySnapshot:
    vram_total: int
    vram_used: int
    ram_total: int
    ram_available: int
    sampled_at: float

    @property
    def vram_free(self) -> int:
        return self.vram_total - self.vram_used


@dataclass(frozen=True)
class MemoryRequirement:
    vram_free: int
    ram_available: int

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.vram_free, self.ram_available)):
            raise ValueError('Explicit positive byte thresholds required')


def _integer(path: Path) -> int:
    value = path.read_text().strip()
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError('Invalid sysfs integer')
    return int(value)


def read_linux_memory(device: Path, meminfo: Path = Path('/proc/meminfo')) -> MemorySnapshot:
    """Use one explicitly configured AMD PCI device, never sum/enumerate GPUs.

    Prefer a stable /sys/bus/pci/devices/<BDF> path to renumberable DRM card names.
    This is a point-in-time sample, not protection from later desktop allocations.
    """
    try:
        if (device / 'vendor').read_text().strip().lower() != '0x1002':
            raise ValueError('Selected device is not AMD')
        total = _integer(device / 'mem_info_vram_total')
        used = _integer(device / 'mem_info_vram_used')
        values = {}
        for line in meminfo.read_text().splitlines():
            if line.startswith(('MemTotal:', 'MemAvailable:')):
                match = re.fullmatch(r'(MemTotal|MemAvailable):\s+([0-9]+) kB', line)
                if not match or match[1] in values:
                    raise ValueError('Invalid meminfo field')
                values[match[1]] = int(match[2]) * 1024
        ram_total, available = values['MemTotal'], values['MemAvailable']
        if total <= 0 or used > total or ram_total <= 0 or available > ram_total:
            raise ValueError('Inconsistent memory telemetry')
        return MemorySnapshot(total, used, ram_total, available, time.monotonic())
    except (OSError, ValueError, KeyError):
        raise MemoryAdmissionError('Required AMD/system memory telemetry unavailable or invalid') from None


async def wait_for_memory(reader: Callable[[], MemorySnapshot], requirement: MemoryRequirement,
                          *, timeout: float, poll_interval: float = 0.25,
                          max_sample_age: float = 1) -> MemorySnapshot:
    """Allow bounded allocation-release settling. Missing/stale telemetry fails closed.

    Invoke only after lifecycle release proof when handing ownership over. A
    resident-model check instead needs a separately calibrated headroom budget.
    """
    if min(timeout, poll_interval, max_sample_age) <= 0:
        raise ValueError('Positive memory admission deadlines required')
    try:
        async with asyncio.timeout(timeout):
            while True:
                snapshot = await asyncio.to_thread(reader)
                age = time.monotonic() - snapshot.sampled_at
                if (not 0 <= age <= max_sample_age or snapshot.vram_total <= 0
                        or not 0 <= snapshot.vram_used <= snapshot.vram_total
                        or snapshot.ram_total <= 0 or not 0 <= snapshot.ram_available <= snapshot.ram_total):
                    raise MemoryAdmissionError('Stale or inconsistent memory sample')
                if (snapshot.vram_free >= requirement.vram_free
                        and snapshot.ram_available >= requirement.ram_available):
                    return snapshot
                await asyncio.sleep(poll_interval)
    except TimeoutError:
        raise MemoryAdmissionError('Memory admission deadline exceeded') from None
