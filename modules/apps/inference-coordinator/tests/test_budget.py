"""Input accounting boundary tests with synthetic counts, never real token estimates."""
import asyncio
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.budget import (BudgetError, BudgetRequest, InputUsage,
                                UnsupportedInput, check_budget)


class FakeCounter:
    def __init__(self, usage):
        self.usage = usage
        self.requests = []

    async def count(self, request):
        self.requests.append(request)
        return self.usage


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    def request(self, *, output=1024, sequences=1):
        return BudgetRequest('small', '/api/chat', b'{"prompt":"private"}', 8192, output, sequences)

    async def test_exact_boundary_is_accepted_and_body_is_not_repr(self):
        counter = FakeCounter(InputUsage('small', 8192, (7168,)))
        request = self.request()
        await check_budget(counter, request, timeout=0.1)
        self.assertIs(counter.requests[0], request)
        self.assertNotIn('private', repr(request))

    async def test_input_plus_output_rejected_not_truncated(self):
        counter = FakeCounter(InputUsage('small', 8192, (7169,)))
        with self.assertRaises(BudgetError) as error:
            await check_budget(counter, self.request(), timeout=0.1)
        self.assertEqual(error.exception.status, 422)
        self.assertIn('not truncated', error.exception.message)
        self.assertEqual(counter.usage.tokens, (7169,))

    async def test_no_counter_fails_closed(self):
        with self.assertRaises(BudgetError) as error:
            await check_budget(None, self.request(), timeout=0.1)
        self.assertEqual(error.exception.status, 503)

    async def test_batches_checked_per_sequence_not_summed(self):
        counter = FakeCounter(InputUsage('small', 8192, (8000, 8000)))
        await check_budget(counter, self.request(output=0, sequences=2), timeout=0.1)
        counter.usage = InputUsage('small', 8192, (8000, 8193))
        with self.assertRaises(BudgetError) as error:
            await check_budget(counter, self.request(output=0, sequences=2), timeout=0.1)
        self.assertEqual(error.exception.status, 422)

    async def test_empty_embedding_batch_is_accounted_explicitly(self):
        await check_budget(FakeCounter(InputUsage('small', 8192, ())),
                           self.request(output=0, sequences=0), timeout=0.1)

    async def test_profile_sequence_and_count_mismatches_fail_closed(self):
        for usage in [InputUsage('different', 8192, (1,)), InputUsage('small', 4096, (1,)),
                      InputUsage('small', True, (1,)), InputUsage('small', 8192, (True,)),
                      InputUsage('small', 8192, (-1,)), InputUsage('small', 8192, (1.5,)),
                      InputUsage('small', 8192, ()), InputUsage('small', 8192, [1]), None]:
            with self.subTest(usage=usage), self.assertRaises(BudgetError) as error:
                await check_budget(FakeCounter(usage), self.request(), timeout=0.1)
            self.assertEqual(error.exception.status, 503)

    async def test_unknown_modalities_rejected_with_no_counter_details(self):
        class Counter:
            async def count(self, request):
                raise UnsupportedInput('private prompt and image bytes')
        with self.assertRaises(BudgetError) as error:
            await check_budget(Counter(), self.request(), timeout=0.1)
        self.assertEqual(error.exception.status, 422)
        self.assertNotIn('private', error.exception.message)

    async def test_counter_failure_sanitized(self):
        class Counter:
            async def count(self, request):
                raise RuntimeError('secret path/key/prompt')
        with self.assertRaises(BudgetError) as error:
            await check_budget(Counter(), self.request(), timeout=0.1)
        self.assertEqual(error.exception.status, 503)
        self.assertNotIn('secret', error.exception.message)

    async def test_deadline_cancels_accounting(self):
        cancelled = asyncio.Event()
        class Counter:
            async def count(self, request):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        with self.assertRaises(BudgetError) as error:
            await check_budget(Counter(), self.request(), timeout=0.005)
        self.assertEqual(error.exception.status, 503)
        self.assertTrue(cancelled.is_set())

    async def test_disconnect_cancellation_propagates(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()
        class Counter:
            async def count(self, request):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        task = asyncio.create_task(check_budget(Counter(), self.request(), timeout=10))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())


if __name__ == '__main__':
    unittest.main()
