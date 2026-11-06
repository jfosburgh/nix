"""Narrow local supervisor RPC; no unit names, commands, paths or HTTP inputs.

The privileged server accepts only quiescence for one configured backend from
one configured peer UID. Its injected transaction must be ManagedQuiescence with
real validated dependencies; RPC success alone cannot manufacture that proof.
"""
import asyncio
import json
import math
import os
import re
import socket
import stat
import struct
import uuid

from .supervision import SupervisionError, _parts


def _peer(writer):
    value = writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    return struct.unpack('3i', value)[1]


def _json(data):
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError('duplicate')
            values[key] = value
        return values
    return json.loads(data.decode('ascii'), object_pairs_hook=unique)


class SupervisorRPC:
    """Serial, fail-closed server adapter. No automatic resume/recovery/replay.

    Accepted operations continue on disconnect, bounded by the configured total
    deadline. A failed/uncertain operation permanently faults this server object.
    Caller shutdown must await aclose() inside an outer systemd shutdown bound.
    Socket creation, private directory/ownership, watchdog and service packaging
    belong to the privileged entrypoint, not this transport class.
    """
    def __init__(self, *, backend: str, allowed_uid: int, transaction, timeout: float):
        if (type(backend) is not str or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', backend)
                or type(allowed_uid) is not int or allowed_uid < 0 or not callable(transaction)
                or type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 86400):
            raise SupervisionError('Invalid supervisor RPC policy')
        self.backend, self.uid, self.transaction, self.timeout = backend, allowed_uid, transaction, timeout
        self._tasks = set()
        self._busy = self._faulted = self._closing = False
        self._connections = 0

    async def _operation(self):
        try:
            async with asyncio.timeout(self.timeout):
                await self.transaction()
            return True
        except BaseException:
            self._faulted = True
            return False
        finally:
            self._busy = False

    async def handle(self, reader, writer):
        counted = False
        try:
            if self._connections >= 8:
                return
            self._connections += 1
            counted = True
            # Root is the explicit local provisioning/calibration operator.
            if _peer(writer) not in (0, self.uid) or self._closing:
                return
            async with asyncio.timeout(1):
                # Reader limit must also be bounded by start_unix_server(limit=1024).
                line = await reader.readline()
                if not line.endswith(b'\n') or len(line) > 512:
                    return
                value = _json(line)
                if (type(value) is not dict or set(value) != {'op', 'backend', 'nonce'}
                        or value['op'] != 'quiesce' or value['backend'] != self.backend
                        or type(value['nonce']) is not str
                        or not re.fullmatch(r'[0-9a-f]{32}', value['nonce'])):
                    return
            if self._busy or self._faulted or self._closing:
                result = False
            else:
                self._busy = True
                task = asyncio.create_task(self._operation())
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                result = await asyncio.shield(task)
            writer.write((json.dumps(dict(ok=result, nonce=value['nonce']), separators=(',', ':')) + '\n').encode())
            async with asyncio.timeout(1):
                await writer.drain()
        except (Exception, asyncio.CancelledError):
            pass  # Never cancel an accepted operation because its caller left.
        finally:
            if counted:
                self._connections -= 1
            writer.close()
            try:
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            except (Exception, asyncio.CancelledError):
                pass

    async def aclose(self):
        self._closing = True
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


class SupervisorClient:
    """One bodyless quiescence call, pinned filesystem/peer identity, no retry."""
    def __init__(self, path: str, *, backend: str, timeout: float, expected_uid: int = 0):
        if (not _parts(path) or type(expected_uid) is not int or expected_uid < 0
                or type(backend) is not str or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', backend)
                or type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 86400):
            raise SupervisionError('Invalid supervisor client policy')
        self.path, self.backend, self.timeout, self.uid = path, backend, timeout, expected_uid

    async def __call__(self):
        writer = None
        try:
            async with asyncio.timeout(self.timeout):
                # Server peer credentials remain authoritative if the name races.
                # Parent-directory isolation is provisioned by systemd/root.
                info = os.stat(self.path, follow_symlinks=False)
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.uid or info.st_mode & 0o007:
                    raise ValueError('socket')
                reader, writer = await asyncio.open_unix_connection(self.path, limit=1024)
                if _peer(writer) != self.uid:
                    raise ValueError('peer')
                nonce = uuid.uuid4().hex
                writer.write((json.dumps(dict(op='quiesce', backend=self.backend, nonce=nonce),
                                         separators=(',', ':')) + '\n').encode())
                await writer.drain()
                line = await reader.readline()
                if len(line) > 512 or not line.endswith(b'\n'):
                    raise ValueError('response')
                value = _json(line)
                if type(value) is not dict or value != dict(ok=True, nonce=nonce) or value['ok'] is not True:
                    raise ValueError('response')
        except asyncio.CancelledError:
            raise
        except Exception:
            raise SupervisionError('Supervisor quiescence unconfirmed') from None
        finally:
            if writer is not None:
                writer.close()
                try:
                    async with asyncio.timeout(1):
                        await writer.wait_closed()
                except (Exception, asyncio.CancelledError):
                    pass
