"""Verified transaction boundary; no mutating systemd/helper transport exists.

Only explicit calls may act through the injected helper. A fake helper is not
production proof. Mount pin provisioning, helper privileges, job persistence and
lazy-unit contracts must be established before wiring quiescence; the separate
cgroup_mount module provides an explicit read-only mount-pinning reader. The
systemd_inspect module gathers read-only evidence, not validated UnitState.
"""
import asyncio
from dataclasses import dataclass
import math
import os
from pathlib import PurePosixPath
import re
from typing import Awaitable, Callable, Protocol
import uuid


class SupervisionError(Exception):
    """Sanitized uncertain-process failure; admissions must remain blocked."""


@dataclass(frozen=True)
class UnitContract:
    unit: str
    cgroup: str
    identity: str  # Pinned managed deployment/configuration fingerprint.
    kill_mode: str
    send_sigkill: bool
    stop_timeout: float
    restart: str
    lazy_start: bool
    delegated: bool
    exclusive_control: bool


@dataclass(frozen=True)
class UnitState:
    contract: UnitContract
    active: str
    substate: str
    main_pid: int
    invocation: str
    control_group: str
    pending_job: bool


@dataclass(frozen=True)
class JobCompletion:
    unit: str
    action: str
    nonce: str
    completed: bool
    result: str


@dataclass(frozen=True)
class APIState:
    version: str
    residents: tuple[str, ...]


class UnitHelper(Protocol):
    """Bound to ONE operator-authorized local inference unit, never caller input.

    snapshot validates actual managed-unit configuration, not just asserted flags.
    pending_job includes submitted/uncertain jobs owned by the helper, even before
    systemd has acknowledged them. Mutations return correlated completed jobs,
    never mere submission acknowledgements. Persist uncertainty across helper
    restart; cancellation must not hide pending jobs or auto-start anything.
    """
    async def snapshot(self) -> UnitState: ...
    async def stop(self, nonce: str) -> JobCompletion: ...
    async def start_lazy(self, nonce: str) -> JobCompletion: ...


def _parts(path):
    if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
            or str(PurePosixPath(path)) != path or '..' in PurePosixPath(path).parts
            or any(ord(c) < 32 for c in path)):
        raise SupervisionError('Invalid cgroup path')
    return PurePosixPath(path).parts[1:]


