"""Freeze the V5 live-run contract after the no-network 30-case preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

from evaluation.current_flash_v5 import build_cases, run
from evaluation.current_flash_v5.journal import write_x
from app.engine import CONTEXT_BRIEF_PROMPT_VERSION
from app.provider import CONTINUITY_PROMPT_VERSION, DeepSeekProvider

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "frozen-inputs.json"
BASE_HEAD = "7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2"
V3_MANIFEST_SHA = "0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths() -> list[pathlib.Path]:
    local = [HERE / name for name in ("PLAN.md", "build_cases.py", "cases.json", "inputs.py", "journal.py",
                                     "score.py", "run.py", "test_offline.py", "freeze.py")]
    prep = sorted(path for path in (HERE / "runs/prep-v5-03").rglob("*.json") if path.is_file())
    upstream = [ROOT / name for name in (
        "evaluation/current_contract_compare_v3/frozen-inputs.json",
        "evaluation/current_contract_compare_v3/cases.json",
        "evaluation/current_contract_compare_v3/score.py",
        "evaluation/current_contract_compare_v2/actual-inputs.json",
        "evaluation/current_contract_compare_v2/score.py",
        "evaluation/current_flash_v2/cases.json",
        "evaluation/current_flash_v4/cases.json",
        "evaluation/current_flash_v4/frozen-inputs.json",
        "evaluation/v2_fixture_loader.py",
        "backend/app/provider.py", "backend/app/engine.py", "backend/app/brief_citations.py",
        "backend/app/v2_database.py", "backend/app/main.py", "backend/app/seed_data.py",
        "backend/app/config.py", "backend/app/database.py", "backend/app/stage13.py",
    )] + sorted((ROOT / "evaluation/current_contract_compare_v2/corpora").glob("*.json"))
    return local + prep + upstream


def validate_assets() -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    if cases != build_cases.build() or len(cases["cases"]) != 30:
        raise RuntimeError("v5_case_set_drift")
    if sha(ROOT / "evaluation/current_contract_compare_v3/frozen-inputs.json") != V3_MANIFEST_SHA:
        raise RuntimeError("v3_manifest_drift")
    prep = HERE / "runs/prep-v5-03"
    summary = json.loads((prep / "summary.json").read_text(encoding="utf-8"))
    if (summary["logical_cases_finished"] != 30 or summary["post_attempt_start_records"] != 0 or
        summary["models_get_start_records"] != 0 or summary["service_stop"]):
        raise RuntimeError("v5_preparation_incomplete")
    audits = sorted(prep.glob("cases/[0-9][0-9]/input-audit/01.json"))
    requests = sorted(prep.glob("cases/[0-9][0-9]/requests/01.json"))
    bindings = sorted(prep.glob("cases/[0-9][0-9]/runtime-binding.json"))
    if tuple(map(len, (audits, requests, bindings))) != (30, 30, 30):
        raise RuntimeError("v5_capture_count_invalid")
    for case, audit_path, request_path in zip(cases["cases"], audits, requests):
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if (audit["case_id"] != case["case_id"] or request["case_id"] != case["case_id"] or
            audit["same_run_request_sha256"] != request["business_request_sha256"] or
            audit["database_binding"] != "matched_persisted_isolated_database"):
            raise RuntimeError("v5_same_run_capture_binding_invalid:" + case["case_id"])
    body = json.loads((prep / "cases/27/input-audit/01.json").read_text(encoding="utf-8"))
    dialogue = json.loads((prep / "cases/30/input-audit/01.json").read_text(encoding="utf-8"))
    if (body["draft_chars"], body["claim_available"], body["claim_selected"], body["claim_unselected"]) != (1980, 180, 8, 172):
        raise RuntimeError("v5_long_body_scope_invalid")
    if not dialogue["dialogue_two_complete_quotes"]:
        raise RuntimeError("v5_dialogue_claim_shape_invalid")
    workspace = json.loads((prep / "workspace-manifest.json").read_text(encoding="utf-8"))
    if workspace != run.workspace_inventory(run.WORKSPACES / "prep-v5-03") or workspace["database_count"] != 30:
        raise RuntimeError("v5_isolated_workspace_drift")
    return {"logical_cases": 30, "comparison": 24, "g02": 6,
            "same_run_request_captures": 30, "isolated_databases": 30,
            "preparation_post_attempts": 0, "preparation_models_get": 0,
            "dialogue_complete_quotes": 2, "long_body_available_selected_unselected": [180, 8, 172]}


def freeze() -> None:
    if MANIFEST.exists():
        raise RuntimeError("v5_already_frozen")
    details = validate_assets()
    head = subprocess.check_output(["git", "-c", "core.longpaths=true", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != BASE_HEAD:
        raise RuntimeError("git_base_changed")
    payload = {"version": "current-flash-v5", "status": "prepared_for_controller_technical_review",
               "frozen_at": datetime.now(timezone.utc).isoformat(), "git_base": BASE_HEAD,
               "model": "deepseek-flash", "base_url": "https://api.deepseek.com", "provider": "deepseek",
               "response_format": "json_object", "thinking": "disabled", "temperature": 0,
               "max_tokens": DeepSeekProvider.max_output_tokens,
               "timeout_seconds": DeepSeekProvider.timeout_seconds,
               "transport_retries": DeepSeekProvider.max_retries,
               "comparison_contract_evaluations_cap": 2, "g02_evaluations_cap": 1,
               "maximum_generation_post_attempts": run.MAX_POST, "maximum_models_get_attempts": 1,
               "service_stop": "HTTP400/401/403/404 immediately; two consecutive logical cases with any transport/service error",
               "comparison_prompt_version": CONTINUITY_PROMPT_VERSION,
               "g02_prompt_version": CONTEXT_BRIEF_PROMPT_VERSION,
               "fixture_settings": "Stage13Settings.for_test; isolated evaluation DB and no SMTP",
               "quality_scored": False, "real_provider_calls_this_round": 0,
               "details": details,
               "source_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in paths()}}
    write_x(MANIFEST, payload)


def verify() -> dict:
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_assets()
    head = subprocess.check_output(["git", "-c", "core.longpaths=true", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != BASE_HEAD:
        raise RuntimeError("git_base_changed")
    for relative, expected in frozen["source_hashes"].items():
        path = ROOT / relative
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError("v5_frozen_hash_mismatch:" + relative)
    if (frozen["maximum_generation_post_attempts"] != run.MAX_POST or
        frozen["max_tokens"] != DeepSeekProvider.max_output_tokens or
        frozen["timeout_seconds"] != DeepSeekProvider.timeout_seconds or
        frozen["transport_retries"] != DeepSeekProvider.max_retries or
        frozen["comparison_prompt_version"] != CONTINUITY_PROMPT_VERSION or
        frozen["g02_prompt_version"] != CONTEXT_BRIEF_PROMPT_VERSION):
        raise RuntimeError("v5_provider_parameter_drift")
    return frozen


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    (freeze if args.command == "freeze" else verify)()
    print(json.dumps({"command": args.command, "ok": True}, ensure_ascii=False))
