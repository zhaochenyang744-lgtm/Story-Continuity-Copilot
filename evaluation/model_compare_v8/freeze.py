"""V8 dependency closure. Never invoke a historical product freeze or open a DB."""
from __future__ import annotations

import argparse
import importlib.metadata
import pathlib
import sys

from app.provider import CONTINUITY_PROMPT_VERSION, request_prompt_and_budget
from evaluation.model_compare_v8 import harness
from evaluation.model_compare_v8.config import *
from evaluation.model_compare_v8.provider import body_for

MANIFEST = HERE / "frozen-inputs.json"
PREP = HERE / "runs/prep-v8-01"
V7_LIVE = ROOT / "evaluation/current_flash_v7/runs/flash-v7-20260927-01"


def paths():
    found = set(HERE.glob("*.py")) | set(HERE.glob("*.md"))
    found |= set(HERE.glob("offline-*.json"))
    found |= set((ROOT / "backend/app").rglob("*.py"))
    found |= set(PREP.rglob("*.json"))
    found |= {V7_CASES, ROOT / "evaluation/__init__.py", ROOT / "backend/requirements.txt"}
    found |= {PREPARED / "cases" / f"{n:02d}" / "requests/01.json" for n in range(1, 35)}
    # Replay reads original business requests, visible response chains and archived scores.
    for n in range(1, 35):
        folder = V7_LIVE / "cases" / f"{n:02d}"
        found |= set((folder / "requests").glob("*.json"))
        found |= set((folder / "evaluations").glob("*.json"))
        found |= set((folder / "attempts").glob("*-finish.json"))
        found.add(folder / "scores.json")
    names = (
        "evaluation/current_flash_v7/score.py", "evaluation/current_flash_v7/build_cases.py",
        "evaluation/current_contract_compare_v3/cases.json",
        "evaluation/current_flash_v5/cases.json", "evaluation/current_flash_v6/INPUT-ADAPTATION.md",
        "evaluation/current_flash_v6/SCORING-POLICY.md", "evaluation/current_flash_v6/SCORING-ADDENDUM.md",
        "evaluation/current_flash_v6/SCORING-ADDENDUM-02.md", "evaluation/current_flash_v6/SCORING-ADDENDUM-03.md",
        "docs/flash-v6-independent-acceptance-evidence/semantics/criteria.md",
        "docs/flash-v6-independent-acceptance-evidence/semantics/control-matrix.json",
        "docs/flash-v6-independent-acceptance-evidence/semantics/scoring-role-review.json",
        "docs/flash-v7-independent-acceptance-evidence/input-review-01.json",
        "docs/model-compare-v8-independent-acceptance/PLAN.md",
        "docs/model-compare-v8-independent-acceptance/SEMANTIC-CRITERIA.md",
        "docs/model-compare-v8-independent-acceptance/SEMANTIC-CRITERIA.json",
        "docs/model-compare-v8-independent-acceptance/engineering-design-review-01.md",
        "docs/model-compare-v8-independent-acceptance/build_blind_packets.py",
    )
    found |= {ROOT / name for name in names}
    for path in tuple(found):
        for parent in path.parents:
            if parent == ROOT:
                break
            initializer = parent / "__init__.py"
            if initializer.is_file():
                found.add(initializer)
    return sorted(found)


def runtime_pins():
    # Pin installed HTTP/validation dependencies, including package initializers
    # and conditional import modules; pin the interpreter too. No credentials.
    distributions = ("httpx", "httpcore", "anyio", "certifi", "idna", "h11", "sniffio",
                     "pydantic", "pydantic_core", "typing_extensions", "typing_inspection", "annotated_types")
    files = {pathlib.Path(sys.executable).resolve()}
    versions = {}
    for name in distributions:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        versions[name] = distribution.version
        for file in distribution.files or ():
            path = pathlib.Path(distribution.locate_file(file)).resolve()
            if path.is_file() and (path.suffix in {".py", ".pyd", ".dll", ".pem"} or path.name == "METADATA"):
                files.add(path)
    return {"python_version": sys.version, "distributions": versions,
            "files": {str(path): sha(path) for path in sorted(files)}}


def validate_assets():
    if CONTINUITY_PROMPT_VERSION != PROMPT_VERSION or harness.engine_module.MAX_RUN_TOKENS != 8000:
        raise RuntimeError("product_prompt_or_original_budget_drift")
    if read(PREP / "plan.json") != plan():
        raise RuntimeError("prepared_plan_drift")
    if read(PREP / "summary.json") != {"mode": "prepare", "version": VERSION, "cases": 34,
            "condition_cases": 102, "provider_calls": 0, "database_connections": 0, "quality_scored": False}:
        raise RuntimeError("preparation_incomplete")
    conditions = {c["id"]: c for c in CONDITIONS}
    by_case = {c["ordinal"]: c for c in cases()}
    for item in schedule():
        request = request_for(by_case[item["case_ordinal"]])
        folder = PREP / "cases" / f"{item['case_ordinal']:02d}" / item["condition_id"]
        if read(folder / "input.json") != {"business_request": request, "business_request_sha256": digest(request)}:
            raise RuntimeError("prepared_business_request_drift")
        body = body_for(request, conditions[item["condition_id"]])
        if read(folder / "wire.json") != {"http_json_body": body, "body_sha256": digest(body)}:
            raise RuntimeError("prepared_serialized_prompt_drift")
        if request_prompt_and_budget(request)[1] > 6000:
            raise RuntimeError("original_input_budget_exceeded")
    return {"logical_cases": 34, "condition_cases": 102, "exact_v7_requests": 34,
            "gold_policy": "unchanged_v7", "database_connections": 0, "provider_calls": 0}


def freeze():
    if MANIFEST.exists():
        raise FileExistsError("v8_already_frozen")
    details = validate_assets()
    write_x(MANIFEST, {"version": VERSION, "created_at": stamp(), "quality_scored": False,
        "limits": limits(), "conditions": list(CONDITIONS), "details": details,
        "source_hashes": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths()},
        "runtime": runtime_pins()})


def verify():
    frozen = read(MANIFEST)
    if frozen.get("version") != VERSION or frozen.get("limits") != limits() or frozen.get("conditions") != list(CONDITIONS):
        raise RuntimeError("v8_configuration_drift")
    expected = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths()}
    if frozen.get("source_hashes") != expected:
        raise RuntimeError("v8_dependency_closure_or_hash_drift")
    if frozen.get("runtime") != runtime_pins():
        raise RuntimeError("v8_installed_runtime_drift")
    validate_assets()
    return frozen


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    (freeze if args.command == "freeze" else verify)()
    print(args.command + ":ok")
