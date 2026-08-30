"""Read-only fail-closed validator for V8's retained first-valid formal run."""
from __future__ import annotations

import json
import pathlib
import sqlite3

from evaluation.post_run_integrity import sha256_file
from evaluation.scan_v8_retained import scan as scan_retained
from evaluation.validate_eval_set import canonical_sha256

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"; INTEGRITY = RESULTS / "v8-first-formal-post-run-integrity.json"
CASE_HASH = "6f85776fbab6bc7caa099e6132d2d8f9c65730bfc176f40033ca036b2f9e0c33"
ARTIFACTS = {f"evaluation/results/eval-v8-first-formal-{suffix}" for suffix in ("api-corpus-scan.json", "bad-cases.json", "checkpoint.json", "report.md", "results.json", "run-manifest.json", "stability.json")}

def _load(relative: str): return json.loads((ROOT / relative).read_text(encoding="utf-8"))

def validate() -> dict:
    integrity = _load("evaluation/results/v8-first-formal-post-run-integrity.json")
    if (integrity.get("schema_version"), integrity.get("evaluation"), integrity.get("integrity_status"), integrity.get("raw_provider_content_retained")) != ("scc-evaluation-post-run-integrity-v1", "scc-web-demo-eval-v8-first-formal", "retained_baseline", False): raise ValueError("v8_post_integrity_schema_invalid")
    files = integrity.get("retained_artifacts", {}).get("files")
    if integrity.get("retained_artifacts", {}).get("count") != 7 or not isinstance(files, list) or {item.get("path") for item in files} != ARTIFACTS: raise ValueError("v8_post_artifact_set_invalid")
    for item in files:
        path = ROOT / item["path"]
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"): raise ValueError("v8_post_artifact_hash_invalid")
    report = _load("evaluation/results/eval-v8-first-formal-results.json"); execution = report.get("run_metadata", {}).get("provider_execution", {})
    if (report.get("evaluation"), report.get("execution_kind"), report.get("status"), report.get("abort_reason"), report.get("case_set_sha256")) != ("scc-web-demo-eval-v8-first-formal", "first_valid_formal", "gate_failed", None, CASE_HASH) or canonical_sha256(_load("evaluation/case_sets/eval-set-v8.json")) != CASE_HASH or len(report.get("formal_case_results", [])) != 24: raise ValueError("v8_result_shape_invalid")
    if (execution.get("provider_run_records"), execution.get("actual_provider_http_attempts"), execution.get("successful_provider_responses"), execution.get("terminal_status_counts")) != (30, 30, 30, {"completed": 30}) or report.get("run_metadata", {}).get("provider_configuration") != "environment_only_not_recorded": raise ValueError("v8_provider_execution_invalid")
    stability = _load("evaluation/results/eval-v8-first-formal-stability.json").get("rows")
    if not isinstance(stability, list) or len(stability) != 3 or any(len(row.get("runs", [])) != 3 or row.get("stability", {}).get("terminal_failure_count", 0) or row.get("stability", {}).get("quality_stability_established") is not True for row in stability): raise ValueError("v8_stability_invalid")
    bad = _load("evaluation/results/eval-v8-first-formal-bad-cases.json").get("bad_cases")
    if not isinstance(bad, list) or any(not item.get("failure_dimensions") or set(item.get("category", {})) != {"expected", "predicted"} for item in bad): raise ValueError("v8_bad_case_audit_invalid")
    forbidden = ("target_draft", "prompt", "raw_provider_body", "provider_body", "chain_of_thought", "reasoning_content")
    if any(any(token in json.dumps(item, ensure_ascii=False).casefold() for token in forbidden) for item in bad) or _load("evaluation/results/eval-v8-first-formal-api-corpus-scan.json").get("unresolved") != 0: raise ValueError("v8_sensitive_or_api_scan_invalid")
    retained = scan_retained()
    if not retained.get("clean"): raise ValueError("v8_retained_sensitive_scan_invalid")
    manifest = _load("evaluation/results/eval-v8-first-formal-run-manifest.json")
    if manifest.get("provider_execution") != execution or manifest.get("status") != "gate_failed" or manifest.get("execution_kind") != "first_valid_formal": raise ValueError("v8_run_manifest_invalid")
    workspaces = integrity.get("fixture_workspaces", {}); items = workspaces.get("sqlite_files"); totals = {}
    if workspaces.get("root") != "evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal" or workspaces.get("sqlite_count") != 24 or not isinstance(items, list) or len(items) != 24: raise ValueError("v8_workspace_shape_invalid")
    for item in items:
        path = ROOT / workspaces["root"] / item["workspace_key"] / "runtime/data/demo.sqlite3"
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"): raise ValueError("v8_workspace_hash_invalid")
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try: statuses = dict(connection.execute("SELECT status, COUNT(*) FROM v2_runs GROUP BY status"))
        finally: connection.close()
        if statuses != item.get("run_status"): raise ValueError("v8_workspace_status_invalid")
        for status, count in statuses.items(): totals[status] = totals.get(status, 0) + count
    if totals != {"completed": 30} or totals != workspaces.get("run_status_totals"): raise ValueError("v8_workspace_total_invalid")
    plan = _load("evaluation/manifests/eval-v8-first-formal-plan.json")
    if (plan.get("status"), plan.get("formal_run_executed"), plan.get("provider_calls"), plan.get("real_provider_authorization_received")) != ("gate_failed", True, 30, True): raise ValueError("v8_plan_post_run_invalid")
    return {"valid": True, "status": "gate_failed", "formal_case_count": 24, "provider_run_count": 30, "actual_provider_http_attempts": 30, "successful_provider_responses": 30, "bad_case_count": len(bad), "run_status_totals": totals, "retained_scan": retained}

if __name__ == "__main__": print(json.dumps(validate(), ensure_ascii=False, indent=2))
