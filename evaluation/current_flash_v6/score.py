"""V6 source-role scoring for raw, repair and final outputs; semantics stay manual."""
from __future__ import annotations

import json
import pathlib

from evaluation.current_flash_v6.build_cases import controls

ROOT = pathlib.Path(__file__).resolve().parents[2]
V3 = {item["case_id"]: item for item in json.loads(
    (ROOT / "evaluation/current_contract_compare_v3/cases.json").read_text(encoding="utf-8"))["cases"]}
CONTROL = {item["id"]: item for item in controls()["controls"]}
JOINT_PREMISES = {("north_glass", 4), ("orchard_restoration", 1), ("orchard_restoration", 4), ("basalt_observatory", 1)}
JOINT_RULE_TIME_FLEX = {"ccv3-north_glass-object_state-conflict", "ccv3-orchard_restoration-event_status-conflict"}
CHAIN_ROLES = {"prior_state", "current_context", "missing_link"}


class ScoringProvider:
    continuity_contract_version = "v6"


def policy(case: dict, request: dict) -> dict:
    if case["evaluation_kind"] == "preserved_v5_comparison":
        gold = V3[case["case_id"]]
        source_id = lambda item: f"fixture-span-{case['corpus_key']}-{item['chapter_number']}"
        minimum = [{source_id(item) for item in group} for group in gold["minimum_sufficient_evidence_sets"]]
        optional = {source_id(item) for item in gold["recommended_context"]}
        premises = {f"fixture-span-{key}-{number}" for key, number in JOINT_PREMISES if key == case["corpus_key"]}
        return {"allowed_outcomes": set(gold["allowed_outcomes"]), "minimum": minimum,
                "optional": optional, "premises": premises, "category": gold["decision_category"],
                "category_candidates": set(gold.get("category_candidates", [])),
                "manual_variant": gold.get("category_policy") == "manual_variant",
                "temporal_relations": ({"timeless_rule", "explicit_overlap"} if case["case_id"] in JOINT_RULE_TIME_FLEX else
                                       {"timeless_rule"} if gold["temporal_policy"] == "timeless_rule" else
                                       {"explicit_overlap"} if "confirmed_conflict" in gold["allowed_outcomes"] else set())}
    chosen = CONTROL[case["control_ids"][0]]
    by_label = {item["label"]: item["id"] for item in request["claims"][0]["allowed_evidence"]}
    def bound(groups):
        return [{by_label.get(label, "unselected:" + label) for label in group} for group in groups]
    if chosen["id"] == "V6S-12":
        outcomes = {"no_issue", "state_change"}
    elif chosen["world_fact_expected"].startswith("confirmed_conflict"):
        outcomes = {"confirmed_conflict"}
    elif chosen["world_fact_expected"] in {"no_issue", "no_conflict"}:
        outcomes = {"no_issue"}
    else:
        outcomes = {"insufficient_evidence"}
    groups = (chosen.get("minimum_source_sets") or chosen.get("minimum_source_sets_for_review") or
              chosen.get("minimum_source_sets_if_state_change") or [])
    optional_labels = set(chosen.get("optional_sources") or [])
    if case["fixture_key"] == "lens":
        optional_labels |= {"L3", "L4"}
    premises = {by_label[label] for label in ("L1", "R1") if label in by_label}
    category = chosen.get("category") or chosen.get("category_if_state_change") or chosen.get("category_if_issue")
    return {"allowed_outcomes": outcomes, "minimum": bound(groups),
            "optional": {by_label.get(label, "unselected:" + label) for label in optional_labels},
            "premises": premises, "category": category,
            "category_candidates": set(chosen.get("category_candidates") or []),
            "manual_variant": chosen.get("category_policy") == "manual_variant",
            "temporal_relations": {"explicit_overlap"} if "confirmed_conflict" in outcomes else set()}


def outcome(issue: dict, final: bool) -> str:
    status = issue.get("classification") if final else issue.get("status")
    return ({("conflict", "confirmed_conflict"): "confirmed_conflict",
             ("conflict", "state_change"): "state_change",
             ("insufficient_evidence", "insufficient_evidence"): "insufficient_evidence"}
            .get((status, issue.get("nature")), "invalid"))


