"""Explicit development assembly, not a CLI, listener or production dependency set.

Construction does no I/O and never reconciles/resumes. AppRunner setup opens
control sessions; operator reconciliation is an explicit, potentially mutating
step. App cleanup drains before closing control sessions.
"""
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping, Protocol

from aiohttp import web

from .backend_http import ControlClient
from .budget import InputCounter
from .config import BackendConfig, Config
from .credentials import Credentials
from .http import Endpoint, create_app
from .lifecycle import OllamaLifecycle, OllamaProfile, OllamaResident, StrataLifecycle
from .protocol import ModelLimits, OllamaProtocol, StrataProtocol
from .native_trial import NativeTrialProtocol
from .openai_ollama import OllamaChatProtocol
from .scheduler import Backend, Scheduler


class AssemblyError(ValueError):
    """Sanitized dependency/credential mismatch; no secret values."""


class MemoryAdmission(Protocol):
    async def check(self, backend: BackendConfig, *, model: str, context: int,
                    resident: bool) -> None:
        """Check fresh telemetry with calibrated budget selection; never load models.

        `backend` includes cold/resident budget data. `resident` means the exact
        requested profile was observed, not that another allocation is safe.
        Smaller contexts need an explicit validated budget strategy or rejection.
        Exceptions fail closed. This callback is cancellation-cooperative.
        """
        ...


@dataclass(frozen=True, repr=False)
class Runtime:
    scheduler: Scheduler
    app: web.Application
    endpoints: Mapping[str, Endpoint] = field(repr=False)

    def __repr__(self):
        return 'Runtime(<maintenance-capable development assembly>)'