class CgroupReader:
    """Bounded no-symlink cgroup.events reader for an explicitly trusted root.

    `None` means a missing group/path, NEVER proof by itself. The transaction only
    accepts disappearance after correlated stop completion and inactive-unit
    verification. Deployment must pin/verify the real cgroup-v2 mount; fixtures
    intentionally use ordinary directories and do not prove process teardown.
    Use cgroup_mount.VerifiedCgroupReader for explicit mount identity checks;
    this base reader deliberately does not authenticate its filesystem.
    """
    def __init__(self, root: str):
        self.root = _parts(root)

    def _validate_root(self, directory: int):
        pass  # Fixture reader; deployment should use VerifiedCgroupReader.

    def _validate_fd(self, descriptor: int):
        pass

    def _validate_end(self):
        pass

    def __call__(self, group: str) -> bool | None:
        components = _parts(group)
        if not components:
            raise SupervisionError('Root cgroup cannot be a unit release target')
        directory = file_fd = None
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            directory = os.open('/', flags)
            # A missing/misconfigured telemetry root is not unit disappearance.
            for component in self.root:
                next_fd = os.open(component, flags, dir_fd=directory)
                os.close(directory)
                directory = next_fd
            self._validate_root(directory)
            try:
                for component in components:
                    next_fd = os.open(component, flags, dir_fd=directory)
                    os.close(directory)
                    directory = next_fd
                    self._validate_fd(directory)
            except FileNotFoundError:
                self._validate_end()
                return None
            # A present group without its events file is invalid, not release.
            file_fd = os.open('cgroup.events', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                              dir_fd=directory)
            self._validate_fd(file_fd)
            data = bytearray()
            while len(data) <= 4096:
                chunk = os.read(file_fd, 4097 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > 4096:
                raise SupervisionError('Cgroup event byte limit exceeded')
            values = {}
            for line in data.decode('ascii').splitlines():
                match = re.fullmatch(r'([a-z_]+) ([0-9]+)', line)
                if not match or match[1] in values:
                    raise SupervisionError('Invalid cgroup event data')
                values[match[1]] = match[2]
            if values.get('populated') not in ('0', '1'):
                raise SupervisionError('Missing or invalid cgroup population')
            self._validate_end()
            return values['populated'] == '1'
        except SupervisionError:
            raise
        except (OSError, ValueError, UnicodeError):
            raise SupervisionError('Cgroup evidence unavailable') from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if directory is not None:
                os.close(directory)


class ManagedQuiescence:
    """Stop -> verify whole-group empty -> lazy start -> verify new empty API.

    Standalone invocations do not queue/retry: overlapping calls fail. Each fresh
    call re-inspects real helper state and performs a complete transaction; no
    cached success or implicit resume. The scheduler must hold its ownership lock.
    Errors/cancellation leave `uncertain` true. There is no unconditional restart.
    """
    def __init__(self, expected: UnitContract, *, helper: UnitHelper,
                 population: Callable[[str], bool | None],
                 readiness: Callable[[], Awaitable[APIState]], expected_version: str,
                 phase_timeout: float, total_timeout: float):
        if (not isinstance(expected, UnitContract) or not isinstance(expected.unit, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.service', expected.unit)
                or not _parts(expected.cgroup) or PurePosixPath(expected.cgroup).name != expected.unit
                or not isinstance(expected.identity, str) or not expected.identity
                or expected.kill_mode != 'control-group' or expected.send_sigkill is not True
                or expected.restart != 'no' or expected.lazy_start is not True
                or expected.delegated is not False or expected.exclusive_control is not True):
            raise SupervisionError('Unsupported managed-unit contract')
        for timeout in (phase_timeout, total_timeout, expected.stop_timeout):
            if type(timeout) not in (int, float) or not 0 < timeout <= 86400 or not math.isfinite(timeout):
                raise SupervisionError('Finite positive supervision deadlines required')
        if expected.stop_timeout >= phase_timeout or phase_timeout > total_timeout:
            raise SupervisionError('Stop deadline must fit supervision deadlines')
        if (not isinstance(expected_version, str) or not expected_version or not callable(population)
                or not callable(readiness)
                or any(not callable(getattr(helper, method, None))
                       for method in ('snapshot', 'stop', 'start_lazy'))):
            raise SupervisionError('Explicit supervision dependencies required')
        self.expected, self.helper = expected, helper
        self.population, self.readiness = population, readiness
        self.expected_version = expected_version
        self.phase_timeout, self.total_timeout = phase_timeout, total_timeout
        self.uncertain = True
        self._lock = asyncio.Lock()

    async def _phase(self, action):
        async with asyncio.timeout(self.phase_timeout):
            return await action

    def _state(self, state):
        if (not isinstance(state, UnitState) or type(state.contract) is not UnitContract
                or state.contract != self.expected
                or any(type(getattr(state.contract, key)) is not type(getattr(self.expected, key))
                       for key in UnitContract.__dataclass_fields__)
                or state.pending_job is not False or type(state.main_pid) is not int or state.main_pid < 0
                or state.control_group not in ('', self.expected.cgroup)
                or state.active not in ('active', 'inactive', 'failed')
                or not isinstance(state.invocation, str)
                or (state.invocation and not re.fullmatch(r'[0-9a-f]{32}', state.invocation))):
            raise SupervisionError('Unverified unit identity, contract or pending job')
        if state.active == 'active':
            if (state.substate != 'running' or state.main_pid == 0 or not state.invocation
                    or state.control_group != self.expected.cgroup):
                raise SupervisionError('Invalid active managed unit')
        elif state.main_pid != 0 or state.substate != ('dead' if state.active == 'inactive' else 'failed'):
            raise SupervisionError('Invalid stopped managed unit')
        return state

    def _job(self, value, action, nonce):
        if (not isinstance(value, JobCompletion) or value.unit != self.expected.unit
                or value.action != action or value.nonce != nonce
                or value.completed is not True or value.result != 'done'):
            raise SupervisionError('Unit job did not complete with correlated success')

    async def __call__(self):
        if self._lock.locked():
            raise SupervisionError('Supervision transaction already in progress')
        async with self._lock:
            self.uncertain = True
            try:
                async with asyncio.timeout(self.total_timeout):
                    before = self._state(await self._phase(self.helper.snapshot()))
                    # Record pre-stop evidence; missing active groups fail closed.
                    old_population = self.population(self.expected.cgroup)
                    if (old_population is not None and type(old_population) is not bool
                            or before.active == 'active' and old_population is not True):
                        raise SupervisionError('Invalid pre-stop cgroup evidence')
                    nonce = uuid.uuid4().hex
                    self._job(await self._phase(self.helper.stop(nonce)), 'stop', nonce)
                    stopped = self._state(await self._phase(self.helper.snapshot()))
                    if stopped.active != 'inactive':
                        raise SupervisionError('Unit stop did not become inactive')
                    population = self.population(self.expected.cgroup)
                    if population is not False and population is not None:
                        raise SupervisionError('Managed cgroup still populated or uncertain')
                    nonce = uuid.uuid4().hex
                    self._job(await self._phase(self.helper.start_lazy(nonce)), 'start', nonce)
                    started = self._state(await self._phase(self.helper.snapshot()))
                    if started.active != 'active' or started.invocation == before.invocation:
                        raise SupervisionError('Lazy API did not start a new invocation')
                    api = await self._phase(self.readiness())
                    if (not isinstance(api, APIState) or api.version != self.expected_version
                            or not isinstance(api.residents, tuple) or api.residents):
                        raise SupervisionError('Lazy API version/residency verification failed')
                    final = self._state(await self._phase(self.helper.snapshot()))
                    if final.active != 'active' or final.invocation != started.invocation:
                        raise SupervisionError('Lazy API invocation changed during readiness')
                self.uncertain = False
            except asyncio.CancelledError:
                raise
            except Exception:
                raise SupervisionError('Quiescence failed; explicit reconciliation required') from None
