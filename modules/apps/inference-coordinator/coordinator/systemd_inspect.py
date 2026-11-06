"""Bounded read-only busctl transport, not a UnitHelper or stop/start authority.

Only bus identity reads, GetUnit and selected get-property calls are exposed. No GetAll (which could
read environment credentials), shell, inherited bus address or service mutation.
A trusted deployment must pin the executable and local system-bus namespace.
"""
import asyncio
from dataclasses import dataclass
import json
import math
import os
import re
import signal

from .supervision import SupervisionError, _parts
from .bus_identity import BusIdentity

_BUS = 'org.freedesktop.DBus'
_BUS_PATH = '/org/freedesktop/DBus'

_DEST = 'org.freedesktop.systemd1'
_UNIT = _DEST + '.Unit'
_SERVICE = _DEST + '.Service'
_UNIT_PROPERTIES = (
    ('Id', 's'), ('LoadState', 's'), ('ActiveState', 's'), ('SubState', 's'),
    ('InvocationID', 'ay'), ('Job', '(uo)'), ('NeedDaemonReload', 'b'),
    ('RefuseManualStart', 'b'), ('RefuseManualStop', 'b'), ('TriggeredBy', 'as'),
    ('Transient', 'b'),
)
_SERVICE_PROPERTIES = (
    ('MainPID', 'u'), ('ControlPID', 'u'), ('ControlGroup', 's'), ('KillMode', 's'),
    ('SendSIGKILL', 'b'), ('FinalKillSignal', 'i'), ('TimeoutStopUSec', 't'),
    ('Restart', 's'), ('Delegate', 'b'), ('Type', 's'), ('RemainAfterExit', 'b'),
)


@dataclass(frozen=True)
class UnitEvidence:
    unit: str
    object_path: str
    bus_identity: BusIdentity
    active: str
    substate: str
    invocation: str
    job_id: int
    job_path: str
    main_pid: int
    control_pid: int
    control_group: str
    kill_mode: str
    send_sigkill: bool
    final_kill_signal: int
    stop_timeout_usec: int
    restart: str
    delegated: bool
    service_type: str
    remain_after_exit: bool
    triggered_by: tuple[str, ...]
    transient: bool
    refuse_manual_start: bool
    refuse_manual_stop: bool


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate')
        value[key] = item
    return value


def _typed(value, signature):
    if (type(value) is not dict or set(value) != {'type', 'data'}
            or value['type'] != signature):
        raise ValueError('signature')
    data = value['data']
    if signature in ('s', 'o'):
        if type(data) is not str or len(data) > 4096 or any(ord(c) < 32 for c in data):
            raise ValueError('string')
    elif signature == 'b':
        if type(data) is not bool:
            raise ValueError('boolean')
    elif signature in ('u', 't', 'i'):
        lower, upper = {'u': (0, 2**32 - 1), 't': (0, 2**64 - 1),
                        'i': (-2**31, 2**31 - 1)}[signature]
        if type(data) is not int or not lower <= data <= upper:
            raise ValueError('integer')
    elif signature == 'ay':
        if (type(data) is not list or len(data) not in (0, 16)
                or any(type(v) is not int or not 0 <= v <= 255 for v in data)):
            raise ValueError('invocation')
    elif signature == 'as':
        if type(data) is not list or len(data) > 128:
            raise ValueError('array')
        for item in data:
            _typed(dict(type='s', data=item), 's')
    elif signature == '(uo)':
        if type(data) is not list or len(data) != 2:
            raise ValueError('job')
        _typed(dict(type='u', data=data[0]), 'u')
        _typed(dict(type='o', data=data[1]), 'o')
        if data[1] != ('/' if data[0] == 0 else f'/org/freedesktop/systemd1/job/{data[0]}'):
            raise ValueError('job path')
    else:
        raise ValueError('unsupported signature')
    return data


