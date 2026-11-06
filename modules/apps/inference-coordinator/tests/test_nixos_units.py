"""Opt-in checks against the built personal-use NixOS service, without activation."""
import configparser
import json
import os
from pathlib import Path
import shlex
import unittest
from unittest.mock import AsyncMock

from coordinator.config import parse_config
from coordinator.credentials import Credentials
from coordinator.runtime import assemble
from coordinator.native_trial import NativeTrialProtocol


@unittest.skipUnless(os.environ.get('NARSIL_TRIAL_SYSTEM'), 'requires built personal-use closure')
class BuiltUnitDependencyTests(unittest.TestCase):
    def unit(self, name):
        path = Path(os.environ['NARSIL_TRIAL_SYSTEM']) / 'etc/systemd/system' / name
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(path.read_text())
        return parser

    def test_default_enablement_and_nontrial_marker(self):
        root = Path(os.environ['NARSIL_TRIAL_SYSTEM'])
        self.assertTrue((root/'etc/systemd/system/multi-user.target.wants/inference-coordinator.service').exists())
        self.assertTrue((root/'etc/narsil-inference-coordinator').exists())
        self.assertFalse((root/'etc/narsil-inference-trial').exists())

    def test_backend_stop_cannot_stop_router(self):
        unit = self.unit('inference-coordinator.service')['Unit']
        for relation in ('Requires', 'BindsTo', 'PartOf', 'Requisite'):
            self.assertFalse({'ollama.service','strata.service'}.intersection(unit.get(relation,'').split()))
        self.assertTrue({'ollama.service','strata.service'}.issubset(unit['Wants'].split()))
        self.assertTrue({'ollama.service','strata.service'}.issubset(unit['After'].split()))

    def test_no_supervisor_pins_config_condition_or_watchdog(self):
        root = Path(os.environ['NARSIL_TRIAL_SYSTEM'])
        self.assertFalse((root/'etc/systemd/system/inference-supervisor.service').exists())
        unit = self.unit('inference-coordinator.service')
        self.assertNotIn('ConditionPathExists', unit['Unit'])
        self.assertNotIn('inference-supervisor.service', unit['Unit'].get('Requires',''))
        self.assertNotIn('WatchdogSec', unit['Service'])
        self.assertEqual(unit['Service']['Type'], 'exec')
        self.assertEqual(unit['Service']['Restart'], 'on-failure')
        self.assertEqual(unit['Service']['User'], 'inference-coordinator')
        self.assertIn('inference-credentials.service', unit['Unit']['Requires'])

    def test_immutable_direct_config_has_admission_budgets(self):
        command = shlex.split(self.unit('inference-coordinator.service')['Service']['ExecStart'])
        self.assertIn('serve', command)
        value = json.loads(Path(command[command.index('--config')+1]).read_text())
        self.assertEqual(value['profile'], 'desktop')
        self.assertEqual(value['backends'][0]['context'],131072)
        self.assertEqual(value['backends'][0]['resident']['ram_available'],2*1024**3)
        self.assertEqual(value['backends'][1]['models']['gemma4:12b']['context'],65536)
        self.assertEqual(set(value['backends'][1]['models']),
                         {'gemma4:12b','ornith-1.5:9b','nemotron-3.5-bolt:e4b'})
        self.assertEqual(value['backends'][1]['models']['ornith-1.5:9b']['context'],262144)
        self.assertEqual(value['backends'][1]['models']['nemotron-3.5-bolt:e4b']['context'],65536)
        self.assertEqual(value['limits']['max_body'],4*1024**2)
        self.assertEqual(value['limits']['max_queue_bytes'],16*1024**2)
        self.assertGreaterEqual(value['limits']['stream_idle'],600)
        self.assertEqual(value['backends'][1]['input_policy'],'native-reject')
        runtime = assemble(parse_config(json.dumps(value).encode()),
            Credentials('c'*32,'a'*32,{}), memory=AsyncMock(), counters={},
            quiescence={'ollama':AsyncMock()})
        self.assertIsInstance(runtime.endpoints['ollama'].protocol,NativeTrialProtocol)
        self.assertFalse(runtime.scheduler.backends['ollama'].lifecycle.context_shift)
        for backend in value['backends']:
            profiles = [backend] if backend['adapter']=='strata' else backend['models'].values()
            for profile in profiles:
                for mode in ('cold','resident'):
                    self.assertGreater(profile[mode]['ram_available'],0)
                    self.assertGreater(profile[mode]['vram_free'],0)

    def test_gateway_and_pi_registry_match_configured_profiles(self):
        root=Path(os.environ['NARSIL_TRIAL_SYSTEM'])
        unit=self.unit('inference-coordinator.service')['Service']
        self.assertIn('100.64.0.1',unit['IPAddressAllow'])
        command=shlex.split(unit['ExecStart'])
        configuration=json.loads(Path(command[command.index('--config')+1]).read_text())
        profiles=configuration['backends'][1]['models']
        registry=json.loads((Path(__file__).resolve().parents[2]/'agents/models.json').read_text())['providers']
        self.assertEqual(registry['ollama']['baseUrl'],'https://strata.threegoldenhairs.me/ollama/v1')
        self.assertEqual(set(profiles),{m['id'] for m in registry['ollama']['models']})
        for model in registry['ollama']['models']:
            self.assertEqual(model['contextWindow'],profiles[model['id']]['context'])
            self.assertEqual(model['maxTokens'],profiles[model['id']]['output'])
        for name in ('strata','strata-server'):
            self.assertEqual(registry[name]['models'][0]['contextWindow'],configuration['backends'][0]['context'])

    @unittest.skipUnless(os.environ.get('NARSIL_BLADE_SYSTEM'),'requires built Blade closure')
    def test_blade_preserves_gateway_path_and_network_boundary(self):
        root=Path(os.environ['NARSIL_BLADE_SYSTEM'])
        text=(root/'etc/nginx/nginx.conf').read_text()
        start=text.rindex('server_name strata.threegoldenhairs.me')
        section=text[start:]
        end=section.find('server_name ',len('server_name '))
        if end>=0:
            section=section[:end]
        for expected in ('http://100.64.0.3:8081','allow 192.168.1.0/24','allow 100.64.0.0/10',
                         'deny 192.168.1.1','deny all','proxy_next_upstream off','proxy_buffering off',
                         'client_max_body_size 4m','proxy_read_timeout 3600s'):
            self.assertIn(expected,section)

    def test_narrow_polkit_rule_deployed(self):
        root = Path(os.environ['NARSIL_TRIAL_SYSTEM'])/'etc/polkit-1/rules.d'
        text = '\n'.join(p.read_text() for p in root.glob('*.rules'))
        self.assertIn('subject.user === "inference-coordinator"',text)
        self.assertIn('action.lookup("verb") === "restart"',text)
        self.assertIn('action.lookup("unit") === "ollama.service"',text)
        self.assertIn('action.lookup("unit") === "strata.service"',text)
