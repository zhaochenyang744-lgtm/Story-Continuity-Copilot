"""Separate first/raw-repair/final checks; semantic truth stays manual."""
from __future__ import annotations

import json
import pathlib

from evaluation.current_contract_compare_v3.score import score_one as score_continuity_final
from evaluation.current_contract_compare_v3.score import score_raw_one as score_continuity_raw

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLD = {x["case_id"]: x for x in json.loads((ROOT / "evaluation/current_contract_compare_v3/cases.json").read_text(encoding="utf-8"))["cases"]}


def _allowed(request: dict) -> set[tuple[str, str]]:
    layers = request.get("layers", {})
    written = layers.get("written", {})
    return ({("draft_claim", x["id"]) for x in written.get("draft_claims", [])} |
            {("source_span", x["id"]) for x in written.get("source_spans", [])} |
            {("memory_record", x["id"]) for x in layers.get("confirmed", {}).get("memory_records", [])} |
            {("author_context", x["id"]) for group in layers.get("planned", {}).values() for x in group})


def _citations(sources, allowed: set[tuple[str, str]], label: str) -> list[str]:
    if not isinstance(sources, list) or not sources:
        return [label + "_uncited"]
    return [label + "_unbound" for source in sources if not isinstance(source, dict) or
            (source.get("source_type"), source.get("source_id")) not in allowed]


def score_g02_raw(payload: dict, request: dict) -> dict:
    errors = []
    allowed = _allowed(request)
    if not isinstance(payload, dict):
        errors.append("raw_json_not_object")
    else:
        errors += _citations(payload.get("summary_sources"), allowed, "summary")
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            errors.append("raw_items_missing")
        else:
            for index, item in enumerate(items):
                errors += _citations(item.get("sources") if isinstance(item, dict) else None,
                                     allowed, f"item_{index}")
    return {"machine_result": "fail" if errors else "pass", "semantic_result": "not_reviewed" if errors else "pending_manual_review",
            "errors": errors, "scope": "citation_binding_only; item_and_summary_semantic_support_pending_manual_review",
            "source": "first_or_repair_model_business_json"}


def score_g02_final(product: dict, request: dict) -> dict:
    if product.get("status") != "completed":
        return {"result": "terminal_failure", "machine_result": "terminal_failure", "semantic_result": "not_reviewed",
                "errors": [product.get("error_code") or "run_not_completed"]}
    analysis = product.get("analysis") or {}
    allowed = _allowed(request)
    errors = _citations(analysis.get("summary_sources"), allowed, "final_summary")
    items = analysis.get("items")
    if not isinstance(items, list) or not items:
        errors.append("final_items_missing")
    else:
        for index, item in enumerate(items):
            errors += _citations(item.get("sources") if isinstance(item, dict) else None,
                                 allowed, f"final_item_{index}")
    machine = "fail" if errors else "pass"
    return {"result": "fail" if errors else "pending_manual_review", "machine_result": machine,
            "semantic_result": "not_reviewed" if errors else "pending_manual_review", "errors": errors,
            "scope": "citation_binding_only; each_item_and_summary_semantic_support_pending_manual_review",
            "source": "persisted_source_rendered_product"}


def _safe_score(function, *args) -> dict:
    try:
        return function(*args)
    except Exception as error:
        # Scoring a malformed but parseable answer must not stop the fixed matrix.
        return {"machine_result": "score_error", "semantic_result": "not_reviewed",
                "result": "score_error", "error_type": type(error).__name__,
                "error": str(error)[:200]}


def score_case(case: dict, case_root: pathlib.Path, product: dict | None, mode: str) -> dict:
    requests = sorted((case_root / "requests").glob("*.json"))
    evaluations = sorted((case_root / "evaluations").glob("*.json"))
    if mode == "prepare":
        return {"kind": "input_preflight_only", "model_outputs_scored": 0,
                "first_raw": None, "repair_raw": [], "final": {"result": "not_scored_offline_stub"},
                "request_count": len(requests), "stub_evaluation_count": len(evaluations)}
    if not requests:
        return {"kind": "live", "first_raw": None, "repair_raw": [],
                "final": {"result": "terminal_failure", "errors": ["business_request_missing"]}}
    req = [json.loads(p.read_text(encoding="utf-8"))["business_request"] for p in requests]
    ev = {int(p.stem): json.loads(p.read_text(encoding="utf-8")) for p in evaluations}
    raw_scores = []
    for index, request in enumerate(req, 1):
        evaluation = ev.get(index, {})
        payload = evaluation.get("parsed_business_json")
        if evaluation.get("outcome") != "parsed":
            raw_scores.append({"machine_result": "unavailable", "semantic_result": "not_reviewed",
                               "reason": evaluation.get("error_type", "no_parsed_business_json")})
        elif not isinstance(payload, dict):
            raw_scores.append({"machine_result": "unscorable", "semantic_result": "not_reviewed",
                               "reason": "parsed_business_json_not_object", "payload_type": type(payload).__name__})
        elif case["family"] == "comparison":
            raw_scores.append(_safe_score(score_continuity_raw, GOLD[case["case_id"]], payload, request))
        else:
            raw_scores.append(_safe_score(score_g02_raw, payload, request))
    final = ({"result": "unscorable", "machine_result": "unscorable", "semantic_result": "not_reviewed",
              "reason": "no_persisted_api_product"} if product is None else
             _safe_score(score_continuity_final, GOLD[case["case_id"]], product, req[0])
             if case["family"] == "comparison" else _safe_score(score_g02_final, product, req[0]))
    return {"kind": "live", "first_raw": raw_scores[0], "repair_raw": raw_scores[1:],
            "final": final, "request_count": len(req), "parsed_output_count": sum(
                ev.get(index, {}).get("outcome") == "parsed" for index in range(1, len(req)+1)),
            "manual_semantic_review": "pending_manual_review"}
