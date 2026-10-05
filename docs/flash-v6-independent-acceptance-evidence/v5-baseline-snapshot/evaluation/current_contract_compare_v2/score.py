"""Structural scoring against captured requests; narrative truth stays manual."""
from __future__ import annotations

import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def span_id(case: dict, item: dict) -> str:
    return f"fixture-span-{case['corpus_key']}-{item['chapter_number']}"


def score_raw_one(case: dict, raw: dict, request: dict) -> dict:
    """Audit first/repair raw structure separately from the persisted Issue."""
    errors = []
    claims = request.get("claims", [])
    if len(claims) != 1 or claims[0].get("text") != case["target_draft"]:
        errors.append("raw_target_request_mismatch")
    claim = claims[0] if len(claims) == 1 else {}
    spans = {x.get("id"): x for x in claim.get("allowed_evidence", [])}
    issues = raw.get("issues")
    if not isinstance(issues, list):
        errors.append("raw_issues_missing")
        issues = []
    if not issues:
        if "no_issue" not in case["allowed_outcomes"]:
            errors.append("raw_required_issue_missing")
    elif len(issues) != 1:
        errors.append("raw_issue_count_mismatch")
    else:
        issue = issues[0]
        outcome = ({("conflict", "confirmed_conflict"): "confirmed_conflict",
                    ("conflict", "state_change"): "state_change",
                    ("insufficient_evidence", "insufficient_evidence"): "insufficient_evidence"}
                   .get((issue.get("status"), issue.get("nature")), "invalid"))
        if outcome not in case["allowed_outcomes"]:
            errors.append("raw_outcome_invalid")
        if issue.get("claim_span_id") != claim.get("id") or issue.get("category") != case["decision_category"]:
            errors.append("raw_target_or_category_mismatch")
        allowed_ids = {span_id(case, x) for group in case["minimum_sufficient_evidence_sets"] + [case["recommended_context"]] for x in group}
        minimum = [{span_id(case, x) for x in group} for group in case["minimum_sufficient_evidence_sets"]]
        evidence = issue.get("evidence", [])
        cited = {x.get("span_id") for x in evidence}
        if not any(group <= cited for group in minimum) or not cited <= allowed_ids:
            errors.append("raw_evidence_policy_mismatch")
        relation = "supports" if outcome == "state_change" else case["evidence_relation"]
        sufficiency = "sufficient" if outcome == "state_change" else case["evidence_sufficiency"]
        for ev in evidence:
            source = spans.get(ev.get("span_id"))
            if not source or ev.get("chapter_id") != source.get("chapter_id"):
                errors.append("raw_source_unbound")
            if ev.get("relation") != relation or ev.get("sufficiency") != sufficiency:
                errors.append("raw_relation_mismatch")
        temporal = issue.get("temporal_basis", {})
        expected_temporal = ("explicit_later_transition" if outcome == "state_change" else
                             "timeless_rule" if outcome == "confirmed_conflict" and case["temporal_policy"] == "timeless_rule" else
                             "explicit_overlap" if outcome == "confirmed_conflict" else "unknown")
        if temporal.get("relation") != expected_temporal:
            errors.append("raw_temporal_policy_mismatch")
        if expected_temporal in {"explicit_overlap", "explicit_later_transition"}:
            claim_anchor, source_anchor = temporal.get("claim_anchor"), temporal.get("evidence_anchor")
            if (not isinstance(claim_anchor, str) or not claim_anchor.strip() or claim_anchor not in claim.get("text", "") or
                not isinstance(source_anchor, str) or not source_anchor.strip() or not any(
                    source_anchor in spans[x["span_id"]]["prompt_excerpt"] for x in evidence if x.get("span_id") in spans)):
                errors.append("raw_temporal_anchor_unbound")
    return {"machine_result": "fail" if errors else "pass", "semantic_result": "pending_manual_review" if not errors else "not_reviewed",
            "errors": sorted(set(errors))}


