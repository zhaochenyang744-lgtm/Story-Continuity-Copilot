"""Same V7 frozen policy; engine-final adaptation removes only API persistence checks."""
from __future__ import annotations

import copy

from evaluation.current_flash_v7.score import issue_errors, policy, score_raw


def layers(errors):
    result = {"decision": [], "category": [], "citation": [], "structure": [], "temporal": [], "generation": []}
    for error in errors:
        key = ("category" if "category" in error else "generation" if error.startswith(("generation:", "finish_reason:")) else
               "temporal" if "temporal" in error else
               "citation" if any(word in error for word in ("evidence", "source_", "premise", "direct_fact", "memory_id")) else
               "decision" if error in {"outcome_not_allowed", "required_issue_missing"} else "structure")
        result[key].append(error)
    return result


def safe_score(function, *args):
    try:
        return function(*args)
    except Exception as error:
        return {"machine_result": "score_error", "errors": ["scorer_exception:" + type(error).__name__],
                "layers": {"scoring": [type(error).__name__]}, "semantic_result": "pending_independent_review"}


def raw_score(case, payload, request, finish_reason="stop"):
    scored = safe_score(score_raw, case, payload, request)
    errors = list(scored["errors"])
    if finish_reason != "stop":
        errors.append("generation:finish_reason_" + str(finish_reason))
    dimensions = layers(errors)
    if scored["machine_result"] == "score_error":
        dimensions["scoring"] = scored["layers"]["scoring"]
    return {**scored, "machine_result": "score_error" if scored["machine_result"] == "score_error" else "fail" if errors else "pass", "errors": sorted(set(errors)),
            "layers": dimensions, "semantic_result": "pending_independent_review",
            "complete_answer": finish_reason == "stop", "scoring_policy": "unchanged_v7"}


def engine_final_score(case, product, request, accepted_payload, finish_reason="stop"):
    if product.get("status") != "completed":
        return {"machine_result": "terminal_failure", "errors": [product.get("error_code") or "not_completed"],
                "layers": layers([product.get("error_code") or "not_completed"]),
                "semantic_result": "not_delivered", "output_layer": "experiment_engine_not_api_persistence"}
    issues = product.get("issues")
    errors = []
    if not isinstance(issues, list):
        errors.append("issues_not_included")
    elif not issues:
        if "no_issue" not in policy(case, request)["allowed_outcomes"]:
            errors.append("required_issue_missing")
    elif len(issues) != 1:
        errors.append("issue_count_invalid")
    else:
        item = copy.deepcopy(issues[0])
        accepted = (accepted_payload or {}).get("issues", []) if isinstance(accepted_payload, dict) else []
        original = next((x for x in accepted if isinstance(x, dict) and x.get("claim_span_id") == item.get("claim_span_id")), {})
        # The original engine validates then drops temporal_basis. Read it from
        # the actual accepted response, never invent it or widen the policy.
        item["temporal_basis"] = copy.deepcopy(original.get("temporal_basis"))
        errors += issue_errors(case, item, request, False)
        if item.get("review_contract_version") != "trustworthy_review_v1" or not item.get("reasoning"):
            errors.append("review_contract_missing")
    if finish_reason != "stop":
        errors.append("generation:finish_reason_" + str(finish_reason))
    return {"machine_result": "fail" if errors else "pass", "errors": sorted(set(errors)),
            "layers": layers(errors), "semantic_result": "pending_independent_review",
            "output_layer": "experiment_engine_not_api_persistence", "scoring_policy": "unchanged_v7",
            "excluded_checks": ["database_open_status", "database_evidence_id_chain_mapping", "persisted_revision_fields", "API_excerpt_context"]}
