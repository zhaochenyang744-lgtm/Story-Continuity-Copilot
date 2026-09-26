"""Freeze the seen comparison candidate after its no-network preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "frozen-inputs.json"
BASE_HEAD = "c3bd54ab019447354e8b1387e16b9aca3258b4c9"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_paths() -> list[pathlib.Path]:
    return [HERE / name for name in (
        "RUBRIC.md", "PRECHECK_FAILURES.md", "build.py", "preflight.py", "score.py",
        "contract_probe.py", "api_score_probe.py", "test_offline.py", "write_lineage.py", "freeze.py",
        "cases.json", "actual-inputs.json", "contract-probe-results.json",
        "api-score-probe-results.json", "api-score-probe-results-v2.json", "v8-lineage.json",
    )] + sorted((HERE / "corpora").glob("*.json")) + [ROOT / name for name in (
        "backend/app/engine.py", "backend/app/v2_database.py", "backend/app/provider.py",
        "backend/app/brief_citations.py", "evaluation/v2_fixture_loader.py",
        "evaluation/case_sets/eval-set-v8-candidate.json",
        "backend/tests/test_g02_source_rendering.py", "backend/tests/test_v130_writing_analysis.py",
        "frontend/e2e/v130-g02-citation.spec.ts", "frontend/e2e/v130-writing-analysis.spec.ts",
    )]


def validate_assets() -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    capture = json.loads((HERE / "actual-inputs.json").read_text(encoding="utf-8"))
    contract = json.loads((HERE / "contract-probe-results.json").read_text(encoding="utf-8"))
    api = json.loads((HERE / "api-score-probe-results-v2.json").read_text(encoding="utf-8"))
    lineage = json.loads((HERE / "v8-lineage.json").read_text(encoding="utf-8"))
    if len(cases) != 24 or len({x["case_id"] for x in cases}) != 24 or len({x["corpus_key"] for x in cases}) != 4:
        raise RuntimeError("case_set_invalid")
    if capture["required_evidence_present_count"] != 24 or capture["real_provider_calls"] != 0 or capture["missing"]:
        raise RuntimeError("business_input_preflight_failed")
    if contract["validator_accepted"] != 24 or contract["score_pass_count"] != 24:
        raise RuntimeError("contract_probe_failed")
    if any(api[key] != 24 for key in ("case_count", "completed_count", "actual_content_equal_count", "score_pass_count")) or api["real_provider_calls"] != 0:
        raise RuntimeError("api_score_probe_failed")
    if lineage["old_case_count"] != 24 or lineage["retained_byte_identical_count"] != 0:
        raise RuntimeError("lineage_invalid")
    return {"case_count": 24, "class_counts": {name: sum(x["expected_class"] == name for x in cases)
            for name in ("conflict", "no_conflict", "insufficient_evidence")},
            "corpus_count": 4, "multi_evidence_conflicts": sum(x["expected_class"] == "conflict" and len(x["expected_evidence"]) >= 2 for x in cases),
            "multi_evidence_insufficient": sum(x["expected_class"] == "insufficient_evidence" and len(x["expected_evidence"]) >= 2 for x in cases)}


def freeze() -> None:
    if MANIFEST.exists():
        raise RuntimeError("frozen_inputs_already_exist")
    details = validate_assets()
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != BASE_HEAD:
        raise RuntimeError("git_base_changed")
    payload = {"version": "current-contract-compare-v1", "status": "seen_development_candidate",
               "frozen_at": datetime.now(timezone.utc).isoformat(), "git_base": BASE_HEAD,
               "real_provider_calls": 0, "quality_scored": False, "gold_independently_accepted": False,
               "details": details,
               "source_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in source_paths()}}
    with MANIFEST.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def verify() -> None:
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_assets()
    for name, digest in frozen["source_hashes"].items():
        path = ROOT / name
        if not path.exists() or sha(path) != digest:
            raise RuntimeError("frozen_hash_mismatch:" + name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    (freeze if args.command == "freeze" else verify)()
    print(json.dumps({"command": args.command, "ok": True}, ensure_ascii=False))
