"""Explicit initial HTTP admission policies; unknown operations fail closed."""
from dataclasses import dataclass
import json
import math

from .budget import BudgetError, BudgetRequest, InputCounter, check_budget


class AdmissionError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


@dataclass(frozen=True)
class Admission:
    operation: str
    inference: bool
    body: bytes
    upstream_path: str | None = None
    response_adapter: str | None = None


@dataclass(frozen=True)
class ModelLimits:
    context: int
    output: int


class Protocol:
    content_type: str | None = None
    buffers_discovery = False

    async def validate_input(self, path: str, admission: Admission) -> None:
        """Opaque protocols may supply their own non-loading admission checks."""

    def discovery_response(self, path: str, body: bytes) -> bytes:
        return body

    def __init__(self, inference: dict[tuple[str, str], str],
                 discovery: set[tuple[str, str]]):
        self.inference, self.discovery = inference, discovery

    def admit(self, method: str, path: str, body: bytes) -> Admission:
        route = method, path
        if route in self.discovery and not body:
            return Admission('discovery', False, body)
        if route not in self.inference:
            raise AdmissionError(404, 'Unsupported operation')
        return Admission(self.inference[route], True, body)


class StrataProtocol(Protocol):
    content_type = 'application/json'

    def __init__(self):
        super().__init__({('POST', '/v1/chat/completions'): 'chat',
                          ('POST', '/v1/completions'): 'completion'},
                         {('GET', '/v1/models')})

    def admit(self, method, path, body):
        admission = super().admit(method, path, body)
        if admission.inference:
            json_object(body)  # Validation only: preserve tools/schema/reasoning bytes.
        return admission


def json_object(body):
    try:
        def invalid_constant(value):
            raise ValueError('Non-finite JSON number')
        def finite_float(value):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError('Non-finite JSON number')
            return number
        value = json.loads(body, parse_constant=invalid_constant, parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError):
        raise AdmissionError(400, 'Expected a JSON object') from None
    if not isinstance(value, dict):
        raise AdmissionError(400, 'Expected a JSON object')
    return value


