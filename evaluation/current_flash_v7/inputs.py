"""V7 same-run API request and isolated SQLite input binding."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib

from evaluation.current_flash_v5.inputs import InputContract as V5InputContract
from evaluation.current_flash_v5.journal import digest

from evaluation.current_flash_v7.build_cases import controls, corpus

ROOT = pathlib.Path(__file__).resolve().parents[2]
V2_CAPTURE = ROOT / "evaluation/current_contract_compare_v2/actual-inputs.json"


def fail(case_id: str, reason: str) -> None:
    raise RuntimeError("input_contract:" + case_id + ":" + reason)


class InputContract(V5InputContract):
    def __init__(self):
        super().__init__()
        self.control_matrix = controls()

    def __call__(self, case: dict, request: dict) -> dict:
        binding = self.runtime_binding(case, request)
        audit = self.comparison(case, request) if case["evaluation_kind"] == "preserved_v5_comparison" else self.new_control(case, request)
        return {**audit, **binding}

    def comparison(self, case: dict, request: dict) -> dict:
        case_id = case["case_id"]
        gold = self.gold[case_id]
        if request.get("draft", {}).get("body") != case["saved_draft"] or len(request.get("claims", [])) != 1 or request["claims"][0].get("text") != case["saved_draft"]:
            fail(case_id, "draft_or_claim_shape")
        output_schema = request.get("output_schema", {})
        if set(output_schema) != {"issues", "claim_verdicts"}:
            fail(case_id, "v6_output_schema_missing")
        captured = copy.deepcopy(self.capture[gold["lineage"]["v2_case_id"]])
        current = copy.deepcopy(request)
        current.pop("contract_repair", None)
        current.pop("output_schema", None)
        captured.pop("output_schema", None)
        current["claims"][0]["id"] = captured["claims"][0]["id"]
        if current != captured:
            fail(case_id, "historical_capture_content_drift_except_declared_v6_schema")
        selected = {x["id"] for x in request["claims"][0]["allowed_evidence"]}
        minimum = [{f"fixture-span-{case['corpus_key']}-{x['chapter_number']}" for x in group}
                   for group in gold["minimum_sufficient_evidence_sets"]]
        if not any(group <= selected for group in minimum):
            fail(case_id, "minimum_source_not_selected")
        return {"case_id": case_id, "family": "comparison", "evaluation_kind": case["evaluation_kind"],
                "status": "v2_capture_exact_except_claim_id_and_v6_output_schema",
                "historical_capture_sha256": hashlib.sha256(V2_CAPTURE.read_bytes()).hexdigest(),
                "same_run_request_sha256": digest(request), "selected_source_count": len(selected),
                "minimum_source_selected": True, "repair": bool(request.get("contract_repair"))}

    def new_control(self, case: dict, request: dict) -> dict:
        case_id = case["case_id"]
        fixture = self.control_matrix["fixtures"][case["fixture_key"]]
        bound = self.runtime[case_id]
        if (request.get("draft", {}).get("id") != bound["draft_id"] or
            request.get("draft", {}).get("revision") != bound["draft_revision"]):
            fail(case_id, "control_draft_id_or_revision_database_binding")
        if request.get("draft", {}).get("body") != case["saved_draft"] or len(request.get("claims", [])) != 1 or request["claims"][0].get("text") != case["saved_draft"]:
            fail(case_id, "control_draft_or_claim_shape")
        if set(request.get("output_schema", {})) != {"issues", "claim_verdicts"}:
            fail(case_id, "v6_output_schema_missing")
        selected = request["claims"][0]["allowed_evidence"]
        adapted_corpus = corpus(case["fixture_key"], fixture)
        source_by_label = {x["source_label"]: (x["chapter_number"], x) for x in adapted_corpus["chapters"]}
        found = []
        for span in selected:
            label = span.get("label")
            if label not in source_by_label:
                fail(case_id, "selected_unknown_control_source")
            number, source = source_by_label[label]
            if (span.get("id") != f"fixture-span-{case['corpus_key']}-{number}" or
                span.get("chapter_id") != f"fixture-chapter-{case['corpus_key']}-{number}" or
                span.get("body") != source["body"] or span.get("prompt_excerpt") != source["body"]):
                fail(case_id, "control_selected_source_body_binding")
            found.append(label)
        if set(found) != set(case["selected_source_labels"]) or len(found) != len(case["selected_source_labels"]):
            fail(case_id, "control_selected_source_set_drift")
        memories = request.get("memory", [])
        expected_memory_ids = {f"fixture-memory-{case['corpus_key']}-{index}" for index in range(1, len(adapted_corpus["memory"])+1)}
        if (not isinstance(memories, list) or len(memories) != len(expected_memory_ids) or
            {row.get("id") for row in memories if isinstance(row, dict)} != expected_memory_ids):
            fail(case_id, "control_selected_memory_set_drift")
        for row in memories:
            source_id = row.get("source_span_id")
            if source_id not in {f"fixture-span-{case['corpus_key']}-{i}" for i in range(1, len(adapted_corpus["chapters"])+1)}:
                fail(case_id, "control_memory_source_unknown")
            number = int(source_id.rsplit("-", 1)[1])
            if row.get("value") != adapted_corpus["chapters"][number-1]["body"]:
                fail(case_id, "control_memory_value_source_drift")
        return {"case_id": case_id, "family": "comparison", "evaluation_kind": case["evaluation_kind"],
                "status": "v6_control_source_set_and_body_bound", "control_ids": case["control_ids"],
                "same_run_request_sha256": digest(request), "selected_source_labels": sorted(found),
                "selected_memory_count": len(memories), "repair": bool(request.get("contract_repair"))}
