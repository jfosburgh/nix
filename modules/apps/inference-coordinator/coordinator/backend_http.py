"""Bounded, loopback-only JSON control transport. Never replays mutating calls."""
import json
import logging
from .diagnostics import event
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout, DummyCookieJar


class LifecycleError(Exception):
    """Sanitized backend control failure; never includes response bodies/secrets."""


def loopback_origin(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', '::1')
            or url.username or url.password or url.path not in ('', '/')
            or url.query or url.fragment or not url.port):
        raise ValueError('Upstreams must be explicit loopback HTTP origins')
    return value.rstrip('/')


def strict_json(body: bytes):
    def invalid_constant(value):
        raise ValueError('Non-finite JSON number')
    return json.loads(body, parse_constant=invalid_constant)


class ControlClient:
    def __init__(self, upstream: str, *, bearer_token: str | None = None,
                 timeout: float = 120, max_response_bytes: int = 65536):
        self.upstream = loopback_origin(upstream)
        if timeout <= 0 or max_response_bytes <= 0:
            raise ValueError('Positive control limits required')
        self._token = bearer_token
        self.timeout, self.max_response_bytes = timeout, max_response_bytes
        self._session = None

    async def __aenter__(self):
        if self._session is not None:
            raise RuntimeError('Control client already open')
        self._session = ClientSession(
            auto_decompress=False, trust_env=False, cookie_jar=DummyCookieJar(),
            timeout=ClientTimeout(total=self.timeout, connect=min(10, self.timeout)),
            skip_auto_headers={'Accept-Encoding'})
        return self

    async def __aexit__(self, *exc):
        await self._session.close()
        self._session = None

    async def request(self, method: str, path: str, body: dict | None = None,
                      *, statuses: frozenset[int] = frozenset({200})) -> tuple[int, dict]:
        if self._session is None:
            raise LifecycleError('Control client is not open')
        if method not in ('GET', 'POST') or not path.startswith('/') or path.startswith('//') or '#' in path:
            raise ValueError('Unsupported control request')
        headers = {'Content-Type': 'application/json'}
        if self._token is not None:
            headers['Authorization'] = 'Bearer ' + self._token
        try:
            async with self._session.request(method, self.upstream + path,
                                             json=body, headers=headers,
                                             allow_redirects=False) as response:
                if response.status not in statuses or response.headers.get('Content-Encoding'):
                    event('control_response_invalid', level=logging.ERROR, upstream=self.upstream,
                          method=method, status=response.status, reason='status_or_encoding')
                    raise LifecycleError('Unexpected control response status/encoding')
                if response.content_type != 'application/json':
                    event('control_response_invalid', level=logging.ERROR, upstream=self.upstream,
                          method=method, status=response.status, reason='content_type')
                    raise LifecycleError('Expected a JSON control response')
                data = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    data.extend(chunk)
                    if len(data) > self.max_response_bytes:
                        raise LifecycleError('Control response exceeds byte limit')
                value = strict_json(bytes(data))
                if not isinstance(value, dict):
                    raise LifecycleError('Expected a JSON control object')
                return response.status, value
        except (ClientError, TimeoutError, ValueError, RecursionError):
            raise LifecycleError('Invalid or unavailable control response') from None
