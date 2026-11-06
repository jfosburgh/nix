"""Development HTTP front door. No listener, real adapters or auto-resume on import.

Use create_runner(), behind the eventual network ACL.
All paths require a bearer token; this does not replace LAN/tailnet restrictions.
"""
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import hmac
from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, web
from multidict import CIMultiDict

from .diagnostics import event, failure
from .backend_http import loopback_origin
from .protocol import AdmissionError, Protocol
from .scheduler import Rejected, Scheduler

HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length'}
PRIVATE = {'authorization', 'x-api-key', 'cookie', 'set-cookie', 'forwarded', 'x-forwarded-for',
           'x-forwarded-host', 'x-forwarded-proto', 'proxy-connection'}


def headers_for_proxy(headers):
    nominated = {item.strip().lower() for value in headers.getall('Connection', [])
                 for item in value.split(',')}
    return CIMultiDict((k, v) for k, v in headers.items()
                      if k.lower() not in HOP | PRIVATE | nominated)


@dataclass(frozen=True)
class Endpoint:
    upstream: str
    protocol: Protocol
    bearer_token: str | None = field(default=None, repr=False)

    def __post_init__(self):
        loopback_origin(self.upstream)


def create_runner(app: web.Application) -> web.AppRunner:
    """Disable request decompression before admission and prompt-bearing access logs."""
    return web.AppRunner(app, handler_cancellation=True, auto_decompress=False, access_log=None)


