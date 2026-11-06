"""Strata/Ollama lifecycle adapters. No installed service is contacted on import.

Ollama release requires an injected quiescence proof, not just an empty /api/ps.
Real process supervision/quiescence and memory calibration are integration work.
"""
import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from .backend_http import ControlClient, LifecycleError, strict_json


@dataclass(frozen=True)
class StrataStatus:
    loaded: bool
    busy: bool
    queued: int
    model: str
    context: int


class StrataLifecycle:
    def __init__(self, client: ControlClient, *, model: str, context: int,
                 release_timeout: float = 90, poll_interval: float = 0.25):
        if not model or type(context) is not int or context <= 0 or min(release_timeout, poll_interval) <= 0:
            raise ValueError('Explicit Strata profile and positive lifecycle limits required')
        self.client, self.model, self.context = client, model, context
        self.release_timeout, self.poll_interval = release_timeout, poll_interval

    async def inspect(self) -> StrataStatus:
        _, health = await self.client.request('GET', '/health')
        _, status = await self.client.request('GET', '/status')
        if (health.get('service') != 'strata' or health.get('status') != 'ok'
                or type(health.get('loaded')) is not bool
                or health.get('model') != self.model
                or type(health.get('max_context')) is not int
                or health['max_context'] != self.context
                or health.get('images') is not False or health.get('image_generation') is not False
                or type(status.get('busy')) is not bool
                or type(status.get('queued')) is not int or status['queued'] < 0):
            raise LifecycleError('Unexpected Strata profile/status or unsupported auxiliary engine')
        return StrataStatus(health['loaded'], status['busy'], status['queued'], self.model, self.context)

    async def prepare(self, operation: str) -> None:
        if operation not in ('chat', 'completion'):
            raise LifecycleError('Unsupported Strata operation')
        before = await self.inspect()
        if before.busy or before.queued:
            raise LifecycleError('Untracked Strata work prevents preparation')
        if not before.loaded:
            _, response = await self.client.request('POST', '/load', {})
            if response.get('status') != 'loaded':
                raise LifecycleError('Strata did not acknowledge loading')
        after = await self.inspect()
        if not after.loaded or after.busy or after.queued:
            raise LifecycleError('Strata did not become loaded and idle')

    async def release(self) -> None:
        try:
            async with asyncio.timeout(self.release_timeout):
                while True:
                    code, response = await self.client.request('POST', '/unload', {},
                                                               statuses=frozenset({200, 409}))
                    status = response.get('status')
                    if code == 409 and status == 'busy':
                        await asyncio.sleep(self.poll_interval)
                        continue
                    if code != 200 or status not in ('unloaded', 'not loaded'):
                        raise LifecycleError('Strata cannot confirm engine release')
                    after = await self.inspect()
                    if after.loaded or after.busy or after.queued:
                        raise LifecycleError('Strata release verification failed')
                    return
        except TimeoutError:
            raise LifecycleError('Strata release deadline exceeded') from None


@dataclass(frozen=True)
class OllamaProfile:
    resident_name: str  # Exact /api/ps display name; no implicit alias guessing.
    context: int
    operations: frozenset[str]

    def __post_init__(self):
        if (not self.resident_name or type(self.context) is not int or self.context <= 0
                or not self.operations or self.operations - {'chat', 'generate', 'completion', 'embed'}):
            raise ValueError('Explicit resident name, context and capabilities required')


@dataclass(frozen=True)
class OllamaResident:
    name: str
    context: int


