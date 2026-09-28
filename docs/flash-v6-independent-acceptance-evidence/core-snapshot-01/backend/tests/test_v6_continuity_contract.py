"""Small offline V6 contract controls; no Provider HTTP or product database."""
from __future__ import annotations

import copy
import json
import pathlib
import unittest

from app.engine import ContinuityContractValidationError, ContinuityEngine
from app.provider import ProviderResult


ROOT = pathlib.Path(__file__).resolve().parents[2]
LIVE = ROOT / "evaluation/current_flash_v5/runs/flash-v5-20260927-01/cases"


class V6Provider:
    continuity_contract_version = "v6"
    available = True

    def __init__(self, answers=()):
        self.answers = iter(answers)
        self.calls = 0

    def evaluate(self, request):
        self.calls += 1
        return ProviderResult(next(self.answers))


def captured(number: str):
    case = LIVE / number
    request = json.loads((case / "requests/01.json").read_text(encoding="utf-8"))["business_request"]
    raw = json.loads((case / "evaluations/01.json").read_text(encoding="utf-8"))["parsed_business_json"]
    return request, raw


def verdict(raw, request, kind="reviewed_issue"):
    raw = copy.deepcopy(raw)
    raw["claim_verdicts"] = [{"claim_span_id": request["claims"][0]["id"], "verdict": kind,
                              "basis": "The selected sources were checked for this specific claim."}]
    return raw


