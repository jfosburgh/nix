"""Priority harness checks with fake streams/status; no service/GPU/credential I/O."""
import asyncio
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from coordinator.credentials import CredentialError

spec = importlib.util.spec_from_file_location('priority_smoke',
    Path(__file__).resolve().parents[1] / 'scripts/smoke-priority.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class PrioritySmokeTests(unittest.IsolatedAsyncioTestCase):
    def state(self, **changes):
        value = dict(active_request_id='fixture-id', owner='ollama', maintenance=False,
                     fault=None, reconciled=True,
                     queues=dict(strata=dict(length=2), ollama=dict(length=2)))
        value.update(changes)
        return value

    async def test_exact_nonpreemptive_priority_and_both_fifo_orders_required(self):
        smoke.require_order(['O-active', 'S-1', 'S-2', 'O-1', 'O-2'])
        for order in (['S-1','O-active','S-2','O-1','O-2'],
                      ['O-active','O-1','S-1','S-2','O-2'],
                      ['O-active','S-2','S-1','O-1','O-2'],
                      ['O-active','S-1','S-2','O-2','O-1']):
            with self.subTest(order=order), self.assertRaises(RuntimeError):
                smoke.require_order(order)

    async def test_queue_observation_correlates_same_active_request_and_counts(self):
        client = AsyncMock()
        client.request.return_value = 200, self.state()
        await smoke.queued(client, 'fixture-id', 2, 2, [])
        client.request.assert_awaited_once_with('GET', '/coordinator/status')

    async def test_completed_or_changed_owner_or_fault_refuses_queue_claim(self):
        for changes in (dict(active_request_id=None), dict(owner='strata'),
                        dict(maintenance=True), dict(fault='fixture')):
            client = AsyncMock()
            client.request.return_value = 200, self.state(**changes)
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                await smoke.queued(client, 'fixture-id', 2, 2, [])
        client.request.return_value = 200, self.state()
        with self.assertRaises(RuntimeError):
            await smoke.queued(client, 'fixture-id', 2, 2, [SimpleNamespace(done=lambda:True)])

    async def test_complete_harness_enqueues_ollama_first_without_admin_or_replay(self):
        class Response:
            status = 200
            headers = {'X-Request-ID':'fixture-id'}
            content_type = 'application/x-ndjson'
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            @property
            def content(self): return self
            async def __aiter__(self):
                yield b'{"message":{"content":"fixture"},"done":false}\n'
                yield b'{"done":true}\n'
        session = SimpleNamespace(post=lambda *args,**kwargs:Response())
        submitted = []
        async def result(session, backend, label, completed):
            submitted.append(label)
            await asyncio.sleep({'S-1':.01,'S-2':.02,'O-1':.03,'O-2':.04,'S-final':0}[label])
            completed.append(label)
        queue = AsyncMock()
        with patch.object(smoke, 'queued', queue), patch.object(smoke, 'result', result), \
             patch.object(smoke.streams, 'status', AsyncMock()), contextlib.redirect_stdout(io.StringIO()):
            await smoke.exercise(session, object())
        self.assertEqual(submitted, ['O-1','O-2','S-1','S-2','S-final'])
        self.assertEqual([(call.args[2],call.args[3]) for call in queue.await_args_list],
                         [(0,1),(0,2),(1,2),(2,2)])

    async def test_failed_queue_boundary_does_not_replay_active_request(self):
        session = SimpleNamespace(post=lambda *args,**kwargs:None)
        with patch.object(smoke.streams, 'status', AsyncMock(side_effect=RuntimeError('fixture'))):
            with self.assertRaises(RuntimeError):
                await smoke.exercise(session, object())

    async def test_credential_error_not_logged_or_retried(self):
        output = io.StringIO()
        with patch.object(smoke.os,'geteuid',return_value=0), \
             patch.object(smoke,'read_token',side_effect=CredentialError('DO NOT LOG')), \
             patch.object(smoke,'ClientSession') as client, contextlib.redirect_stderr(output):
            self.assertEqual(await smoke.main(),1)
        client.assert_not_called()
        self.assertNotIn('DO NOT LOG', output.getvalue())
