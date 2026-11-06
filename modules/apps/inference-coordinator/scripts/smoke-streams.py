#!/nix/store/3hr90mddrgkz0src1vykj19yddnjimzl-python3-3.14.8-env/bin/python -I
"""Explicit coordinated SSE/NDJSON completion and active Ollama cancellation.

Root-private client token only; no admin/raw generations/retries/secret output.
Requires initial idle Strata ownership from smoke-handoff; leaves Strata loaded.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, '/nix/store/ixd421qmcxsq5j8rnx3a5fgp3y1s79cl-narsil-inference-coordinator-trial/lib')
from aiohttp import ClientSession, ClientTimeout, DummyCookieJar
from coordinator.backend_http import ControlClient
from coordinator.credentials import read_token

STRATA = 'qwen3.8-flash-next-coder-iq1_m'
OLLAMA = 'gemma4:12b'
ORIGIN = 'http://127.0.0.1:18080'


def event(line, protocol):
    if protocol == 'sse':
        if not line.strip() or line.startswith(b':') or line.startswith(b'event:'):
            return None, False
        if not line.startswith(b'data:'):
            raise RuntimeError('unexpected SSE framing')
        line = line[5:].strip()
        if line == b'[DONE]':
            return None, True
    value = json.loads(line)
    if type(value) is not dict or 'error' in value:
        raise RuntimeError('stream event unconfirmed')
    return value, protocol == 'ndjson' and value.get('done') is True


async def status(client, owner, *, timeout=330):
    async with asyncio.timeout(timeout):
        while True:
            _, value = await client.request('GET', '/coordinator/status')
            if (value.get('maintenance') is not False or value.get('reconciled') is not True
                    or value.get('fault') is not None):
                raise RuntimeError('coordinator not healthy/admitting')
            queues = value.get('queues')
            if (type(queues) is not dict or set(queues) != {'strata', 'ollama'}
                    or any(q.get('length') != 0 for q in queues.values())):
                raise RuntimeError('unexpected concurrent queued work')
            if value.get('active_request_id') is None:
                if value.get('owner') != owner or (owner is None and value.get('lease') is not None):
                    raise RuntimeError('unexpected settled ownership')
                return
            await asyncio.sleep(0.2)


async def stream(session, client, path, body, protocol, *, cancel=False):
    seen = terminal = False
    count = size = 0
    async with session.post(ORIGIN + path, json=body, allow_redirects=False) as response:
        expected = 'text/event-stream' if protocol == 'sse' else 'application/x-ndjson'
        request_id = response.headers.get('X-Request-ID')
        if response.status != 200 or response.content_type != expected or not request_id:
            raise RuntimeError('stream response/header unconfirmed')
        async for line in response.content:
            size += len(line)
            if len(line) > 65536 or size > 1048576:
                raise RuntimeError('stream byte bound exceeded')
            value, done = event(line, protocol)
            if terminal and (value is not None or done):
                raise RuntimeError('data after terminal event')
            terminal |= done
            if value is not None:
                count += 1
                if protocol == 'sse':
                    for choice in value.get('choices', []):
                        delta = choice.get('delta', {})
                        seen |= bool(delta.get('content') or delta.get('reasoning_content'))
                else:
                    seen |= bool(value.get('message', {}).get('content'))
            if cancel and seen and not terminal:
                _, current = await client.request('GET', '/coordinator/status')
                if (current.get('active_request_id') != request_id or current.get('owner') != 'ollama'
                        or current.get('fault') is not None or current.get('maintenance') is not False):
                    raise RuntimeError('active cancellation boundary unconfirmed')
                response.close()  # Deliberate disconnect, not a lifecycle/admin call.
                return count
        if cancel or not seen or not terminal:
            raise RuntimeError('stream completion/cancellation unconfirmed')
    return count


async def main():
    if os.geteuid() != 0:
        print('Explicit sudo required; client credential remains root-private.', file=sys.stderr)
        return 1
    try:
        token = read_token('/var/lib/inference-coordinator-secrets/client', expected_uid=0)
        headers = {'Authorization': 'Bearer ' + token}
        async with ControlClient(ORIGIN, bearer_token=token, timeout=10) as client, \
                   ControlClient('http://127.0.0.1:18081', timeout=5) as strata, \
                   ControlClient('http://127.0.0.1:12434', timeout=5) as ollama, \
                   ClientSession(headers=headers, trust_env=False, auto_decompress=False,
                                 cookie_jar=DummyCookieJar(), timeout=ClientTimeout(total=950, sock_read=180)) as session:
            await status(client, 'strata', timeout=10)
            _, health = await strata.request('GET', '/health')
            _, ps = await ollama.request('GET', '/api/ps')
            if health.get('loaded') is not True or ps.get('models') != []:
                raise RuntimeError('initial exclusive Strata residency unconfirmed')
            strata_body = dict(model=STRATA, messages=[dict(role='user', content='Reply with READY only.')],
                               stream=True, max_tokens=32)
            ollama_body = dict(model=OLLAMA, messages=[dict(role='user', content='Count from 1 to 20.')],
                               stream=True, think=False, options=dict(num_ctx=8192, num_predict=64))
            for label, path, body, protocol, owner in (
                ('Strata SSE completion', '/strata/v1/chat/completions', strata_body, 'sse', 'strata'),
                ('Ollama NDJSON completion', '/ollama/api/chat', ollama_body, 'ndjson', 'ollama')):
                print(label + ' (no retry)...', flush=True)
                started = time.monotonic()
                count = await stream(session, client, path, body, protocol)
                await status(client, owner)
                print(f'PASS {label}: {count} JSON events, {time.monotonic()-started:.1f}s', flush=True)
            print('Active Ollama stream cancellation (no retry)...', flush=True)
            cancel_body = dict(ollama_body, messages=[dict(role='user', content=
                'Write a numbered list of 200 different short household tips, one tip per line.')],
                options=dict(num_ctx=8192, num_predict=512))
            await stream(session, client, '/ollama/api/chat', cancel_body, 'ndjson', cancel=True)
            await status(client, None)  # Require lease release, not just socket closure.
            _, health = await strata.request('GET', '/health')
            _, ps = await ollama.request('GET', '/api/ps')
            if health.get('loaded') is not False or ps.get('models') != []:
                raise RuntimeError('post-cancellation release unconfirmed')
            print('PASS active cancellation: no active work/owner/lease/fault; both backends empty.', flush=True)
            print('Post-cancellation Strata SSE recovery (no retry)...', flush=True)
            await stream(session, client, '/strata/v1/chat/completions', strata_body, 'sse')
            await status(client, 'strata')
            _, health = await strata.request('GET', '/health')
            _, ps = await ollama.request('GET', '/api/ps')
            if health.get('loaded') is not True or ps.get('models') != []:
                raise RuntimeError('final exclusive Strata residency unconfirmed')
            print('STREAM CHECK PASSED. Final Strata loaded; no admin controls used.', flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print('STREAM CHECK UNCONFIRMED: ' + type(error).__name__
              + '. No retry/replay. Inspect coordinator status before further work.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
