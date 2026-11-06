#!/nix/store/3hr90mddrgkz0src1vykj19yddnjimzl-python3-3.14.8-env/bin/python -I
"""Retire healthy, stopped commissioning state before corrected-unit activation.

One-shot move only: no service/job mutations, journal edits, secret reads,
repinning, activation or retries. Refuses any unresolved journal intent.
"""
import asyncio
import errno
import json
import os
import socket
import stat
import subprocess
import sys

sys.path.insert(0, '/nix/store/ixd421qmcxsq5j8rnx3a5fgp3y1s79cl-narsil-inference-coordinator-trial/lib')
from coordinator.cgroup_mount import VerifiedCgroupReader
from coordinator.helper_service import parse_manifest
from coordinator.job_journal import JobJournal
from coordinator.operator_files import read_operator_file
from coordinator.provisioning import boot_id, load_pins, observe_fence, observe_mount
from coordinator.supervision import SupervisionError

SYSTEMCTL = '/nix/store/avshcbcrykiffn4vlhmz848ab69wbp9n-systemd-262/bin/systemctl'
ACTIVE = '/nix/store/5d8y0qma5g73zd3dxiz1b3v5yi4swlz5-nixos-system-narsil-26.11.20261030.1c89083'
MANIFEST = '/nix/store/jsn76jav5pdqb19dlzk77cylh1mdlb91-narsil-inference-trial-config/manifest.json'
STATE = '/var/lib/inference-supervisor'
CONFIG = '/var/lib/inference-coordinator/config.json'
ARCHIVE = '/var/lib/inference-commissioned-before-h0sksmcwdny9h3m5mfh4ikd7mh03aim1'
UNITS = ('inference-coordinator-repair.service', 'inference-coordinator.service',
         'inference-supervisor.service', 'strata.service', 'ollama.service')
FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


def stopped(value):
    if (value.get('ActiveState') not in ('inactive', 'failed')
            or value.get('MainPID') != '0' or value.get('ControlPID') != '0'
            or value.get('Job') != ''):
        raise SupervisionError('Inference unit not independently stopped')


def clean(journal):
    if journal.pending is not None:
        raise SupervisionError('Unresolved journal transaction; no retirement permitted')


async def cold(fence, mount):
    if await observe_fence() != fence or observe_mount() != mount:
        raise SupervisionError('Manager/mount fence changed')
    reader = VerifiedCgroupReader('/sys/fs/cgroup', expected=mount)
    for unit in UNITS:
        result = subprocess.run([SYSTEMCTL, 'show', unit,
            '--property=ActiveState,MainPID,ControlPID,Job'], check=True, capture_output=True,
            stdin=subprocess.DEVNULL, timeout=10, env={'LANG':'C','LC_ALL':'C'})
        stopped(dict(line.split('=', 1) for line in result.stdout.decode().splitlines()))
        if reader('/system.slice/' + unit) not in (None, False):
            raise SupervisionError('Inference cgroup remains populated')
    result = subprocess.run([SYSTEMCTL, 'list-jobs', '--no-legend', '--no-pager'],
        check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=10,
        env={'LANG':'C','LC_ALL':'C'})
    if result.stdout.strip() or result.stderr.strip():
        raise SupervisionError('Outstanding manager jobs')
    for port in (8080, 11434, 12434, 18080, 18081):
        with socket.socket() as probe:
            probe.settimeout(.2)
            if probe.connect_ex(('127.0.0.1', port)) != errno.ECONNREFUSED:
                raise SupervisionError('Inference listener present or check uncertain')
    if await observe_fence() != fence or observe_mount() != mount:
        raise SupervisionError('Fence changed during cold check')


def move_state(state, config_dir, parent):
    """Caller holds clean journal lock and verified cold boundary; never replay."""
    os.mkdir(ARCHIVE, 0o700)  # Exclusive reservation: never replace an archive.
    envelope = os.open(ARCHIVE, FLAGS | os.O_DIRECTORY)
    try:
        os.fsync(state)
        os.rename(STATE, 'supervisor', dst_dir_fd=envelope)
        os.fsync(envelope)
        os.fsync(parent)
        os.rename('config.json', 'config.json', src_dir_fd=config_dir, dst_dir_fd=envelope)
        os.fsync(config_dir)
        os.fsync(envelope)
        os.mkdir(STATE, 0o700)
        os.fsync(parent)
    finally:
        os.close(envelope)


async def retire():
    if os.geteuid() != 0 or os.path.realpath('/run/current-system') != ACTIVE:
        raise SupervisionError('Explicit root on reviewed active generation required')
    if os.path.lexists(ARCHIVE):
        raise SupervisionError('Retirement destination exists; inspect, never replay')
    os.umask(0o077)
    _, deployment, contract = parse_manifest(read_operator_file(MANIFEST))
    fence, mount, boot = load_pins(STATE, deployment=deployment.identity)
    if boot != boot_id():
        raise SupervisionError('Boot changed')
    with JobJournal(STATE + '/jobs.jsonl', unit=contract.unit, identity=deployment.identity,
            boot_id=boot, bus_identity=fence.bus, expected_uid=0,
            manager_load_usec=fence.units_load_usec, manager_version=fence.version) as journal:
        clean(journal)
        state = os.open(STATE, FLAGS | os.O_DIRECTORY)
        config_dir = os.open('/var/lib/inference-coordinator', FLAGS | os.O_DIRECTORY)
        parent = os.open('/var/lib', FLAGS | os.O_DIRECTORY)
        try:
            info = os.fstat(state)
            if (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700
                    or set(os.listdir(state)) != {'pins.json', 'jobs.jsonl'}):
                raise SupervisionError('Unexpected supervisor directory')
            # No credential content is accessed. Config is only checked and moved.
            original = read_operator_file(CONFIG)
            if type(json.loads(original)) is not dict:
                raise SupervisionError('Measured config invalid')
            await cold(fence, mount)
            await cold(fence, mount)
            clean(journal)
            named = os.stat(STATE, follow_symlinks=False)
            if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                    or read_operator_file(CONFIG) != original or boot_id() != boot):
                raise SupervisionError('State/config identity changed')
            move_state(state, config_dir, parent)
        finally:
            for fd in (state, config_dir, parent):
                os.close(fd)
    print('RETIREMENT PASSED: clean journal locked; two cold-boundary checks passed.')
    print('Old state/config moved to ' + ARCHIVE)
    print('Fresh pins/config absent. No services, activation or credentials changed.')


def main():
    try:
        asyncio.run(retire())
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print('RETIREMENT UNCONFIRMED: ' + type(error).__name__
              + '. Stop here; inspect before any retry/activation.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