def score_one(case: dict, product: dict, request: dict) -> dict:
    errors: list[str] = []
    result = {"case_id": case["case_id"], "expected_class": case["expected_class"]}
    if product.get("status") != "completed":
        return {**result, "machine_result": "terminal_failure", "semantic_result": "not_reviewed",
                "result": "terminal_failure", "errors": [product.get("error_code") or "run_not_completed"]}
    issues = product.get("issues")
    if not isinstance(issues, list):
        return {**result, "machine_result": "unscorable", "semantic_result": "not_reviewed",
                "result": "unscorable", "errors": ["issues_not_included"]}
    claims = request.get("claims", [])
    if len(claims) != 1 or claims[0].get("text") != case["target_draft"] or request.get("draft", {}).get("body") != case["target_draft"]:
        errors.append("captured_target_mismatch")
        claim = {}
    else:
        claim = claims[0]
    spans = {x.get("id"): x for x in claim.get("allowed_evidence", [])}
    memory_by_id = {x.get("id"): x for x in request.get("memory", [])}
    declared = case["minimum_sufficient_evidence_sets"] + [case["recommended_context"]]
    declared_ids = {span_id(case, item) for group in declared for item in group}
    expected_sets = [{span_id(case, item) for item in group} for group in case["minimum_sufficient_evidence_sets"]]
    for group in declared:
        for item in group:
            source = spans.get(span_id(case, item))
            if (not source or source.get("label") != item["source_label"] or
                hashlib.sha256(source.get("body", "").encode("utf-8")).hexdigest() != item["body_sha256"]):
                errors.append("captured_source_mismatch")

    if not issues:
        if "no_issue" not in case["allowed_outcomes"]:
            errors.append("missing_required_issue")
    elif len(issues) != 1:
        errors.append("issue_count_mismatch")
    else:
        issue = issues[0]
        nature = issue.get("nature")
        classification = issue.get("classification")
        outcome = ({("conflict", "confirmed_conflict"): "confirmed_conflict",
                    ("conflict", "state_change"): "state_change",
                    ("insufficient_evidence", "insufficient_evidence"): "insufficient_evidence"}
                   .get((classification, nature), "invalid"))
        if outcome not in case["allowed_outcomes"]:
            errors.append("outcome_not_allowed")
        if issue.get("status") != "open":
            errors.append("issue_not_open")
        if issue.get("claim_span_id") != claim.get("id") or issue.get("claim_text") != case["target_draft"]:
            errors.append("target_claim_mismatch")
        if issue.get("category") != case["decision_category"]:
            errors.append("category_mismatch")
        if issue.get("review_contract_version") != "trustworthy_review_v1" or not issue.get("reasoning"):
            errors.append("review_contract_missing")
        evidence = issue.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append("evidence_missing")
            evidence = []
        cited_ids = [x.get("span_id") for x in evidence]
        if len(cited_ids) != len(set(cited_ids)):
            errors.append("duplicate_evidence")
        if not any(required <= set(cited_ids) for required in expected_sets):
            errors.append("minimum_evidence_missing")
        if not set(cited_ids) <= declared_ids:
            errors.append("undeclared_extra_evidence")
        relation = "supports" if outcome == "state_change" else case["evidence_relation"]
        sufficiency = "sufficient" if outcome == "state_change" else case["evidence_sufficiency"]
        for ev in evidence:
            sid = ev.get("span_id")
            source = spans.get(sid)
            if not source:
                errors.append("source_not_in_captured_request")
                continue
            if ev.get("chapter_id") != source.get("chapter_id") or ev.get("excerpt") != source.get("prompt_excerpt") or ev.get("excerpt_context") != source.get("body", "")[:500]:
                errors.append("source_content_mismatch")
            chapter = next((x["chapter_number"] for group in declared for x in group if span_id(case, x) == sid), None)
            if ev.get("chapter_number") != chapter:
                errors.append("source_chapter_mismatch")
            if ev.get("source_revision") != product.get("source_revision"):
                errors.append("source_revision_mismatch")
            related = ev.get("related_memory_ids")
            if not isinstance(related, list) or any(mid not in memory_by_id or memory_by_id[mid].get("source_span_id") != sid for mid in related):
                errors.append("memory_link_mismatch")
            if ev.get("relation") != relation or ev.get("sufficiency") != sufficiency:
                errors.append("evidence_relation_mismatch")
        chain = issue.get("evidence_chain")
        if not isinstance(chain, list) or {x.get("evidence_id") for x in chain if isinstance(x, dict)} != {x.get("id") for x in evidence} or len(chain) != len(evidence):
            errors.append("evidence_chain_mismatch")
        else:
            permitted_roles = {"missing_link"} if outcome == "insufficient_evidence" else {"prior_state", "current_context"}
            if any(x.get("role") not in permitted_roles for x in chain):
                errors.append("evidence_chain_role_mismatch")
        if outcome == "insufficient_evidence":
            if issue.get("available_actions") != [] or issue.get("suggested_revision") is not None:
                errors.append("uncertainty_action_upgrade")
            if issue.get("evidence_status") != "insufficient":
                errors.append("uncertainty_status_upgrade")
    machine = "fail" if errors else "pass"
    semantic = "not_reviewed" if errors else "pending_manual_review"
    return {**result, "machine_result": machine, "semantic_result": semantic,
            "result": "fail" if errors else "pending_manual_review", "errors": sorted(set(errors))}


def score_all(runs: dict[str, dict]) -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    rows = [score_one(case, runs[case["case_id"]]["product"], runs[case["case_id"]]["business_request"])
            if case["case_id"] in runs else
            {"case_id": case["case_id"], "result": "not_run", "errors": []} for case in cases]
    return {"schema_version": "current-contract-compare-v2-score", "case_count": len(rows),
            "run_count": sum(row["result"] != "not_run" for row in rows),
            "machine_pass_count": sum(row.get("machine_result") == "pass" for row in rows),
            "semantic_pending_count": sum(row.get("semantic_result") == "pending_manual_review" for row in rows),
            "rows": rows}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("products_json", help="Mapping from case_id to paired product and actual business_request")
    args = parser.parse_args()
    print(json.dumps(score_all(json.loads(pathlib.Path(args.products_json).read_text(encoding="utf-8"))), ensure_ascii=False, indent=2))