def create_app(scheduler: Scheduler, endpoints: dict[str, Endpoint], *, token: str,
               max_body: int = 1024 * 1024, max_connections: int = 32,
               body_timeout: float = 10, stream_idle: float = 60,
               queue_timeout: float = 300, max_discovery_bytes: int = 256 * 1024,
               discovery_timeout: float = 10, admin_token: str | None = None,
               admin_timeout: float = 120) -> web.Application:
    if len(token) < 24 or set(endpoints) != set(scheduler.backends):
        raise ValueError('Strong token and complete explicit endpoint registry required')
    if min(max_body, max_connections, body_timeout, stream_idle, queue_timeout,
           max_discovery_bytes, discovery_timeout) <= 0:
        raise ValueError('Positive transport limits required')
    if admin_token is not None and (len(admin_token) < 24 or admin_token == token):
        raise ValueError('Administration requires a strong, distinct bearer token')
    if not 0 < admin_timeout < float('inf'):
        raise ValueError('Finite positive administration deadline required')
    app = web.Application(client_max_size=max_body)
    wakeup = asyncio.Event()
    session = None
    connections = 0
    admin_task = None

    async def administer(action):
        event('admin_begin', action=action)
        # Invalidated before awaiting the worker lock: timeout while waiting for
        # active inference must not leave old reconciliation sufficient to resume.
        if action != 'resume':
            scheduler.maintenance = True
            scheduler.reconciled = False
        try:
            async with asyncio.timeout(admin_timeout):
                if action == 'resume':
                    scheduler.resume()
                elif action == 'drain':
                    await scheduler.drain()
                    # Successful all-backend release is a fresh reconciliation.
                    if scheduler.fault is None:
                        scheduler.reconciled = True
                else:
                    await scheduler.reconcile()
            event('admin_complete', action=action, state=scheduler.state.value)
            return web.json_response(scheduler.snapshot(), headers={'Cache-Control': 'no-store'})
        except Rejected:
            return web.json_response({'error': 'Verified idle reconciliation required'}, status=409,
                                     headers={'Cache-Control': 'no-store'})
        except Exception as error:
            failure('admin_failed', error, action=action)
            scheduler.maintenance = True
            scheduler.reconciled = False
            return web.json_response({'error': 'Administration failed; reconciliation required'},
                                     status=503, headers={'Cache-Control': 'no-store', 'Retry-After': '1'})

    async def worker():
        while True:
            await wakeup.wait()
            wakeup.clear()
            try:
                while await scheduler.run_next():
                    pass
            except Exception as error:
                failure('worker_failed', error)
                # Scheduler records a sanitized fault and fails queued callers.
                # Never retry inference or expose exception text to clients.
                pass

    async def expiry():
        while True:
            scheduler.expire_queued()
            await asyncio.sleep(0.02)

    async def lifecycle(app):
        nonlocal session
        async with ClientSession(auto_decompress=False, trust_env=False, cookie_jar=DummyCookieJar(),
                                 timeout=ClientTimeout(total=None, connect=10, sock_read=stream_idle),
                                 skip_auto_headers={'Accept-Encoding'}) as session:
            tasks = [asyncio.create_task(worker()), asyncio.create_task(expiry())]
            yield
            # A disconnected admin caller must not cancel a partially completed transition.
            if admin_task is not None:
                await admin_task
            # Shutdown stays in maintenance. Verified release is a lifecycle-adapter duty.
            scheduler.maintenance = True
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await scheduler.drain()
    app.cleanup_ctx.append(lifecycle)

    async def handle(request):
        nonlocal connections, admin_task
        is_admin = request.path.startswith('/coordinator/admin/')
        credential = admin_token if is_admin else token
        if credential is None:
            raise web.HTTPNotFound()
        expected = 'Bearer ' + credential
        supplied = request.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            event('authentication_rejected', status=401, admin=is_admin)
            raise web.HTTPUnauthorized()
        if connections >= max_connections:
            event('connection_limit_reached', limit=max_connections)
            raise web.HTTPServiceUnavailable(headers={'Retry-After': '1'})
        connections += 1
        job, monitor = None, None
        response = None
        try:
            if request.query_string or request.headers.get('Upgrade') or request.headers.get('Content-Encoding'):
                raise AdmissionError(400, 'Queries, upgrades and encoded request bodies are unsupported')
            # Do not allow URL normalization to turn unknown routes into admitted routes.
            if '%' in request.raw_path or '//' in request.path:
                raise AdmissionError(404, 'Unsupported path')
            if is_admin:
                action = request.path.removeprefix('/coordinator/admin/')
                if action not in {'drain', 'reconcile', 'resume'}:
                    raise AdmissionError(404, 'Unsupported administration operation')
                if request.method != 'POST' or request.can_read_body:
                    raise AdmissionError(405, 'Administration supports bodyless POST only')
                # Bearer-only, non-browser control surface. Never accept ambient
                # browser credentials or an Origin, even with a valid token.
                if request.headers.get('Origin') is not None or request.headers.get('Cookie') is not None:
                    raise AdmissionError(403, 'Browser administration is unsupported')
                if admin_task is not None and not admin_task.done():
                    raise AdmissionError(409, 'Administration operation in progress')
                admin_task = asyncio.create_task(administer(action))
                return await asyncio.shield(admin_task)
            if request.path == '/coordinator/status':
                if request.method != 'GET' or request.can_read_body:
                    raise AdmissionError(405, 'Status supports bodyless GET only')
                return web.json_response(scheduler.snapshot(), headers={'Cache-Control': 'no-store'})
            parts = request.path.split('/', 2)
            if len(parts) != 3 or parts[1] not in endpoints:
                raise AdmissionError(404, 'Unsupported provider')
            backend, path = parts[1], '/' + parts[2]
            endpoint = endpoints[backend]
            try:
                async with asyncio.timeout(body_timeout):
                    body = await request.read()
            except TimeoutError:
                raise AdmissionError(408, 'Request body deadline exceeded') from None
            admission = endpoint.protocol.admit(request.method, path, body)
            if admission.inference and request.method != 'POST':
                # aiohttp may retry methods it considers idempotent. Only POST
                # inference is supported until other methods have a no-replay transport.
                raise AdmissionError(405, 'Only POST inference is supported')
            expected_type = endpoint.protocol.content_type
            if admission.inference and expected_type and request.content_type != expected_type:
                raise AdmissionError(415, 'Unsupported request content type')
            if len(admission.body) > max_body:
                raise AdmissionError(413, 'Normalized request exceeds body limit')
            if admission.inference:
                if scheduler.maintenance or scheduler.fault:
                    raise Rejected('Coordinator unavailable')
                # This must never load a model or acquire an inference lease.
                # Handler cancellation also cancels in-progress CPU accounting.
                await endpoint.protocol.validate_input(path, admission)

            async def execute():
                nonlocal response
                upstream_headers = headers_for_proxy(request.headers)
                if endpoint.bearer_token is not None:
                    upstream_headers['Authorization'] = 'Bearer ' + endpoint.bearer_token
                if job is not None:
                    upstream_headers['X-Request-ID'] = job.request_id
                async with session.request(request.method, endpoint.upstream.rstrip('/') + (admission.upstream_path or path),
                                           data=admission.body or None,
                                           headers=upstream_headers,
                                           allow_redirects=False) as upstream:
                    if 300 <= upstream.status < 400 or upstream.status == 101:
                        raise RuntimeError('Unsupported upstream redirect/upgrade')
                    if not admission.inference and endpoint.protocol.buffers_discovery:
                        if (upstream.status != 200 or upstream.content_type != 'application/json'
                                or upstream.headers.get('Content-Encoding')):
                            raise AdmissionError(502, 'Unexpected upstream discovery response')
                        catalog = bytearray()
                        async for chunk in upstream.content.iter_chunked(8192):
                            catalog.extend(chunk)
                            if len(catalog) > max_discovery_bytes:
                                raise AdmissionError(502, 'Upstream discovery response exceeds byte limit')
                        filtered = endpoint.protocol.discovery_response(path, bytes(catalog))
                        return web.Response(body=filtered, content_type='application/json',
                                            headers={'Cache-Control': 'no-store'})
                    event('upstream_response', backend=backend,
                          request_id=job.request_id if job else None, status=upstream.status)
                    response = web.StreamResponse(status=upstream.status,
                                                  headers=headers_for_proxy(upstream.headers))
                    if job is not None:
                        response.headers['X-Request-ID'] = job.request_id
                    if admission.response_adapter and upstream.status == 200:
                        from .openai_ollama import relay
                        await relay(upstream,response,request,request_id=job.request_id,
                                    streaming=admission.response_adapter=='openai-stream',idle=stream_idle)
                        return response
                    await response.prepare(request)
                    async for chunk in upstream.content.iter_chunked(65536):
                        # write waits on aiohttp flow control; no unbounded response queue.
                        async with asyncio.timeout(stream_idle):
                            await response.write(chunk)
                    await response.write_eof()
                    return response

            if not admission.inference:
                # Only explicit discovery routes; no lifecycle prepare/load or lease.
                async with asyncio.timeout(discovery_timeout):
                    return await execute()
            job = scheduler.submit(backend, admission.operation, len(admission.body), execute,
                                   queue_timeout=queue_timeout)
            wakeup.set()

            async def watch_disconnect():
                while not job.result.done():
                    if request.transport is None or request.transport.is_closing():
                        event('client_disconnect', request_id=job.request_id, backend=job.backend)
                        job.result.cancel()
                        return
                    await asyncio.sleep(0.02)
            monitor = asyncio.create_task(watch_disconnect())
            return await asyncio.shield(job.result)
        except AdmissionError as exc:
            event('request_rejected', status=exc.status)
            return web.json_response({'error': exc.message}, status=exc.status)
        except Rejected:
            if response is not None and response.prepared:
                if request.transport:
                    request.transport.abort()  # Never append JSON to a partial stream.
                return response
            headers = {'Retry-After': '1'}
            if job is not None:
                headers['X-Request-ID'] = job.request_id
            return web.json_response({'error': 'Inference unavailable; request not replayed'},
                                     status=503, headers=headers)
        except asyncio.CancelledError:
            if job is not None:
                event('handler_cancelled', request_id=job.request_id, backend=job.backend)
                job.result.cancel()
            raise
        except web.HTTPException:
            raise
        except Exception as error:
            failure('http_request_failed', error, request_id=job.request_id if job else None,
                    backend=job.backend if job else None)
            if response is not None and response.prepared:
                if request.transport:
                    request.transport.abort()
                return response
            return web.json_response({'error': 'Upstream unavailable; request not replayed'}, status=502)
        finally:
            connections -= 1
            if monitor:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor

    app.router.add_route('*', '/{path:.*}', handle)
    return app
