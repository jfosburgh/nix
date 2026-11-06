"""Persistent, journaled systemd job transport; not a deployment-approved helper.

Only an explicitly pinned unit can be started/stopped. No reconnect, mutation
retry, inferred completion, unknown-intent clearing or automatic journal ack.
The caller must separately verify deployment policy and post-job unit/cgroup
state. dbus-next talks to a fixed local system bus, never caller environment.
"""
import asyncio
from dataclasses import dataclass
import math
import re

from dbus_next import Message, MessageFlag, MessageType
from dbus_next.aio import MessageBus

from .bus_identity import BusIdentity
from .job_journal import JobJournal
from .supervision import JobCompletion, SupervisionError

DBUS = 'org.freedesktop.DBus'
DBUS_PATH = '/org/freedesktop/DBus'
MANAGER = 'org.freedesktop.systemd1'
PATH = '/org/freedesktop/systemd1'
INTERFACE = MANAGER + '.Manager'
RESULTS = frozenset({'done', 'failed', 'canceled', 'timeout', 'dependency', 'skipped'})


@dataclass(frozen=True)
class ManagerFence:
    """Explicit reload-sensitive marker, NOT a generic process epoch.

    Supported systemd 262 updates UnitsLoadTimestampMonotonic in
    manager_reloading_start during serialization/deserialization (including
    reexec). This policy rejects any marker/version change and Reloading signal;
    unknown versions are refused, not assumed equivalent. Trusted PID1/bus and
    non-adversarial monotonic-clock resolution are deployment assumptions.
    """
    bus: BusIdentity
    units_load_usec: int
    version: str

    def __post_init__(self):
        if (type(self.bus) is not BusIdentity or type(self.units_load_usec) is not int
                or not 0 < self.units_load_usec < 2**64 or self.version != '262'):
            raise SupervisionError('Explicit supported manager fence required')


