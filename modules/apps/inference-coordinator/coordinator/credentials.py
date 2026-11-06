"""Explicit Linux credential-file loading; never called by configuration parsing.

Local trusted filesystems only. No environment fallback, secret logging or writes.
This is not a secret manager or protection against the owning UID/root.
"""
from dataclasses import dataclass, field
import hmac
import os
from pathlib import PurePosixPath
import stat
import struct
from types import MappingProxyType
from typing import Mapping

from .config import Config, ConfigError, credential


class CredentialError(Exception):
    """Sanitized failure; no supplied paths, tokens or underlying OS errors."""


@dataclass(frozen=True, repr=False)
class Credentials:
    token: str = field(repr=False)
    admin_token: str | None = field(repr=False)
    backend_tokens: Mapping[str, str] = field(repr=False)

    def __repr__(self):
        return 'Credentials(<redacted>)'


def _directory(fd: int, uid: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, uid):
        raise CredentialError('Unsafe credential directory')
    # Root-owned sticky ancestors such as /tmp are allowed. O_NOFOLLOW traversal
    # and protected descendants prevent an attacker substituting a symlink/file.
    writable = info.st_mode & 0o022
    if writable and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
        raise CredentialError('Unsafe credential directory permissions')


def _file(info, uid: int, maximum: int, systemd_uid: int | None = None) -> None:
    if systemd_uid is None:
        permissions = not (stat.S_IMODE(info.st_mode) & ~0o600) and bool(info.st_mode & stat.S_IRUSR)
    else:
        # Explicit systemd snapshot policy, not a relaxed ordinary-file policy.
        permissions = (uid == 0 and info.st_gid == 0
                       and stat.S_IMODE(info.st_mode) == 0o440)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1
            or not permissions or not 0 < info.st_size <= maximum):
        raise CredentialError('Unsafe credential file metadata')


