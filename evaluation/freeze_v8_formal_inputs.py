"""One-time V8 formal-input freeze. This module never freezes on import."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V8_CORPUS_PATHS, corpus_manifest_payload
from evaluation.validate_eval_set_v8_candidate import validate_all as validate_candidate

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_CASE = ROOT / "evaluation/case_sets/eval-set-v8-candidate.json"
FORMAL_CASE = ROOT / "evaluation/case_sets/eval-set-v8.json"
CANDIDATE_MANIFEST = ROOT / "evaluation/manifests/eval-set-v8-candidate-manifest.json"
FORMAL_MANIFEST = ROOT / "evaluation/manifests/eval-set-v8-manifest.json"
CANDIDATE_REVIEW = ROOT / "evaluation/v8-candidate-semantic-review.json"
FORMAL_REVIEW = ROOT / "evaluation/v8-semantic-review.json"
CORPUS_MANIFEST = ROOT / "evaluation/fixtures/eval-v8-corpus-manifest.json"
PLAN = ROOT / "evaluation/manifests/eval-v8-first-formal-plan.json"
INTEGRITY = ROOT / "evaluation/manifests/eval-set-v8-freeze-integrity.json"
WORKSPACE = ROOT / "evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal"
EXPECTED_CASE_HASH = "6f85776fbab6bc7caa099e6132d2d8f9c65730bfc176f40033ca036b2f9e0c33"
EXPECTED_CORPUS_HASH = "878a21487bc9cde3e06982eac73e152fdc94851b8c6b2c5513ef39d1c31f476b"


def _read(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_paths() -> dict[str, pathlib.Path]:
    return {
        "evaluation/case_sets/eval-set-v8.json": FORMAL_CASE,
        "evaluation/manifests/eval-set-v8-manifest.json": FORMAL_MANIFEST,
        "evaluation/v8-semantic-review.json": FORMAL_REVIEW,
        "evaluation/fixtures/eval-v8-corpus-manifest.json": CORPUS_MANIFEST,
        **{f"evaluation/fixtures/{path.name}": path for path in V8_CORPUS_PATHS.values()},
    }


def formal_manifest(candidate: dict[str, Any]) -> dict[str, Any]:
    manifest = copy.deepcopy(candidate)
    manifest.update({
        "manifest_version": "scc-eval-manifest-v8", "status": "approved_for_formal_run", "runtime_mode": "evaluation_fixture",
        "case_set": {**candidate["case_set"], "path": "evaluation/case_sets/eval-set-v8.json"},
        "formal_run_plan": {"path": "evaluation/manifests/eval-v8-first-formal-plan.json", "status": "awaiting_real_provider_authorization"},
        "approval": {"controller_candidate_gate_passed": True, "formal_inputs_frozen": True, "real_provider_authorization_received": False, "approval_scope": "evaluation_input_freeze_only", "accepted_case_canonical_sha256": EXPECTED_CASE_HASH, "accepted_corpus_canonical_sha256": EXPECTED_CORPUS_HASH},
        "boundaries": {**candidate["boundaries"], "controller_candidate_gate_passed": True, "formal_inputs_frozen": True},
        "formal_run_executed": False, "provider_calls": 0,
    })
    return manifest


def freeze() -> dict[str, Any]:
    """Create the eight immutable V8 formal inputs exactly once after controller approval."""
    targets = (FORMAL_CASE, FORMAL_MANIFEST, FORMAL_REVIEW, INTEGRITY)
    if any(path.exists() for path in targets): raise RuntimeError("v8_formal_freeze_target_exists")
    candidate_result = validate_candidate()
    if candidate_result["status"] != "candidate_for_controller_review": raise RuntimeError("v8_formal_freeze_candidate_state_invalid")
    if (candidate_result["case_set"]["canonical_sha256"] != EXPECTED_CASE_HASH or candidate_result["manifest"]["corpus_canonical_sha256"] != EXPECTED_CORPUS_HASH): raise RuntimeError("v8_formal_freeze_controller_accepted_hash_mismatch")
    if WORKSPACE.exists() or any((ROOT / value).exists() for value in _read(PLAN)["planned_output_paths"].values()): raise RuntimeError("v8_formal_freeze_output_or_workspace_exists")
    candidate = _read(CANDIDATE_CASE)
    if canonical_sha256(candidate) != EXPECTED_CASE_HASH: raise RuntimeError("v8_formal_freeze_candidate_canonical_hash_mismatch")
    corpus = corpus_manifest_payload(V8_CORPUS_PATHS)
    if corpus["canonical_sha256"] != EXPECTED_CORPUS_HASH or _read(CORPUS_MANIFEST) != corpus: raise RuntimeError("v8_formal_freeze_corpus_hash_mismatch")
    plan = _read(PLAN)
    if {key: plan.get(key) for key in ("status", "controller_candidate_gate_passed", "formal_inputs_frozen", "real_provider_authorization_received", "formal_run_executed", "provider_calls")} != {"status": "not_run", "controller_candidate_gate_passed": False, "formal_inputs_frozen": False, "real_provider_authorization_received": False, "formal_run_executed": False, "provider_calls": 0}: raise RuntimeError("v8_formal_freeze_plan_execution_boundary_invalid")
    # Byte snapshots are intentionally copied, never regenerated.
    FORMAL_CASE.write_bytes(CANDIDATE_CASE.read_bytes()); FORMAL_REVIEW.write_bytes(CANDIDATE_REVIEW.read_bytes())
    FORMAL_MANIFEST.write_text(json.dumps(formal_manifest(_read(CANDIDATE_MANIFEST)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan.update({"status": "awaiting_real_provider_authorization", "controller_candidate_gate_passed": True, "formal_inputs_frozen": True})
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    integrity = {"schema_version": "scc-eval-v8-freeze-integrity-v1", "status": "frozen_formal_inputs", "controller_candidate_gate_passed": True, "formal_inputs_frozen": True, "real_provider_authorization_received": False, "formal_run_executed": False, "provider_calls": 0, "case_canonical_sha256": EXPECTED_CASE_HASH, "corpus_canonical_sha256": EXPECTED_CORPUS_HASH, "frozen_files": {relative: _sha(path) for relative, path in _frozen_paths().items()}}
    INTEGRITY.write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"case_canonical_sha256": EXPECTED_CASE_HASH, "corpus_canonical_sha256": EXPECTED_CORPUS_HASH, "frozen_file_count": len(integrity["frozen_files"]), "provider_calls": 0}


if __name__ == "__main__": print(json.dumps(freeze(), ensure_ascii=False, indent=2))
