"""Explicit Nix-store deployment file pins; no service mutations or discovery.

Trusted Nix store/root and operator-reviewed artifacts are prerequisites. This
verifies exact file identity/content, not the semantics of arbitrary commands.
The operator must pin an API-only lazy unit with no competing activation actors.
Do not use a fingerprint obtained by blessing whatever unit happens to be live.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .supervision import SupervisionError, _parts


@dataclass(frozen=True)
class StoreArtifact:
    path: str
    sha256: str

    def __post_init__(self):
        if (type(self.path) is not str or not re.fullmatch(
                r'/nix/store/[0-9a-z]{32}-[A-Za-z0-9+._?=-]+(?:/[A-Za-z0-9+._?=-]+)*', self.path)
                or not _parts(self.path) or type(self.sha256) is not str
                or not re.fullmatch(r'[0-9a-f]{64}', self.sha256)):
            raise SupervisionError('Invalid deployment artifact pin')


def verify_artifact(artifact: StoreArtifact):
    """Bounded no-symlink reads of root-owned immutable local-store files."""
    directory = descriptor = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        directory = os.open('/', flags)
        parts = _parts(artifact.path)
        for part in parts[:-1]:
            info = os.fstat(directory)
            if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise ValueError('directory')
            next_fd = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        info = os.fstat(directory)
        if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
            raise ValueError('directory')
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=directory)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_mode & 0o222 or not 0 < before.st_size <= 65536):
            raise ValueError('artifact')
        data = bytearray()
        while len(data) <= 65536:
            chunk = os.read(descriptor, min(4096, 65537 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(descriptor)
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size',
                  'st_mtime_ns', 'st_ctime_ns')
        if (any(getattr(before, key) != getattr(after, key) for key in fields)
                or len(data) != before.st_size
                or hashlib.sha256(data).hexdigest() != artifact.sha256):
            raise ValueError('artifact changed')
    except (OSError, ValueError, AttributeError):
        raise SupervisionError('Deployment artifact unavailable or mismatched') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


@dataclass(frozen=True)
class StoreUnitDeployment:
    """Reviewed unit/config artifact pins, never a semantic lazy-start detector.

    No drop-ins or generator source are allowed. FragmentPath may be the usual
    /etc symlink, but must resolve to the exact pinned store artifact; that
    artifact is independently opened without symlinks and hashed. Manager reload
    fencing and fresh policy checks are the helper's responsibility. No claims
    against privileged concurrent configuration/mount changes are made.
    """
    unit: str
    fragment: StoreArtifact
    configuration: tuple[StoreArtifact, ...]

    def __post_init__(self):
        if (type(self.unit) is not str or not re.fullmatch(
                r'[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.service', self.unit)
                or type(self.fragment) is not StoreArtifact or type(self.configuration) is not tuple
                or len(self.configuration) > 16
                or any(type(a) is not StoreArtifact for a in self.configuration)
                or len({a.path for a in (self.fragment, *self.configuration)}) != 1 + len(self.configuration)):
            raise SupervisionError('Invalid deployment manifest')

    @property
    def identity(self):
        entries = [(a.path, a.sha256) for a in (self.fragment, *self.configuration)]
        return hashlib.sha256(json.dumps([self.unit, entries], separators=(',', ':')).encode()).hexdigest()

    async def check(self, session):
        if session.unit != self.unit:
            raise SupervisionError('Deployment unit mismatch')
        evidence = await session.unit_files()
        try:
            if (type(evidence) is not dict or set(evidence) != {
                    'FragmentPath', 'SourcePath', 'DropInPaths', 'NeedDaemonReload'}
                    or evidence['SourcePath'] != '' or evidence['DropInPaths'] != ()
                    or evidence['NeedDaemonReload'] is not False
                    or type(evidence['FragmentPath']) is not str
                    or not _parts(evidence['FragmentPath'])
                    or str(Path(evidence['FragmentPath']).resolve(strict=True)) != self.fragment.path):
                raise ValueError('unit origin')
            for artifact in (self.fragment, *self.configuration):
                verify_artifact(artifact)
        except (OSError, ValueError, RuntimeError):
            raise SupervisionError('Deployment manifest mismatch') from None
        await session.check()
