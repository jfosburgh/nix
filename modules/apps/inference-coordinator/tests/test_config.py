"""Schema-only tests. Numbers are synthetic, not calibrated deployment budgets."""
import copy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.config import ConfigError, Limits, parse_config


def fixture():
    budget = {'vram_free': 1234, 'ram_available': 5678}
    return {
        'version': 1, 'profile': 'desktop', 'token_file': '/run/credentials/client',
        'admin_token_file': '/run/credentials/admin',
        'limits': {key: 64 if key.startswith('max_') else 5 for key in Limits.__dataclass_fields__},
        'backends': [
            {'id': 'strata', 'adapter': 'strata', 'upstream': 'http://127.0.0.1:18080',
             'priority': 0, 'resources': ['narsil-gpu'], 'model': 'preserved-strata-profile',
             'context': 131072, 'cold': dict(budget), 'resident': dict(budget)},
            {'id': 'ollama', 'adapter': 'ollama', 'upstream': 'http://127.0.0.1:21434',
             'priority': 1, 'resources': ['narsil-gpu'], 'expected_version': '0.40.11',
             'models': {'small': {'catalog_name': 'small:latest', 'resident_name': 'small:latest',
                                  'context': 8192, 'output': 1024,
                                  'cold': dict(budget), 'resident': dict(budget)}}},
        ],
    }


def parse(value):
    return parse_config(json.dumps(value).encode())


