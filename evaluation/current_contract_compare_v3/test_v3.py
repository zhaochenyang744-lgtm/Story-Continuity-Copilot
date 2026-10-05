"""Focused V3 metadata, scorer, and create-only persistence tests."""
from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from evaluation.current_contract_compare_v3 import build, controls, run


class CompareV3Test(unittest.TestCase):
    def test_gold_is_deterministic_and_v2_preserved(self):
        saved = json.loads((run.HERE / "cases.json").read_text(encoding="utf-8"))
        self.assertEqual(build.build(), saved)
        self.assertEqual(len(saved["cases"]), 24)
        self.assertEqual(len(run.verify_v2(saved)), 3)
        badge = next(x for x in saved["cases"] if x["case_id"] == "ccv3-north_glass-world_rule-conflict")
        self.assertEqual(len(badge["minimum_sufficient_evidence_sets"][0]), 1)
        self.assertEqual(len(badge["recommended_context"]), 1)
        self.assertFalse(badge["requires_all_expected_evidence"])

    def test_category_gold_is_per_question(self):
        cases = json.loads((run.HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
        insuff = {x["category_axis"]: x for x in cases if x["expected_class"] == "insufficient_evidence"}
        self.assertEqual(len(insuff), 8)
        self.assertEqual(insuff["timeline"]["decision_category"], "relationship")
        self.assertEqual(insuff["relationship"]["decision_category"], "timeline")
        self.assertEqual(insuff["character_knowledge"]["decision_category"], "relationship")
        self.assertEqual(insuff["location_action"]["category_policy"], "manual_variant")
        self.assertEqual(insuff["location_action"]["category_candidates"], ["location_action", "relationship"])
        self.assertTrue(all(x["case_time_scope"]["draft"] == x["target_draft"] for x in cases))

    def test_saved_rescore_and_controls(self):
        summary, rows = run.analyze()
        self.assertEqual((summary["saved_record_count"], summary["raw_first_machine_pass"],
                          summary["final_machine_pass"], summary["new_api_runs"]), (26, 19, 19, 0))
        self.assertEqual(len(summary["category_delta_rows"]), 7)
        self.assertTrue(all(x["raw_repair"] is None for x in rows["rows"]))
        result = controls.controls()
        self.assertEqual((result["control_count"], result["passed_count"], result["real_provider_calls"]), (20, 20, 0))

    def test_create_only_and_first_failure_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(run, "HERE", pathlib.Path(directory)):
                first = run.reserve_run_dir("reserved")
                self.assertTrue(first.is_dir())
                with self.assertRaises(FileExistsError):
                    run.reserve_run_dir("reserved")
                with mock.patch.object(run, "analyze", side_effect=RuntimeError("intentional-test-failure")):
                    with self.assertRaises(RuntimeError):
                        run.execute("failure-control")
                failure = pathlib.Path(directory) / "runs/failure-control/first-failure.json"
                before = hashlib.sha256(failure.read_bytes()).hexdigest()
                with self.assertRaises(FileExistsError):
                    run.execute("failure-control")
                self.assertEqual(hashlib.sha256(failure.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
