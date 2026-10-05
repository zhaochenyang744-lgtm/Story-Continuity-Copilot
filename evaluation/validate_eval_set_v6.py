"""Fail-closed validation for the controller-approved V6 formal input freeze."""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V6_CORPUS_PATHS, corpus_manifest_payload
from evaluation.validate_eval_set_v6_candidate import validate_all as validate_candidate


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v6-candidate.json"
CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v6.json"
CANDIDATE_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-candidate-manifest.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-manifest.json"
CANDIDATE_REVIEW_PATH = ROOT / "evaluation" / "v6-candidate-semantic-review.json"
REVIEW_PATH = ROOT / "evaluation" / "v6-semantic-review.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v6-corpus-manifest.json"
PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v6-first-formal-plan.json"
INTEGRITY_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-freeze-integrity.json"

EXPECTED_CASE_CANONICAL_HASH = "3b40e1a157be6e61be58025f7429c7011f30461c6b995ddb1dd9c28adf7564f0"
EXPECTED_CORPUS_CANONICAL_HASH = "24cc03de333f2dc397748c1e419df03b782c45e07364f8e11b8497c046f0c753"
EXPECTED_FROZEN_FILE_HASHES = {
    "evaluation/case_sets/eval-set-v6.json": "0ccb0831e7b120091ae3fc9c67b65d982929de3f81525bd9be354c1936adb115",
    "evaluation/manifests/eval-set-v6-manifest.json": "fa9cffdc5d6d6d7d465e043dfb630a6c8ea47783aaf28cf2c6ec9eed3c4ec5b7",
    "evaluation/v6-semantic-review.json": "992de80b72c09a5f1c702fc76132b8eb965a9fb64bdbf229a075bf99713e60c2",
    "evaluation/fixtures/eval-v6-corpus-manifest.json": "c4f270cfb1c6ad0675e0391640fbd86dc0b4b6a8cf15e0feefbb18915ce26861",
    "evaluation/fixtures/eval-v6-lumen-tidehouse.json": "4d4fdaa57262bf6e1eac5bed230d0cd5bcfcee942735eccc74d19cd16c0ccb91",
    "evaluation/fixtures/eval-v6-velvet-signal-yard.json": "f8fbad31eac556a33083e778fedbb4e6b9c0a3b61a038b74b0df514c0024f5ad",
    "evaluation/fixtures/eval-v6-quartz-aviary.json": "2dfab135faddc4de6ec3ed622445387a0edc4825299fa452bcfd48587afec65b",
    "evaluation/fixtures/eval-v6-cinder-lantern-ferry.json": "8a535d066bc9880f2aa7704271fd484d853233913b13b63692c6154722b5e1d6",
}


