"""Safe unit/integration tests: all session/service changes are mocked.
Run with Python 3.10+; no root, GPU, model load or live activation required.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'

STUB = r'''
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['TEST_LOG'], 'a') as f:
    f.write(json.dumps([name, args]) + '\n')
mode = Path(os.environ['TEST_MODE']).read_text().strip()
if name == 'systemctl':
    if args[0] == 'show':
        print('activating' if os.environ.get('BUSY') else 'inactive')
    elif args[:2] == ['cat', 'strata.service']:
        sys.exit(0 if mode == 'headless' else 1)
    elif args[:2] == ['stop', 'strata.service'] and os.environ.get('FAIL_STOP'):
        sys.exit(1)
elif name == 'loginctl':
    sessions = {'gui1': ('wayland', '1000', 'james'), 'gui2': ('x11', '1001', 'work'), 'ssh3': ('tty', '1000', 'james')}
    if args[0] == 'list-sessions':
        print('gui1 1000 james\ngui2 1001 work\nssh3 1000 james')
    elif args[0] == 'show-session':
        if args[1] not in sessions:
            sys.exit(1)
        if '--value' in args:
            prop = next(a.split('=', 1)[1] for a in args if a.startswith('--property='))
            print(sessions[args[1]][{'Type': 0, 'User': 1, 'Name': 2}[prop]])
elif name == 'stop-manual-strata':
    sys.exit(1 if os.environ.get('FAIL_CLEANUP') else 0)
elif name == 'curl':
    print(json.dumps({'loaded': not bool(os.environ.get('FAIL_HEALTH')),
                     'max_context': int(os.environ.get('HEALTH_CONTEXT', '262144'))}))
elif name == 'jq':
    import re
    obj = json.load(sys.stdin)
    expected = re.search(r'\.max_context == (\d+)', ' '.join(args))
    sys.exit(0 if expected and obj.get('loaded') and obj.get('max_context') == int(expected[1]) else 1)
'''


class LiveModes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        self.base, self.child = self.p / 'desktop', self.p / 'server'
        self.current, self.marker = self.p / 'current', self.p / 'mode'
        self.gc, self.profiles = self.p / 'gc-root', self.p / 'profiles'
        self.state, self.log = self.p / 'state', self.p / 'calls.jsonl'
        self.profiles.mkdir()
        self.current.symlink_to(self.base)
        self.marker.write_text('desktop\n')
        self.env = dict(os.environ, TEST_LOG=str(self.log), TEST_MODE=str(self.marker), TEST_CURRENT=str(self.current))
        self.bin = self.p / 'bin'
        self.bin.mkdir()
        for name in ('systemctl', 'loginctl', 'runuser', 'stop-manual-strata', 'curl', 'jq', 'sleep'):
            path = self.bin / name
            path.write_text(f'#!{sys.executable}\n' + STUB)
            path.chmod(0o755)
        self.env['PATH'] = str(self.bin) + ':' + os.environ['PATH']
        for mode, root in [('desktop', self.base), ('headless', self.child)]:
            (root / 'bin').mkdir(parents=True)
            script = root / 'bin/switch-to-configuration'
            script.write_text(f'''#!{sys.executable}
import json, os, sys
from pathlib import Path
with open(os.environ['TEST_LOG'], 'a') as f:
    f.write(json.dumps(['activate', ['{mode}', *sys.argv[1:]]])+'\\n')
if '{mode}' == 'headless' and os.environ.get('FAIL_ACTIVATE'):
    sys.exit(1)
p=Path(os.environ['TEST_CURRENT'])
p.unlink()
p.symlink_to('{root}')
Path(os.environ['TEST_MODE']).write_text('{mode}\\n')
''')
            script.chmod(0o755)
        (self.base / 'specialisation').mkdir()
        (self.base / 'specialisation/strata-server').symlink_to(self.child)
        (self.profiles / 'system').symlink_to(self.base)
        self.common = (SCRIPTS / 'mode-common.sh').read_text()
        for old, new in [('/nix/var/nix/gcroots/narsil-mode-desktop', self.gc),
                         ('/nix/var/nix/profiles', self.profiles),
                         ('/run/current-system', self.current), ('/etc/narsil-mode', self.marker),
                         ('/home/james/dev', self.p / 'dev')]:
            self.common = self.common.replace(old, str(new))
        # Empty readable fixtures are sufficient for the installation preflight.
        import re
        for name in re.findall(r'/home/james/dev/[^\s\\;]+', (SCRIPTS / 'mode-common.sh').read_text()):
            path = Path(name.replace('/home/james/dev', str(self.p / 'dev')))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.sockets = []
        for uid in (1000, 1001):
            path = self.p / f'users/{uid}/bus'
            path.parent.mkdir(parents=True)
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(path))
            self.sockets.append(sock)

    def tearDown(self):
        for sock in self.sockets:
            sock.close()
        self.tmp.cleanup()

    def run_script(self, script, *args, **env):
        source = (SCRIPTS / script).read_text()
        if script == 'mode-command.sh':
            # Unit tests cannot elevate; strip only the sudo handoff in this
            # temporary test copy. Production always retains the root check.
            block = 'if (( EUID != 0 )); then\n  exec /run/wrappers/bin/sudo -- "$0" "$@"\nfi\n'
            self.assertIn(block, source)
            source = source.replace(block, '')
        source = source.replace('/etc/narsil-inference-coordinator', str(self.p / 'inference-coordinator'))
        source = source.replace('/run/narsil-mode', str(self.state))
        source = source.replace('/run/user/', str(self.p / 'users') + '/')
        source = source.replace('attempt<150', 'attempt<2')
        test_script = self.p / script
        test_script.write_text('set -euo pipefail\n' + self.common + '\n' + source)
        return subprocess.run([shutil.which('bash'), str(test_script), *args],
                              env=dict(self.env, **env), text=True, capture_output=True, timeout=15)

    def test_inference_coordinator_refuses_mode_switch_before_any_service_or_session_change(self):
        (self.p / 'inference-coordinator').write_text('coordinated inference\n')
        result = self.run_script('mode-worker.sh', 'headless')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires coordinated inference lifecycle support', result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.state.exists())
        self.assertEqual(self.marker.read_text(), 'desktop\n')

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    @unittest.skipIf(os.geteuid() == 0, 'requires unprivileged EUID to exercise sudo handoff')
    def test_frontend_elevation_uses_nixos_wrapper(self):
        source = (SCRIPTS / 'mode-command.sh').read_text()
        self.assertIn('exec /run/wrappers/bin/sudo -- "$0" "$@"', source)
        wrapper = self.p / 'sudo-wrapper'
        wrapper.write_text('#!' + shutil.which('bash') + '\n'
                           'printf "%s\\n" "$@" > "$TEST_LOG"\nexit 37\n')
        wrapper.chmod(0o755)
        script = self.p / 'elevation-test.sh'
        script.write_text('set -euo pipefail\n' + source.replace('/run/wrappers/bin/sudo', str(wrapper)))
        result = subprocess.run([shutil.which('bash'), str(script), 'headless', '--yes'],
                                env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ['--', str(script), 'headless', '--yes'])

    def test_headless_orders_cleanup_and_preserves_ssh(self):
        result = self.run_script('mode-worker.sh', 'headless')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertLess(calls.index(['stop-manual-strata', []]), calls.index(['activate', ['headless', 'test']]))
        terminated = [a[1] for cmd, a in calls if cmd == 'loginctl' and a[0] == 'terminate-session']
        self.assertEqual(set(terminated), {'gui1', 'gui2'})
        self.assertEqual(len([1 for cmd, a in calls if cmd == 'runuser']), 2)
        self.assertIn(['systemctl', ['isolate', 'multi-user.target']], calls)
        self.assertEqual(self.gc.resolve(), self.base)
        self.assertEqual(self.marker.read_text().strip(), 'headless')

    def test_desktop_releases_gpu_before_activation(self):
        self.current.unlink(); self.current.symlink_to(self.child)
        self.marker.write_text('headless\n')
        result = self.run_script('mode-worker.sh', 'desktop')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertLess(calls.index(['systemctl', ['stop', 'strata.service']]), calls.index(['activate', ['desktop', 'test']]))
        self.assertLess(calls.index(['stop-manual-strata', []]), calls.index(['activate', ['desktop', 'test']]))
        self.assertIn(['systemctl', ['isolate', 'graphical.target']], calls)
        self.assertFalse(self.gc.exists())

    def test_headless_health_failure_restores_desktop(self):
        result = self.run_script('mode-worker.sh', 'headless', FAIL_HEALTH='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Attempting to restore', result.stderr)
        self.assertEqual(self.marker.read_text().strip(), 'desktop')
        self.assertIn(['activate', ['desktop', 'test']], self.calls())

    def test_wrong_context_health_restores_desktop(self):
        result = self.run_script('mode-worker.sh', 'headless', HEALTH_CONTEXT='131072')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Attempting to restore', result.stderr)
        self.assertEqual(self.marker.read_text().strip(), 'desktop')
        self.assertIn(['activate', ['desktop', 'test']], self.calls())

    def test_activation_failure_restores_desktop(self):
        result = self.run_script('mode-worker.sh', 'headless', FAIL_ACTIVATE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(['activate', ['desktop', 'test']], self.calls())

    def test_failed_manual_cleanup_does_not_log_out(self):
        result = self.run_script('mode-worker.sh', 'headless', FAIL_CLEANUP='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(cmd in ('loginctl', 'activate') for cmd, _ in self.calls()))

    def test_failed_managed_stop_does_not_start_desktop(self):
        self.current.unlink(); self.current.symlink_to(self.child)
        self.marker.write_text('headless\n')
        result = self.run_script('mode-worker.sh', 'desktop', FAIL_STOP='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(cmd == 'activate' for cmd, _ in self.calls()))

    def test_missing_model_fails_before_cleanup(self):
        shutil.rmtree(self.p / 'dev')
        result = self.run_script('mode-worker.sh', 'headless')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing Strata', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_worker_lock_prevents_concurrent_switch(self):
        self.state.mkdir()
        with (self.state / 'switch.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_script('mode-worker.sh', 'headless')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Another mode switch', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_frontend_confirmation_and_detached_job(self):
        result = self.run_script('mode-command.sh', 'headless')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Interactive confirmation required', result.stderr)
        self.assertFalse(any(a[:1] == ['start'] for cmd, a in self.calls()))
        result = self.run_script('mode-command.sh', 'headless', '--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(['systemctl', ['start', '--no-block', 'narsil-mode-switch@headless.service']], self.calls())
        self.assertFalse(any(cmd == 'activate' for cmd, _ in self.calls()))

    def test_frontend_rejects_busy_and_invalid_requests(self):
        result = self.run_script('mode-command.sh', 'headless', '--yes', BUSY='1')
        self.assertNotEqual(result.returncode, 0)
        result = self.run_script('mode-command.sh', 'invalid')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(any(a[:1] == ['start'] for cmd, a in self.calls()))

    def test_frontend_same_mode_is_noop_and_status_is_readonly(self):
        self.assertEqual(self.run_script('mode-command.sh', 'desktop', '--yes').returncode, 0)
        result = self.run_script('mode-command.sh', 'status')
        self.assertEqual(result.returncode, 0)
        self.assertIn('Narsil mode: desktop', result.stdout)
        self.assertFalse(any(a[:1] == ['start'] for cmd, a in self.calls()))

    def test_return_matches_older_generation_not_latest_profile(self):
        self.current.unlink(); self.current.symlink_to(self.child)
        self.marker.write_text('headless\n')
        (self.profiles / 'system').unlink()
        unrelated = self.p / 'newer-profile'
        unrelated.mkdir()
        (self.profiles / 'system').symlink_to(unrelated)
        (self.profiles / 'system-10-link').symlink_to(self.base)
        result = self.run_script('mode-worker.sh', 'desktop')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(['activate', ['desktop', 'test']], self.calls())

    def test_no_matching_parent_fails_without_touching_sessions(self):
        self.current.unlink(); self.current.symlink_to(self.child)
        self.marker.write_text('headless\n')
        (self.profiles / 'system').unlink()
        result = self.run_script('mode-worker.sh', 'desktop')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Cannot find the matching desktop generation', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_cached_parent_survives_profile_removal(self):
        self.current.unlink(); self.current.symlink_to(self.child)
        self.marker.write_text('headless\n')
        (self.profiles / 'system').unlink()
        self.gc.symlink_to(self.base)
        result = self.run_script('mode-worker.sh', 'desktop')
        self.assertEqual(result.returncode, 0, result.stderr)


class ManualStrata(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('stop_manual_strata', SCRIPTS / 'stop-manual-strata.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def proc(self, pid, args, cwd=None, start=123):
        p = self.root / str(pid); p.mkdir()
        (p / 'cwd').symlink_to(cwd or self.mod.ROOT)
        (p / 'cmdline').write_bytes(('\0'.join(args) + '\0').encode())
        (p / 'stat').write_text(f'{pid} (name with spaces) ' + ' '.join(['S'] + ['0'] * 18 + [str(start)]))
        return p

    def test_identifies_only_installed_server_and_serve_engine(self):
        p = self.proc(100, [str(self.mod.ROOT / '.venv/bin/python'), 'serve/server.py'])
        self.assertEqual(self.mod.identify(p, os.getuid()), ('server', '123'))
        self.assertIsNone(self.mod.identify(p, os.getuid() + 1))
        p = self.proc(101, [str(self.mod.ROOT / 'engine/strata'), '--serve'])
        self.assertEqual(self.mod.identify(p, os.getuid()), ('engine', '123'))
        p = self.proc(102, ['python', 'serve/server.py'], cwd=self.root)
        self.assertIsNone(self.mod.identify(p, os.getuid()))
        p = self.proc(103, ['python', 'other.py', str(self.mod.ROOT / 'serve/server.py')])
        self.assertIsNone(self.mod.identify(p, os.getuid()))
        p = self.proc(104, [str(self.mod.ROOT / 'engine/strata'), 'generate'])
        self.assertIsNone(self.mod.identify(p, os.getuid()))

    def test_stops_server_cleanly_without_signalling_its_engine(self):
        self.proc(100, [str(self.mod.ROOT / '.venv/bin/python'), 'serve/server.py'])
        self.proc(101, [str(self.mod.ROOT / 'engine/strata'), '--serve'])
        def terminated(*_):
            for p in self.root.iterdir():
                (p / 'cmdline').write_bytes(b'')
        with patch.object(self.mod.os, 'kill', side_effect=terminated) as kill:
            self.mod.stop(self.root, timeout=1)
        kill.assert_called_once_with(100, self.mod.signal.SIGTERM)

    def test_stops_an_orphan_serve_engine(self):
        p = self.proc(101, [str(self.mod.ROOT / 'engine/strata'), '--serve'])
        with patch.object(self.mod.os, 'kill', side_effect=lambda *_: (p / 'cmdline').write_bytes(b'')) as kill:
            self.mod.stop(self.root, timeout=1)
        kill.assert_called_once_with(101, self.mod.signal.SIGTERM)

    def test_refuses_to_continue_on_timeout_without_sigkill(self):
        self.proc(100, [str(self.mod.ROOT / '.venv/bin/python'), 'serve/server.py'])
        with patch.object(self.mod.os, 'kill') as kill:
            with self.assertRaises(RuntimeError):
                self.mod.stop(self.root, timeout=0)
        kill.assert_called_once_with(100, self.mod.signal.SIGTERM)


if __name__ == '__main__':
    unittest.main()
