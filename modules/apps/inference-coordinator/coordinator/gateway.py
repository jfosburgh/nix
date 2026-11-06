"""Trusted Blade/localhost ingress, sharing the same scheduler and HTTP app.

Port 18080 retains bearer authentication. Port 8081 accepts inference/discovery
only from Blade's actual tailnet source IP or localhost, injects the client scope
in memory, and never exposes admin controls. No credential files on Blade/Pi.
"""
from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, web

from .diagnostics import event
from .http import headers_for_proxy

PEERS = frozenset({'127.0.0.1','::1','100.64.0.1'})
ORIGINS = frozenset({'https://strata.threegoldenhairs.me',
                     'http://127.0.0.1:8081','http://localhost:8081'})


def ingress_path(path):
    if path.startswith('/v1/'):
        return '/strata'+path
    if path.startswith(('/strata/','/ollama/')) or path=='/coordinator/status':
        return path
    raise web.HTTPNotFound()


def static_path(path):
    return path in ('/','/health','/api/health','/status','/props') or path.startswith(('/web/','/fonts/'))


def install_gateway(app, token, *, port=8081):
    session = None

    async def sessions(app):
        nonlocal session
        async with ClientSession(trust_env=False,auto_decompress=False,cookie_jar=DummyCookieJar(),
                                 timeout=ClientTimeout(total=60,connect=5)) as session:
            yield
    app.cleanup_ctx.insert(0,sessions)

    @web.middleware
    async def ingress(request,handler):
        address = request.transport.get_extra_info('sockname')
        if not address or address[1] != port:
            return await handler(request)
        peer = request.transport.get_extra_info('peername')
        if not peer or peer[0] not in PEERS:
            event('gateway_peer_rejected')
            raise web.HTTPForbidden()
        if request.headers.get('Origin') not in (None,*ORIGINS) or request.headers.get('Sec-Fetch-Site')=='cross-site':
            event('gateway_origin_rejected')
            raise web.HTTPForbidden()
        if '%' in request.raw_path or '//' in request.path:
            raise web.HTTPNotFound()
        if static_path(request.path):
            if request.method!='GET' or request.can_read_body:
                raise web.HTTPMethodNotAllowed(request.method,['GET'])
            # Fixed non-loading GET surface for the existing Strata UI. No model
            # load/unload/settings/mcp/slots or raw inference forwarding.
            async with session.get('http://127.0.0.1:18081'+request.rel_url.path_qs,
                                   allow_redirects=False) as upstream:
                if upstream.status!=200:
                    raise web.HTTPBadGateway()
                response = web.StreamResponse(status=200,headers=headers_for_proxy(upstream.headers))
                await response.prepare(request)
                total = 0
                async for chunk in upstream.content.iter_chunked(65536):
                    total += len(chunk)
                    if total>32*1024**2:
                        raise RuntimeError('UI response exceeds bound')
                    await response.write(chunk)
                await response.write_eof()
                return response
        if request.query_string:
            raise web.HTTPBadRequest()
        path = ingress_path(request.path)
        headers = headers_for_proxy(request.headers)
        headers.popall('Origin',None)  # Validated browser origin; private backend host differs.
        headers['Authorization'] = 'Bearer '+token
        # Routing uses one catch-all handler, so cloned path is resolved by the
        # same explicit provider policy; never proxy straight to model engines.
        clone = request.clone(rel_url=request.rel_url.with_path(path),headers=headers)
        return await handler(clone)

    app.middlewares.append(ingress)
