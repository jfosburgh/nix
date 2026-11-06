"""Explicit local operator commands. No activation, mode changes or auto-resume.

`prepare` provisions NEW supervisor state/credentials, performs real calibration
and starts the protected API in maintenance. It never clears existing uncertainty.
Control commands never retry and never print secrets or inference bodies.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

from aiohttp import ClientSession, ClientTimeout, DummyCookieJar

from .calibrate import calibrate
from .backend_http import LifecycleError
from .memory import MemoryAdmissionError
from .helper_service import run as supervisor_run
from .operator_files import read_operator_file
from .supervision import SupervisionError
from .supervisor_rpc import _json

STATE = '/var/lib/inference-supervisor'
CONFIG = '/var/lib/inference-coordinator/config.json'
SECRETS = '/var/lib/inference-coordinator-secrets'
SOCKET = '/run/inference-supervisor/control.sock'
SYSTEMCTL = '/run/current-system/sw/bin/systemctl'


def _credential(name):
    raw = read_operator_file(SECRETS + '/' + name, limit=4096)
    value = raw.decode('ascii').removesuffix('\n')
    if not 24 <= len(value) <= 4096 or any(not 0x21 <= ord(c) <= 0x7e for c in value):
        raise SupervisionError('Invalid operator credential')
    return value


def provision_credentials():
    directory = os.open(SECRETS, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(directory)
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise SupervisionError('Private root secret directory required')
        for name in ('client', 'admin'):
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=directory)
            except FileExistsError:
                _credential(name)  # Never replace or silently rotate.
                continue
            try:
                data = (secrets.token_urlsafe(48) + '\n').encode('ascii')
                count = os.write(fd, data)
                if count != len(data):
                    raise SupervisionError('Credential provisioning write uncertain')
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(directory)
        if _credential('client') == _credential('admin'):
            raise SupervisionError('Credential scopes overlap')
    finally:
        os.close(directory)


def _systemctl(*args):
    return subprocess.run([SYSTEMCTL, *args], stdin=subprocess.DEVNULL, capture_output=True,
                          env={'LANG': 'C', 'LC_ALL': 'C'}, timeout=60, check=True)


async def prepare(manifest, template):
    value = _json(read_operator_file(template))
    expected = value['configuration']['profile']
    current = Path('/etc/narsil-mode').read_text().strip()
    if current != expected or not Path('/etc/narsil-inference-trial').is_file():
        raise SupervisionError('Activate the matching trial generation first; no mode switching here')
    if Path(STATE, 'pins.json').exists() or Path(STATE, 'jobs.jsonl').exists():
        raise SupervisionError('Existing supervisor state requires explicit recovery, not prepare')
    if Path(CONFIG).exists():
        raise SupervisionError('Existing calibrated configuration requires explicit operator review')
    print('Preparing local trial: real model allocations will be measured; no mode/session changes.', flush=True)
    provision_credentials()
    await asyncio.to_thread(_systemctl, 'start', 'strata.service', 'ollama.service')
    await supervisor_run('provision', manifest, STATE, SOCKET)
    await asyncio.to_thread(_systemctl, 'start', 'inference-supervisor.service')
    await calibrate(template, CONFIG, SOCKET)
    await asyncio.to_thread(_systemctl, 'start', 'inference-coordinator.service')
    print('API started in maintenance. Run: sudo narsil-inference reconcile; then sudo narsil-inference resume', flush=True)


async def control(operation):
    admin = operation != 'status'
    token = _credential('admin' if admin else 'client')
    path = '/coordinator/admin/' + operation if admin else '/coordinator/status'
    async with ClientSession(trust_env=False, auto_decompress=False, cookie_jar=DummyCookieJar(),
                              timeout=ClientTimeout(total=920)) as client:
        async with client.request('POST' if admin else 'GET', 'http://127.0.0.1:18080' + path,
                                   headers={'Authorization': 'Bearer ' + token}, allow_redirects=False) as response:
            data = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                data.extend(chunk)
                if len(data) > 65536:
                    raise SupervisionError('Operator response limit exceeded')
            value = _json(bytes(data))
            if response.status != 200:
                raise SupervisionError('Operator control unconfirmed; inspect status before retrying')
            print(json.dumps(value, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Explicit protected local inference trial controls')
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--template', required=True)
    parser.add_argument('operation', choices=('prepare', 'status', 'drain', 'reconcile', 'resume', 'calibrate'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        print('Use sudo for this operator command; inference clients use the separate client credential.', file=sys.stderr)
        return 1
    try:
        if args.operation == 'prepare':
            asyncio.run(prepare(args.manifest, args.template))
        elif args.operation == 'calibrate':
            asyncio.run(calibrate(args.template, CONFIG, SOCKET))
        else:
            asyncio.run(control(args.operation))
    except (Exception, KeyboardInterrupt) as error:
        detail = str(error) if isinstance(error, (SupervisionError, LifecycleError, MemoryAdmissionError)) else type(error).__name__
        print('Operator action failed closed: ' + detail + '. No automatic retry or uncertainty reset.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
