"""Fake persistent bus + real temporary journals; no installed service calls."""
import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dbus_next import Message, MessageFlag, MessageType, Variant
from coordinator.bus_identity import BusIdentity
from coordinator.job_journal import JobJournal
from coordinator.supervision import SupervisionError
from coordinator.systemd_jobs import DBUS, DBUS_PATH, MANAGER, PATH, INTERFACE, ManagerFence, SystemdJobSession

BUS = BusIdentity('a' * 32, ':1.99')
FENCE = ManagerFence(BUS, 123456, '262')


class FakeBus:
    def __init__(self):
        self.handler = None
        self.disconnected = asyncio.Event()
        self.calls = []
        self.job_id = 10
        self.marker = FENCE.units_load_usec
        self.owner = BUS.manager_owner
        self.guid = BUS.bus_id
        self.version = '262'
        self.mode = 'early'
        self.result = 'done'
        self.inventory = []
        self.on_mutation = None
        self.mutating = asyncio.Event()
        self.reply_sender = None

    async def connect(self):
        return self

    def add_message_handler(self, handler):
        self.handler = handler

    def remove_message_handler(self, handler):
        self.handler = None

    def disconnect(self):
        self.disconnected.set()

    async def wait_for_disconnect(self):
        await self.disconnected.wait()

    def signal(self, member, signature='', body=None, **fields):
        msg = Message(message_type=MessageType.SIGNAL, sender=BUS.manager_owner,
                      path=PATH, interface=INTERFACE, member=member,
                      signature=signature, body=body or [])
        for key, value in fields.items():
            setattr(msg, key, value)
        if self.handler:
            self.handler(msg)

    def events(self):
        path = f'{PATH}/job/{self.job_id}'
        self.signal('JobNew', 'uos', [self.job_id, path, 'ollama.service'])
        self.signal('JobRemoved', 'uoss', [self.job_id, path, 'ollama.service', self.result])

    async def call(self, msg):
        self.calls.append(msg)
        member = msg.member
        if member == 'GetId':
            signature, body = 's', [self.guid]
        elif member == 'GetNameOwner':
            signature, body = 's', [self.owner]
        elif member == 'Get':
            signature, body = 'v', [Variant('t', self.marker) if msg.body[1] == 'UnitsLoadTimestampMonotonic'
                                     else Variant('s', self.version)]
        elif member == 'ListJobs':
            signature, body = 'a(usssoo)', [self.inventory]
        elif member in ('StartUnit', 'StopUnit'):
            self.mutating.set()
            if self.on_mutation:
                self.on_mutation()
            if self.mode == 'timeout':
                await asyncio.sleep(60)
            if self.mode == 'early':
                self.events()
            elif self.mode == 'late':
                asyncio.get_running_loop().call_soon(self.events)
            elif self.mode == 'removed-only':
                self.signal('JobRemoved', 'uoss', [self.job_id, f'{PATH}/job/{self.job_id}', 'ollama.service', 'done'])
            elif self.mode == 'wrong-reply':
                self.events()
                self.job_id += 1
            elif self.mode == 'duplicate':
                self.events()
                self.events()
            elif self.mode == 'reload':
                self.events()
                self.marker += 1
            elif self.mode == 'disconnect':
                self.disconnect()
                await asyncio.sleep(0)
            signature, body = 'o', [f'{PATH}/job/{self.job_id}']
        else:
            signature, body = '', []
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN,
                               sender=self.reply_sender or msg.destination,
                               signature=signature, body=body)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-jobs-')
        self.addCleanup(self.temp.cleanup)
        Path(self.temp.name).chmod(0o700)
        self.path = str(Path(self.temp.name) / 'jobs')
        self.journal = self.make_journal().open(initialize=True)
        self.addCleanup(self.journal.close)
        self.bus = FakeBus()
        self.session = self.build()
        self.addAsyncCleanup(self.session.close)

    def make_journal(self):
        return JobJournal(self.path, unit='ollama.service', identity='deployment-test',
                          boot_id='b' * 32, bus_identity=BUS,
                          manager_load_usec=FENCE.units_load_usec, manager_version='262')

    def build(self, **kwargs):
        return SystemdJobSession(self.journal, expected=FENCE,
                                 bus_factory=lambda: self.bus, **kwargs)

    def mutations(self):
        return [c for c in self.bus.calls if c.member in ('StartUnit', 'StopUnit')]

    async def test_construction_no_io_explicit_open_subscribes_before_any_mutation(self):
        self.assertEqual(self.bus.calls, [])
        await self.session.open()
        self.assertEqual(self.mutations(), [])
        names = [m.member for m in self.bus.calls]
        self.assertLess(names.index('AddMatch'), names.index('Subscribe'))
        self.assertLess(names.index('Subscribe'), names.index('ListJobs'))
        for msg in self.bus.calls:
            self.assertTrue(msg.flags & MessageFlag.NO_AUTOSTART)
            if msg.destination != DBUS:
                self.assertEqual(msg.destination, BUS.manager_owner)
        self.assertFalse(any(c.member in ('GetAll', 'LoadUnit', 'RestartUnit') for c in self.bus.calls))

    async def test_early_and_late_signals_correlate_and_ack_is_explicit(self):
        await self.session.open()
        for number, mode in enumerate(('early', 'late')):
            self.bus.mode = mode
            self.bus.job_id += 1
            nonce = f'{number:032x}'
            self.bus.on_mutation = lambda: self.assertIsNotNone(self.journal.pending)
            result = await self.session.run('stop', nonce)
            self.assertTrue(result.completed)
            self.assertEqual(result.result, 'done')
            self.assertEqual(self.journal.pending.result, 'done')
            await self.session.acknowledge(result)
            self.assertIsNone(self.journal.pending)
        self.assertEqual(len(self.mutations()), 2)
        self.assertTrue(all(c.body == ['ollama.service', 'fail'] for c in self.mutations()))

    async def test_begin_commit_failure_never_submits(self):
        await self.session.open()
        with patch.object(self.journal, 'begin', side_effect=SupervisionError('private')):
            with self.assertRaisesRegex(SupervisionError, '^Job operation uncertain; explicit recovery required$'):
                await self.session.run('stop', '1' * 32)
        self.assertEqual(self.mutations(), [])

    async def test_submitted_commit_failure_leaves_unknown_intent_no_retry(self):
        await self.session.open()
        with patch.object(self.journal, 'submitted', side_effect=SupervisionError('private')):
            with self.assertRaises(SupervisionError):
                await self.session.run('stop', '1' * 32)
        self.assertIsNone(self.journal.pending.job_id)
        with self.assertRaises(SupervisionError):
            await self.session.run('stop', '2' * 32)
        self.assertEqual(len(self.mutations()), 1)

    async def test_timeout_cancellation_leave_intent_pending_and_fault(self):
        self.session.timeout = 0.05
        await self.session.open()
        self.bus.mode = 'timeout'
        with self.assertRaises(SupervisionError):
            await self.session.run('stop', '1' * 32)
        self.assertIsNotNone(self.journal.pending)
        with self.assertRaises(SupervisionError):
            await self.session.run('start', '2' * 32)
        self.assertEqual(len(self.mutations()), 1)

    async def test_cancel_then_late_completion_never_clears_uncertainty(self):
        await self.session.open()
        self.bus.mode = 'timeout'
        task = asyncio.create_task(self.session.run('stop', '1' * 32))
        await self.bus.mutating.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.bus.events()
        self.assertIsNone(self.journal.pending.result)
        with self.assertRaises(SupervisionError):
            await self.session.check()

    async def test_unknown_submission_reopen_refused_without_calls(self):
        self.journal.begin('stop', '1' * 32)
        self.journal.close()
        self.journal.open()
        with self.assertRaises(SupervisionError):
            await self.session.open()
        self.assertEqual(self.bus.calls, [])

    async def test_completed_unacknowledged_reopen_refused(self):
        await self.session.open()
        await self.session.run('stop', '1' * 32)
        await self.session.close()
        self.journal.close()
        self.journal.open()
        bus = FakeBus()
        other = SystemdJobSession(self.journal, expected=FENCE, bus_factory=lambda: bus)
        self.addAsyncCleanup(other.close)
        with self.assertRaises(SupervisionError):
            await other.open()
        self.assertEqual(bus.calls, [])

    async def test_wrong_reply_uncorrelated_duplicate_and_fence_change(self):
        # Each failure is permanent; fresh journal/session for each fixture.
        for number, mode in enumerate(('removed-only', 'wrong-reply', 'duplicate', 'reload', 'disconnect')):
            path = str(Path(self.temp.name) / str(number))
            journal = JobJournal(path, unit='ollama.service', identity='test', boot_id='b' * 32,
                                 bus_identity=BUS, manager_load_usec=FENCE.units_load_usec,
                                 manager_version='262')
            journal.open(initialize=True)
            bus = FakeBus()
            session = SystemdJobSession(journal, expected=FENCE, bus_factory=lambda: bus, timeout=0.1)
            try:
                await session.open()
                bus.mode = mode
                with self.subTest(mode=mode), self.assertRaises(SupervisionError):
                    await session.run('stop', '1' * 32)
                self.assertIsNotNone(journal.pending)
            finally:
                await session.close()
                journal.close()

    async def test_failed_result_never_acknowledged(self):
        await self.session.open()
        self.bus.result = 'failed'
        result = await self.session.run('stop', '1' * 32)
        self.assertEqual(result.result, 'failed')
        with self.assertRaises(SupervisionError):
            await self.session.acknowledge(result)
        self.assertEqual(self.journal.pending.result, 'failed')

    async def test_overlap_refused_no_second_job(self):
        await self.session.open()
        self.bus.mode = 'timeout'
        task = asyncio.create_task(self.session.run('stop', '1' * 32))
        await self.bus.mutating.wait()
        with self.assertRaises(SupervisionError):
            await self.session.run('start', '2' * 32)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(len(self.mutations()), 1)

    async def test_unexpected_idle_job_and_reload_signals_fault(self):
        await self.session.open()
        self.bus.signal('Reloading', 'b', [True])
        with self.assertRaises(SupervisionError):
            await self.session.run('stop', '1' * 32)
        self.assertEqual(self.mutations(), [])

    async def test_external_idle_job_faults_but_other_units_and_senders_do_not(self):
        await self.session.open()
        self.bus.signal('JobNew', 'uos', [1, f'{PATH}/job/1', 'other.service'])
        self.bus.signal('Reloading', 'b', [True], sender=':1.999')
        await self.session.check()
        self.bus.events()
        with self.assertRaises(SupervisionError):
            await self.session.check()

    async def test_owner_change_even_if_restored_faults(self):
        await self.session.open()
        self.bus.signal('NameOwnerChanged', 'sss', [MANAGER, ':1.99', ':1.100'],
                        sender=DBUS, path=DBUS_PATH, interface=DBUS)
        self.bus.owner = BUS.manager_owner
        with self.assertRaises(SupervisionError):
            await self.session.check()

    async def test_marker_change_without_signal_and_bus_restart_fault(self):
        await self.session.open()
        self.bus.marker += 1
        with self.assertRaises(SupervisionError):
            await self.session.check()
        self.bus.marker -= 1
        with self.assertRaises(SupervisionError):
            await self.session.check()

    async def test_initial_bus_marker_version_mismatch_no_mutation(self):
        for attribute, value in (('marker', 555), ('guid', 'c' * 32),
                                 ('owner', ':1.100'), ('version', '263')):
            bus = FakeBus()
            setattr(bus, attribute, value)
            session = SystemdJobSession(self.journal, expected=FENCE, bus_factory=lambda: bus)
            try:
                with self.subTest(attribute=attribute), self.assertRaises(SupervisionError):
                    await session.open()
                self.assertFalse(any(c.member in ('StartUnit', 'StopUnit') for c in bus.calls))
            finally:
                await session.close()

    async def test_existing_target_job_refused(self):
        self.bus.inventory = [[1, 'ollama.service', 'stop', 'running', f'{PATH}/job/1',
                               f'{PATH}/unit/ollama_2eservice']]
        with self.assertRaises(SupervisionError):
            await self.session.open()
        self.assertEqual(self.mutations(), [])

    async def test_invalid_reply_sender_no_fallback(self):
        self.bus.reply_sender = ':1.999'
        with self.assertRaises(SupervisionError):
            await self.session.open()
        self.assertEqual(self.mutations(), [])

    async def test_disconnect_faults_idle_session(self):
        await self.session.open()
        self.bus.disconnect()
        await asyncio.sleep(0)
        with self.assertRaises(SupervisionError):
            await self.session.check()

    async def test_unfenced_or_differently_fenced_journal_refused(self):
        old = JobJournal(str(Path(self.temp.name) / 'v2'), unit='ollama.service',
                         identity='test', boot_id='b' * 32, bus_identity=BUS)
        with self.assertRaises(SupervisionError):
            SystemdJobSession(old, expected=FENCE)
        with self.assertRaises(SupervisionError):
            SystemdJobSession(self.journal, expected=replace(FENCE, units_load_usec=999))
        self.journal.close()
        stale = JobJournal(self.path, unit='ollama.service', identity='deployment-test',
                           boot_id='b' * 32, bus_identity=BUS,
                           manager_load_usec=999, manager_version='262')
        with self.assertRaises(SupervisionError):
            stale.open()
        self.journal.open()
        self.assertIsNone(self.journal.pending)

    async def test_invalid_action_nonce_policy_before_mutation(self):
        await self.session.open()
        for action, nonce in (('restart', '1' * 32), ('stop', 'bad'), ('start', None)):
            with self.assertRaises(SupervisionError):
                await self.session.run(action, nonce)
        self.assertEqual(self.mutations(), [])
        for changes in (dict(units_load_usec=True), dict(version='263'), dict(bus=None)):
            with self.assertRaises(SupervisionError):
                replace(FENCE, **changes)


if __name__ == '__main__':
    unittest.main()
