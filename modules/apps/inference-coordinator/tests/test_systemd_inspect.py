"""Fake busctl processes only; no systemd or real service operations."""
import asyncio
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.systemd_inspect import SystemdInspector
from coordinator.bus_identity import BusIdentity
from coordinator.supervision import SupervisionError


def typed(signature, data):
    return dict(type=signature, data=data)


def properties():
    return {
        'Id': typed('s', 'ollama.service'), 'LoadState': typed('s', 'loaded'),
        'ActiveState': typed('s', 'active'), 'SubState': typed('s', 'running'),
        'InvocationID': typed('ay', list(range(16))), 'Job': typed('(uo)', [0, '/']),
        'NeedDaemonReload': typed('b', False), 'RefuseManualStart': typed('b', False),
        'RefuseManualStop': typed('b', False), 'TriggeredBy': typed('as', []),
        'Transient': typed('b', False), 'MainPID': typed('u', 123),
        'ControlPID': typed('u', 0), 'ControlGroup': typed('s', '/system.slice/ollama.service'),
        'KillMode': typed('s', 'control-group'), 'SendSIGKILL': typed('b', True),
        'FinalKillSignal': typed('i', 9), 'TimeoutStopUSec': typed('t', 90000000),
        'Restart': typed('s', 'no'), 'Delegate': typed('b', False),
        'Type': typed('s', 'exec'), 'RemainAfterExit': typed('b', False),
    }


class InspectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-inspect-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.log = self.root / 'commands.jsonl'
        self.pid = self.root / 'pid'
        self.counter = self.root / 'counter'
        self.binary = self.root / 'fake-busctl'
        self.binary.write_text(f'''#!{sys.executable}
import json, os, sys, time
from pathlib import Path
root = Path({str(self.root)!r})
cfg = json.loads((root / 'config.json').read_text())
with (root / 'commands.jsonl').open('a') as log:
    log.write(json.dumps(dict(args=sys.argv[1:], env=dict(os.environ), cwd=os.getcwd())) + '\\n')
(root / 'pid').write_text(str(os.getpid()))
mode = cfg.get('mode')
if mode == 'sleep':
    time.sleep(60)
if mode == 'fork':
    if os.fork() == 0:
        (root / 'descendant').write_text(str(os.getpid()))
        time.sleep(60)
        os._exit(0)
    time.sleep(60)
if cfg.get('delay'):
    time.sleep(cfg['delay'])
if mode == 'stdout':
    os.write(1, b'x' * 200000)
    time.sleep(60)
if mode == 'stderr':
    os.write(2, b'private diagnostic' * 20000)
    time.sleep(60)
if mode == 'failure':
    os.write(2, b'private diagnostic')
    sys.exit(1)
if mode == 'warning':
    os.write(2, b'private diagnostic')
if mode == 'raw':
    os.write(1, cfg['raw'].encode())
    sys.exit(0)
args = sys.argv[1:]
def next_value(key, default):
    path = root / (key + '-counter')
    n = int(path.read_text()) if path.exists() else 0
    path.write_text(str(n + 1))
    sequence = cfg.get(key, [default])
    return sequence[min(n, len(sequence) - 1)]
if 'GetId' in args:
    print(json.dumps(cfg.get('bus_reply', dict(type='s', data=[next_value('bus_ids', 'a' * 32)]))))
elif 'GetNameOwner' in args:
    print(json.dumps(cfg.get('owner_reply', dict(type='s', data=[next_value('owners', ':1.99')]))))
elif cfg.get('manager_fails'):
    os.write(2, b'private diagnostic')
    sys.exit(1)
elif 'call' in args:
    print(json.dumps(cfg.get('lookup', dict(type='o', data=['/org/freedesktop/systemd1/unit/ollama_2eservice']))))
else:
    start = args.index('get-property')
    names = args[start + 4:]
    values = cfg['properties']
    if 'Id' in names:
        counter = root / 'counter'
        n = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(n + 1))
        if n and cfg.get('after'):
            values.update(cfg['after'])
    for name in names:
        print(json.dumps(values[name]))
''')
        self.binary.chmod(0o700)
        self.values = dict(properties=properties())
        self.save()
        self.inspector = self.build()

    def save(self):
        self.config.write_text(json.dumps(self.values))

    def build(self, **options):
        config = dict(executable=str(self.binary), unit='ollama.service', timeout=3,
                      expected_bus=BusIdentity('a' * 32, ':1.99'),
                      cleanup_timeout=0.5, output_limit=65536)
        config.update(options)
        return SystemdInspector(**config)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    async def wait_pid(self, name='pid'):
        async with asyncio.timeout(2):
            path = self.root / name
            while not path.exists():
                await asyncio.sleep(0.005)
            return int(path.read_text())

    def reaped(self):
        pid = int(self.pid.read_text())
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        self.assertFalse(Path(f'/proc/{pid}').exists())

    async def test_construction_no_io_and_selected_read_only_commands(self):
        self.assertFalse(self.log.exists())
        with patch.dict(os.environ, {'DBUS_SYSTEM_BUS_ADDRESS': 'untrusted', 'LD_PRELOAD': 'untrusted'}):
            evidence = await self.inspector.inspect()
        self.assertEqual(evidence.unit, 'ollama.service')
        self.assertEqual(evidence.invocation, bytes(range(16)).hex())
        self.assertEqual(evidence.main_pid, 123)
        self.assertEqual(evidence.stop_timeout_usec, 90000000)
        self.assertEqual(evidence.job_id, 0)
        with self.assertRaises(FrozenInstanceError):
            evidence.active = 'inactive'
        calls = self.commands()
        self.assertEqual(len(calls), 8)
        self.assertEqual(evidence.bus_identity, BusIdentity('a' * 32, ':1.99'))
        self.assertEqual(calls[0]['args'][-1], 'GetId')
        self.assertEqual(calls[1]['args'][-3:], ['GetNameOwner', 's', 'org.freedesktop.systemd1'])
        self.assertEqual(calls[2]['args'][-3:], ['GetUnit', 's', 'ollama.service'])
        for call in calls[2:6]:
            verb = 'call' if 'call' in call['args'] else 'get-property'
            self.assertEqual(call['args'][call['args'].index(verb) + 1], ':1.99')
        self.assertEqual(calls[-2]['args'][-3:], ['GetNameOwner', 's', 'org.freedesktop.systemd1'])
        self.assertEqual(calls[-1]['args'][-1], 'GetId')
        for call in calls:
            self.assertEqual(call['cwd'], '/')
            self.assertNotIn('DBUS_SYSTEM_BUS_ADDRESS', call['env'])
            self.assertNotIn('LD_PRELOAD', call['env'])
            self.assertIn('--auto-start=no', call['args'])
            self.assertIn('--allow-interactive-authorization=no', call['args'])
            self.assertFalse(set(call['args']) & {'GetAll', 'LoadUnit', 'StartUnit', 'StopUnit', 'Environment'})
        self.reaped()

    async def test_pending_job_and_unsafe_policy_are_evidence_not_success(self):
        props = self.values['properties']
        props['Job'] = typed('(uo)', [23, '/org/freedesktop/systemd1/job/23'])
        props['Restart'] = typed('s', 'always')
        props['TriggeredBy'] = typed('as', ['ollama.socket'])
        props['Delegate'] = typed('b', True)
        self.save()
        evidence = await self.inspector.inspect()
        self.assertEqual(evidence.job_id, 23)
        self.assertEqual(evidence.restart, 'always')
        self.assertTrue(evidence.delegated)
        self.assertEqual(evidence.triggered_by, ('ollama.socket',))
        self.assertFalse(hasattr(evidence, 'contract'))
        self.assertFalse(hasattr(self.inspector, 'stop'))

    async def test_inactive_and_failed_without_invocation_or_cgroup(self):
        props = self.values['properties']
        for active, sub in [('inactive', 'dead'), ('failed', 'failed')]:
            props.update(ActiveState=typed('s', active), SubState=typed('s', sub),
                         MainPID=typed('u', 0), InvocationID=typed('ay', []),
                         ControlGroup=typed('s', ''))
            self.save()
            evidence = await self.inspector.inspect()
            self.assertEqual(evidence.active, active)
            self.assertEqual(evidence.invocation, '')

    async def test_lookup_unknown_shapes_and_paths_rejected(self):
        for lookup in [dict(type='s', data=['/wrong']), dict(type='o', data='/wrong'),
                       dict(type='o', data=['/wrong']), dict(type='o', data=[]),
                       dict(type='o', data=['/org/freedesktop/systemd1/unit/x', 'extra'])]:
            self.values['lookup'] = lookup
            self.save()
            with self.subTest(lookup=lookup), self.assertRaises(SupervisionError):
                await self.inspector.inspect()

    async def test_malformed_duplicate_truncated_or_extra_json_rejected(self):
        for raw in ['{', '{}\n', '{"type":"o","type":"o","data":[]}\n',
                    '{"type":"o","data":[]}\n{}\n', '\ufffd\n']:
            self.values.update(mode='raw', raw=raw)
            self.save()
            with self.subTest(raw=raw), self.assertRaises(SupervisionError):
                await self.inspector.inspect()

    async def test_wrong_property_types_and_inconsistent_states_fail_closed(self):
        mutations = [('MainPID', typed('u', True)), ('MainPID', typed('u', -1)),
                     ('MainPID', typed('u', 2**32)), ('MainPID', typed('u', 0)),
                     ('SendSIGKILL', typed('b', 1)), ('Delegate', typed('s', 'false')),
                     ('InvocationID', typed('ay', [0] * 15)),
                     ('InvocationID', typed('ay', [True] * 16)),
                     ('InvocationID', typed('ay', [])), ('ControlGroup', typed('s', '/')),
                     ('ControlGroup', typed('s', '/bad/../path')),
                     ('ControlGroup', typed('s', '')), ('Job', typed('(uo)', [1, '/'])),
                     ('Job', typed('(uo)', [0, '/org/freedesktop/systemd1/job/1'])),
                     ('Id', typed('s', 'other.service')), ('LoadState', typed('s', 'not-found')),
                     ('NeedDaemonReload', typed('b', True)), ('ActiveState', typed('s', 'activating')),
                     ('SubState', typed('s', 'dead'))]
        for name, value in mutations:
            self.values['properties'] = properties()
            self.values['properties'][name] = value
            self.save()
            with self.subTest(name=name, value=value), self.assertRaises(SupervisionError):
                await self.inspector.inspect()

    async def test_unit_changed_across_service_read_rejected(self):
        self.values['after'] = dict(InvocationID=typed('ay', [99] * 16))
        self.save()
        with self.assertRaises(SupervisionError):
            await self.inspector.inspect()

    async def test_nonzero_or_stderr_errors_sanitized_and_no_retry(self):
        for mode in ('failure', 'warning'):
            self.values['mode'] = mode
            self.save()
            self.log.unlink(missing_ok=True)
            with self.subTest(mode=mode), self.assertRaises(SupervisionError) as error:
                await self.inspector.inspect()
            self.assertNotIn('private diagnostic', str(error.exception))
            self.assertEqual(len(self.commands()), 1)
            self.reaped()

    async def test_timeout_and_cancellation_kill_and_reap(self):
        for cancel in (False, True):
            self.values['mode'] = 'sleep'
            self.save()
            self.pid.unlink(missing_ok=True)
            inspector = self.build(timeout=0.25)
            task = asyncio.create_task(inspector.inspect())
            await self.wait_pid()
            if cancel:
                task.cancel()
            with self.subTest(cancel=cancel), self.assertRaises(
                    asyncio.CancelledError if cancel else SupervisionError):
                await task
            self.reaped()
            self.assertFalse(inspector._cleanup)

    async def test_output_floods_killed_reaped_and_bounded(self):
        for mode in ('stdout', 'stderr'):
            self.values['mode'] = mode
            self.save()
            inspector = self.build(output_limit=1024)
            started = time.monotonic()
            with self.subTest(mode=mode), self.assertRaises(SupervisionError):
                await inspector.inspect()
            self.assertLess(time.monotonic() - started, 2)
            self.reaped()
            self.assertFalse(inspector._faulted)
            self.assertFalse(inspector._cleanup)

    async def test_process_group_cleanup_includes_inherited_pipe_descendant(self):
        self.values['mode'] = 'fork'
        self.save()
        inspector = self.build(timeout=0.5)
        task = asyncio.create_task(inspector.inspect())
        child = await self.wait_pid('descendant')
        with self.assertRaises(SupervisionError):
            await task
        self.reaped()
        status = Path(f'/proc/{child}/stat')
        if status.exists():
            self.assertEqual(status.read_text().split()[2], 'Z')  # Killed, awaiting init reap.
        self.assertFalse(inspector._cleanup)

    async def test_overlap_refused_instead_of_spawning(self):
        self.values['mode'] = 'sleep'
        self.save()
        task = asyncio.create_task(self.inspector.inspect())
        await self.wait_pid()
        with self.assertRaises(SupervisionError):
            await self.inspector.inspect()
        self.assertEqual(len(self.commands()), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.reaped()

    async def test_whole_inspection_deadline_not_reset_per_command(self):
        self.values['delay'] = 0.15
        self.save()
        started = time.monotonic()
        with self.assertRaises(SupervisionError):
            await self.build(timeout=0.4).inspect()
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertLess(len(self.commands()), 8)
        self.reaped()

    async def test_missing_executable_is_sanitized_and_no_unhandled_task(self):
        inspector = self.build(executable=str(self.root / 'missing'))
        with self.assertRaises(SupervisionError) as error:
            await inspector.inspect()
        self.assertNotIn(str(self.root), str(error.exception))
        self.assertFalse(inspector._cleanup)
        self.assertTrue(inspector._faulted)

    async def test_cancelled_late_spawn_stays_tracked_and_is_eventually_reaped(self):
        self.values['mode'] = 'sleep'
        self.save()
        original = asyncio.create_subprocess_exec
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            process = await original(*args, **kwargs)
            started.set()
            await release.wait()
            return process
        inspector = self.build(cleanup_timeout=0.03)
        with patch('coordinator.systemd_inspect.asyncio.create_subprocess_exec', side_effect=delayed):
            task = asyncio.create_task(inspector.inspect())
            await started.wait()
            await self.wait_pid()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(inspector._faulted)
            self.assertTrue(inspector._cleanup)
            with self.assertRaises(SupervisionError):
                await inspector.inspect()
            release.set()
            async with asyncio.timeout(2):
                while inspector._cleanup:
                    await asyncio.sleep(0.005)
        self.reaped()

    async def test_repeated_cancellation_does_not_abandon_process_cleanup(self):
        self.values['mode'] = 'sleep'
        self.save()
        original = self.inspector._reap
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(spawn, tasks):
            entered.set()
            await release.wait()
            await original(spawn, tasks)
        with patch.object(self.inspector, '_reap', side_effect=delayed):
            task = asyncio.create_task(self.inspector.inspect())
            await self.wait_pid()
            task.cancel()
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(self.inspector._faulted)
            self.assertTrue(self.inspector._cleanup)
            release.set()
            async with asyncio.timeout(2):
                while self.inspector._cleanup:
                    await asyncio.sleep(0.005)
        self.reaped()

    async def test_repeated_success_and_error_do_not_leak_descriptors(self):
        # Prime the event loop's child-watcher machinery before counting.
        await self.inspector.inspect()
        before = len(os.listdir('/proc/self/fd'))
        for _ in range(3):
            await self.inspector.inspect()
            self.values['mode'] = 'stdout'
            self.save()
            with self.assertRaises(SupervisionError):
                await self.inspector.inspect()
            self.values.pop('mode')
            self.save()
        self.assertEqual(before, len(os.listdir('/proc/self/fd')))

    async def test_wrong_entry_bus_or_owner_blocks_all_manager_calls_and_faults(self):
        for changes in (dict(bus_ids=['b' * 32]), dict(owners=[':1.100'])):
            self.values = dict(properties=properties(), **changes)
            self.save()
            self.log.unlink(missing_ok=True)
            inspector = self.build()
            with self.subTest(changes=changes), self.assertRaises(SupervisionError):
                await inspector.inspect()
            self.assertTrue(inspector._faulted)
            calls = self.commands()
            self.assertEqual(len(calls), 2)
            self.assertFalse(any('GetUnit' in call['args'] for call in calls))
            # Recovery of the observed endpoint does not automatically repin or
            # restore this instance after an identity mismatch.
            self.values = dict(properties=properties())
            self.save()
            with self.assertRaises(SupervisionError):
                await inspector.inspect()
            self.assertEqual(self.commands(), calls)

    async def test_bus_restart_with_reused_owner_and_job_id_rejected_at_exit(self):
        self.values.update(bus_ids=['a' * 32, 'b' * 32])
        self.values['properties']['Job'] = typed('(uo)', [42, '/org/freedesktop/systemd1/job/42'])
        self.save()
        with self.assertRaises(SupervisionError):
            await self.inspector.inspect()
        self.assertTrue(self.inspector._faulted)
        self.assertEqual(len(self.commands()), 8)

    async def test_manager_owner_change_during_read_rejected_at_exit(self):
        self.values['owners'] = [':1.99', ':1.100']
        self.save()
        with self.assertRaises(SupervisionError):
            await self.inspector.inspect()
        self.assertTrue(self.inspector._faulted)
        self.assertEqual(len(self.commands()), 8)

    async def test_owner_change_between_inspections_never_repins(self):
        await self.inspector.inspect()
        self.values['owners'] = [':1.100']
        self.save()
        with self.assertRaises(SupervisionError):
            await self.inspector.inspect()
        calls = self.commands()
        self.assertEqual(len(calls), 10)
        self.assertEqual(sum('GetUnit' in call['args'] for call in calls), 1)
        self.assertTrue(self.inspector._faulted)

    async def test_malformed_identity_method_replies_fail_before_unit_lookup(self):
        for key in ('bus_reply', 'owner_reply'):
            for reply in [typed('o', ['not-an-object']), typed('s', []),
                          typed('s', ['one', 'two']), typed('s', True),
                          typed('s', ['bad']), typed('s', [None])]:
                self.values = dict(properties=properties(), **{key: reply})
                self.save()
                self.log.unlink(missing_ok=True)
                with self.subTest(key=key, reply=reply), self.assertRaises(SupervisionError):
                    await self.build().inspect()
                self.assertFalse(any('GetUnit' in call['args'] for call in self.commands()))

    async def test_vanished_pinned_manager_has_no_well_known_fallback(self):
        self.values['manager_fails'] = True
        self.save()
        with self.assertRaises(SupervisionError):
            await self.inspector.inspect()
        calls = self.commands()
        self.assertEqual(len(calls), 3)
        manager = calls[-1]['args']
        self.assertEqual(manager[manager.index('call') + 1], ':1.99')
        self.assertNotIn('LoadUnit', manager)
        self.reaped()

    async def test_constructor_rejects_paths_units_limits_and_deadlines_without_io(self):
        for options in [dict(executable='busctl'), dict(executable='/bin/../busctl'),
                        dict(unit='--host=untrusted'), dict(unit='x.service;anything'),
                        dict(timeout=True), dict(timeout=float('inf')),
                        dict(cleanup_timeout=0), dict(output_limit=True), dict(output_limit=2**30),
                        dict(expected_bus=None), dict(expected_bus={'bus_id': 'a' * 32})]:
            with self.subTest(options=options), self.assertRaises(SupervisionError):
                self.build(**options)
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
