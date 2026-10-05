"""Structural validation for the controller-review-only V2 evaluation candidate."""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter, defaultdict

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import CORPUS_PATHS, corpus_catalog, corpus_manifest_payload


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v2-candidate.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v2-candidate-manifest.json"
V1_CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v1.json"
V1_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v1-manifest.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v2-corpus-manifest.json"
SEMANTIC_REVIEW_PATH = ROOT / "evaluation" / "v2-candidate-semantic-review.json"
CLASSES = {"conflict", "no_conflict", "insufficient_evidence"}


def load_candidate(path: pathlib.Path = CASE_SET_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "scc-eval-case-set-v2-candidate" or payload.get("status") != "candidate_for_controller_review" or not isinstance(payload.get("cases"), list):
        raise ValueError("invalid_candidate_case_set_schema")
    return payload


def draft_sha256(case: dict) -> str:
    return hashlib.sha256(case["target_draft"].encode("utf-8")).hexdigest()


def target_claim_text(case: dict) -> str:
    # Candidate cases are explicitly one-claim drafts. Keep this separate from
    # the draft checksum so future claim extraction cannot weaken the overlap guard.
    return case["target_draft"].strip()


def validate_candidate_case_set(payload: dict | None = None) -> dict:
    payload = payload or load_candidate()
    cases = payload["cases"]
    required = {"case_id", "corpus_key", "seed_key", "target_draft", "target_claim_ordinal", "expected_class", "expected_category", "expected_severity", "expected_evidence", "rubric", "retrieval_difficulty"}
    if len(cases) != 15:
        raise ValueError("candidate_case_count_must_be_15")
    if any(not required <= set(case) for case in cases):
        raise ValueError("candidate_missing_required_case_fields")
    ids = [case.get("case_id") for case in cases]
    if len(ids) != len(set(ids)) or any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise ValueError("candidate_case_ids_must_be_unique")
    classes = Counter(case.get("expected_class") for case in cases)
    if classes != Counter({"conflict": 5, "no_conflict": 5, "insufficient_evidence": 5}):
        raise ValueError("candidate_classes_must_be_balanced")
    corpora = Counter(case.get("corpus_key") for case in cases)
    if set(corpora) != set(CORPUS_PATHS) or any(count != 5 for count in corpora.values()):
        raise ValueError("candidate_all_three_isolated_corpora_required")
    classes_by_corpus: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        classes_by_corpus[case["corpus_key"]].add(case["expected_class"])
    if any(classes_by_corpus[corpus_key] != CLASSES for corpus_key in corpora):
        raise ValueError("candidate_each_corpus_must_cover_all_classes")
    conflict_categories = {case["expected_category"] for case in cases if case["expected_class"] == "conflict"}
    required_categories = {"timeline", "relationship", "character_knowledge", "world_rule", "object_state"}
    if not required_categories <= conflict_categories:
        raise ValueError("candidate_conflict_category_coverage_incomplete")
    multi = [case for case in cases if case.get("requires_multiple_direct_evidence") and case["expected_class"] == "conflict" and len(case["expected_evidence"]) >= 2]
    invalid_multi = [case for case in cases if case.get("requires_multiple_direct_evidence") and (case["expected_class"] != "conflict" or len(case["expected_evidence"]) < 2)]
    if len(multi) < 2 or invalid_multi:
        raise ValueError("candidate_multiple_direct_evidence_requirement_failed")
    boundary = [case for case in cases if case.get("category_boundary")]
    boundary_categories = {case["expected_category"] for case in boundary}
    if len(boundary) < 2 or not {"relationship", "character_knowledge"} <= boundary_categories:
        raise ValueError("candidate_relationship_knowledge_boundary_requirement_failed")
    difficult = sum(case["retrieval_difficulty"] == "nearby_distractor" for case in cases)
    if difficult < 5:
        raise ValueError("candidate_nearby_distractor_requirement_failed")
    catalog = corpus_catalog()
    for case in cases:
        if case["corpus_key"] not in catalog or case["seed_key"] != case["corpus_key"] or case["expected_class"] not in CLASSES or case["target_claim_ordinal"] != 1:
            raise ValueError(f"candidate_invalid_case_input:{case['case_id']}")
        if not isinstance(case["target_draft"], str) or not case["target_draft"].strip() or not isinstance(case["rubric"], str) or not case["rubric"].strip():
            raise ValueError(f"candidate_invalid_case_text:{case['case_id']}")
        if case["expected_class"] == "conflict":
            if not isinstance(case["expected_category"], str) or not case["expected_severity"]:
                raise ValueError(f"candidate_conflict_expectation_incomplete:{case['case_id']}")
        elif case["expected_category"] is not None:
            raise ValueError(f"candidate_non_conflict_category_must_be_null:{case['case_id']}")
        if not case["expected_evidence"]:
            raise ValueError(f"candidate_expected_evidence_required:{case['case_id']}")
        for expected in case["expected_evidence"]:
            location = (expected.get("chapter_number"), expected.get("source_label"))
            if location not in catalog[case["corpus_key"]]:
                raise ValueError(f"candidate_unresolvable_expected_evidence:{case['case_id']}:{location}")
    v1_cases = json.loads(V1_CASE_SET_PATH.read_text(encoding="utf-8"))["cases"]
    if set(ids) & {case["case_id"] for case in v1_cases}:
        raise ValueError("candidate_case_id_overlaps_v1")
    if {draft_sha256(case) for case in cases} & {draft_sha256(case) for case in v1_cases}:
        raise ValueError("candidate_target_draft_hash_overlaps_v1")
    if {target_claim_text(case) for case in cases} & {target_claim_text(case) for case in v1_cases}:
        raise ValueError("candidate_target_claim_text_overlaps_v1")
    return {
        "valid": True,
        "status": payload["status"],
        "case_count": len(cases),
        "class_counts": dict(classes),
        "corpus_counts": dict(corpora),
        "conflict_categories": sorted(conflict_categories),
        "multiple_direct_evidence_cases": len(multi),
        "relationship_knowledge_boundary_cases": len(boundary),
        "nearby_distractor_cases": difficult,
        "provisional_canonical_sha256": canonical_sha256(payload),
    }


def validate_semantic_review() -> dict:
    review = json.loads(SEMANTIC_REVIEW_PATH.read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in load_candidate()["cases"]}
    v1_cases = {case["case_id"] for case in json.loads(V1_CASE_SET_PATH.read_text(encoding="utf-8"))["cases"]}
    entries = review.get("entries")
    if review.get("schema_version") != "scc-eval-v2-semantic-review-v1" or not isinstance(entries, list) or not isinstance(review.get("structural_validation_note"), str):
        raise ValueError("candidate_semantic_review_schema_invalid")
    entry_ids = [entry.get("case_id") for entry in entries]
    if len(entries) != 15 or len(entry_ids) != len(set(entry_ids)) or set(entry_ids) != set(cases):
        raise ValueError("candidate_semantic_review_must_cover_all_cases")
    for entry in entries:
        if entry.get("corpus_key") != cases[entry["case_id"]]["corpus_key"]:
            raise ValueError("candidate_semantic_review_corpus_mismatch")
        if entry.get("nearest_v1_case_id") not in v1_cases or entry.get("nearest_v2_case_id") not in cases or entry.get("nearest_v2_case_id") == entry["case_id"]:
            raise ValueError("candidate_semantic_review_reference_invalid")
        if entry.get("same_decision_point") is not False or not isinstance(entry.get("why_not_same_fact_or_decision_point"), str) or not isinstance(entry.get("why_not_duplicate"), str) or not entry["why_not_same_fact_or_decision_point"].strip() or not entry["why_not_duplicate"].strip():
            raise ValueError("candidate_semantic_review_independence_invalid")
    return {"valid": True, "entry_count": len(entries), "manual_review_required": True}


def validate_candidate_manifest(case_result: dict | None = None) -> dict:
    case_result = case_result or validate_candidate_case_set()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    v1_manifest = json.loads(V1_MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != "scc-eval-manifest-v2-candidate" or manifest.get("status") != "candidate_for_controller_review":
        raise ValueError("candidate_manifest_status_invalid")
    if manifest.get("case_set") != {
        "path": "evaluation/case_sets/eval-set-v2-candidate.json",
        "canonical_sha256": case_result["provisional_canonical_sha256"],
        "case_count": 15,
        "split": {"conflict": 5, "no_conflict": 5, "insufficient_evidence": 5},
    }:
        raise ValueError("candidate_manifest_case_set_invalid")
    if manifest.get("required_thresholds") != v1_manifest["required_thresholds"]:
        raise ValueError("candidate_manifest_thresholds_differ_from_v1")
    if manifest.get("scoring") != v1_manifest["scoring"]:
        raise ValueError("candidate_manifest_scoring_differs_from_v1")
    corpus_manifest = json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8"))
    if corpus_manifest != corpus_manifest_payload():
        raise ValueError("candidate_corpus_manifest_hash_invalid")
    expected_fixture = {"path": "evaluation/fixtures/eval-v2-corpus-manifest.json", "canonical_sha256": corpus_manifest["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False}
    if manifest.get("fixture_corpus") != expected_fixture:
        raise ValueError("candidate_manifest_fixture_corpus_invalid")
    stability = manifest.get("stability_protocol", {})
    selected = stability.get("representative_case_ids", [])
    candidates = {case["case_id"]: case for case in load_candidate()["cases"]}
    if len(selected) != 3 or len(set(selected)) != 3 or not all(case_id in candidates for case_id in selected):
        raise ValueError("candidate_stability_selection_invalid")
    if {candidates[case_id]["expected_class"] for case_id in selected} != CLASSES or {candidates[case_id]["corpus_key"] for case_id in selected} != set(CORPUS_PATHS):
        raise ValueError("candidate_stability_selection_must_cover_classes_and_corpora")
    if stability.get("independent_runs_per_case") != 3 or stability.get("additional_calls_after_formal") != 6:
        raise ValueError("candidate_stability_protocol_differs")
    return {"valid": True, "status": manifest["status"], "provisional_canonical_sha256": case_result["provisional_canonical_sha256"], "stability_case_ids": selected}


if __name__ == "__main__":
    result = validate_candidate_case_set()
    print(json.dumps({"case_set": result, "semantic_review": validate_semantic_review(), "manifest": validate_candidate_manifest(result)}, ensure_ascii=False, indent=2))
