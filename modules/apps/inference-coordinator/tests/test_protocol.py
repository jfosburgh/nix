"""Admission contract tests without networking or third-party dependencies."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.budget import InputUsage
from coordinator.protocol import AdmissionError, ModelLimits, OllamaProtocol, StrataProtocol


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = OllamaProtocol({'small': ModelLimits(8192, 1024)})

    def admit(self, path, value):
        result = self.protocol.admit('POST', path, json.dumps(value).encode())
        return result, json.loads(result.body)

    def test_native_defaults_and_explicit_smaller_limits(self):
        admission, body = self.admit('/api/chat', {'model': 'small', 'messages': [],
                                                 'options': {'num_ctx': 4096, 'num_predict': 128}})
        self.assertTrue(admission.inference)
        self.assertEqual(json.loads(admission.operation), ['chat', 'small', 4096])
        self.assertEqual(body['options'], {'num_ctx': 4096, 'num_predict': 128})
        self.assertEqual(body['keep_alive'], -1)

    def test_openai_schema_and_tool_metadata_preserved(self):
        value = {'model': 'small', 'tools': [{'type': 'function', 'function': {'name': 'f'}}],
                 'response_format': {'type': 'json_schema', 'json_schema': {'name': 'r'}},
                 'messages': [{'role': 'tool', 'tool_call_id': 'id', 'content': 'opaque'}]}
        _, body = self.admit('/v1/chat/completions', value)
        self.assertEqual(body, dict(value, max_tokens=1024))

    def test_openai_output_limits(self):
        for value in [0, -1, True, 1025, '128']:
            for key in ['max_tokens', 'max_completion_tokens']:
                with self.assertRaises(AdmissionError):
                    self.admit('/v1/chat/completions', {'model': 'small', key: value})
        _, body = self.admit('/v1/chat/completions', {'model': 'small', 'max_completion_tokens': 64})
        self.assertEqual(body['max_completion_tokens'], 64)
        self.assertNotIn('max_tokens', body)

    def test_embeddings_queued_and_truncation_disabled(self):
        result, body = self.admit('/api/embed', {'model': 'small', 'input': ['x']})
        self.assertTrue(result.inference)
        self.assertFalse(body['truncate'])
        with self.assertRaises(AdmissionError):
            self.admit('/api/embed', {'model': 'small', 'truncate': True})
        result, body = self.admit('/v1/embeddings', {'model': 'small', 'input': ['x']})
        self.assertTrue(result.inference)
        self.assertNotIn('max_tokens', body)

    def test_warmup_is_not_discovery(self):
        result, _ = self.admit('/api/generate', {'model': 'small'})
        self.assertTrue(result.inference)

    def test_strata_unknown_routes_and_controls_refused(self):
        protocol = StrataProtocol()
        for path in ['/load', '/unload', '/v1/responses', '/v1/messages']:
            with self.assertRaises(AdmissionError):
                protocol.admit('POST', path, b'{}')
        self.assertFalse(protocol.admit('GET', '/v1/models', b'').inference)

    def test_invalid_model_configuration(self):
        for models in [{}, {'x': ModelLimits(0, 1)}, {'x': ModelLimits(1024, 1024)}]:
            with self.assertRaises(ValueError):
                OllamaProtocol(models)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.protocol = OllamaProtocol({'small': ModelLimits(8192, 1024)},
                                       catalog_names={'small': 'small:latest'})

    def catalog(self, path, value):
        return json.loads(self.protocol.discovery_response(path, json.dumps(value).encode()))

    def test_missing_approved_models_not_synthesized_as_installed(self):
        self.assertEqual(self.catalog('/api/tags', {'models': []}), {'models': []})
        self.assertEqual(self.catalog('/v1/models', {'data': []}), {'object': 'list', 'data': []})

    def test_approved_metadata_preserved_unknown_root_discarded(self):
        value = {'name': 'small:latest', 'model': 'small:latest', 'digest': 'sha256',
                 'details': {'quantization_level': 'Q4_K_M'}}
        result = self.catalog('/api/tags', {'models': [value], 'internal': 'private'})
        self.assertEqual(result, {'models': [dict(value, name='small', model='small')]})
        self.assertEqual(self.catalog('/api/version', {'version': '0.40.11', 'internal': 'private'}),
                         {'version': '0.40.11'})

    def test_no_implicit_latest_or_basename_aliases(self):
        result = self.catalog('/api/tags', {'models': [{'name': 'small', 'model': 'small'},
                                                       {'name': 'org/small:latest', 'model': 'org/small:latest'}]})
        self.assertEqual(result, {'models': []})

    def test_invalid_alias_configuration_rejected(self):
        models = {'a': ModelLimits(8192, 1024), 'b': ModelLimits(8192, 1024)}
        for names in [{'a': 'a:latest'}, {'a': 'same', 'b': 'same'}, {'a': '', 'b': 'b'}]:
            with self.assertRaises(ValueError):
                OllamaProtocol(models, catalog_names=names)

    def test_noninteger_context_and_output_configuration_rejected(self):
        for limits in [ModelLimits(True, 1), ModelLimits(8192, True), ModelLimits(8192.5, 1024)]:
            with self.assertRaises(ValueError):
                OllamaProtocol({'small': limits})


class InputProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        requests = self.requests
        class Counter:
            async def count(self, request):
                requests.append(request)
                return InputUsage(request.model, request.context, (1,) * request.sequences)
        self.protocol = OllamaProtocol({'small': ModelLimits(8192, 1024)}, counter=Counter())

    async def validate(self, path, value):
        admission = self.protocol.admit('POST', path, json.dumps(value).encode())
        await self.protocol.validate_input(path, admission)
        return admission

    async def test_normalized_full_envelope_given_to_counter(self):
        value = {'model': 'small', 'system': 'hidden system', 'template': '{{custom}}',
                 'prompt': 'user', 'context': [1, 2], 'options': {'num_ctx': 4096, 'num_predict': 128}}
        await self.validate('/api/generate', value)
        request = self.requests[0]
        self.assertEqual(request.context, 4096)
        self.assertEqual(request.output, 128)
        for key in ['system', 'template', 'prompt', 'context']:
            self.assertEqual(json.loads(request.body)[key], value[key])

    async def test_tools_schema_and_tool_results_must_be_counted(self):
        value = {'model': 'small', 'messages': [{'role': 'tool', 'content': 'tool result'}],
                 'tools': [{'function': {'name': 'f'}}], 'format': {'type': 'object'}}
        await self.validate('/api/chat', value)
        counted = json.loads(self.requests[0].body)
        for key in ['messages', 'tools', 'format']:
            self.assertEqual(counted[key], value[key])

    async def test_legacy_embedding_and_completion_batch_shapes(self):
        await self.validate('/api/embeddings', {'model': 'small', 'prompt': 'x'})
        self.assertEqual(self.requests[-1].output, 0)
        await self.validate('/v1/completions', {'model': 'small', 'prompt': ['a', 'b'], 'max_tokens': 128})
        self.assertEqual(self.requests[-1].sequences, 2)
        self.assertEqual(self.requests[-1].output, 128)

    async def test_token_arrays_and_invalid_input_shapes_refused(self):
        for path, field, value in [('/v1/embeddings', 'input', [1, 2]),
                                   ('/api/embed', 'input', [['a']]),
                                   ('/api/chat', 'messages', 'not messages'),
                                   ('/v1/completions', 'prompt', [])]:
            with self.assertRaises(AdmissionError):
                await self.validate(path, {'model': 'small', field: value})
        self.assertEqual(self.requests, [])

    async def test_no_counter_required_for_discovery(self):
        protocol = OllamaProtocol({'small': ModelLimits(8192, 1024)})
        admission = protocol.admit('GET', '/api/tags', b'')
        await protocol.validate_input('/api/tags', admission)

    async def test_openai_resource_and_multiplicity_overrides_rejected(self):
        for value in [{'n': True}, {'n': 2}, {'best_of': 2}, {'options': {'num_ctx': 999999}},
                      {'num_ctx': 999999}, {'keep_alive': -1}]:
            with self.assertRaises(AdmissionError):
                await self.validate('/v1/completions', dict(value, model='small', prompt='x'))


if __name__ == '__main__':
    unittest.main()
