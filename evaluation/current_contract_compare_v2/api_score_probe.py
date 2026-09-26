"""Run scripted minimal decisions through isolated product API, without network."""
from __future__ import annotations

import json
import copy
import pathlib
import re
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from evaluation.current_contract_compare_v2.preflight import CORPORA, HERE, fixture_runtime, data
from evaluation.current_contract_compare_v2.score import score_one, score_raw_one
from app.provider import ProviderResult


def scripted_payload(case: dict, request: dict, variant: str = "gold") -> dict:
    state_change = variant == "state_change"
    if case["expected_class"] == "no_conflict" and not state_change:
        return {"issues": []}
    claim = request["claims"][0]
    spans = {x["id"]: x for x in claim["allowed_evidence"]}
    conflict = case["expected_class"] == "conflict"
    evidence = []
    for item in case["minimum_sufficient_evidence_sets"][0]:
        span_id = f"fixture-span-{case['corpus_key']}-{item['chapter_number']}"
        span = spans[span_id]
        evidence.append({"chapter_id": span["chapter_id"], "span_id": span_id,
                         "relation": "contradicts" if conflict else "supports" if state_change else "context",
                         "sufficiency": "sufficient" if conflict or state_change else "insufficient",
                         "related_memory_ids": [x["id"] for x in request["memory"] if x["source_span_id"] == span_id]})
    temporal = {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"}
    if state_change:
        anchor = re.search(r"\d+点", claim["text"])
        temporal = {"claim_anchor": anchor.group(), "evidence_anchor": anchor.group(), "relation": "explicit_later_transition"}
    elif conflict and case["temporal_policy"] == "timeless_rule":
        temporal["relation"] = "timeless_rule"
    elif conflict:
        anchor = re.search(r"\d+点", claim["text"])
        if not anchor:
            raise RuntimeError("clock_anchor_missing")
        temporal = {"claim_anchor": anchor.group(), "evidence_anchor": anchor.group(), "relation": "explicit_overlap"}
    return {"issues": [{"claim_span_id": claim["id"], "status": "conflict" if conflict or state_change else "insufficient_evidence",
                        "nature": "confirmed_conflict" if conflict else "state_change" if state_change else "insufficient_evidence",
                        "category": case["decision_category"], "severity": "high" if conflict else "low",
                        "explanation": "The cited record requires this review decision.", "reasoning": case["label_reason"],
                        "temporal_basis": temporal, "evidence": evidence,
                        "evidence_chain": [{"span_id": x["span_id"], "role": "prior_state" if conflict else "current_context" if state_change else "missing_link"} for x in evidence],
                        "suggested_revision": None, "available_actions": [], "proposed_memory_change": None}]}


class ScriptedProvider:
    label = "compare-v2-scripted-offline"
    model_label = "compare-v2-no-model"
    available = True

    def __init__(self, case: dict, variant: str = "gold"):
        self.case = case
        self.variant = variant
        self.calls = 0
        self.requests = []
        self.raw_payloads = []

    def evaluate(self, request: dict) -> ProviderResult:
        self.calls += 1
        self.requests.append(request)
        payload = scripted_payload(self.case, request, self.variant)
        self.raw_payloads.append(copy.deepcopy(payload))
        return ProviderResult(payload, input_tokens=1, output_tokens=1, latency_ms=1)


def run_probe() -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    captured = {row["case_id"]: row["business_request"] for row in json.loads(
        (HERE / "actual-inputs.json").read_text(encoding="utf-8"))["rows"]}
    rows = []
    runs = [(case, "gold") for case in cases] + [(case, "state_change") for case in cases
                                                if case["expected_class"] == "no_conflict" and "state_change" in case["allowed_outcomes"]]
    for case, variant in runs:
        provider = ScriptedProvider(case, variant)
        with fixture_runtime(case["corpus_key"], provider, CORPORA) as runtime:
            from datetime import datetime, timezone
            with runtime.app.state.database.connection() as connection:
                runtime.app.state.database._insert_empty_author_context_zero(
                    connection, runtime.identity.project_id, datetime.now(timezone.utc).isoformat())
            pid = runtime.identity.project_id
            project = data(runtime.client.get(f"/api/projects/{pid}"))
            headers = {"Idempotency-Key": str(uuid.uuid4())}
            saved = data(runtime.client.patch(f"/api/projects/{pid}/drafts/{runtime.identity.draft_id}",
                                              json={"base_revision": project["current_draft"]["revision"],
                                                    "body": case["target_draft"]}, headers=headers))
            started = data(runtime.client.post(f"/api/projects/{pid}/checks", headers=headers,
                                               json={"draft_id": saved["id"], "draft_revision": saved["revision"]}))
            product = data(runtime.client.get(f"/api/projects/{pid}/checks/{started['run_id']}?include=issues,evidence,metrics"))
            actual_request = provider.requests[0]
            frozen_request = captured[case["case_id"]]
            def content_signature(request: dict) -> dict:
                return {"draft_body": request["draft"]["body"],
                        "claims": [{"text": claim["text"], "allowed_evidence": [
                            {key: span[key] for key in ("id", "chapter_id", "body", "prompt_excerpt")}
                            for span in claim["allowed_evidence"]]} for claim in request["claims"]],
                        "memory": [{key: row[key] for key in ("id", "memory_type", "subject", "predicate", "value", "source_span_id")}
                                   for row in request["memory"]],
                        "output_schema": request["output_schema"]}
            same_content = provider.calls == 1 and content_signature(actual_request) == content_signature(frozen_request)
            scored = score_one(case, product, actual_request)
            raw_scored = score_raw_one(case, provider.raw_payloads[0], actual_request)
            rows.append({"case_id": case["case_id"], "variant": variant, "status": product["status"],
                         "actual_business_content_equal_capture": same_content,
                         "business_request": actual_request,
                         "raw_first": provider.raw_payloads[0], "raw_first_score": raw_scored,
                         "raw_repair": None,
                         "final_product": product, "product": product,
                         "issue_count": len(product.get("issues", [])),
                         "issue_shape": [{"status": issue.get("status"), "classification": issue.get("classification"),
                                          "nature": issue.get("nature"), "temporal_basis_persisted": "temporal_basis" in issue}
                                         for issue in product.get("issues", [])],
                         "score": scored})
    return {"schema_version": "current-contract-compare-v2-api-score-probe",
            "case_count": len(rows), "fake_provider_calls": len(rows), "real_provider_calls": 0,
            "actual_content_equal_count": sum(x["actual_business_content_equal_capture"] for x in rows),
            "completed_count": sum(x["status"] == "completed" for x in rows),
            "machine_pass_count": sum(x["score"]["machine_result"] == "pass" for x in rows),
            "raw_first_machine_pass_count": sum(x["raw_first_score"]["machine_result"] == "pass" for x in rows),
            "semantic_pending_count": sum(x["score"]["semantic_result"] == "pending_manual_review" for x in rows),
            "rows": rows}


if __name__ == "__main__":
    result = run_probe()
    destination = HERE / "api-score-probe-results-v2.json"
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"case_count": result["case_count"], "completed": result["completed_count"],
                      "content_equal": result["actual_content_equal_count"], "machine_pass": result["machine_pass_count"]}, ensure_ascii=False))
