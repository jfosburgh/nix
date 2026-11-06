"""Durable write-ahead supervisor intent ledger; NOT a systemd transport.

A trusted helper must commit begin() BEFORE submitting a mutation. Cancellation,
submission timeout and process exit leave the intent pending. No replay, retry,
service action or automatic uncertainty clearing occurs here. Local trusted
filesystems with working fsync/flock are required; owner/root remain trusted.
"""
from dataclasses import asdict, dataclass, replace
import fcntl
import json
import os
import re
import stat

from .supervision import SupervisionError, _parts
from .bus_identity import BusIdentity


@dataclass(frozen=True)
class JobIntent:
    nonce: str
    action: str
    job_id: int | None = None
    result: str | None = None


class JobJournal:
    """One pinned unit/deployment, one unresolved intent, one exclusive writer.

    Construction has no I/O. Explicit open(initialize=True) exclusively creates a
    NEW ledger; normal open never treats a missing file as empty. Hold the object
    open for the helper's lifetime. Every event is appended and fsynced before it
    is reflected in memory/returned. A failed write poisons this instance. Torn,
    malformed or excessive logs fail closed on reopen, never truncate/repair.

    acknowledge() is an explicit reconciliation bookkeeping operation, NOT proof
    a backend is stopped. Even a completed/acknowledged job never establishes
    cgroup release or API readiness. Recovered state always needs real inspection.
    The injected normalized kernel boot ID must match on reopen; no job-ID reuse
    across boots is accepted. The future transport must also correlate actual
    jobs/nonces and handle manager reexecution/ID reuse explicitly. The required
    bus GUID/name-owner pins also persist unchanged in the version-2 header;
    version-1 journals have no implicit migration or reuse path.
    """
    MAX_BYTES = 1024 * 1024
    MAX_LINE = 2048

    def __init__(self, path: str, *, unit: str, identity: str, boot_id: str,
                 bus_identity: BusIdentity, expected_uid: int | None = None,
                 manager_load_usec: int | None = None, manager_version: str | None = None):
        components = _parts(path)
        uid = os.geteuid() if expected_uid is None else expected_uid
        if (type(bus_identity) is not BusIdentity
                or not components or type(uid) is not int or uid < 0
                or not isinstance(unit, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.service', unit)
                or not isinstance(boot_id, str) or not re.fullmatch(r'[0-9a-f]{32}', boot_id)
                or not isinstance(identity, str) or not 1 <= len(identity) <= 256
                or any(not 0x21 <= ord(c) <= 0x7e for c in identity)):
            raise SupervisionError('Invalid journal policy')
        if ((manager_load_usec is None) != (manager_version is None)
                or (manager_load_usec is not None and (
                    type(manager_load_usec) is not int or not 0 < manager_load_usec < 2**64
                    or type(manager_version) is not str or manager_version != '262'))):
            raise SupervisionError('Invalid journal manager fence')
        self.components, self.uid = components, uid
        self.header = dict(version=2, unit=unit, identity=identity, boot_id=boot_id,
                           bus_id=bus_identity.bus_id, manager_owner=bus_identity.manager_owner)
        if manager_load_usec is not None:
            self.header.update(version=3, manager_load_usec=manager_load_usec,
                               manager_version=manager_version)
        self._directory = self._fd = None
        self._poisoned = False
        self._pending = None
        self._used = set()
        self._size = 0

    @property
    def pending(self) -> JobIntent | None:
        self._ready()
        try:
            if self._pinned().st_size != self._size:
                raise ValueError('external write')
        except Exception:
            self._poisoned = True
            raise SupervisionError('Journal evidence changed; explicit recovery required') from None
        return self._pending

    def _ready(self):
        if self._fd is None or self._poisoned:
            raise SupervisionError('Journal unavailable; explicit recovery required')

    def _directory_ok(self, descriptor, *, final=False):
        info = os.fstat(descriptor)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, self.uid)
                or (info.st_mode & 0o022 and not (
                    not final and info.st_uid == 0 and info.st_mode & stat.S_ISVTX))
                or (final and (info.st_uid != self.uid or info.st_mode & 0o077))):
            raise SupervisionError('Unsafe journal directory')

    def _file_ok(self, info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.uid or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > self.MAX_BYTES):
            raise SupervisionError('Unsafe journal file')

    def _pinned(self):
        self._directory_ok(self._directory, final=True)
        current = os.stat(self.components[-1], dir_fd=self._directory, follow_symlinks=False)
        opened = os.fstat(self._fd)
        self._file_ok(current)
        self._file_ok(opened)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise SupervisionError('Journal identity changed')
        return opened

    def open(self, *, initialize=False):
        if self._fd is not None or type(initialize) is not bool:
            raise SupervisionError('Journal already open or invalid open policy')
        self._poisoned = False
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            self._directory = os.open('/', flags)
            self._directory_ok(self._directory)
            for part in self.components[:-1]:
                next_fd = os.open(part, flags, dir_fd=self._directory)
                os.close(self._directory)
                self._directory = next_fd
                self._directory_ok(self._directory)
            self._directory_ok(self._directory, final=True)
            flags = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            candidate = None
            if initialize:
                flags |= os.O_CREAT | os.O_EXCL
            else:
                candidate = os.stat(self.components[-1], dir_fd=self._directory, follow_symlinks=False)
                self._file_ok(candidate)  # Reject devices/FIFOs before opening them.
            self._fd = os.open(self.components[-1], flags, 0o600, dir_fd=self._directory)
            opened = os.fstat(self._fd)
            self._file_ok(opened)
            if candidate is not None and (candidate.st_dev, candidate.st_ino) != (opened.st_dev, opened.st_ino):
                raise SupervisionError('Journal changed while opening')
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._pinned()
            self._pending, self._used, self._size = None, set(), 0
            if initialize:
                self._append(self.header)
                os.fsync(self._directory)
            else:
                self._replay()
            return self
        except BaseException as error:
            self.close()
            if not isinstance(error, Exception):
                raise
            raise SupervisionError('Journal could not be opened securely') from None

    def close(self):
        for name in ('_fd', '_directory'):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)
        self._pending, self._used = None, set()

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate')
            result[key] = value
        return result

    def _replay(self):
        before = self._pinned()
        data = bytearray()
        while len(data) <= self.MAX_BYTES:
            chunk = os.read(self._fd, min(65536, self.MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = self._pinned()
        if (not data or len(data) > self.MAX_BYTES or not data.endswith(b'\n')
                or len(data) != after.st_size
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise SupervisionError('Incomplete or changed journal')
        for index, line in enumerate(data.splitlines()):
            if not line or len(line) > self.MAX_LINE:
                raise SupervisionError('Invalid journal record')
            event = json.loads(line.decode('ascii'), object_pairs_hook=self._object)
            if index == 0:
                if (type(event) is not dict or event != self.header
                        or type(event.get('version')) is not int):
                    raise SupervisionError('Journal deployment mismatch')
            else:
                self._apply(event)
        self._size = len(data)

    def _apply(self, event):
        if type(event) is not dict or set(event) != {'event', 'intent'}:
            raise SupervisionError('Invalid journal event')
        value = event['intent']
        if type(value) is not dict or set(value) != {'nonce', 'action', 'job_id', 'result'}:
            raise SupervisionError('Invalid journal intent')
        intent = JobIntent(**value)
        if (not isinstance(intent.nonce, str) or not re.fullmatch(r'[0-9a-f]{32}', intent.nonce)
                or intent.action not in ('stop', 'start')
                or (intent.job_id is not None and (
                    type(intent.job_id) is not int or not 0 < intent.job_id <= 0xffffffff))
                or (intent.result is not None and intent.result not in (
                    'done', 'failed', 'canceled', 'timeout', 'dependency', 'skipped'))):
            raise SupervisionError('Invalid journal intent metadata')
        kind = event['event']
        old = self._pending
        if kind == 'begin':
            if old is not None or intent.nonce in self._used or intent.job_id is not None or intent.result is not None:
                raise SupervisionError('Overlapping or repeated journal intent')
            self._used.add(intent.nonce)
            self._pending = intent
        elif kind == 'submitted':
            if (old is None or old.job_id is not None or intent.job_id is None
                    or replace(intent, job_id=None) != old):
                raise SupervisionError('Uncorrelated submitted job')
            self._pending = intent
        elif kind == 'completed':
            if (old is None or old.job_id is None or old.result is not None or intent.result is None
                    or replace(intent, result=None) != old):
                raise SupervisionError('Uncorrelated completed job')
            self._pending = intent
        elif kind == 'acknowledged':
            if old is None or old.result is None or intent != old:
                raise SupervisionError('Unverified journal acknowledgement')
            self._pending = None
        else:
            raise SupervisionError('Unknown journal event')

    def _append(self, event):
        self._ready()
        try:
            data = (json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
            if len(data) > self.MAX_LINE or self._size + len(data) > self.MAX_BYTES:
                raise ValueError('limit')
            if self._pinned().st_size != self._size:
                raise ValueError('external write')
            remaining = memoryview(data)
            while remaining:
                written = os.write(self._fd, remaining)
                if written <= 0:
                    raise ValueError('short write')
                remaining = remaining[written:]
            os.fsync(self._fd)
            if self._pinned().st_size != self._size + len(data):
                raise ValueError('external write')
            self._size += len(data)
        except Exception:
            self._poisoned = True
            raise SupervisionError('Journal commit uncertain; explicit recovery required') from None

    def _commit(self, kind, intent):
        self._ready()
        if type(intent) is not JobIntent:
            raise SupervisionError('Explicit correlated job intent required')
        event = dict(event=kind, intent=asdict(intent))
        # Validate without publishing state until durable commit succeeds.
        old, used = self._pending, set(self._used)
        try:
            self._apply(event)
        finally:
            self._pending, self._used = old, used
        try:
            self._append(event)
            self._apply(event)
            return self._pending
        except BaseException:
            self._poisoned = True
            raise

    def begin(self, action: str, nonce: str) -> JobIntent:
        return self._commit('begin', JobIntent(nonce, action))

    def submitted(self, intent: JobIntent, job_id: int) -> JobIntent:
        return self._commit('submitted', replace(intent, job_id=job_id))

    def completed(self, intent: JobIntent, result: str) -> JobIntent:
        return self._commit('completed', replace(intent, result=result))

    def acknowledge(self, intent: JobIntent) -> None:
        self._commit('acknowledged', intent)
