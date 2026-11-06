"""Read-only cgroup-v2 mount pinning; no service control or automatic pin discovery.

Requires a trusted kernel procfs at /proc in a stable, operator-owned mount/cgroup
namespace. This does not defend against root/CAP_SYS_ADMIN or prove GPU isolation.
"""
from dataclasses import dataclass
import os
import re

from .supervision import CgroupReader, SupervisionError


@dataclass(frozen=True)
class CgroupMount:
    """Operator-provisioned identity in this process's mount namespace.

    IDs are namespace/boot specific, not portable deployment configuration. A
    changed identity requires explicit revalidation, never automatic repinning.
    """
    mount_id: int
    device_major: int
    device_minor: int
    root_inode: int


def _read_proc(path: str, limit: int) -> str:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, limit + 1 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > limit:
            raise ValueError('limit')
        return data.decode('ascii')
    except (OSError, ValueError, UnicodeError):
        raise SupervisionError('Mount evidence unavailable') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unescape(value: str) -> str:
    # These are the only escapes emitted by mountinfo. Reject ambiguous input.
    if re.search(r'\\(?!040|011|012|134)', value):
        raise SupervisionError('Invalid mount evidence')
    return re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), value)


class VerifiedCgroupReader(CgroupReader):
    """CgroupReader with explicit whole-mount identity and per-open mount checks.

    Accepts only a full cgroup2 mount (mountinfo root '/'), not a bind-mounted
    delegated subtree. Verifies root inode/device, mount ID, filesystem and mount
    point before reading, checks each descendant/events descriptor against that
    mount, and rechecks mountinfo before returning, including missing groups.
    Construction has no I/O. No default identity or repinning fallback exists.
    """
    def __init__(self, root: str, *, expected: CgroupMount):
        super().__init__(root)
        if (type(expected) is not CgroupMount or not self.root
                or any(type(getattr(expected, key)) is not int
                       for key in CgroupMount.__dataclass_fields__)
                or expected.mount_id <= 0 or expected.root_inode <= 0
                or expected.device_major < 0 or expected.device_minor < 0):
            raise SupervisionError('Explicit cgroup mount identity required')
        self.expected = expected
        self.mountpoint = root

    def _validate_end(self):
        data = _read_proc('/proc/self/mountinfo', 1024 * 1024)
        matching = []
        ids = set()
        try:
            for line in data.splitlines():
                left, right = line.split(' - ')
                fields, filesystem = left.split(), right.split()
                if (len(fields) < 6 or len(filesystem) != 3
                        or not re.fullmatch(r'[1-9][0-9]*', fields[0])
                        or not re.fullmatch(r'[0-9]+:[0-9]+', fields[2])):
                    raise ValueError('shape')
                mount_id = int(fields[0])
                if mount_id in ids:
                    raise ValueError('duplicate')
                ids.add(mount_id)
                point = _unescape(fields[4])
                if mount_id == self.expected.mount_id or point == self.mountpoint:
                    matching.append((mount_id, fields[2], _unescape(fields[3]), point, filesystem[0]))
            expected = (self.expected.mount_id,
                        f'{self.expected.device_major}:{self.expected.device_minor}',
                        '/', self.mountpoint, 'cgroup2')
            if matching != [expected]:
                raise ValueError('identity')
        except (ValueError, IndexError):
            raise SupervisionError('Cgroup mount identity mismatch') from None

    def _validate_fd(self, descriptor: int):
        info = _read_proc(f'/proc/self/fdinfo/{descriptor}', 16384)
        values = [line.split(':', 1)[1].strip() for line in info.splitlines()
                  if line.startswith('mnt_id:')]
        if (len(values) != 1 or not re.fullmatch(r'[1-9][0-9]*', values[0])
                or int(values[0]) != self.expected.mount_id):
            raise SupervisionError('Cgroup descriptor mount mismatch')
        status = os.fstat(descriptor)
        if (os.major(status.st_dev), os.minor(status.st_dev)) != (
                self.expected.device_major, self.expected.device_minor):
            raise SupervisionError('Cgroup descriptor device mismatch')

    def _validate_root(self, directory: int):
        self._validate_end()
        self._validate_fd(directory)
        if os.fstat(directory).st_ino != self.expected.root_inode:
            raise SupervisionError('Cgroup mount root mismatch')
