#!/nix/store/3hr90mddrgkz0src1vykj19yddnjimzl-python3-3.14.8-env/bin/python -I
"""One-off evidence-preserving abandonment of the first submitted stop.

No service mutations, intent acknowledgement, credential access or automatic
provisioning. Root must first explicitly stop every trial service. This script
is deliberately pinned to the reviewed build, boot and exact journal below.
Use --check first, then separately --archive. No retry after uncertain failure.
"""
import argparse
import asyncio
import errno
import fcntl
import json
import os
import socket
import stat
import subprocess
import sys

# Immutable reviewed dependencies; never import root code from the working tree.
sys.path.insert(0, '/nix/store/b0j1c2drplxqa0x4vb4l43fqypbd53a0-narsil-inference-coordinator-trial/lib')
from coordinator.cgroup_mount import VerifiedCgroupReader
from coordinator.provisioning import boot_id, load_pins, observe_fence, observe_mount
from coordinator.supervision import SupervisionError
from coordinator.systemd_inspect import SystemdInspector

DEPLOYMENT = '2a6f33e568235c36d64c44954ad5b76baab12dbba22598e995df70e0178a0b85'
NONCE = '3b204dbc33fe4571a7d0b0466bb1bee5'
STATE = 'inference-supervisor'
ARCHIVE = 'inference-supervisor.abandoned-' + NONCE
SYSTEMD = '/nix/store/avshcbcrykiffn4vlhmz848ab69wbp9n-systemd-262/bin/'
UNITS = ('inference-coordinator.service', 'inference-supervisor.service', 'strata.service', 'ollama.service')
EXPECTED = (
    '{"boot_id":"f06ec7e2c2c3478698e5e3fa016ba256","bus_id":"13b8c6902a0b0dd79e6ecf1f3b9010fb","identity":"' + DEPLOYMENT + '","manager_load_usec":453106989790,"manager_owner":":1.598","manager_version":"262","unit":"ollama.service","version":3}\n'
    '{"event":"begin","intent":{"action":"stop","job_id":null,"nonce":"' + NONCE + '","result":null}}\n'
    '{"event":"submitted","intent":{"action":"stop","job_id":60919,"nonce":"' + NONCE + '","result":null}}\n'
).encode('ascii')
FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


def private_directory(fd, *, owner=0):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o700:
        raise SupervisionError('Private state directory required')
    return info


def locked_journal(state, *, owner=0):
    fd = os.open('jobs.jsonl', FLAGS | os.O_NONBLOCK, dir_fd=state)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != len(EXPECTED)):
            raise SupervisionError('Unexpected journal metadata')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.read(fd, len(EXPECTED) + 1) != EXPECTED:
            raise SupervisionError('Not the reviewed unresolved stop journal')
        return fd
    except BaseException:
        os.close(fd)
        raise