class SystemdInspector:
    """One operator-pinned unit/executable; explicit inspect() performs reads.

    Evidence is deliberately NOT UnitState: this cannot prove deployment identity,
    lazy startup, exclusive control, absence of historical jobs or GPU release.
    No automatic contract assertions or runtime wiring. Concurrent calls refuse
    rather than queue. Budgets are development bounds, not deployment calibration.
    """
    def __init__(self, *, executable: str, unit: str, expected_bus: BusIdentity,
                 timeout: float = 5,
                 cleanup_timeout: float = 1, output_limit: int = 65536):
        if (type(expected_bus) is not BusIdentity
                or not _parts(executable) or not isinstance(unit, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.service', unit)
                or type(output_limit) is not int or not 1024 <= output_limit <= 1024 * 1024):
            raise SupervisionError('Invalid inspection policy')
        for duration in (timeout, cleanup_timeout):
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 60:
                raise SupervisionError('Bounded inspection deadlines required')
        self.executable, self.unit = executable, unit
        self.expected_bus = expected_bus
        self.timeout, self.cleanup_timeout, self.output_limit = timeout, cleanup_timeout, output_limit
        self._lock = asyncio.Lock()
        self._cleanup = set()
        self._faulted = False

    async def _read(self, stream):
        data = bytearray()
        while True:
            chunk = await stream.read(min(4096, self.output_limit + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            if len(data) > self.output_limit:
                raise SupervisionError('Inspection output limit exceeded')

    async def _reap(self, spawn, tasks):
        # Keep ownership of late process creation even if its caller timed out.
        process = await spawn
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async def discard(stream):
            while await stream.read(4096):
                pass
        # Drain bounded-memory pipe buffers after kill. A stopped limit-reader
        # can otherwise keep asyncio's process.wait() waiting on a paused pipe.
        async with asyncio.timeout(self.cleanup_timeout):
            await asyncio.gather(process.wait(), discard(process.stdout), discard(process.stderr))

    def _cleanup_done(self, task):
        self._cleanup.discard(task)
        if task.cancelled() or task.exception() is not None:
            self._faulted = True

    async def _run(self, arguments):
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            self.executable, '--system', '--no-pager', '--json=short',
            '--auto-start=no', '--allow-interactive-authorization=no',
            f'--timeout={self.timeout}s', *arguments,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env={'LANG': 'C', 'LC_ALL': 'C'},
            cwd='/', start_new_session=True, close_fds=True, limit=4096))
        tasks = []
        try:
            process = await asyncio.shield(spawn)
            stdout = asyncio.create_task(self._read(process.stdout))
            stderr = asyncio.create_task(self._read(process.stderr))
            wait = asyncio.create_task(process.wait())
            tasks = [stdout, stderr, wait]
            output, errors, code = await asyncio.gather(*tasks)
            if code != 0 or errors:
                raise SupervisionError('Inspection command failed')
            return output
        except BaseException:
            cleanup = asyncio.create_task(self._reap(spawn, tasks))
            self._cleanup.add(cleanup)
            cleanup.add_done_callback(self._cleanup_done)
            try:
                async with asyncio.timeout(self.cleanup_timeout * 2):
                    await asyncio.shield(cleanup)
            except BaseException:
                # No further command may run while process cleanup is uncertain.
                self._faulted = True
            raise

    def _lines(self, data):
        if not data.endswith(b'\n'):
            raise ValueError('incomplete')
        return [json.loads(line.decode('utf-8'), object_pairs_hook=_object)
                for line in data.splitlines()]

    async def _single_reply(self, arguments, signature):
        lines = self._lines(await self._run(arguments))
        # Method replies carry a tuple of return values, unlike properties.
        if (len(lines) != 1 or type(lines[0]) is not dict
                or set(lines[0]) != {'type', 'data'} or lines[0]['type'] != signature
                or type(lines[0]['data']) is not list or len(lines[0]['data']) != 1):
            raise ValueError('method reply')
        return _typed(dict(type=signature, data=lines[0]['data'][0]), signature)

    async def _bus_check(self, *, final=False):
        # Read GUID first at entry, last at exit, enclosing every manager call.
        async def guid():
            return await self._single_reply(('call', _BUS, _BUS_PATH, _BUS, 'GetId'), 's')
        async def owner():
            return await self._single_reply(('call', _BUS, _BUS_PATH, _BUS,
                                             'GetNameOwner', 's', _DEST), 's')
        if final:
            manager_owner, bus_id = await owner(), await guid()
        else:
            bus_id, manager_owner = await guid(), await owner()
        actual = BusIdentity(bus_id, manager_owner)
        if actual != self.expected_bus:
            self._faulted = True
            raise SupervisionError('Bus identity changed; explicit recovery required')

    async def _properties(self, path, interface, properties):
        lines = self._lines(await self._run(('get-property', self.expected_bus.manager_owner, path, interface,
                                            *(name for name, _ in properties))))
        if len(lines) != len(properties):
            raise ValueError('property count')
        return {name: _typed(value, signature)
                for (name, signature), value in zip(properties, lines)}

    async def inspect(self) -> UnitEvidence:
        if self._lock.locked() or self._faulted or self._cleanup:
            raise SupervisionError('Inspection busy or process cleanup uncertain')
        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout):
                    await self._bus_check()
                    path = await self._single_reply((
                        'call', self.expected_bus.manager_owner, '/org/freedesktop/systemd1',
                        _DEST + '.Manager', 'GetUnit', 's', self.unit), 'o')
                    if (type(path) is not str or not re.fullmatch(
                            r'/org/freedesktop/systemd1/unit/[A-Za-z0-9_]{1,512}', path)):
                        raise ValueError('object path')
                    before = await self._properties(path, _UNIT, _UNIT_PROPERTIES)
                    service = await self._properties(path, _SERVICE, _SERVICE_PROPERTIES)
                    after = await self._properties(path, _UNIT, _UNIT_PROPERTIES)
                    if (before != after or before['Id'] != self.unit
                            or before['LoadState'] != 'loaded' or before['NeedDaemonReload']):
                        raise ValueError('unstable or stale unit')
                    active = before['ActiveState']
                    if before['SubState'] != {'active': 'running', 'inactive': 'dead',
                                              'failed': 'failed'}.get(active):
                        raise ValueError('transitional unit')
                    group = service['ControlGroup']
                    if group and not _parts(group):
                        raise ValueError('root group')
                    invocation = bytes(before['InvocationID']).hex()
                    if (active == 'active' and (not service['MainPID'] or not invocation or not group)
                            or active != 'active' and service['MainPID'] != 0):
                        raise ValueError('inconsistent process state')
                    job_id, job_path = before['Job']
                    await self._bus_check(final=True)
                    return UnitEvidence(
                        self.unit, path, self.expected_bus, before['ActiveState'], before['SubState'], invocation,
                        job_id, job_path, service['MainPID'], service['ControlPID'], group,
                        service['KillMode'], service['SendSIGKILL'], service['FinalKillSignal'],
                        service['TimeoutStopUSec'], service['Restart'], service['Delegate'],
                        service['Type'], service['RemainAfterExit'], tuple(before['TriggeredBy']),
                        before['Transient'], before['RefuseManualStart'], before['RefuseManualStop'])
            except asyncio.CancelledError:
                raise
            except Exception:
                raise SupervisionError('Systemd inspection failed; no release proof') from None
