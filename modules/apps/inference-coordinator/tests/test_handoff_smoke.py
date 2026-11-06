"""Handoff operator script with fake clients only; no credentials/GPU/service I/O."""
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from coordinator.credentials import CredentialError

spec = importlib.util.spec_from_file_location('handoff_smoke',
    Path(__file__).resolve().parents[1] / 'scripts/smoke-handoff.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class FakeClients:
    def __init__(self):
        self.owner = None
        self.maintenance = False
        self.overlap = False
        self.fail = False
        self.posts = []
        self.calls = []

    def client(self, kind):
        parent = self
        class Client:
            async def request(self, method, path, body=None):
                parent.calls.append((kind, method, path))
                if method == 'POST':
                    if kind != 'coordinator':
                        raise AssertionError('raw backend generation')
                    parent.posts.append(path)
                    if parent.fail:
                        raise RuntimeError('fixture failure')
                    parent.owner = 'strata' if path.startswith('/strata/') else 'ollama'
                    if parent.owner == 'strata':
                        return 200, dict(choices=[dict(message=dict(content='synthetic output'))],
                                         usage=dict(completion_tokens=16))
                    return 200, dict(done=True, message=dict(content='synthetic output'), eval_count=16)
                if path == '/coordinator/status':
                    return 200, dict(maintenance=parent.maintenance, reconciled=True, fault=None,
                        owner=parent.owner, active_request_id=None,
                        queues={name:dict(length=0,bytes=0) for name in ('strata','ollama')})
                if path == '/health':
                    return 200, dict(loaded=parent.owner=='strata' or parent.overlap and parent.owner=='ollama',
                        model=smoke.STRATA_MODEL, max_context=131072)
                if path == '/status':
                    return 200, dict(busy=False, queued=0)
                if path == '/api/ps':
                    return 200, dict(models=[dict(name=smoke.OLLAMA_MODEL, context_length=8192)]
                                     if parent.owner=='ollama' else [])
                raise AssertionError('unexpected request')
        return Client()


class HandoffSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, clients):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(smoke, 'read_linux_memory',
                return_value=SimpleNamespace(vram_used=8*1024**3, ram_available=8*1024**3)):
            await smoke.smoke(clients.client('coordinator'), clients.client('strata'), clients.client('ollama'))

    async def test_three_coordinated_generations_and_no_raw_mutations(self):
        clients = FakeClients()
        await self.exercise(clients)
        self.assertEqual(clients.posts, ['/strata/v1/chat/completions', '/ollama/api/chat',
                                         '/strata/v1/chat/completions'])
        self.assertEqual(clients.owner, 'strata')
        self.assertFalse(any('/admin/' in path for _, _, path in clients.calls))
        self.assertTrue(all(kind=='coordinator' or method=='GET' for kind,method,_ in clients.calls))

    async def test_failed_request_not_retried_or_replayed(self):
        clients = FakeClients()
        clients.fail = True
        with self.assertRaises(RuntimeError):
            await self.exercise(clients)
        self.assertEqual(len(clients.posts), 1)

    async def test_maintenance_refuses_before_inference(self):
        clients = FakeClients()
        clients.maintenance = True
        with self.assertRaises(RuntimeError):
            await self.exercise(clients)
        self.assertEqual(clients.posts, [])

    async def test_overlap_residency_stops_without_next_generation(self):
        clients = FakeClients()
        clients.overlap = True
        with self.assertRaises(RuntimeError):
            await self.exercise(clients)
        self.assertEqual(len(clients.posts), 2)

    async def test_credential_failure_never_logs_secret_or_opens_http(self):
        output = io.StringIO()
        with patch.object(smoke.os, 'geteuid', return_value=0), \
             patch.object(smoke, 'read_token', side_effect=CredentialError('SECRET FIXTURE')), \
             patch.object(smoke, 'ControlClient') as client, contextlib.redirect_stderr(output):
            self.assertEqual(await smoke.main(), 1)
        client.assert_not_called()
        self.assertNotIn('SECRET FIXTURE', output.getvalue())
        self.assertIn('CredentialError', output.getvalue())
