"""Loopback Unix sockets and fake quiescence, never privileged service calls."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.supervision import SupervisionError
from coordinator.supervisor_rpc import SupervisorClient, SupervisorRPC


class RPCTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-rpc-')
        self.addCleanup(self.temp.cleanup)
        self.path = self.temp.name + '/socket'
        self.operation = AsyncMock()
        self.rpc = SupervisorRPC(backend='ollama', allowed_uid=os.geteuid(),
                                  transaction=self.operation, timeout=0.5)
        self.server = await asyncio.start_unix_server(self.rpc.handle, path=self.path, limit=1024)
        os.chmod(self.path, 0o660)
        self.client = SupervisorClient(self.path, backend='ollama', timeout=1, expected_uid=os.geteuid())
        self.addAsyncCleanup(self.cleanup)

    async def cleanup(self):
        self.server.close()
        await self.server.wait_closed()
        await self.rpc.aclose()

    async def test_success_exact_peer_and_one_operation(self):
        await self.client()
        self.operation.assert_awaited_once()

    async def test_wrong_client_uid_or_server_uid(self):
        self.rpc.uid = os.geteuid() + 1
        with self.assertRaises(SupervisionError):
            await self.client()
        self.operation.assert_not_awaited()
        self.client.uid = os.geteuid() + 1
        with self.assertRaises(SupervisionError):
            await self.client()
        self.operation.assert_not_awaited()

    async def test_failure_faults_no_automatic_retry(self):
        self.operation.side_effect = SupervisionError('private details')
        for _ in range(2):
            with self.assertRaisesRegex(SupervisionError, '^Supervisor quiescence unconfirmed$'):
                await self.client()
        self.operation.assert_awaited_once()

    async def test_timeout_faults_and_blocks_further_work(self):
        self.rpc.timeout = 0.02
        self.operation.side_effect = lambda: None
        async def slow():
            await asyncio.sleep(60)
        self.operation.side_effect = slow
        with self.assertRaises(SupervisionError):
            await self.client()
        self.operation.side_effect = None
        with self.assertRaises(SupervisionError):
            await self.client()
        self.operation.assert_awaited_once()

    async def test_cancelled_client_does_not_cancel_accepted_operation(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def waiting():
            entered.set()
            await finish.wait()
        self.operation.side_effect = waiting
        task = asyncio.create_task(self.client())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(SupervisionError):
            await self.client()  # Busy, not a duplicate operation.
        self.assertTrue(self.rpc._busy)
        finish.set()
        await self.rpc.aclose()
        self.operation.assert_awaited_once()
        self.assertFalse(self.rpc._faulted)

    async def test_unknown_fields_units_commands_and_oversize_rejected(self):
        for value in (dict(op='start', backend='ollama', nonce='1' * 32),
                      dict(op='quiesce', backend='other', nonce='1' * 32),
                      dict(op='quiesce', backend='ollama', nonce='1' * 32, unit='sshd.service'),
                      dict(op='quiesce', backend='ollama', nonce='bad'), {'command': 'shell'}):
            reader, writer = await asyncio.open_unix_connection(self.path)
            writer.write(json.dumps(value).encode() + b'\n')
            await writer.drain()
            self.assertEqual(await reader.read(), b'')
            writer.close()
            await writer.wait_closed()
        reader, writer = await asyncio.open_unix_connection(self.path)
        writer.write(b'x' * 2048 + b'\n')
        await writer.drain()
        self.assertEqual(await reader.read(), b'')
        writer.close()
        await writer.wait_closed()
        self.operation.assert_not_awaited()

    async def test_duplicate_keys_rejected(self):
        reader, writer = await asyncio.open_unix_connection(self.path)
        writer.write(b'{"op":"quiesce","op":"quiesce","backend":"ollama","nonce":"' + b'1' * 32 + b'"}\n')
        await writer.drain()
        self.assertEqual(await reader.read(), b'')
        writer.close()
        await writer.wait_closed()
        self.operation.assert_not_awaited()

    async def test_symlink_or_world_accessible_socket_refused(self):
        os.chmod(self.path, 0o666)
        with self.assertRaises(SupervisionError):
            await self.client()
        os.chmod(self.path, 0o660)
        link = self.temp.name + '/link'
        Path(link).symlink_to(self.path)
        with self.assertRaises(SupervisionError):
            await SupervisorClient(link, backend='ollama', timeout=1, expected_uid=os.geteuid())()
        self.operation.assert_not_awaited()

    async def test_forged_wrong_nonce_or_extra_response_refused(self):
        async def forged(reader, writer):
            request = json.loads(await reader.readline())
            writer.write(json.dumps(dict(ok=True, nonce='f' * 32)).encode() + b'\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        self.server.close()
        await self.server.wait_closed()
        Path(self.path).unlink(missing_ok=True)
        self.server = await asyncio.start_unix_server(forged, path=self.path)
        os.chmod(self.path, 0o660)
        with self.assertRaises(SupervisionError):
            await self.client()


if __name__ == '__main__':
    unittest.main()
