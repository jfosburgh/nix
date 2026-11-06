"""Strict versioned configuration data, not a service launcher.

Parsing never reads credentials, touches services, or enables admissions. No
counter, memory or quiescence implementation can be selected by a magic string.
"""
from dataclasses import dataclass
import json
import math
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from .backend_http import loopback_origin


class ConfigError(ValueError):
    """Sanitized schema error; never includes supplied values or credential paths."""


def fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ConfigError('Missing or unknown configuration fields')
    return value


def integer(value, minimum=1):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ConfigError('Invalid integer configuration limit')
    return value


def duration(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 86400:
        raise ConfigError('Invalid finite configuration deadline')
    return value


def text(value):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ConfigError('Invalid configuration identifier')
    return value


def credential(value):
    value = text(value)
    path = PurePosixPath(value)
    if (not path.is_absolute() or value.startswith('//') or not path.name
            or '..' in path.parts or str(path) != value):
        raise ConfigError('Credential reference must be a canonical absolute path')
    return value


@dataclass(frozen=True)
class Limits:
    max_queue: int
    max_queue_bytes: int
    lifecycle_timeout: float
    inference_timeout: float
    max_body: int
    max_connections: int
    body_timeout: float
    stream_idle: float
    queue_timeout: float
    max_discovery_bytes: int
    discovery_timeout: float
    admin_timeout: float
    count_timeout: float


@dataclass(frozen=True)
class MemoryBudget:
    vram_free: int
    ram_available: int


@dataclass(frozen=True)
class Model:
    catalog_name: str
    resident_name: str
    context: int
    output: int
    cold: MemoryBudget
    resident: MemoryBudget


@dataclass(frozen=True)
class BackendConfig:
    id: str
    adapter: str
    upstream: str
    priority: int
    resources: frozenset[str]
    credential_file: str | None
    # Exact profile identity/version is required, not discovered during parsing.
    model: str | None
    context: int | None
    expected_version: str | None
    models: Mapping[str, Model]
    cold: MemoryBudget | None
    resident: MemoryBudget | None
    input_policy: str = 'counted'


@dataclass(frozen=True)
class Config:
    version: int
    profile: str
    token_file: str
    admin_token_file: str | None
    limits: Limits
    backends: tuple[BackendConfig, ...]


def budget(value):
    fields(value, ('vram_free', 'ram_available'))
    return MemoryBudget(integer(value['vram_free']), integer(value['ram_available']))


def parse_config(body: bytes) -> Config:
    """Parse <=256 KiB UTF-8 JSON. No I/O, imports by name, or default budgets."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ConfigError('Duplicate configuration key')
            result[key] = value
        return result

    def invalid_constant(_):
        raise ConfigError('Non-finite configuration number')

    if not isinstance(body, bytes) or len(body) > 256 * 1024:
        raise ConfigError('Configuration byte limit exceeded')
    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid_constant)
        return _parse(value)
    except ConfigError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ConfigError('Invalid coordinator configuration') from None


def _parse(value):
    fields(value, ('version', 'profile', 'token_file', 'limits', 'backends'), ('admin_token_file',))
    if type(value['version']) is not int or value['version'] != 1:
        raise ConfigError('Unsupported configuration version')
    if value['profile'] not in ('desktop', 'headless'):
        raise ConfigError('Explicit desktop/headless profile required')
    token = credential(value['token_file'])
    admin = credential(value['admin_token_file']) if 'admin_token_file' in value else None
    if admin == token:
        raise ConfigError('Separate administration credential reference required')
    keys = tuple(Limits.__dataclass_fields__)
    limits = fields(value['limits'], keys)
    counts = {'max_queue', 'max_queue_bytes', 'max_body', 'max_connections', 'max_discovery_bytes'}
    limits = Limits(**{k: integer(v) if k in counts else duration(v) for k, v in limits.items()})
    if limits.max_body > limits.max_queue_bytes:
        raise ConfigError('Body cap exceeds queue byte cap')
    if not isinstance(value['backends'], list) or len(value['backends']) != 2:
        raise ConfigError('Initial deployment requires exactly two backends')
    backends = []
    for item in value['backends']:
        common = ('id', 'adapter', 'upstream', 'priority', 'resources')
        if not isinstance(item, dict):
            raise ConfigError('Invalid backend registration')
        adapter = item.get('adapter')
        if adapter not in ('strata', 'ollama'):
            raise ConfigError('Unsupported deployment adapter')
        extra = ('model', 'context', 'cold', 'resident') if adapter == 'strata' else ('expected_version', 'models')
        fields(item, common + extra, ('credential_file', 'input_policy') if adapter == 'ollama' else ('credential_file',))
        input_policy = item.get('input_policy', 'counted')
        if input_policy not in ('counted', 'native-reject', 'native-reject-trial'):
            raise ConfigError('Unsupported input admission policy')
        name = text(item['id'])
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name) or name == 'coordinator':
            raise ConfigError('Invalid or reserved backend ID')
        upstream = loopback_origin(text(item['upstream']))
        if item['resources'] != ['narsil-gpu']:
            raise ConfigError('Only exclusive narsil-gpu registration is supported')
        priority = integer(item['priority'], 0)
        secret = credential(item['credential_file']) if 'credential_file' in item else None
        model = context = version = cold = resident = None
        models = {}
        if adapter == 'strata':
            model, context = text(item['model']), integer(item['context'])
            expected = 131072 if value['profile'] == 'desktop' else 262144
            if context != expected:
                raise ConfigError('Strata context does not match preserved mode profile')
            cold, resident = budget(item['cold']), budget(item['resident'])
        else:
            version = text(item['expected_version'])
            if input_policy in ('native-reject', 'native-reject-trial') and version != '0.40.11':
                raise ConfigError('Native rejection trial requires validated backend version')
            if not isinstance(item['models'], dict) or not item['models']:
                raise ConfigError('Explicit Ollama model allowlist required')
            for key, entry in item['models'].items():
                text(key)
                fields(entry, ('catalog_name', 'resident_name', 'context', 'output', 'cold', 'resident'))
                ctx, out = integer(entry['context']), integer(entry['output'])
                if out >= ctx:
                    raise ConfigError('Output reservation must fit context')
                models[key] = Model(text(entry['catalog_name']), text(entry['resident_name']), ctx, out,
                                    budget(entry['cold']), budget(entry['resident']))
            for attribute in ('catalog_name', 'resident_name'):
                if len({getattr(m, attribute) for m in models.values()}) != len(models):
                    raise ConfigError('Ambiguous Ollama model identities')
        backends.append(BackendConfig(name, adapter, upstream, priority, frozenset({'narsil-gpu'}),
                                      secret, model, context, version, MappingProxyType(models), cold, resident,
                                      input_policy))
    if len({b.id for b in backends}) != 2 or {b.adapter for b in backends} != {'strata', 'ollama'}:
        raise ConfigError('Unique initial backend IDs and adapters required')
    # IPv4/IPv6 loopback spellings may still address the same dual-stack socket.
    # Require distinct ports, not merely distinct origin strings.
    if len({urlsplit(b.upstream).port for b in backends}) != 2:
        raise ConfigError('Backend ports must be distinct')
    strata = next(b for b in backends if b.adapter == 'strata')
    ollama = next(b for b in backends if b.adapter == 'ollama')
    if strata.priority >= ollama.priority:
        raise ConfigError('Strict Strata-over-Ollama priority required')
    refs = [token, admin] + [b.credential_file for b in backends]
    refs = [ref for ref in refs if ref is not None]
    if len(refs) != len(set(refs)):
        raise ConfigError('Client, admin and backend credentials must have separate references')
    return Config(1, value['profile'], token, admin, limits, tuple(backends))
