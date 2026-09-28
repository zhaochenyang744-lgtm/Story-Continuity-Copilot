"""Bounded V6 preparation and scorer checks; no Provider HTTP."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from evaluation.current_flash_v6 import live_guard, run
from evaluation.current_flash_v6.build_cases import build
from evaluation.current_flash_v6.inputs import InputContract
from evaluation.current_flash_v6.score import score_final, score_raw

ROOT = pathlib.Path(__file__).resolve().parents[2]
PREP = ROOT / "evaluation/current_flash_v6/runs/prep-v6-02"
OLD_LIVE = ROOT / "evaluation/current_flash_v5/runs/flash-v5-20260927-01"


def saved_request(number: int) -> dict:
    path = PREP / "cases" / f"{number:02d}" / "requests/01.json"
    return json.loads(path.read_text(encoding="utf-8"))["business_request"]


class V6OfflineTests(unittest.TestCase):
    def test_34_saved_api_inputs_have_no_provider_dispatch(self):
        cases = build()["cases"]
        summary = json.loads((PREP / "summary.json").read_text(encoding="utf-8"))
        workspace = json.loads((PREP / "workspace-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((len(cases), summary["logical_cases_finished"], workspace["database_count"]), (34, 34, 34))
        self.assertEqual((summary["post_attempt_start_records"], summary["models_get_start_records"]), (0, 0))
        for index in range(1, 35):
            folder = PREP / "cases" / f"{index:02d}"
            self.assertTrue((folder / "requests/01.json").is_file())
            self.assertTrue((folder / "input-audit/01.json").is_file())
            self.assertEqual(json.loads((folder / "case-finish.json").read_text(encoding="utf-8"))["status"], "completed")

    def test_lens_unselected_span_is_memory_only(self):
        request = saved_request(25)
        labels = {item["label"] for item in request["claims"][0]["allowed_evidence"]}
        self.assertEqual(labels, {"L1", "L2", "L4"})
        self.assertNotIn("fixture-span-v6_lens-3", {item["id"] for item in request["claims"][0]["allowed_evidence"]})
        self.assertIn("fixture-span-v6_lens-3", {item["source_span_id"] for item in request["memory"]})

    def test_new_control_draft_and_memory_set_bind_to_database(self):
        case = build()["cases"][24]
        contract = InputContract()
        binding = json.loads((PREP / "cases/25/runtime-binding.json").read_text(encoding="utf-8"))
        contract.bind_runtime(case["case_id"], binding)
        request = saved_request(25)
        self.assertEqual(contract(case, request)["selected_memory_count"], 4)
        wrong = copy.deepcopy(request)
        wrong["draft"]["revision"] += 1
        with self.assertRaisesRegex(RuntimeError, "draft_id_or_revision"):
            contract(case, wrong)
        missing = copy.deepcopy(request)
        missing["memory"].pop()
        with self.assertRaisesRegex(RuntimeError, "selected_memory_set_drift"):
            contract(case, missing)

    def test_mixed_joint_source_roles_pass_without_relabeling(self):
        case = build()["cases"][3]
        request = saved_request(4)
        raw = json.loads((OLD_LIVE / "cases/04/evaluations/01.json").read_text(encoding="utf-8"))["parsed_business_json"]
        raw["issues"][0]["claim_span_id"] = request["claims"][0]["id"]
        raw["issues"][0]["evidence"][1]["relation"] = "context"
        raw["claim_verdicts"] = [{"claim_span_id": request["claims"][0]["id"],
                                  "verdict": "reviewed_issue", "basis": "The rule and observed state jointly refute readiness."}]
        self.assertEqual(score_raw(case, raw, request)["machine_result"], "pass")
        for item in raw["issues"][0]["evidence"]:
            item["relation"] = "supports"
        self.assertEqual(score_raw(case, raw, request)["machine_result"], "fail")

    def test_kinship_rule_and_named_twin_fact_are_joint_roles(self):
        case = build()["cases"][12]
        request = saved_request(13)
        raw = json.loads((OLD_LIVE / "cases/13/evaluations/01.json").read_text(encoding="utf-8"))["parsed_business_json"]
        issue = raw["issues"][0]
        issue["claim_span_id"] = request["claims"][0]["id"]
        for item in issue["evidence"]:
            if item["span_id"] == "fixture-span-orchard_restoration-1":
                item["relation"] = "context"
        raw["claim_verdicts"] = [{"claim_span_id": request["claims"][0]["id"],
                                  "verdict": "reviewed_issue", "basis": "The kinship rule and named twins jointly establish incompatibility."}]
        self.assertEqual(score_raw(case, raw, request)["machine_result"], "pass")
        rule = next(item for item in issue["evidence"] if item["span_id"] == "fixture-span-orchard_restoration-1")
        rule["relation"] = "contradicts"
        self.assertIn("premise_mislabeled_direct_contradiction", score_raw(case, raw, request)["errors"])

    def test_silent_empty_does_not_pass_insufficient_case(self):
        case = build()["cases"][30]
        request = saved_request(31)
        raw = {"issues": [], "claim_verdicts": [{"claim_span_id": request["claims"][0]["id"],
               "verdict": "no_issue", "basis": "The register is silent."}]}
        self.assertIn("required_issue_missing", score_raw(case, raw, request)["errors"])

    def test_companion_manual_category_is_a_closed_set(self):
        case = build()["cases"][31]
        request = saved_request(32)
        claim = request["claims"][0]
        source = claim["allowed_evidence"][0]
        issue = {"claim_span_id": claim["id"], "status": "insufficient_evidence", "nature": "insufficient_evidence",
                 "category": "character_knowledge", "severity": "medium", "explanation": "The log omits the companion's name.",
                 "reasoning": "The source leaves the companion unnamed, so the story fact remains unknown.",
                 "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
                 "evidence": [{"chapter_id": source["chapter_id"], "span_id": source["id"],
                               "relation": "context", "sufficiency": "insufficient", "related_memory_ids": []}],
                 "evidence_chain": [{"span_id": source["id"], "role": "missing_link"}],
                 "suggested_revision": None, "available_actions": [], "proposed_memory_change": None}
        raw = {"issues": [issue], "claim_verdicts": [{"claim_span_id": claim["id"],
               "verdict": "insufficient_evidence", "basis": "The named companion is absent from the record."}]}
        self.assertIn("category_mismatch", score_raw(case, raw, request)["errors"])
        issue["category"] = "location_action"
        self.assertEqual(score_raw(case, raw, request)["machine_result"], "pass")

    def test_terminal_failure_and_supported_old_final_are_distinct(self):
        case = build()["cases"][6]
        folder = OLD_LIVE / "cases/07"
        old_request = json.loads((folder / "requests/01.json").read_text(encoding="utf-8"))["business_request"]
        product = json.loads((folder / "final-product.json").read_text(encoding="utf-8"))
        self.assertEqual(score_final(case, product, old_request)["machine_result"], "pass")
        self.assertEqual(score_final(case, {"status": "failed", "issues": []}, old_request)["machine_result"], "terminal_failure")

    def test_occupied_workspace_identity_rejected_before_run_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            result_dir, workspace = root / "runs", root / "artifacts"
            workspace.mkdir()
            (workspace / "prep-v6-occupied").mkdir()
            with patch.object(run, "RESULTS", result_dir), patch.object(run, "WORKSPACES", workspace):
                with self.assertRaises(FileExistsError):
                    run.reserve("prep-v6-occupied")
            self.assertFalse(result_dir.exists())

    def test_live_guard_rejects_changed_dependency_before_product_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            here = root / "evaluation/current_flash_v6"
            here.mkdir(parents=True)
            dependency = root / "backend/app/engine.py"
            dependency.parent.mkdir(parents=True)
            dependency.write_text("changed", encoding="utf-8")
            manifest = here / "frozen-inputs.json"
            manifest.write_text(json.dumps({"source_hashes": {"backend/app/engine.py": "0" * 64}}), encoding="utf-8")
            manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            with patch.object(live_guard, "ROOT", root), patch.object(live_guard, "HERE", here), patch.object(live_guard, "MANIFEST", manifest):
                with self.assertRaisesRegex(RuntimeError, "v6_frozen_hash_mismatch:backend/app/engine.py"):
                    live_guard.verify("flash-v6-test", manifest_sha)
                (here / "runs/flash-v6-test").mkdir(parents=True)
                with self.assertRaises(FileExistsError):
                    live_guard.verify("flash-v6-test", "wrong-manifest-hash")


if __name__ == "__main__":
    unittest.main()
