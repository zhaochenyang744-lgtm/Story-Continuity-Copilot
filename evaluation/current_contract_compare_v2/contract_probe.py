"""No-network representability probe using actual captured business requests."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"

from app.engine import ContinuityEngine


def probe() -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    captured = json.loads((HERE / "actual-inputs.json").read_text(encoding="utf-8"))
    by_id = {row["case_id"]: row for row in captured["rows"]}
    engine = ContinuityEngine(object())
    rows = []
    for case in cases:
        request = by_id[case["case_id"]]["business_request"]
        claims = request["claims"]
        if len(claims) != 1 or claims[0]["text"] != case["target_draft"]:
            raise RuntimeError("target_claim_not_bound:" + case["case_id"])
        span_map = {x["id"]: x for x in claims[0]["allowed_evidence"]}
        evidence = []
        for item in case["minimum_sufficient_evidence_sets"][0]:
            span_id = f"fixture-span-{case['corpus_key']}-{item['chapter_number']}"
            span = span_map.get(span_id)
            if not span:
                raise RuntimeError("required_source_not_in_business_request:" + case["case_id"])
            evidence.append({"chapter_id": span["chapter_id"], "span_id": span_id,
                             "relation": "contradicts" if case["expected_class"] == "conflict" else "context",
                             "sufficiency": "sufficient" if case["expected_class"] == "conflict" else "insufficient",
                             "related_memory_ids": [x["id"] for x in request["memory"] if x["source_span_id"] == span_id]})
        if case["expected_class"] == "no_conflict":
            payload = {"issues": []}
        else:
            policy = case["temporal_policy"]
            temporal = {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"}
            if case["expected_class"] == "conflict" and policy == "timeless_rule":
                temporal["relation"] = "timeless_rule"
            elif case["expected_class"] == "conflict" and policy == "same_explicit_time":
                anchor = re.search(r"\d+点", claims[0]["text"])
                if not anchor or not any(anchor.group() in span_map[x["span_id"]]["prompt_excerpt"] for x in evidence):
                    raise RuntimeError("clock_anchor_not_bound:" + case["case_id"])
                temporal = {"claim_anchor": anchor.group(), "evidence_anchor": anchor.group(), "relation": "explicit_overlap"}
            issue = {"claim_span_id": claims[0]["id"],
                     "status": "conflict" if case["expected_class"] == "conflict" else "insufficient_evidence",
                     "nature": "confirmed_conflict" if case["expected_class"] == "conflict" else "insufficient_evidence",
                     "category": case["decision_category"],
                     "severity": "high" if case["expected_class"] == "conflict" else "low",
                     "explanation": "The cited record requires this review decision.",
                     "reasoning": case["label_reason"], "temporal_basis": temporal,
                     "evidence": evidence,
                     "evidence_chain": [{"span_id": x["span_id"],
                                         "role": "prior_state" if case["expected_class"] == "conflict" else "missing_link"} for x in evidence],
                     "suggested_revision": None, "available_actions": [], "proposed_memory_change": None}
            payload = {"issues": [issue]}
        try:
            validated = engine.validate(payload, request)
            api_issues = [{**item, "status": "open", "classification": item["status"],
                           "claim_text": case["target_draft"]} for item in validated]
            rows.append({"case_id": case["case_id"], "validator": "accepted",
                         "api_issue_shape": [{"status": x["status"], "classification": x["classification"],
                                              "nature": x.get("nature"), "has_temporal_basis": "temporal_basis" in x} for x in api_issues]})
        except ValueError as error:
            rows.append({"case_id": case["case_id"], "validator": str(error)})
    return {"schema_version": "current-contract-compare-v2-contract-probe",
            "real_provider_calls": 0, "database_connections": 0,
            "case_count": len(rows), "validator_accepted": sum(x["validator"] == "accepted" for x in rows),
            "rows": rows}


if __name__ == "__main__":
    destination = HERE / "contract-probe-results.json"
    result = probe()
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"cases": result["case_count"], "validator_accepted": result["validator_accepted"],
                      "output": str(destination)}, ensure_ascii=False))
