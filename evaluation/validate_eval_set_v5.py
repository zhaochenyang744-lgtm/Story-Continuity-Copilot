"""Fail-closed integrity validation for the controller-approved V5 evaluation inputs."""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V5_CORPUS_PATHS, corpus_manifest_payload
from evaluation.validate_eval_set_v5_candidate import validate_all as validate_candidate


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v5-candidate.json"
CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v5.json"
CANDIDATE_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v5-candidate-manifest.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v5-manifest.json"
CANDIDATE_SEMANTIC_REVIEW_PATH = ROOT / "evaluation" / "v5-candidate-semantic-review.json"
SEMANTIC_REVIEW_PATH = ROOT / "evaluation" / "v5-semantic-review.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v5-corpus-manifest.json"
FORMAL_PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v5-first-formal-plan.json"
FREEZE_INTEGRITY_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v5-freeze-integrity.json"

EXPECTED_CASE_CANONICAL_HASH = "6eae96104b3aea7040eca1c2d927c4d7cc3ce9315a51c45045bfc10711ceb519"
EXPECTED_CORPUS_CANONICAL_HASH = "48124a6eab2b65a4ab2339bf5f645d732fcbec5dbf36a3c5d25fdfc79d74795a"
EXPECTED_FROZEN_FILE_HASHES = {
    "evaluation/case_sets/eval-set-v5.json": "c79b61842f2fe1d2ff37a25cd40ce24310bf7270ec9528ab29b3e91d4fb76b30",
    "evaluation/manifests/eval-set-v5-manifest.json": "914eb8697a7df668934cf0d9da69279523b1c3446ea96a5251ddb3bc062d6bd0",
    "evaluation/v5-semantic-review.json": "cd5f0518016cff39980ef6c275f62ce9e29568db875335d1b6701ea7eeb1771f",
    "evaluation/fixtures/eval-v5-corpus-manifest.json": "6c4f45022834f78b634ded5fc554d7437f7f1e14078b6b46abc8cb81dd3dd07b",
    "evaluation/fixtures/eval-v5-ember-observatory.json": "beb4b30ae4613c06f5c95ac82a06ef14a6c546faf32efab4fe15aaec8cfb61c8",
    "evaluation/fixtures/eval-v5-reed-foundry.json": "12cfac0f67fee346483f6e878064ca6a6e9869653fbe6e66fc2adfa737700c3b",
    "evaluation/fixtures/eval-v5-glass-marsh.json": "c8a913c2573f03dddb65dd74402f1f37e01d7db243aa85afc973604ec098063a",
    "evaluation/fixtures/eval-v5-copper-orchard.json": "79cecdcb51016812ba9d02d2fb67e60d10ae9da77d5d05b5078fddf52d667473",
}


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _frozen_paths() -> dict[str, pathlib.Path]:
    return {
        "evaluation/case_sets/eval-set-v5.json": CASE_SET_PATH,
        "evaluation/manifests/eval-set-v5-manifest.json": MANIFEST_PATH,
        "evaluation/v5-semantic-review.json": SEMANTIC_REVIEW_PATH,
        "evaluation/fixtures/eval-v5-corpus-manifest.json": CORPUS_MANIFEST_PATH,
        "evaluation/fixtures/eval-v5-ember-observatory.json": ROOT / "evaluation" / "fixtures" / "eval-v5-ember-observatory.json",
        "evaluation/fixtures/eval-v5-reed-foundry.json": ROOT / "evaluation" / "fixtures" / "eval-v5-reed-foundry.json",
        "evaluation/fixtures/eval-v5-glass-marsh.json": ROOT / "evaluation" / "fixtures" / "eval-v5-glass-marsh.json",
        "evaluation/fixtures/eval-v5-copper-orchard.json": ROOT / "evaluation" / "fixtures" / "eval-v5-copper-orchard.json",
    }


