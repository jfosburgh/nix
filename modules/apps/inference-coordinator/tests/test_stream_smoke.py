"""Streaming operator harness fixtures; no live HTTP, models or credentials."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

spec = importlib.util.spec_from_file_location('stream_smoke',
    Path(__file__).resolve().parents[1] / 'scripts/smoke-streams.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class Response:
    status = 200
    headers = {'X-Request-ID': 'fixture-id'}

    def __init__(self, lines, protocol):
        self.lines = lines
        self.content_type = 'text/event-stream' if protocol == 'sse' else 'application/x-ndjson'
        self.content = self
        self.closed = False
        self.consumed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.close()

    def close(self):
        self.closed = True

    async def __aiter__(self):
        for line in self.lines:
            self.consumed += 1
            yield line


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return self.response


class StreamSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sse_completion_consumes_through_eof(self):
        response = Response([b'data: {"choices":[{"delta":{"content":"fixture"}}]}\n',
                             b'\n', b'data: [DONE]\n', b'\n'], 'sse')
        session = Session(response)
        self.assertEqual(await smoke.stream(session, None, '/synthetic', {}, 'sse'), 1)
        self.assertEqual(response.consumed, 4)
        self.assertEqual(session.calls, 1)

    async def test_ndjson_requires_terminal_and_nonempty_content(self):
        for lines in ([b'{"message":{"content":"fixture"},"done":false}\n'],
                      [b'{"message":{"content":""},"done":true}\n']):
            with self.subTest(lines=lines), self.assertRaises(RuntimeError):
                await smoke.stream(Session(Response(lines, 'ndjson')), None, '/synthetic', {}, 'ndjson')
        lines = [b'{"message":{"content":"fixture"},"done":false}\n', b'{"done":true}\n']
        self.assertEqual(await smoke.stream(Session(Response(lines, 'ndjson')), None,
                                            '/synthetic', {}, 'ndjson'), 2)

    async def test_active_cancel_requires_matching_id_and_closes_before_final(self):
        response = Response([b'{"message":{"content":"fixture"},"done":false}\n',
                             b'{"done":true}\n'], 'ndjson')
        control = AsyncMock()
        control.request.return_value = (200, dict(active_request_id='fixture-id', owner='ollama',
                                                  fault=None, maintenance=False))
        session = Session(response)
        await smoke.stream(session, control, '/synthetic', {}, 'ndjson', cancel=True)
        self.assertTrue(response.closed)
        self.assertEqual(response.consumed, 1)
        self.assertEqual(session.calls, 1)
        control.request.assert_awaited_once_with('GET', '/coordinator/status')

    async def test_completed_or_mismatched_request_cannot_claim_active_cancellation(self):
        control = AsyncMock()
        control.request.return_value = (200, dict(active_request_id=None, owner='ollama',
                                                  fault=None, maintenance=False))
        response = Response([b'{"message":{"content":"fixture"},"done":false}\n'], 'ndjson')
        with self.assertRaises(RuntimeError):
            await smoke.stream(Session(response), control, '/synthetic', {}, 'ndjson', cancel=True)

    async def test_bad_framing_backend_error_and_post_terminal_data_refused(self):
        for line in (b'unknown: x\n', b'data: {"error":"fixture"}\n'):
            with self.subTest(line=line), self.assertRaises(RuntimeError):
                smoke.event(line, 'sse')
        response = Response([b'data: [DONE]\n',
                             b'data: {"choices":[{"delta":{"content":"fixture"}}]}\n'], 'sse')
        with self.assertRaises(RuntimeError):
            await smoke.stream(Session(response), None, '/synthetic', {}, 'sse')
