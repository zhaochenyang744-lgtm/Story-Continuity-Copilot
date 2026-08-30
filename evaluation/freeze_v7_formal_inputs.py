"""One-time, fail-closed freeze of the controller-approved V7 candidate inputs."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V7_CORPUS_PATHS, corpus_manifest_payload
from evaluation.validate_eval_set_v7_candidate import validate_all as validate_candidate


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v7-candidate.json"
FORMAL_CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v7.json"
CANDIDATE_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-candidate-manifest.json"
FORMAL_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-manifest.json"
CANDIDATE_REVIEW_PATH = ROOT / "evaluation" / "v7-candidate-semantic-review.json"
FORMAL_REVIEW_PATH = ROOT / "evaluation" / "v7-semantic-review.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v7-corpus-manifest.json"
FORMAL_PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v7-first-formal-plan.json"
INTEGRITY_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-freeze-integrity.json"
FORMAL_WORKSPACE = ROOT / "evaluation" / "fixture-workspaces" / "scc-web-demo-eval-v7-first-formal"

EXPECTED_CASE_HASH = "e53eba34c29f889855c01f0c2657e4769d2f19e458cf5631a3f3d2ffcee0b3fd"
EXPECTED_CORPUS_HASH = "04a9e6e1b4c847c12433d42de640b8906252f3590cb5135f77d375fedda683c0"
OUTPUT_PATHS = {
    key: ROOT / value
    for key, value in ({
        "checkpoint": "evaluation/results/eval-v7-first-formal-checkpoint.json",
        "results": "evaluation/results/eval-v7-first-formal-results.json",
        "report": "evaluation/results/eval-v7-first-formal-report.md",
        "bad_cases": "evaluation/results/eval-v7-first-formal-bad-cases.json",
        "stability": "evaluation/results/eval-v7-first-formal-stability.json",
        "run_manifest": "evaluation/results/eval-v7-first-formal-run-manifest.json",
        "api_scan": "evaluation/results/eval-v7-first-formal-api-corpus-scan.json",
        "post_run_integrity": "evaluation/results/v7-first-formal-post-run-integrity.json",
    }).items()
}


def _read(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_once(path: pathlib.Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"v7_formal_freeze_target_exists:{path.name}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_paths() -> dict[str, pathlib.Path]:
    return {
        "evaluation/case_sets/eval-set-v7.json": FORMAL_CASE_PATH,
        "evaluation/manifests/eval-set-v7-manifest.json": FORMAL_MANIFEST_PATH,
        "evaluation/v7-semantic-review.json": FORMAL_REVIEW_PATH,
        "evaluation/fixtures/eval-v7-corpus-manifest.json": CORPUS_MANIFEST_PATH,
        **{f"evaluation/fixtures/{path.name}": path for path in V7_CORPUS_PATHS.values()},
    }


def freeze() -> dict[str, Any]:
    targets = (FORMAL_CASE_PATH, FORMAL_MANIFEST_PATH, FORMAL_REVIEW_PATH, INTEGRITY_PATH)
    if any(path.exists() for path in targets):
        raise RuntimeError("v7_formal_freeze_target_exists")
    candidate_result = validate_candidate()
    if candidate_result["status"] != "candidate_for_controller_review":
        raise RuntimeError("v7_formal_freeze_candidate_state_invalid")
    if (candidate_result["case_set"]["canonical_sha256"] != EXPECTED_CASE_HASH
            or candidate_result["manifest"]["corpus_canonical_sha256"] != EXPECTED_CORPUS_HASH):
        raise RuntimeError("v7_formal_freeze_controller_accepted_hash_mismatch")
    if FORMAL_WORKSPACE.exists() or any(path.exists() for path in OUTPUT_PATHS.values()):
        raise RuntimeError("v7_formal_freeze_output_or_workspace_exists")

    candidate_bytes = CANDIDATE_CASE_PATH.read_bytes()
    candidate = _read(CANDIDATE_CASE_PATH)
    if canonical_sha256(candidate) != EXPECTED_CASE_HASH:
        raise RuntimeError("v7_formal_freeze_candidate_canonical_hash_mismatch")
    corpus = corpus_manifest_payload(V7_CORPUS_PATHS)
    if corpus["canonical_sha256"] != EXPECTED_CORPUS_HASH or _read(CORPUS_MANIFEST_PATH) != corpus:
        raise RuntimeError("v7_formal_freeze_corpus_hash_mismatch")

    # The formal case and semantic review are immutable byte snapshots, not regenerated copies.
    FORMAL_CASE_PATH.write_bytes(candidate_bytes)
    FORMAL_REVIEW_PATH.write_bytes(CANDIDATE_REVIEW_PATH.read_bytes())

    candidate_manifest = _read(CANDIDATE_MANIFEST_PATH)
    manifest = copy.deepcopy(candidate_manifest)
    manifest.update({
        "manifest_version": "scc-eval-manifest-v7",
        "status": "approved_for_formal_run",
        "case_set": {**candidate_manifest["case_set"], "path": "evaluation/case_sets/eval-set-v7.json"},
        "formal_run_plan": {"path": "evaluation/manifests/eval-v7-first-formal-plan.json", "status": "awaiting_real_provider_authorization"},
        "approval": {
            "controller_candidate_gate_passed": True,
            "formal_inputs_frozen": True,
            "real_provider_authorization_received": False,
            "approval_scope": "evaluation_input_freeze_only",
            "accepted_case_canonical_sha256": EXPECTED_CASE_HASH,
            "accepted_corpus_canonical_sha256": EXPECTED_CORPUS_HASH,
        },
        "boundaries": {**candidate_manifest["boundaries"], "controller_candidate_gate_passed": True, "formal_inputs_frozen": True},
        "formal_run_executed": False,
        "provider_calls": 0,
    })
    _write_once(FORMAL_MANIFEST_PATH, manifest)

    plan = _read(FORMAL_PLAN_PATH)
    if (plan.get("status") != "not_run" or plan.get("controller_candidate_gate_passed") is not False
            or plan.get("formal_inputs_frozen") is not False or plan.get("real_provider_authorization_received") is not False
            or plan.get("formal_run_executed") is not False or plan.get("provider_calls") != 0):
        raise RuntimeError("v7_formal_freeze_plan_execution_boundary_invalid")
    plan.update({
        "status": "awaiting_real_provider_authorization",
        "controller_candidate_gate_passed": True,
        "formal_inputs_frozen": True,
        "execution_note": "Controller-approved V7 formal inputs are frozen. Real Provider authorization is absent; no result, checkpoint, report, Bad Case, stability, run manifest, API scan, workspace, or post-run integrity artifact exists.",
    })
    plan["stage_status"] = {"stage_10": "gate_failed_not_passed_v7_formal_awaiting_authorization", "stage_11": "not_started", "stage_12": "not_started"}
    FORMAL_PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    integrity = {
        "schema_version": "scc-eval-v7-freeze-integrity-v1",
        "status": "frozen_formal_inputs",
        "controller_candidate_gate_passed": True,
        "formal_inputs_frozen": True,
        "real_provider_authorization_received": False,
        "formal_run_executed": False,
        "provider_calls": 0,
        "case_canonical_sha256": EXPECTED_CASE_HASH,
        "corpus_canonical_sha256": EXPECTED_CORPUS_HASH,
        "frozen_files": {relative: _sha(path) for relative, path in _frozen_paths().items()},
    }
    _write_once(INTEGRITY_PATH, integrity)
    return {
        "case_canonical_sha256": EXPECTED_CASE_HASH,
        "corpus_canonical_sha256": EXPECTED_CORPUS_HASH,
        "frozen_file_hashes": integrity["frozen_files"],
        "formal_run_executed": False,
        "provider_calls": 0,
    }


if __name__ == "__main__":
    print(json.dumps(freeze(), ensure_ascii=False, indent=2))
