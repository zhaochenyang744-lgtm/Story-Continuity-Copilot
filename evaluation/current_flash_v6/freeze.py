"""Freeze the V6 34-case input and source closure before any real dispatch."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

from evaluation.current_flash_v6 import build_cases, run
from evaluation.current_flash_v6.build_cases import write_x
from app.provider import CONTINUITY_PROMPT_VERSION, DeepSeekProvider

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "frozen-inputs.json"
BASE_HEAD = "7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2"
PREP = HERE / "runs/prep-v6-02"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths() -> list[pathlib.Path]:
    local = [HERE / name for name in (
        "CONTRACT.md", "DESIGN-FREEZE.json", "DESIGN-ADDENDUM.md", "DESIGN-ADDENDUM-FREEZE.json",
        "DESIGN-ADDENDUM-02.md", "DESIGN-ADDENDUM-02-FREEZE.json", "INPUT-ADAPTATION.md",
        "SCORING-POLICY.md", "SCORING-ADDENDUM.md", "SCORING-ADDENDUM-02.md",
        "SCORING-ADDENDUM-03.md", "CORE-OFFLINE-HANDOFF.md", "CORE-HASH-CORRECTION.md",
        "CORE-INCREMENTAL-02.md", "CORE-INCREMENTAL-03.md",
        "build_cases.py", "cases.json", "cases-v2.json", "inputs.py", "score.py", "run.py", "test_offline.py",
        "live_guard.py", "freeze.py")]
    local += sorted((HERE / "corpora").glob("*.json"))
    local += sorted((HERE / "corpora-v2").glob("*.json"))
    local += sorted(path for path in (HERE / "runs/prep-v6-01").rglob("*.json") if path.is_file())
    local += sorted(path for path in PREP.rglob("*.json") if path.is_file())
    names = (
        "docs/flash-v6-independent-acceptance-evidence/BASELINE.json",
        "docs/flash-v6-independent-acceptance-evidence/semantics/criteria.md",
        "docs/flash-v6-independent-acceptance-evidence/semantics/control-matrix.json",
        "docs/flash-v6-independent-acceptance-evidence/semantics/input-preflight-02-review.json",
        "docs/flash-v6-independent-acceptance-evidence/semantics/input-preflight-02-review.md",
        "docs/flash-v6-independent-acceptance-evidence/semantics/prompt-preflight-02-receipt.json",
        "docs/flash-v6-independent-acceptance-evidence/semantics/prompt-preflight-02-receipt.md",
        "docs/flash-v6-independent-acceptance-evidence/semantics/scoring-role-review.json",
        "docs/flash-v6-independent-acceptance-evidence/semantics/scoring-role-review.md",
        "docs/flash-v6-independent-acceptance-evidence/engineering/criteria.md",
        "docs/flash-v6-independent-acceptance-evidence/g02/criteria.md",
        "evaluation/current_flash_v5/frozen-inputs.json",
        "evaluation/current_flash_v5/LIVE-INVENTORY.json",
        "evaluation/current_flash_v5/cases.json",
        "evaluation/current_flash_v5/inputs.py", "evaluation/current_flash_v5/journal.py",
        "evaluation/current_contract_compare_v3/cases.json",
        "evaluation/current_contract_compare_v2/actual-inputs.json",
        "evaluation/v2_fixture_loader.py",
        "backend/app/__init__.py", "backend/app/provider.py", "backend/app/engine.py",
        "backend/app/brief_citations.py", "backend/app/v2_database.py",
        "backend/app/main.py", "backend/app/seed_data.py", "backend/app/config.py",
        "backend/app/database.py", "backend/app/stage13.py", "backend/app/memory_contract.py",
        "backend/app/text_content.py", "backend/app/long_term_workflow.py", "backend/app/project_export.py",
        "backend/tests/test_v6_continuity_contract.py",
    )
    upstream = [ROOT / name for name in names]
    upstream += sorted((ROOT / "evaluation/current_contract_compare_v2/corpora").glob("*.json"))
    upstream += sorted(path for path in (ROOT / "evaluation/current_flash_v5/runs/flash-v5-20260927-01").rglob("*.json") if path.is_file())
    return local + upstream


def validate_assets() -> dict:
    cases = json.loads((HERE / "cases-v2.json").read_text(encoding="utf-8"))
    if cases != build_cases.build() or len(cases["cases"]) != 34 or len({item["case_id"] for item in cases["cases"]}) != 34:
        raise RuntimeError("v6_case_matrix_drift")
    summary = json.loads((PREP / "summary.json").read_text(encoding="utf-8"))
    if (summary["logical_cases_finished"] != 34 or summary["post_attempt_start_records"] != 0 or
        summary["models_get_start_records"] != 0 or summary["service_stop"]):
        raise RuntimeError("v6_preparation_incomplete")
    audits = sorted(PREP.glob("cases/[0-9][0-9]/input-audit/01.json"))
    requests = sorted(PREP.glob("cases/[0-9][0-9]/requests/01.json"))
    bindings = sorted(PREP.glob("cases/[0-9][0-9]/runtime-binding.json"))
    if tuple(map(len, (audits, requests, bindings))) != (34, 34, 34):
        raise RuntimeError("v6_capture_count_invalid")
    for case, audit_path, request_path in zip(cases["cases"], audits, requests):
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if (audit["case_id"] != case["case_id"] or request["case_id"] != case["case_id"] or
            audit["same_run_request_sha256"] != request["business_request_sha256"] or
            audit["database_binding"] != "matched_persisted_isolated_database"):
            raise RuntimeError("v6_same_run_capture_binding_invalid:" + case["case_id"])
    lens = json.loads((PREP / "cases/25/input-audit/01.json").read_text(encoding="utf-8"))
    if lens["selected_source_labels"] != ["L1", "L2", "L4"] or lens["selected_memory_count"] != 4:
        raise RuntimeError("v6_lens_input_adaptation_drift")
    inventory = json.loads((PREP / "workspace-manifest.json").read_text(encoding="utf-8"))
    if inventory != run.workspace_inventory(run.WORKSPACES / "prep-v6-02") or inventory["database_count"] != 34:
        raise RuntimeError("v6_isolated_workspace_drift")
    return {"logical_cases": 34, "preserved_comparison_inputs": 24, "deduplicated_new_control_inputs": 10,
            "independent_semantic_control_candidates": 12, "same_run_request_captures": 34,
            "isolated_databases": 34, "preparation_post_attempts": 0, "preparation_models_get": 0,
            "lens_selected": ["L1", "L2", "L4"], "lens_l3_unselected_memory_known": True}


def freeze() -> None:
    if MANIFEST.exists():
        raise RuntimeError("v6_already_frozen")
    details = validate_assets()
    head = subprocess.check_output(["git", "-c", "core.longpaths=true", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != BASE_HEAD:
        raise RuntimeError("git_base_changed")
    payload = {"version": "current-flash-v6", "status": "prepared_for_controller_technical_review",
               "frozen_at": datetime.now(timezone.utc).isoformat(), "git_base": BASE_HEAD,
               "modified_product_source_is_identified_by_hash": True,
               "model": "deepseek-flash", "base_url": "https://api.deepseek.com", "provider": "deepseek",
               "response_format": "json_object", "thinking": "disabled", "temperature": 0,
               "max_tokens": DeepSeekProvider.max_output_tokens,
               "timeout_seconds": DeepSeekProvider.timeout_seconds,
               "transport_retries": DeepSeekProvider.max_retries,
               "contract_evaluations_cap_per_case": 2,
               "maximum_generation_post_attempts": run.MAX_POST, "maximum_models_get_attempts": 1,
               "service_stop": "HTTP400/401/403/404 immediately; two consecutive logical cases with any transport/service error",
               "continuity_prompt_version": CONTINUITY_PROMPT_VERSION,
               "fixture_settings": "Stage13Settings.for_test; isolated evaluation DB and no SMTP",
               "quality_scored": False, "real_provider_calls_this_phase": 0,
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
            raise RuntimeError("v6_frozen_hash_mismatch:" + relative)
    if (frozen["maximum_generation_post_attempts"] != run.MAX_POST or
        frozen["max_tokens"] != DeepSeekProvider.max_output_tokens or
        frozen["timeout_seconds"] != DeepSeekProvider.timeout_seconds or
        frozen["transport_retries"] != DeepSeekProvider.max_retries or
        frozen["continuity_prompt_version"] != CONTINUITY_PROMPT_VERSION):
        raise RuntimeError("v6_provider_parameter_drift")
    return frozen


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    (freeze if args.command == "freeze" else verify)()
    print(json.dumps({"command": args.command, "ok": True}, ensure_ascii=False))
