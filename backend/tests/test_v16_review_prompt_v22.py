"""Continuity review v22: settle undecidable tensions quickly, and repair a self-contradicting gap.

On imported projects (Memory built by Flash, not fixtures) the v21 review often thought until the
16,000-token cap: an undated contradiction without a static_canon rule, a character contradicting
their own earlier statement, or an "only when" rule read as a requirement. v22 states how to settle
each. A V10 diagnostic rerun also hit one insufficient_evidence issue that marked its citation
sufficient; that self-contradiction now gets the bounded repair instead of failing the check.

Settling a tension as possible_conflict has the same failure mode from the other side: an unsure
model marks its own cited span insufficient, which the contract forbids for a conflict-status
nature. On imported projects that sank 3 of 4 checks of one case, so it is repairable too.
"""
from __future__ import annotations

import json
import unittest

from app.engine import ContinuityEngine
from app.provider import CONTINUITY_PROMPT_VERSION, ProviderResult, continuity_prompt


def data():
    body = "林默张开完好无缺的左手，五根手指都在。"
    evidence = "林默是港务局的年轻记录员，左手缺了一根小指。"
    return {"draft": {"id": "draft-v22", "revision": 1, "body": body},
            "claims": [{"id": "claim-v22", "text": body, "allowed_evidence": [
                {"id": "span-v22", "chapter_id": "chapter-v22", "body": evidence, "prompt_excerpt": evidence}]}],
            "memory": []}


def unsettled_answer(sufficiency):
    return {"claim_verdicts": [{"claim_span_id": "claim-v22", "verdict": "reviewed_issue", "basis": "两处手部描述相互矛盾，但没有共同时间可以确定。"}],
            "issues": [{"claim_span_id": "claim-v22", "status": "conflict", "nature": "possible_conflict",
                        "category": "attribute", "severity": "medium", "explanation": "两处手部描述相互矛盾，时间关系未知。",
                        "reasoning": "来源说缺一根小指，草稿说五指完好；没有共同时间或永久规则可以确定二者不能并存。",
                        "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
                        "evidence": [{"chapter_id": "chapter-v22", "span_id": "span-v22", "relation": "contradicts",
                                      "sufficiency": sufficiency, "related_memory_ids": []}],
                        "evidence_chain": [{"span_id": "span-v22", "role": "prior_state"}],
                        "suggested_revision": None, "available_actions": ["keep_intentional"], "proposed_memory_change": None}]}


def gap_answer(sufficiency):
    return {"claim_verdicts": [{"claim_span_id": "claim-v22", "verdict": "insufficient_evidence", "basis": "没有给出时间，无法确定两种手部状态同时成立。"}],
            "issues": [{"claim_span_id": "claim-v22", "status": "insufficient_evidence", "nature": "insufficient_evidence",
                        "category": "attribute", "severity": "medium", "explanation": "原文与草稿的手部状态无法确认是否同一时间。",
                        "reasoning": "来源说缺一根小指，草稿说五指完好；缺少说明两者时间关系的文本。",
                        "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
                        "evidence": [{"chapter_id": "chapter-v22", "span_id": "span-v22", "relation": "context",
                                      "sufficiency": sufficiency, "related_memory_ids": []}],
                        "evidence_chain": [{"span_id": "span-v22", "role": "missing_link"}],
                        "suggested_revision": None, "available_actions": [], "proposed_memory_change": None}]}


class Scripted:
    available = True
    continuity_contract_version = "v6"
    label = model_label = "v22-offline"

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def evaluate(self, request):
        self.requests.append(request)
        return ProviderResult(self.answers.pop(0), input_tokens=1, output_tokens=1)


class ReviewPromptV22Tests(unittest.TestCase):
    def test_prompt_settles_undated_self_contradicting_and_only_when_cases(self):
        rules = "\n".join(json.loads(continuity_prompt({**data(), "output_schema": {}}))["rules"])
        # The v22 rules stay in later versions; v24 adds the explicit missing-link wording.
        self.assertTrue(CONTINUITY_PROMPT_VERSION.startswith("continuity-review-v2"))
        self.assertIn("an undated contradiction that no shared time or static_canon rule proves", rules)
        self.assertIn("a character contradicting their own earlier unmarked statement", rules)
        self.assertIn("it does not require X whenever C holds", rules)

    def test_gap_that_marks_its_citation_sufficient_is_repaired_once(self):
        provider = Scripted(gap_answer("sufficient"), gap_answer("insufficient"))
        result = ContinuityEngine(provider).execute(data())
        self.assertEqual((result["status"], len(provider.requests)), ("completed", 2))
        self.assertEqual(provider.requests[1]["contract_repair"]["reason_code"], "insufficient_evidence_upgraded")
        self.assertEqual([issue["nature"] for issue in result["issues"]], ["insufficient_evidence"])

    def test_the_same_slip_after_repair_still_fails_closed(self):
        provider = Scripted(gap_answer("sufficient"), gap_answer("sufficient"))
        result = ContinuityEngine(provider).execute(data())
        self.assertEqual((result["status"], result["error_code"], len(provider.requests)), ("failed", "insufficient_evidence_upgraded", 2))

    def test_possible_conflict_citing_its_own_span_as_insufficient_is_repaired_once(self):
        provider = Scripted(unsettled_answer("insufficient"), unsettled_answer("sufficient"))
        result = ContinuityEngine(provider).execute(data())
        self.assertEqual((result["status"], len(provider.requests)), ("completed", 2))
        self.assertEqual(provider.requests[1]["contract_repair"]["reason_code"], "conflict_evidence_insufficient")
        self.assertEqual([issue["nature"] for issue in result["issues"]], ["possible_conflict"])

    def test_the_same_unsettled_slip_after_repair_still_fails_closed(self):
        provider = Scripted(unsettled_answer("insufficient"), unsettled_answer("insufficient"))
        result = ContinuityEngine(provider).execute(data())
        self.assertEqual((result["status"], result["error_code"], len(provider.requests)),
                         ("failed", "conflict_evidence_insufficient", 2))


if __name__ == "__main__":
    unittest.main()