def _read(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_paths() -> dict[str, pathlib.Path]:
    return {
        "evaluation/case_sets/eval-set-v6.json": CASE_PATH,
        "evaluation/manifests/eval-set-v6-manifest.json": MANIFEST_PATH,
        "evaluation/v6-semantic-review.json": REVIEW_PATH,
        "evaluation/fixtures/eval-v6-corpus-manifest.json": CORPUS_MANIFEST_PATH,
        **{f"evaluation/fixtures/{path.name}": path for path in V6_CORPUS_PATHS.values()},
    }


def validate_formal_freeze(
    case_path: pathlib.Path = CASE_PATH,
    manifest_path: pathlib.Path = MANIFEST_PATH,
    review_path: pathlib.Path = REVIEW_PATH,
    integrity_path: pathlib.Path = INTEGRITY_PATH,
) -> dict[str, Any]:
    """Validate the exact V6 freeze before or after the one permitted formal run."""
    if any(actual.resolve() != expected.resolve() for actual, expected in ((case_path, CASE_PATH), (manifest_path, MANIFEST_PATH), (review_path, REVIEW_PATH), (integrity_path, INTEGRITY_PATH))):
        raise ValueError("formal_v6_assets_must_use_frozen_paths")
    candidate_result = validate_candidate()
    if candidate_result.get("status") != "candidate_for_controller_review" or candidate_result.get("case_set", {}).get("status") != "candidate_for_controller_review":
        raise ValueError("formal_v6_accepted_candidate_no_longer_valid")
    if CANDIDATE_CASE_PATH.read_bytes() != CASE_PATH.read_bytes():
        raise ValueError("formal_v6_case_set_not_byte_identical_to_candidate")
    candidate, case_set = _read(CANDIDATE_CASE_PATH), _read(CASE_PATH)
    if candidate != case_set or canonical_sha256(case_set) != EXPECTED_CASE_CANONICAL_HASH:
        raise ValueError("formal_v6_case_set_hash_invalid")

    candidate_manifest, manifest = _read(CANDIDATE_MANIFEST_PATH), _read(MANIFEST_PATH)
    expected_case_set = {"path": "evaluation/case_sets/eval-set-v6.json", "canonical_sha256": EXPECTED_CASE_CANONICAL_HASH, "case_count": 24, "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8}, "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2}}
    if manifest.get("manifest_version") != "scc-eval-manifest-v6" or manifest.get("status") != "approved_for_formal_run" or manifest.get("case_set") != expected_case_set or manifest.get("runtime_mode") != "evaluation_fixture":
        raise ValueError("formal_v6_manifest_not_approved_or_case_invalid")
    for field in ("required_thresholds", "scoring", "stability_protocol", "fixture_corpus", "formal_run_plan"):
        if manifest.get(field) != candidate_manifest.get(field):
            raise ValueError("formal_v6_manifest_rules_differ_from_accepted_candidate")
    expected_approval = {"controller_candidate_gate_passed": True, "real_provider_authorization_received": False, "approval_scope": "evaluation_input_freeze_only", "accepted_case_canonical_sha256": EXPECTED_CASE_CANONICAL_HASH, "accepted_corpus_canonical_sha256": EXPECTED_CORPUS_CANONICAL_HASH}
    expected_boundaries = {**candidate_manifest["boundaries"], "controller_candidate_gate_passed": True}
    if manifest.get("approval") != expected_approval or manifest.get("boundaries") != expected_boundaries or manifest.get("formal_run_executed") is not False or manifest.get("provider_calls") != 0:
        raise ValueError("formal_v6_manifest_approval_or_execution_boundary_invalid")

    plan_result = candidate_result["formal_plan"]
    if plan_result.get("lifecycle") not in {"pre_run", "post_run"}:
        raise ValueError("formal_v6_plan_lifecycle_invalid")
    formal_case_sets = sorted(path.name for path in CASE_PATH.parent.glob("eval-set-v6*.json"))
    if formal_case_sets != ["eval-set-v6-candidate.json", "eval-set-v6.json"]:
        raise ValueError("formal_v6_case_path_not_unique")

    corpus = _read(CORPUS_MANIFEST_PATH)
    if corpus != corpus_manifest_payload(V6_CORPUS_PATHS) or corpus.get("canonical_sha256") != EXPECTED_CORPUS_CANONICAL_HASH:
        raise ValueError("formal_v6_corpus_manifest_invalid")
    candidate_review, review = _read(CANDIDATE_REVIEW_PATH), _read(REVIEW_PATH)
    case_by_id = {case["case_id"]: case for case in case_set["cases"]}
    candidate_by_id = {entry["case_id"]: entry for entry in candidate_review["entries"]}
    acceptance = {"accepted_case_canonical_sha256": EXPECTED_CASE_CANONICAL_HASH, "accepted_corpus_canonical_sha256": EXPECTED_CORPUS_CANONICAL_HASH, "accepted_case_count": 24, "all_same_decision_point": False}
    if review.get("schema_version") != "scc-eval-v6-semantic-review-v1" or review.get("review_scope") != "controller_accepted_for_freeze" or review.get("status") != "approved_for_formal_run" or review.get("formal_run_executed") is not False or review.get("provider_calls") != 0 or review.get("controller_acceptance") != acceptance:
        raise ValueError("formal_v6_semantic_review_schema_invalid")
    entries = review.get("entries")
    if not isinstance(entries, list) or len(entries) != 24 or {entry.get("case_id") for entry in entries} != set(case_by_id):
        raise ValueError("formal_v6_semantic_review_coverage_invalid")
    for entry in entries:
        case, prior = case_by_id[entry["case_id"]], candidate_by_id.get(entry["case_id"], {})
        if entry.get("corpus_key") != case["corpus_key"] or entry.get("core_fact_key") != case["core_fact_key"] or any(entry.get(field) != prior.get(field) for field in ("decision_point", "prior_archetype_reference", "why_independent")) or entry.get("same_decision_point") is not False or entry.get("review_status") != "controller_accepted_for_freeze":
            raise ValueError("formal_v6_semantic_review_acceptance_invalid")

    integrity = _read(INTEGRITY_PATH)
    if integrity.get("schema_version") != "scc-eval-v6-freeze-integrity-v1" or integrity.get("status") != "frozen_data_assets" or integrity.get("formal_run_executed") is not False or integrity.get("provider_calls") != 0 or integrity.get("real_provider_authorization_received") is not False or integrity.get("case_canonical_sha256") != EXPECTED_CASE_CANONICAL_HASH or integrity.get("corpus_canonical_sha256") != EXPECTED_CORPUS_CANONICAL_HASH:
        raise ValueError("formal_v6_freeze_integrity_schema_invalid")
    frozen_paths = _frozen_paths()
    if integrity.get("frozen_files") != EXPECTED_FROZEN_FILE_HASHES or set(EXPECTED_FROZEN_FILE_HASHES) != set(frozen_paths) or any(_sha(path) != EXPECTED_FROZEN_FILE_HASHES[key] for key, path in frozen_paths.items()):
        raise ValueError("formal_v6_freeze_integrity_hash_mismatch")
    return {"valid": True, "case_canonical_sha256": EXPECTED_CASE_CANONICAL_HASH, "corpus_canonical_sha256": EXPECTED_CORPUS_CANONICAL_HASH, "semantic_review_entries": 24, "frozen_file_count": len(frozen_paths), "case_set_byte_identical_to_candidate": True, "controller_candidate_gate_passed": True, "real_provider_authorization_received": candidate_result["formal_run_executed"], "formal_run_executed": candidate_result["formal_run_executed"], "provider_calls": candidate_result["provider_calls"], "status": "approved_for_formal_run", "lifecycle": plan_result["lifecycle"], "formal_result_status": plan_result["status"] if plan_result["lifecycle"] == "post_run" else None}


if __name__ == "__main__":
    print(json.dumps(validate_formal_freeze(), ensure_ascii=False, indent=2))
