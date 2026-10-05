"""Diagnostic rerun of the spent V9 held-out set after the thinking-budget change.

This is NOT a gate run. The V9 first-valid formal result stays gate_failed and
its files are never touched. The rerun uses the same frozen case set, product
chain, run_case/build_case_result, metrics and gate thresholds, with its own
checkpoint and output under evaluation/results/eval-v9-diagnostic-*.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from evaluation.execute_v9_first_formal import validate_environment
from evaluation.metrics import aggregate
from evaluation.run_eval import SAFETY, ApiResponseScanner, FormalCheckpoint, gate, run_case
from evaluation.v2_fixture_loader import V9_CORPUS_PATHS, fixture_runtime_at

CASE_SET = ROOT / "evaluation/case_sets/eval-set-v9.json"
MANIFEST = ROOT / "evaluation/manifests/eval-set-v9-manifest.json"


def run(run_id: str) -> dict:
    out = ROOT / "evaluation/results" / f"eval-v9-diagnostic-{run_id}.json"
    checkpoint_path = ROOT / "evaluation/results" / f"eval-v9-diagnostic-{run_id}-checkpoint.json"
    if out.exists() or checkpoint_path.exists():
        raise FileExistsError("diagnostic_run_identity_already_exists")
    provider = validate_environment()
    cases = json.loads(CASE_SET.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checkpoint = FormalCheckpoint(checkpoint_path, manifest["case_set"]["canonical_sha256"])
    scanner, results = ApiResponseScanner(), []
    with tempfile.TemporaryDirectory(prefix="scc-eval-v9-diagnostic-") as temporary:
        for index, case in enumerate(cases["cases"]):
            runtime = fixture_runtime_at(pathlib.Path(temporary) / f"{index:02d}", case["corpus_key"], provider, V9_CORPUS_PATHS)
            try:
                result, _ = run_case(checkpoint, runtime.client, case, scanner, preloaded_project_id=runtime.identity.project_id)
            finally:
                runtime.client.close()
            results.append(result)
    metrics = aggregate(results)
    passed, checks = gate(metrics, json.loads(SAFETY.read_text(encoding="utf-8")), manifest["required_thresholds"])
    report = {"kind": "diagnostic_rerun_not_gate", "run_id": run_id, "diagnostic_gate_status": "would_pass" if passed else "would_fail",
              "formal_v9_status_unchanged": "gate_failed", "gate_checks": checks, "metrics": metrics,
              "terminal": {f"{r['terminal_status']}:{r['terminal_error_code']}": sum(1 for x in results if (x["terminal_status"], x["terminal_error_code"]) == (r["terminal_status"], r["terminal_error_code"])) for r in results},
              "provider_http_attempts": provider.request_attempts, "stability_protocol": "not_run_in_diagnostic",
              "case_results": results}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    report = run(parser.parse_args().run_id)
    print(json.dumps({k: report[k] for k in ("diagnostic_gate_status", "terminal", "gate_checks", "provider_http_attempts")}, ensure_ascii=False, indent=2))
