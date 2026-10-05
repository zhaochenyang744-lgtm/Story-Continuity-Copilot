"""Create and verify a V7-only freeze; never invoke an older product freeze."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

from evaluation.current_flash_v7 import build_cases, run
from evaluation.current_flash_v7.build_cases import write_x
from app.provider import CONTINUITY_PROMPT_VERSION, DeepSeekProvider

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "frozen-inputs.json"
PREP = HERE / "runs/prep-v7-01"
BASE_HEAD = "7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2"
EXPECTED_PROMPT = "continuity-review-v17-repair-diagnostics"
EXPECTED_SCHEMA = "continuity-issue-v7-repair-diagnostics"
REFERENCE_PREP = ROOT / "evaluation/current_flash_v6/runs/prep-v6-02"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths() -> list[pathlib.Path]:
    # Include package initialization before importing evaluation.* at live launch.
    # All app modules are pinned, including transitive and conditional imports.
    found = set(HERE.glob("*.py")) | set(HERE.glob("*.md"))
    found |= {HERE / "cases.json", ROOT / "evaluation/__init__.py", ROOT / "backend/requirements.txt"}
    found |= set((HERE / "corpora").glob("*.json"))
    found |= set((ROOT / "backend/app").rglob("*.py"))
    found |= set(PREP.rglob("*.json"))
    names = (
        "evaluation/current_flash_v5/inputs.py", "evaluation/current_flash_v5/journal.py",
        "evaluation/current_flash_v5/cases.json", "evaluation/v2_fixture_loader.py",
        "evaluation/current_contract_compare_v3/cases.json",
        "evaluation/current_contract_compare_v2/actual-inputs.json",
        "evaluation/current_flash_v6/cases-v2.json", "evaluation/current_flash_v6/INPUT-ADAPTATION.md",
        "evaluation/current_flash_v6/SCORING-POLICY.md", "evaluation/current_flash_v6/SCORING-ADDENDUM.md",
        "evaluation/current_flash_v6/SCORING-ADDENDUM-02.md", "evaluation/current_flash_v6/SCORING-ADDENDUM-03.md",
        "evaluation/current_flash_v6/score.py",
        "docs/flash-v6-independent-acceptance-evidence/semantics/criteria.md",
        "docs/flash-v6-independent-acceptance-evidence/semantics/control-matrix.json",
        "docs/flash-v6-independent-acceptance-evidence/semantics/scoring-role-review.json",
        "backend/tests/test_v7_continuity_contract.py",
    )
    found |= {ROOT / name for name in names}
    found |= set((ROOT / "evaluation/current_contract_compare_v2/corpora").glob("*.json"))
    found |= set((ROOT / "evaluation/current_flash_v6/corpora-v2").glob("*.json"))
    # These read-only captures are used by input equivalence and offline tests.
    found |= set(REFERENCE_PREP.rglob("*.json"))
    for name in ("04/evaluations/01.json", "13/evaluations/01.json", "07/requests/01.json", "07/final-product.json"):
        found.add(ROOT / "evaluation/current_flash_v5/runs/flash-v5-20260927-01/cases" / name)
    for ordinal in ("03", "17", "22", "26"):
        for name in ("requests/01.json", "attempts/01-finish.json", "evaluations/01.json"):
            found.add(ROOT / "evaluation/current_flash_v6/runs/flash-v6-20260927-01/cases" / ordinal / name)
    # Include every existing initializer for every local dependency package.
    for path in tuple(found):
        for parent in path.parents:
            if parent == ROOT:
                break
            initializer = parent / "__init__.py"
            if initializer.is_file():
                found.add(initializer)
    return sorted(found)


def _business(request: dict) -> dict:
    result = json.loads(json.dumps(request))
    result.pop("output_schema", None)
    result.pop("contract_repair", None)
    for claim in result["claims"]:
        claim["id"] = "normalized-ephemeral-claim-id"
    return result


def validate_assets() -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    old = json.loads((ROOT / "evaluation/current_flash_v6/cases-v2.json").read_text(encoding="utf-8"))
    if cases != build_cases.build() or cases["cases"] != old["cases"] or len(cases["cases"]) != 34:
        raise RuntimeError("v7_case_matrix_drift")
    for path in sorted((HERE / "corpora").glob("*.json")):
        if path.read_bytes() != (ROOT / "evaluation/current_flash_v6/corpora-v2" / path.name).read_bytes():
            raise RuntimeError("v7_business_corpus_drift:" + path.name)
    summary = json.loads((PREP / "summary.json").read_text(encoding="utf-8"))
    if (summary["logical_cases_finished"] != 34 or summary["post_attempt_start_records"] != 0 or
            summary["models_get_start_records"] != 0 or summary["service_stop"]):
        raise RuntimeError("v7_preparation_incomplete")
    for case in cases["cases"]:
        folder = PREP / "cases" / f"{case['ordinal']:02d}"
        capture = json.loads((folder / "requests/01.json").read_text(encoding="utf-8"))
        audit = json.loads((folder / "input-audit/01.json").read_text(encoding="utf-8"))
        product = json.loads((folder / "final-product.json").read_text(encoding="utf-8"))
        reference = json.loads((REFERENCE_PREP / "cases" / folder.name / "requests/01.json").read_text(encoding="utf-8"))
        request = capture["business_request"]
        from evaluation.current_flash_v5.journal import digest
        if (capture["case_id"] != case["case_id"] or audit["case_id"] != case["case_id"] or
                capture["business_request_sha256"] != digest(request) or
                audit["same_run_request_sha256"] != digest(request) or
                audit["database_binding"] != "matched_persisted_isolated_database" or
                _business(request) != _business(reference["business_request"])):
            raise RuntimeError("v7_same_business_input_binding_invalid:" + case["case_id"])
        if (product.get("status") != "completed" or
                product.get("provenance", {}).get("prompt_version") != EXPECTED_PROMPT or
                product.get("provenance", {}).get("schema_version") != EXPECTED_SCHEMA):
            raise RuntimeError("v7_preparation_product_provenance_invalid:" + case["case_id"])
    inventory = json.loads((PREP / "workspace-manifest.json").read_text(encoding="utf-8"))
    if inventory != run.workspace_inventory(run.WORKSPACES / PREP.name) or inventory["database_count"] != 34:
        raise RuntimeError("v7_isolated_workspace_drift")
    return {"logical_cases": 34, "same_v6_business_inputs": 34, "preserved_comparison_inputs": 24,
            "deduplicated_seen_controls": 10, "same_run_request_captures": 34,
            "isolated_databases": 34, "preparation_post_attempts": 0, "preparation_models_get": 0,
            "scoring_policy": "unchanged_v6", "semantic_review_required": True}


def _head() -> str:
    return subprocess.check_output(["git", "-c", "core.longpaths=true", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _parameters() -> dict:
    return {"continuity_prompt_version": CONTINUITY_PROMPT_VERSION,
            "continuity_contract_marker": DeepSeekProvider.continuity_contract_version,
            "max_tokens": DeepSeekProvider.max_output_tokens, "timeout_seconds": DeepSeekProvider.timeout_seconds,
            "transport_retries": DeepSeekProvider.max_retries,
            "contract_evaluations_cap_per_case": 2, "maximum_generation_post_attempts": run.MAX_POST,
            "maximum_models_get_attempts": 1}


def freeze() -> None:
    if MANIFEST.exists():
        raise RuntimeError("v7_already_frozen")
    if _head() != BASE_HEAD:
        raise RuntimeError("git_base_changed")
    if (CONTINUITY_PROMPT_VERSION != EXPECTED_PROMPT or DeepSeekProvider.continuity_contract_version != "v6" or
            DeepSeekProvider.max_retries != 1 or run.MAX_POST != 136):
        raise RuntimeError("v7_provider_parameter_drift")
    details = validate_assets()
    source_hashes = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths()}
    write_x(MANIFEST, {"version": "current-flash-v7", "status": "prepared_for_controller_technical_review",
        "frozen_at": datetime.now(timezone.utc).isoformat(), "git_base": BASE_HEAD,
        "modified_product_source_is_identified_by_hash": True,
        "model": "deepseek-flash", "base_url": "https://api.deepseek.com", "provider": "deepseek",
        "response_format": "json_object", "thinking": "disabled", "temperature": 0,
        "schema_version": EXPECTED_SCHEMA, **_parameters(),
        "service_stop": "HTTP400/401/403/404 immediately; two consecutive logical cases with any transport/service error",
        "fixture_settings": "Stage13Settings.for_test; isolated evaluation DB and no SMTP",
        "quality_scored": False, "real_provider_calls_this_phase": 0,
        "details": details, "source_hashes": source_hashes})


def verify() -> dict:
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected_paths = {path.relative_to(ROOT).as_posix() for path in paths()}
    if frozen.get("version") != "current-flash-v7" or set(frozen.get("source_hashes", {})) != expected_paths:
        raise RuntimeError("v7_dependency_closure_drift")
    if _head() != BASE_HEAD:
        raise RuntimeError("git_base_changed")
    for relative, expected in frozen["source_hashes"].items():
        path = ROOT / relative
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError("v7_frozen_hash_mismatch:" + relative)
    if any(frozen.get(key) != value for key, value in _parameters().items()):
        raise RuntimeError("v7_provider_parameter_drift")
    validate_assets()
    return frozen


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    (freeze if args.command == "freeze" else verify)()
    print(json.dumps({"command": args.command, "ok": True}))
