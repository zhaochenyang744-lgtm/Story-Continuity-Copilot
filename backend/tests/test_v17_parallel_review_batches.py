"""Review batches of one check are dispatched in parallel when the provider declares a concurrency.

Production, 2026-09-30, release v22-0696e52: an 816-character chapter became 36 claims and its
batches ran one after another for about four minutes. Batches are independent requests, so running
several at once changes wall-clock time, not what any batch is asked. Everything the run reports
still follows claim order, and a provider without the attribute keeps the old sequential order.
"""
from __future__ import annotations

import os
import threading
import time
import unittest
from contextvars import ContextVar
from unittest.mock import patch

from app.engine import ContinuityEngine
from app.provider import DeepSeekProvider, ProviderFailure, ProviderResult

from tests.test_v17_partial_review_results import Poisoned, data

CLAIMS = 150
_caller: ContextVar[str | None] = ContextVar("v17_parallel_caller", default=None)


class Slow(Poisoned):
    """Poisoned, but each dispatch takes a moment and the peak number in flight is recorded."""

    def __init__(self, bad_claim_id=None, concurrency=4, delay=0.05):
        super().__init__(bad_claim_id)
        self.continuity_batch_concurrency = concurrency
        self.delay, self.lock, self.active, self.peak, self.threads, self.seen_caller = delay, threading.Lock(), 0, 0, set(), set()

    def evaluate(self, request):
        with self.lock:
            self.active += 1; self.peak = max(self.peak, self.active)
            self.threads.add(threading.get_ident()); self.seen_caller.add(_caller.get())
        try:
            time.sleep(self.delay)
            return super().evaluate(request)
        finally:
            with self.lock:
                self.active -= 1


class ParallelBatchTests(unittest.TestCase):
    def setUp(self):
        self.payload = data(CLAIMS)
        batches = ContinuityEngine(Poisoned(None))._batches(self.payload)
        self.assertGreater(len(batches), 4, "the fixture must span several batches to test anything")

    def test_batches_overlap_up_to_the_declared_concurrency_and_no_further(self):
        provider = Slow(concurrency=3)
        result = ContinuityEngine(provider).execute(self.payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(provider.peak, 3)

    def test_parallel_results_match_the_sequential_run_in_claim_order(self):
        sequential = ContinuityEngine(Poisoned("claim-v17-149")).execute(self.payload)
        parallel = ContinuityEngine(Slow("claim-v17-149", delay=0.01)).execute(self.payload)
        for key in ("status", "issues", "undecided_claims", "retrieval_traces", "input_tokens", "output_tokens"):
            self.assertEqual(parallel[key], sequential[key], key)
        self.assertEqual([row["claim_span_id"] for row in parallel["undecided_claims"]], ["claim-v17-149"])

    def test_a_provider_without_the_attribute_stays_on_the_calling_thread(self):
        provider = Slow(concurrency=None, delay=0)
        ContinuityEngine(provider).execute(self.payload)
        self.assertEqual((provider.peak, provider.threads), (1, {threading.get_ident()}))

    def test_the_callers_context_reaches_every_parallel_dispatch(self):
        # The usage reservation, the dispatch guard and the shared thinking effort are context variables.
        provider = Slow(delay=0.01)
        token = _caller.set("reservation-v17")
        try:
            ContinuityEngine(provider).execute(self.payload)
        finally:
            _caller.reset(token)
        self.assertEqual(provider.seen_caller, {"reservation-v17"})
        self.assertGreater(len(provider.threads - {threading.get_ident()}), 1)

    def test_a_failure_stops_dispatching_and_still_counts_what_was_spent(self):
        class FailsOnce(Slow):
            def evaluate(self, request):
                if request["claims"][0]["id"] == first_of_third_batch:
                    raise ProviderFailure()
                return super().evaluate(request)

        first_of_third_batch = ContinuityEngine(Poisoned(None))._batches(self.payload)[2]["claims"][0]["id"]
        provider = FailsOnce(delay=0.02)
        result = ContinuityEngine(provider).execute(self.payload)
        self.assertEqual((result["status"], result["error_code"]), ("failed", "provider_error"))
        dispatched = len(provider.requests)
        self.assertLess(dispatched, len(ContinuityEngine(Poisoned(None))._batches(self.payload)))
        # A plain provider failure leaves usage known; every answered dispatch cost one token each way.
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (dispatched, dispatched))

    def test_budget_pause_in_one_batch_pauses_the_run(self):
        class Expensive(Slow):
            def evaluate(self, request):
                answer = super().evaluate(request)
                return ProviderResult(answer.payload, input_tokens=1, output_tokens=10**9)

        result = ContinuityEngine(Expensive(delay=0.01)).execute(self.payload)
        self.assertEqual(result["status"], "budget_paused")


class ConcurrencySettingTests(unittest.TestCase):
    def concurrency(self, value):
        env = {} if value is None else {"CONTINUITY_REVIEW_CONCURRENCY": value}
        with patch.dict(os.environ, env, clear=True):
            return DeepSeekProvider().continuity_batch_concurrency

    def test_off_unless_the_deployment_sets_it(self):
        self.assertEqual(self.concurrency(None), 1)

    def test_parsed_and_clamped(self):
        self.assertEqual([self.concurrency(value) for value in ("4", "0", "-3", "99", "four", "")], [4, 1, 1, 8, 1, 1])


if __name__ == "__main__":
    unittest.main()
