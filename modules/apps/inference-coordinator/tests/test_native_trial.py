"""Explicit user-approved alternate admission policy; no synthetic counters."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.native_trial import NativeTrialProtocol
from coordinator.protocol import Admission, AdmissionError, ModelLimits


class NativeTrialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.protocol = NativeTrialProtocol({'fixture': ModelLimits(16384, 2048)}, expected_version='0.40.11')

    def admit(self, path='/api/chat', **values):
        return self.protocol.admit('POST', path, json.dumps(dict(model='fixture', **values)).encode())

    async def test_native_text_tools_preserved_and_guard_forced(self):
        request = dict(messages=[dict(role='user', content='hello')],
                       tools=[dict(type='function', function=dict(name='fixture', parameters={'type': 'object'}))])
        admitted = self.admit(**request)
        body = json.loads(admitted.body)
        self.assertFalse(body['truncate'])
        self.assertFalse(body['shift'])
        self.assertEqual(body['messages'], request['messages'])
        self.assertEqual(body['tools'], request['tools'])
        self.assertEqual(body['options'], dict(num_ctx=16384, num_predict=2048))
        await self.protocol.validate_input('/api/chat', admitted)
        # There is deliberately no count and no claimed output reservation proof.
        self.assertIsNone(self.protocol.counter)

    async def test_native_generate_raw_guard(self):
        admitted = self.admit('/api/generate', prompt='hello', raw=True)
        await self.protocol.validate_input('/api/generate', admitted)
        self.assertFalse(json.loads(admitted.body)['shift'])

    async def test_unknown_openai_embedding_and_backend_controls_refused(self):
        for path in ('/v1/chat/completions', '/v1/completions', '/v1/embeddings',
                     '/api/embed', '/api/embeddings', '/api/pull', '/api/show'):
            with self.subTest(path=path), self.assertRaises(AdmissionError):
                self.admit(path, prompt='hello')
        with self.assertRaises(AdmissionError):
            self.protocol.admit('GET', '/v1/models', b'')
        for path in ('/api/tags', '/api/version'):
            self.assertFalse(self.protocol.admit('GET', path, b'').inference)

    async def test_truncation_shift_context_override_and_unknown_fields_refused(self):
        for changes in (dict(truncate=True), dict(shift=True), dict(truncate=0), dict(shift=None),
                        dict(options={'num_ctx': 8192}), dict(images=['abc']), dict(context=[1,2]),
                        dict(runner='other'), dict(debug_render_only=True), dict(keep_alive=-1),
                        dict(stream='yes'), dict(think=[]), dict(format=42), dict(prompt=['hello'])):
            with self.subTest(changes=changes), self.assertRaises(AdmissionError):
                self.admit('/api/generate', **changes)

    async def test_multimodal_messages_and_nontext_input_refused(self):
        for messages in (None, [dict(role='user', content=['text'])],
                         [dict(role='user', content='text', images=['abc'])],
                         [dict(role='bogus', content='text')], [dict(role='assistant', tool_calls={})]):
            with self.subTest(messages=messages), self.assertRaises(AdmissionError):
                self.admit(messages=messages)

    async def test_altered_admission_without_guard_refused(self):
        altered = Admission('["chat","fixture",16384]', True, b'{"model":"fixture"}')
        with self.assertRaises(AdmissionError):
            await self.protocol.validate_input('/api/chat', altered)
        with self.assertRaises(ValueError):
            NativeTrialProtocol({'fixture': ModelLimits(16384, 2048)}, expected_version='other')


if __name__ == '__main__':
    unittest.main()
