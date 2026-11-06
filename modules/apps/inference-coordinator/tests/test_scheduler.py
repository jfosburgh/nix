"""Offline tests: no network, services, GPU, models, or third-party dependencies."""
import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.scheduler import Backend, Rejected, Scheduler, State


class FakeLifecycle:
    def __init__(self, name, world):
        self.name, self.world = name, world
        self.loading = None
        self.releasing = None
        self.failure = None

    async def prepare(self, operation):
        self.world['events'].append(('load', self.name, operation))
        assert self.world['resident'] in (None, self.name), 'Overlapping load!'
        self.world['resident'] = self.name
        if self.loading:
            entered, proceed = self.loading
            entered.set()
            await proceed.wait()
        if self.failure == 'load':
            raise RuntimeError('load failed')

    async def release(self):
        self.world['events'].append(('release', self.name))
        if self.releasing:
            entered, proceed = self.releasing
            entered.set()
            await proceed.wait()
        if self.failure == 'release':
            raise RuntimeError('release uncertain')
        if self.world['resident'] == self.name:
            self.world['resident'] = None


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.world = {'events': [], 'resident': None}
        self.adapters = {key: FakeLifecycle(key, self.world) for key in ('strata', 'ollama', 'third')}
        async def gate(backend, operation):
            self.world['events'].append(('memory', backend.id))
        self.scheduler = Scheduler([
            Backend(key, priority, frozenset({'narsil-gpu'}), self.adapters[key])
            for priority, key in enumerate(self.adapters)
        ], memory_gate=gate, lifecycle_timeout=1, inference_timeout=1,
            max_queue=8, max_queue_bytes=100)
        await self.scheduler.reconcile()
        self.scheduler.resume()
        self.world['events'].clear()
        self.jobs = []

    async def asyncTearDown(self):
        # Consume intentionally failed jobs, without suppressing test assertions.
        for job in self.jobs:
            if job.result.done() and not job.result.cancelled():
                job.result.exception()
            elif not job.result.done():
                job.result.cancel()

    def submit(self, backend, name, *, execute=None, size=1, timeout=300):
        async def run():
            self.assertEqual(self.world['resident'], backend)
            self.world['events'].append(('run', name))
            return name
        job = self.scheduler.submit(backend, name, size, execute or run, queue_timeout=timeout)
        self.jobs.append(job)
        return job

    async def finish(self):
        while await self.scheduler.run_next():
            pass

    def runs(self):
        return [event[1] for event in self.world['events'] if event[0] == 'run']

    async def test_fifo_and_strict_priority(self):
        for backend, name in [('ollama', 'X'), ('strata', 'A'), ('ollama', 'Y'), ('strata', 'B')]:
            self.submit(backend, name)
        await self.finish()
        self.assertEqual(self.runs(), ['A', 'B', 'X', 'Y'])

    async def test_continuous_priority_starves_lower_queue(self):
        low = self.submit('ollama', 'X')
        for n in range(10):
            self.submit('strata', str(n))
            await self.scheduler.run_next()
            self.assertFalse(low.result.done())
        await self.finish()
        self.assertEqual(await low.result, 'X')

    async def test_load_commit_boundary_rechecks_priority(self):
        entered, proceed = asyncio.Event(), asyncio.Event()
        self.adapters['ollama'].loading = (entered, proceed)
        self.submit('ollama', 'X')
        worker = asyncio.create_task(self.scheduler.run_next())
        await entered.wait()
        self.submit('strata', 'A')
        proceed.set()
        await worker
        self.assertEqual(self.runs(), ['A'])
        await self.finish()
        self.assertEqual(self.runs(), ['A', 'X'])

    async def test_priority_rechecked_after_release_before_loading(self):
        self.submit('third', 'first')
        await self.finish()
        entered, proceed = asyncio.Event(), asyncio.Event()
        self.adapters['third'].releasing = (entered, proceed)
        self.submit('ollama', 'X')
        worker = asyncio.create_task(self.scheduler.run_next())
        await entered.wait()
        self.submit('strata', 'A')
        proceed.set()
        await worker
        self.assertEqual(self.runs(), ['first', 'A'])
        self.assertNotIn(('load', 'ollama', 'X'), self.world['events'])
        await self.finish()
        self.assertEqual(self.runs(), ['first', 'A', 'X'])

    async def test_maintenance_during_load_prevents_inference(self):
        entered, proceed = asyncio.Event(), asyncio.Event()
        self.adapters['ollama'].loading = (entered, proceed)
        job = self.submit('ollama', 'X')
        worker = asyncio.create_task(self.scheduler.run_next())
        await entered.wait()
        drain = asyncio.create_task(self.scheduler.drain())
        await asyncio.sleep(0)
        proceed.set()
        await asyncio.gather(worker, drain)
        with self.assertRaises(Rejected):
            await job.result
        self.assertEqual(self.runs(), [])
        self.assertIsNone(self.world['resident'])
        self.scheduler.resume()

    async def test_active_job_is_not_preempted_and_holds_lease_to_completion(self):
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def stream():
            entered.set()  # response headers/first chunk are not completion
            await proceed.wait()
            self.world['events'].append(('run', 'X'))
        self.submit('ollama', 'X', execute=stream)
        worker = asyncio.create_task(self.scheduler.run_next())
        await entered.wait()
        self.submit('strata', 'A')
        second_worker = asyncio.create_task(self.scheduler.run_next())
        await asyncio.sleep(0)
        self.assertEqual(self.scheduler.lease, 'narsil-gpu')
        self.assertEqual(self.scheduler.state, State.RUNNING)
        self.assertEqual(self.world['resident'], 'ollama')
        self.assertFalse(second_worker.done())
        proceed.set()
        await asyncio.gather(worker, second_worker)
        self.assertEqual(self.runs(), ['X', 'A'])

    async def test_cancelled_queued_job_does_not_load(self):
        job = self.submit('ollama', 'X')
        job.result.cancel()
        self.assertFalse(await self.scheduler.run_next())
        self.assertEqual(self.world['events'], [])

    async def test_cancel_during_load_never_executes(self):
        entered, proceed = asyncio.Event(), asyncio.Event()
        self.adapters['ollama'].loading = (entered, proceed)
        job = self.submit('ollama', 'X')
        worker = asyncio.create_task(self.scheduler.run_next())
        await entered.wait()
        job.result.cancel()
        proceed.set()
        await worker
        self.assertEqual(self.runs(), [])
        self.submit('strata', 'A')
        await self.finish()
        self.assertEqual(self.runs(), ['A'])

    async def test_active_disconnect_verifies_release(self):
        entered = asyncio.Event()
        async def stream():
            entered.set()
            await asyncio.Event().wait()
        job = self.submit('ollama', 'X', execute=stream)
        worker = asyncio.create_task(self.scheduler.run_next())
        await entered.wait()
        job.result.cancel()
        await worker
        self.assertIsNone(self.world['resident'])
        self.assertIsNone(self.scheduler.lease)
        self.assertIsNone(self.scheduler.fault)

    async def test_uncertain_cancellation_faults_and_never_loads_other(self):
        entered = asyncio.Event()
        async def stream():
            entered.set()
            await asyncio.Event().wait()
        job = self.submit('ollama', 'X', execute=stream)
        worker = asyncio.create_task(self.scheduler.run_next())
        await entered.wait()
        self.adapters['ollama'].failure = 'release'
        next_job = self.submit('strata', 'A')
        job.result.cancel()
        await worker
        self.assertEqual(self.scheduler.state, State.FAULT)
        self.assertEqual(self.scheduler.owner, 'ollama')
        self.assertEqual(self.scheduler.lease, 'narsil-gpu')
        with self.assertRaises(Rejected):
            await next_job.result
        self.assertFalse(await self.scheduler.run_next())

    async def test_unload_failure_blocks_next_backend(self):
        self.submit('ollama', 'X')
        await self.finish()
        self.adapters['ollama'].failure = 'release'
        self.submit('strata', 'A')
        with self.assertRaises(RuntimeError):
            await self.scheduler.run_next()
        self.assertEqual(self.runs(), ['X'])
        self.assertEqual(self.scheduler.state, State.FAULT)

    async def test_failed_load_and_explicit_recovery(self):
        self.adapters['strata'].failure = 'load'
        self.submit('strata', 'A')
        with self.assertRaises(RuntimeError):
            await self.scheduler.run_next()
        with self.assertRaises(Rejected):
            self.scheduler.resume()
        self.adapters['strata'].failure = None
        await self.scheduler.reconcile()
        self.assertIsNone(self.world['resident'])
        self.scheduler.resume()
        self.submit('ollama', 'X')
        await self.finish()
        self.assertEqual(self.runs(), ['X'])

    async def test_queue_bytes_count_and_expiry(self):
        job = self.submit('ollama', 'X', size=100, timeout=0.001)
        with self.assertRaises(Rejected):
            self.submit('strata', 'too big')
        await asyncio.sleep(0.005)
        self.assertFalse(await self.scheduler.run_next())
        with self.assertRaises(Rejected):
            await job.result
        for n in range(8):
            self.submit('strata', str(n))
        with self.assertRaises(Rejected):
            self.submit('strata', 'too many')

    async def test_memory_gate_failure_is_closed(self):
        async def unavailable(*args):
            raise RuntimeError('telemetry unavailable')
        self.scheduler.memory_gate = unavailable
        self.submit('strata', 'A')
        with self.assertRaises(RuntimeError):
            await self.scheduler.run_next()
        self.assertEqual(self.world['resident'], None)
        self.assertEqual(self.scheduler.state, State.FAULT)

    async def test_drain_refuses_new_and_fails_queued_without_replay(self):
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def stream():
            entered.set()
            await proceed.wait()
        active = self.submit('strata', 'A', execute=stream)
        queued = self.submit('ollama', 'X')
        worker = asyncio.create_task(self.scheduler.run_next())
        await entered.wait()
        drain = asyncio.create_task(self.scheduler.drain())
        await asyncio.sleep(0)
        with self.assertRaises(Rejected):
            self.submit('strata', 'B')
        with self.assertRaises(Rejected):
            await queued.result
        self.assertFalse(drain.done())
        proceed.set()
        await asyncio.gather(worker, drain)
        await active.result
        self.assertIsNone(self.world['resident'])
        self.assertEqual(self.scheduler.state, State.IDLE)
        self.assertTrue(self.scheduler.maintenance)
        self.assertIn(('release', 'third'), self.world['events'])

    async def test_third_backend_and_opaque_payload(self):
        payload = b'\x00\xffbinary\r\n--multipart'
        async def binary():
            self.assertEqual(self.scheduler.owner, 'third')
            return payload
        job = self.submit('third', 'binary-upload', execute=binary, size=len(payload))
        self.submit('ollama', 'X')
        await self.finish()
        self.assertIs(await job.result, payload)

    async def test_inference_failure_is_not_replayed(self):
        calls = []
        async def broken():
            calls.append('partial output')
            raise RuntimeError('backend crashed')
        job = self.submit('strata', 'A', execute=broken)
        await self.finish()
        self.assertEqual(calls, ['partial output'])
        with self.assertRaises(Rejected):
            await job.result
        self.assertIsNone(self.world['resident'])

    async def test_inference_deadline_releases_backend(self):
        self.scheduler.inference_timeout = 0.005
        async def stalled():
            await asyncio.Event().wait()
        job = self.submit('ollama', 'X', execute=stalled)
        await self.scheduler.run_next()
        with self.assertRaises(Rejected):
            await job.result
        self.assertIsNone(self.world['resident'])

    async def test_lifecycle_deadline_faults(self):
        self.scheduler.lifecycle_timeout = 0.005
        self.adapters['ollama'].loading = (asyncio.Event(), asyncio.Event())
        self.submit('ollama', 'X')
        with self.assertRaises(TimeoutError):
            await self.scheduler.run_next()
        self.assertEqual(self.scheduler.state, State.FAULT)
        self.assertEqual(self.scheduler.owner, 'ollama')

    async def test_startup_must_reconcile_even_with_no_known_owner(self):
        other = Scheduler(list(self.scheduler.backends.values()), memory_gate=self.scheduler.memory_gate)
        with self.assertRaises(Rejected):
            other.resume()
        self.world['resident'] = 'ollama'  # orphan from previous coordinator
        await other.reconcile()
        self.assertIsNone(self.world['resident'])
        self.assertTrue(other.maintenance)
        other.resume()

    async def test_snapshot_filters_cancelled_jobs_and_never_exposes_operations(self):
        cancelled = self.submit('ollama', 'cancelled-secret', size=10)
        cancelled.result.cancel()
        live = self.submit('strata', 'private-operation', size=20)
        snapshot = self.scheduler.snapshot()
        self.assertEqual(snapshot['queues']['ollama']['length'], 0)
        self.assertEqual(snapshot['queues']['strata']['length'], 1)
        self.assertEqual(snapshot['queues']['strata']['bytes'], 20)
        self.assertGreaterEqual(snapshot['queues']['strata']['oldest_wait_seconds'], 0)
        self.assertNotIn('private-operation', str(snapshot))
        self.assertIsNone(snapshot['active_request_id'])
        self.assertIsNone(self.world['resident'])
        live.result.cancel()

    def test_unsupported_resource_policy_rejected(self):
        with self.assertRaises(ValueError):
            Scheduler([Backend('remote', 3, frozenset(), self.adapters['third'])],
                      memory_gate=self.scheduler.memory_gate)


if __name__ == '__main__':
    unittest.main()
