#!/nix/store/3hr90mddrgkz0src1vykj19yddnjimzl-python3-3.14.8-env/bin/python -I
"""Read-only startup-stage probe; no API bind, lifecycle, control or admissions.

Run only in the reviewed disposable systemd unit as inference-coordinator.
Never log credential contents, config bodies or arbitrary exception messages.
"""
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import stat
import struct
import sys

sys.path.insert(0, '/nix/store/ixd421qmcxsq5j8rnx3a5fgp3y1s79cl-narsil-inference-coordinator-trial/lib')
from coordinator.credentials import load_systemd_credentials
from coordinator.http import create_runner
from coordinator.memory import read_linux_memory
from coordinator.operator_files import read_operator_file
from coordinator.production import CalibratedMemory, load_calibrated
from coordinator.runtime import assemble
from coordinator.supervisor_rpc import SupervisorClient

TEMPLATE = '/nix/store/jsn76jav5pdqb19dlzk77cylh1mdlb91-narsil-inference-trial-config/template.json'
CONFIG = '/var/lib/inference-coordinator/config.json'
DEVICE = '/sys/bus/pci/devices/0000:08:00.0'
SOCKET = '/run/inference-supervisor/control.sock'


async def check():
    stage = 'identity'
    try:
        import pwd
        if os.geteuid() != pwd.getpwnam('inference-coordinator').pw_uid:
            raise RuntimeError('wrong identity')
        print('PASS service identity', flush=True)
        stage = 'root-owned config/template read'
        raw, template = read_operator_file(CONFIG), read_operator_file(TEMPLATE)
        print('PASS ' + stage, flush=True)
        stage = 'measured config validation'
        config = load_calibrated(raw, template, DEVICE)
        print('PASS ' + stage, flush=True)
        stage = 'credential snapshot metadata'
        directory = os.environ.get('CREDENTIALS_DIRECTORY')
        if directory != '/run/credentials/inference-startup-check.service':
            raise RuntimeError('unexpected credential directory')
        for name in ('client', 'admin'):
            info = os.stat(str(Path(directory) / name), follow_symlinks=False)
            print(f'METADATA {name}: uid={info.st_uid}, gid={info.st_gid}, '
                  f'service_gid={os.getegid()}, mode={stat.S_IMODE(info.st_mode):04o}, '
                  f'nlink={info.st_nlink}, regular={stat.S_ISREG(info.st_mode)}', flush=True)
            # POSIX access ACL is metadata, not secret contents. Inspect exact
            # kernel permissions before selecting another acceptance policy.
            path = str(Path(directory) / name)
            acl = os.getxattr(path, 'system.posix_acl_access', follow_symlinks=False)
            if len(acl) > 256 or len(acl) < 4 or (len(acl)-4) % 8:
                raise RuntimeError('invalid ACL metadata')
            version = struct.unpack_from('<I', acl)[0]
            entries = [struct.unpack_from('<HHI', acl, offset)
                       for offset in range(4, len(acl), 8)]
            print(f'METADATA {name}: acl_version={version}, acl_entries={entries}, '
                  f'kernel_readable={os.access(path, os.R_OK, effective_ids=True)}', flush=True)
        # Use this disposable unit's snapshots, not the failed service's path.
        config = replace(config, token_file=directory + '/client', admin_token_file=directory + '/admin')
        stage = 'secure credential snapshot load'
        credentials = load_systemd_credentials(config, directory=directory,
                                               unit='inference-startup-check.service')
        print('PASS ' + stage, flush=True)
        stage = 'real runtime construction (no I/O)'
        quiescence = {b.id: SupervisorClient(SOCKET, backend=b.id,
                                            timeout=config.limits.lifecycle_timeout - 5)
                      for b in config.backends if b.adapter == 'ollama'}
        runtime = assemble(config, credentials, memory=CalibratedMemory(DEVICE),
                           counters={}, quiescence=quiescence)
        create_runner(runtime.app)  # No setup/bind/cleanup: cleanup would drain.
        print('PASS ' + stage, flush=True)
        stage = 'read-only memory telemetry'
        read_linux_memory(Path(DEVICE))
        print('PASS ' + stage, flush=True)
        stage = 'supervisor socket permissions (no connection)'
        info = os.stat(SOCKET, follow_symlinks=False)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or not os.access(SOCKET, os.W_OK):
            raise RuntimeError('socket unavailable')
        print('PASS ' + stage, flush=True)
        print('CHECK PASSED: no backend/API calls, listener, admission or state mutation.', flush=True)
        return 0
    except Exception as error:
        print('CHECK FAILED at ' + stage + ': ' + type(error).__name__ + '; no secret values logged.',
              file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(check()))
