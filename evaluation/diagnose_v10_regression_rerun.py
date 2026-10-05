"""Diagnostic regression rerun of the spent V10 held-out set on the current code.

This is NOT a gate run. The V10 first formal result (gate_passed) and its files are never touched.
It reuses the frozen V10 case set, product chain, run_case, metrics and both threshold sets to
check that a review-prompt change does not regress the gated behaviour. Output goes to
evaluation/results/eval-v10-diagnostic-<run-id>.json.
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

from app.engine import PROMPT_VERSION
from evaluation.build_v10_formal_assets import CASE_SET, HISTORICAL_THRESHOLDS, MANIFEST
from evaluation.execute_v10_first_formal import validate_environment
from evaluation.metrics import aggregate
from evaluation.run_eval import SAFETY, ApiResponseScanner, FormalCheckpoint, gate, run_case
from evaluation.v2_fixture_loader import V10_CORPUS_PATHS, fixture_runtime_at


def run_selected(run_id: str, case_ids: list[str], repeats: int) -> dict:
    """Repeat only the named cases; reports per-attempt outcomes, never gate metrics."""
    out = ROOT / "evaluation/results" / f"eval-v10-diagnostic-{run_id}.json"
    if out.exists():
        raise FileExistsError("diagnostic_run_identity_already_exists")
    provider = validate_environment()
    cases = [case for case in json.loads(CASE_SET.read_text(encoding="utf-8"))["cases"] if case["case_id"] in case_ids]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    attempts = []
    with tempfile.TemporaryDirectory(prefix="scc-eval-v10-selected-") as temporary:
        for attempt in range(repeats):
            checkpoint = FormalCheckpoint(pathlib.Path(temporary) / f"checkpoint-{attempt}.json", manifest["case_set"]["canonical_sha256"])
            for index, case in enumerate(cases):
                runtime = fixture_runtime_at(pathlib.Path(temporary) / f"{attempt:02d}-{index:02d}", case["corpus_key"], provider, V10_CORPUS_PATHS)
                try:
                    result, _ = run_case(checkpoint, runtime.client, case, ApiResponseScanner(), preloaded_project_id=runtime.identity.project_id)
                finally:
                    runtime.client.close()
                row = {"case": case["case_id"], "attempt": attempt, "expected": result["expected_class"], "predicted": result["predicted_class"],
                       "status": result["terminal_status"], "error": result["terminal_error_code"], "latency_ms": result.get("latency_ms")}
                attempts.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    report = {"kind": "diagnostic_selected_cases_not_gate", "run_id": run_id, "prompt_version": PROMPT_VERSION, "attempts": attempts}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def run(run_id: str) -> dict:
    out = ROOT / "evaluation/results" / f"eval-v10-diagnostic-{run_id}.json"
    checkpoint_path = ROOT / "evaluation/results" / f"eval-v10-diagnostic-{run_id}-checkpoint.json"
    if out.exists() or checkpoint_path.exists():
        raise FileExistsError("diagnostic_run_identity_already_exists")
    provider = validate_environment()
    cases = json.loads(CASE_SET.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checkpoint = FormalCheckpoint(checkpoint_path, manifest["case_set"]["canonical_sha256"])
    scanner, results = ApiResponseScanner(), []
    with tempfile.TemporaryDirectory(prefix="scc-eval-v10-diagnostic-") as temporary:
        for index, case in enumerate(cases["cases"]):
            runtime = fixture_runtime_at(pathlib.Path(temporary) / f"{index:02d}", case["corpus_key"], provider, V10_CORPUS_PATHS)
            try:
                result, _ = run_case(checkpoint, runtime.client, case, scanner, preloaded_project_id=runtime.identity.project_id)
            finally:
                runtime.client.close()
            results.append(result)
            print(json.dumps({"case": case.get("case_id") or case.get("id"), "status": result["terminal_status"],
                              "error": result["terminal_error_code"]}, ensure_ascii=False), flush=True)
    metrics = aggregate(results)
    safety = json.loads(SAFETY.read_text(encoding="utf-8"))
    passed, checks = gate(metrics, safety, manifest["required_thresholds"])
    historical_passed, historical_checks = gate(metrics, safety, HISTORICAL_THRESHOLDS)
    report = {"kind": "diagnostic_rerun_not_gate", "run_id": run_id, "prompt_version": PROMPT_VERSION,
              "diagnostic_gate_status": "would_pass" if passed else "would_fail",
              "historical_gate_status": "would_pass" if historical_passed else "would_fail",
              "formal_v10_status_unchanged": "gate_passed", "gate_checks": checks, "historical_gate_checks": historical_checks,
              "metrics": metrics,
              "terminal": {f"{r['terminal_status']}:{r['terminal_error_code']}": sum(1 for x in results if (x["terminal_status"], x["terminal_error_code"]) == (r["terminal_status"], r["terminal_error_code"])) for r in results},
              "provider_http_attempts": provider.request_attempts, "stability_protocol": "not_run_in_diagnostic",
              "case_results": results}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.only:
        run_selected(args.run_id, args.only, args.repeats)
        raise SystemExit(0)
    report = run(args.run_id)
    print(json.dumps({k: report[k] for k in ("diagnostic_gate_status", "historical_gate_status", "terminal", "provider_http_attempts")},
                     ensure_ascii=False, indent=2))
