#!/usr/bin/env python3
"""Capture small identity files without stopping networking or printing secrets."""
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys

ROOT_UID = 0
SOURCE_ROOT = Path('/')
DEFAULT_SSH_KEYS = ['/etc/ssh/ssh_host_ed25519_key', '/etc/ssh/ssh_host_rsa_key']
MAX_FILE_SIZE = 64 * 1024 * 1024


def require_directory(original, exact_mode=None):
    path = SOURCE_ROOT / original.lstrip('/')
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022:
        raise ValueError('Unsafe machine-recovery source directory')
    if exact_mode is not None and stat.S_IMODE(info.st_mode) != exact_mode:
        raise ValueError('Incorrect credential directory permissions')


def read_private(original):
    """An open FD stays on the complete old inode across an atomic rename."""
    path = SOURCE_ROOT / original.lstrip('/')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        before = os.fstat(source.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != ROOT_UID
                or stat.S_IMODE(before.st_mode) not in (0o400, 0o600)
                or not 0 < before.st_size <= MAX_FILE_SIZE):
            raise ValueError('Missing, insecure, empty or oversized identity/credential file')
        contents = source.read(MAX_FILE_SIZE + 1)
        after = os.fstat(source.fileno())
        # nlink/ctime can change when the daemon replaces the source inode.
        if (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                or len(contents) != before.st_size):
            raise ValueError('Identity file changed in place during capture')
        return contents


def write_private(path, contents):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('xb') as destination:
        destination.write(contents)
    path.chmod(0o600)


def capture(destination):
    if not destination.is_absolute() or destination.parent.is_symlink():
        raise ValueError('Expected an absolute private staging destination')
    parent = destination.parent.stat()
    if parent.st_uid != ROOT_UID or stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError('Expected root-only staging parent')
    # Never overwrite or clean up a pre-existing directory/symlink.
    destination.mkdir(mode=0o700)
    try:
        keys = json.loads(os.environ.get('BLADE_SSH_HOST_KEYS', json.dumps(DEFAULT_SSH_KEYS)))
        if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
            raise ValueError('Expected configured SSH host-key paths')
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate SSH host-key paths')
        for key in keys:
            source = Path(key)
            if not source.is_absolute() or '..' in source.parts:
                raise ValueError('Invalid SSH host-key path')
            require_directory(str(source.parent))
            copied = destination / source.relative_to('/')
            write_private(copied, read_private(key))
            # Derive the matching public key from the captured private key,
            # avoiding a rotation race between separate private/public files.
            result = subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', str(copied)],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=15, check=True)
            if not result.stdout.strip():
                raise ValueError('Invalid captured SSH host key')
            write_private(Path(str(copied) + '.pub'), result.stdout)

        require_directory('/var/lib/tailscale')
        state = read_private('/var/lib/tailscale/tailscaled.state')
        decoded = json.loads(state)
        if not isinstance(decoded, dict) or not isinstance(decoded.get('_machinekey'), str) or not decoded['_machinekey']:
            raise ValueError('Expected Linux file-store Tailscale identity JSON')
        write_private(destination / 'var/lib/tailscale/tailscaled.state', state)

        require_directory('/var/lib/restic-secrets', 0o700)
        require_directory('/var/lib/restic-secrets/pinas', 0o700)
        for name in ('rest-password', 'critical-password', 'media-password'):
            original = '/var/lib/restic-secrets/pinas/' + name
            write_private(destination / original.lstrip('/'), read_private(original))

        write_private(destination / 'README.txt', b'''MACHINE RECOVERY: SENSITIVE ROOT-ONLY MATERIAL
Files retain their original absolute paths relative to this directory.
Contains SSH host private keys, Tailscale node identity and Restic credentials.
Activate identities ONLY on a replacement Blade after the original is offline.
Never activate these identities in test sandboxes or on a second running node.
Stop tailscaled before restoring its state; preserve root-only permissions.
Do not blindly overwrite identities/credentials on an existing installation.
Restic passwords here are NOT independent recovery: keep the critical repository
password and repository-access instructions OUTSIDE this encrypted repository.
No personal home files, ACME state, Tailscale logs/caches or SSH user keys included.
''')
    except BaseException:
        shutil.rmtree(destination)
        raise


def main():
    os.umask(0o077)
    if os.geteuid() != ROOT_UID or socket.gethostname() != 'blade':
        raise ValueError('Run as root on Blade')
    if len(sys.argv) != 2:
        raise ValueError('Expected a new private staging destination')
    capture(Path(sys.argv[1]))
    print('Captured root-only machine recovery bundle; SSH and Tailscale were not stopped.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError):
        # Never include parsed JSON, key contents, or command output in errors.
        print('Machine recovery capture failed; check required source files and private permissions.', file=sys.stderr)
        sys.exit(1)
