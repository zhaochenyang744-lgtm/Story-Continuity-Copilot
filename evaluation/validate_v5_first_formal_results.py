"""Fail-closed validator for the retained V5 first-formal execution evidence."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from typing import Any

from evaluation.metrics import aggregate
from evaluation.run_eval import gate


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results"
INTEGRITY_PATH = RESULTS / "v5-first-formal-post-run-integrity.json"
EXPECTED_INTEGRITY_SHA256 = "b90bdd187bf4434cb4244545432fd4e4afa80d0a609907a2fdf05e81ac10724c"
EXPECTED_ARTIFACTS = {
    "evaluation/results/eval-v5-first-formal-api-corpus-scan.json": "2a76e1671b624c6f375400fcb397c43c1b29b8b497c219b6fdbab4bcb22f4a31",
    "evaluation/results/eval-v5-first-formal-bad-cases.json": "27c25f0f1853a641cd3b90be40aed46e3576ec47370e8a8cb85f6a94f20956d7",
    "evaluation/results/eval-v5-first-formal-checkpoint.json": "d4e00e660b119985d48f1b7c45f30fe32512f92c0a62c041344b734e6842174e",
    "evaluation/results/eval-v5-first-formal-report.md": "dda0932918fc6df8987a8ac898db5a8451b18714df509ca7b0628ddf628ee9ec",
    "evaluation/results/eval-v5-first-formal-results.json": "9f24925966b16f5979ec18ea2277f99b19409b275b368b8e1ff8848b8e1403c1",
    "evaluation/results/eval-v5-first-formal-run-manifest.json": "1aab0415f28ba8d03ee52424c3da233c9d7adc21c0a307ebebe036fd5c199a41",
    "evaluation/results/eval-v5-first-formal-stability.json": "7af5781ece1b0d4b244318e1c2ae8416b99eef3a0e0fc84cfc0cf9b5074936b3",
}
EXPECTED_RUN_SOURCE_HASHES = {
    "backend\\app\\v2_database.py": "acfc10485136b94740d06fd6b371c825f6413c3e5694ab6a5dc10cdaa317e3d0",
    "backend\\app\\engine.py": "64c6863b0117059356791969637be669e9802879e78e74b13163033ca1b9b504",
    "backend\\app\\provider.py": "753e36570f7112a89321de4d3630dcc1e5e86afbfa5823c2965704c05c52d275",
    "evaluation\\case_sets\\eval-set-v5.json": "c79b61842f2fe1d2ff37a25cd40ce24310bf7270ec9528ab29b3e91d4fb76b30",
    "evaluation\\run_eval.py": "a2943b260d8d926c6529b3a2a7f097d5403c8bd1f7a666af52160f0aac217ccc",
    "evaluation\\manifests\\eval-set-v5-manifest.json": "914eb8697a7df668934cf0d9da69279523b1c3446ea96a5251ddb3bc062d6bd0",
    "evaluation\\fixtures\\eval-v5-corpus-manifest.json": "6c4f45022834f78b634ded5fc554d7437f7f1e14078b6b46abc8cb81dd3dd07b",
    "evaluation\\fixtures\\eval-v5-copper-orchard.json": "79cecdcb51016812ba9d02d2fb67e60d10ae9da77d5d05b5078fddf52d667473",
    "evaluation\\fixtures\\eval-v5-ember-observatory.json": "beb4b30ae4613c06f5c95ac82a06ef14a6c546faf32efab4fe15aaec8cfb61c8",
    "evaluation\\fixtures\\eval-v5-glass-marsh.json": "c8a913c2573f03dddb65dd74402f1f37e01d7db243aa85afc973604ec098063a",
    "evaluation\\fixtures\\eval-v5-reed-foundry.json": "12cfac0f67fee346483f6e878064ca6a6e9869653fbe6e66fc2adfa737700c3b",
    "evaluation\\v2_fixture_loader.py": "64557599a2f28e5a904044bef1ffb92a9cacd5a5fe1d1bb1d17efeb4834f7dd9",
}
FROZEN_RUN_INPUT_PATHS = {
    "evaluation\\case_sets\\eval-set-v5.json",
    "evaluation\\manifests\\eval-set-v5-manifest.json",
    "evaluation\\fixtures\\eval-v5-corpus-manifest.json",
    "evaluation\\fixtures\\eval-v5-copper-orchard.json",
    "evaluation\\fixtures\\eval-v5-ember-observatory.json",
    "evaluation\\fixtures\\eval-v5-glass-marsh.json",
    "evaluation\\fixtures\\eval-v5-reed-foundry.json",
}


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def validate() -> dict[str, Any]:
    if sha256_file(INTEGRITY_PATH) != EXPECTED_INTEGRITY_SHA256:
        raise ValueError("v5_post_run_integrity_hash_mismatch")
    integrity = json.loads(INTEGRITY_PATH.read_text(encoding="utf-8"))
    if (
        integrity.get("schema_version") != "scc-evaluation-post-run-integrity-v1"
        or integrity.get("evaluation") != "scc-web-demo-eval-v5-first-formal"
        or integrity.get("integrity_status") != "retained_baseline"
        or integrity.get("raw_provider_content_retained") is not False
    ):
        raise ValueError("v5_post_run_integrity_schema_invalid")
    retained = integrity.get("retained_artifacts", {})
    files = retained.get("files")
    if retained.get("count") != 7 or not isinstance(files, list) or len(files) != 7:
        raise ValueError("v5_retained_artifact_count_invalid")
    recorded = {item.get("path"): item for item in files if isinstance(item, dict)}
    if set(recorded) != set(EXPECTED_ARTIFACTS):
        raise ValueError("v5_retained_artifact_paths_invalid")
    for relative, expected_hash in EXPECTED_ARTIFACTS.items():
        path = ROOT / relative
        item = recorded[relative]
        if not path.is_file() or item.get("sha256") != expected_hash or sha256_file(path) != expected_hash or item.get("size") != path.stat().st_size:
            raise ValueError("v5_retained_artifact_hash_mismatch")

    report = load("evaluation/results/eval-v5-first-formal-results.json")
    cases = report.get("formal_case_results")
    if report.get("evaluation") != "scc-web-demo-eval-v5-first-formal" or report.get("execution_kind") != "first_valid_formal" or report.get("status") != "gate_failed" or report.get("abort_reason") is not None or not isinstance(cases, list) or len(cases) != 24:
        raise ValueError("v5_formal_report_shape_invalid")
    if len({item.get("case_id") for item in cases}) != 24 or len({item.get("run_id") for item in cases}) != 24:
        raise ValueError("v5_formal_run_identity_invalid")
    if any(item.get("terminal_status") != "completed" or item.get("terminal_error_code") is not None for item in cases):
        raise ValueError("v5_formal_terminal_outcome_changed")
    recalculated_metrics = aggregate(cases)
    manifest = load("evaluation/manifests/eval-set-v5-manifest.json")
    safety = load("evaluation/results/fail-closed-contract.json")
    passed, checks = gate(recalculated_metrics, safety, manifest["required_thresholds"])
    if passed or report.get("metrics") != recalculated_metrics or report.get("gate_checks") != checks:
        raise ValueError("v5_formal_metrics_or_gate_mismatch")

    checkpoint = load("evaluation/results/eval-v5-first-formal-checkpoint.json")
    checkpoint_cases = checkpoint.get("cases")
    if checkpoint.get("case_set_sha256") != manifest["case_set"]["canonical_sha256"] or not isinstance(checkpoint_cases, dict) or len(checkpoint_cases) != 24:
        raise ValueError("v5_checkpoint_shape_invalid")
    if any(item.get("state") != "completed" or item.get("result", {}).get("run_id") != item.get("run_id") for item in checkpoint_cases.values()):
        raise ValueError("v5_checkpoint_completion_invalid")

    stability = load("evaluation/results/eval-v5-first-formal-stability.json")
    rows = stability.get("rows")
    selected = set(manifest["stability_protocol"]["representative_case_ids"])
    if not isinstance(rows, list) or {item.get("case_id") for item in rows} != selected or any(len(item.get("runs", [])) != 3 for item in rows):
        raise ValueError("v5_stability_shape_invalid")
    stability_run_ids = [run.get("run_id") for row in rows for run in row["runs"]]
    if len(stability_run_ids) != 9 or len(set(stability_run_ids)) != 9:
        raise ValueError("v5_stability_run_identity_invalid")
    if any(not item.get("stability", {}).get("quality_stability_established") or item.get("stability", {}).get("terminal_failure_count") != 0 for item in rows):
        raise ValueError("v5_stability_quality_not_established")

    bad_cases = load("evaluation/results/eval-v5-first-formal-bad-cases.json")
    allowed_bad_keys = {"case_id", "expected_class", "predicted_class", "root_cause", "rationale", "evidence"}
    frozen_bad_rows = bad_cases.get("bad_cases")
    if not isinstance(frozen_bad_rows, list) or len(frozen_bad_rows) != 4 or any(set(item) != allowed_bad_keys for item in frozen_bad_rows):
        raise ValueError("v5_bad_case_payload_invalid")
    scan = load("evaluation/results/eval-v5-first-formal-api-corpus-scan.json")
    if scan.get("unresolved") != 0 or any(scan.get("categories", {}).values()):
        raise ValueError("v5_api_scan_not_clean")

    run_manifest = load("evaluation/results/eval-v5-first-formal-run-manifest.json")
    expected_execution = {
        "provider_run_records": 30,
        "actual_provider_http_attempts": 30,
        "successful_provider_responses": 30,
        "terminal_status_counts": {"completed": 30},
        "input_tokens_returned": 33002,
        "output_tokens_returned": 4161,
        "cost": "unavailable",
        "elapsed_ms": 66304,
    }
    if run_manifest.get("evaluation") != report["evaluation"] or run_manifest.get("execution_kind") != "first_valid_formal" or run_manifest.get("status") != "gate_failed" or run_manifest.get("case_set_sha256") != manifest["case_set"]["canonical_sha256"] or run_manifest.get("provider_configuration") != "environment_only_not_recorded" or run_manifest.get("provider_execution") != expected_execution or report.get("run_metadata", {}).get("provider_execution") != expected_execution:
        raise ValueError("v5_run_manifest_shape_invalid")
    recorded_source_hashes = run_manifest.get("source_file_hashes")
    if recorded_source_hashes != EXPECTED_RUN_SOURCE_HASHES:
        raise ValueError("v5_run_source_hash_record_mismatch")
    for relative in FROZEN_RUN_INPUT_PATHS:
        if sha256_file(ROOT / relative) != EXPECTED_RUN_SOURCE_HASHES[relative]:
            raise ValueError("v5_frozen_run_input_hash_mismatch")

    workspaces = integrity.get("fixture_workspaces", {})
    sqlite_files = workspaces.get("sqlite_files")
    if workspaces.get("root") != "evaluation/fixture-workspaces/scc-web-demo-eval-v5-first-formal" or workspaces.get("sqlite_count") != 24 or workspaces.get("run_status_totals") != {"completed": 30} or not isinstance(sqlite_files, list) or len(sqlite_files) != 24:
        raise ValueError("v5_workspace_summary_invalid")
    for item in sqlite_files:
        path = ROOT / workspaces["root"] / item["workspace_key"] / "runtime" / "data" / "demo.sqlite3"
        if sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("v5_workspace_hash_mismatch")
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            statuses = dict(connection.execute("SELECT status, COUNT(*) FROM v2_runs GROUP BY status"))
        finally:
            connection.close()
        if statuses != item.get("run_status"):
            raise ValueError("v5_workspace_status_mismatch")

    return {
        "valid": True,
        "status": report["status"],
        "formal_case_count": 24,
        "stability_additional_call_count": 6,
        "provider_run_count": 30,
        "actual_provider_http_attempts": 30,
        "provider_successful_result_count": 30,
        "terminal_status_counts": {"completed": 30},
        "terminal_error_counts": {},
        "input_tokens_returned": 33002,
        "output_tokens_returned": 4161,
        "cost": "unavailable",
        "elapsed_ms": 66304,
        "artifact_count": 8,
        "fixture_sqlite_count": 24,
        "api_scan_unresolved": 0,
        "gate_checks": checks,
    }


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
