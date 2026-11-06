"""Lifecycle contracts using local fake HTTP only. Never touches real services."""
import asyncio
import json
from pathlib import Path
import sys
import unittest

from aiohttp import web
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.backend_http import ControlClient, LifecycleError
from coordinator.http import create_runner
from coordinator.lifecycle import OllamaLifecycle, OllamaProfile, StrataLifecycle
from coordinator.scheduler import Backend, Rejected, Scheduler, State


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.strata_loaded = False
        self.strata_busy = False
        self.strata_queued = 0
        self.strata_context = 131072
        self.strata_images = False
        self.busy_unloads = 0
        self.unload_status = None
        self.load_status = 'loaded'
        self.strata_release_lies = False
        self.residents = {}
        self.version = '0.40.11'
        self.ps_override = None
        self.health_override = None
        self.evictions = {}
        self.eviction_delay = 0
        self.eviction_stuck = False
        self.load_reason, self.evict_reason = 'load', 'unload'
        self.wrong_context = None
        self.load_started, self.load_go = asyncio.Event(), asyncio.Event()
        self.block_load = False
        self.quiesce_error = False
        self.memory_error = False
        self.pending_load = False
        self.override = None
        self.calls = []
        app = web.Application()
        app.router.add_route('*', '/{path:.*}', self.fake)
        self.runner = create_runner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.url = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])
        self.client = ControlClient(self.url, bearer_token='backend-secret', timeout=0.5)
        await self.client.__aenter__()
        self.strata = StrataLifecycle(self.client, model='coder', context=131072,
                                      release_timeout=0.1, poll_interval=0.001)
        self.ollama = self.new_ollama()
        await self.ollama.release()
        self.events.clear()
        self.calls.clear()

    def new_ollama(self):
        return OllamaLifecycle(self.client, {
            'small': OllamaProfile('small:latest', 8192, frozenset({'chat', 'generate', 'completion', 'embed'})),
            'other': OllamaProfile('other:q4', 4096, frozenset({'chat', 'generate'})),
        }, quiesce=self.quiesce, memory_gate=self.memory,
            expected_version='0.40.11', release_timeout=0.1, poll_interval=0.001)

    async def quiesce(self):
        self.events.append(('quiesce',))
        if self.quiesce_error:
            raise LifecycleError('Quiescence could not be proven')
        self.pending_load = False

    async def memory(self, model, context):
        self.events.append(('memory', model, context))
        if self.memory_error:
            raise LifecycleError('Insufficient memory')
        # Model/context switches must release old allocation before checking.
        self.assertFalse(self.strata_loaded)
        self.assertTrue(not self.residents or self.residents == {self.name(model): context})

    def name(self, model):
        return {'small': 'small:latest', 'other': 'other:q4'}.get(model, model)

    async def fake(self, request):
        body = await request.json() if request.method == 'POST' else None
        self.calls.append((request.method, request.path, body, dict(request.headers)))
        if self.override:
            return self.override(request)
        if request.path == '/health':
            return web.json_response(self.health_override if self.health_override is not None else {
                'service': 'strata', 'status': 'ok', 'model': 'coder',
                'max_context': self.strata_context, 'loaded': self.strata_loaded,
                'images': self.strata_images, 'image_generation': False})
        if request.path == '/status':
            return web.json_response({'busy': self.strata_busy, 'queued': self.strata_queued})
        if request.path == '/load':
            self.assertFalse(self.residents, 'Concurrent Strata/Ollama load')
            self.events.append(('load', 'strata'))
            self.strata_loaded = True
            return web.json_response({'status': self.load_status})
        if request.path == '/unload':
            self.events.append(('unload', 'strata'))
            if self.busy_unloads:
                self.busy_unloads -= 1
                return web.json_response({'status': 'busy'}, status=409)
            if self.unload_status:
                return web.json_response({'status': self.unload_status})
            if not self.strata_release_lies:
                self.strata_loaded = False
            return web.json_response({'status': 'unloaded'})
        if request.path == '/api/version':
            return web.json_response({'version': self.version})
        if request.path == '/api/ps':
            if self.ps_override is not None:
                return web.json_response(self.ps_override)
            if not self.eviction_stuck:
                for name in list(self.evictions):
                    self.evictions[name] -= 1
                    if self.evictions[name] <= 0:
                        self.residents.pop(name, None)
                        del self.evictions[name]
            return web.json_response({'models': [
                {'name': name, 'model': name, 'context_length': context}
                for name, context in self.residents.items()]})
        if request.path in ('/api/generate', '/api/embed'):
            name = self.name(body['model'])
            if body.get('keep_alive') == 0:
                self.events.append(('unload', name))
                self.evictions[name] = max(1, self.eviction_delay)
                return web.json_response({'model': body['model'], 'done': True, 'done_reason': self.evict_reason})
            self.assertFalse(self.strata_loaded, 'Concurrent Strata/Ollama load')
            self.assertFalse(self.residents, 'Coordinator failed to evict old model/context')
            context = body['options']['num_ctx']
            self.residents[name] = self.wrong_context if self.wrong_context is not None else context
            self.events.append(('load', name, context))
            self.load_started.set()
            if self.block_load:
                await self.load_go.wait()
            if request.path == '/api/embed':
                return web.json_response({'model': body['model'], 'embeddings': []})
            return web.json_response({'model': body['model'], 'done': True, 'done_reason': self.load_reason})
        return web.json_response({'error': 'unexpected route'}, status=404)

    async def asyncTearDown(self):
        self.load_go.set()
        await self.client.__aexit__()
        await self.runner.cleanup()

    def op(self, kind='chat', model='small', context=8192):
        return json.dumps([kind, model, context])

    async def test_inspection_does_not_load(self):
        status = await self.strata.inspect()
        self.assertFalse(status.loaded)
        self.assertEqual(await self.ollama.inspect(), ())
        self.assertEqual(self.events, [])

    async def test_strata_load_is_verified_and_idempotent(self):
        await self.strata.prepare('chat')
        await self.strata.prepare('completion')
        self.assertTrue(self.strata_loaded)
        self.assertEqual(self.events, [('load', 'strata')])
        posts = [call for call in self.calls if call[0] == 'POST']
        self.assertEqual(posts[0][2], {})
        self.assertEqual(posts[0][3]['Content-Type'], 'application/json')
        self.assertEqual(posts[0][3]['Authorization'], 'Bearer backend-secret')
        self.assertNotIn('Origin', posts[0][3])

    async def test_strata_busy_release_is_bounded_and_rechecked(self):
        self.strata_loaded, self.busy_unloads = True, 2
        await self.strata.release()
        self.assertFalse(self.strata_loaded)
        self.assertEqual(self.events.count(('unload', 'strata')), 3)

    async def test_strata_permanently_busy_fails_closed(self):
        self.busy_unloads = 10000
        with self.assertRaisesRegex(LifecycleError, 'deadline'):
            await self.strata.release()

    async def test_strata_unsupported_or_inconsistent_ack_fails(self):
        for status in ['unsupported', 'busy', 'loaded']:
            self.unload_status = status
            with self.assertRaises(LifecycleError):
                await self.strata.release()

    async def test_strata_false_release_ack_does_not_count(self):
        self.strata_loaded, self.strata_release_lies = True, True
        with self.assertRaisesRegex(LifecycleError, 'verification'):
            await self.strata.release()

    async def test_strata_load_response_must_be_explicit(self):
        self.load_status = 'ok'
        with self.assertRaises(LifecycleError):
            await self.strata.prepare('chat')
        self.assertTrue(self.strata_loaded)  # Failure is not proof of absent residency.

    async def test_strata_profile_and_auxiliary_engines_fail_closed(self):
        self.strata_context = 262144
        with self.assertRaises(LifecycleError):
            await self.strata.prepare('chat')
        self.strata_context, self.strata_images = 131072, True
        with self.assertRaises(LifecycleError):
            await self.strata.release()

    async def test_strata_untracked_work_not_loaded_over(self):
        self.strata_busy = True
        with self.assertRaises(LifecycleError):
            await self.strata.prepare('chat')
        self.assertEqual(self.events, [])
        self.strata_busy, self.strata_queued = False, 1
        with self.assertRaises(LifecycleError):
            await self.strata.prepare('chat')

    async def test_strata_missing_health_fields_fail_closed(self):
        self.health_override = {'loaded': False}
        with self.assertRaises(LifecycleError):
            await self.strata.inspect()

    async def test_ollama_startup_requires_quiescence_and_reconciliation(self):
        adapter = self.new_ollama()
        with self.assertRaisesRegex(LifecycleError, 'reconciliation'):
            await adapter.prepare(self.op())
        self.pending_load = True
        await adapter.release()
        self.assertFalse(self.pending_load)
        await adapter.prepare(self.op())
        self.assertEqual(self.residents, {'small:latest': 8192})

    async def test_personal_policy_checks_resident_headroom_after_load(self):
        self.ollama.verify_resident_memory = True
        await self.ollama.prepare(json.dumps(['chat','small',8192]))
        self.assertEqual(self.events.count(('memory','small',8192)),2)
        self.assertEqual(self.residents,{'small:latest':8192})

    async def test_personal_policy_releases_load_with_insufficient_resident_headroom(self):
        self.ollama.verify_resident_memory = True
        async def gate(model,context):
            if self.residents:
                raise LifecycleError('Insufficient resident headroom')
        self.ollama.memory_gate=gate
        with self.assertRaises(LifecycleError):
            await self.ollama.prepare(json.dumps(['chat','small',8192]))
        self.assertEqual(self.residents,{})
        self.assertFalse(self.ollama.uncertain)
        self.assertIn(('quiesce',),self.events)

    async def test_ollama_load_verified_idempotent_and_memory_checked(self):
        await self.ollama.prepare(self.op())
        await self.ollama.prepare(self.op())
        self.assertEqual(self.events.count(('load', 'small:latest', 8192)), 1)
        self.assertEqual(self.events.count(('memory', 'small', 8192)), 2)
        self.assertFalse(self.ollama.uncertain)

    async def test_ollama_embedding_warmup_uses_embed_not_generate(self):
        await self.ollama.prepare(self.op('embed'))
        loads = [call for call in self.calls if call[0] == 'POST']
        self.assertEqual(len(loads), 1)
        self.assertEqual(loads[0][1], '/api/embed')
        self.assertEqual(loads[0][2]['input'], [])
        self.assertFalse(loads[0][2]['truncate'])

    async def test_ollama_unloads_all_models_including_unapproved(self):
        self.residents = {'small:latest': 8192, 'alien:latest': 2048}
        self.eviction_delay = 3
        await self.ollama.release()
        self.assertEqual(self.residents, {})
        self.assertEqual(self.events[0], ('quiesce',))
        self.assertIn(('unload', 'alien:latest'), self.events)
        self.assertIn(('unload', 'small:latest'), self.events)
        # Each unload schedules eviction; poll rather than repeat mutating calls.
        self.assertEqual(self.events.count(('unload', 'small:latest')), 1)
        self.assertFalse(self.ollama.uncertain)

    async def test_ollama_same_backend_model_switch_releases_before_memory(self):
        await self.ollama.prepare(self.op())
        await self.ollama.prepare(self.op(model='other', context=4096))
        self.assertEqual(self.residents, {'other:q4': 4096})
        self.assertLess(self.events.index(('unload', 'small:latest')),
                        self.events.index(('memory', 'other', 4096)))

    async def test_ollama_context_switch_releases_and_loads_exact_context(self):
        await self.ollama.prepare(self.op())
        await self.ollama.prepare(self.op(context=4096))
        self.assertEqual(self.residents, {'small:latest': 4096})
        self.assertIn(('unload', 'small:latest'), self.events)
        self.assertIn(('load', 'small:latest', 4096), self.events)

    async def test_ollama_stuck_eviction_is_not_release(self):
        self.residents, self.eviction_stuck = {'small:latest': 8192}, True
        with self.assertRaisesRegex(LifecycleError, 'deadline'):
            await self.ollama.release()
        self.assertTrue(self.ollama.uncertain)
        with self.assertRaises(LifecycleError):
            await self.ollama.prepare(self.op())

    async def test_ollama_failed_quiescence_is_not_empty_residency_proof(self):
        self.quiesce_error = True
        self.assertEqual(self.residents, {})
        with self.assertRaises(LifecycleError):
            await self.ollama.release()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.ollama.uncertain)

    async def test_ollama_version_and_schema_mismatch_fail_closed(self):
        self.version = 'unknown-new-version'
        with self.assertRaises(LifecycleError):
            await self.ollama.inspect()
        self.version = '0.40.11'
        for response in [{}, {'models': None}, {'models': [{}]},
                         {'models': [{'name': 'x', 'model': 'x', 'context_length': True}]}]:
            self.ps_override = response
            with self.assertRaises(LifecycleError):
                await self.ollama.inspect()

    async def test_ollama_load_ack_or_actual_context_mismatch_remains_uncertain(self):
        self.load_reason = 'stop'
        with self.assertRaises(LifecycleError):
            await self.ollama.prepare(self.op())
        self.assertTrue(self.ollama.uncertain)
        await self.ollama.release()
        self.load_reason, self.wrong_context = 'load', 4096
        with self.assertRaisesRegex(LifecycleError, 'context verification'):
            await self.ollama.prepare(self.op())
        self.assertTrue(self.ollama.uncertain)

    async def test_ollama_bad_unload_ack_not_accepted(self):
        self.residents, self.evict_reason = {'small:latest': 8192}, 'stop'
        with self.assertRaises(LifecycleError):
            await self.ollama.release()
        self.assertTrue(self.ollama.uncertain)

    async def test_ollama_cancelled_load_requires_explicit_recovery(self):
        self.block_load = True
        task = asyncio.create_task(self.ollama.prepare(self.op()))
        await self.load_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.ollama.uncertain)
        self.assertTrue(self.residents)
        with self.assertRaises(LifecycleError):
            await self.ollama.prepare(self.op())
        await self.ollama.release()
        self.assertFalse(self.residents)
        self.assertFalse(self.ollama.uncertain)

    async def test_ollama_memory_failure_never_loads(self):
        self.memory_error = True
        with self.assertRaises(LifecycleError):
            await self.ollama.prepare(self.op())
        self.assertFalse(any(event[0] == 'load' for event in self.events))

    async def test_ollama_invalid_or_unapproved_metadata_refused(self):
        for operation in [None, 'not-json', '[]', '{}', '["chat","small"]', self.op(model='alien'),
                          self.op('speech'), self.op(context=999999), self.op(context=True)]:
            with self.assertRaises(LifecycleError):
                await self.ollama.prepare(operation)
        self.assertFalse(self.calls)

    async def test_scheduler_real_adapters_fake_http_repeated_handoffs(self):
        async def gate(*args):
            pass
        scheduler = Scheduler([
            Backend('strata', 0, frozenset({'narsil-gpu'}), self.strata),
            Backend('ollama', 1, frozenset({'narsil-gpu'}), self.ollama),
        ], memory_gate=gate)
        await scheduler.reconcile()
        scheduler.resume()
        for backend, operation in [('strata', 'chat'), ('ollama', self.op()),
                                   ('strata', 'completion'), ('ollama', self.op('embed'))]:
            async def execute():
                self.assertNotEqual(self.strata_loaded, bool(self.residents))
                return backend
            job = scheduler.submit(backend, operation, 1, execute)
            await scheduler.run_next()
            self.assertEqual(await job.result, backend)
        await scheduler.drain()
        self.assertFalse(self.strata_loaded)
        self.assertFalse(self.residents)
        self.assertEqual(scheduler.state, State.IDLE)

    async def test_failed_ollama_release_blocks_strata_with_real_adapters(self):
        async def gate(*args):
            pass
        scheduler = Scheduler([
            Backend('strata', 0, frozenset({'narsil-gpu'}), self.strata),
            Backend('ollama', 1, frozenset({'narsil-gpu'}), self.ollama),
        ], memory_gate=gate)
        await scheduler.reconcile()
        scheduler.resume()
        async def execute():
            return 'complete'
        first = scheduler.submit('ollama', self.op(), 1, execute)
        await scheduler.run_next()
        await first.result
        self.eviction_stuck = True
        second = scheduler.submit('strata', 'chat', 1, execute)
        with self.assertRaises(LifecycleError):
            await scheduler.run_next()
        with self.assertRaises(Rejected):
            await second.result
        self.assertEqual(scheduler.state, State.FAULT)
        self.assertFalse(self.strata_loaded)
        self.assertTrue(self.residents)
        self.assertNotIn(('load', 'strata'), self.events)

    async def test_control_client_rejects_bad_status_json_encoding_and_oversize(self):
        cases = [lambda req: web.Response(status=302, headers={'Location': '/load'}),
                 lambda req: web.Response(text='secret', content_type='application/json'),
                 lambda req: web.json_response([]),
                 lambda req: web.Response(body=b'{"x":NaN}', content_type='application/json'),
                 lambda req: web.Response(body=b'{}', content_type='application/json',
                                          headers={'Content-Encoding': 'gzip'}),
                 lambda req: web.json_response({'secret': 'x' * 65537})]
        for factory in cases:
            self.override = factory
            with self.assertRaises(LifecycleError) as error:
                await self.client.request('POST', '/load', {})
            self.assertNotIn('secret', str(error.exception))
        self.assertEqual(len(self.calls), len(cases))  # No redirect/replay.

    async def test_control_client_timeout_is_bounded(self):
        self.block_load = True
        async with ControlClient(self.url, timeout=0.01) as client:
            with self.assertRaises(LifecycleError):
                await client.request('POST', '/api/generate',
                                     {'model': 'small', 'options': {'num_ctx': 8192}})
        self.assertEqual(len(self.calls), 1)

    def test_ollama_profile_requires_explicit_capabilities(self):
        for args in [('', 8192, frozenset({'chat'})),
                     ('small', -1, frozenset({'chat'})),
                     ('small', 8192, frozenset()),
                     ('small', 8192, frozenset({'speech'}))]:
            with self.assertRaises(ValueError):
                OllamaProfile(*args)


if __name__ == '__main__':
    unittest.main()
