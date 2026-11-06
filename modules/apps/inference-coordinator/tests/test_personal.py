"""Personal-use runtime: fake process/HTTP controls, never real services or secrets."""
import asyncio
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from coordinator import personal
from coordinator.backend_http import LifecycleError
from coordinator.diagnostics import failure


class PersonalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_uses_only_normal_systemctl_and_waits_for_readiness(self):
        process = SimpleNamespace(wait=AsyncMock(return_value=0), returncode=0)
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.request.side_effect = [LifecycleError('not ready'), (200, {})]
        with patch.object(personal.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process)) as spawn, \
             patch.object(personal,'ControlClient',return_value=client), \
             patch.object(personal.asyncio,'sleep',AsyncMock()), self.assertLogs('narsil.inference') as logs:
            await personal.SystemdBackends('/fixed/systemctl').reset_ollama()
        self.assertEqual(spawn.call_args.args,('/fixed/systemctl','--no-ask-password','restart','ollama.service'))
        process.wait.assert_awaited_once()
        self.assertEqual(client.request.await_count,2)
        self.assertIn('backend_restart_complete','\n'.join(logs.output))

    async def test_nonzero_restart_logs_exit_and_systemctl_diagnostic(self):
        async def spawn(*args, **kwargs):
            kwargs['stderr'].write(b'Access denied by polkit fixture')
            return SimpleNamespace(wait=AsyncMock(return_value=1),returncode=1)
        with patch.object(personal.asyncio,'create_subprocess_exec',side_effect=spawn), \
             patch.object(personal,'ControlClient') as client, self.assertLogs('narsil.inference') as logs:
            with self.assertRaises(LifecycleError):
                await personal.SystemdBackends('/fixed/systemctl').reset_strata()
        client.assert_not_called()
        self.assertIn('Access denied by polkit fixture','\n'.join(logs.output))
        self.assertIn('"exit_code":1','\n'.join(logs.output))

    async def test_restart_timeout_does_not_claim_release_or_retry(self):
        process = SimpleNamespace(returncode=None)
        calls = 0
        async def wait():
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.sleep(10)
            return -9
        process.wait = wait
        process.kill = MagicMock(side_effect=lambda:setattr(process,'returncode',-9))
        with patch.object(personal.asyncio,'create_subprocess_exec',AsyncMock(return_value=process)) as spawn, \
             patch.object(personal,'ControlClient') as client, self.assertLogs('narsil.inference'):
            with self.assertRaises(TimeoutError):
                await personal.SystemdBackends('/fixed/systemctl',timeout=.01).reset_ollama()
        spawn.assert_awaited_once()
        process.kill.assert_called_once()
        client.assert_not_called()

    async def test_unknown_unit_refused_without_process(self):
        with patch.object(personal.asyncio,'create_subprocess_exec') as spawn:
            with self.assertRaises(ValueError):
                await personal.SystemdBackends('/fixed/systemctl').restart('sshd.service','http://127.0.0.1:1','/')
        spawn.assert_not_called()

    async def startup(self, *, fail=False):
        order = []
        config = SimpleNamespace(profile='desktop',backends=[SimpleNamespace(id='ollama',adapter='ollama')])
        controls = SimpleNamespace(reset_strata=AsyncMock(side_effect=LifecycleError('fixture') if fail
                                                else lambda:order.append('reset_strata')),
                                   reset_ollama=AsyncMock())
        scheduler = SimpleNamespace(reconcile=AsyncMock(side_effect=lambda:order.append('reconcile')),
                                    resume=MagicMock(side_effect=lambda:order.append('resume')))
        runner = SimpleNamespace(setup=AsyncMock(),cleanup=AsyncMock())
        site = SimpleNamespace(start=AsyncMock(side_effect=lambda:order.append('listen')))
        stop = SimpleNamespace(set=lambda:None, wait=AsyncMock())
        loop = asyncio.get_running_loop()
        with patch.object(personal,'read_operator_file'), patch.object(personal,'parse_config',return_value=config), \
             patch.object(personal,'load_systemd_credentials'), patch.object(personal,'SystemdBackends',return_value=controls), \
             patch.object(personal,'assemble',return_value=SimpleNamespace(app=object(),scheduler=scheduler)), \
             patch.object(personal,'create_runner',return_value=runner), patch.object(personal,'install_gateway'), \
             patch.object(personal.web,'TCPSite',return_value=site), \
             patch.object(personal.asyncio,'Event',return_value=stop), patch.object(loop,'add_signal_handler'), \
             self.assertLogs('narsil.inference'):
            if fail:
                with self.assertRaises(LifecycleError):
                    await personal.serve('/fixed/config','/fixed/device','/fixed/systemctl',18080)
            else:
                await personal.serve('/fixed/config','/fixed/device','/fixed/systemctl',18080)
        runner.cleanup.assert_awaited_once()
        return order

    async def test_startup_resets_reconciles_and_resumes_before_listening(self):
        self.assertEqual(await self.startup(),['reset_strata','reconcile','resume','listen','listen'])

    async def test_failed_startup_never_admits_or_listens(self):
        self.assertEqual(await self.startup(fail=True),[])

    def test_diagnostic_frames_never_include_exception_values_or_prompt(self):
        with self.assertLogs('narsil.inference') as logs:
            try:
                raise ValueError('SECRET credential and PROMPT fixture')
            except ValueError as error:
                failure('fixture_failure',error,request_id='fixed-id')
        message = logs.records[0].getMessage()
        value = json.loads(message)
        self.assertEqual(value['errors'][0]['type'],'ValueError')
        self.assertTrue(value['errors'][0]['frames'][0]['line']>0)
        self.assertNotIn('SECRET',message)
        self.assertNotIn('PROMPT',message)
        self.assertEqual(value['request_id'],'fixed-id')

    async def test_memory_logs_observed_and_required_bytes(self):
        from coordinator.memory import MemorySnapshot
        budget = SimpleNamespace(ram_available=1000,vram_free=2000)
        backend = SimpleNamespace(id='strata',adapter='strata',model='fixed-model',context=8192,
                                  cold=budget,resident=budget)
        sample = MemorySnapshot(16000,1000,32000,22000,time.monotonic())
        with patch.object(personal,'read_linux_memory',return_value=sample), self.assertLogs('narsil.inference') as logs:
            await personal.MemoryAdmission('/fake/device').check(backend,model='fixed-model',context=8192,resident=False)
        value = json.loads(logs.records[0].getMessage())
        self.assertEqual(value['vram_free_bytes'],15000)
        self.assertEqual(value['ram_available_bytes'],22000)
        self.assertEqual(value['required_vram_bytes'],2000)
        self.assertEqual(value['required_ram_bytes'],1000)

    async def test_control_failure_logs_status_without_body_or_credential(self):
        response = AsyncMock()
        response.__aenter__.return_value = response
        response.status, response.headers = 401, {}
        client = personal.ControlClient('http://127.0.0.1:12434',bearer_token='SECRET fixture token')
        client._session = SimpleNamespace(request=lambda *args,**kwargs:response)
        with self.assertLogs('narsil.inference') as logs, self.assertRaises(LifecycleError):
            await client.request('GET','/api/ps')
        self.assertIn('"status":401',logs.records[0].getMessage())
        self.assertNotIn('SECRET','\n'.join(logs.output))
        response.content.iter_chunked.assert_not_called()

    def test_credentials_use_root_private_scopes_without_printing(self):
        with patch.object(personal,'read_token',return_value='synthetic-fixture') as read:
            self.assertEqual(personal.credential('client'),'synthetic-fixture')
        read.assert_called_once_with('/var/lib/inference-coordinator-secrets/client',expected_uid=0)
        with self.assertRaises(ValueError):
            personal.credential('../admin')
