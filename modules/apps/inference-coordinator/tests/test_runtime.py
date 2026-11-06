"""Runtime wiring against ephemeral loopback fakes only; no real safety providers."""
import json
from dataclasses import replace
from pathlib import Path
import sys
from types import MappingProxyType
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, web
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.backend_http import ControlClient
from coordinator.budget import InputUsage
from coordinator.config import parse_config
from coordinator.credentials import Credentials
from coordinator.http import create_runner
from coordinator.runtime import AssemblyError, assemble
from coordinator.scheduler import Rejected, State
from test_config import fixture

CLIENT = 'synthetic-runtime-client-test-token'
ADMIN = 'synthetic-runtime-administration-token'
STRATA = 'synthetic-runtime-strata-backend-token'
OLLAMA = 'synthetic-runtime-ollama-backend-token'


class Counter:
    async def count(self, request):
        return InputUsage(request.model, request.context, (1,) * request.sequences)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def server(self, app):
        runner = create_runner(app)
        await runner.setup()
        self.runners.append(runner)
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        return 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])

    async def asyncSetUp(self):
        self.runners, self.calls, self.memory_calls, self.events = [], [], [], []
        self.loaded = False
        self.residents = {}
        self.memory_fails = False
        self.quiescence_fails = False
        async def strata(request):
            body = await request.json() if request.method == 'POST' else None
            self.calls.append(('coder', request.path, body, dict(request.headers)))
            if request.path == '/health':
                return web.json_response({'service': 'strata', 'status': 'ok', 'model': 'coder',
                                          'max_context': 131072, 'loaded': self.loaded,
                                          'images': False, 'image_generation': False})
            if request.path == '/status':
                return web.json_response({'busy': False, 'queued': 0})
            if request.path == '/unload':
                self.loaded = False
                self.events.append('strata-release')
                return web.json_response({'status': 'unloaded'})
            if request.path == '/load':
                self.assertFalse(self.residents)
                self.loaded = True
                self.events.append('strata-load')
                return web.json_response({'status': 'loaded'})
            if request.path == '/v1/chat/completions':
                self.assertTrue(self.loaded)
                return web.Response(body=b'data: [DONE]\n\n', content_type='text/event-stream')
            return web.json_response({'error': 'unexpected'}, status=404)

        async def ollama(request):
            body = await request.json() if request.method == 'POST' else None
            self.calls.append(('apps', request.path, body, dict(request.headers)))
            if request.path == '/api/version':
                return web.json_response({'version': '0.40.11'})
            if request.path == '/api/ps':
                return web.json_response({'models': [
                    {'name': name, 'model': name, 'context_length': context}
                    for name, context in self.residents.items()]})
            if request.path == '/api/tags':
                return web.json_response({'models': [{'name': 'small:latest', 'model': 'small:latest'},
                                                     {'name': 'not-approved', 'model': 'not-approved'}]})
            if request.path == '/api/generate':
                if body.get('keep_alive') == 0:
                    self.residents.pop(body['model'], None)
                    self.events.append('ollama-release')
                    return web.json_response({'done': True, 'done_reason': 'unload'})
                self.assertFalse(self.loaded)
                if body.get('prompt') == '':
                    self.assertFalse(self.residents)
                    self.residents['small:latest'] = body['options']['num_ctx']
                    self.events.append('ollama-load')
                    return web.json_response({'done': True, 'done_reason': 'load'})
                self.assertEqual(self.residents, {'small:latest': body['options']['num_ctx']})
                return web.Response(body=b'{"done":true}\n', content_type='application/x-ndjson')
            return web.json_response({'error': 'unexpected'}, status=404)

        addresses = []
        for handler in (strata, ollama):
            app = web.Application()
            app.router.add_route('*', '/{path:.*}', handler)
            addresses.append(await self.server(app))
        value = fixture()
        value['limits'].update(max_queue=8, max_queue_bytes=8192, max_body=4096,
                               max_connections=8, max_discovery_bytes=8192)
        for backend, name, address in zip(value['backends'], ('coder', 'apps'), addresses):
            backend.update(id=name, upstream=address, credential_file='/run/credentials/' + name)
        value['backends'][0]['model'] = 'coder'
        self.config = parse_config(json.dumps(value).encode())
        self.credentials = Credentials(CLIENT, ADMIN, MappingProxyType({'coder': STRATA, 'apps': OLLAMA}))
        test = self
        class Memory:
            async def check(self, backend, *, model, context, resident):
                test.memory_calls.append((backend.id, model, context, resident, backend.cold, backend.models))
                if test.memory_fails:
                    raise RuntimeError('synthetic-private-memory-error')
        self.memory = Memory()
        self.client = ClientSession(headers={'Authorization': 'Bearer ' + CLIENT})

    async def asyncTearDown(self):
        self.quiescence_fails = False
        await self.client.close()
        for runner in reversed(self.runners):
            await runner.cleanup()

    async def quiesce(self):
        self.events.append('quiesce')
        if self.quiescence_fails:
            raise RuntimeError('synthetic-private-quiescence-error')

    def build(self, **changes):
        options = dict(memory=self.memory, counters={'apps': Counter()}, quiescence={'apps': self.quiesce})
        options.update(changes)
        return assemble(self.config, self.credentials, **options)

    async def start(self):
        runtime = self.build()
        url = await self.server(runtime.app)
        return runtime, url

    async def post(self, url, path, body):
        response = await self.client.post(url + path, json=body)
        await response.read()
        return response

    async def test_assembly_and_setup_do_not_contact_or_resume_backends(self):
        with patch('coordinator.backend_http.ClientSession', side_effect=AssertionError('I/O on assembly')):
            runtime = self.build()
        self.assertEqual(self.calls, [])
        self.assertTrue(runtime.scheduler.maintenance)
        self.assertFalse(runtime.scheduler.reconciled)
        with self.assertRaises(Rejected):
            runtime.scheduler.resume()
        url = await self.server(runtime.app)
        self.assertEqual(self.calls, [])
        response = await self.client.get(url + '/coordinator/status')
        self.assertTrue((await response.json())['maintenance'])
        response = await self.post(url, '/apps/api/generate', {'model': 'small', 'prompt': 'hello'})
        self.assertEqual(response.status, 503)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])
        self.assertEqual(self.memory_calls, [])

    async def test_native_trial_has_no_counter_and_pins_warmup_shift_policy(self):
        self.config = replace(self.config, backends=(self.config.backends[0],
            replace(self.config.backends[1], input_policy='native-reject-trial')))
        runtime = self.build(counters={})
        url = await self.server(runtime.app)
        await runtime.scheduler.reconcile()
        runtime.scheduler.resume()
        response = await self.post(url, '/apps/api/generate', {'model': 'small', 'prompt': 'hello'})
        self.assertEqual(response.status, 200)
        requests = [body for backend, path, body, headers in self.calls if path == '/api/generate']
        self.assertTrue(requests)
        for body in requests:
            self.assertIs(body['shift'], False)
            self.assertIs(body['truncate'], False)
        before = len(self.calls)
        response = await self.post(url, '/apps/v1/chat/completions', {'model': 'small', 'messages': []})
        self.assertEqual(response.status, 404)
        self.assertEqual(len(self.calls), before)
        with self.assertRaises(AssemblyError):
            self.build(counters={'apps': Counter()})  # No synthetic fallback registry.

    async def test_dependency_registries_must_be_exact_and_complete(self):
        cases = [dict(counters=None), dict(quiescence=None),
                 dict(counters={}), dict(counters={'ollama': Counter()}),
                 dict(counters={'apps': None}), dict(counters={'apps': Counter(), 'extra': Counter()}),
                 dict(quiescence={}), dict(quiescence={'apps': None}), dict(memory=None)]
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(AssemblyError):
                    self.build(**changes)
        self.assertEqual(self.calls, [])

    async def test_direct_credential_objects_cannot_bypass_scope_validation(self):
        for credentials in (
            Credentials(CLIENT, CLIENT, {'coder': STRATA, 'apps': OLLAMA}),
            Credentials('short', ADMIN, {'coder': STRATA, 'apps': OLLAMA}),
            Credentials(CLIENT, ADMIN, {'coder': STRATA, 'apps': OLLAMA + '\r\n'}),
            Credentials(CLIENT, None, {'coder': STRATA, 'apps': OLLAMA}),
            Credentials(CLIENT, ADMIN, {}),
        ):
            with self.assertRaises(AssemblyError):
                assemble(self.config, credentials, memory=self.memory,
                         counters={'apps': Counter()}, quiescence={'apps': self.quiesce})

    async def test_limits_models_and_names_are_explicitly_wired(self):
        runtime = self.build()
        scheduler = runtime.scheduler
        self.assertEqual(scheduler.order, ['coder', 'apps'])
        for key in ('max_queue', 'max_queue_bytes', 'lifecycle_timeout', 'inference_timeout'):
            self.assertEqual(getattr(scheduler, key), getattr(self.config.limits, key))
        protocol = runtime.endpoints['apps'].protocol
        self.assertEqual(protocol.count_timeout, self.config.limits.count_timeout)
        self.assertEqual(protocol.models['small'].context, 8192)
        self.assertEqual(protocol.catalog_aliases, {'small:latest': 'small'})
        with self.assertRaises(TypeError):
            runtime.endpoints['extra'] = runtime.endpoints['apps']
        for secret in (CLIENT, ADMIN, STRATA, OLLAMA):
            self.assertNotIn(secret, repr(runtime))
            self.assertNotIn(secret, repr(runtime.endpoints))

    async def test_real_adapters_on_fakes_switch_and_select_resident_memory(self):
        runtime, url = await self.start()
        await runtime.scheduler.reconcile()
        runtime.scheduler.resume()
        self.calls.clear()
        self.events.clear()
        for path, body in (
            ('/coder/v1/chat/completions', {'messages': []}),
            ('/coder/v1/chat/completions', {'messages': []}),
            ('/apps/api/generate', {'model': 'small', 'prompt': 'hello'}),
            ('/apps/api/generate', {'model': 'small', 'prompt': 'hello'}),
            ('/coder/v1/chat/completions', {'messages': []}),
        ):
            self.assertEqual((await self.post(url, path, body)).status, 200)
        self.assertEqual([call[:4] for call in self.memory_calls], [
            ('coder', 'coder', 131072, False), ('coder', 'coder', 131072, True),
            ('apps', 'small', 8192, False), ('apps', 'small', 8192, True),
            ('coder', 'coder', 131072, False)])
        self.assertEqual(self.events, ['strata-load', 'strata-release', 'ollama-load',
                                      'quiesce', 'ollama-release', 'strata-load'])
        for name, path, body, headers in self.calls:
            expected = STRATA if name == 'coder' else OLLAMA
            self.assertEqual(headers['Authorization'], 'Bearer ' + expected)
            self.assertNotIn(CLIENT, headers['Authorization'])

    async def test_smaller_context_switch_passes_actual_context_after_eviction(self):
        runtime, url = await self.start()
        await runtime.scheduler.reconcile()
        runtime.scheduler.resume()
        for context in (8192, 4096, 4096):
            response = await self.post(url, '/apps/api/generate',
                                       {'model': 'small', 'prompt': 'hello', 'options': {'num_ctx': context}})
            self.assertEqual(response.status, 200)
        self.assertEqual([call[:4] for call in self.memory_calls], [
            ('apps', 'small', 8192, False), ('apps', 'small', 4096, False),
            ('apps', 'small', 4096, True)])
        self.assertEqual(self.events.count('ollama-release'), 1)
        self.assertEqual(self.residents, {'small:latest': 4096})

    async def test_partial_session_setup_failure_closes_previously_opened_client(self):
        runtime = self.build()
        original = ControlClient.__aenter__
        opened = []
        async def fail_second(client):
            if opened:
                raise RuntimeError('synthetic-session-setup-failure')
            opened.append(client)
            return await original(client)
        runner = create_runner(runtime.app)
        with patch.object(ControlClient, '__aenter__', fail_second):
            with self.assertRaises(RuntimeError):
                await runner.setup()
        self.assertIsNone(opened[0]._session)
        self.assertEqual(self.calls, [])
        self.assertTrue(runtime.scheduler.maintenance)
        await runner.cleanup()

    async def test_discovery_in_maintenance_filters_without_safety_calls(self):
        runtime, url = await self.start()
        response = await self.client.get(url + '/apps/api/tags')
        self.assertEqual(response.status, 200)
        self.assertEqual([m['name'] for m in (await response.json())['models']], ['small'])
        self.assertEqual(self.events, [])
        self.assertEqual(self.memory_calls, [])
        self.assertTrue(runtime.scheduler.maintenance)

    async def test_memory_failure_blocks_load_without_leaking_error(self):
        runtime, url = await self.start()
        await runtime.scheduler.reconcile()
        runtime.scheduler.resume()
        self.events.clear()
        self.memory_fails = True
        response = await self.post(url, '/apps/api/generate', {'model': 'small', 'prompt': 'hello'})
        self.assertEqual(response.status, 503)
        self.assertNotIn('private-memory', await response.text())
        self.assertFalse(self.residents)
        self.assertNotIn('ollama-load', self.events)
        self.assertEqual(runtime.scheduler.state, State.FAULT)

    async def test_failed_startup_quiescence_never_resumes_or_loads(self):
        runtime, url = await self.start()
        self.quiescence_fails = True
        with self.assertRaises(RuntimeError):
            await runtime.scheduler.reconcile()
        self.assertTrue(runtime.scheduler.maintenance)
        self.assertFalse(runtime.scheduler.reconciled)
        with self.assertRaises(Rejected):
            runtime.scheduler.resume()
        self.assertFalse(self.loaded)
        self.assertFalse(self.residents)

    async def test_separately_authorized_admin_uses_live_control_sessions(self):
        runtime, url = await self.start()
        headers = {'Authorization': 'Bearer ' + ADMIN}
        for operation in ('reconcile', 'resume', 'drain'):
            response = await self.client.post(url + '/coordinator/admin/' + operation, headers=headers)
            self.assertEqual(response.status, 200)
            await response.read()
        self.assertTrue(runtime.scheduler.maintenance)
        self.assertFalse(self.loaded)
        self.assertFalse(self.residents)

    async def test_failed_cleanup_still_closes_sessions_and_blocks_admission(self):
        runtime, url = await self.start()
        self.quiescence_fails = True
        runner = self.runners.pop()
        with self.assertRaises(RuntimeError):
            await runner.cleanup()
        self.assertTrue(runtime.scheduler.maintenance)
        self.assertFalse(runtime.scheduler.reconciled)
        for backend in runtime.scheduler.backends.values():
            self.assertIsNone(backend.lifecycle.client._session)

    async def test_cleanup_releases_before_closing_control_sessions(self):
        runtime, url = await self.start()
        await runtime.scheduler.reconcile()
        runtime.scheduler.resume()
        self.assertEqual((await self.post(url, '/apps/api/generate',
                                        {'model': 'small', 'prompt': 'hello'})).status, 200)
        self.assertTrue(self.residents)
        runner = self.runners.pop()
        await runner.cleanup()
        self.assertFalse(self.residents)
        self.assertTrue(runtime.scheduler.maintenance)
        for backend in runtime.scheduler.backends.values():
            self.assertIsNone(backend.lifecycle.client._session)