class V6ContinuityContractTests(unittest.TestCase):
    def test_rule_premise_and_direct_fact_keep_distinct_relations(self):
        request, raw = captured("04")
        raw = verdict(raw, request)
        raw["issues"][0]["evidence"][1]["relation"] = "context"
        issue = ContinuityEngine(V6Provider()).validate(raw, request)[0]
        self.assertEqual([item["relation"] for item in issue["evidence"]], ["contradicts", "context"])

    def test_all_supports_cannot_be_confirmed_conflict(self):
        request, raw = captured("04")
        raw = verdict(raw, request)
        for item in raw["issues"][0]["evidence"]:
            item["relation"] = "supports"
        with self.assertRaisesRegex(ContinuityContractValidationError, "conflict_evidence_not_direct"):
            ContinuityEngine(V6Provider()).validate(raw, request)

    def test_unselected_span_and_bad_chapter_still_fail(self):
        request, raw = captured("22")
        raw = verdict(raw, request)
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            ContinuityEngine(V6Provider()).validate(raw, request)
        request, raw = captured("04")
        raw = verdict(raw, request)
        raw["issues"][0]["evidence"][0]["chapter_id"] = "wrong-chapter"
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            ContinuityEngine(V6Provider()).validate(raw, request)

    def test_timeless_rule_requires_rule_source_cited_by_same_issue(self):
        request, raw = captured("04")
        raw = verdict(raw, request)
        issue = raw["issues"][0]
        rule_source = issue["evidence"][1]
        rule_memory = next(item for item in request["memory"] if item["source_span_id"] == rule_source["span_id"])
        issue["temporal_basis"] = {"claim_anchor": None, "evidence_anchor": None, "relation": "timeless_rule"}
        issue["evidence"] = [issue["evidence"][0]]
        issue["evidence"][0]["related_memory_ids"] = [rule_memory["id"]]
        issue["evidence_chain"] = [{"span_id": issue["evidence"][0]["span_id"], "role": "current_context"}]
        with self.assertRaisesRegex(ContinuityContractValidationError, "timeless_rule_unproven"):
            ContinuityEngine(V6Provider()).validate(raw, request)
        rule_source["relation"] = "context"
        rule_source["related_memory_ids"] = [rule_memory["id"]]
        issue["evidence"].append(rule_source)
        issue["evidence_chain"].append({"span_id": rule_source["span_id"], "role": "prior_state"})
        self.assertEqual(ContinuityEngine(V6Provider()).validate(raw, request)[0]["nature"], "confirmed_conflict")

    def test_cross_source_memory_association_remains_valid(self):
        request, raw = captured("04")
        raw = verdict(raw, request)
        raw["issues"][0]["evidence"][1]["relation"] = "context"
        other_memory = next(item for item in request["memory"] if item["source_span_id"] == raw["issues"][0]["evidence"][1]["span_id"])
        raw["issues"][0]["evidence"][0]["related_memory_ids"] = [other_memory["id"]]
        self.assertEqual(ContinuityEngine(V6Provider()).validate(raw, request)[0]["nature"], "confirmed_conflict")

    def test_unknown_time_does_not_upgrade_to_confirmed(self):
        request, raw = captured("04")
        raw = verdict(raw, request)
        raw["issues"][0]["evidence"][1]["relation"] = "context"
        raw["issues"][0]["temporal_basis"] = {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"}
        with self.assertRaisesRegex(ContinuityContractValidationError, "temporal_overlap_unproven"):
            ContinuityEngine(V6Provider()).validate(raw, request)

    def test_explained_empty_and_state_change_are_distinct(self):
        request, _ = captured("04")
        claim_id = request["claims"][0]["id"]
        empty = {"issues": [], "claim_verdicts": [{"claim_span_id": claim_id, "verdict": "no_issue",
                                                   "basis": "A newly written compatible event is not contradicted by prior material."}]}
        self.assertEqual(ContinuityEngine(V6Provider()).validate(empty, request), [])
        state_change = {"claim_span_id": claim_id, "status": "conflict", "nature": "state_change",
                        "category": "object_state", "severity": "low", "explanation": "A later compatible change.",
                        "reasoning": "The cited prior state and later written action can both hold.",
                        "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "explicit_later_transition"},
                        "evidence": [{"chapter_id": request["claims"][0]["allowed_evidence"][0]["chapter_id"],
                                      "span_id": request["claims"][0]["allowed_evidence"][0]["id"],
                                      "relation": "supports", "sufficiency": "sufficient", "related_memory_ids": []}],
                        "evidence_chain": [{"span_id": request["claims"][0]["allowed_evidence"][0]["id"], "role": "prior_state"}],
                        "suggested_revision": None, "available_actions": [], "proposed_memory_change": None}
        reviewed = {"issues": [state_change], "claim_verdicts": [{"claim_span_id": claim_id,
                     "verdict": "reviewed_issue", "basis": "The prior and later states form a compatible change."}]}
        self.assertEqual(ContinuityEngine(V6Provider()).validate(reviewed, request)[0]["nature"], "state_change")

    def test_per_batch_coverage_rejects_missing_duplicate_foreign_and_unhashable_ids(self):
        request, _ = captured("04")
        one = copy.deepcopy(request["claims"][0])
        second = {**one, "id": "claim-second", "text": "A compatible new scene occurred."}
        third = {**one, "id": "claim-third", "text": "A separate compatible scene occurred."}
        batch1 = {**request, "claims": [one, second]}
        batch2 = {**request, "claims": [third]}
        def row(claim_id):
            return {"claim_span_id": claim_id, "verdict": "no_issue", "basis": "Compatible new written event."}
        engine = ContinuityEngine(V6Provider())
        self.assertEqual(engine.validate({"issues": [], "claim_verdicts": [row(one["id"]), row(second["id"])]}, batch1), [])
        self.assertEqual(engine.validate({"issues": [], "claim_verdicts": [row(third["id"])]}, batch2), [])
        for rows in ([row(one["id"])], [row(one["id"]), row(one["id"])],
                     [row(one["id"]), row(third["id"])], [row(one["id"]), row([])]):
            with self.subTest(rows=rows), self.assertRaises(ContinuityContractValidationError):
                engine.validate({"issues": [], "claim_verdicts": rows}, batch1)
        with self.assertRaises(ContinuityContractValidationError):
            engine.validate({"issues": [{"claim_span_id": []}], "claim_verdicts": [row(one["id"]), row(second["id"])]}, batch1)

    def test_malformed_memory_id_is_a_controlled_binding_error(self):
        request, raw = captured("04")
        raw = verdict(raw, request)
        raw["issues"][0]["evidence"][1]["relation"] = "context"
        raw["issues"][0]["evidence"][0]["related_memory_ids"] = [[]]
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            ContinuityEngine(V6Provider()).validate(raw, request)

    def test_repair_cannot_silently_drop_an_issue(self):
        request, _ = captured("04")
        first = {"issues": [], "claim_verdicts": []}
        second = {"issues": [], "claim_verdicts": []}
        provider = V6Provider([first, second])
        result = ContinuityEngine(provider).execute({"claims": request["claims"], "memory": request["memory"], "draft": request["draft"]})
        self.assertEqual((provider.calls, result["status"], result["error_code"]),
                         (2, "failed", "claim_verdicts_incomplete"))


if __name__ == "__main__":
    unittest.main()
