"""Fail-closed integrity validation for the approved V4 fixture evaluation."""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V4_CORPUS_PATHS, corpus_manifest_payload


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v4-candidate.json"
CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v4.json"
CANDIDATE_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v4-candidate-manifest.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v4-manifest.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v4-corpus-manifest.json"
SEMANTIC_REVIEW_PATH = ROOT / "evaluation" / "v4-semantic-review.json"
FREEZE_INTEGRITY_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v4-freeze-integrity.json"
EXPECTED_CASE_HASH = "2fd88830ad7ef61e089de7bd6d18ba930bdecf445c65c6ce835f20c7507768fc"
EXPECTED_CORPUS_HASH = "5bc19ed4c6e1fd231af4e2f798b174f58bd5fe55314552f907e3b8b82de7daf3"


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_formal_freeze(
    case_set_path: pathlib.Path = CASE_SET_PATH,
    manifest_path: pathlib.Path = MANIFEST_PATH,
    semantic_review_path: pathlib.Path = SEMANTIC_REVIEW_PATH,
    integrity_path: pathlib.Path = FREEZE_INTEGRITY_PATH,
) -> dict[str, Any]:
    """Reject anything except the controller-approved, immutable V4 assets."""
    if case_set_path.resolve() != CASE_SET_PATH.resolve() or manifest_path.resolve() != MANIFEST_PATH.resolve() or semantic_review_path.resolve() != SEMANTIC_REVIEW_PATH.resolve() or integrity_path.resolve() != FREEZE_INTEGRITY_PATH.resolve():
        raise ValueError("formal_v4_assets_must_use_frozen_paths")
    candidate = _load(CANDIDATE_CASE_SET_PATH)
    case_set = _load(CASE_SET_PATH)
    candidate_manifest = _load(CANDIDATE_MANIFEST_PATH)
    manifest = _load(MANIFEST_PATH)
    semantic_review = _load(SEMANTIC_REVIEW_PATH)
    integrity = _load(FREEZE_INTEGRITY_PATH)
    if case_set != candidate or canonical_sha256(case_set) != EXPECTED_CASE_HASH:
        raise ValueError("formal_v4_case_set_differs_from_accepted_candidate")
    expected_case_set = {"path": "evaluation/case_sets/eval-set-v4.json", "canonical_sha256": EXPECTED_CASE_HASH, "case_count": 15, "split": {"conflict": 5, "no_conflict": 5, "insufficient_evidence": 5}}
    expected_fixture = {"path": "evaluation/fixtures/eval-v4-corpus-manifest.json", "canonical_sha256": EXPECTED_CORPUS_HASH, "evaluation_only": True, "production_seed": False, "protected_asset_source": False}
    if manifest.get("manifest_version") != "scc-eval-manifest-v4" or manifest.get("status") != "approved_for_formal_run":
        raise ValueError("formal_v4_manifest_not_approved")
    if manifest.get("case_set") != expected_case_set or manifest.get("runtime_mode") != "evaluation_fixture":
        raise ValueError("formal_v4_manifest_runtime_or_case_set_invalid")
    if manifest.get("required_thresholds") != candidate_manifest.get("required_thresholds") or manifest.get("scoring") != candidate_manifest.get("scoring") or manifest.get("stability_protocol") != candidate_manifest.get("stability_protocol"):
        raise ValueError("formal_v4_manifest_rules_differ_from_accepted_candidate")
    if manifest.get("fixture_corpus") != expected_fixture or manifest.get("formal_run_executed") is not False or manifest.get("provider_calls") != 0:
        raise ValueError("formal_v4_manifest_execution_boundary_invalid")
    expected_boundaries = {"evaluation_only": True, "production_seed": False, "protected_asset_source": False, "formal_run_executed": False, "provider_calls": 0, "deployment": False, "ui_change": False}
    if manifest.get("boundaries") != expected_boundaries:
        raise ValueError("formal_v4_manifest_boundaries_invalid")
    corpus_manifest = _load(CORPUS_MANIFEST_PATH)
    if corpus_manifest != corpus_manifest_payload(V4_CORPUS_PATHS) or corpus_manifest.get("canonical_sha256") != EXPECTED_CORPUS_HASH:
        raise ValueError("formal_v4_corpus_manifest_invalid")
    entries = semantic_review.get("entries")
    case_ids = {case["case_id"] for case in case_set["cases"]}
    core_facts = {case["core_fact_key"] for case in case_set["cases"]}
    if semantic_review.get("schema_version") != "scc-eval-v4-semantic-review-v1" or semantic_review.get("review_scope") != "controller_accepted_for_freeze" or not isinstance(semantic_review.get("structural_validation_note"), str) or not isinstance(entries, list):
        raise ValueError("formal_v4_semantic_review_schema_invalid")
    if len(entries) != 15 or {entry.get("case_id") for entry in entries} != case_ids or {entry.get("core_fact_key") for entry in entries} != core_facts or any(entry.get("review_status") != "controller_accepted_for_freeze" or entry.get("same_decision_point") is not False for entry in entries):
        raise ValueError("formal_v4_semantic_review_acceptance_invalid")
    frozen_paths = {
        "evaluation/case_sets/eval-set-v4.json": CASE_SET_PATH,
        "evaluation/manifests/eval-set-v4-manifest.json": MANIFEST_PATH,
        "evaluation/v4-semantic-review.json": SEMANTIC_REVIEW_PATH,
        "evaluation/fixtures/eval-v4-corpus-manifest.json": CORPUS_MANIFEST_PATH,
        "evaluation/fixtures/eval-v4-mist-jetty.json": ROOT / "evaluation" / "fixtures" / "eval-v4-mist-jetty.json",
        "evaluation/fixtures/eval-v4-eave-cabin.json": ROOT / "evaluation" / "fixtures" / "eval-v4-eave-cabin.json",
        "evaluation/fixtures/eval-v4-mica-office.json": ROOT / "evaluation" / "fixtures" / "eval-v4-mica-office.json",
    }
    if integrity.get("schema_version") != "scc-eval-v4-freeze-integrity-v1" or integrity.get("status") != "frozen_data_assets" or integrity.get("case_canonical_sha256") != EXPECTED_CASE_HASH or integrity.get("corpus_canonical_sha256") != EXPECTED_CORPUS_HASH:
        raise ValueError("formal_v4_freeze_integrity_schema_invalid")
    recorded = integrity.get("frozen_files")
    if not isinstance(recorded, dict) or set(recorded) != set(frozen_paths) or any(recorded[relative] != sha256_file(path) for relative, path in frozen_paths.items()):
        raise ValueError("formal_v4_freeze_integrity_hash_mismatch")
    return {"valid": True, "case_canonical_sha256": EXPECTED_CASE_HASH, "corpus_canonical_sha256": EXPECTED_CORPUS_HASH, "semantic_review_entries": 15, "status": manifest["status"]}


if __name__ == "__main__":
    print(json.dumps(validate_formal_freeze(), ensure_ascii=False, indent=2))
