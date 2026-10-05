"""A batch whose last, non-thinking answer still runs out of output is retried one claim at a time.

Live, 2026-10-03 (v1.5.1, rolled back): the 灰港回声 demo draft is four short claims in one batch.
Thinking filled the 16,000-token cap at high and at medium effort, and the final non-thinking
answer (2,000 tokens) overflowed too, because v24 now reports the draft's missing link as an
insufficient_evidence issue where v22 stayed silent. Two checks in a row failed as
output_truncated at 34,000 output tokens. The claims are now retried one at a time instead.
"""
from __future__ import annotations

import unittest

from app.engine import ContinuityEngine
from app.provider import ProviderInvalidJson, ProviderResult


class TruncatedBatchProvider:
    available = True
    label = model_label = "truncation-split"
    allows_legacy_continuity_contract = True

    def __init__(self, truncate_single: set[str] | None = None):
        self.calls: list[list[str]] = []
        self.truncate_single = truncate_single or set()

    def evaluate(self, request):
        ids = [claim["id"] for claim in request["claims"]]
        self.calls.append(ids)
        if len(ids) > 1 or ids[0] in self.truncate_single:
            raise ProviderInvalidJson(1000, 34000, 0.3, 150000, "length")
        claim = request["claims"][0]
        evidence = claim["allowed_evidence"][0]
        issues = [] if claim["id"] != "claim-1" else [{
            "claim_span_id": claim["id"], "status": "conflict", "category": "object_state", "severity": "high",
            "explanation": "bounded test evidence",
            "evidence": [{"chapter_id": evidence["chapter_id"], "span_id": evidence["id"], "relation": "contradicts",
                          "sufficiency": "sufficient", "related_memory_ids": []}]}]
        return ProviderResult({"issues": issues}, input_tokens=100, output_tokens=50, latency_ms=900, cost_cny=0.01)


def data() -> dict:
    claims = [{"id": f"claim-{index}", "text": f"短句{index}。",
               "allowed_evidence": [{"id": f"span-{index}", "chapter_id": f"chapter-{index}", "body": f"原文{index}。"}]}
              for index in range(1, 5)]
    return {"draft": {"id": "draft-split", "revision": 1, "body": ""}, "claims": claims, "memory": []}


class TruncationSplitTests(unittest.TestCase):
    def test_a_truncated_multi_claim_batch_is_retried_claim_by_claim(self):
        provider = TruncatedBatchProvider()
        result = ContinuityEngine(provider).execute(data())
        self.assertEqual(provider.calls[0], ["claim-1", "claim-2", "claim-3", "claim-4"])
        self.assertEqual(sorted(provider.calls[1:]), [["claim-1"], ["claim-2"], ["claim-3"], ["claim-4"]])
        self.assertEqual(result["status"], "completed")
        self.assertEqual([issue["claim_span_id"] for issue in result["issues"]], ["claim-1"])
        self.assertEqual(result["undecided_claim_count"], 0)
        # The truncated dispatch is billed and stays in the totals.
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (1400, 34200))

    def test_a_single_claim_that_still_overflows_is_undecided(self):
        provider = TruncatedBatchProvider(truncate_single={"claim-4"})
        result = ContinuityEngine(provider).execute(data())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["undecided_claims"], [{"claim_span_id": "claim-4", "error_code": "output_truncated"}])

    def test_every_claim_overflowing_still_fails_the_check(self):
        provider = TruncatedBatchProvider(truncate_single={"claim-1", "claim-2", "claim-3", "claim-4"})
        result = ContinuityEngine(provider).execute(data())
        self.assertEqual((result["status"], result["error_code"]), ("failed", "output_truncated"))


if __name__ == "__main__":
    unittest.main()
