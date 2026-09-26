"""Freeze V3 incremental metadata, scorer, and create-only offline records."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

from evaluation.current_contract_compare_v3 import run

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "frozen-inputs.json"
BASE_HEAD = "c3bd54ab019447354e8b1387e16b9aca3258b4c9"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_paths() -> list[pathlib.Path]:
    local = [HERE / name for name in ("RUBRIC.md", "HISTORY_GAP.md", "build.py", "cases.json",
                                     "score.py", "run.py", "controls.py", "test_v3.py", "freeze.py")]
    runs = sorted(path for path in (HERE / "runs").rglob("*.json") if path.is_file())
    upstream = [ROOT / name for name in (
        "evaluation/current_contract_compare_v2/frozen-inputs.json",
        "evaluation/current_contract_compare_v2/cases.json",
        "evaluation/current_contract_compare_v2/actual-inputs.json",
        "evaluation/current_contract_compare_v2/api-score-probe-results-v2.json",
        "evaluation/current_contract_compare_v2/score.py",
        "evaluation/current_contract_compare_v1/frozen-inputs.json",
        "docs/g02-citation-repair-evidence/independent-round3-root/ACCEPTANCE.md",
        "docs/g02-citation-repair-evidence/independent-round3-root/v2-preservation-final.json",
        "backend/app/engine.py", "backend/app/provider.py",
    )]
    return local + runs + upstream


def validate_assets() -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    run.verify_v2(cases)
    summary = json.loads((HERE / "runs/final-offline-rescore/summary.json").read_text(encoding="utf-8"))
    controls = json.loads((HERE / "runs/targeted-controls-02/controls.json").read_text(encoding="utf-8"))
    if len(cases["cases"]) != 24 or summary["saved_record_count"] != 26 or summary["raw_first_machine_pass"] != 19 or summary["final_machine_pass"] != 19:
        raise RuntimeError("v3_rescore_invalid")
    if summary["new_api_runs"] != 0 or summary["real_provider_calls"] != 0 or summary["raw_repair_present"] != 0:
        raise RuntimeError("v3_run_boundary_invalid")
    if controls["control_count"] != 20 or controls["passed_count"] != 20 or controls["new_api_runs"] != 0:
        raise RuntimeError("v3_controls_invalid")
    raw_failures = [x for x in controls["rows"] if x["control"].startswith("raw_")]
    if len(raw_failures) != 5 or any(x["raw_full_validator"] != "rejected" or
                                    "raw_target_or_category_mismatch" in x["raw_errors"] for x in raw_failures):
        raise RuntimeError("v3_raw_controls_confounded")
    return {"case_count": 24, "saved_v2_records_rescored": 26,
            "historical_raw_pass": 19, "historical_final_pass": 19,
            "historical_category_deltas": len(summary["category_delta_rows"]),
            "targeted_controls_passed": 20, "new_api_runs": 0, "real_provider_calls": 0}


def freeze() -> None:
    if MANIFEST.exists():
        raise RuntimeError("v3_already_frozen")
    details = validate_assets()
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != BASE_HEAD:
        raise RuntimeError("git_base_changed")
    payload = {"version": "current-contract-compare-v3", "status": "seen_development_incremental",
               "frozen_at": datetime.now(timezone.utc).isoformat(), "git_base": BASE_HEAD,
               "real_provider_calls": 0, "new_api_runs": 0, "quality_scored": False,
               "gold_independently_accepted": False, "details": details,
               "source_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in source_paths()}}
    with MANIFEST.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def verify() -> None:
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_assets()
    for name, digest in frozen["source_hashes"].items():
        path = ROOT / name
        if not path.is_file() or sha(path) != digest:
            raise RuntimeError("v3_frozen_hash_mismatch:" + name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    (freeze if args.command == "freeze" else verify)()
    print(json.dumps({"command": args.command, "ok": True}))