class OllamaLifecycle:
    def __init__(self, client: ControlClient, profiles: dict[str, OllamaProfile], *,
                 quiesce: Callable[[], Awaitable[None]],
                 memory_gate: Callable[[str, int], Awaitable[None]],
                 expected_version: str, release_timeout: float = 90, poll_interval: float = 0.25,
                 context_shift: bool = True, verify_resident_memory: bool = False):
        if (type(verify_resident_memory) is not bool or type(context_shift) is not bool or not profiles or not expected_version
                or not callable(quiesce) or not callable(memory_gate)
                or min(release_timeout, poll_interval) <= 0):
            raise ValueError('Profiles, version, quiescence proof and memory admission required')
        if len({p.resident_name for p in profiles.values()}) != len(profiles):
            raise ValueError('Ambiguous Ollama resident aliases')
        self.client, self.profiles = client, dict(profiles)
        self.quiesce, self.memory_gate = quiesce, memory_gate
        self.expected_version = expected_version
        self.context_shift = context_shift
        self.verify_resident_memory = verify_resident_memory
        self.release_timeout, self.poll_interval = release_timeout, poll_interval
        # A cancelled/timed-out load may outlive its HTTP connection. Require
        # quiescence/release before this adapter can ever attempt another load.
        self.uncertain = True

    async def inspect(self) -> tuple[OllamaResident, ...]:
        _, version = await self.client.request('GET', '/api/version')
        if version.get('version') != self.expected_version:
            raise LifecycleError('Ollama version differs from validated configuration')
        _, response = await self.client.request('GET', '/api/ps')
        values = response.get('models')
        if not isinstance(values, list):
            raise LifecycleError('Invalid Ollama residency response')
        residents = []
        for value in values:
            if (not isinstance(value, dict) or not isinstance(value.get('name'), str) or not value['name']
                    or value.get('model') != value['name']
                    or type(value.get('context_length')) is not int or value['context_length'] < 0):
                raise LifecycleError('Invalid Ollama resident model')
            residents.append(OllamaResident(value['name'], value['context_length']))
        if len({item.name for item in residents}) != len(residents):
            raise LifecycleError('Ambiguous Ollama resident model list')
        return tuple(residents)

    def _operation(self, operation: str) -> tuple[str, str, int]:
        if not isinstance(operation, str):
            raise LifecycleError('Invalid Ollama admission metadata')
        try:
            value = strict_json(operation.encode())
        except (ValueError, UnicodeError, RecursionError):
            raise LifecycleError('Invalid Ollama admission metadata') from None
        if not isinstance(value, list) or len(value) != 3:
            raise LifecycleError('Invalid Ollama admission metadata')
        kind, model, context = value
        if not isinstance(model, str) or model not in self.profiles or not isinstance(kind, str):
            raise LifecycleError('Unapproved Ollama admission')
        profile = self.profiles[model]
        if kind not in profile.operations or type(context) is not int or not 0 < context <= profile.context:
            raise LifecycleError('Unsupported Ollama operation/context')
        return kind, model, context

    async def prepare(self, operation: str) -> None:
        kind, model, context = self._operation(operation)
        if self.uncertain:
            raise LifecycleError('Ollama requires verified reconciliation')
        profile = self.profiles[model]
        residents = await self.inspect()
        target = (OllamaResident(profile.resident_name, context),)
        if residents and residents != target:
            # Same-backend model/context changes require release BEFORE the
            # per-model memory gate. Never rely on Ollama's automatic eviction.
            await self.release()
            residents = ()
        await self.memory_gate(model, context)
        if residents == target:
            return
        self.uncertain = True
        if kind == 'embed':
            path = '/api/embed'
            body = {'model': model, 'input': [], 'keep_alive': -1,
                    'truncate': False, 'options': {'num_ctx': context}}
        else:
            path = '/api/generate'
            body = {'model': model, 'prompt': '', 'stream': False,
                    'keep_alive': -1, 'options': {'num_ctx': context}}
        if kind != 'embed' and not self.context_shift:
            # The runner's context-shift policy is a LOAD-time choice. Match the
            # native trial's inference guard to avoid a hidden runner replacement.
            body['shift'] = False
            body['truncate'] = False
        _, response = await self.client.request('POST', path, body)
        if kind == 'embed':
            if response.get('model') != model or response.get('embeddings') != []:
                raise LifecycleError('Ollama did not acknowledge embedding warmup')
        elif response.get('done') is not True or response.get('done_reason') != 'load':
            raise LifecycleError('Ollama did not acknowledge model load')
        if await self.inspect() != target:
            raise LifecycleError('Ollama residency/context verification failed')
        if self.verify_resident_memory:
            try:
                await self.memory_gate(model,context)
            except Exception:
                # A new profile may fit cold but leave too little resident RAM.
                # Unload it before reporting failure; never start inference there.
                await self.release()
                raise
        self.uncertain = False

    async def release(self) -> None:
        self.uncertain = True
        try:
            async with asyncio.timeout(self.release_timeout):
                # Required even on startup and after cancellation. /api/ps alone
                # cannot prove there are no pending/admitting model loads.
                await self.quiesce()
                requested = set()
                while True:
                    residents = await self.inspect()
                    if not residents:
                        self.uncertain = False
                        return
                    for resident in residents:
                        if resident.name in requested:
                            continue
                        _, response = await self.client.request('POST', '/api/generate',
                                                               {'model': resident.name, 'prompt': '',
                                                                'stream': False, 'keep_alive': 0})
                        if response.get('done') is not True or response.get('done_reason') != 'unload':
                            raise LifecycleError('Ollama did not acknowledge model eviction')
                        requested.add(resident.name)
                    # Acknowledgement schedules eviction; it is not release proof.
                    await asyncio.sleep(self.poll_interval)
        except TimeoutError:
            raise LifecycleError('Ollama release deadline exceeded') from None