def _systemd_acl(descriptor: int, uid: int) -> bytes:
    """Exact observed Linux POSIX ACL: root + one named service UID read only.

    Read through the pinned leaf descriptor, never a pathname. The owning group,
    other users and additional named users/groups must have no access. No ACL
    absence, malformed/extra entries, generic kernel-readable fallback or
    service-group policy is accepted.
    """
    if type(uid) is not int or not 0 < uid < 0xffffffff:
        raise CredentialError('Invalid systemd credential ACL identity')
    undefined = 0xffffffff
    expected = struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in (
        (1, 4, undefined), (2, 4, uid), (4, 0, undefined),
        (16, 4, undefined), (32, 0, undefined)))
    try:
        actual = os.getxattr(descriptor, 'system.posix_acl_access')
    except OSError:
        raise CredentialError('Systemd credential ACL unavailable') from None
    if actual != expected:
        raise CredentialError('Unexpected systemd credential access ACL')
    return actual


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_token(path: str, *, expected_uid: int | None = None,
                systemd_uid: int | None = None) -> str:
    """Read one 24..4096-byte printable-ASCII token, optionally ending in one LF.

    Pin each canonical absolute path component with openat/O_NOFOLLOW; require
    trusted directories and a single-link regular 0400/0600 file owned by the
    expected UID (default effective UID). Nonblocking open prevents FIFO hangs.
    """
    uid = os.geteuid() if expected_uid is None else expected_uid
    if (type(uid) is not int or uid < 0
            or systemd_uid is not None and (uid != 0 or type(systemd_uid) is not int
                                           or not 0 < systemd_uid < 0xffffffff)):
        raise CredentialError('Invalid credential owner policy')
    directory = file_fd = None
    maximum = 4096
    try:
        credential(path)
        components = PurePosixPath(path).parts[1:]
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory = os.open('/', flags)
        directory_uid = os.geteuid() if systemd_uid is not None else uid
        _directory(directory, directory_uid)
        for component in components[:-1]:
            next_fd = os.open(component, flags, dir_fd=directory)
            os.close(directory)
            directory = next_fd
            _directory(directory, directory_uid)
        candidate = os.stat(components[-1], dir_fd=directory, follow_symlinks=False)
        _file(candidate, uid, maximum, systemd_uid)  # Refuse special files before opening them.
        file_fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                          dir_fd=directory)
        before = os.fstat(file_fd)
        _file(before, uid, maximum, systemd_uid)
        if systemd_uid is not None:
            _systemd_acl(file_fd, systemd_uid)
        if _identity(candidate) != _identity(before):
            raise CredentialError('Credential changed while opening')
        data = bytearray()
        while len(data) <= maximum:
            chunk = os.read(file_fd, maximum + 1 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        if systemd_uid is not None:
            _systemd_acl(file_fd, systemd_uid)
        after = os.fstat(file_fd)
        _file(after, uid, maximum, systemd_uid)
        if _identity(before) != _identity(after) or len(data) != after.st_size or len(data) > maximum:
            raise CredentialError('Credential changed while reading')
        if data.endswith(b'\n'):
            del data[-1:]
        if len(data) < 24 or any(not 0x21 <= byte <= 0x7e for byte in data):
            raise CredentialError('Invalid bearer credential contents')
        return data.decode('ascii')
    except CredentialError:
        raise
    except (OSError, ConfigError, ValueError, TypeError, IndexError):
        raise CredentialError('Credential could not be loaded securely') from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory is not None:
            os.close(directory)


def read_token(path: str, *, expected_uid: int | None = None) -> str:
    """Ordinary single-link owner-private 0400/0600 credential; no group read."""
    return _read_token(path, expected_uid=expected_uid)


def _load_credentials(config: Config, reader) -> Credentials:
    """All-or-nothing startup snapshot; reject equal secrets across every scope.

    No hot reload or fallback to missing/old credentials. The caller must keep
    admissions blocked on failure. Plaintext strings remain in process memory;
    Python does not provide reliable zeroization. Never serialize this object.
    """
    token = reader(config.token_file)
    admin = (reader(config.admin_token_file) if config.admin_token_file is not None else None)
    backends = {backend.id: reader(backend.credential_file)
                for backend in config.backends if backend.credential_file is not None}
    values = [token] + ([admin] if admin is not None else []) + list(backends.values())
    for index, value in enumerate(values):
        if any(hmac.compare_digest(value, previous) for previous in values[:index]):
            raise CredentialError('Credentials must be distinct across scopes')
    return Credentials(token, admin, MappingProxyType(backends))


def load_credentials(config: Config, *, expected_uid: int | None = None) -> Credentials:
    """Ordinary owner-private files; no fallback to systemd/group-readable files."""
    return _load_credentials(config, lambda path: read_token(path, expected_uid=expected_uid))


def load_systemd_credentials(config: Config, *, directory: str | None,
                             unit: str = 'inference-coordinator.service',
                             source_unit: str | None = None) -> Credentials:
    """Pinned root:root 0440 snapshots with exact read-only service-user ACL.

    The unit/name and config paths are trusted deployment inputs. Require the
    systemd-provided directory to equal its canonical expected value and every
    configured scope to be a direct child. Root and the service UID remain trusted.
    No owner-private fallback, environment secret or rotation is implemented.
    """
    import re
    source_unit = unit if source_unit is None else source_unit
    if (any(type(name) is not str or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}\.service', name)
            for name in (unit, source_unit))
            or directory != '/run/credentials/' + unit
            or os.geteuid() == 0 or os.getegid() <= 0):
        raise CredentialError('Systemd credential identity/directory unavailable')
    paths = [config.token_file]
    if config.admin_token_file is not None:
        paths.append(config.admin_token_file)
    paths.extend(b.credential_file for b in config.backends if b.credential_file is not None)
    if any(str(PurePosixPath(path).parent) != '/run/credentials/' + source_unit for path in paths):
        raise CredentialError('Credential scope outside pinned systemd directory')
    # A separately reviewed transient commissioning unit can carry the same
    # scopes under its own directory without editing the measured config.
    return _load_credentials(config, lambda path: _read_token(
        directory + '/' + PurePosixPath(path).name, expected_uid=0, systemd_uid=os.geteuid()))
