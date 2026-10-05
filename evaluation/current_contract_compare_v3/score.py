"""V3 metadata scoring; reuses frozen V2 capture-bound checks read-only."""
from __future__ import annotations

import copy
import os
import pathlib
import sys

from evaluation.current_contract_compare_v2.score import score_one as v2_score_final
from evaluation.current_contract_compare_v2.score import score_raw_one as v2_score_raw

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
from app.engine import ContinuityEngine  # noqa: E402


def _category_case(case: dict, actual: str | None) -> dict:
    adapted = copy.deepcopy(case)
    if case["category_policy"] == "manual_variant" and actual in case["category_candidates"]:
        adapted["decision_category"] = actual
    return adapted


def _category_status(case: dict, actual: str | None) -> str:
    if case["category_policy"] == "manual_variant" and actual in case["category_candidates"]:
        return "pending_manual_adjudication"
    return "fixed_gold"


def score_one(case: dict, product: dict, request: dict) -> dict:
    issues = product.get("issues")
    actual = issues[0].get("category") if isinstance(issues, list) and len(issues) == 1 else None
    result = v2_score_final(_category_case(case, actual), product, request)
    return {**result, "category_status": _category_status(case, actual),
            "score_layer": "final_product", "input_origin": "caller_supplied_capture"}


def score_raw_one(case: dict, raw: dict, request: dict) -> dict:
    """Run targeted gold checks and the current complete product validator."""
    issues = raw.get("issues") if isinstance(raw, dict) else None
    actual = issues[0].get("category") if isinstance(issues, list) and len(issues) == 1 else None
    base = v2_score_raw(_category_case(case, actual), raw, request)
    errors = list(base["errors"])
    memory = {x.get("id"): x for x in request.get("memory", [])}
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                errors.append("raw_issue_malformed")
                continue
            evidence = issue.get("evidence", [])
            if not isinstance(evidence, list):
                errors.append("raw_evidence_malformed")
                evidence = []
            spans = [x.get("span_id") for x in evidence if isinstance(x, dict)]
            chain = issue.get("evidence_chain")
            if (not isinstance(chain, list) or len(chain) != len(spans) or
                {x.get("span_id") for x in chain if isinstance(x, dict)} != set(spans)):
                errors.append("raw_evidence_chain_mismatch")
            elif issue.get("status") == "insufficient_evidence" and any(
                not isinstance(x, dict) or x.get("role") != "missing_link" for x in chain):
                errors.append("raw_missing_link_role_invalid")
            if issue.get("status") == "insufficient_evidence":
                if issue.get("available_actions") != []:
                    errors.append("raw_insufficient_actions_invalid")
                if issue.get("proposed_memory_change") is not None:
                    errors.append("raw_insufficient_memory_change_invalid")
            for ev in evidence:
                if not isinstance(ev, dict):
                    errors.append("raw_evidence_malformed")
                    continue
                ids = ev.get("related_memory_ids")
                if not isinstance(ids, list) or any(mid not in memory or memory[mid].get("source_span_id") != ev.get("span_id") for mid in ids):
                    errors.append("raw_memory_link_mismatch")
    try:
        ContinuityEngine(object()).validate(raw, request)
        validator = "accepted"
    except ValueError as exc:
        validator = "rejected"
        errors.append("product_validator:" + str(exc))
    errors = sorted(set(errors))
    return {"machine_result": "fail" if errors else "pass",
            "semantic_result": "not_reviewed" if errors else "pending_manual_review",
            "category_status": _category_status(case, actual),
            "full_validator_result": validator, "score_layer": "raw_first_or_repair",
            "errors": errors}
