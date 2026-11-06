"""Fake managed helper plus temporary cgroup fixtures; no systemctl or real units."""
import asyncio
from dataclasses import replace
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.supervision import (APIState, CgroupReader, JobCompletion, ManagedQuiescence,
                                    SupervisionError, UnitContract, UnitState)


def contract():
    return UnitContract('ollama.service', '/system.slice/ollama.service', 'synthetic-unit-fingerprint',
                        'control-group', True, 0.01, 'no', True, False, True)


class FakeHelper:
    def __init__(self, root, expected):
        self.root, self.expected = root, expected
        self.group = root / expected.cgroup.lstrip('/')
        self.events = []
        self.invocations = 1
        self.state = UnitState(expected, 'active', 'running', 123, f'{1:032x}', expected.cgroup, False)
        self.write(True)
        self.stop_override = self.start_override = None
        self.population_after_stop = False
        self.disappear_after_stop = False
        self.block = None
        self.stop_entered = asyncio.Event()

    def write(self, populated):
        self.group.mkdir(parents=True, exist_ok=True)
        (self.group / 'cgroup.events').write_text(f'populated {int(populated)}\nfrozen 0\n')

    async def snapshot(self):
        self.events.append('snapshot')
        return self.state

    async def stop(self, nonce):
        self.events.append('stop')
        self.stop_entered.set()
        self.state = replace(self.state, pending_job=True)
        if self.block is not None:
            await self.block.wait()
        self.state = replace(self.state, active='inactive', substate='dead', main_pid=0,
                             control_group='', pending_job=False)
        if self.disappear_after_stop:
            shutil.rmtree(self.group)
        else:
            self.write(self.population_after_stop)
        value = JobCompletion(self.expected.unit, 'stop', nonce, True, 'done')
        return self.stop_override(value) if self.stop_override else value

    async def start_lazy(self, nonce):
        self.events.append('start')
        self.invocations += 1
        self.state = replace(self.state, active='active', substate='running', main_pid=456,
                             invocation=f'{self.invocations:032x}', control_group=self.expected.cgroup)
        self.write(True)
        value = JobCompletion(self.expected.unit, 'start', nonce, True, 'done')
        return self.start_override(value) if self.start_override else value


class SupervisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-supervision-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.expected = contract()
        self.helper = FakeHelper(self.root, self.expected)
        self.api = APIState('0.40.11', ())
        self.readiness_override = None
        self.quiescence = self.build()

    async def ready(self):
        self.helper.events.append('ready')
        if self.readiness_override:
            return await self.readiness_override()
        return self.api

    def build(self, **options):
        values = dict(helper=self.helper, population=CgroupReader(str(self.root)), readiness=self.ready,
                      expected_version='0.40.11', phase_timeout=0.05, total_timeout=0.25)
        values.update(options)
        return ManagedQuiescence(self.expected, **values)

    async def test_success_proves_stop_before_new_empty_api(self):
        self.assertTrue(self.quiescence.uncertain)
        self.assertEqual(self.helper.events, [])
        await self.quiescence()
        self.assertFalse(self.quiescence.uncertain)
        self.assertEqual(self.helper.events,
                         ['snapshot', 'stop', 'snapshot', 'start', 'snapshot', 'ready', 'snapshot'])
        self.assertEqual(self.helper.state.invocation, f'{2:032x}')
        await self.quiescence()
        self.assertEqual(self.helper.events.count('stop'), 2)  # No cached proof.
        self.assertEqual(self.helper.state.invocation, f'{3:032x}')

    async def test_missing_group_accepted_only_after_verified_stop(self):
        self.helper.disappear_after_stop = True
        await self.quiescence()
        self.assertFalse(self.quiescence.uncertain)
        self.assertIn('start', self.helper.events)

    async def test_missing_active_group_does_not_prove_anything(self):
        shutil.rmtree(self.helper.group)
        with self.assertRaises(SupervisionError):
            await self.quiescence()
        self.assertNotIn('stop', self.helper.events)
        self.assertNotIn('start', self.helper.events)

    async def test_main_pid_zero_but_populated_descendants_blocks_start(self):
        self.helper.population_after_stop = True
        with self.assertRaises(SupervisionError):
            await self.quiescence()
        self.assertEqual(self.helper.state.main_pid, 0)
        self.assertNotIn('start', self.helper.events)
        self.assertTrue(self.quiescence.uncertain)

    async def test_job_acknowledgement_identity_and_correlation_fail_closed(self):
        mutations = [dict(completed=False), dict(completed=1), dict(result='pending'),
                     dict(result='failed'), dict(unit='unapproved.service'),
                     dict(nonce='different-nonce'), dict(action='restart')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                helper = FakeHelper(self.root, self.expected)
                helper.stop_override = lambda result, mutation=mutation: replace(result, **mutation)
                q = self.build(helper=helper)
                with self.assertRaises(SupervisionError):
                    await q()
                self.assertNotIn('start', helper.events)
                self.assertTrue(q.uncertain)

    async def test_wrong_unit_configuration_or_pending_job_rejected_before_stop(self):
        initial = self.helper.state
        mutations = [dict(pending_job=True), dict(main_pid=True), dict(control_group='/other'),
                     dict(contract=replace(self.expected, unit='other.service')),
                     dict(contract=replace(self.expected, identity='different-deployment')),
                     dict(contract=replace(self.expected, send_sigkill=1)),
                     dict(active='activating'), dict(invocation='unverified-invocation')]
        for mutation in mutations:
            self.helper.state = replace(initial, **mutation)
            self.helper.events.clear()
            with self.subTest(mutation=mutation):
                with self.assertRaises(SupervisionError):
                    await self.quiescence()
                self.assertNotIn('stop', self.helper.events)
                self.assertNotIn('start', self.helper.events)

    async def test_stop_timeout_retains_uncertainty_and_pending_job(self):
        self.helper.block = asyncio.Event()
        with self.assertRaises(SupervisionError):
            await self.quiescence()
        self.assertTrue(self.helper.state.pending_job)
        self.assertNotIn('start', self.helper.events)
        # Retrying cannot conceal a job that may still complete in systemd.
        self.helper.block = None
        with self.assertRaises(SupervisionError):
            await self.quiescence()
        self.assertEqual(self.helper.events.count('stop'), 1)
        self.assertTrue(self.quiescence.uncertain)

    async def test_cancelled_stop_never_runs_unconditional_restart(self):
        self.helper.block = asyncio.Event()
        caller = asyncio.create_task(self.quiescence())
        await asyncio.wait_for(self.helper.stop_entered.wait(), 1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertNotIn('start', self.helper.events)
        self.assertTrue(self.quiescence.uncertain)
        # Model a late completed stop observed by explicit operator reconciliation.
        self.helper.state = replace(self.helper.state, active='inactive', substate='dead', main_pid=0,
                                    control_group='', pending_job=False)
        self.helper.write(False)
        self.helper.block = None
        self.assertNotIn('start', self.helper.events)
        await self.quiescence()
        self.assertFalse(self.quiescence.uncertain)

    async def test_overlapping_transaction_is_rejected_not_queued(self):
        self.helper.block = asyncio.Event()
        caller = asyncio.create_task(self.quiescence())
        await asyncio.wait_for(self.helper.stop_entered.wait(), 1)
        with self.assertRaises(SupervisionError):
            await self.quiescence()
        self.helper.block.set()
        await caller
        self.assertEqual(self.helper.events.count('stop'), 1)

    async def test_start_failure_never_reports_success_or_replays(self):
        self.helper.start_override = lambda result: replace(result, result='failed')
        with self.assertRaises(SupervisionError):
            await self.quiescence()
        self.assertTrue(self.quiescence.uncertain)
        self.assertEqual(self.helper.events.count('start'), 1)
        self.assertNotIn('ready', self.helper.events)

    async def test_successful_job_reply_cannot_replace_unit_state_verification(self):
        for phase in ('stop', 'start'):
            with self.subTest(phase=phase):
                helper = FakeHelper(self.root, self.expected)
                def false_state(result):
                    if phase == 'stop':
                        helper.state = replace(helper.state, active='active', substate='running', main_pid=123,
                                               control_group=self.expected.cgroup)
                    else:
                        helper.state = replace(helper.state, invocation=f'{1:032x}')
                    return result
                if phase == 'stop':
                    helper.stop_override = false_state
                else:
                    helper.start_override = false_state
                q = self.build(helper=helper)
                with self.assertRaises(SupervisionError):
                    await q()
                self.assertTrue(q.uncertain)
                self.assertNotIn('ready', helper.events)
                if phase == 'stop':
                    self.assertNotIn('start', helper.events)

    async def test_readiness_timeout_never_restarts_or_reports_quiescence(self):
        async def slow():
            await asyncio.sleep(1)
            return self.api
        self.readiness_override = slow
        with self.assertRaises(SupervisionError):
            await self.quiescence()
        self.assertTrue(self.quiescence.uncertain)
        self.assertEqual(self.helper.events.count('stop'), 1)
        self.assertEqual(self.helper.events.count('start'), 1)

    async def test_readiness_wrong_version_or_residency_fails_closed(self):
        for api in (APIState('different-version', ()), APIState('0.40.11', ('prewarmed-model',)),
                    APIState('0.40.11', []), None):
            self.api = api
            with self.subTest(api=api):
                with self.assertRaises(SupervisionError):
                    await self.quiescence()
                self.assertTrue(self.quiescence.uncertain)

    async def test_api_invocation_change_during_readiness_fails(self):
        async def change():
            self.helper.state = replace(self.helper.state, invocation=f'{99:032x}')
            return self.api
        self.readiness_override = change
        with self.assertRaises(SupervisionError):
            await self.quiescence()
        self.assertTrue(self.quiescence.uncertain)

    async def test_whole_transaction_deadline_not_reset_by_successful_phases(self):
        original = self.helper.snapshot
        async def slow_snapshot():
            await asyncio.sleep(0.015)
            return await original()
        self.helper.snapshot = slow_snapshot
        q = self.build(total_timeout=0.055)
        with self.assertRaises(SupervisionError):
            await q()
        self.assertTrue(q.uncertain)

    async def test_errors_never_echo_helper_details(self):
        async def broken():
            raise RuntimeError('secret-helper-path-or-credential')
        self.helper.snapshot = broken
        with self.assertRaises(SupervisionError) as error:
            await self.quiescence()
        self.assertNotIn('secret-helper', str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)
        self.assertNotIn('start', self.helper.events)

    async def test_invalid_contracts_and_deadlines_rejected_without_calls(self):
        for mutation in (dict(unit='--arbitrary.service'), dict(kill_mode='process'), dict(send_sigkill=False),
                         dict(restart='always'), dict(lazy_start=False), dict(delegated=True),
                         dict(exclusive_control=False), dict(cgroup='/'), dict(identity='')):
            with self.subTest(mutation=mutation):
                expected = replace(self.expected, **mutation)
                with self.assertRaises(SupervisionError):
                    ManagedQuiescence(expected, helper=self.helper, population=CgroupReader(str(self.root)),
                                      readiness=self.ready, expected_version='0.40.11',
                                      phase_timeout=0.05, total_timeout=0.25)
        for options in (dict(phase_timeout=0), dict(total_timeout=float('inf')),
                        dict(phase_timeout=0.005), dict(total_timeout=0.02), dict(helper=None)):
            with self.subTest(options=options):
                with self.assertRaises(SupervisionError):
                    self.build(**options)
        self.assertEqual(self.helper.events, [])


class CgroupReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-cgroup-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.group = self.root / 'system.slice/ollama.service'
        self.group.mkdir(parents=True)
        self.events = self.group / 'cgroup.events'
        self.events.write_text('populated 0\nfrozen 0\n')
        self.reader = CgroupReader(str(self.root))
        self.name = '/system.slice/ollama.service'

    def test_reads_recursive_population_flag_not_main_pid_or_direct_children(self):
        self.assertIs(self.reader(self.name), False)
        child = self.group / 'runner'
        child.mkdir()
        (child / 'cgroup.procs').write_text('999\n')
        self.events.write_text('populated 1\nfrozen 0\n')
        self.assertIs(self.reader(self.name), True)

    def test_missing_group_is_distinct_from_bad_root_or_missing_events(self):
        self.assertIsNone(self.reader('/system.slice/missing.service'))
        with self.assertRaises(SupervisionError):
            CgroupReader(str(self.root / 'absent-root'))(self.name)
        self.events.unlink()
        with self.assertRaises(SupervisionError):
            self.reader(self.name)

    def test_bad_or_oversized_events_fail_closed(self):
        for body in (b'', b'populated 2\n', b'populated 0\npopulated 0\n', b'frozen 0\n',
                     b'populated 00\n', b'populated 0\n' + b'x' * 4096, b'\xff', b'populated 0 extra\n'):
            with self.subTest(body=body[:30]):
                self.events.write_bytes(body)
                with self.assertRaises(SupervisionError):
                    self.reader(self.name)

    def test_symlink_events_and_group_are_refused(self):
        target = self.root / 'other-events'
        target.write_text('populated 0\n')
        self.events.unlink()
        self.events.symlink_to(target)
        with self.assertRaises(SupervisionError):
            self.reader(self.name)
        self.events.unlink()
        self.group.rmdir()
        other = self.root / 'other-group'
        other.mkdir()
        (other / 'cgroup.events').write_text('populated 0\n')
        self.group.symlink_to(other, target_is_directory=True)
        with self.assertRaises(SupervisionError):
            self.reader(self.name)

    def test_read_success_and_failure_do_not_leak_descriptors(self):
        descriptors = Path('/proc/self/fd')
        baseline = len(list(descriptors.iterdir()))
        for _ in range(10):
            self.assertIs(self.reader(self.name), False)
            self.assertIsNone(self.reader('/system.slice/missing.service'))
            with self.assertRaises(SupervisionError):
                CgroupReader(str(self.root / 'missing-root'))(self.name)
        self.assertEqual(len(list(descriptors.iterdir())), baseline)

    def test_root_symlink_or_traversal_paths_are_refused(self):
        link = self.root / 'linked-root'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(SupervisionError):
            CgroupReader(str(link))(self.name)
        for group in ('/', '/../escape', '/system.slice//ollama.service', '//system.slice/ollama.service',
                      'relative', '/system.slice/../ollama.service', '/control\n/ollama.service'):
            with self.subTest(group=group):
                with self.assertRaises(SupervisionError):
                    self.reader(group)