def issue_errors(case: dict, issue: dict, request: dict, final: bool) -> list[str]:
    if not isinstance(issue, dict):
        return ["issue_not_object"]
    errors = []
    rule = policy(case, request)
    claim = request["claims"][0]
    sources = {item["id"]: item for item in claim["allowed_evidence"]}
    memory = {item["id"]: item for item in request.get("memory", [])}
    result = outcome(issue, final)
    if result not in rule["allowed_outcomes"]:
        errors.append("outcome_not_allowed")
    if issue.get("claim_span_id") != claim["id"] or final and issue.get("claim_text") != claim["text"]:
        errors.append("target_claim_mismatch")
    category = issue.get("category")
    if rule["manual_variant"]:
        if category not in rule["category_candidates"]:
            errors.append("category_mismatch")
    elif rule["category"] is not None and category != rule["category"]:
        errors.append("category_mismatch")
    if final and (issue.get("status") != "open" or issue.get("review_contract_version") != "trustworthy_review_v1" or not issue.get("reasoning")):
        errors.append("persisted_review_contract_missing")
    evidence = issue.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return errors + ["evidence_missing"]
    cited = [item.get("span_id") for item in evidence if isinstance(item, dict)]
    if len(cited) != len(evidence) or len(cited) != len(set(cited)):
        errors.append("evidence_shape_or_duplicate")
    cited_set = set(cited)
    if rule["minimum"] and not any(group <= cited_set for group in rule["minimum"]):
        errors.append("minimum_joint_evidence_missing")
    declared = set().union(*rule["minimum"]) if rule["minimum"] else set()
    if not cited_set <= declared | rule["optional"]:
        errors.append("undeclared_extra_evidence")
    direct = 0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        span_id = item.get("span_id")
        source = sources.get(span_id)
        if source is None or item.get("chapter_id") != source.get("chapter_id"):
            errors.append("source_not_selected_or_wrong_chapter")
            continue
        if final and (item.get("excerpt") != source.get("prompt_excerpt") or item.get("excerpt_context") != source.get("body", "")[:500]):
            errors.append("persisted_source_content_mismatch")
        ids = item.get("related_memory_ids")
        if not isinstance(ids, list) or any(not isinstance(mid, str) or mid not in memory for mid in ids):
            errors.append("memory_id_unbound")
        relation, sufficiency = item.get("relation"), item.get("sufficiency")
        if result == "confirmed_conflict":
            if relation == "contradicts" and sufficiency == "sufficient":
                direct += 1
                if span_id in rule["premises"]:
                    errors.append("premise_mislabeled_direct_contradiction")
            elif relation != "context" or sufficiency != "sufficient":
                errors.append("confirmed_evidence_role_invalid")
            elif span_id in declared and span_id not in rule["premises"]:
                errors.append("direct_fact_mislabeled_context")
        elif result == "insufficient_evidence" and (relation, sufficiency) != ("context", "insufficient"):
            errors.append("insufficient_evidence_upgraded")
        elif result == "state_change" and (relation, sufficiency) != ("supports", "sufficient"):
            errors.append("state_change_evidence_relation_invalid")
    if result == "confirmed_conflict" and direct == 0:
        errors.append("direct_contradiction_missing")
    chain = issue.get("evidence_chain")
    key = "evidence_id" if final else "span_id"
    expected = {item.get("id") for item in evidence} if final else cited_set
    if (not isinstance(chain, list) or len(chain) != len(evidence) or
        any(not isinstance(item, dict) or item.get("role") not in CHAIN_ROLES for item in chain) or
        {item.get(key) for item in chain if isinstance(item, dict)} != expected):
        errors.append("evidence_chain_mismatch")
    elif result == "insufficient_evidence" and any(item["role"] != "missing_link" for item in chain):
        errors.append("missing_link_role_invalid")
    if result == "insufficient_evidence" and (issue.get("available_actions") != [] or issue.get("suggested_revision") is not None):
        errors.append("uncertainty_action_upgrade")
    if not final and result == "confirmed_conflict":
        temporal = issue.get("temporal_basis") if isinstance(issue.get("temporal_basis"), dict) else {}
        if temporal.get("relation") not in rule["temporal_relations"]:
            errors.append("temporal_policy_mismatch")
    return errors


