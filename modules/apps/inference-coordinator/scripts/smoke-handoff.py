#!/nix/store/3hr90mddrgkz0src1vykj19yddnjimzl-python3-3.14.8-env/bin/python -I
"""Explicit real Strata -> Ollama -> Strata commissioning, without retries.

Reads only the root-private client credential in memory. No admin operations,
credential copy/output, response-body logging or direct backend generation.
Non-loading raw residency reads independently check the coordinated handoffs.
Leave final Strata residency intact; this is not a drain/recovery command.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, '/nix/store/ixd421qmcxsq5j8rnx3a5fgp3y1s79cl-narsil-inference-coordinator-trial/lib')
from coordinator.backend_http import ControlClient
from coordinator.credentials import read_token
from coordinator.memory import read_linux_memory

STRATA_MODEL = 'qwen3.8-flash-next-coder-iq1_m'
OLLAMA_MODEL = 'gemma4:12b'
DEVICE = Path('/sys/bus/pci/devices/0000:08:00.0')


async def idle_status(client, *, owner):
    async with asyncio.timeout(10):
        while True:
            _, status = await client.request('GET', '/coordinator/status')
            if (status.get('maintenance') is not False or status.get('reconciled') is not True
                    or status.get('fault') is not None):
                raise RuntimeError('coordinator not admitting')
            queues = status.get('queues')
            if (type(queues) is not dict or set(queues) != {'strata', 'ollama'}
                    or any(q.get('length') != 0 or q.get('bytes') != 0 for q in queues.values())):
                raise RuntimeError('unexpected queued traffic')
            if status.get('active_request_id') is None:
                if status.get('owner') != owner:
                    raise RuntimeError('unexpected owner')
                return
            await asyncio.sleep(0.1)


async def smoke(client, strata, ollama):
    await idle_status(client, owner=None)
    _, health = await strata.request('GET', '/health')
    _, residents = await ollama.request('GET', '/api/ps')
    if health.get('loaded') is not False or residents.get('models') != []:
        raise RuntimeError('initial residency is not empty')
    for index, backend in enumerate(('strata', 'ollama', 'strata'), 1):
        print(f'Step {index}/3: coordinated {backend} inference (no retry)...', flush=True)
        started = time.monotonic()
        if backend == 'strata':
            _, response = await client.request('POST', '/strata/v1/chat/completions', dict(
                model=STRATA_MODEL, messages=[dict(role='user', content='Reply with READY only.')],
                max_tokens=32, stream=False))
            choices = response.get('choices')
            if (type(choices) is not list or len(choices) != 1
                    or type(choices[0].get('message')) is not dict):
                raise RuntimeError('generation response unconfirmed')
            generated = response.get('usage', {}).get('completion_tokens')
        else:
            _, response = await client.request('POST', '/ollama/api/chat', dict(
                model=OLLAMA_MODEL, messages=[dict(role='user', content='Reply with READY only.')],
                stream=False, think=False, options=dict(num_ctx=8192, num_predict=32)))
            if response.get('done') is not True or type(response.get('message')) is not dict:
                raise RuntimeError('generation response unconfirmed')
            generated = response.get('eval_count')
        if type(generated) is not int or generated <= 0:
            raise RuntimeError('nonzero inference output unconfirmed')
        await idle_status(client, owner=backend)
        _, health = await strata.request('GET', '/health')
        _, work = await strata.request('GET', '/status')
        _, residents = await ollama.request('GET', '/api/ps')
        if (health.get('model') != STRATA_MODEL or health.get('max_context') != 131072
                or work.get('busy') is not False or work.get('queued') != 0):
            raise RuntimeError('Strata profile/work mismatch')
        if backend == 'strata':
            if health.get('loaded') is not True or residents.get('models') != []:
                raise RuntimeError('exclusive Strata residency unconfirmed')
        else:
            models = residents.get('models')
            if (health.get('loaded') is not False or type(models) is not list or len(models) != 1
                    or models[0].get('name') != OLLAMA_MODEL or models[0].get('context_length') != 8192):
                raise RuntimeError('exclusive Ollama residency unconfirmed')
        memory = read_linux_memory(DEVICE)
        print(f'PASS step {index}: {backend}, {generated} tokens, exclusive residency, '
              f'{time.monotonic()-started:.1f}s; total VRAM={memory.vram_used/1024**3:.2f} GiB, '
              f'MemAvailable={memory.ram_available/1024**3:.2f} GiB', flush=True)
    print('HANDOFF CHECK PASSED. Final Strata remains loaded; no admin operations performed.', flush=True)


async def main():
    if os.geteuid() != 0:
        print('Explicit sudo required; client credential remains root-private.', file=sys.stderr)
        return 1
    try:
        token = read_token('/var/lib/inference-coordinator-secrets/client', expected_uid=0)
        async with ControlClient('http://127.0.0.1:18080', bearer_token=token, timeout=950) as client, \
                   ControlClient('http://127.0.0.1:18081', timeout=5) as strata, \
                   ControlClient('http://127.0.0.1:12434', timeout=5) as ollama:
            await smoke(client, strata, ollama)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print('HANDOFF CHECK UNCONFIRMED: ' + type(error).__name__
              + '. No retry/replay. Inspect coordinator status before further work.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
