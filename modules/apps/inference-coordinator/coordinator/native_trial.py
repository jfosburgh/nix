"""Native Ollama guard with backend-enforced input rejection.

Not pre-queue token counting. Requires Ollama 0.40.11; forces no input truncation
or context shifting. The Pi bridge subclasses this policy and translates chat
requests to these same native guards; embedding/multimodal remain disabled.
The historical class/module names are retained for legacy offline tests.
"""
import json

from .protocol import Admission, AdmissionError, OllamaProtocol, json_object


class NativeTrialProtocol(OllamaProtocol):
    def __init__(self, models, *, expected_version, catalog_names=None):
        if expected_version != '0.40.11':
            raise ValueError('Native rejection trial requires validated Ollama version')
        super().__init__(models, catalog_names=catalog_names)
        self.inference = {('POST', '/api/chat'): 'chat', ('POST', '/api/generate'): 'generate'}
        self.discovery = {('GET', '/api/tags'), ('GET', '/api/version')}

    def admit(self, method, path, body):
        if (method, path) not in self.inference:
            return super().admit(method, path, body)
        value = json_object(body)
        common = {'model', 'stream', 'format', 'think', 'options', 'truncate', 'shift'}
        allowed = common | ({'messages', 'tools'} if path == '/api/chat' else
                            {'prompt', 'system', 'template', 'raw'})
        if set(value) - allowed:
            raise AdmissionError(422, 'Unsupported native request feature')
        for flag in ('truncate', 'shift'):
            if flag in value and value[flag] is not False:
                raise AdmissionError(400, 'Input truncation and context shifting are disabled')
        for flag in ('stream', 'raw'):
            if flag in value and type(value[flag]) is not bool:
                raise AdmissionError(400, 'Expected boolean request flag')
        if 'think' in value and type(value['think']) is not bool and value['think'] not in ('low', 'medium', 'high'):
            raise AdmissionError(422, 'Unsupported thinking mode')
        if 'format' in value and value['format'] != 'json' and type(value['format']) is not dict:
            raise AdmissionError(422, 'Unsupported output format')
        if path == '/api/chat':
            messages = value.get('messages', [])
            if type(messages) is not list:
                raise AdmissionError(422, 'Expected text messages')
            for message in messages:
                if (type(message) is not dict or set(message) - {
                        'role', 'content', 'thinking', 'tool_calls', 'tool_name', 'tool_call_id'}
                        or message.get('role') not in ('system', 'user', 'assistant', 'tool')
                        or type(message.get('content', '')) is not str
                        or any(type(message[k]) is not str for k in ('thinking', 'tool_name', 'tool_call_id') if k in message)
                        or ('tool_calls' in message and type(message['tool_calls']) is not list)):
                    raise AdmissionError(422, 'Only text messages are supported')
            if 'tools' in value and type(value['tools']) is not list:
                raise AdmissionError(422, 'Expected tools array')
        else:
            if any(type(value.get(k, '')) is not str for k in ('prompt', 'system', 'template')):
                raise AdmissionError(422, 'Expected text generation input')
        value['truncate'] = value['shift'] = False
        admitted = super().admit(method, path, json.dumps(value, separators=(',', ':'), allow_nan=False).encode())
        # Trial memory calibration uses one exact context, not inferred scaling.
        operation, model, context = json.loads(admitted.operation)
        if context != self.models[model].context:
            raise AdmissionError(422, 'Native requests require the configured exact context')
        return admitted

    async def validate_input(self, path: str, admission: Admission):
        # Deliberately a DIFFERENT approved policy, not a fake InputCounter.
        # Backend rejects oversized full templated text while holding the lease.
        if admission.inference:
            if path not in ('/api/chat', '/api/generate'):
                raise AdmissionError(422, 'Unsupported native operation')
            value = json_object(admission.body)
            if value.get('truncate') is not False or value.get('shift') is not False:
                raise AdmissionError(503, 'Native rejection guard missing')