def validate_formal_freeze(
    case_set_path: pathlib.Path = CASE_SET_PATH,
    manifest_path: pathlib.Path = MANIFEST_PATH,
    semantic_review_path: pathlib.Path = SEMANTIC_REVIEW_PATH,
    integrity_path: pathlib.Path = FREEZE_INTEGRITY_PATH,
) -> dict[str, Any]:
    """Reject anything except the controller-approved, fixed-path V5 input bundle."""
    if (
        case_set_path.resolve() != CASE_SET_PATH.resolve()
        or manifest_path.resolve() != MANIFEST_PATH.resolve()
        or semantic_review_path.resolve() != SEMANTIC_REVIEW_PATH.resolve()
        or integrity_path.resolve() != FREEZE_INTEGRITY_PATH.resolve()
    ):
        raise ValueError("formal_v5_assets_must_use_frozen_paths")

    candidate_result = validate_candidate()
    if candidate_result.get("status") != "candidate_for_controller_review" or candidate_result.get("formal_run_executed") is not False or candidate_result.get("provider_calls") != 0:
        raise ValueError("formal_v5_accepted_candidate_no_longer_valid")

    candidate_bytes = CANDIDATE_CASE_SET_PATH.read_bytes()
    case_bytes = CASE_SET_PATH.read_bytes()
    candidate = _load(CANDIDATE_CASE_SET_PATH)
    case_set = _load(CASE_SET_PATH)
    if candidate_bytes != case_bytes or candidate != case_set or canonical_sha256(case_set) != EXPECTED_CASE_CANONICAL_HASH:
        raise ValueError("formal_v5_case_set_differs_from_accepted_candidate")

    candidate_manifest = _load(CANDIDATE_MANIFEST_PATH)
    manifest = _load(MANIFEST_PATH)
    expected_case_set = {
        "path": "evaluation/case_sets/eval-set-v5.json",
        "canonical_sha256": EXPECTED_CASE_CANONICAL_HASH,
        "case_count": 24,
        "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8},
        "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2},
    }
    expected_fixture = {
        "path": "evaluation/fixtures/eval-v5-corpus-manifest.json",
        "canonical_sha256": EXPECTED_CORPUS_CANONICAL_HASH,
        "evaluation_only": True,
        "production_seed": False,
        "protected_asset_source": False,
    }
    if manifest.get("manifest_version") != "scc-eval-manifest-v5" or manifest.get("status") != "approved_for_formal_run":
        raise ValueError("formal_v5_manifest_not_approved")
    if manifest.get("case_set") != expected_case_set or manifest.get("runtime_mode") != "evaluation_fixture":
        raise ValueError("formal_v5_manifest_runtime_or_case_set_invalid")
    for field in ("required_thresholds", "scoring", "stability_protocol", "fixture_corpus", "formal_run_plan"):
        if manifest.get(field) != candidate_manifest.get(field):
            raise ValueError("formal_v5_manifest_rules_differ_from_accepted_candidate")
    if manifest.get("fixture_corpus") != expected_fixture or manifest.get("formal_run_executed") is not False or manifest.get("provider_calls") != 0:
        raise ValueError("formal_v5_manifest_execution_boundary_invalid")
    expected_approval = {
        "controller_candidate_gate_passed": True,
        "real_provider_authorization_received": False,
        "approval_scope": "evaluation_input_freeze_only",
    }
    expected_boundaries = {
        "evaluation_only": True,
        "production_seed": False,
        "protected_asset_source": False,
        "formal_run_executed": False,
        "provider_calls": 0,
        "real_provider_authorization": False,
        "controller_candidate_gate_passed": True,
        "deployment": False,
        "ui_change": False,
    }
    if manifest.get("approval") != expected_approval or manifest.get("boundaries") != expected_boundaries:
        raise ValueError("formal_v5_manifest_approval_or_boundary_invalid")

    plan = _load(FORMAL_PLAN_PATH)
    if plan.get("status") != "not_run" or plan.get("formal_run_executed") is not False or plan.get("provider_calls") != 0 or plan.get("real_provider_authorization_received") is not False:
        raise ValueError("formal_v5_run_plan_must_remain_not_run")

    corpus_manifest = _load(CORPUS_MANIFEST_PATH)
    if corpus_manifest != corpus_manifest_payload(V5_CORPUS_PATHS) or corpus_manifest.get("canonical_sha256") != EXPECTED_CORPUS_CANONICAL_HASH:
        raise ValueError("formal_v5_corpus_manifest_invalid")

    candidate_review = _load(CANDIDATE_SEMANTIC_REVIEW_PATH)
    semantic_review = _load(SEMANTIC_REVIEW_PATH)
    entries = semantic_review.get("entries")
    case_by_id = {case["case_id"]: case for case in case_set["cases"]}
    candidate_review_by_id = {entry["case_id"]: entry for entry in candidate_review["entries"]}
    if (
        semantic_review.get("schema_version") != "scc-eval-v5-semantic-review-v1"
        or semantic_review.get("review_scope") != "controller_accepted_for_freeze"
        or semantic_review.get("status") != "approved_for_formal_run"
        or semantic_review.get("formal_run_executed") is not False
        or semantic_review.get("provider_calls") != 0
        or not isinstance(semantic_review.get("structural_validation_note"), str)
        or not isinstance(entries, list)
    ):
        raise ValueError("formal_v5_semantic_review_schema_invalid")
    if len(entries) != 24 or {entry.get("case_id") for entry in entries} != set(case_by_id):
        raise ValueError("formal_v5_semantic_review_coverage_invalid")
    for entry in entries:
        case = case_by_id[entry["case_id"]]
        candidate_entry = candidate_review_by_id.get(entry["case_id"], {})
        if (
            entry.get("corpus_key") != case["corpus_key"]
            or entry.get("core_fact_key") != case["core_fact_key"]
            or entry.get("decision_point") != candidate_entry.get("decision_point")
            or entry.get("prior_archetype_reference") != candidate_entry.get("prior_archetype_reference")
            or entry.get("why_independent") != candidate_entry.get("why_independent")
            or entry.get("same_decision_point") is not False
            or entry.get("review_status") != "controller_accepted_for_freeze"
        ):
            raise ValueError("formal_v5_semantic_review_acceptance_invalid")

    integrity = _load(FREEZE_INTEGRITY_PATH)
    frozen_paths = _frozen_paths()
    if (
        integrity.get("schema_version") != "scc-eval-v5-freeze-integrity-v1"
        or integrity.get("status") != "frozen_data_assets"
        or integrity.get("formal_run_executed") is not False
        or integrity.get("provider_calls") != 0
        or integrity.get("case_canonical_sha256") != EXPECTED_CASE_CANONICAL_HASH
        or integrity.get("corpus_canonical_sha256") != EXPECTED_CORPUS_CANONICAL_HASH
    ):
        raise ValueError("formal_v5_freeze_integrity_schema_invalid")
    recorded = integrity.get("frozen_files")
    if not isinstance(recorded, dict) or recorded != EXPECTED_FROZEN_FILE_HASHES or set(recorded) != set(frozen_paths):
        raise ValueError("formal_v5_freeze_integrity_record_invalid")
    if any(recorded[relative] != sha256_file(path) for relative, path in frozen_paths.items()):
        raise ValueError("formal_v5_freeze_integrity_hash_mismatch")

    return {
        "valid": True,
        "case_canonical_sha256": EXPECTED_CASE_CANONICAL_HASH,
        "corpus_canonical_sha256": EXPECTED_CORPUS_CANONICAL_HASH,
        "semantic_review_entries": 24,
        "frozen_file_count": len(frozen_paths),
        "case_set_byte_identical_to_candidate": True,
        "controller_candidate_gate_passed": True,
        "real_provider_authorization_received": False,
        "formal_run_executed": False,
        "provider_calls": 0,
        "status": manifest["status"],
    }


if __name__ == "__main__":
    print(json.dumps(validate_formal_freeze(), ensure_ascii=False, indent=2))
