"""No-network score and asset checks for the seen comparison candidate."""
from __future__ import annotations

import collections
import json
import pathlib
import unittest

from evaluation.current_contract_compare_v1.score import score_one

HERE = pathlib.Path(__file__).resolve().parent


class CompareAssetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]

    def test_case_balance_lineage_and_exact_captured_source_content(self):
        self.assertEqual(len(self.cases), 24)
        self.assertEqual(dict(collections.Counter(x["expected_class"] for x in self.cases)),
                         {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8})
        self.assertEqual(len({(x["corpus_key"], x["axis_index"]) for x in self.cases}), 8)
        self.assertEqual(len({x["corpus_key"] for x in self.cases}), 4)
        self.assertGreaterEqual(sum(x["expected_class"] == "conflict" and len(x["expected_evidence"]) >= 2
                                    for x in self.cases), 4)
        self.assertGreaterEqual(sum(x["expected_class"] == "insufficient_evidence" and len(x["expected_evidence"]) >= 2
                                    for x in self.cases), 4)
        capture = json.loads((HERE / "actual-inputs.json").read_text(encoding="utf-8"))
        self.assertEqual((capture["required_evidence_present_count"], capture["real_provider_calls"]), (24, 0))
        for row in capture["rows"]:
            self.assertTrue(row["required_evidence_present"], row["case_id"])
        lineage = json.loads((HERE / "v8-lineage.json").read_text(encoding="utf-8"))
        self.assertEqual((lineage["old_case_count"], lineage["retained_byte_identical_count"]), (24, 0))

    def test_contract_and_actual_api_issue_shape_are_scored(self):
        contract = json.loads((HERE / "contract-probe-results.json").read_text(encoding="utf-8"))
        api = json.loads((HERE / "api-score-probe-results-v2.json").read_text(encoding="utf-8"))
        self.assertEqual((contract["validator_accepted"], contract["score_pass_count"]), (24, 24))
        self.assertEqual((api["completed_count"], api["actual_content_equal_count"], api["score_pass_count"]), (24, 24, 24))
        self.assertTrue(all(issue["status"] == "open" and not issue["temporal_basis_persisted"]
                            for row in api["rows"] for issue in row["issue_shape"]))

    def test_negative_controls_do_not_pass(self):
        conflict = next(x for x in self.cases if x["expected_class"] == "conflict")
        no_conflict = next(x for x in self.cases if x["expected_class"] == "no_conflict")
        insuff = next(x for x in self.cases if x["expected_class"] == "insufficient_evidence")
        self.assertEqual(score_one(no_conflict, {"status": "failed", "issues": []})["result"], "terminal_failure")
        self.assertEqual(score_one(no_conflict, {"status": "completed", "issues": [{"classification": "conflict"}]})["result"], "fail")
        self.assertEqual(score_one(conflict, {"status": "completed", "issues": [{"status": "open", "classification": "conflict",
            "nature": "possible_conflict"}]})["result"], "fail")
        self.assertEqual(score_one(insuff, {"status": "completed", "issues": [{"status": "open", "classification": "conflict",
            "nature": "confirmed_conflict"}]})["result"], "fail")


if __name__ == "__main__":
    unittest.main()
