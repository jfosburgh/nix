"""Full commissioning flow against loopback fakes and synthetic memory only."""
import copy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.calibrate import calibrate
from coordinator.memory import MemorySnapshot
from coordinator.production import load_calibrated
from coordinator.supervision import SupervisionError
from test_config import fixture

GIB=1024**3


class CalibrationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runners=[]
        self.strata=False
        self.context=131072
        self.ollama=False
        self.reject=True
        self.events=[]
        async def strata(request):
            body=await request.json() if request.method=='POST' else None
            if request.path=='/health':
                return web.json_response(dict(service='strata',status='ok',loaded=self.strata,
                    model='preserved-strata-profile',max_context=self.context,images=False,image_generation=False))
            if request.path=='/status':
                return web.json_response(dict(busy=False,queued=0))
            if request.path=='/unload':
                self.strata=False
                self.events.append('strata-release')
                return web.json_response(dict(status='unloaded'))
            if request.path=='/load':
                self.assertFalse(self.ollama)
                self.strata=True
                self.events.append('strata-load')
                return web.json_response(dict(status='loaded'))
            self.assertEqual(request.path,'/v1/chat/completions')
            self.assertTrue(self.strata)
            await __import__('asyncio').sleep(0.06)
            return web.json_response(dict(choices=[dict(message=dict(role='assistant',content='READY'))]))
        async def ollama(request):
            body=await request.json() if request.method=='POST' else None
            if request.path=='/api/version':
                return web.json_response(dict(version='0.40.11'))
            if request.path=='/api/ps':
                return web.json_response(dict(models=[dict(name='small:latest',model='small:latest',context_length=8192)] if self.ollama else []))
            self.assertFalse(self.strata)
            self.assertFalse(body['truncate'])
            self.assertFalse(body['shift'])
            if request.path=='/api/generate' and body.get('prompt')=='':
                self.ollama=True
                self.events.append('ollama-load')
                return web.json_response(dict(done=True,done_reason='load'))
            size=len(body.get('prompt',''))+sum(len(m['content']) for m in body.get('messages',[]))
            if size>100000 and self.reject:
                return web.json_response(dict(error='the prompt is longer than the context length currently available to the model'),status=400)
            await __import__('asyncio').sleep(0.06)
            return web.json_response(dict(done=True,message=dict(content='READY')))
        addresses=[]
        for handler in (strata,ollama):
            app=web.Application()
            app.router.add_route('*','/{path:.*}',handler)
            runner=web.AppRunner(app,access_log=None)
            await runner.setup()
            self.runners.append(runner)
            site=web.TCPSite(runner,'127.0.0.1',0)
            await site.start()
            addresses.append('http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1]))
        config=fixture()
        config['backends'][1]['input_policy']='native-reject-trial'
        for backend,address in zip(config['backends'],addresses):
            backend['upstream']=address
            targets=[backend] if backend['adapter']=='strata' else backend['models'].values()
            for target in targets:
                target['cold']=target['resident']=None
        self.device='/sys/bus/pci/devices/0000:08:00.0'
        self.raw=json.dumps(dict(configuration=config,deployment='a'*64,device=self.device)).encode()
        self.quiesce=AsyncMock(side_effect=self.release)

    async def asyncTearDown(self):
        for runner in self.runners:
            await runner.cleanup()

    async def release(self):
        self.ollama=False
        self.events.append('verified-ollama-release-fixture')

    def memory(self,device):
        used,available=(13,18) if self.strata else ((10,22) if self.ollama else (1,28))
        return MemorySnapshot(16*GIB,used*GIB,32*GIB,available*GIB,time.monotonic())

    async def exercise(self,**kwargs):
        with patch('coordinator.calibrate.os.geteuid',return_value=0), patch(
                'coordinator.calibrate._require_no_listener',new=AsyncMock()), patch(
                'coordinator.calibrate.read_operator_file',return_value=self.raw), patch(
                'coordinator.calibrate.SupervisorClient',return_value=self.quiesce), patch(
                'coordinator.calibrate.read_linux_memory',side_effect=self.memory), patch(
                'coordinator.calibrate._write_config') as output:
            try:
                await calibrate('/synthetic/template','/synthetic/output','/synthetic/socket')
            finally:
                self.output=output.call_args

    async def test_measurements_and_three_real_rejection_paths_required_before_publish(self):
        await self.exercise()
        self.assertIsNotNone(self.output)
        config=load_calibrated(json.dumps(self.output.args[1]).encode(),self.raw,self.device)
        self.assertEqual(config.backends[0].cold.vram_free,int(12.5*GIB))
        self.assertEqual(config.backends[1].models['small'].cold.vram_free,int(9.5*GIB))
        self.assertEqual(config.backends[0].resident.ram_available,2*GIB)
        self.assertEqual(config.backends[1].models['small'].resident.ram_available,6*GIB)
        self.assertEqual(self.output.args[1]['calibration']['observations']['strata']['ram_headroom_bytes'],2*GIB)
        self.assertFalse(self.strata)
        self.assertFalse(self.ollama)
        self.assertLess(self.events.index('strata-release'),self.events.index('ollama-load'))
        self.assertEqual(self.quiesce.await_count,2)

    async def test_headless_retains_six_gib_strata_margin(self):
        value=json.loads(self.raw)
        value['configuration']['profile']='headless'
        value['configuration']['backends'][0]['context']=262144
        self.context=262144
        self.raw=json.dumps(value).encode()
        await self.exercise()
        config=load_calibrated(json.dumps(self.output.args[1]).encode(),self.raw,self.device)
        self.assertEqual(config.backends[0].resident.ram_available,6*GIB)
        self.assertEqual(config.backends[1].models['small'].resident.ram_available,6*GIB)

    async def test_successful_oversize_inference_is_not_blessed_as_rejection(self):
        self.reject=False
        with self.assertRaisesRegex(SupervisionError,'oversize rejection not verified'):
            await self.exercise()
        self.assertIsNone(self.output)
        self.assertFalse(self.strata)
        self.assertFalse(self.ollama)
        self.assertEqual(self.quiesce.await_count,2)


if __name__=='__main__':
    unittest.main()