class ConfigTests(unittest.TestCase):
    def test_valid_immutable_configuration_has_no_io(self):
        with patch('builtins.open', side_effect=AssertionError('Unexpected I/O')):
            config = parse(fixture())
        self.assertEqual(config.backends[0].priority, 0)
        self.assertEqual(config.backends[1].models['small'].context, 8192)
        self.assertEqual(config.backends[0].resources, frozenset({'narsil-gpu'}))
        with self.assertRaises(FrozenInstanceError):
            config.profile = 'headless'
        with self.assertRaises(TypeError):
            config.backends[1].models['other'] = config.backends[1].models['small']

    def test_explicit_native_trial_policy_is_version_pinned(self):
        value = fixture()
        value['backends'][1]['input_policy'] = 'native-reject-trial'
        self.assertEqual(parse(value).backends[1].input_policy, 'native-reject-trial')
        value['backends'][1]['expected_version'] = 'other'
        with self.assertRaises(ConfigError):
            parse(value)
        value = fixture()
        value['backends'][0]['input_policy'] = 'native-reject-trial'
        with self.assertRaises(ConfigError):
            parse(value)
        for policy in ('permissive', None, [], True):
            value = fixture()
            value['backends'][1]['input_policy'] = policy
            with self.assertRaises(ConfigError):
                parse(value)

    def test_headless_and_disabled_admin(self):
        value = fixture()
        value['profile'] = 'headless'
        value['backends'][0]['context'] = 262144
        del value['admin_token_file']
        self.assertIsNone(parse(value).admin_token_file)

    def test_explicit_backend_ids_not_scheduler_name_branches(self):
        value = fixture()
        value['backends'][0]['id'] = 'coder'
        value['backends'][1]['id'] = 'applications'
        self.assertEqual(parse(value).backends[0].id, 'coder')

    def test_unknown_and_missing_fields_at_every_level(self):
        for location in ((), ('limits',), ('backends', 0), ('backends', 1),
                         ('backends', 1, 'models', 'small'), ('backends', 0, 'cold')):
            for mutation in ('unknown', 'missing'):
                with self.subTest(location=location, mutation=mutation):
                    value = fixture()
                    target = value
                    for key in location:
                        target = target[key]
                    if mutation == 'unknown':
                        target['unexpected'] = 'sensitive-value'
                    else:
                        del target[next(iter(target))]
                    with self.assertRaises(ConfigError) as error:
                        parse(value)
                    self.assertNotIn('sensitive-value', str(error.exception))

    def test_rejects_invalid_limits(self):
        for key in Limits.__dataclass_fields__:
            invalid = (True, 0, -1, '10', None, float('inf'), float('nan'))
            if key.startswith('max_'):
                invalid += (1.5, 2**64)
            else:
                invalid += (86401,)
            for number in invalid:
                with self.subTest(key=key, number=number):
                    value = fixture()
                    value['limits'][key] = number
                    with self.assertRaises(ConfigError):
                        parse(value)
        value = fixture()
        value['limits']['max_body'] = 65
        with self.assertRaises(ConfigError):
            parse(value)

    def test_backend_safety_invariants(self):
        mutations = [
            lambda v: v.update(version=True),
            lambda v: v.update(version=2),
            lambda v: v.update(profile='auto'),
            lambda v: v['backends'].pop(),
            lambda v: v['backends'][0].update(id='coordinator'),
            lambda v: v['backends'][0].update(id='../strata'),
            lambda v: v['backends'][1].update(id='strata'),
            lambda v: v['backends'][0].update(adapter='plugin'),
            lambda v: v['backends'][0].update(priority=True),
            lambda v: v['backends'][0].update(priority=1),
            lambda v: v['backends'][0].update(priority=2),
            lambda v: v['backends'][0].update(resources=['cpu']),
            lambda v: v['backends'][0].update(resources=['narsil-gpu', 'narsil-gpu']),
            lambda v: v['backends'][0].update(upstream='http://192.168.1.2:8080'),
            lambda v: v['backends'][0].update(upstream='http://localhost:8080'),
            lambda v: v['backends'][0].update(upstream='http://user:secret@127.0.0.1:8080'),
            lambda v: v['backends'][0].update(upstream='http://127.0.0.1:8080/path'),
            lambda v: v['backends'][0].update(upstream='http://[::1]:21434'),
            lambda v: v['backends'][0].update(context=262144),
            lambda v: v['backends'][0]['cold'].update(vram_free=0),
            lambda v: v['backends'][1].update(expected_version=''),
            lambda v: v['backends'][1].update(models={}),
            lambda v: v['backends'][1]['models']['small'].update(output=8192),
            lambda v: v['backends'][1]['models']['small'].update(context=True),
            lambda v: v['backends'][1]['models'].update(other=copy.deepcopy(v['backends'][1]['models']['small'])),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = fixture()
                mutate(value)
                with self.assertRaises(ConfigError):
                    parse(value)

    def test_credentials_are_references_not_inline_values_or_shared_scopes(self):
        for path in ('secret-token', '/', '/run/../secret', '/run//secret', '/run/./secret',
                     '/run/secret\n', '/run/\ud800'):
            value = fixture()
            value['token_file'] = path
            with self.assertRaises(ConfigError):
                parse(value)
        value = fixture()
        value['admin_token_file'] = value['token_file']
        with self.assertRaises(ConfigError):
            parse(value)
        value = fixture()
        value['backends'][0]['credential_file'] = value['token_file']
        with self.assertRaises(ConfigError):
            parse(value)
        value = fixture()
        value['backends'][0]['credential_file'] = '/run/credentials/backend'
        self.assertEqual(parse(value).backends[0].credential_file, '/run/credentials/backend')

    def test_malformed_duplicate_oversize_and_nonfinite_json(self):
        for body in (b'{"version":1,"version":1}', b'{"nested":{"x":1,"x":2}}',
                     b'[]', b'null', b'{}', b'\xff', b'{' * 2000,
                     b' ' * (256 * 1024 + 1), b'{"version":NaN}', b'{"version":1e999}'):
            with self.subTest(body=body[:30]):
                with self.assertRaises(ConfigError):
                    parse_config(body)

    def test_configuration_does_not_retain_mutable_input(self):
        value = fixture()
        config = parse(value)
        value['backends'][1]['models']['small']['context'] = 1
        self.assertEqual(config.backends[1].models['small'].context, 8192)
