"""Explicit operator-only boot/bus/mount pin provisioning, never auto-repin.

Call only as a reviewed local provisioning action, in the supervisor's stable
host mount/cgroup namespace. Runtime loads existing pins; changes fail closed.
These observations trust kernel procfs, PID1, the local system bus and root/Nix.
"""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import stat

from dbus_next import Message, MessageFlag, MessageType
from dbus_next.aio import MessageBus

from .bus_identity import BusIdentity
from .cgroup_mount import CgroupMount, VerifiedCgroupReader, _read_proc
from .supervision import SupervisionError, _parts
from .systemd_jobs import DBUS, DBUS_PATH, MANAGER, PATH, INTERFACE, ManagerFence


def boot_id():
    value = _read_proc('/proc/sys/kernel/random/boot_id', 128).strip().replace('-', '')
    if not re.fullmatch(r'[0-9a-f]{32}', value):
        raise SupervisionError('Kernel boot identity unavailable')
    return value


async def observe_fence():
    """Only the explicit provision command may discover a new identity."""
    bus = MessageBus(bus_address='unix:path=/run/dbus/system_bus_socket')
    async def call(destination, path, interface, member, signature='', body=None, expected='s'):
        reply = await bus.call(Message(destination=destination, path=path, interface=interface,
                                       member=member, signature=signature, body=body or [],
                                       flags=MessageFlag.NO_AUTOSTART))
        if (reply.message_type != MessageType.METHOD_RETURN or reply.sender != destination
                or reply.signature != expected or len(reply.body) != 1):
            raise SupervisionError('Provisioning identity reply invalid')
        return reply.body[0]
    try:
        async with asyncio.timeout(5):
            await bus.connect()
            guid = await call(DBUS, DBUS_PATH, DBUS, 'GetId')
            owner = await call(DBUS, DBUS_PATH, DBUS, 'GetNameOwner', 's', [MANAGER])
            values = []
            for prop, signature in (('UnitsLoadTimestampMonotonic', 't'), ('Version', 's')):
                value = await call(owner, PATH, 'org.freedesktop.DBus.Properties', 'Get', 'ss',
                                   [INTERFACE, prop], expected='v')
                if getattr(value, 'signature', None) != signature:
                    raise SupervisionError('Provisioning manager fence invalid')
                values.append(value.value)
            if (await call(DBUS, DBUS_PATH, DBUS, 'GetNameOwner', 's', [MANAGER]) != owner
                    or await call(DBUS, DBUS_PATH, DBUS, 'GetId') != guid):
                raise SupervisionError('Provisioning identity changed')
            return ManagerFence(BusIdentity(guid, owner), *values)
    finally:
        bus.disconnect()
        try:
            async with asyncio.timeout(1):
                await bus.wait_for_disconnect()
        except Exception:
            pass


def observe_mount():
    descriptor = os.open('/sys/fs/cgroup', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        values = [line.split(':', 1)[1].strip()
                  for line in _read_proc(f'/proc/self/fdinfo/{descriptor}', 16384).splitlines()
                  if line.startswith('mnt_id:')]
        if len(values) != 1 or not re.fullmatch(r'[1-9][0-9]*', values[0]):
            raise SupervisionError('Provisioning cgroup mount unavailable')
        pin = CgroupMount(int(values[0]), os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
        reader = VerifiedCgroupReader('/sys/fs/cgroup', expected=pin)
        reader._validate_root(descriptor)
        return pin
    finally:
        os.close(descriptor)


def _directory(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for part in _parts(path):
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise SupervisionError('Unsafe supervisor state ancestor')
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_mode & 0o077:
            raise SupervisionError('Private root supervisor state required')
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_pins(directory, *, deployment, fence, mount):
    """Exclusive creation + fsync. Never overwrite/migrate/repair existing pins."""
    data = dict(version=1, boot_id=boot_id(), deployment=deployment,
                bus=asdict(fence.bus), units_load_usec=fence.units_load_usec,
                manager_version=fence.version, mount=asdict(mount))
    fd = _directory(directory)
    file = None
    try:
        file = os.open('pins.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o600, dir_fd=fd)
        payload = (json.dumps(data, separators=(',', ':')) + '\n').encode()
        while payload:
            written = os.write(file, payload)
            if written <= 0:
                raise SupervisionError('Pin provisioning write uncertain')
            payload = payload[written:]
        os.fsync(file)
        os.fsync(fd)
    finally:
        if file is not None:
            os.close(file)
        os.close(fd)


def load_pins(directory, *, deployment):
    """Read existing bounded private pins; no discovery or stale fallback."""
    fd = _directory(directory)
    file = None
    try:
        file = os.open('pins.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
        info = os.fstat(file)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or not 0 < info.st_size <= 4096):
            raise SupervisionError('Unsafe supervisor pins')
        data = os.read(file, 4097)
        after = os.fstat(file)
        current = os.stat('pins.json', dir_fd=fd, follow_symlinks=False)
        metadata = ('st_dev', 'st_ino', 'st_uid', 'st_mode', 'st_nlink', 'st_size',
                    'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(info, key) != getattr(after, key) or getattr(info, key) != getattr(current, key)
               for key in metadata):
            raise SupervisionError('Supervisor pins changed during read')
        from .supervisor_rpc import _json
        value = _json(data)
        if (type(value) is not dict or set(value) != {'version', 'boot_id', 'deployment', 'bus',
                'units_load_usec', 'manager_version', 'mount'} or type(value['version']) is not int
                or value['version'] != 1 or value['boot_id'] != boot_id()
                or value['deployment'] != deployment or len(data) != info.st_size):
            raise SupervisionError('Supervisor pin deployment/boot mismatch')
        bus = BusIdentity(**value['bus'])
        fence = ManagerFence(bus, value['units_load_usec'], value['manager_version'])
        mount = CgroupMount(**value['mount'])
        VerifiedCgroupReader('/sys/fs/cgroup', expected=mount)
        return fence, mount, value['boot_id']
    except (OSError, ValueError, TypeError, KeyError):
        raise SupervisionError('Supervisor pins unavailable or invalid') from None
    finally:
        if file is not None:
            os.close(file)
        os.close(fd)
