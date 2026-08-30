"""Fail-closed validator for retained V6 first-valid formal evidence."""
from __future__ import annotations

import json
import pathlib
import sqlite3
from typing import Any

from evaluation.post_run_integrity import sha256_file
from evaluation.validate_eval_set import canonical_sha256


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results"
INTEGRITY_PATH = RESULTS / "v6-first-formal-post-run-integrity.json"
EXPECTED_ARTIFACTS = {
    f"evaluation/results/eval-v6-first-formal-{suffix}"
    for suffix in ("api-corpus-scan.json", "bad-cases.json", "checkpoint.json", "report.md", "results.json", "run-manifest.json", "stability.json")
}
EXPECTED_CASE_HASH = "3b40e1a157be6e61be58025f7429c7011f30461c6b995ddb1dd9c28adf7564f0"


def load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def validate(*, check_plan: bool = True) -> dict[str, Any]:
    integrity = load("evaluation/results/v6-first-formal-post-run-integrity.json")
    if integrity.get("schema_version") != "scc-evaluation-post-run-integrity-v1" or integrity.get("evaluation") != "scc-web-demo-eval-v6-first-formal" or integrity.get("integrity_status") != "retained_baseline" or integrity.get("raw_provider_content_retained") is not False:
        raise ValueError("v6_post_run_integrity_schema_invalid")
    files = integrity.get("retained_artifacts", {}).get("files")
    if integrity.get("retained_artifacts", {}).get("count") != 7 or not isinstance(files, list) or {item.get("path") for item in files} != EXPECTED_ARTIFACTS:
        raise ValueError("v6_post_run_artifact_set_invalid")
    for item in files:
        path = ROOT / item["path"]
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("v6_post_run_artifact_hash_mismatch")

    report = load("evaluation/results/eval-v6-first-formal-results.json")
    manifest = load("evaluation/manifests/eval-set-v6-manifest.json")
    cases = report.get("formal_case_results")
    aborted = report.get("status") == "aborted_valid_run_attempt"
    if report.get("evaluation") != "scc-web-demo-eval-v6-first-formal" or report.get("execution_kind") != "first_valid_formal" or report.get("case_set_sha256") != EXPECTED_CASE_HASH or canonical_sha256(load("evaluation/case_sets/eval-set-v6.json")) != EXPECTED_CASE_HASH or manifest.get("case_set", {}).get("canonical_sha256") != EXPECTED_CASE_HASH or not isinstance(cases, list) or len(cases) != (1 if aborted else 24):
        raise ValueError("v6_formal_report_shape_invalid")
    if report.get("status") not in {"gate_passed", "gate_failed", "aborted_valid_run_attempt"}:
        raise ValueError("v6_formal_status_invalid")
    execution = report.get("run_metadata", {}).get("provider_execution", {})
    if execution.get("provider_run_records") != (1 if aborted else 30) or not isinstance(execution.get("actual_provider_http_attempts"), int) or execution["actual_provider_http_attempts"] < execution["provider_run_records"] or not isinstance(execution.get("successful_provider_responses"), int):
        raise ValueError("v6_provider_execution_invalid")
    if report.get("run_metadata", {}).get("provider_configuration") != "environment_only_not_recorded":
        raise ValueError("v6_provider_configuration_retention_invalid")
    if aborted:
        if report.get("metrics") is not None or report.get("gate_checks") != {"quality_gate_evaluated": False} or report.get("abort_reason") not in {"provider_unavailable", "provider_timeout", "provider_error"}:
            raise ValueError("v6_abort_contract_invalid")
    elif report.get("metrics") is None or not isinstance(report.get("gate_checks"), dict):
        raise ValueError("v6_quality_result_invalid")

    stability = load("evaluation/results/eval-v6-first-formal-stability.json")
    rows = stability.get("rows")
    if not isinstance(rows, list) or len(rows) != (0 if aborted else 3) or any(len(row.get("runs", [])) != 3 for row in rows):
        raise ValueError("v6_stability_shape_invalid")
    for row in rows:
        result = row.get("stability", {})
        if result.get("terminal_failure_count", 0) and result.get("quality_stability_established") is not False:
            raise ValueError("v6_terminal_failure_cannot_establish_stability")

    bad = load("evaluation/results/eval-v6-first-formal-bad-cases.json").get("bad_cases")
    if not isinstance(bad, list) or any(not item.get("failure_dimensions") for item in bad):
        raise ValueError("v6_bad_case_dimensions_invalid")
    scan = load("evaluation/results/eval-v6-first-formal-api-corpus-scan.json")
    if scan.get("unresolved") != 0:
        raise ValueError("v6_api_scan_not_clean")
    run_manifest = load("evaluation/results/eval-v6-first-formal-run-manifest.json")
    if run_manifest.get("provider_execution") != execution or run_manifest.get("status") != report.get("status") or run_manifest.get("execution_kind") != "first_valid_formal":
        raise ValueError("v6_run_manifest_mismatch")

    workspaces = integrity.get("fixture_workspaces", {})
    database_items = workspaces.get("sqlite_files")
    if workspaces.get("root") != "evaluation/fixture-workspaces/scc-web-demo-eval-v6-first-formal" or workspaces.get("sqlite_count") != (1 if aborted else 24) or not isinstance(database_items, list) or len(database_items) != (1 if aborted else 24):
        raise ValueError("v6_workspace_shape_invalid")
    totals: dict[str, int] = {}
    for item in database_items:
        path = ROOT / workspaces["root"] / item["workspace_key"] / "runtime" / "data" / "demo.sqlite3"
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("v6_workspace_hash_mismatch")
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            statuses = dict(connection.execute("SELECT status, COUNT(*) FROM v2_runs GROUP BY status"))
        finally:
            connection.close()
        if statuses != item.get("run_status"):
            raise ValueError("v6_workspace_status_mismatch")
        for status, count in statuses.items():
            totals[status] = totals.get(status, 0) + count
    if totals != workspaces.get("run_status_totals") or sum(totals.values()) != execution["provider_run_records"]:
        raise ValueError("v6_workspace_total_mismatch")
    if check_plan:
        plan = load("evaluation/manifests/eval-v6-first-formal-plan.json")
        if plan.get("status") != report.get("status") or plan.get("formal_run_executed") is not True or plan.get("provider_calls") != execution["provider_run_records"] or plan.get("real_provider_authorization_received") is not True:
            raise ValueError("v6_plan_execution_state_invalid")
        if plan.get("stage_status") != {"stage_10": "gate_failed_not_passed", "stage_11": "not_started", "stage_12": "not_started", "v7_or_repeat_authorized": False}:
            raise ValueError("v6_plan_stage_boundary_invalid")
        expected_bad_audit = []
        by_case_id = {item["case_id"]: item for item in cases}
        for item in bad:
            row = by_case_id.get(item.get("case_id"))
            if row is None:
                raise ValueError("v6_plan_bad_case_audit_missing_result")
            audit_item = {"case_id": item["case_id"], "failure_dimensions": item["failure_dimensions"]}
            if "category_mismatch" in item["failure_dimensions"]:
                audit_item["category"] = {"expected": row["expected_category"], "predicted": row["predicted_category"]}
            expected_bad_audit.append(audit_item)
        expected_audit = {"source": "frozen_results_rows_and_bad_cases", "known_artifact_limitation": "The frozen V6 Bad Case artifact records failure_dimensions but omits expected_category and predicted_category; this audit derives category detail from the immutable results rows.", "bad_cases": expected_bad_audit}
        if plan.get("post_run_audit") != expected_audit:
            raise ValueError("v6_plan_bad_case_audit_invalid")
    return {"valid": True, "status": report["status"], "formal_case_count": len(cases), "provider_run_count": execution["provider_run_records"], "actual_provider_http_attempts": execution["actual_provider_http_attempts"], "successful_provider_responses": execution["successful_provider_responses"], "bad_case_count": len(bad), "run_status_totals": totals}


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
