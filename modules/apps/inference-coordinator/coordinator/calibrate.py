"""Explicit ROOT local-trial measurement; intentionally loads real models.

Never runs at build/startup. Coordinator must be stopped, no manual Strata front
 door may be listening, and all local raw-API clients are trusted/idle. This is
operator-authorized empirical tuning, not a proof of worst-case allocations.
Existing tuned Strata settings are never modified. Only successfully measured
budgets + real native oversize rejection produce a usable configuration.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import uuid

from .backend_http import ControlClient, LifecycleError
from .config import parse_config
from .lifecycle import OllamaLifecycle, OllamaProfile, StrataLifecycle
from .memory import read_linux_memory
from .operator_files import read_operator_file
from .supervision import SupervisionError
from .supervisor_rpc import SupervisorClient, _json

GIB = 1024**3
MIB = 1024**2


def derive_budget(baseline, samples, *, ram_headroom=6*GIB):
    # Explicitly approved desktop Strata floor; Ollama retains the original
    # margin. No arbitrary/zero safety margin is selectable by a client/CLI.
    if type(ram_headroom) is not int or ram_headroom not in (2*GIB, 6*GIB):
        raise SupervisionError('Unapproved calibration RAM headroom')
    if not samples:
        raise SupervisionError('Calibration has no samples')
    peak_vram = max(s.vram_used for s in samples)
    minimum_ram = min(s.ram_available for s in samples)
    cold = dict(vram_free=max(512*MIB, peak_vram-baseline.vram_used+512*MIB),
                ram_available=max(ram_headroom, baseline.ram_available-minimum_ram+ram_headroom))
    resident = dict(vram_free=512*MIB, ram_available=ram_headroom)
    if cold['vram_free'] > baseline.vram_free or cold['ram_available'] > baseline.ram_available:
        exceeded = []
        if cold['vram_free'] > baseline.vram_free:
            exceeded.append('VRAM')
        if cold['ram_available'] > baseline.ram_available:
            exceeded.append('RAM')
        # Numeric telemetry only: no prompts, backend replies, paths or secrets.
        # Keep both resources visible even when only one exceeds its boundary.
        raise SupervisionError(
            'Measured load plus safety headroom exceeds baseline availability ('
            + ', '.join(exceeded) + '); '
            f'VRAM cold required={cold["vram_free"]/MIB:.1f} MiB, '
            f'baseline free={baseline.vram_free/MIB:.1f} MiB, '
            f'peak used={peak_vram/MIB:.1f} MiB, margin=512 MiB; '
            f'RAM cold required={cold["ram_available"]/MIB:.1f} MiB, '
            f'baseline available={baseline.ram_available/MIB:.1f} MiB, '
            f'minimum observed available={minimum_ram/MIB:.1f} MiB, margin={ram_headroom/MIB:.0f} MiB')
    return dict(cold=cold, resident=resident, ram_headroom_bytes=ram_headroom,
                peak_vram_used=peak_vram,
                minimum_ram_available=minimum_ram, baseline_vram_used=baseline.vram_used,
                baseline_ram_available=baseline.ram_available)


async def _require_no_listener(port):
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', port), 1)
    except (OSError, TimeoutError):
        return
    writer.close()
    await writer.wait_closed()
    raise SupervisionError('Stop coordinator/manual Strata before calibration')


@asynccontextmanager
async def measure(device):
    samples = [read_linux_memory(device)]
    async def poll():
        while True:
            await asyncio.sleep(0.05)
            samples.append(read_linux_memory(device))
            if len(samples) > 24000:
                raise SupervisionError('Calibration sample bound exceeded')
    task = asyncio.create_task(poll())
    try:
        yield samples
    finally:
        samples.append(read_linux_memory(device))
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        if result and isinstance(result[0], Exception):
            raise SupervisionError('Calibration telemetry interrupted')


async def _settle(device, baseline):
    async with asyncio.timeout(10):
        while read_linux_memory(device).vram_used > baseline.vram_used + 256*MIB:
            await asyncio.sleep(0.2)


def _write_config(path, value):
    directory = os.open(str(Path(path).parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    file = None
    name = '.calibration-' + uuid.uuid4().hex
    try:
        info = os.fstat(directory)
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise SupervisionError('Unsafe calibration output directory')
        file = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o644, dir_fd=directory)
        os.fchmod(file, 0o644)
        data = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        while data:
            count = os.write(file, data)
            if count <= 0:
                raise SupervisionError('Calibration output write uncertain')
            data = data[count:]
        os.fsync(file)
        os.rename(name, Path(path).name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if file is not None:
            os.close(file)
        try:
            os.unlink(name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


async def calibrate(template_path, output_path, socket_path):
    if os.geteuid() != 0:
        raise SupervisionError('Explicit root calibration operator required')
    await _require_no_listener(18080)
    await _require_no_listener(8080)
    raw = read_operator_file(template_path)
    template = _json(raw)
    if type(template) is not dict or set(template) != {'configuration', 'deployment', 'device'}:
        raise SupervisionError('Invalid trial calibration template')
    device = Path(template['device'])
    configuration = copy.deepcopy(template['configuration'])
    initial = read_linux_memory(device)
    # Structural validation only, NOT admission and not injected safety callbacks.
    # Full physical capacities fill required budget fields until measurements exist.
    full = dict(vram_free=initial.vram_total, ram_available=initial.ram_total)
    for registration in configuration['backends']:
        profiles = [registration] if registration['adapter'] == 'strata' else registration['models'].values()
        for profile in profiles:
            if profile.get('cold') is not None or profile.get('resident') is not None:
                raise SupervisionError('Calibration template must not contain guessed budgets')
            profile['cold'], profile['resident'] = dict(full), dict(full)
    config = parse_config(json.dumps(configuration).encode())
    strata = next(b for b in config.backends if b.adapter == 'strata')
    ollama = next(b for b in config.backends if b.adapter == 'ollama')
    if ollama.input_policy != 'native-reject-trial' or len(ollama.models) != 1:
        raise SupervisionError('Single-model native rejection trial required')
    model, profile = next(iter(ollama.models.items()))
    quiesce = SupervisorClient(socket_path, backend=ollama.id, timeout=config.limits.lifecycle_timeout)
    observations = {}
    print('Calibrating real tuned Strata and approved Ollama; coordinator remains stopped', flush=True)
    async with ControlClient(strata.upstream, timeout=300) as sc, ControlClient(ollama.upstream, timeout=300) as oc:
        sa = StrataLifecycle(sc, model=strata.model, context=strata.context, release_timeout=120)
        async with asyncio.timeout(30):
            while True:
                try:
                    await sa.inspect()
                    _, version = await oc.request('GET', '/api/version')
                except LifecycleError:
                    await asyncio.sleep(0.2)
                    continue
                if version.get('version') != ollama.expected_version:
                    raise SupervisionError('Calibration backend version mismatch')
                break
        await sa.release()
        await quiesce()  # Real verified stop / cgroup empty / lazy restart.
        baseline = read_linux_memory(device)
        # These are conservative CALIBRATION preconditions from the existing
        # tuned 16GiB/32GiB machine, not deployable model admission budgets.
        if baseline.vram_free < baseline.vram_total - 3*GIB or baseline.ram_available < 24*GIB:
            raise SupervisionError('Close desktop applications: calibration needs nearly-idle memory')
        print('Measuring tuned Strata load and short/long text inference...', flush=True)
        try:
            async with measure(device) as samples:
                await sa.prepare('chat')
                for text in ('Reply with READY only.', 'Calibration text. ' * 2048 + '\nReply with READY only.'):
                    _, response = await sc.request('POST', '/v1/chat/completions',
                        dict(model=strata.model, messages=[dict(role='user', content=text)],
                             max_tokens=32, stream=False))
                    if not isinstance(response.get('choices'), list) or not response['choices']:
                        raise SupervisionError('Strata calibration inference failed')
            # The operator accepts 2 GiB MemAvailable for desktop Strata.
            # Headless commissioning has not been approved with this reduction.
            observations[strata.id] = derive_budget(
                baseline, samples, ram_headroom=(2*GIB if config.profile == 'desktop' else 6*GIB))
        finally:
            await sa.release()
        await _settle(device, baseline)
        baseline = read_linux_memory(device)
        if baseline.vram_free < 12*GIB or baseline.ram_available < 12*GIB:
            raise SupervisionError('Insufficient baseline for Ollama trial calibration')
        print('Measuring Gemma 4 12B at the fixed 8192 context...', flush=True)
        try:
            async with measure(device) as samples:
                # Deliberate direct measurement, not a no-op runtime memory gate.
                _, warm = await oc.request('POST', '/api/generate', dict(model=model, prompt='', stream=False,
                    keep_alive=-1, shift=False, truncate=False, options=dict(num_ctx=profile.context)))
                if warm.get('done') is not True or warm.get('done_reason') != 'load':
                    raise SupervisionError('Ollama calibration load not acknowledged')
                _, ps = await oc.request('GET', '/api/ps')
                models = ps.get('models')
                if (type(models) is not list or len(models) != 1
                        or models[0].get('name') != profile.resident_name
                        or models[0].get('context_length') != profile.context):
                    raise SupervisionError('Ollama calibration residency mismatch')
                for text in ('Reply with READY only.', 'Calibration text. ' * 2048 + '\nReply with READY only.'):
                    _, response = await oc.request('POST', '/api/chat', dict(model=model,
                        messages=[dict(role='user', content=text)], stream=False, think=False,
                        keep_alive=-1, shift=False, truncate=False,
                        options=dict(num_ctx=profile.context, num_predict=32)))
                    if response.get('done') is not True or type(response.get('message')) is not dict:
                        raise SupervisionError('Ollama calibration inference failed')
                # Multiple individually fitting messages catch history dropping;
                # raw/default generate exercise both prompt-rendering paths.
                long_text = ' '.join(f'word{i:05d}' for i in range(16000))
                cases = [('/api/chat', dict(messages=[dict(role='user', content=long_text[i:i+16000])
                           for i in range(0, len(long_text), 16000)])),
                         ('/api/generate', dict(prompt=long_text)),
                         ('/api/generate', dict(prompt=long_text, raw=True))]
                print('Verifying full-history/default/raw oversized inputs are rejected...', flush=True)
                for path, payload in cases:
                    code, response = await oc.request('POST', path, dict(model=model, **payload,
                        stream=False, think=False, keep_alive=-1, truncate=False, shift=False,
                        options=dict(num_ctx=profile.context, num_predict=1)), statuses=frozenset({200,400,413,500}))
                    error = response.get('error', '')
                    if (code == 200 or type(error) is not str or not any(s in error.lower() for s in (
                            'the prompt is longer than the context length',
                            'exceeds the available context', 'input length exceeds the context length'))):
                        raise SupervisionError('Native full-prompt oversize rejection not verified')
            observations[ollama.id] = derive_budget(baseline, samples)
        finally:
            await quiesce()  # No automatic inference retry; actual process release.
        await _settle(device, baseline)
    for registration in configuration['backends']:
        targets = [registration] if registration['adapter'] == 'strata' else registration['models'].values()
        for target in targets:
            for key in ('cold', 'resident'):
                target[key] = observations[registration['id']][key]
    parse_config(json.dumps(configuration).encode())
    result = dict(template_sha256=hashlib.sha256(raw).hexdigest(), configuration=configuration,
                  calibration=dict(device=str(device), profile=config.profile, deployment=template['deployment'],
                                   native_oversize_rejection=True, measured_at_unix=int(time.time()),
                                   observations=observations))
    _write_config(output_path, result)
    print('Measured configuration written; both backends released. Start API in maintenance, then reconcile explicitly.', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Explicit real-model local trial calibration')
    parser.add_argument('--template', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--supervisor-socket', default='/run/inference-supervisor/control.sock')
    args = parser.parse_args()
    try:
        asyncio.run(calibrate(args.template, args.output, args.supervisor_socket))
    except (Exception, KeyboardInterrupt) as error:
        detail = str(error) if isinstance(error, (SupervisionError, LifecycleError)) else type(error).__name__
        print('Calibration failed closed: ' + detail + '; no new configuration was published.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
