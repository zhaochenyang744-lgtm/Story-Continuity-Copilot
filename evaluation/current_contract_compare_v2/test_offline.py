"""Bounded offline probes of case design and scorer failure modes."""
from __future__ import annotations

import collections
import copy
import json
import pathlib
import unittest

from evaluation.current_contract_compare_v2.score import score_one, score_raw_one

HERE = pathlib.Path(__file__).resolve().parent


class CompareV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
        cls.by_id = {x["case_id"]: x for x in cls.cases}
        cls.api = json.loads((HERE / "api-score-probe-results-v2.json").read_text(encoding="utf-8"))
        cls.runs = {(x["case_id"], x["variant"]): x for x in cls.api["rows"]}

    def row(self, category, label, variant="gold"):
        case = next(x for x in self.cases if x["decision_category"] == category and x["expected_class"] == label)
        return case, self.runs[(case["case_id"], variant)]

    def assert_rejected(self, case, row, mutate):
        product = copy.deepcopy(row["product"])
        request = copy.deepcopy(row["business_request"])
        mutate(product, request)
        self.assertNotEqual(score_one(case, product, request)["machine_result"], "pass")

    def test_case_balance_context_and_wording(self):
        self.assertEqual(len(self.cases), 24)
        self.assertEqual(dict(collections.Counter(x["expected_class"] for x in self.cases)),
                         {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8})
        self.assertEqual(len({(x["corpus_key"], x["axis_index"]) for x in self.cases}), 8)
        insuff = [x for x in self.cases if x["expected_class"] == "insufficient_evidence"]
        self.assertEqual(sum(bool(x["recommended_context"]) for x in insuff), 5)
        self.assertLess(sum("establish" in x["target_draft"] for x in insuff), 8)
        self.assertTrue(any("establish" in x["target_draft"] for x in self.cases if x["expected_class"] == "no_conflict"))
        for case in self.cases:
            self.assertTrue(case["time_scope"] and case["label_reason"] and case["lineage"]["v1_case_id"])
            self.assertTrue(case["minimum_sufficient_evidence_sets"])

    def test_offline_capture_contract_and_api(self):
        capture = json.loads((HERE / "actual-inputs.json").read_text(encoding="utf-8"))
        contract = json.loads((HERE / "contract-probe-results.json").read_text(encoding="utf-8"))
        self.assertEqual((capture["required_evidence_present_count"], capture["real_provider_calls"]), (24, 0))
        self.assertEqual(contract["validator_accepted"], 24)
        self.assertEqual((self.api["case_count"], self.api["completed_count"],
                          self.api["actual_content_equal_count"], self.api["machine_pass_count"],
                          self.api["raw_first_machine_pass_count"],
                          self.api["semantic_pending_count"], self.api["real_provider_calls"]),
                         (26, 26, 26, 26, 26, 26, 0))
        self.assertTrue(all(row["score"]["result"] == "pending_manual_review" for row in self.api["rows"]))

    def test_two_supported_state_change_controls_and_invalid_variants(self):
        for category in ("character_knowledge", "location_action"):
            case, row = self.row(category, "no_conflict", "state_change")
            self.assertEqual(score_one(case, row["product"], row["business_request"])["machine_result"], "pass")
            self.assert_rejected(case, row, lambda p, r: p["issues"][0].update(category="timeline"))
            self.assert_rejected(case, row, lambda p, r: p["issues"][0].update(nature="possible_conflict"))
            self.assert_rejected(case, row, lambda p, r: p["issues"][0]["evidence"][0].update(relation="contradicts"))
        case, row = self.row("location_action", "no_conflict", "state_change")
        product = copy.deepcopy(row["product"])
        optional = case["recommended_context"][0]
        source_id = f"fixture-span-{case['corpus_key']}-{optional['chapter_number']}"
        source = next(x for x in row["business_request"]["claims"][0]["allowed_evidence"] if x["id"] == source_id)
        issue = product["issues"][0]
        issue["evidence"].append({"id": "optional-prior", "span_id": source_id,
                                  "chapter_id": source["chapter_id"], "chapter_number": optional["chapter_number"],
                                  "excerpt": source["prompt_excerpt"], "excerpt_context": source["body"][:500],
                                  "source_revision": product["source_revision"], "related_memory_ids": [],
                                  "relation": "supports", "sufficiency": "sufficient"})
        issue["evidence_chain"].append({"evidence_id": "optional-prior", "role": "prior_state"})
        self.assertEqual(score_one(case, product, row["business_request"])["machine_result"], "pass")

    def test_negative_score_controls(self):
        conflict, row = self.row("world_rule", "conflict")
        self.assert_rejected(conflict, row, lambda p, r: p["issues"][0]["evidence"][0].update(chapter_id="wrong"))
        self.assert_rejected(conflict, row, lambda p, r: p["issues"][0]["evidence"][0].update(excerpt="tampered"))
        self.assert_rejected(conflict, row, lambda p, r: p["issues"][0].update(claim_span_id="wrong"))
        self.assert_rejected(conflict, row, lambda p, r: p["issues"][0].update(nature="possible_conflict"))
        self.assert_rejected(conflict, row, lambda p, r: p.update(status="failed", issues=[]))
        self.assert_rejected(conflict, row, lambda p, r: p["issues"][0]["evidence"][0].update(related_memory_ids=["wrong"]))
        def add_unrelated(p, r):
            source = next(x for x in r["claims"][0]["allowed_evidence"] if x["id"] not in
                          {e["span_id"] for e in p["issues"][0]["evidence"]})
            extra = copy.deepcopy(p["issues"][0]["evidence"][0])
            extra.update(id="extra", span_id=source["id"], chapter_id=source["chapter_id"],
                         excerpt=source["prompt_excerpt"], excerpt_context=source["body"][:500],
                         related_memory_ids=[])
            p["issues"][0]["evidence"].append(extra)
        self.assert_rejected(conflict, row, add_unrelated)
        insuff, row = self.row("object_state", "insufficient_evidence")
        self.assert_rejected(insuff, row, lambda p, r: p["issues"][0]["evidence"][0].update(relation="contradicts"))
        self.assert_rejected(insuff, row, lambda p, r: p["issues"][0].update(available_actions=["edit"]))
        regular, row = self.row("timeline", "no_conflict")
        self.assert_rejected(regular, row, lambda p, r: p.update(issues=[copy.deepcopy(self.row("timeline", "conflict")[1]["product"]["issues"][0])]))

    def test_raw_first_temporal_and_relation_controls(self):
        case, row = self.row("timeline", "conflict")
        raw = copy.deepcopy(row["raw_first"])
        raw["issues"][0]["temporal_basis"]["relation"] = "unknown"
        self.assertEqual(score_raw_one(case, raw, row["business_request"])["machine_result"], "fail")
        raw = copy.deepcopy(row["raw_first"])
        raw["issues"][0]["evidence"][0]["relation"] = "context"
        self.assertEqual(score_raw_one(case, raw, row["business_request"])["machine_result"], "fail")


if __name__ == "__main__":
    unittest.main()
