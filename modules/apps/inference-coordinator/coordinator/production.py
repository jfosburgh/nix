"""Loopback-only local-trial entrypoint. No automatic reconcile or resume.

Requires an operator-calibrated root-owned configuration, separate systemd
credentials and the real privileged supervisor socket. Unsupported policies fail
closed; synthetic counters/providers are never selectable. systemd watchdog and
TimeoutStopSec provide the outer process/cgroup shutdown boundary.
"""
import argparse
import asyncio
import os
from pathlib import Path
import signal
import sys

from aiohttp import web

from .config import parse_config
from .credentials import load_systemd_credentials
from .helper_service import _notify, _watchdog
from .http import create_runner
from .memory import MemoryRequirement, read_linux_memory, wait_for_memory
from .operator_files import read_operator_file
from .runtime import assemble
from .supervisor_rpc import SupervisorClient


class CalibratedMemory:
    """Exact-profile measured budgets only; never infer context scaling."""
    def __init__(self, device):
        self.device = Path(device)

    async def check(self, backend, *, model, context, resident):
        if backend.adapter == 'strata':
            if model != backend.model or context != backend.context:
                raise ValueError('Uncalibrated Strata profile')
            budget = backend.resident if resident else backend.cold
        else:
            profile = backend.models.get(model)
            if profile is None or profile.context != context:
                raise ValueError('Uncalibrated Ollama profile')
            budget = profile.resident if resident else profile.cold
        await wait_for_memory(lambda: read_linux_memory(self.device),
                              MemoryRequirement(budget.vram_free, budget.ram_available), timeout=5)


def load_calibrated(raw, template_raw, device):
    import copy
    import hashlib
    import json
    from .supervisor_rpc import _json
    envelope, template = _json(raw), _json(template_raw)
    if (type(envelope) is not dict or set(envelope) != {'template_sha256', 'configuration', 'calibration'}
            or type(template) is not dict or set(template) != {'configuration', 'deployment', 'device'}
            or envelope['template_sha256'] != hashlib.sha256(template_raw).hexdigest()):
        raise ValueError('Calibration/configuration does not match this generation')
    calibration = envelope['calibration']
    if (type(calibration) is not dict or set(calibration) != {'device', 'profile', 'deployment',
            'native_oversize_rejection', 'measured_at_unix', 'observations'}
            or calibration['device'] != device or template['device'] != device
            or calibration['deployment'] != template['deployment']
            or calibration['profile'] != template['configuration']['profile']
            or calibration['native_oversize_rejection'] is not True
            or type(calibration['measured_at_unix']) is not int or calibration['measured_at_unix'] <= 0):
        raise ValueError('Required local calibration/rejection evidence missing')
    expected = copy.deepcopy(template['configuration'])
    observations = calibration['observations']
    if type(observations) is not dict or set(observations) != {b['id'] for b in expected['backends']}:
        raise ValueError('Calibration backend mismatch')
    for backend in expected['backends']:
        targets = [backend] if backend['adapter'] == 'strata' else backend['models'].values()
        for target in targets:
            if target.get('cold') is not None or target.get('resident') is not None:
                raise ValueError('Calibration template contains unmeasured budgets')
            target['cold'] = observations[backend['id']]['cold']
            target['resident'] = observations[backend['id']]['resident']
    if envelope['configuration'] != expected:
        raise ValueError('Measured configuration differs from reviewed template')
    return parse_config(json.dumps(expected, separators=(',', ':')).encode())


async def serve(config_path, template_path, device, socket_path, port, *,
                credential_unit='inference-coordinator.service'):
    config = load_calibrated(read_operator_file(config_path), read_operator_file(template_path), device)
    if any(b.input_policy != 'native-reject-trial' for b in config.backends if b.adapter == 'ollama'):
        raise ValueError('Production counters are not implemented; explicit native trial required')
    credentials = load_systemd_credentials(
        config, directory=os.environ.get('CREDENTIALS_DIRECTORY'), unit=credential_unit,
        source_unit='inference-coordinator.service')
    quiescence = {b.id: SupervisorClient(socket_path, backend=b.id,
                                        timeout=config.limits.lifecycle_timeout - 5)
                  for b in config.backends if b.adapter == 'ollama'}
    runtime = assemble(config, credentials, memory=CalibratedMemory(device), counters={}, quiescence=quiescence)
    runner = create_runner(runtime.app)
    heartbeat = asyncio.create_task(_watchdog())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', port, backlog=32)
        await site.start()
        _notify('READY=1')
        print('Local inference API ready in maintenance; explicit reconcile/resume required', flush=True)
        await stop.wait()
    finally:
        try:
            # Cooperative deadline; systemd's TimeoutStopSec is the hard outer
            # bound. Restart always requires fresh all-backend reconciliation.
            async with asyncio.timeout(25):
                await runner.cleanup()
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description='Protected loopback inference API trial')
    parser.add_argument('--config', required=True)
    parser.add_argument('--template', required=True)
    parser.add_argument('--device', required=True)
    parser.add_argument('--supervisor-socket', default='/run/inference-supervisor/control.sock')
    parser.add_argument('--port', type=int, default=18080)
    parser.add_argument('--credential-unit', default='inference-coordinator.service',
                        help='Explicit reviewed systemd snapshot unit; no file/token fallback')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('unprivileged listener port required')
    try:
        asyncio.run(serve(args.config, args.template, args.device, args.supervisor_socket, args.port,
                          credential_unit=args.credential_unit))
    except (Exception, KeyboardInterrupt):
        print('Inference API failed closed; inspect calibration/supervisor/configuration', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
