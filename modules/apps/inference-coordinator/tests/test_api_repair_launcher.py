"""Exercise launcher control flow with temporary fake tools, never systemd/root."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RepairLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='repair-launcher-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = (Path(__file__).resolve().parents[1] / 'scripts/start-api-repair').read_text()
        self.capture = self.root / 'captured'
        tool = self.root / 'tool'
        tool.write_text('#!' + sys.executable + '\n' + '''import json, os, pathlib, sys
if pathlib.Path(sys.argv[0]).name == 'systemd-run':
    pathlib.Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))
    raise SystemExit(0)
if sys.argv[1] == 'is-active':
    raise SystemExit(int(os.environ.get('HELPER_EXIT', '0')))
for argument in sys.argv:
    if argument.startswith('--property='):
        name = argument.split('=', 1)[1]
        print(os.environ.get('PROPERTY_' + name, {'ActiveState':'failed','MainPID':'0','ControlPID':'0','Job':''}[name]))
        raise SystemExit(0)
raise SystemExit(99)
''')
        tool.chmod(0o755)
        for name in ('systemctl', 'systemd-run'):
            (self.root / name).symlink_to(tool)
        script = self.source.replace(
            'systemd=/nix/store/avshcbcrykiffn4vlhmz848ab69wbp9n-systemd-262/bin',
            'systemd=' + str(self.root)).replace('"$EUID"', '"0"')
        self.script = self.root / 'launcher'
        self.script.write_text(script)

    def run_fixture(self, **changes):
        environment = dict(os.environ, CAPTURE=str(self.capture), **changes)
        return subprocess.run(['bash', str(self.script)], env=environment,
                              capture_output=True, text=True, timeout=5)

    def test_notify_sandbox_dependencies_and_scoped_credentials(self):
        result = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.capture.read_text())
        self.assertIn('--property=Type=notify', args)
        self.assertIn('--property=WatchdogSec=15', args)
        self.assertIn('--property=Requires=inference-supervisor.service', args)
        self.assertIn('--property=Wants=strata.service ollama.service', args)
        self.assertNotIn('--property=Requires=ollama.service', args)
        self.assertIn('--property=ProtectSystem=strict', args)
        self.assertIn('--property=Restart=no', args)
        self.assertEqual(args[-2:], ['--credential-unit', 'inference-coordinator-repair.service'])
        self.assertNotIn('resume', args)
        self.assertNotIn('reconcile', args)
        self.assertNotIn('daemon-reload', self.source)

    def test_active_original_refused_without_starting_anything(self):
        result = self.run_fixture(PROPERTY_ActiveState='active')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.capture.exists())

    def test_original_process_or_job_refused(self):
        for key in ('MainPID', 'ControlPID', 'Job'):
            with self.subTest(property=key):
                result = self.run_fixture(**{'PROPERTY_' + key: '123'})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.capture.exists())

    def test_inactive_supervisor_refused(self):
        result = self.run_fixture(HELPER_EXIT='3')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.capture.exists())

    @unittest.skipIf(os.geteuid() == 0, 'nonroot identity guard')
    def test_real_launcher_refuses_nonroot_before_external_commands(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/start-api-repair'
        result = subprocess.run(['bash', str(path)], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Explicit sudo required', result.stderr)