def assemble(config: Config, credentials: Credentials, *, memory: MemoryAdmission,
             counters: Mapping[str, InputCounter],
             quiescence: Mapping[str, Callable[[], Awaitable[None]]]) -> Runtime:
    """Build configured real adapters with explicitly injected safety contracts.

    Dependency registries are keyed by backend ID, not hardcoded route names.
    Each Ollama backend requires exactly one counter and quiescence callback.
    Memory/calibration, counter correctness and quiescence proof are trusted
    integration contracts; presence/callability is not production validation.
    Use parsed Config and securely loaded Credentials, never synthetic fixtures
    for a real deployment. This function neither loads nor reads credentials.
    """
    required = {b.id for b in config.backends if b.adapter == 'ollama'}
    counted = {b.id for b in config.backends if b.adapter == 'ollama' and b.input_policy == 'counted'}
    backend_secrets = {b.id for b in config.backends if b.credential_file is not None}
    if (not isinstance(counters, Mapping) or not isinstance(quiescence, Mapping)
            or set(counters) != counted or set(quiescence) != required
            or any(not callable(getattr(c, 'count', None)) for c in counters.values())
            or any(not callable(q) for q in quiescence.values())
            or not callable(getattr(memory, 'check', None))):
        raise AssemblyError('Complete explicit safety dependencies required')
    if (set(credentials.backend_tokens) != backend_secrets
            or (credentials.admin_token is not None) != (config.admin_token_file is not None)):
        raise AssemblyError('Credentials do not match configured scopes')
    # Validate even directly constructed Credentials; never let a caller bypass
    # cross-scope separation or smuggle control characters into upstream headers.
    secrets = [credentials.token] + list(credentials.backend_tokens.values())
    if credentials.admin_token is not None:
        secrets.append(credentials.admin_token)
    if (any(not isinstance(secret, str) or not 24 <= len(secret) <= 4096
            or any(not 0x21 <= ord(c) <= 0x7e for c in secret) for secret in secrets)
            or len(set(secrets)) != len(secrets)):
        raise AssemblyError('Invalid or overlapping credential scopes')
    limits = config.limits
    clients, backends, endpoints = [], [], {}
    configs = {b.id: b for b in config.backends}

    def strata_adapter(registration, client):
        adapter = StrataLifecycle(client, model=registration.model, context=registration.context,
                                  release_timeout=limits.lifecycle_timeout)
        return adapter

    def ollama_adapter(registration, client):
        async def model_memory(model, context):
            residents = await adapter.inspect()
            target = (OllamaResident(registration.models[model].resident_name, context),)
            if residents and residents != target:
                # Do not select a cold budget on top of unexpected allocations.
                raise AssemblyError('Unexpected residency during memory admission')
            await memory.check(registration, model=model, context=context, resident=residents == target)

        adapter = OllamaLifecycle(client, {
            model: OllamaProfile(profile.resident_name, profile.context,
                                 frozenset({'chat', 'generate', 'completion', 'embed'}))
            for model, profile in registration.models.items()
        }, quiesce=quiescence[registration.id], memory_gate=model_memory,
            expected_version=registration.expected_version, release_timeout=limits.lifecycle_timeout,
            context_shift=registration.input_policy not in ('native-reject', 'native-reject-trial'),
            verify_resident_memory=registration.input_policy=='native-reject')
        return adapter

    for registration in config.backends:
        secret = credentials.backend_tokens.get(registration.id)
        client = ControlClient(registration.upstream, bearer_token=secret,
                               timeout=limits.lifecycle_timeout,
                               max_response_bytes=limits.max_discovery_bytes)
        clients.append(client)
        if registration.adapter == 'strata':
            adapter = strata_adapter(registration, client)
            protocol = StrataProtocol()
        else:
            adapter = ollama_adapter(registration, client)
            models = {key: ModelLimits(model.context, model.output)
                      for key, model in registration.models.items()}
            names = {key: model.catalog_name for key, model in registration.models.items()}
            if registration.input_policy in ('native-reject', 'native-reject-trial'):
                protocol_type = OllamaChatProtocol if registration.input_policy == 'native-reject' else NativeTrialProtocol
                protocol = protocol_type(models, expected_version=registration.expected_version,
                                         catalog_names=names)
            elif registration.input_policy == 'counted':
                protocol = OllamaProtocol(models, counter=counters[registration.id],
                                          count_timeout=limits.count_timeout, catalog_names=names)
            else:
                raise AssemblyError('Unsupported input admission policy')
        backends.append(Backend(registration.id, registration.priority, registration.resources, adapter))
        endpoints[registration.id] = Endpoint(registration.upstream, protocol, secret)

    async def handoff_memory(backend, operation):
        registration = configs[backend.id]
        if registration.adapter == 'strata':
            status = await backend.lifecycle.inspect()
            if status.busy or status.queued:
                raise AssemblyError('Untracked work during memory admission')
            await memory.check(registration, model=status.model, context=status.context,
                               resident=status.loaded)
        # Ollama's model/context check belongs inside prepare, AFTER any required
        # same-backend eviction. Do not run a second cold-load gate here.

    scheduler = Scheduler(backends, memory_gate=handoff_memory,
                          max_queue=limits.max_queue, max_queue_bytes=limits.max_queue_bytes,
                          lifecycle_timeout=limits.lifecycle_timeout, inference_timeout=limits.inference_timeout)
    app = create_app(scheduler, endpoints, token=credentials.token, admin_token=credentials.admin_token,
                     max_body=limits.max_body, max_connections=limits.max_connections,
                     body_timeout=limits.body_timeout, stream_idle=limits.stream_idle,
                     queue_timeout=limits.queue_timeout, max_discovery_bytes=limits.max_discovery_bytes,
                     discovery_timeout=limits.discovery_timeout, admin_timeout=limits.admin_timeout)

    async def control_sessions(app):
        async with AsyncExitStack() as stack:
            for client in clients:
                await stack.enter_async_context(client)
            yield

    # aiohttp unwinds cleanup contexts in reverse: HTTP drain first, then close
    # lifecycle clients. AsyncExitStack also closes partially opened sessions.
    app.cleanup_ctx.insert(0, control_sessions)
    return Runtime(scheduler, app, MappingProxyType(endpoints))
