"""Fail-closed V8 formal-freeze validator for before and after input freezing."""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from evaluation.freeze_v8_formal_inputs import (
    CANDIDATE_CASE, CANDIDATE_MANIFEST, CANDIDATE_REVIEW, EXPECTED_CASE_HASH,
    EXPECTED_CORPUS_HASH, FORMAL_CASE, FORMAL_MANIFEST, FORMAL_REVIEW, INTEGRITY,
    PLAN, WORKSPACE, _frozen_paths, formal_manifest,
)
from evaluation.validate_eval_set import canonical_sha256
from evaluation.validate_eval_set_v8_candidate import (
    load_v8_candidate, validate_all as validate_candidate, validate_v8_candidate_case_set,
    validate_v8_corpora, validate_v8_manifest, validate_v8_semantic_review,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT_PATHS = tuple(ROOT / value for value in json.loads(PLAN.read_text(encoding="utf-8"))["planned_output_paths"].values())


def _read(path: pathlib.Path) -> dict[str, Any]: return json.loads(path.read_text(encoding="utf-8"))
def _sha(path: pathlib.Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_formal_freeze(*, plan_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate fixed V8 inputs only; never creates assets or touches a Provider."""
    formal_paths = (FORMAL_CASE, FORMAL_MANIFEST, FORMAL_REVIEW, INTEGRITY)
    present = [path.exists() for path in formal_paths]
    if not any(present):
        candidate = validate_candidate()
        return {"valid": True, "lifecycle": "before_freeze", "status": "awaiting_controller_candidate_gate", "candidate_status": candidate["status"], "formal_input_count": 0, "formal_result_count": 0, "formal_workspace_count": 0, "provider_calls": 0}
    if not all(present): raise ValueError("v8_formal_freeze_partial_asset_set")
    # Candidate semantic, lineage, and novelty checks remain live after its
    # formal copy is created. The plan is deliberately mutable run state.
    candidate = load_v8_candidate(); case_result = validate_v8_candidate_case_set(candidate)
    validate_v8_corpora(); validate_v8_manifest(case_result); validate_v8_semantic_review(candidate)
    plan = plan_payload or _read(PLAN)
    post_run = plan.get("formal_run_executed") is True
    if post_run:
        if (plan.get("status"), plan.get("controller_candidate_gate_passed"), plan.get("formal_inputs_frozen"), plan.get("real_provider_authorization_received"), plan.get("provider_calls")) != ("gate_failed", True, True, True, 30):
            raise ValueError("v8_formal_plan_post_run_state_invalid")
    else:
        expected_plan = {"controller_candidate_gate_passed": True, "formal_inputs_frozen": True, "formal_run_executed": False, "provider_calls": 0}
        if (any(plan.get(key) != value for key, value in expected_plan.items()) or plan.get("status") not in {"awaiting_real_provider_authorization", "approved_for_formal_run"} or not isinstance(plan.get("real_provider_authorization_received"), bool)):
            raise ValueError("v8_formal_plan_pre_run_state_invalid")
        if any(path.exists() for path in OUTPUT_PATHS) or WORKSPACE.exists(): raise ValueError("v8_formal_pre_run_outputs_or_workspace_present")
    if CANDIDATE_CASE.read_bytes() != FORMAL_CASE.read_bytes() or canonical_sha256(_read(FORMAL_CASE)) != EXPECTED_CASE_HASH: raise ValueError("v8_formal_case_set_not_byte_identical_or_hash_invalid")
    if CANDIDATE_REVIEW.read_bytes() != FORMAL_REVIEW.read_bytes(): raise ValueError("v8_formal_semantic_review_not_byte_identical_to_candidate")
    if _read(FORMAL_MANIFEST) != formal_manifest(_read(CANDIDATE_MANIFEST)): raise ValueError("v8_formal_manifest_not_accepted_candidate_snapshot")
    integrity = _read(INTEGRITY); frozen = _frozen_paths()
    expected_integrity = {"schema_version": "scc-eval-v8-freeze-integrity-v1", "status": "frozen_formal_inputs", "controller_candidate_gate_passed": True, "formal_inputs_frozen": True, "real_provider_authorization_received": False, "formal_run_executed": False, "provider_calls": 0, "case_canonical_sha256": EXPECTED_CASE_HASH, "corpus_canonical_sha256": EXPECTED_CORPUS_HASH}
    if (any(integrity.get(key) != value for key, value in expected_integrity.items()) or set(integrity.get("frozen_files", {})) != set(frozen) or any(integrity["frozen_files"].get(key) != _sha(path) for key, path in frozen.items())): raise ValueError("v8_formal_freeze_integrity_hash_invalid")
    if sorted(path.name for path in FORMAL_CASE.parent.glob("eval-set-v8*.json")) != ["eval-set-v8-candidate.json", "eval-set-v8.json"]: raise ValueError("v8_formal_case_path_not_unique")
    if post_run:
        from evaluation.validate_v8_first_formal_results import validate as validate_post_run
        post = validate_post_run()
        actual = {path.resolve() for path in (ROOT / "evaluation/results").glob("eval-v8-first-formal-*")}
        actual.add((ROOT / "evaluation/results/v8-first-formal-post-run-integrity.json").resolve())
        if actual != {path.resolve() for path in OUTPUT_PATHS}: raise ValueError("v8_formal_post_run_result_paths_not_unique")
        return {"valid": True, "lifecycle": "post_run", "status": "formal_run_completed", "formal_result_status": post["status"], "case_canonical_sha256": EXPECTED_CASE_HASH, "corpus_canonical_sha256": EXPECTED_CORPUS_HASH, "frozen_file_count": len(frozen), "formal_input_count": len(frozen), "formal_result_count": len(OUTPUT_PATHS), "formal_workspace_count": 24, "provider_calls": 30, "real_provider_authorization_received": True}
    return {"valid": True, "lifecycle": "after_freeze", "status": plan["status"], "case_canonical_sha256": EXPECTED_CASE_HASH, "corpus_canonical_sha256": EXPECTED_CORPUS_HASH, "frozen_file_count": len(frozen), "formal_input_count": len(frozen), "formal_result_count": 0, "formal_workspace_count": 0, "provider_calls": 0, "real_provider_authorization_received": plan["real_provider_authorization_received"]}


def validate_formal_readiness() -> dict[str, Any]: return validate_formal_freeze()


if __name__ == "__main__": print(json.dumps(validate_formal_freeze(), ensure_ascii=False, indent=2))
