import asyncio
import json
import os
import socket
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from coordinator.http import Endpoint, create_app
from coordinator.gateway import install_gateway
from coordinator.openai_ollama import OllamaChatProtocol, messages_to_native, usage
from coordinator.protocol import AdmissionError, ModelLimits
from coordinator.scheduler import Backend, Scheduler


class OllamaOpenAITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.tool_file = None
        async def chat(request):
            value = await request.json()
            self.requests.append(value)
            if value['messages'][-1]['content']=='reject':
                return web.json_response({'error':'context exceeded'},status=400)
            message = dict(role='assistant',content='READY')
            if value.get('tools') and not (self.tool_file and value['messages'][-1]['role']=='tool'):
                name,arguments = ('read',{'path':self.tool_file}) if self.tool_file else ('lookup',{'key':'fixture'})
                message = dict(role='assistant',content='',tool_calls=[dict(function=dict(name=name,arguments=arguments))])
            final = dict(model=value['model'],message=message,done=True,done_reason='stop',
                         prompt_eval_count=20,eval_count=3)
            if value.get('stream'):
                response = web.StreamResponse(headers={'Content-Type':'application/x-ndjson'})
                await response.prepare(request)
                await response.write(json.dumps(dict(model=value['model'],message=message,done=False)).encode()+b'\n')
                final['message'] = dict(role='assistant',content='')
                await response.write(json.dumps(final).encode()+b'\n')
                await response.write_eof()
                return response
            return web.json_response(final)
        upstream = web.Application()
        upstream.router.add_post('/api/chat',chat)
        upstream.router.add_get('/api/tags',lambda request:web.json_response(dict(models=[
            dict(name='gemma4:12b',model='gemma4:12b'),dict(name='qwen:latest',model='qwen:latest'),
            dict(name='not-approved',model='not-approved')])) )
        self.server = TestServer(upstream)
        await self.server.start_server()
        self.protocol = OllamaChatProtocol({'gemma4:12b':ModelLimits(65536,8192),'qwen':ModelLimits(65536,8192)},
                                          expected_version='0.40.11',catalog_names={'gemma4:12b':'gemma4:12b','qwen':'qwen:latest'})
        lifecycle = AsyncMock()
        self.scheduler = Scheduler([Backend('ollama',0,frozenset({'narsil-gpu'}),lifecycle)],memory_gate=AsyncMock())
        self.scheduler.reconciled=True
        self.scheduler.maintenance=False
        app=create_app(self.scheduler,{'ollama':Endpoint(str(self.server.make_url('')).rstrip('/'),self.protocol)},token='x'*32)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0))
            port=probe.getsockname()[1]
        install_gateway(app,'x'*32,port=port)
        self.client=TestClient(TestServer(app,port=port))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def post(self, **extra):
        value=dict(model='gemma4:12b',messages=[dict(role='user',content='PRIVATE prompt fixture')],max_tokens=32)
        value.update(extra)
        return await self.client.post('/ollama/v1/chat/completions',json=value,headers={'Authorization':'Bearer '+'x'*32})

    async def test_nonstream_translation_no_silent_input_rewrite_and_real_usage(self):
        response=await self.post()
        value=await response.json()
        self.assertEqual(value['choices'][0]['message']['content'],'READY')
        self.assertEqual(value['usage'],dict(prompt_tokens=20,completion_tokens=3,total_tokens=23))
        self.assertEqual(self.requests[0]['messages'][0]['content'],'PRIVATE prompt fixture')
        self.assertIs(self.requests[0]['truncate'],False)
        self.assertIs(self.requests[0]['shift'],False)
        self.assertEqual(self.requests[0]['options']['num_ctx'],65536)
        self.assertEqual(self.requests[0]['options']['num_predict'],32)
        self.assertTrue(response.headers['X-Request-ID'])

    async def test_stream_tools_and_history_round_trip(self):
        response=await self.post(stream=True,stream_options={'include_usage':True},
            tools=[dict(type='function',function=dict(name='lookup',parameters={'type':'object'}))])
        text=await response.text()
        self.assertEqual(response.content_type,'text/event-stream')
        events=[json.loads(line[6:]) for line in text.splitlines() if line.startswith('data: {')]
        tool=events[0]['choices'][0]['delta']['tool_calls'][0]
        self.assertEqual(tool['function']['name'],'lookup')
        self.assertEqual(json.loads(tool['function']['arguments']),{'key':'fixture'})
        self.assertEqual(events[-2]['choices'][0]['finish_reason'],'tool_calls')
        self.assertEqual(events[-1]['usage']['completion_tokens'],3)
        self.assertIn('data: [DONE]',text)
        native=messages_to_native([dict(role='assistant',content=None,tool_calls=[{k:v for k,v in tool.items() if k!='index'}]),
                                   dict(role='tool',tool_call_id=tool['id'],content='result')])
        self.assertEqual(native[-1],dict(role='tool',content='result',tool_name='lookup'))
        self.assertEqual(native[0]['tool_calls'][0]['function']['arguments'],{'key':'fixture'})

    async def test_catalog_filters_downloaded_models_and_publishes_accepted_ids(self):
        response=await self.client.get('/ollama/v1/models',headers={'Authorization':'Bearer '+'x'*32})
        self.assertEqual([v['id'] for v in (await response.json())['data']],['gemma4:12b','qwen'])
        self.assertEqual(self.requests,[])

    async def test_native_rejection_passes_through_without_replay(self):
        response=await self.post(messages=[dict(role='user',content='reject')])
        self.assertEqual(response.status,400)
        await response.read()
        self.assertEqual(len(self.requests),1)
        self.assertIsNone(self.scheduler.fault)

    @unittest.skipUnless(os.environ.get('PI_TEST_BINARY'),'optional installed-Pi interoperability check')
    async def test_actual_pi_cli_against_native_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            source=json.loads((Path(__file__).resolve().parents[2]/'agents/models.json').read_text())
            provider=source['providers']['ollama']
            provider['baseUrl']=str(self.client.make_url('/ollama/v1')).rstrip('/')
            provider['apiKey']='x'*32
            (path/'models.json').write_text(json.dumps(dict(providers={'fixture':provider})))
            env=dict(os.environ,PI_CODING_AGENT_DIR=directory)
            process=await asyncio.create_subprocess_exec(os.environ['PI_TEST_BINARY'],
                '--no-extensions','--no-skills','--no-tools','--no-session','--provider','fixture',
                '--model','gemma4:12b','--thinking','off','-p','Reply READY only.',cwd=directory,env=env,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            try:
                async with asyncio.timeout(45):
                    stdout,stderr=await process.communicate()
                self.assertEqual(process.returncode,0,stderr.decode())
                self.assertIn('READY',stdout.decode())
                self.assertEqual(len(self.requests),1)
                self.assertIs(self.requests[0]['shift'],False)
                self.assertIs(self.requests[0]['truncate'],False)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

    @unittest.skipUnless(os.environ.get('PI_TEST_BINARY'),'optional installed-Pi tool round trip')
    async def test_actual_pi_tool_call_result_and_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/'fixture.txt').write_text('fixture-data')
            self.tool_file=str(path/'fixture.txt')
            provider=json.loads((Path(__file__).resolve().parents[2]/'agents/models.json').read_text())['providers']['ollama']
            provider.update(baseUrl=str(self.client.make_url('/ollama/v1')).rstrip('/'),apiKey='x'*32)
            (path/'models.json').write_text(json.dumps(dict(providers={'fixture':provider})))
            process=await asyncio.create_subprocess_exec(os.environ['PI_TEST_BINARY'],
                '--no-extensions','--no-skills','--tools','read','--no-session','--provider','fixture',
                '--model','gemma4:12b','--thinking','off','-p','Read fixture.txt then reply READY.',
                cwd=directory,env=dict(os.environ,PI_CODING_AGENT_DIR=directory),
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            try:
                async with asyncio.timeout(45):
                    stdout,stderr=await process.communicate()
                self.assertEqual(process.returncode,0,stderr.decode())
                self.assertIn('READY',stdout.decode())
                self.assertEqual(len(self.requests),2)
                result=self.requests[1]['messages'][-1]
                self.assertEqual(result['role'],'tool')
                self.assertEqual(result['tool_name'],'read')
                self.assertIn('fixture-data',result['content'])
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

    def test_invalid_controls_images_and_output_overflow_refused(self):
        for change in (dict(n=2),dict(n=True),dict(max_tokens=8193),dict(keep_alive=0),dict(tool_choice='required'),
                       dict(messages=[dict(role='user',content=[dict(type='image_url',image_url='private')])])):
            value=dict(model='gemma4:12b',messages=[dict(role='user',content='fixture')])
            value.update(change)
            with self.subTest(change=change),self.assertRaises(AdmissionError):
                self.protocol.admit('POST','/v1/chat/completions',json.dumps(value).encode())
        self.assertIsNone(usage({}))
