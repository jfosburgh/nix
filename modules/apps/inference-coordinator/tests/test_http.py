"""Loopback-only HTTP integration tests with fake lifecycle/backend services."""
import asyncio
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

from aiohttp import ClientPayloadError, ClientSession, web
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.budget import InputUsage, UnsupportedInput
from coordinator.http import Endpoint, create_app, create_runner
from coordinator.protocol import ModelLimits, OllamaProtocol, Protocol, StrataProtocol
from coordinator.scheduler import Backend, Scheduler, State

TOKEN = 'development-test-token-not-for-deployment'


class FakeCounter:
    """Synthetic token counts only; never usable for real model admission."""
    async def count(self, request):
        return InputUsage(request.model, request.context, (1,) * request.sequences)


class FakeLifecycle:
    def __init__(self, name, events):
        self.name, self.events = name, events

    async def prepare(self, operation):
        self.events.append(('load', self.name, operation))

    async def release(self):
        self.events.append(('release', self.name))


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def start_server(self, app):
        runner = create_runner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        self.runners.append(runner)
        return 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])

    async def asyncSetUp(self):
        self.runners, self.events, self.received = [], [], []
        self.entered, self.proceed, self.disconnected = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.streaming = False
        self.upstream_status = 200
        self.abort_before_headers = False
        self.upstream_headers = {}
        self.payload = b'data: {"reasoning":"opaque"}\n\ndata: [DONE]\n\n'
        self.payload_type = 'text/event-stream'
        self.catalogs = {
            '/api/tags': {'models': [{'name': 'small:latest', 'model': 'small:latest'},
                                     {'name': 'unapproved:latest', 'model': 'unapproved:latest'}]},
            '/api/version': {'version': '0.40.11'},
            '/v1/models': {'object': 'list', 'data': [{'id': 'small:latest'}, {'id': 'unapproved:latest'}]},
        }
        async def fake(request):
            self.received.append((request.path, await request.read(), request.headers.copy()))
            if self.abort_before_headers:
                request.transport.abort()
                return web.Response()
            if self.upstream_status != 200:
                return web.Response(status=self.upstream_status, headers=self.upstream_headers, body=b'error')
            if request.method == 'GET' and request.path in self.catalogs:
                return web.json_response(self.catalogs[request.path], headers={'ETag': 'unfiltered'})
            response = web.StreamResponse(headers={'Content-Type': self.payload_type,
                                                   'Connection': 'X-Private', 'X-Private': 'secret'})
            await response.prepare(request)
            await response.write(self.payload)
            self.entered.set()
            try:
                if self.streaming:
                    await self.proceed.wait()
                    await response.write(b'final\n')
                await response.write_eof()
            except asyncio.CancelledError:
                self.disconnected.set()
                raise
            return response
        backend = web.Application()
        backend.router.add_route('*', '/{path:.*}', fake)
        self.upstream = await self.start_server(backend)
        async def memory(*args):
            pass
        self.scheduler = Scheduler([
            Backend(key, priority, frozenset({'narsil-gpu'}), FakeLifecycle(key, self.events))
            for priority, key in enumerate(('strata', 'ollama', 'binary'))
        ], memory_gate=memory)
        await self.scheduler.reconcile()
        self.scheduler.resume()
        self.events.clear()
        self.endpoints = {
            'strata': Endpoint(self.upstream, StrataProtocol()),
            'ollama': Endpoint(self.upstream, OllamaProtocol({'small': ModelLimits(8192, 1024)},
                                counter=FakeCounter(), catalog_names={'small': 'small:latest'})),
            'binary': Endpoint(self.upstream, Protocol({('POST', '/upload'): 'upload'}, set())),
        }
        self.url = await self.start_server(create_app(self.scheduler, self.endpoints, token=TOKEN,
                                                     max_body=1024, queue_timeout=0.1))
        self.client = ClientSession(headers={'Authorization': 'Bearer ' + TOKEN})

    async def asyncTearDown(self):
        self.proceed.set()
        await self.client.close()
        for runner in reversed(self.runners):
            await runner.cleanup()

    async def post(self, path='/strata/v1/chat/completions', body=b'{"messages":[]}', **kwargs):
        return await self.client.post(self.url + path, data=body,
                                      headers={'Content-Type': 'application/json', **kwargs})

    async def enable_admin(self, timeout=1):
        self.admin_token = 'separate-administration-test-token'
        self.url = await self.start_server(create_app(
            self.scheduler, self.endpoints, token=TOKEN,
            admin_token=self.admin_token, admin_timeout=timeout))

    async def admin(self, action, **kwargs):
        return await self.client.post(self.url + '/coordinator/admin/' + action,
                                     headers={'Authorization': 'Bearer ' + self.admin_token}, **kwargs)

    async def test_admin_disabled_by_default_and_distinct_credentials_required(self):
        response = await self.client.post(self.url + '/coordinator/admin/drain')
        self.assertEqual(response.status, 404)
        for credential in (TOKEN, 'short'):
            with self.assertRaises(ValueError):
                create_app(self.scheduler, self.endpoints, token=TOKEN, admin_token=credential)
        for timeout in (0, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                create_app(self.scheduler, self.endpoints, token=TOKEN, admin_timeout=timeout)

    async def test_admin_authentication_and_request_shape(self):
        await self.enable_admin()
        response = await self.client.post(self.url + '/coordinator/admin/drain')
        self.assertEqual(response.status, 401)
        response = await self.client.get(self.url + '/coordinator/status',
                                       headers={'Authorization': 'Bearer ' + self.admin_token})
        self.assertEqual(response.status, 401)  # Admin key is not an inference/status key.
        for suffix, method, extras, expected in (
            ('drain', 'GET', {}, 405),
            ('drain', 'POST', {'data': b'{}'}, 405),
            ('drain?x=1', 'POST', {}, 400),
            ('drain', 'POST', {'headers': {'Origin': 'https://example.test'}}, 403),
            ('drain', 'POST', {'headers': {'Cookie': 'session=test'}}, 403),
            ('unknown', 'POST', {}, 404),
        ):
            headers = {'Authorization': 'Bearer ' + self.admin_token, **extras.pop('headers', {})}
            response = await self.client.request(method, self.url + '/coordinator/admin/' + suffix,
                                                 headers=headers, **extras)
            self.assertEqual(response.status, expected)
        self.assertFalse(self.scheduler.maintenance)
        self.assertEqual(self.events, [])

    async def test_admin_drain_reconcile_resume(self):
        await self.enable_admin()
        response = await self.admin('drain')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertTrue((await response.json())['maintenance'])
        self.assertEqual(self.events, [('release', key) for key in self.endpoints])
        response = await self.post()
        self.assertEqual(response.status, 503)
        response = await self.admin('resume')
        self.assertEqual(response.status, 200)
        self.assertFalse(self.scheduler.maintenance)
        response = await self.admin('reconcile')
        self.assertEqual(response.status, 200)
        self.assertTrue(self.scheduler.maintenance)
        response = await self.admin('resume')
        self.assertEqual(response.status, 200)
        self.assertEqual(self.received, [])

    async def test_admin_timeout_waiting_for_inference_requires_reconciliation(self):
        await self.enable_admin(timeout=0.03)
        self.streaming = True
        response = await self.post()
        await response.content.readexactly(len(self.payload))
        queued = asyncio.create_task(self.post())
        async with asyncio.timeout(1):
            while not self.scheduler.queues['strata']:
                await asyncio.sleep(0.001)
        draining = asyncio.create_task(self.admin('drain'))
        async with asyncio.timeout(1):
            while not self.scheduler.maintenance:
                await asyncio.sleep(0.001)
        conflict = await self.admin('resume')
        self.assertEqual(conflict.status, 409)
        self.assertEqual((await queued).status, 503)
        self.assertEqual((await draining).status, 503)
        self.assertFalse(self.scheduler.reconciled)
        self.assertEqual(self.scheduler.state, State.RUNNING)
        self.proceed.set()
        await response.read()
        async with asyncio.timeout(1):
            while self.scheduler.active is not None:
                await asyncio.sleep(0.001)
        self.assertEqual((await self.admin('resume')).status, 409)
        self.assertEqual((await self.admin('reconcile')).status, 200)
        self.assertEqual((await self.admin('resume')).status, 200)

    async def test_admin_release_failure_is_sanitized_and_blocks_resume(self):
        await self.enable_admin()
        lifecycle = self.scheduler.backends['ollama'].lifecycle
        original = lifecycle.release
        async def broken_release():
            raise RuntimeError('secret backend detail')
        lifecycle.release = broken_release
        response = await self.admin('drain')
        self.assertEqual(response.status, 503)
        self.assertNotIn('secret', await response.text())
        self.assertTrue(self.scheduler.maintenance)
        self.assertFalse(self.scheduler.reconciled)
        self.assertEqual(self.scheduler.state, State.FAULT)
        self.assertEqual((await self.admin('resume')).status, 409)
        lifecycle.release = original
        self.assertEqual((await self.admin('reconcile')).status, 200)
        self.assertEqual((await self.admin('resume')).status, 200)
        self.assertEqual(self.received, [])

    async def test_admin_disconnect_does_not_cancel_release(self):
        await self.enable_admin()
        entered, finish = asyncio.Event(), asyncio.Event()
        original = self.scheduler.backends['strata'].lifecycle.release
        async def slow_release():
            entered.set()
            await finish.wait()
            await original()
        self.scheduler.backends['strata'].lifecycle.release = slow_release
        caller = asyncio.create_task(self.admin('drain'))
        await asyncio.wait_for(entered.wait(), 1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual((await self.admin('resume')).status, 409)
        finish.set()
        async with asyncio.timeout(1):
            while not self.scheduler.reconciled:
                await asyncio.sleep(0.001)
        self.assertTrue(self.scheduler.maintenance)
        self.assertEqual(self.events, [('release', key) for key in self.endpoints])
        self.assertEqual((await self.admin('resume')).status, 200)

    async def test_streaming_lease_until_last_byte_and_no_replay(self):
        self.streaming = True
        response = await self.post()
        first = await response.content.readexactly(len(self.payload))
        self.assertEqual(first, self.payload)
        self.assertEqual(self.scheduler.state, State.RUNNING)
        self.assertEqual(self.scheduler.owner, 'strata')
        self.assertNotIn('X-Private', response.headers)
        self.proceed.set()
        self.assertEqual(await response.read(), b'final\n')
        self.assertEqual(len(self.received), 1)

    async def test_blocked_downstream_write_retains_ownership(self):
        blocked, resume = asyncio.Event(), asyncio.Event()
        original = web.StreamResponse.write
        async def write(response, data):
            # The upstream carries X-Private; the proxy has stripped that header.
            if 'X-Private' not in response.headers:
                blocked.set()
                await resume.wait()
            return await original(response, data)
        with patch.object(web.StreamResponse, 'write', write):
            first = await self.post()
            await asyncio.wait_for(blocked.wait(), 1)
            second = asyncio.create_task(self.post('/ollama/api/generate', b'{"model":"small"}'))
            await asyncio.sleep(0.01)
            self.assertEqual(self.scheduler.state, State.RUNNING)
            self.assertEqual(self.scheduler.owner, 'strata')
            self.assertEqual(len(self.received), 1)
            resume.set()
            await first.read()
            response = await second
            await response.read()
        self.assertEqual(len(self.received), 2)

    async def test_stream_idle_timeout_aborts_partial_response_and_releases(self):
        self.streaming = True
        self.url = await self.start_server(create_app(self.scheduler, self.endpoints, token=TOKEN,
                                                     stream_idle=0.02))
        response = await self.post()
        await response.content.readexactly(len(self.payload))
        with self.assertRaises(ClientPayloadError):
            await response.read()
        async with asyncio.timeout(1):
            while self.scheduler.active is not None:
                await asyncio.sleep(0.001)
        self.assertIn(('release', 'strata'), self.events)
        self.assertIsNone(self.scheduler.lease)
        self.assertEqual(len(self.received), 1)

    async def test_json_tools_schema_and_reasoning_body_unchanged(self):
        body = b'{ "tools":[{"function":{"parameters":{"type":"object"}}}], "reasoning":true }'
        response = await self.post(body=body)
        self.assertEqual(await response.read(), self.payload)
        self.assertEqual(self.received[0][1], body)
        self.assertEqual(self.received[0][0], '/v1/chat/completions')
        self.assertNotIn('Authorization', self.received[0][2])

    async def test_ndjson_bytes_preserved(self):
        self.payload_type = 'application/x-ndjson'
        self.payload = b'{"response":"a","done":false}\n{"done":true}\n'
        response = await self.post('/ollama/api/generate', b'{"model":"small","prompt":"x"}')
        self.assertEqual(await response.read(), self.payload)
        self.assertEqual(response.content_type, self.payload_type)
        sent = json.loads(self.received[0][1])
        self.assertEqual(sent['keep_alive'], -1)
        self.assertEqual(sent['options'], {'num_ctx': 8192, 'num_predict': 1024})

    async def test_multipart_binary_opaque_forwarding(self):
        body = b'--abc\r\nContent-Disposition: form-data; name="audio"\r\n\r\n\x00\xff\r\n--abc--\r\n'
        response = await self.client.post(self.url + '/binary/upload', data=body,
                                         headers={'Content-Type': 'multipart/form-data; boundary=abc'})
        await response.read()
        self.assertEqual(response.status, 200)
        self.assertEqual(self.received[0][1], body)
        self.assertEqual(self.received[0][2]['Content-Type'], 'multipart/form-data; boundary=abc')

    async def test_discovery_does_not_load_or_take_lease(self):
        for path in ['/ollama/api/tags', '/ollama/api/version', '/strata/v1/models']:
            response = await self.client.get(self.url + path)
            await response.read()
            self.assertEqual(response.status, 200)
        self.assertEqual(self.events, [])
        self.assertIsNone(self.scheduler.owner)

    async def test_catalog_filters_unapproved_models_and_rewrites_explicit_alias(self):
        for path, list_key, id_key in [('/ollama/api/tags', 'models', 'name'),
                                       ('/ollama/v1/models', 'data', 'id')]:
            response = await self.client.get(self.url + path)
            self.assertEqual(response.status, 200)
            value = await response.json()
            self.assertEqual([entry[id_key] for entry in value[list_key]], ['small'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertNotIn('ETag', response.headers)
        self.assertEqual(self.events, [])
        self.assertIsNone(self.scheduler.lease)

    async def test_catalog_refresh_does_not_evict_an_active_owner(self):
        self.streaming = True
        first = await self.post()
        await first.content.readexactly(len(self.payload))
        events = list(self.events)
        response = await self.client.get(self.url + '/ollama/api/tags')
        self.assertEqual(response.status, 200)
        self.assertEqual(len((await response.json())['models']), 1)
        self.assertEqual(self.events, events)
        self.assertEqual(self.scheduler.owner, 'strata')
        self.assertEqual(self.scheduler.state, State.RUNNING)
        self.proceed.set()
        await first.read()

    async def test_catalog_malformed_and_oversize_fail_before_response_headers(self):
        for value in [{'models': None}, {'models': [{}]},
                      {'models': [{'name': 'small:latest', 'model': 'different'}]},
                      {'models': [{'name': 'small:latest', 'model': 'small:latest'}] * 2}]:
            self.catalogs['/api/tags'] = value
            response = await self.client.get(self.url + '/ollama/api/tags')
            self.assertEqual(response.status, 502)
            self.assertNotIn('small:latest', await response.text())
        self.catalogs['/api/tags'] = {'models': [], 'padding': 'x' * (256 * 1024)}
        response = await self.client.get(self.url + '/ollama/api/tags')
        self.assertEqual(response.status, 502)
        await response.read()
        self.assertEqual(self.events, [])

    async def test_missing_input_counter_blocks_inference_not_discovery(self):
        self.endpoints['ollama'].protocol.counter = None
        response = await self.post('/ollama/api/generate', b'{"model":"small","prompt":"x"}')
        self.assertEqual(response.status, 503)
        await response.read()
        self.assertEqual(self.received, [])
        self.assertEqual(self.events, [])
        response = await self.client.get(self.url + '/ollama/api/tags')
        self.assertEqual(response.status, 200)
        self.assertEqual(len((await response.json())['models']), 1)

    async def test_budget_rejected_before_queue_or_lifecycle_or_upstream(self):
        class OversizeCounter:
            async def count(self, request):
                return InputUsage(request.model, request.context, (request.context,))
        self.endpoints['ollama'].protocol.counter = OversizeCounter()
        response = await self.post('/ollama/api/chat', b'{"model":"small","messages":[]}')
        self.assertEqual(response.status, 422)
        self.assertIn('not truncated', await response.text())
        self.assertEqual(self.received, [])
        self.assertEqual(self.events, [])
        self.assertIsNone(self.scheduler.owner)
        self.assertFalse(self.scheduler.queues['ollama'])

    async def test_unsupported_modality_never_estimated(self):
        class TextOnlyCounter:
            async def count(self, request):
                raise UnsupportedInput('secret image contents')
        self.endpoints['ollama'].protocol.counter = TextOnlyCounter()
        response = await self.post('/ollama/api/generate', b'{"model":"small","images":["base64"]}')
        self.assertEqual(response.status, 422)
        self.assertNotIn('secret', await response.text())
        self.assertEqual(self.received, [])

    async def test_embedding_batches_count_each_input_without_output_reservation(self):
        calls = []
        class BatchCounter:
            async def count(self, request):
                calls.append(request)
                return InputUsage(request.model, request.context, (8000,) * request.sequences)
        self.endpoints['ollama'].protocol.counter = BatchCounter()
        response = await self.post('/ollama/api/embed', b'{"model":"small","input":["a","b"]}')
        self.assertEqual(response.status, 200)
        await response.read()
        self.assertEqual(calls[0].sequences, 2)
        self.assertEqual(calls[0].output, 0)
        self.assertFalse(json.loads(calls[0].body)['truncate'])

    async def test_accounting_deadline_does_not_acquire_a_lease(self):
        cancelled = asyncio.Event()
        class SlowCounter:
            async def count(self, request):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        protocol = self.endpoints['ollama'].protocol
        protocol.counter, protocol.count_timeout = SlowCounter(), 0.005
        response = await self.post('/ollama/api/generate', b'{"model":"small","prompt":"x"}')
        self.assertEqual(response.status, 503)
        await response.read()
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(self.scheduler.lease)
        self.assertEqual(self.received, [])
        self.assertEqual(self.events, [])

    async def test_disconnect_during_accounting_cancels_without_admission(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()
        class Counter:
            async def count(self, request):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        self.endpoints['ollama'].protocol.counter = Counter()
        task = asyncio.create_task(self.post('/ollama/api/generate', b'{"model":"small"}'))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), 1)
        self.assertIsNone(self.scheduler.lease)
        self.assertEqual(self.received, [])
        self.assertEqual(self.events, [])

    async def test_openai_context_must_match_verified_counter_profile(self):
        class WrongContextCounter:
            async def count(self, request):
                return InputUsage(request.model, 4096, (1,))
        self.endpoints['ollama'].protocol.counter = WrongContextCounter()
        response = await self.post('/ollama/v1/chat/completions', b'{"model":"small","messages":[]}')
        self.assertEqual(response.status, 503)
        await response.read()
        self.assertEqual(self.received, [])

    async def test_status_is_authenticated_nonloading_and_available_in_maintenance(self):
        self.scheduler.maintenance = True
        response = await self.client.get(self.url + '/coordinator/status')
        self.assertEqual(response.status, 200)
        value = await response.json()
        self.assertTrue(value['maintenance'])
        self.assertEqual(value['queues']['ollama']['length'], 0)
        self.assertIsNone(value['owner'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.events, [])
        self.assertEqual(self.received, [])
        response = await self.client.post(self.url + '/coordinator/status', json={})
        self.assertEqual(response.status, 405)
        await response.read()
        response = await self.client.post(self.url + '/coordinator/drain', json={})
        self.assertEqual(response.status, 404)  # No control endpoints enabled yet.
        await response.read()

    async def test_status_and_request_ids_track_active_stream_without_prompt_data(self):
        self.streaming = True
        response = await self.post(body=b'{"messages":[{"content":"secret prompt"}]}',
                                   **{'X-Request-ID': 'untrusted-client-value'})
        await response.content.readexactly(len(self.payload))
        request_id = response.headers['X-Request-ID']
        self.assertEqual(str(uuid.UUID(request_id)), request_id)
        self.assertEqual(self.received[0][2]['X-Request-ID'], request_id)
        status = await self.client.get(self.url + '/coordinator/status')
        value = await status.json()
        self.assertEqual(value['active_request_id'], request_id)
        self.assertEqual(value['owner'], 'strata')
        self.assertNotIn('secret prompt', json.dumps(value))
        self.proceed.set()
        await response.read()

    async def test_unknown_controls_and_transports_refused(self):
        for path in ['/ollama/api/pull', '/ollama/api/create', '/ollama/api/delete',
                     '/strata/load', '/strata/unload', '/strata/', '/binary/unknown']:
            response = await self.post(path)
            await response.read()
            self.assertEqual(response.status, 404, path)
        response = await self.client.get(self.url + '/binary/upload', headers={'Upgrade': 'websocket'})
        self.assertEqual(response.status, 400)
        await response.read()
        self.assertEqual(self.received, [])
        self.assertEqual(self.events, [])

    async def test_model_and_resource_controls_refused(self):
        for body in [b'{"model":"unapproved"}', b'{"model":"small","keep_alive":-1}',
                     b'{"model":"small","options":{"num_ctx":999999}}',
                     b'{"model":"small","options":{"num_predict":-1}}',
                     b'{"model":"small","options":{"num_gpu":999}}',
                     b'{"model":"small","options":{"num_ctx":true}}']:
            response = await self.post('/ollama/api/generate', body)
            self.assertEqual(response.status, 400)
            await response.read()
        self.assertEqual(self.received, [])

    async def test_auth_applies_to_all_routes_ignores_forwarded_headers(self):
        async with ClientSession() as client:
            for path in ['/ollama/api/tags', '/strata/v1/models', '/coordinator/status', '/']:
                response = await client.get(self.url + path,
                                            headers={'X-Forwarded-For': '127.0.0.1'})
                self.assertEqual(response.status, 401)
                await response.read()
        self.assertEqual(self.received, [])

    async def test_body_limit_including_chunked(self):
        response = await self.post(body=b'x' * 1025)
        self.assertEqual(response.status, 413)
        await response.read()
        async def chunks():
            for _ in range(4):
                yield b'x' * 300
        response = await self.post(body=chunks())
        self.assertEqual(response.status, 413)
        await response.read()
        self.assertEqual(self.received, [])

    async def test_malformed_and_wrong_media_type(self):
        for body in (b'[]', b'{bad', b'{"x":NaN}', b'{"x":1e999}'):
            response = await self.post(body=body)
            self.assertEqual(response.status, 400)
            await response.read()
        response = await self.client.post(self.url + '/strata/v1/chat/completions', data=b'{}')
        self.assertEqual(response.status, 415)
        await response.read()

    async def test_backend_disconnect_before_headers_does_not_replay(self):
        self.abort_before_headers = True
        response = await self.post()
        self.assertEqual(response.status, 503)
        await response.read()
        self.assertEqual(len(self.received), 1)
        self.assertIn(('release', 'strata'), self.events)

    async def test_connection_cap_bounds_pre_admission_body_buffers(self):
        self.streaming = True
        self.url = await self.start_server(create_app(self.scheduler, self.endpoints, token=TOKEN,
                                                     max_connections=1))
        first = await self.post()
        await first.content.readexactly(len(self.payload))
        second = await self.post()
        self.assertEqual(second.status, 503)
        await second.read()
        self.assertEqual(len(self.received), 1)
        self.proceed.set()
        await first.read()

    async def test_upstream_status_and_no_redirect_following(self):
        self.upstream_status = 429
        response = await self.post()
        self.assertEqual(response.status, 429)
        self.assertEqual(await response.read(), b'error')
        self.upstream_status = 302
        self.upstream_headers = {'Location': self.upstream + '/unsafe'}
        response = await self.post()
        self.assertEqual(response.status, 503)
        await response.read()
        self.assertEqual(len(self.received), 2)
        self.assertIn(('release', 'strata'), self.events)

    async def test_queue_deadline_expires_while_other_request_streams(self):
        self.streaming = True
        first = await self.post()
        await first.content.readexactly(len(self.payload))
        second = await self.post('/ollama/api/generate', b'{"model":"small"}')
        self.assertEqual(second.status, 503)
        await second.read()
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.scheduler.owner, 'strata')
        self.proceed.set()
        await first.read()

    async def test_active_disconnect_cancels_upstream_and_verifies_release(self):
        self.streaming = True
        response = await self.post()
        await response.content.readexactly(len(self.payload))
        response.close()
        await asyncio.wait_for(self.disconnected.wait(), 1)
        async with asyncio.timeout(1):
            while self.scheduler.active is not None:
                await asyncio.sleep(0.005)
        self.assertIn(('release', 'strata'), self.events)
        self.assertIsNone(self.scheduler.lease)
        self.assertIsNone(self.scheduler.fault)
        self.assertEqual(len(self.received), 1)

    async def test_cancelled_queued_request_never_reaches_upstream(self):
        self.streaming = True
        first = await self.post()
        await first.content.readexactly(len(self.payload))
        task = asyncio.create_task(self.post('/ollama/api/generate', b'{"model":"small"}'))
        async with asyncio.timeout(1):
            while not self.scheduler.queues['ollama']:
                await asyncio.sleep(0.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.04)
        self.proceed.set()
        await first.read()
        await asyncio.sleep(0.02)
        self.assertEqual(len(self.received), 1)
        self.assertFalse(self.scheduler.queues['ollama'])

    async def test_backend_credentials_are_separate_and_not_client_supplied(self):
        endpoint = Endpoint(self.upstream, StrataProtocol(), bearer_token='private-backend-token')
        self.endpoints['strata'] = endpoint
        self.assertNotIn('private-backend-token', repr(endpoint))
        response = await self.post(**{'x-api-key': 'untrusted-client-key'})
        await response.read()
        headers = self.received[0][2]
        self.assertEqual(headers['Authorization'], 'Bearer private-backend-token')
        self.assertNotIn('x-api-key', headers)
        self.assertNotIn('Authorization', response.headers)

    async def test_no_hop_by_hop_or_forwarded_credentials(self):
        response = await self.post(**{'Connection': 'X-Secret', 'X-Secret': 'hidden',
                                      'Cookie': 'session=secret', 'X-Forwarded-For': 'arbitrary',
                                      'x-api-key': 'secret-client-key'})
        await response.read()
        headers = self.received[0][2]
        for name in ('X-Secret', 'Cookie', 'X-Forwarded-For', 'Authorization', 'x-api-key'):
            self.assertNotIn(name, headers)

    async def test_queries_and_encoded_requests_refused(self):
        response = await self.post(**{'Content-Encoding': 'gzip'})
        self.assertEqual(response.status, 400)
        await response.read()
        response = await self.post('/strata/v1/chat/completions?load=true')
        self.assertEqual(response.status, 400)
        await response.read()
        self.assertEqual(self.received, [])

    def test_nonlocal_upstreams_rejected(self):
        for address in ('http://example.com:80', 'http://127.0.0.1:80/path',
                        'http://user:secret@127.0.0.1:80', 'https://127.0.0.1:80'):
            with self.assertRaises(ValueError):
                Endpoint(address, StrataProtocol())


if __name__ == '__main__':
    unittest.main()