class SystemdJobSession:
    """One persistent subscribed bus connection and one durable pending intent.

    Construction performs no I/O. open() performs identity checks, installs
    matches BEFORE Subscribe, and rejects existing target-unit jobs. A mutation
    commits begin before submission, then requires its reply path AND live
    JobNew/JobRemoved correlation (including signals before the method reply).
    Cancellation/timeouts leave the journal pending and permanently fault the
    session. Completion remains pending until explicit acknowledgement. Recovery
    of an old pending intent is intentionally unavailable, never guessed from
    Job=0. Deadlines are cooperative; an outer helper supervisor is required.
    """
    def __init__(self, journal: JobJournal, *, expected: ManagerFence,
                 timeout: float = 120, bus_factory=None):
        if (type(journal) is not JobJournal or type(expected) is not ManagerFence
                or journal.header['bus_id'] != expected.bus.bus_id
                or journal.header['manager_owner'] != expected.bus.manager_owner
                or journal.header.get('version') != 3
                or journal.header.get('manager_load_usec') != expected.units_load_usec
                or journal.header.get('manager_version') != expected.version
                or type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 86400):
            raise SupervisionError('Invalid job session policy')
        self.journal, self.expected, self.timeout = journal, expected, timeout
        self.unit = journal.header['unit']
        self._factory = bus_factory or (lambda: MessageBus(
            bus_address='unix:path=/run/dbus/system_bus_socket'))
        self._bus = None
        self._watch = None
        self._opened = self._faulted = self._sending = False
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._new = self._removed = None
        self._seen = set()

    def _fault(self):
        self._faulted = True
        self._changed.set()

    def _usable(self):
        if self._faulted or self._bus is None:
            raise SupervisionError('Job session uncertain; explicit recovery required')

    async def _call(self, destination, path, interface, member, signature='', body=None,
                    reply_signature=''):
        self._usable()
        reply = await self._bus.call(Message(
            destination=destination, path=path, interface=interface, member=member,
            signature=signature, body=[] if body is None else body,
            flags=MessageFlag.NO_AUTOSTART))
        self._usable()
        if (reply is None or reply.message_type != MessageType.METHOD_RETURN
                or reply.sender != destination or reply.signature != reply_signature
                or type(reply.body) is not list):
            raise SupervisionError('Job transport reply invalid')
        return reply.body

    async def _identity(self):
        guid = await self._call(DBUS, DBUS_PATH, DBUS, 'GetId', reply_signature='s')
        owner = await self._call(DBUS, DBUS_PATH, DBUS, 'GetNameOwner', 's', [MANAGER], 's')
        if guid != [self.expected.bus.bus_id] or owner != [self.expected.bus.manager_owner]:
            raise SupervisionError('Job bus identity changed')
        values = []
        for name, signature in (('UnitsLoadTimestampMonotonic', 't'), ('Version', 's')):
            body = await self._call(self.expected.bus.manager_owner, PATH,
                                    'org.freedesktop.DBus.Properties', 'Get', 'ss',
                                    [INTERFACE, name], 'v')
            if (len(body) != 1 or getattr(body[0], 'signature', None) != signature):
                raise SupervisionError('Manager fence unavailable')
            values.append(body[0].value)
        if (type(values[0]) is not int or type(values[1]) is not str
                or values != [self.expected.units_load_usec, self.expected.version]):
            raise SupervisionError('Manager fence changed')

    def _signal(self, message):
        if message.message_type != MessageType.SIGNAL:
            return
        try:
            if (message.sender == DBUS and message.path == DBUS_PATH
                    and message.interface == DBUS and message.member == 'NameOwnerChanged'):
                if (message.signature != 'sss' or len(message.body) != 3
                        or any(type(v) is not str for v in message.body)):
                    raise ValueError('owner signal')
                if message.body[0] == MANAGER:
                    raise ValueError('owner changed')
                return
            if (message.sender != self.expected.bus.manager_owner or message.path != PATH
                    or message.interface != INTERFACE):
                return
            if message.member in ('Reloading', 'UnitFilesChanged'):
                raise ValueError('manager changed')
            if message.member not in ('JobNew', 'JobRemoved'):
                return
            removed = message.member == 'JobRemoved'
            if (message.signature != ('uoss' if removed else 'uos')
                    or len(message.body) != (4 if removed else 3)):
                raise ValueError('job signal')
            job_id, path, unit = message.body[:3]
            if (type(job_id) is not int or not 0 < job_id <= 0xffffffff
                    or path != f'{PATH}/job/{job_id}' or type(unit) is not str
                    or len(unit) > 256):
                raise ValueError('job identity')
            if unit != self.unit:
                return
            if not self._sending:
                raise ValueError('external unit job')
            if removed:
                if (self._new != (job_id, path) or self._removed is not None
                        or message.body[3] not in RESULTS):
                    raise ValueError('uncorrelated removal')
                self._removed = (job_id, path, message.body[3])
            else:
                if self._new is not None or job_id in self._seen or len(self._seen) >= 4096:
                    raise ValueError('duplicate job')
                self._seen.add(job_id)
                self._new = (job_id, path)
            self._changed.set()
        except Exception:
            self._fault()

    async def _disconnected(self):
        try:
            await self._bus.wait_for_disconnect()
        finally:
            self._fault()

    async def open(self):
        if self._bus is not None or self._opened or self._faulted or self._lock.locked():
            raise SupervisionError('Job session already used')
        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout):
                    if self.journal.pending is not None:
                        raise SupervisionError('Pending job requires explicit recovery')
                    self._bus = self._factory()
                    await self._bus.connect()
                    self._bus.add_message_handler(self._signal)
                    self._watch = asyncio.create_task(self._disconnected())
                    await self._identity()
                    matches = (
                        f"type='signal',sender='{DBUS}',interface='{DBUS}',path='{DBUS_PATH}',member='NameOwnerChanged',arg0='{MANAGER}'",
                        f"type='signal',sender='{self.expected.bus.manager_owner}',interface='{INTERFACE}',path='{PATH}'",
                    )
                    for match in matches:
                        body = await self._call(DBUS, DBUS_PATH, DBUS, 'AddMatch', 's', [match])
                        if body:
                            raise SupervisionError('Invalid subscription reply')
                    body = await self._call(self.expected.bus.manager_owner, PATH, INTERFACE, 'Subscribe')
                    if body:
                        raise SupervisionError('Invalid subscription reply')
                    jobs = await self._call(self.expected.bus.manager_owner, PATH, INTERFACE,
                                            'ListJobs', reply_signature='a(usssoo)')
                    if (len(jobs) != 1 or type(jobs[0]) is not list or len(jobs[0]) > 4096):
                        raise SupervisionError('Invalid job inventory')
                    for job in jobs[0]:
                        if (type(job) not in (list, tuple) or len(job) != 6
                                or type(job[1]) is not str or job[1] == self.unit):
                            raise SupervisionError('Target job pending or inventory invalid')
                    await self._identity()
                    self._opened = True
            except BaseException as error:
                self._fault()
                await self.close()
                if not isinstance(error, Exception):
                    raise
                raise SupervisionError('Job session could not be opened') from None
        return self

    async def check(self):
        """Fresh identity/fence check; NOT deployment validation or release proof."""
        if not self._opened or self._lock.locked():
            raise SupervisionError('Job session unavailable or busy')
        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout):
                    await self._identity()
            except BaseException as error:
                self._fault()
                if not isinstance(error, Exception):
                    raise
                raise SupervisionError('Job session fence uncertain') from None

    async def unit_files(self):
        """Bounded selected file-origin evidence; never GetAll/environment."""
        if not self._opened or self._lock.locked():
            raise SupervisionError('Job session unavailable or busy')
        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout):
                    await self._identity()
                    reply = await self._call(self.expected.bus.manager_owner, PATH, INTERFACE,
                                             'GetUnit', 's', [self.unit], 'o')
                    if (len(reply) != 1 or type(reply[0]) is not str or not re.fullmatch(
                            r'/org/freedesktop/systemd1/unit/[A-Za-z0-9_]{1,512}', reply[0])):
                        raise SupervisionError('Invalid unit file evidence')
                    values = {}
                    for name, signature in (('FragmentPath', 's'), ('SourcePath', 's'),
                                            ('DropInPaths', 'as'), ('NeedDaemonReload', 'b')):
                        body = await self._call(self.expected.bus.manager_owner, reply[0],
                                                'org.freedesktop.DBus.Properties', 'Get', 'ss',
                                                [MANAGER + '.Unit', name], 'v')
                        if len(body) != 1 or getattr(body[0], 'signature', None) != signature:
                            raise SupervisionError('Invalid unit file evidence')
                        value = body[0].value
                        if (signature == 's' and (type(value) is not str or len(value) > 4096)
                                or signature == 'as' and (type(value) is not list or len(value) > 128
                                    or any(type(v) is not str or len(v) > 4096 for v in value))
                                or signature == 'b' and type(value) is not bool):
                            raise SupervisionError('Invalid unit file evidence')
                        values[name] = tuple(value) if signature == 'as' else value
                    await self._identity()
                    return values
            except BaseException as error:
                self._fault()
                if not isinstance(error, Exception):
                    raise
                raise SupervisionError('Unit file evidence uncertain') from None

    async def run(self, action: str, nonce: str) -> JobCompletion:
        if (action not in ('stop', 'start') or type(action) is not str
                or type(nonce) is not str or not re.fullmatch(r'[0-9a-f]{32}', nonce)
                or not self._opened or self._lock.locked()):
            raise SupervisionError('Invalid or overlapping job operation')
        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout):
                    await self._identity()
                    # Fsync before any mutation. No acknowledgement on failure.
                    intent = self.journal.begin(action, nonce)
                    self._new = self._removed = None
                    self._changed.clear()
                    self._sending = True
                    reply = await self._call(self.expected.bus.manager_owner, PATH, INTERFACE,
                                             'StopUnit' if action == 'stop' else 'StartUnit',
                                             'ss', [self.unit, 'fail'], 'o')
                    if (len(reply) != 1 or type(reply[0]) is not str
                            or not re.fullmatch(r'/org/freedesktop/systemd1/job/[1-9][0-9]{0,9}', reply[0])):
                        raise SupervisionError('Invalid submitted job path')
                    job_id = int(reply[0].rsplit('/', 1)[1])
                    if job_id > 0xffffffff:
                        raise SupervisionError('Invalid submitted job ID')
                    intent = self.journal.submitted(intent, job_id)
                    while self._removed is None:
                        self._usable()
                        self._changed.clear()
                        await self._changed.wait()
                    self._usable()
                    if self._removed[:2] != (job_id, reply[0]):
                        raise SupervisionError('Job completion identity mismatch')
                    await self._identity()
                    self._usable()
                    result = self._removed[2]
                    self.journal.completed(intent, result)
                    return JobCompletion(self.unit, action, nonce, True, result)
            except BaseException as error:
                self._fault()
                if not isinstance(error, Exception):
                    raise
                raise SupervisionError('Job operation uncertain; explicit recovery required') from None
            finally:
                self._sending = False

    async def acknowledge(self, completion: JobCompletion):
        """Explicit bookkeeping AFTER independent post-job reconciliation.

        Only a live session's matching durable successful completion is eligible.
        This method itself does not validate unit/cgroup state or grant admission.
        """
        if not self._opened or self._lock.locked():
            raise SupervisionError('Job session unavailable or busy')
        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout):
                    await self._identity()
                    pending = self.journal.pending
                    if (type(completion) is not JobCompletion or completion.completed is not True
                            or pending is None
                            or completion != JobCompletion(self.unit, pending.action, pending.nonce, True, 'done')
                            or pending.result != 'done' or self._removed is None
                            or self._removed != (pending.job_id, f'{PATH}/job/{pending.job_id}', 'done')):
                        raise SupervisionError('Completion not eligible for acknowledgement')
                    self.journal.acknowledge(pending)
            except BaseException as error:
                self._fault()
                if not isinstance(error, Exception):
                    raise
                raise SupervisionError('Job acknowledgement uncertain') from None

    async def close(self):
        # No Unsubscribe needed: systemd tracks/discards disconnected subscribers.
        self._fault()
        self._opened = False
        if self._bus is not None:
            self._bus.remove_message_handler(self._signal)
            self._bus.disconnect()
        if self._watch is not None:
            try:
                async with asyncio.timeout(min(self.timeout, 2)):
                    await asyncio.shield(self._watch)
            except (Exception, asyncio.CancelledError):
                if not self._watch.done():
                    self._watch.cancel()
                await asyncio.gather(self._watch, return_exceptions=True)
