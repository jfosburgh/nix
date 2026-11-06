"""Integrated fake bus/inspector/cgroup, real journal; no installed unit calls."""
import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.deployment import StoreArtifact, StoreUnitDeployment
from coordinator.job_journal import JobJournal
from coordinator.managed_helper import ManagedUnitHelper
from coordinator.supervision import APIState, ManagedQuiescence, SupervisionError, UnitContract
from coordinator.systemd_jobs import SystemdJobSession
from test_systemd_jobs import FakeBus, BUS, FENCE
from test_unit_policy import evidence


class HelperTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-helper-')
        self.addCleanup(self.temp.cleanup)
        Path(self.temp.name).chmod(0o700)
        self.deployment = StoreUnitDeployment('ollama.service', StoreArtifact(
            '/nix/store/' + 'a' * 32 + '-unit', 'b' * 64), ())
        self.contract = UnitContract('ollama.service', '/system.slice/ollama.service',
                                     self.deployment.identity, 'control-group', True,
                                     0.01, 'no', True, False, True)
        self.journal = JobJournal(self.temp.name + '/jobs', unit='ollama.service',
                                  identity=self.deployment.identity, boot_id='b' * 32,
                                  bus_identity=BUS, manager_load_usec=FENCE.units_load_usec,
                                  manager_version='262').open(initialize=True)
        self.addCleanup(self.journal.close)
        self.bus = FakeBus()
        self.session = SystemdJobSession(self.journal, expected=FENCE, bus_factory=lambda: self.bus)
        self.addAsyncCleanup(self.session.close)
        await self.session.open()
        self.state = replace(evidence(), stop_timeout_usec=10000)
        self.population = True
        self.inspector = SimpleNamespace(unit='ollama.service', expected_bus=BUS,
                                          inspect=AsyncMock(side_effect=lambda: self.state))
        self.manifest_patch = patch.object(StoreUnitDeployment, 'check', new=AsyncMock())
        self.manifest_check = self.manifest_patch.start()
        self.addCleanup(self.manifest_patch.stop)
        self.helper = self.build()
        self.bus.on_mutation = self.transition

    def build(self, **kwargs):
        args = dict(deployment=self.deployment, session=self.session, inspector=self.inspector,
                    population=lambda group: self.population, service_type='exec')
        args.update(kwargs)
        return ManagedUnitHelper(self.contract, **args)

    def transition(self):
        method = self.bus.calls[-1].member
        if method == 'StopUnit':
            self.state = replace(self.state, active='inactive', substate='dead', main_pid=0)
            self.population = False
        elif method == 'StartUnit':
            self.state = replace(self.state, active='active', substate='running', main_pid=222,
                                 invocation='2' * 32)
            self.population = True

    def mutations(self):
        return [c.member for c in self.bus.calls if c.member in ('StartUnit', 'StopUnit')]

    async def test_complete_managed_quiescence_uses_real_journal_session(self):
        # Increment fake IDs between operations, as the real manager does.
        actual_run = self.session.run
        async def run(*args):
            self.bus.job_id += 1
            return await actual_run(*args)
        self.session.run = run
        readiness = AsyncMock(return_value=APIState('fixture-version', ()))
        transaction = ManagedQuiescence(self.contract, helper=self.helper,
                                         population=lambda _: self.population, readiness=readiness,
                                         expected_version='fixture-version', phase_timeout=0.5,
                                         total_timeout=2)
        await transaction()
        self.assertFalse(transaction.uncertain)
        self.assertEqual(self.mutations(), ['StopUnit', 'StartUnit'])
        self.assertIsNone(self.journal.pending)
        readiness.assert_awaited_once()
        self.assertGreaterEqual(self.manifest_check.await_count, 6)

    async def test_snapshot_validates_manifest_policy_and_fence_without_mutation(self):
        state = await self.helper.snapshot()
        self.assertEqual(state.contract, self.contract)
        self.assertFalse(state.pending_job)
        self.assertEqual(self.mutations(), [])
        self.state = replace(self.state, restart='always')
        with self.assertRaises(SupervisionError):
            await self.helper.stop('1' * 32)
        self.assertEqual(self.mutations(), [])

    async def test_start_without_live_stop_proof_never_mutates(self):
        with self.assertRaises(SupervisionError):
            await self.helper.start_lazy('1' * 32)
        self.assertEqual(self.mutations(), [])

    async def test_populated_descendants_after_stop_leave_intent_pending(self):
        original = self.bus.on_mutation
        def transition():
            original()
            self.population = True
        self.bus.on_mutation = transition
        with self.assertRaises(SupervisionError):
            await self.helper.stop('1' * 32)
        self.assertEqual(self.journal.pending.result, 'done')
        with self.assertRaises(SupervisionError):
            await self.helper.start_lazy('2' * 32)
        self.assertEqual(self.mutations(), ['StopUnit'])

    async def test_missing_active_group_prevents_stop(self):
        self.population = None
        with self.assertRaises(SupervisionError):
            await self.helper.stop('1' * 32)
        self.assertEqual(self.mutations(), [])

    async def test_disappeared_group_only_after_correlated_stop(self):
        original = self.bus.on_mutation
        def transition():
            original()
            self.population = None
        self.bus.on_mutation = transition
        await self.helper.stop('1' * 32)
        self.assertIsNone(self.journal.pending)

    async def test_false_ack_without_inactive_state_stays_pending(self):
        self.bus.on_mutation = None
        with self.assertRaises(SupervisionError):
            await self.helper.stop('1' * 32)
        self.assertIsNotNone(self.journal.pending)

    async def test_changed_policy_or_manifest_before_stop_never_mutates(self):
        self.manifest_check.side_effect = SupervisionError('fixture')
        with self.assertRaises(SupervisionError):
            await self.helper.stop('1' * 32)
        self.assertEqual(self.mutations(), [])

    async def test_changed_population_between_stop_and_start_refuses_start(self):
        await self.helper.stop('1' * 32)
        self.population = True
        with self.assertRaises(SupervisionError):
            await self.helper.start_lazy('2' * 32)
        self.assertEqual(self.mutations(), ['StopUnit'])

    async def test_new_helper_does_not_inherit_start_authority(self):
        await self.helper.stop('1' * 32)
        other = self.build()
        with self.assertRaises(SupervisionError):
            await other.start_lazy('2' * 32)
        self.assertEqual(self.mutations(), ['StopUnit'])

    async def test_failed_or_cancelled_stop_never_grants_start(self):
        self.bus.result = 'failed'
        with self.assertRaises(SupervisionError):
            await self.helper.stop('1' * 32)
        with self.assertRaises(SupervisionError):
            await self.helper.start_lazy('2' * 32)
        self.assertEqual(self.mutations(), ['StopUnit'])

    async def test_cancellation_leaves_durable_intent(self):
        self.bus.mode = 'timeout'
        task = asyncio.create_task(self.helper.stop('1' * 32))
        await self.bus.mutating.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(self.journal.pending)
        with self.assertRaises(SupervisionError):
            await self.helper.start_lazy('2' * 32)

    async def test_dependency_and_identity_mismatch_rejected(self):
        for changes in (dict(identity='wrong'), dict(lazy_start=False), dict(exclusive_control=False),
                        dict(restart='always'), dict(stop_timeout=float('inf'))):
            with self.assertRaises(SupervisionError):
                ManagedUnitHelper(replace(self.contract, **changes), deployment=self.deployment,
                                  session=self.session, inspector=self.inspector,
                                  population=lambda _: False, service_type='exec')


if __name__ == '__main__':
    unittest.main()
