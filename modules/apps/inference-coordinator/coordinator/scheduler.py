"""Single-event-loop, single-resource scheduler, independent of HTTP/protocols.

Adapters must finish execute only when upstream has stopped (not at headers).
release must stop any orphan work, unload ALL residency, and verify release;
returning normally is proof of release, including after execute cancellation.
Failures are never retried automatically. All lifecycle failures fail closed.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from typing import Awaitable, Callable, Protocol

from .diagnostics import event, failure


class Rejected(Exception):
    """Admission rejected; transport maps this to an explicit client error."""


class Fault(Exception):
    """Ownership is uncertain; operator reconciliation required."""


class State(str, Enum):
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    UNLOADING = "unloading"
    FAULT = "fault"


class Lifecycle(Protocol):
    async def prepare(self, operation: str) -> None: ...
    async def release(self) -> None: ...


@dataclass(frozen=True)
class Backend:
    id: str
    priority: int  # Lower numbers win. No implicit priority for new providers.
    resources: frozenset[str]
    lifecycle: Lifecycle


@dataclass(eq=False)
class Job:
    backend: str
    operation: str
    body_bytes: int
    queue_deadline: float
    execute: Callable[[], Awaitable[object]]
    result: asyncio.Future
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    enqueued_at: float = field(default_factory=time.monotonic)


class Scheduler:
    def __init__(self, backends: list[Backend], *,
                 memory_gate: Callable[[Backend, str], Awaitable[None]],
                 max_queue: int = 32, max_queue_bytes: int = 32 * 1024 * 1024,
                 lifecycle_timeout: float = 120, inference_timeout: float = 3600):
        if not backends or len({b.id for b in backends}) != len(backends):
            raise ValueError("Backend IDs must be nonempty and unique")
        if any(not b.id or b.resources != frozenset({"narsil-gpu"}) for b in backends):
            raise ValueError("Only explicit exclusive narsil-gpu claims are supported")
        if min(max_queue, max_queue_bytes, lifecycle_timeout, inference_timeout) <= 0:
            raise ValueError("Limits must be positive")
        self.backends = {b.id: b for b in backends}
        self.queues: dict[str, deque[Job]] = {b.id: deque() for b in backends}
        self.order = sorted(self.backends, key=lambda key: self.backends[key].priority)
        self.memory_gate = memory_gate
        self.max_queue, self.max_queue_bytes = max_queue, max_queue_bytes
        self.lifecycle_timeout, self.inference_timeout = lifecycle_timeout, inference_timeout
        self.state = State.IDLE
        self.owner: str | None = None
        self.lease: str | None = None
        self.maintenance = True  # Startup must reconcile before admissions.
        self.reconciled = False
        self.fault: str | None = None
        self.active: Job | None = None
        self._worker = asyncio.Lock()

    def _prune(self) -> None:
        now = time.monotonic()
        for key, queue in self.queues.items():
            live = deque()
            for job in queue:
                if job.result.done():
                    event('queued_request_removed', request_id=job.request_id, backend=key,
                          cancelled=job.result.cancelled())
                    continue
                if job.queue_deadline <= now:
                    event('queue_expired', request_id=job.request_id, backend=key,
                          waited_seconds=round(now-job.enqueued_at, 3))
                    job.result.set_exception(Rejected("Queue deadline exceeded"))
                else:
                    live.append(job)
            self.queues[key] = live

    def snapshot(self) -> dict:
        """Non-loading, prompt/operation/body-free status for authenticated callers."""
        now = time.monotonic()
        queues = {}
        for key, queue in self.queues.items():
            live = [job for job in queue if not job.result.done() and job.queue_deadline > now]
            queues[key] = {
                'length': len(live),
                'bytes': sum(job.body_bytes for job in live),
                'oldest_wait_seconds': round(max((now - job.enqueued_at for job in live), default=0), 3),
            }
        return {'state': self.state.value, 'owner': self.owner, 'lease': self.lease,
                'maintenance': self.maintenance, 'reconciled': self.reconciled,
                'fault': self.fault, 'queues': queues,
                'active_request_id': self.active.request_id if self.active else None}

    def expire_queued(self) -> None:
        """Transport housekeeping may call this while inference is active."""
        self._prune()

    def submit(self, backend: str, operation: str, body_bytes: int,
               execute: Callable[[], Awaitable[object]], *, queue_timeout: float = 300) -> Job:
        # This method never yields: queue insertion is atomic on the owning loop.
        if self.maintenance or self.fault:
            raise Rejected("Coordinator unavailable; retry later")
        if backend not in self.backends or body_bytes < 0 or queue_timeout <= 0:
            raise Rejected("Invalid admission metadata")
        self._prune()
        jobs = [job for queue in self.queues.values() for job in queue]
        if len(jobs) >= self.max_queue or sum(j.body_bytes for j in jobs) + body_bytes > self.max_queue_bytes:
            raise Rejected("Queue capacity exceeded")
        job = Job(backend, operation, body_bytes, time.monotonic() + queue_timeout,
                  execute, asyncio.get_running_loop().create_future())
        self.queues[backend].append(job)
        event('request_queued', request_id=job.request_id, backend=backend,
              body_bytes=body_bytes, queue_length=len(self.queues[backend]))
        return job

    def _next(self) -> Job | None:
        self._prune()
        return next((self.queues[key][0] for key in self.order if self.queues[key]), None)

    def _fail_queued(self, reason: str) -> None:
        for queue in self.queues.values():
            while queue:
                job = queue.popleft()
                if not job.result.done():
                    job.result.set_exception(Rejected(reason))

    def _fault(self, exc: BaseException) -> None:
        failure('scheduler_fault', exc, owner=self.owner,
                request_id=self.active.request_id if self.active else None,
                hint='Restart inference-coordinator.service or reconcile before resuming')
        self.reconciled = False
        self.fault = type(exc).__name__  # Do not retain potentially sensitive exception text.
        self.state = State.FAULT
        self.maintenance = True
        self._fail_queued("Coordinator fault; ownership requires reconciliation")

    async def _bounded(self, action: Awaitable) -> object:
        return await asyncio.wait_for(action, self.lifecycle_timeout)

    async def _release_backend(self, backend) -> None:
        started = time.monotonic()
        event('owner_release_begin', backend=backend.id)
        await self._bounded(backend.lifecycle.release())
        event('owner_release_complete', backend=backend.id,
              elapsed_seconds=round(time.monotonic()-started, 3))

    async def _release_owner(self) -> None:
        if self.owner is not None:
            self.state = State.UNLOADING
            await self._release_backend(self.backends[self.owner])
            self.owner = None
        self.lease = None
        self.state = State.IDLE

    async def reconcile(self) -> None:
        """Startup/recovery: stop orphans and verify every registered owner empty."""
        self.maintenance = True
        self._fail_queued("Coordinator reconciling; requests are not replayed")
        async with self._worker:
            try:
                for backend in self.backends.values():
                    self.state = State.UNLOADING
                    await self._release_backend(backend)
                self.owner = self.lease = None
                self.fault = None
                self.reconciled = True
                self.state = State.IDLE
            except BaseException as exc:
                self._fault(exc)
                raise
        # Remain in maintenance until explicitly resumed.

    def resume(self) -> None:
        if not self.reconciled or self.fault or self._worker.locked() or self.owner or self.lease:
            raise Rejected("Cannot resume without idle verified ownership")
        self.maintenance = False

    async def drain(self) -> None:
        """Reject queued/new work; finish active inference, then verify release.

        Callers must apply a total drain deadline. Cancellation fails closed.
        """
        self.maintenance = True
        self._fail_queued("Coordinator draining; requests are not replayed")
        async with self._worker:
            try:
                # Iterate registry, not hardcoded provider names; catch orphan residency too.
                for backend in self.backends.values():
                    self.state = State.UNLOADING
                    await self._release_backend(backend)
                self.owner = self.lease = None
                self.state = State.IDLE
            except BaseException as exc:
                self._fault(exc)
                raise

    async def run_next(self) -> bool:
        """Drive one inference. The embedding service supplies the wakeup loop.

        Queue selection, transition reservation and inference commitment are on
        one event loop under _worker. No await between final selection and pop.
        Jobs remain queued during load, enabling cancellation and priority recheck.
        """
        async with self._worker:
            if self.maintenance or self.fault:
                return False
            try:
                while not self.maintenance:
                    job = self._next()
                    if job is None:
                        return False
                    if self.owner != job.backend:
                        await self._release_owner()
                        # Priority may have changed while releasing the previous owner.
                        if self.maintenance:
                            return False
                        job = self._next()
                        if job is None:
                            return False
                        self.owner = job.backend
                        self.lease = "narsil-gpu"
                    self.state = State.LOADING
                    started = time.monotonic()
                    event('backend_prepare_begin', request_id=job.request_id, backend=job.backend)
                    await self._bounded(self.memory_gate(self.backends[job.backend], job.operation))
                    await self._bounded(self.backends[job.backend].lifecycle.prepare(job.operation))
                    event('backend_prepare_complete', request_id=job.request_id, backend=job.backend,
                          elapsed_seconds=round(time.monotonic()-started, 3))
                    self.state = State.READY
                    # Loading is not inference commitment. Honor arrivals/disconnects.
                    if self.maintenance:
                        return False
                    if self._next() is not job:
                        continue
                    self.queues[job.backend].popleft()
                    self.active = job
                    self.state = State.RUNNING
                    started = time.monotonic()
                    event('inference_begin', request_id=job.request_id, backend=job.backend,
                          queued_seconds=round(started-job.enqueued_at, 3))
                    task = asyncio.create_task(job.execute())
                    def disconnect(future: asyncio.Future) -> None:
                        if future.cancelled():
                            task.cancel()
                    job.result.add_done_callback(disconnect)
                    try:
                        value = await asyncio.wait_for(task, self.inference_timeout)
                    except BaseException as exc:
                        if isinstance(exc, asyncio.CancelledError) and job.result.cancelled():
                            event('inference_cancelled', request_id=job.request_id, backend=job.backend,
                                  elapsed_seconds=round(time.monotonic()-started, 3))
                        else:
                            failure('inference_interrupted', exc, request_id=job.request_id, backend=job.backend,
                                    elapsed_seconds=round(time.monotonic()-started, 3))
                        # A closed HTTP connection alone is NOT release confirmation.
                        # Adapter release must prove upstream stopped, or we fault.
                        try:
                            await self._release_owner()
                        except BaseException as release_exc:
                            self._fault(release_exc)
                        if not job.result.done():
                            job.result.set_exception(Rejected("Inference stopped; not replayed"))
                        if isinstance(exc, asyncio.CancelledError) and not job.result.cancelled():
                            raise
                    else:
                        event('inference_complete', request_id=job.request_id, backend=job.backend,
                              elapsed_seconds=round(time.monotonic()-started, 3))
                        if not job.result.done():
                            job.result.set_result(value)
                        self.state = State.READY
                    finally:
                        job.result.remove_done_callback(disconnect)
                        self.active = None
                    return True
                return False
            except BaseException as exc:
                self._fault(exc)
                raise
