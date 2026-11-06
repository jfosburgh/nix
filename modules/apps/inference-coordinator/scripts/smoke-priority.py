#!/nix/store/3hr90mddrgkz0src1vykj19yddnjimzl-python3-3.14.8-env/bin/python -I
"""Real nonpreemptive priority/FIFO commissioning. No admin calls or retries.

With Ollama active, enqueue O-1, O-2 before S-1, S-2. Observe the actual queue
counts under that same active request ID, then require O-active,S-1,S-2,O-1,O-2.
Restore Strata afterward. Only synthetic prompts; never log bodies/credentials.
"""
import asyncio
import importlib.util
import json
import os
import sys

sys.path.insert(0, '/nix/store/ixd421qmcxsq5j8rnx3a5fgp3y1s79cl-narsil-inference-coordinator-trial/lib')
from aiohttp import ClientSession, ClientTimeout, DummyCookieJar
from coordinator.backend_http import ControlClient
from coordinator.credentials import read_token

spec = importlib.util.spec_from_file_location('validated_stream_harness',
    '/nix/store/9k52wdxlm9a1gxx6gglxvrqkvfpbizx8-smoke-streams.py')
streams = importlib.util.module_from_spec(spec)
spec.loader.exec_module(streams)
ORIGIN = 'http://127.0.0.1:18080'
EXPECTED = ['O-active', 'S-1', 'S-2', 'O-1', 'O-2']


def require_order(completed):
    if completed != EXPECTED:
        raise RuntimeError('priority/FIFO completion order unconfirmed')


async def queued(client, request_id, strata, ollama, tasks):
    async with asyncio.timeout(15):
        while True:
            _, value = await client.request('GET', '/coordinator/status')
            if (value.get('active_request_id') != request_id or value.get('owner') != 'ollama'
                    or value.get('maintenance') is not False or value.get('fault') is not None
                    or value.get('reconciled') is not True or any(task.done() for task in tasks)):
                raise RuntimeError('nonpreempted active/queued boundary unconfirmed')
            counts = value.get('queues', {})
            if (counts.get('strata', {}).get('length') == strata
                    and counts.get('ollama', {}).get('length') == ollama):
                return
            await asyncio.sleep(0.05)


async def result(session, backend, label, completed):
    if backend == 'strata':
        path = '/strata/v1/chat/completions'
        body = dict(model=streams.STRATA, messages=[dict(role='user', content='Reply with READY only.')],
                    max_tokens=32, stream=False)
    else:
        path = '/ollama/api/chat'
        body = dict(model=streams.OLLAMA, messages=[dict(role='user', content='Reply with READY only.')],
                    stream=False, think=False, options=dict(num_ctx=8192, num_predict=32))
    async with session.post(ORIGIN + path, json=body, allow_redirects=False) as response:
        if response.status != 200 or response.content_type != 'application/json':
            raise RuntimeError('queued generation response unconfirmed')
        data = bytearray()
        async for chunk in response.content.iter_chunked(8192):
            data.extend(chunk)
            if len(data) > 65536:
                raise RuntimeError('generation response byte bound exceeded')
        value = json.loads(data)
        generated = (value.get('usage', {}).get('completion_tokens') if backend == 'strata'
                     else value.get('eval_count'))
        if type(generated) is not int or generated <= 0:
            raise RuntimeError('nonzero queued inference output unconfirmed')
    completed.append(label)
    print('Completed ' + label + f' ({generated} tokens)', flush=True)


async def exercise(session, client):
    completed, tasks = [], []
    await streams.status(client, 'strata', timeout=10)
    body = dict(model=streams.OLLAMA, messages=[dict(role='user', content=
        'Write a numbered list of 200 different short household tips, one tip per line.')],
        stream=True, think=False, options=dict(num_ctx=8192, num_predict=512))
    try:
        print('Starting O-active; queueing O-1/O-2 before S-1/S-2 (no retries)...', flush=True)
        async with session.post(ORIGIN + '/ollama/api/chat', json=body, allow_redirects=False) as response:
            request_id = response.headers.get('X-Request-ID')
            if response.status != 200 or response.content_type != 'application/x-ndjson' or not request_id:
                raise RuntimeError('active Ollama stream unconfirmed')
            seen = terminal = False
            total = 0
            async for line in response.content:
                total += len(line)
                if len(line) > 65536 or total > 1048576:
                    raise RuntimeError('active stream byte bound exceeded')
                value, done = streams.event(line, 'ndjson')
                terminal |= done
                seen |= bool(value and value.get('message', {}).get('content'))
                if seen and not terminal and not tasks:
                    for label, backend, s_count, o_count in (
                        ('O-1', 'ollama', 0, 1), ('O-2', 'ollama', 0, 2),
                        ('S-1', 'strata', 1, 2), ('S-2', 'strata', 2, 2)):
                        tasks.append(asyncio.create_task(result(session, backend, label, completed)))
                        await queued(client, request_id, s_count, o_count, tasks)
                    print('PASS queue boundary: same active Ollama request, 2 Strata + 2 Ollama queued.', flush=True)
            if not seen or not terminal or len(tasks) != 4:
                raise RuntimeError('natural active-stream completion unconfirmed')
        completed.append('O-active')
        print('Completed O-active naturally (not preempted).', flush=True)
        await asyncio.gather(*tasks)
        require_order(completed)
        await streams.status(client, 'ollama')
        print('PASS priority/FIFO order: ' + ' -> '.join(completed), flush=True)
        await result(session, 'strata', 'S-final', [])
        await streams.status(client, 'strata')
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()  # Only disconnect our callers; no admin/recovery action.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    if os.geteuid() != 0:
        print('Explicit sudo required; client credential remains root-private.', file=sys.stderr)
        return 1
    try:
        token = read_token('/var/lib/inference-coordinator-secrets/client', expected_uid=0)
        async with ControlClient(ORIGIN, bearer_token=token, timeout=10) as client, \
                   ControlClient('http://127.0.0.1:18081', timeout=5) as strata, \
                   ControlClient('http://127.0.0.1:12434', timeout=5) as ollama, \
                   ClientSession(headers={'Authorization':'Bearer '+token}, trust_env=False,
                       auto_decompress=False, cookie_jar=DummyCookieJar(),
                       timeout=ClientTimeout(total=950, sock_read=180)) as session:
            _, health = await strata.request('GET', '/health')
            _, ps = await ollama.request('GET', '/api/ps')
            if health.get('loaded') is not True or ps.get('models') != []:
                raise RuntimeError('initial exclusive Strata residency unconfirmed')
            await exercise(session, client)
            _, health = await strata.request('GET', '/health')
            _, ps = await ollama.request('GET', '/api/ps')
            if health.get('loaded') is not True or ps.get('models') != []:
                raise RuntimeError('final exclusive Strata residency unconfirmed')
            print('PRIORITY CHECK PASSED. Final Strata loaded; no admin controls used.', flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print('PRIORITY CHECK UNCONFIRMED: ' + type(error).__name__
              + '. No retry/replay. Inspect coordinator status before further work.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
