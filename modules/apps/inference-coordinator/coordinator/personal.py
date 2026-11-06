"""Personal-use service: in-memory queues, ordinary systemctl, reset on startup.

No journal, manager pins, calibration envelope or automatic request replay.
Only restart of the two backend units is authorized through a narrow polkit rule.
"""
import argparse
import asyncio
import logging
import os
import signal
import secrets
import stat
import time
import tempfile
from pathlib import Path

from aiohttp import web

from .backend_http import ControlClient, LifecycleError
from .config import parse_config
from .credentials import load_systemd_credentials, read_token
from .diagnostics import event, failure
from .http import create_runner
from .gateway import install_gateway
from .memory import MemoryRequirement, read_linux_memory, wait_for_memory
from .operator_files import read_operator_file
from .runtime import assemble


class SystemdBackends:
    def __init__(self, executable, *, timeout=240):
        self.executable, self.timeout = executable, timeout

    async def restart(self, unit, origin, ready_path):
        if unit not in ('strata.service', 'ollama.service'):
            raise ValueError('Unsupported backend unit')
        started = time.monotonic()
        event('backend_restart_begin', unit=unit)
        process = None
        stderr = tempfile.TemporaryFile()
        try:
            async with asyncio.timeout(self.timeout):
                process = await asyncio.create_subprocess_exec(
                    self.executable, '--no-ask-password', 'restart', unit,
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=stderr,
                    env={'LANG':'C', 'LC_ALL':'C'})
                code = await process.wait()
                if code:
                    stderr.seek(0)
                    event('backend_systemctl_failed', level=logging.ERROR, unit=unit, exit_code=code,
                          detail=stderr.read(4096).decode('utf-8', errors='replace'),
                          hint='Check backend journal and polkit authorization')
                    raise LifecycleError('Backend restart failed')
                # systemctl restart awaits stop/start, including control-group teardown.
                # API readiness may lag Type=exec startup. No model warmup here.
                async with ControlClient(origin, timeout=3) as client:
                    while True:
                        try:
                            await client.request('GET', ready_path)
                            break
                        except LifecycleError:
                            await asyncio.sleep(.25)
        except BaseException as error:
            failure('backend_restart_failed', error, unit=unit,
                    elapsed_seconds=round(time.monotonic()-started, 3))
            raise
        finally:
            if process is not None and process.returncode is None:
                # Killing this client does not claim the systemd job was cancelled.
                process.kill()
                await process.wait()
            stderr.close()
        event('backend_restart_complete', unit=unit,
              elapsed_seconds=round(time.monotonic()-started, 3))

    async def reset_strata(self):
        await self.restart('strata.service', 'http://127.0.0.1:18081', '/health')

    async def reset_ollama(self):
        await self.restart('ollama.service', 'http://127.0.0.1:12434', '/api/version')


class MemoryAdmission:
    def __init__(self, device):
        self.device = Path(device)

    async def check(self, backend, *, model, context, resident):
        if backend.adapter == 'strata':
            if model != backend.model or context != backend.context:
                raise ValueError('Unsupported Strata profile')
            profile = backend
        else:
            profile = backend.models.get(model)
            if profile is None or profile.context != context:
                raise ValueError('Unsupported Ollama profile')
        budget = profile.resident if resident else profile.cold
        def sample():
            memory = read_linux_memory(self.device)
            event('memory_admission', backend=backend.id, model=model, context=context, resident=resident,
                  ram_available_bytes=memory.ram_available, vram_free_bytes=memory.vram_free,
                  required_ram_bytes=budget.ram_available, required_vram_bytes=budget.vram_free)
            return memory
        await wait_for_memory(sample, MemoryRequirement(budget.vram_free, budget.ram_available),
                              timeout=5, poll_interval=1)


async def serve(config_path, device, systemctl, port, *, gateway_port=8081):
    config = parse_config(read_operator_file(config_path))
    credentials = load_systemd_credentials(config, directory=os.environ.get('CREDENTIALS_DIRECTORY'),
                                          unit='inference-coordinator.service',
                                          source_unit='inference-coordinator.service')
    controls = SystemdBackends(systemctl)
    runtime = assemble(config, credentials, memory=MemoryAdmission(device), counters={},
        quiescence={b.id:controls.reset_ollama for b in config.backends if b.adapter=='ollama'})
    install_gateway(runtime.app,credentials.token,port=gateway_port)
    runner = create_runner(runtime.app)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    # Keep backend lifecycle clients open during reset and shutdown.
    try:
        await runner.setup()
        event('startup_reset_begin', profile=config.profile)
        await controls.reset_strata()  # Kill work left by a previous router process.
        await runtime.scheduler.reconcile()  # Unload Strata and restart/empty Ollama.
        runtime.scheduler.resume()
        await web.TCPSite(runner, '127.0.0.1', port, backlog=32).start()
        await web.TCPSite(runner, '0.0.0.0', gateway_port, backlog=32).start()
        event('service_ready', port=port, gateway_port=gateway_port, profile=config.profile, admissions=True)
        await stop.wait()
    finally:
        event('shutdown_begin', requests_may_fail=True)
        try:
            async with asyncio.timeout(25):
                await runner.cleanup()
        except Exception as error:
            failure('shutdown_cleanup_incomplete', error,
                    hint='Next startup resets both backends; in-flight requests are not recovered')
        event('shutdown_complete')


SECRETS = '/var/lib/inference-coordinator-secrets'


def credential(name):
    if name not in ('client', 'admin'):
        raise ValueError('Unknown credential scope')
    return read_token(SECRETS + '/' + name, expected_uid=0)


def provision_credentials():
    directory = os.open(SECRETS, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(directory)
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Root-private credential directory required')
        for name in ('client', 'admin'):
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=directory)
            except FileExistsError:
                credential(name)  # Reuse, never rotate.
                continue
            try:
                data = (secrets.token_urlsafe(48) + '\n').encode('ascii')
                if os.write(fd, data) != len(data):
                    raise OSError('Credential write incomplete')
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(directory)
        if credential('client') == credential('admin'):
            raise ValueError('Credential scopes overlap')
    finally:
        os.close(directory)


async def control(operation):
    admin = operation != 'status'
    path = '/coordinator/admin/' + operation if admin else '/coordinator/status'
    async with ControlClient('http://127.0.0.1:18080', bearer_token=credential('admin' if admin else 'client'),
                             timeout=910) as client:
        _, value = await client.request('POST' if admin else 'GET', path)
    import json
    print(json.dumps(value, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Personal-use coordinated inference service')
    parser.add_argument('operation', choices=('serve','credentials','status','drain','reconcile','resume'))
    parser.add_argument('--config')
    parser.add_argument('--device', default='/sys/bus/pci/devices/0000:08:00.0')
    parser.add_argument('--systemctl', default='/run/current-system/sw/bin/systemctl')
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        if args.operation == 'credentials':
            provision_credentials()  # Existing tokens reused; never printed/rotated.
        elif args.operation == 'serve':
            if not args.config or not 1024 <= args.port <= 65535:
                parser.error('serve requires --config and an unprivileged port')
            asyncio.run(serve(args.config, args.device, args.systemctl, args.port))
        else:
            asyncio.run(control(args.operation))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        failure('service_failed', error, operation=args.operation)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
