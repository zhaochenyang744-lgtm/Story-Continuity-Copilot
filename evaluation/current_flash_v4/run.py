"""Create-only G02 real-Flash repair check. Reuses V2 observation code, never its executor."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from evaluation.current_flash_v2 import run as prior
from app.engine import CONTEXT_BRIEF_PROMPT_VERSION
from app.provider import DeepSeekProvider

MANIFEST = HERE / "frozen-inputs.json"
RESULTS = HERE / "runs"
LOCAL_EVIDENCE = ROOT / "artifacts/current_flash_v4"
BASE_HEAD = "c3bd54ab019447354e8b1387e16b9aca3258b4c9"


def source_paths() -> list[pathlib.Path]:
    return [HERE / name for name in ("PLAN.md", "cases.json", "run.py", "test_offline.py")] + [
        ROOT / name for name in (
            "evaluation/current_flash_v2/run.py", "evaluation/current_flash_v2/cases.json",
            "backend/app/brief_citations.py", "backend/app/engine.py", "backend/app/v2_database.py",
            "backend/app/provider.py", "backend/app/main.py", "backend/app/seed_data.py",
            "backend/app/config.py", "backend/app/database.py", "backend/app/stage13.py",
            "backend/tests/test_g02_source_rendering.py",
            "backend/tests/test_v130_writing_analysis.py",
            "backend/tests/test_v140_real_ai_contract_repairs.py",
            "backend/tests/e2e_app.py", "frontend/e2e/v130-g02-citation.spec.ts",
        )
    ]


def validate_cases(cases: dict) -> None:
    assert cases["schema_version"] == "current-flash-v4-g02-cases"
    rows = cases["g02"]
    assert len(rows) == len({x["id"] for x in rows}) == len({prior.case_body(x) for x in rows}) == 6
    old = json.loads((ROOT / "evaluation/current_flash_v2/cases.json").read_text(encoding="utf-8"))["g02"]
    assert [(x["id"], prior.case_body(x)) for x in rows[:4]] == [
        (x["id"], prior.case_body(x)) for x in old
    ]
    assert all(x["id"].startswith("g02-") and x["expected"] for x in rows)


def freeze() -> None:
    if MANIFEST.exists():
        raise RuntimeError("frozen_inputs_already_exist")
    validate_cases(json.loads((HERE / "cases.json").read_text(encoding="utf-8")))
    prior.write_new(MANIFEST, {
        "version": "current-flash-v4-g02", "frozen_at": prior.stamp(),
        "source_hashes": {str(p.relative_to(ROOT)).replace("\\", "/"): prior.sha(p) for p in source_paths()},
        "git_base": BASE_HEAD, "model": prior.MODEL, "base_url": prior.BASE_URL,
        "provider": "deepseek", "thinking": "disabled", "temperature": 0,
        "max_tokens": DeepSeekProvider.max_output_tokens,
        "provider_timeout_seconds": DeepSeekProvider.timeout_seconds,
        "provider_max_retries": DeepSeekProvider.max_retries,
        "prompt_version": CONTEXT_BRIEF_PROMPT_VERSION,
        "logical_run_count": 6, "families": {"g02": 6},
        "prior": {"run": "flash-v2-20260926-01", "post_count": 57, "models_count": 2},
        "scoring": "First model and source-rendered final product separately; per-item semantic and own-citation review, no aggregate accuracy claim.",
        "classification": "exposed_development_regression",
    })


def verify_freeze() -> dict:
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != BASE_HEAD:
        raise RuntimeError("git_base_changed")
    for name, expected in frozen["source_hashes"].items():
        if not (ROOT / name).exists() or prior.sha(ROOT / name) != expected:
            raise RuntimeError("frozen_hash_mismatch:" + name)
    if frozen["model"] != prior.MODEL or frozen["base_url"] != prior.BASE_URL:
        raise RuntimeError("provider_contract_mismatch")
    validate_cases(json.loads((HERE / "cases.json").read_text(encoding="utf-8")))
    return frozen


def run(run_id: str) -> None:
    verify_freeze()
    if not run_id.startswith("flash-v4-g02-") or not all(ch.isalnum() or ch in "-_" for ch in run_id):
        raise RuntimeError("run_id_invalid")
    run_dir, work_root = RESULTS / run_id, LOCAL_EVIDENCE / run_id
    if run_dir.exists() or work_root.exists():
        raise RuntimeError("run_id_or_workspace_already_exists")
    run_dir.mkdir(parents=True, exist_ok=False)
    work_root.mkdir(parents=True, exist_ok=False)
    prior.write_new(run_dir / "start.json", {
        "run_id": run_id, "started_at": prior.stamp(), "frozen_manifest_sha256": prior.sha(MANIFEST),
        "git_base": BASE_HEAD, "model": prior.MODEL, "provider": "deepseek",
        "local_evidence_root": str(work_root), "cost": "unavailable_unless_returned",
    })
    provider = prior.configured_provider()
    prior.preflight_models(provider, run_dir)
    rows, failures, consecutive_service_errors = [], [], 0
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["g02"]
    for index, case in enumerate(cases, 1):
        case_id = case["id"]
        try:
            record = prior.g02_one(case, provider, work_root / case_id)
            record["input_sha256"] = hashlib.sha256(json.dumps(case, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            record["source_case_ref"] = "evaluation/current_flash_v4/cases.json"
            record["business_input_count"] = len(record["business_requests"])
            consecutive_service_errors = consecutive_service_errors + 1 if prior.service_failure(record) else 0
            rows.append(record)
            prior.write_new(run_dir / "cases" / f"{index:02d}-{case_id}.json", record)
            if prior.auth_or_model_rejection(record) or consecutive_service_errors >= 2:
                failures.append({"case_id": case_id, "type": "service_stop",
                                 "consecutive_service_errors": consecutive_service_errors})
                break
        except Exception as error:
            failure = {"family": "g02", "case_id": case_id, "error_type": type(error).__name__,
                       "http_attempts": [x for x in provider.http_events if x["case_id"] == provider.case_id],
                       "business_requests": [x for x in provider.business_requests if x["case_id"] == provider.case_id],
                       "model_outputs": [x for x in provider.parsed if x["case_id"] == provider.case_id]}
            failures.append(failure)
            prior.write_new(run_dir / "failures" / f"{index:02d}-{case_id}.json", failure)
            break
    events = provider.http_events
    prior.write_new(run_dir / "workspace-manifest.json", prior.workspace_manifest(work_root))
    prompt_known = [e["usage"]["prompt_tokens"] for e in events if e.get("usage") and e["usage"]["prompt_tokens"] is not None]
    completion_known = [e["usage"]["completion_tokens"] for e in events if e.get("usage") and e["usage"]["completion_tokens"] is not None]
    complete = bool(events) and all(e["usage_status"] == "complete" for e in events)
    prior.write_new(run_dir / "summary.json", {
        "run_id": run_id, "ended_at": prior.stamp(), "executed_case_records": len(rows),
        "actual_http_dispatches": len(events), "successful_http_responses": sum(e["status"] == 200 for e in events),
        "complete_usage_attempts": sum(e["usage_status"] == "complete" for e in events),
        "usage_unknown_attempts": sum(e["usage_status"] != "complete" for e in events),
        "known_prompt_tokens_partial_sum": sum(prompt_known),
        "known_completion_tokens_partial_sum": sum(completion_known),
        "complete_total_usage_available": complete,
        "prompt_tokens_total": sum(prompt_known) if complete else None,
        "completion_tokens_total": sum(completion_known) if complete else None,
        "cost": "unavailable", "failures": failures, "all_attempt_metadata": events,
        "open_ended_semantic_review": "pending_independent_review",
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify", "run"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "verify":
        verify_freeze()
    else:
        if not args.run_id:
            raise SystemExit("--run-id required")
        run(args.run_id)
    print(json.dumps({"command": args.command, "ok": True, "run_id": args.run_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