def unchanged(parent, state, journal, pins, *, owner=0):
    info = private_directory(state, owner=owner)
    named = os.stat(STATE, dir_fd=parent, follow_symlinks=False)
    if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
        raise SupervisionError('State directory changed')
    if set(os.listdir(state)) != {'pins.json', 'jobs.jsonl'}:
        raise SupervisionError('Unexpected state directory contents')
    for name, fd in (('jobs.jsonl', journal), ('pins.json', pins)):
        opened = os.fstat(fd)
        named = os.stat(name, dir_fd=state, follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != owner or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != 0o600
                or any(getattr(opened, key) != getattr(named, key) for key in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
            raise SupervisionError('State file changed or unsafe')
    if os.pread(journal, len(EXPECTED) + 1, 0) != EXPECTED:
        raise SupervisionError('Journal changed')
    try:
        os.stat(ARCHIVE, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise SupervisionError('Archive already exists; no replacement')


def archive(parent, state, journal, pins, *, owner=0):
    """Only filesystem mutation phase. Caller must hold verified cold boundary.

    Reserve a new private envelope atomically; move the original whole directory
    inside it without copying/editing. Any partial failure stays for inspection.
    Never delete an archive or roll back/retry an uncertain rename.
    """
    unchanged(parent, state, journal, pins, owner=owner)
    os.fsync(journal)
    os.fsync(pins)
    os.fsync(state)
    os.mkdir(ARCHIVE, mode=0o700, dir_fd=parent)
    envelope = os.open(ARCHIVE, FLAGS | os.O_DIRECTORY, dir_fd=parent)
    try:
        private_directory(envelope, owner=owner)
        os.fsync(parent)
        os.rename(STATE, 'state', src_dir_fd=parent, dst_dir_fd=envelope)
        os.fsync(envelope)
        os.fsync(parent)
        os.mkdir(STATE, mode=0o700, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(envelope)


async def cold_boundary(fence, mount):
    if await observe_fence() != fence or observe_mount() != mount:
        raise SupervisionError('Provisioned manager/mount identity changed')
    reader = VerifiedCgroupReader('/sys/fs/cgroup', expected=mount)
    for unit in UNITS:
        evidence = await SystemdInspector(executable=SYSTEMD + 'busctl', unit=unit,
                                          expected_bus=fence.bus).inspect()
        if (evidence.active not in ('inactive', 'failed')
                or any((evidence.main_pid, evidence.control_pid, evidence.job_id,
                        evidence.control_group, evidence.triggered_by, evidence.delegated))
                or evidence.restart != 'no' or evidence.kill_mode != 'control-group'):
            raise SupervisionError('Trial unit not independently stopped: ' + unit)
        if reader('/system.slice/' + unit) not in (None, False):
            raise SupervisionError('Trial cgroup remains populated: ' + unit)
    result = subprocess.run([SYSTEMD + 'systemctl', 'list-jobs', '--no-legend', '--no-pager'],
                            stdin=subprocess.DEVNULL, capture_output=True,
                            env={'LANG': 'C', 'LC_ALL': 'C'}, timeout=10, check=True)
    if result.stdout.strip() or result.stderr.strip():
        raise SupervisionError('Outstanding systemd jobs or invalid inventory')
    # No listener, including manual Strata or an already-started protected API.
    for port in (8080, 11434, 12434, 18080, 18081):
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(('127.0.0.1', port)) != errno.ECONNREFUSED:
                raise SupervisionError('Inference listener present or check uncertain')
    # No published config (including a dangling symlink), and no archive replay.
    if os.path.lexists('/var/lib/inference-coordinator/config.json'):
        raise SupervisionError('Measured configuration exists; wrong recovery case')
    if await observe_fence() != fence or observe_mount() != mount:
        raise SupervisionError('Identity changed during cold-boundary observation')


def parent_directory():
    fd = os.open('/', FLAGS | os.O_DIRECTORY)
    try:
        for component in ('var', 'lib'):
            child = os.open(component, FLAGS | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise SupervisionError('Unsafe state ancestor')
        return fd
    except BaseException:
        os.close(fd)
        raise


async def run(do_archive):
    if os.geteuid() != 0:
        raise SupervisionError('Explicit root operator required')
    os.umask(0o077)
    parent = parent_directory()
    state = journal = pins = None
    try:
        state = os.open(STATE, FLAGS | os.O_DIRECTORY, dir_fd=parent)
        private_directory(state)
        journal = locked_journal(state)
        pins = os.open('pins.json', FLAGS | os.O_NONBLOCK, dir_fd=state)
        unchanged(parent, state, journal, pins)
        pin_bytes = os.pread(pins, 4097, 0)
        fence, mount, boot = load_pins('/var/lib/' + STATE, deployment=DEPLOYMENT)
        header = json.loads(EXPECTED.splitlines()[0])
        if (boot != boot_id() or boot != header['boot_id']
                or fence.bus.bus_id != header['bus_id']
                or fence.bus.manager_owner != header['manager_owner']
                or fence.units_load_usec != header['manager_load_usec']
                or fence.version != header['manager_version']):
            raise SupervisionError('Pins do not match reviewed journal identity')
        # Two passes, under one retained journal lock; never start/stop a service.
        await cold_boundary(fence, mount)
        await cold_boundary(fence, mount)
        unchanged(parent, state, journal, pins)
        if boot != boot_id() or os.pread(pins, 4097, 0) != pin_bytes:
            raise SupervisionError('Boot or pins changed')
        if do_archive:
            archive(parent, state, journal, pins)
            print('Original unresolved evidence preserved at /var/lib/' + ARCHIVE + '/state')
            print('Fresh private state directory created. No services started; no pins provisioned.')
        else:
            print('CHECK PASSED: exact unresolved journal locked; pins and two cold-boundary passes verified.')
            print('No state changed. Separate --archive authorization is required.')
    finally:
        for fd in (pins, journal, state, parent):
            if fd is not None:
                os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--archive', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.archive))
    except (Exception, KeyboardInterrupt) as error:
        detail = str(error) if isinstance(error, SupervisionError) else type(error).__name__
        print('Cold reset stopped: ' + detail + '. Do not retry or clear state; inspect first.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
