"""Pure preliminary safety gate for inspector evidence, NOT deployment approval.

No systemd calls, UnitState conversion, job reconciliation or release proof.
Passing this gate cannot establish ExecStart/hooks, lazy startup, exclusive
control, trusted pins, or a stable manager epoch. The future helper must verify
those independently before any mutation.
"""
from dataclasses import dataclass
import re

from .bus_identity import BusIdentity
from .supervision import SupervisionError, _parts
from .systemd_inspect import UnitEvidence


@dataclass(frozen=True)
class UnitSafetyPolicy:
    unit: str
    cgroup: str
    bus_identity: BusIdentity
    stop_timeout_usec: int
    service_type: str

    def __post_init__(self):
        if (type(self.unit) is not str or not re.fullmatch(
                r'[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.service', self.unit)
                or type(self.cgroup) is not str or not _parts(self.cgroup)
                or self.cgroup.rsplit('/', 1)[-1] != self.unit
                or type(self.bus_identity) is not BusIdentity
                or type(self.stop_timeout_usec) is not int
                or not 0 < self.stop_timeout_usec <= 86400 * 1000000
                or self.service_type not in ('exec', 'simple')
                or type(self.service_type) is not str):
            raise SupervisionError('Invalid unit safety policy')

    def check(self, evidence: UnitEvidence) -> None:
        """Refuse unsafe/stale/busy observations; success grants NO authority.

        Exact stop timeout/type pins prevent accepting an accidentally different
        deployment policy. Inactive units may have an empty ControlGroup and
        InvocationID, but this is never treated as proof that a stop completed.
        Even Job=0 cannot settle a journal intent. Evidence must be freshly read
        by the future helper; this pure function cannot establish freshness.
        """
        if type(evidence) is not UnitEvidence:
            raise SupervisionError('Invalid unit safety evidence')
        # Dataclass annotations do not enforce types, and bool equals int in
        # Python. Do not promote hand-constructed/altered evidence on equality.
        strings = ('unit', 'object_path', 'active', 'substate', 'invocation',
                   'job_path', 'control_group', 'kill_mode', 'restart', 'service_type')
        integers = ('job_id', 'main_pid', 'control_pid', 'final_kill_signal',
                    'stop_timeout_usec')
        booleans = ('send_sigkill', 'delegated', 'remain_after_exit', 'transient',
                    'refuse_manual_start', 'refuse_manual_stop')
        if (any(type(getattr(evidence, key)) is not str for key in strings)
                or any(type(getattr(evidence, key)) is not int for key in integers)
                or any(type(getattr(evidence, key)) is not bool for key in booleans)
                or type(evidence.bus_identity) is not BusIdentity
                or type(evidence.triggered_by) is not tuple):
            raise SupervisionError('Invalid unit safety evidence')
        if (evidence.unit != self.unit or evidence.bus_identity != self.bus_identity
                or not re.fullmatch(r'/org/freedesktop/systemd1/unit/[A-Za-z0-9_]{1,512}',
                                    evidence.object_path)
                or evidence.job_id != 0 or evidence.job_path != '/'
                or evidence.control_pid != 0
                or evidence.kill_mode != 'control-group' or not evidence.send_sigkill
                or evidence.final_kill_signal != 9
                or evidence.stop_timeout_usec != self.stop_timeout_usec
                or evidence.restart != 'no' or evidence.delegated
                or evidence.service_type != self.service_type or evidence.remain_after_exit
                or evidence.triggered_by or evidence.transient
                or evidence.refuse_manual_start or evidence.refuse_manual_stop):
            raise SupervisionError('Unsafe or busy unit policy')
        if (evidence.active, evidence.substate) == ('active', 'running'):
            valid = (0 < evidence.main_pid <= 2**32 - 1
                     and evidence.control_group == self.cgroup
                     and re.fullmatch(r'[0-9a-f]{32}', evidence.invocation)
                     and evidence.invocation != '0' * 32)
        elif (evidence.active, evidence.substate) == ('inactive', 'dead'):
            valid = (evidence.main_pid == 0
                     and evidence.control_group in ('', self.cgroup)
                     and (evidence.invocation == '' or re.fullmatch(
                         r'[0-9a-f]{32}', evidence.invocation)))
        else:
            valid = False
        if not valid:
            raise SupervisionError('Unsettled or mismatched unit state')
