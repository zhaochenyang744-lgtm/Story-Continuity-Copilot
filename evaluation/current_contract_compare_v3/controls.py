"""Create-only, in-memory positive/negative controls over saved synthetic V2 records."""
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone

from evaluation.current_contract_compare_v3.run import HERE, V2, reserve_run_dir, write_x
from evaluation.current_contract_compare_v3.score import score_one, score_raw_one


def controls() -> dict:
    cases = {x["lineage"]["v2_case_id"]: x for x in json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]}
    saved = json.loads((V2 / "api-score-probe-results-v2.json").read_text(encoding="utf-8"))["rows"]
    rows = {(x["case_id"], x["variant"]): x for x in saved}
    results = []

    def check(name: str, old_id: str, variant: str = "gold", raw_edit=None, final_edit=None,
              raw_expected: str | None = None, final_expected: str | None = None,
              required_error: str | None = None) -> None:
        row, case = rows[(old_id, variant)], cases[old_id]
        raw, final = copy.deepcopy(row["raw_first"]), copy.deepcopy(row["final_product"])
        if raw_edit:
            raw_edit(raw, row["business_request"])
        if final_edit:
            final_edit(final, row["business_request"])
        raw_score = score_raw_one(case, raw, row["business_request"]) if raw_expected else None
        final_score = score_one(case, final, row["business_request"]) if final_expected else None
        actual_raw = raw_score["machine_result"] if raw_score else None
        actual_final = final_score["machine_result"] if final_score else None
        passed = actual_raw == raw_expected and actual_final == final_expected
        if required_error:
            error_list = raw_score["errors"] if raw_score else final_score["errors"] if final_score else []
            passed = passed and required_error in error_list
        results.append({"control": name, "v3_case_id": case["case_id"], "v2_record_id": old_id,
                        "variant": variant, "expected_raw": raw_expected, "actual_raw": actual_raw,
                        "expected_final": final_expected, "actual_final": actual_final,
                        "raw_full_validator": raw_score["full_validator_result"] if raw_score else None,
                        "raw_errors": raw_score["errors"] if raw_score else [],
                        "final_errors": final_score["errors"] if final_score else [],
                        "category_status": (raw_score or final_score or {}).get("category_status"),
                        "required_error": required_error,
                        "passed": passed})
        if not passed:
            raise AssertionError("control_failed:" + name)

    badge = "ccv2-north_glass-world_rule-conflict"
    def raw_rule_only(raw, request):
        rule = next(x for x in raw["issues"][0]["evidence"] if x["span_id"].endswith("-1"))
        raw["issues"][0]["evidence"] = [rule]
        raw["issues"][0]["evidence_chain"] = [x for x in raw["issues"][0]["evidence_chain"] if x["span_id"] == rule["span_id"]]
    def final_rule_only(product, request):
        issue = product["issues"][0]
        rule = next(x for x in issue["evidence"] if x["span_id"].endswith("-1"))
        issue["evidence"] = [rule]
        issue["evidence_chain"] = [x for x in issue["evidence_chain"] if x["evidence_id"] == rule["id"]]
    check("badge_rule_single_source", badge, raw_edit=raw_rule_only, final_edit=final_rule_only,
          raw_expected="pass", final_expected="pass")

    for old_id, case in cases.items():
        if case["expected_class"] != "insufficient_evidence":
            continue
        def set_raw_category(raw, request, category=case["decision_category"]):
            raw["issues"][0]["category"] = category
        def set_final_category(product, request, category=case["decision_category"]):
            product["issues"][0]["category"] = category
        check("supported_insufficient_category:" + case["category_axis"], old_id,
              raw_edit=set_raw_category, final_edit=set_final_category,
              raw_expected="pass", final_expected="pass")

    companion = "ccv2-basalt_observatory-location_action-insufficient_evidence"
    check("companion_relationship_manual_variant", companion,
          raw_edit=lambda r, q: r["issues"][0].update(category="relationship"),
          final_edit=lambda p, q: p["issues"][0].update(category="relationship"),
          raw_expected="pass", final_expected="pass")

    insuff = "ccv2-north_glass-world_rule-insufficient_evidence"
    def corrected_raw(edit):
        def apply(raw, request):
            raw["issues"][0]["category"] = cases[insuff]["decision_category"]
            edit(raw, request)
        return apply
    def corrected_final(edit):
        def apply(product, request):
            product["issues"][0]["category"] = cases[insuff]["decision_category"]
            edit(product, request)
        return apply
    check("raw_missing_chain", insuff,
          raw_edit=corrected_raw(lambda r, q: r["issues"][0].update(evidence_chain=[])), raw_expected="fail",
          required_error="raw_evidence_chain_mismatch")
    check("raw_wrong_missing_link_role", insuff,
          raw_edit=corrected_raw(lambda r, q: r["issues"][0]["evidence_chain"][0].update(role="prior_state")), raw_expected="fail",
          required_error="raw_missing_link_role_invalid")
    check("raw_insufficient_edit_action", insuff,
          raw_edit=corrected_raw(lambda r, q: r["issues"][0].update(available_actions=["edit"])), raw_expected="fail",
          required_error="raw_insufficient_actions_invalid")
    check("raw_insufficient_memory_change", insuff,
          raw_edit=corrected_raw(lambda r, q: r["issues"][0].update(proposed_memory_change={"operation": "add"})), raw_expected="fail",
          required_error="raw_insufficient_memory_change_invalid")
    check("raw_unknown_memory_id", insuff,
          raw_edit=corrected_raw(lambda r, q: r["issues"][0]["evidence"][0].update(related_memory_ids=["not-a-memory"])), raw_expected="fail",
          required_error="raw_memory_link_mismatch")

    for axis in ("character_knowledge", "location_action"):
        old_id = next(k for k, case in cases.items() if case["category_axis"] == axis and case["expected_class"] == "no_conflict")
        check("legal_state_change:" + axis, old_id, variant="state_change", raw_expected="pass", final_expected="pass")

    def extra_unrelated(product, request):
        issue = product["issues"][0]
        source = next(x for x in request["claims"][0]["allowed_evidence"] if x["id"].endswith("-5"))
        new = copy.deepcopy(issue["evidence"][0])
        new.update(id="v3-extra", span_id=source["id"], chapter_id=source["chapter_id"], chapter_number=5,
                   excerpt=source["prompt_excerpt"], excerpt_context=source["body"][:500], related_memory_ids=[])
        issue["evidence"].append(new)
        issue["evidence_chain"].append({"evidence_id": "v3-extra", "role": "prior_state"})
    check("final_unrelated_extra_evidence", badge, final_edit=extra_unrelated, final_expected="fail",
          required_error="undeclared_extra_evidence")
    check("final_wrong_insufficient_relation", insuff,
          final_edit=corrected_final(lambda p, q: p["issues"][0]["evidence"][0].update(relation="contradicts")), final_expected="fail",
          required_error="evidence_relation_mismatch")
    check("terminal_failure_not_no_issue", "ccv2-harbor_signal-timeline-no_conflict",
          final_edit=lambda p, q: p.update(status="failed", issues=[]), final_expected="terminal_failure")
    return {"schema_version": "current-contract-compare-v3-controls", "source": "in_memory_mutations_of_saved_synthetic_v2_records",
            "new_api_runs": 0, "real_provider_calls": 0, "control_count": len(results),
            "passed_count": sum(x["passed"] for x in results), "rows": results}


def execute(run_id: str):
    destination = reserve_run_dir(run_id)
    try:
        result = controls()
        write_x(destination / "controls.json", result)
        write_x(destination / "summary.json", {"run_kind": "in_memory_controls", "control_count": result["control_count"],
                "passed_count": result["passed_count"], "new_api_runs": 0, "real_provider_calls": 0,
                "created_at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        write_x(destination / "first-failure.json", {"run_id": run_id, "error_type": type(exc).__name__,
                "error": str(exc), "note": "V3 first failure; no historical V2 result reconstructed."})
        raise
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(execute(args.run_id))
