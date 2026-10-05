"""Read-only fail-closed validator for the retained V7 first-valid formal run."""
from __future__ import annotations

import json
import pathlib
import sqlite3
from typing import Any

from evaluation.post_run_integrity import sha256_file
from evaluation.scan_v7_retained import scan as scan_v7_retained
from evaluation.validate_eval_set import canonical_sha256


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results"
INTEGRITY_PATH = RESULTS / "v7-first-formal-post-run-integrity.json"
EXPECTED_CASE_HASH = "e53eba34c29f889855c01f0c2657e4769d2f19e458cf5631a3f3d2ffcee0b3fd"
EXPECTED_ARTIFACTS = {f"evaluation/results/eval-v7-first-formal-{suffix}" for suffix in ("api-corpus-scan.json", "bad-cases.json", "checkpoint.json", "report.md", "results.json", "run-manifest.json", "stability.json")}


def _load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def validate(*, check_plan: bool = True) -> dict[str, Any]:
    integrity = _load("evaluation/results/v7-first-formal-post-run-integrity.json")
    if (integrity.get("schema_version") != "scc-evaluation-post-run-integrity-v1" or integrity.get("evaluation") != "scc-web-demo-eval-v7-first-formal"
            or integrity.get("integrity_status") != "retained_baseline" or integrity.get("raw_provider_content_retained") is not False):
        raise ValueError("v7_post_run_integrity_schema_invalid")
    files = integrity.get("retained_artifacts", {}).get("files")
    if integrity.get("retained_artifacts", {}).get("count") != 7 or not isinstance(files, list) or {item.get("path") for item in files} != EXPECTED_ARTIFACTS:
        raise ValueError("v7_post_run_artifact_set_invalid")
    for item in files:
        path = ROOT / item["path"]
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("v7_post_run_artifact_hash_mismatch")

    report = _load("evaluation/results/eval-v7-first-formal-results.json")
    cases = report.get("formal_case_results")
    execution = report.get("run_metadata", {}).get("provider_execution", {})
    if (report.get("evaluation") != "scc-web-demo-eval-v7-first-formal" or report.get("execution_kind") != "first_valid_formal"
            or report.get("status") not in {"gate_passed", "gate_failed"} or report.get("abort_reason") is not None
            or report.get("case_set_sha256") != EXPECTED_CASE_HASH or canonical_sha256(_load("evaluation/case_sets/eval-set-v7.json")) != EXPECTED_CASE_HASH
            or not isinstance(cases, list) or len(cases) != 24):
        raise ValueError("v7_formal_report_shape_invalid")
    if (execution.get("provider_run_records"), execution.get("actual_provider_http_attempts"), execution.get("successful_provider_responses"), execution.get("terminal_status_counts")) != (30, 30, 30, {"completed": 30}):
        raise ValueError("v7_provider_execution_invalid")
    if report.get("run_metadata", {}).get("provider_configuration") != "environment_only_not_recorded":
        raise ValueError("v7_provider_configuration_retention_invalid")
    if report.get("metrics") is None or not isinstance(report.get("gate_checks"), dict):
        raise ValueError("v7_quality_result_invalid")

    stability = _load("evaluation/results/eval-v7-first-formal-stability.json")
    rows = stability.get("rows")
    if not isinstance(rows, list) or len(rows) != 3 or any(len(row.get("runs", [])) != 3 for row in rows):
        raise ValueError("v7_stability_shape_invalid")
    for row in rows:
        result = row.get("stability", {})
        if result.get("terminal_failure_count", 0) or result.get("quality_stability_established") is not True:
            raise ValueError("v7_stability_terminal_or_quality_invalid")

    bad = _load("evaluation/results/eval-v7-first-formal-bad-cases.json").get("bad_cases")
    if not isinstance(bad, list) or any(not item.get("failure_dimensions") or not isinstance(item.get("category"), dict) or set(item["category"]) != {"expected", "predicted"} for item in bad):
        raise ValueError("v7_bad_case_audit_invalid")
    forbidden = ("target_draft", "prompt", "raw_provider_body", "provider_body", "chain_of_thought", "reasoning_content")
    if any(any(token in json.dumps(item, ensure_ascii=False).casefold() for token in forbidden) for item in bad):
        raise ValueError("v7_bad_case_sensitive_content_invalid")
    if _load("evaluation/results/eval-v7-first-formal-api-corpus-scan.json").get("unresolved") != 0:
        raise ValueError("v7_api_scan_not_clean")
    retained_scan = scan_v7_retained()
    if retained_scan.get("clean") is not True:
        raise ValueError("v7_retained_sensitive_scan_not_clean")
    run_manifest = _load("evaluation/results/eval-v7-first-formal-run-manifest.json")
    if run_manifest.get("provider_execution") != execution or run_manifest.get("status") != report.get("status") or run_manifest.get("execution_kind") != "first_valid_formal":
        raise ValueError("v7_run_manifest_mismatch")

    workspaces = integrity.get("fixture_workspaces", {})
    items = workspaces.get("sqlite_files")
    if workspaces.get("root") != "evaluation/fixture-workspaces/scc-web-demo-eval-v7-first-formal" or workspaces.get("sqlite_count") != 24 or not isinstance(items, list) or len(items) != 24:
        raise ValueError("v7_workspace_shape_invalid")
    totals: dict[str, int] = {}
    for item in items:
        path = ROOT / workspaces["root"] / item["workspace_key"] / "runtime" / "data" / "demo.sqlite3"
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("v7_workspace_hash_mismatch")
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            statuses = dict(connection.execute("SELECT status, COUNT(*) FROM v2_runs GROUP BY status"))
        finally:
            connection.close()
        if statuses != item.get("run_status"):
            raise ValueError("v7_workspace_status_mismatch")
        for status, count in statuses.items(): totals[status] = totals.get(status, 0) + count
    if totals != workspaces.get("run_status_totals") or totals != {"completed": 30}:
        raise ValueError("v7_workspace_total_mismatch")
    if check_plan:
        plan = _load("evaluation/manifests/eval-v7-first-formal-plan.json")
        if (plan.get("status") != report["status"] or plan.get("formal_run_executed") is not True or plan.get("provider_calls") != 30
                or plan.get("real_provider_authorization_received") is not True):
            raise ValueError("v7_plan_execution_state_invalid")
    return {"valid": True, "status": report["status"], "formal_case_count": 24, "provider_run_count": 30, "actual_provider_http_attempts": 30, "successful_provider_responses": 30, "bad_case_count": len(bad), "run_status_totals": totals}


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
