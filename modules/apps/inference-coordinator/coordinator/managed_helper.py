"""Managed UnitHelper assembly; no socket server, privileges or auto-start.

Explicitly supplied store deployment, inspector, journaled bus session and
mount-pinned population evidence are required. This is not yet helper packaging
or local-client isolation. All actors with raw API/device/unit access remain
trusted; operator pins must describe a reviewed lazy API-only deployment.
"""
import asyncio

from .deployment import StoreUnitDeployment
from .supervision import SupervisionError, UnitContract, UnitState
from .unit_policy import UnitSafetyPolicy


class ManagedUnitHelper:
    """Serialize snapshot/stop/start, refuse start without live verified stop.

    Each mutation uses a fsynced intent and correlated job completion. Stop
    additionally verifies inactive unit AND whole-cgroup emptiness before journal
    acknowledgement. Start requires that proof again; no recovered completion or
    newly constructed helper grants start authority. Readiness remains the outer
    ManagedQuiescence transaction's responsibility. No automatic retry/recovery.
    """
    def __init__(self, expected: UnitContract, *, deployment: StoreUnitDeployment,
                 session, inspector, population, service_type: str):
        if (type(expected) is not UnitContract or type(deployment) is not StoreUnitDeployment
                or expected.unit != deployment.unit or expected.identity != deployment.identity
                or expected.unit != session.unit or expected.unit != inspector.unit
                or inspector.expected_bus != session.expected.bus
                or expected.kill_mode != 'control-group' or expected.send_sigkill is not True
                or expected.restart != 'no' or expected.lazy_start is not True
                or expected.delegated is not False or expected.exclusive_control is not True
                or type(expected.stop_timeout) not in (int, float)
                or not 0 < expected.stop_timeout <= 86400 or not callable(population)):
            raise SupervisionError('Explicit matching managed helper dependencies required')
        timeout_usec = expected.stop_timeout * 1000000
        if int(timeout_usec) != timeout_usec:
            raise SupervisionError('Exact managed stop timeout required')
        self.policy = UnitSafetyPolicy(expected.unit, expected.cgroup, session.expected.bus,
                                       int(timeout_usec), service_type)
        self.expected, self.deployment = expected, deployment
        self.session, self.inspector, self.population = session, inspector, population
        self._lock = asyncio.Lock()
        self._stopped = False
        self._old_invocation = None

    async def _observe(self):
        await self.session.check()
        await self.deployment.check(self.session)
        evidence = await self.inspector.inspect()
        self.policy.check(evidence)
        await self.session.check()
        return UnitState(self.expected, evidence.active, evidence.substate, evidence.main_pid,
                         evidence.invocation, evidence.control_group,
                         self.session.journal.pending is not None)

    def _empty(self):
        value = self.population(self.expected.cgroup)
        if value is not False and value is not None:
            raise SupervisionError('Managed cgroup release not proven')

    async def snapshot(self):
        if self._lock.locked():
            raise SupervisionError('Managed helper busy')
        async with self._lock:
            return await self._observe()

    async def stop(self, nonce):
        if self._lock.locked():
            raise SupervisionError('Managed helper busy')
        async with self._lock:
            self._stopped = False
            try:
                before = await self._observe()
                if before.pending_job:
                    raise SupervisionError('Unresolved managed job')
                population = self.population(self.expected.cgroup)
                if (population is not True and population is not False and population is not None
                        or before.active == 'active' and population is not True):
                    raise SupervisionError('Managed cgroup evidence inconsistent')
                completion = await self.session.run('stop', nonce)
                if completion.result != 'done':
                    raise SupervisionError('Managed stop did not complete successfully')
                after = await self._observe()
                if after.active != 'inactive':
                    raise SupervisionError('Managed stop state unconfirmed')
                self._empty()
                await self.session.acknowledge(completion)
                self._old_invocation = before.invocation
                self._stopped = True
                return completion
            except BaseException:
                self._stopped = False
                raise

    async def start_lazy(self, nonce):
        if self._lock.locked():
            raise SupervisionError('Managed helper busy')
        async with self._lock:
            if not self._stopped:
                raise SupervisionError('Fresh verified managed stop required')
            self._stopped = False  # One attempt only, including cancellation.
            before = await self._observe()
            if before.pending_job or before.active != 'inactive':
                raise SupervisionError('Managed unit no longer stopped')
            self._empty()
            completion = await self.session.run('start', nonce)
            if completion.result != 'done':
                raise SupervisionError('Managed start did not complete successfully')
            after = await self._observe()
            if after.active != 'active' or after.invocation == self._old_invocation:
                raise SupervisionError('Managed new invocation unconfirmed')
            if self.population(self.expected.cgroup) is not True:
                raise SupervisionError('Managed active cgroup unavailable')
            await self.session.acknowledge(completion)
            return completion