class OllamaProtocol(Protocol):
    content_type = 'application/json'
    buffers_discovery = True

    def __init__(self, models: dict[str, ModelLimits], *, counter: InputCounter | None = None,
                 count_timeout: float = 5, catalog_names: dict[str, str] | None = None):
        if (not models or any(not isinstance(k, str) or not k for k in models)
                or any(type(v.context) is not int or type(v.output) is not int
                       or not 0 < v.output < v.context for v in models.values())
                or count_timeout <= 0):
            raise ValueError('Explicit positive model context/output budgets required')
        self.models = dict(models)
        self.counter, self.count_timeout = counter, count_timeout
        names = dict(catalog_names) if catalog_names is not None else {key: key for key in models}
        if (set(names) != set(models) or any(not isinstance(v, str) or not v for v in names.values())
                or len(set(names.values())) != len(names)):
            raise ValueError('Explicit unambiguous approved catalog identities required')
        self.catalog_aliases = {value: key for key, value in names.items()}
        super().__init__({('POST', '/api/chat'): 'chat',
                          ('POST', '/api/generate'): 'generate',
                          ('POST', '/api/embed'): 'embed',
                          ('POST', '/api/embeddings'): 'embed',
                          ('POST', '/v1/chat/completions'): 'chat',
                          ('POST', '/v1/completions'): 'completion',
                          ('POST', '/v1/embeddings'): 'embed'},
                         {('GET', '/api/tags'), ('GET', '/api/version'), ('GET', '/v1/models')})

    def admit(self, method, path, body):
        admission = super().admit(method, path, body)
        if not admission.inference:
            return admission
        value = json_object(body)
        model = value.get('model')
        if not isinstance(model, str) or model not in self.models:
            raise AdmissionError(400, 'Model not approved')
        limits = self.models[model]
        if path.startswith('/api/'):
            if 'keep_alive' in value:
                raise AdmissionError(400, 'Client residency controls are disabled')
            options = value.get('options', {})
            if not isinstance(options, dict):
                raise AdmissionError(400, 'Invalid model options')
            options = dict(options)
            if set(options) - {'num_ctx', 'num_predict', 'temperature', 'top_p', 'top_k',
                               'min_p', 'seed', 'stop', 'repeat_penalty'}:
                raise AdmissionError(400, 'Unsupported model options')
            for key, cap in [('num_ctx', limits.context), ('num_predict', limits.output)]:
                number = options.get(key, cap)
                if type(number) is not int or not 0 < number <= cap:
                    raise AdmissionError(400, 'Model context/output limit exceeded')
                options[key] = number
            # Avoid backend idle eviction racing coordinator-owned transitions.
            value['keep_alive'] = -1
            value['options'] = options
        else:
            if (type(value.get('n', 1)) is not int or value.get('n', 1) != 1
                    or type(value.get('best_of', 1)) is not int or value.get('best_of', 1) != 1
                    or 'keep_alive' in value
                    or any(k in value for k in ('options', 'num_ctx', 'num_predict'))):
                raise AdmissionError(400, 'Unsupported generation controls')
            for key in ('max_tokens', 'max_completion_tokens'):
                if key in value and (type(value[key]) is not int or not 0 < value[key] <= limits.output):
                    raise AdmissionError(400, 'Model output limit exceeded')
            if admission.operation != 'embed' and not any(k in value for k in ('max_tokens', 'max_completion_tokens')):
                value['max_tokens'] = limits.output
        # No automatic input truncation for embedding requests.
        if admission.operation == 'embed':
            if value.get('truncate') not in (None, False):
                raise AdmissionError(400, 'Embedding truncation is disabled')
            if path == '/api/embed':
                value['truncate'] = False
        context = value['options']['num_ctx'] if path.startswith('/api/') else limits.context
        return Admission(json.dumps([admission.operation, model, context]), True,
                         json.dumps(value, separators=(',', ':'), allow_nan=False).encode())

    async def validate_input(self, path: str, admission: Admission) -> None:
        if not admission.inference:
            return
        operation, model, context = json.loads(admission.operation)
        value = json_object(admission.body)
        if operation == 'chat':
            if not isinstance(value.get('messages', []), list):
                raise AdmissionError(400, 'Expected a messages array')
            sequences = 1
        else:
            key = 'input' if path in ('/api/embed', '/v1/embeddings') else 'prompt'
            inputs = value.get(key, [] if path == '/api/embed' else '')
            if isinstance(inputs, str):
                sequences = 1
            elif isinstance(inputs, list) and all(isinstance(item, str) for item in inputs):
                sequences = len(inputs)
            else:
                raise AdmissionError(422, 'Only text inputs can currently be accounted for')
            if operation != 'embed' and not sequences:
                raise AdmissionError(400, 'Expected at least one input')
        if operation == 'embed':
            output = 0
        elif path.startswith('/api/'):
            output = value['options']['num_predict']
        else:
            output = max(value.get(key, 0) for key in ('max_tokens', 'max_completion_tokens'))
        try:
            await check_budget(self.counter, BudgetRequest(model, path, admission.body,
                                                           context, output, sequences),
                               timeout=self.count_timeout)
        except BudgetError as exc:
            raise AdmissionError(exc.status, exc.message) from None

    def discovery_response(self, path: str, body: bytes) -> bytes:
        try:
            value = json_object(body)
            if path == '/api/version':
                if not isinstance(value.get('version'), str) or not value['version']:
                    raise ValueError('Invalid version')
                result = {'version': value['version']}
            elif path == '/api/tags':
                result = {'models': self._catalog(value.get('models'), native=True)}
            elif path == '/v1/models':
                result = {'object': 'list', 'data': self._catalog(value.get('data'), native=False)}
            else:
                raise ValueError('Unsupported discovery')
            return json.dumps(result, separators=(',', ':'), allow_nan=False).encode()
        except (AdmissionError, ValueError, TypeError, RecursionError):
            raise AdmissionError(502, 'Invalid upstream discovery response') from None

    def _catalog(self, entries, *, native):
        if not isinstance(entries, list):
            raise ValueError('Expected a model list')
        selected, seen = [], set()
        for entry in entries:
            key = 'name' if native else 'id'
            if not isinstance(entry, dict) or not isinstance(entry.get(key), str):
                raise ValueError('Invalid catalog entry')
            if native and entry.get('model') != entry[key]:
                raise ValueError('Ambiguous catalog identity')
            name = entry[key]
            alias = self.catalog_aliases.get(name)
            if alias is None:
                continue
            if alias in seen:
                raise ValueError('Duplicate approved model')
            seen.add(alias)
            # Only approved entries survive; preserve their protocol metadata,
            # while publishing exactly the model ID accepted by admission.
            item = dict(entry)
            item[key] = alias
            if native:
                item['model'] = alias
            selected.append(item)
        return selected