def score_raw(case: dict, payload: dict, request: dict) -> dict:
    from app.engine import ContinuityEngine
    errors = []
    try:
        ContinuityEngine(ScoringProvider()).validate(payload, request)
    except Exception as error:
        errors.append("product_validator:" + str(error))
    issues = payload.get("issues") if isinstance(payload, dict) else None
    if not isinstance(issues, list):
        errors.append("issues_not_list")
    elif not issues:
        if "no_issue" not in policy(case, request)["allowed_outcomes"]:
            errors.append("required_issue_missing")
    elif len(issues) != 1:
        errors.append("issue_count_invalid")
    else:
        errors += issue_errors(case, issues[0], request, False)
    return {"machine_result": "fail" if errors else "pass", "semantic_result": "not_reviewed" if errors else "pending_manual_review",
            "score_layer": "raw_first_or_repair_v6", "errors": sorted(set(errors))}


def score_final(case: dict, product: dict, request: dict) -> dict:
    if product.get("status") != "completed":
        return {"result": "terminal_failure", "machine_result": "terminal_failure", "semantic_result": "not_reviewed",
                "errors": [product.get("error_code") or "run_not_completed"]}
    issues = product.get("issues")
    if not isinstance(issues, list):
        return {"result": "unscorable", "machine_result": "unscorable", "semantic_result": "not_reviewed",
                "errors": ["issues_not_included"]}
    errors = []
    if not issues:
        if "no_issue" not in policy(case, request)["allowed_outcomes"]:
            errors.append("required_issue_missing")
    elif len(issues) != 1:
        errors.append("issue_count_invalid")
    else:
        errors += issue_errors(case, issues[0], request, True)
        if any(item.get("source_revision") != product.get("source_revision") for item in issues[0].get("evidence", []) if isinstance(item, dict)):
            errors.append("source_revision_mismatch")
    return {"result": "fail" if errors else "pending_manual_review", "machine_result": "fail" if errors else "pass",
            "semantic_result": "not_reviewed" if errors else "pending_manual_review", "score_layer": "final_product_v6",
            "errors": sorted(set(errors))}


def safe(function, *args) -> dict:
    try:
        return function(*args)
    except Exception as error:
        return {"result": "score_error", "machine_result": "score_error", "semantic_result": "not_reviewed",
                "error_type": type(error).__name__, "error": str(error)[:200]}


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
    req = [json.loads(path.read_text(encoding="utf-8"))["business_request"] for path in requests]
    ev = {int(path.stem): json.loads(path.read_text(encoding="utf-8")) for path in evaluations}
    raw_scores = []
    for index, request in enumerate(req, 1):
        observed = ev.get(index, {})
        payload = observed.get("parsed_business_json")
        if observed.get("outcome") != "parsed":
            raw_scores.append({"machine_result": "unavailable", "semantic_result": "not_reviewed",
                               "reason": observed.get("error_type", "no_parsed_business_json")})
        elif not isinstance(payload, dict):
            raw_scores.append({"machine_result": "unscorable", "semantic_result": "not_reviewed",
                               "reason": "parsed_business_json_not_object", "payload_type": type(payload).__name__})
        else:
            raw_scores.append(safe(score_raw, case, payload, request))
    final = ({"result": "unscorable", "machine_result": "unscorable", "semantic_result": "not_reviewed",
              "reason": "no_persisted_api_product"} if product is None else safe(score_final, case, product, req[0]))
    return {"kind": "live", "first_raw": raw_scores[0], "repair_raw": raw_scores[1:], "final": final,
            "request_count": len(req), "parsed_output_count": sum(ev.get(index, {}).get("outcome") == "parsed" for index in range(1, len(req)+1)),
            "manual_semantic_review": "pending_manual_review"}
