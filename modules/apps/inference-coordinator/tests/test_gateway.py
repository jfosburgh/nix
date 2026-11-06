import socket
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer

from coordinator import gateway


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0))
            self.port=probe.getsockname()[1]
        self.calls=[]
        async def handler(request):
            self.calls.append(request.path)
            return web.json_response(dict(path=request.path,authorized=request.headers.get('Authorization')=='Bearer '+'x'*32,
                                          content=(await request.read()).decode()))
        app=web.Application()
        app.router.add_route('*','/{path:.*}',handler)
        gateway.install_gateway(app,'x'*32,port=self.port)
        self.client=TestClient(TestServer(app,port=self.port))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_rewrites_strata_and_injects_client_scope_for_ollama(self):
        for path,expected in (('/v1/chat/completions','/strata/v1/chat/completions'),
                              ('/ollama/v1/chat/completions','/ollama/v1/chat/completions')):
            response=await self.client.post(path,data='synthetic body',headers={'Authorization':'Bearer dummy'})
            value=await response.json()
            self.assertEqual(value,dict(path=expected,authorized=True,content='synthetic body'))

    async def test_admin_controls_raw_engines_and_queries_never_reach_handler(self):
        for path in ('/coordinator/admin/resume','/load','/unload','/settings','/api/chat','/v1/models?secret=query'):
            response=await self.client.post(path)
            self.assertIn(response.status,(400,404,405))
            await response.read()
        self.assertEqual(self.calls,[])

    async def test_actual_peer_not_forwarded_headers_is_authority(self):
        with patch.object(gateway,'PEERS',frozenset({'100.64.0.1'})):
            response=await self.client.get('/v1/models',headers={'X-Forwarded-For':'100.64.0.1'})
        self.assertEqual(response.status,403)
        self.assertEqual(self.calls,[])

    async def test_foreign_browser_origin_refused(self):
        response=await self.client.post('/v1/chat/completions',headers={'Origin':'https://evil.invalid'})
        self.assertEqual(response.status,403)
        self.assertEqual(self.calls,[])
        response=await self.client.post('/v1/chat/completions',headers={'Origin':'https://strata.threegoldenhairs.me'})
        self.assertEqual(response.status,200)

    def test_nonloading_ui_allowlist_is_explicit(self):
        for path in ('/','/web/app.js','/fonts/font.woff','/health','/status'):
            self.assertTrue(gateway.static_path(path))
        for path in ('/config','/settings','/mcp','/load','/unload','/slots'):
            self.assertFalse(gateway.static_path(path))
