"""Pure synthetic evidence; no installed units, mutations or model queries."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.bus_identity import BusIdentity
from coordinator.supervision import SupervisionError
from coordinator.systemd_inspect import UnitEvidence
from coordinator.unit_policy import UnitSafetyPolicy


def evidence():
    return UnitEvidence(
        unit='ollama.service', object_path='/org/freedesktop/systemd1/unit/ollama_2eservice',
        bus_identity=BusIdentity('a' * 32, ':1.99'), active='active', substate='running',
        invocation='1' * 32, job_id=0, job_path='/', main_pid=123, control_pid=0,
        control_group='/system.slice/ollama.service', kill_mode='control-group',
        send_sigkill=True, final_kill_signal=9, stop_timeout_usec=90000000,
        restart='no', delegated=False, service_type='exec', remain_after_exit=False,
        triggered_by=(), transient=False, refuse_manual_start=False, refuse_manual_stop=False)


class UnitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = UnitSafetyPolicy('ollama.service', '/system.slice/ollama.service',
                                       BusIdentity('a' * 32, ':1.99'), 90000000, 'exec')

    def test_immutable_explicit_policy_no_authority_return(self):
        with self.assertRaises(FrozenInstanceError):
            self.policy.unit = 'other.service'
        self.assertIsNone(self.policy.check(evidence()))
        # This result is intentionally not a UnitState or completion receipt.

    def test_inactive_observations_are_allowed_not_release_proof(self):
        for cgroup in ('', self.policy.cgroup):
            for invocation in ('', '1' * 32):
                value = replace(evidence(), active='inactive', substate='dead',
                                main_pid=0, control_group=cgroup, invocation=invocation)
                self.assertIsNone(self.policy.check(value))

    def test_unsafe_or_mismatched_fields_refused(self):
        cases = dict(
            unit='other.service', object_path='/untrusted',
            bus_identity=BusIdentity('b' * 32, ':1.99'), job_id=1,
            job_path='/org/freedesktop/systemd1/job/1', control_pid=12,
            control_group='/other/ollama.service', kill_mode='process', send_sigkill=False,
            final_kill_signal=15, stop_timeout_usec=90000001, restart='always',
            delegated=True, service_type='forking', remain_after_exit=True,
            triggered_by=('ollama.socket',), transient=True,
            refuse_manual_start=True, refuse_manual_stop=True,
            main_pid=0, invocation='0' * 32, active='activating', substate='start')
        for key, value in cases.items():
            with self.subTest(field=key), self.assertRaises(SupervisionError):
                self.policy.check(replace(evidence(), **{key: value}))

    def test_bus_owner_changes_refused_independently(self):
        with self.assertRaises(SupervisionError):
            self.policy.check(replace(evidence(), bus_identity=BusIdentity('a' * 32, ':1.100')))

    def test_malformed_typed_dataclasses_do_not_bypass(self):
        for key, value in dict(job_id=False, control_pid=False, main_pid=True,
                               send_sigkill=1, delegated=0, triggered_by=[],
                               stop_timeout_usec=90000000.0, invocation=None,
                               bus_identity=None, object_path=1).items():
            with self.subTest(field=key), self.assertRaises(SupervisionError):
                self.policy.check(replace(evidence(), **{key: value}))
        for value in (None, {}, self.policy):
            with self.assertRaises(SupervisionError):
                self.policy.check(value)

    def test_state_coherence_and_bounds(self):
        cases = [dict(main_pid=-1), dict(main_pid=2**32), dict(invocation='A' * 32),
                 dict(invocation='1' * 31), dict(active='failed', substate='failed'),
                 dict(active='inactive', substate='dead'),
                 dict(active='inactive', substate='dead', main_pid=0, invocation='bad'),
                 dict(active='inactive', substate='dead', main_pid=0, control_group='/wrong')]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(SupervisionError):
                self.policy.check(replace(evidence(), **changes))

    def test_invalid_policy_rejected_before_any_io(self):
        cases = dict(unit='../ollama.service', cgroup='/system.slice/other.service',
                     bus_identity=None, stop_timeout_usec=True, service_type='notify')
        for key, value in cases.items():
            with self.subTest(field=key), self.assertRaises(SupervisionError):
                replace(self.policy, **{key: value})
        for timeout in (0, -1, float('inf'), 86400 * 1000000 + 1):
            with self.assertRaises(SupervisionError):
                replace(self.policy, stop_timeout_usec=timeout)
        for group in ('/', '//ollama.service', '/system.slice/../ollama.service'):
            with self.assertRaises(SupervisionError):
                replace(self.policy, cgroup=group)

    def test_exact_service_type_pin(self):
        policy = replace(self.policy, service_type='simple')
        with self.assertRaises(SupervisionError):
            policy.check(evidence())
        self.assertIsNone(policy.check(replace(evidence(), service_type='simple')))


if __name__ == '__main__':
    unittest.main()
