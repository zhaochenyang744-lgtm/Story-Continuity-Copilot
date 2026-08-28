"""Structural and overlap validation for the controller-review-only V3 candidate."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V3_CORPUS_PATHS, corpus_catalog, corpus_manifest_payload


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v3-candidate.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v3-candidate-manifest.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v3-corpus-manifest.json"
SEMANTIC_REVIEW_PATH = ROOT / "evaluation" / "v3-candidate-semantic-review.json"
PRIOR_CASE_PATHS = (ROOT / "evaluation" / "case_sets" / "eval-set-v1.json", ROOT / "evaluation" / "case_sets" / "eval-set-v2.json")
V2_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v2-manifest.json"
CLASSES = {"conflict", "no_conflict", "insufficient_evidence"}
REQUIRED_CATEGORIES = {"timeline", "relationship", "character_knowledge", "world_rule", "object_state"}


def load_v3_candidate(path: pathlib.Path = CASE_SET_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "scc-eval-case-set-v3-candidate" or payload.get("status") != "candidate_for_controller_review" or not isinstance(payload.get("cases"), list):
        raise ValueError("invalid_v3_candidate_case_set_schema")
    return payload


def normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text).casefold()


def ngrams(text: str, width: int = 8) -> set[str]:
    compact = normalize(text)
    return {compact[index:index + width] for index in range(max(0, len(compact) - width + 1))}


def _prior_cases() -> list[dict[str, Any]]:
    return [case for path in PRIOR_CASE_PATHS for case in json.loads(path.read_text(encoding="utf-8"))["cases"]]


def validate_v3_candidate_case_set(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or load_v3_candidate()
    cases = payload["cases"]
    required = {"case_id", "corpus_key", "seed_key", "target_draft", "target_claim_ordinal", "expected_class", "expected_category", "expected_severity", "expected_evidence", "rubric", "retrieval_difficulty", "core_fact_key", "claim_shape", "proper_nouns"}
    if len(cases) != 15 or any(not required <= set(case) for case in cases):
        raise ValueError("v3_candidate_case_count_or_fields_invalid")
    ids = [case["case_id"] for case in cases]
    core_facts = [case["core_fact_key"] for case in cases]
    if len(ids) != len(set(ids)) or len(core_facts) != len(set(core_facts)):
        raise ValueError("v3_candidate_ids_or_core_facts_not_unique")
    if any(not isinstance(case["target_draft"], str) or not case["target_draft"].strip() or not isinstance(case["rubric"], str) or not case["rubric"].strip() or not isinstance(case["proper_nouns"], list) for case in cases):
        raise ValueError("v3_candidate_text_invalid")
    classes = Counter(case["expected_class"] for case in cases)
    corpora = Counter(case["corpus_key"] for case in cases)
    if classes != Counter({"conflict": 5, "no_conflict": 5, "insufficient_evidence": 5}) or set(corpora) != set(V3_CORPUS_PATHS) or any(value != 5 for value in corpora.values()):
        raise ValueError("v3_candidate_balance_invalid")
    by_corpus: dict[str, set[str]] = defaultdict(set)
    catalog = corpus_catalog(V3_CORPUS_PATHS)
    if len(catalog) != 3 or any(len(catalog[key]) < 7 for key in V3_CORPUS_PATHS) or sum(len(catalog[key]) for key in V3_CORPUS_PATHS) < 21:
        raise ValueError("v3_candidate_corpus_fact_coverage_invalid")
    for case in cases:
        by_corpus[case["corpus_key"]].add(case["expected_class"])
        if case["corpus_key"] not in catalog or case["seed_key"] != case["corpus_key"] or case["target_claim_ordinal"] != 1 or case["expected_class"] not in CLASSES:
            raise ValueError("v3_candidate_case_scope_invalid")
        if not case["expected_evidence"]:
            raise ValueError("v3_candidate_expected_evidence_missing")
        for item in case["expected_evidence"]:
            if (item.get("chapter_number"), item.get("source_label")) not in catalog[case["corpus_key"]]:
                raise ValueError("v3_candidate_expected_evidence_unresolvable")
        if case["expected_class"] == "conflict":
            if case["expected_category"] not in REQUIRED_CATEGORIES or not case["expected_severity"]:
                raise ValueError("v3_candidate_conflict_expectation_invalid")
        elif case["expected_category"] is not None:
            raise ValueError("v3_candidate_non_conflict_category_invalid")
    if any(by_corpus[key] != CLASSES for key in V3_CORPUS_PATHS):
        raise ValueError("v3_candidate_each_corpus_must_cover_classes")
    categories = {case["expected_category"] for case in cases if case["expected_class"] == "conflict"}
    multi = [case for case in cases if case.get("requires_multiple_direct_evidence") and case["expected_class"] == "conflict" and len(case["expected_evidence"]) >= 2]
    invalid_multi = [case for case in cases if case.get("requires_multiple_direct_evidence") and case not in multi]
    difficult = sum(case["retrieval_difficulty"] == "nearby_distractor" for case in cases)
    if not REQUIRED_CATEGORIES <= categories or len(multi) < 2 or invalid_multi or difficult < 5:
        raise ValueError("v3_candidate_coverage_invalid")
    prior = _prior_cases()
    prior_ids = {case["case_id"] for case in prior}
    prior_normalized = {normalize(case["target_draft"]) for case in prior}
    prior_hashes = {hashlib.sha256(case["target_draft"].encode("utf-8")).hexdigest() for case in prior}
    prior_ngrams = set().union(*(ngrams(case["target_draft"]) for case in prior))
    for case in cases:
        target = case["target_draft"]
        if case["case_id"] in prior_ids or normalize(target) in prior_normalized or hashlib.sha256(target.encode("utf-8")).hexdigest() in prior_hashes:
            raise ValueError("v3_candidate_exact_prior_overlap")
        if ngrams(target) & prior_ngrams:
            raise ValueError("v3_candidate_sentence_skeleton_overlap")
        if any(
            token
            and not re.fullmatch(r"[东西南北中][堤塔站桥门巷]", token)
            and token in "\n".join(item["target_draft"] for item in prior)
            for token in case["proper_nouns"]
        ):
            raise ValueError("v3_candidate_proper_noun_overlap")
    return {"valid": True, "status": payload["status"], "case_count": 15, "class_counts": dict(classes), "corpus_counts": dict(corpora), "conflict_categories": sorted(categories), "multiple_direct_evidence_cases": len(multi), "nearby_distractor_cases": difficult, "canonical_sha256": canonical_sha256(payload)}


def validate_v3_semantic_review(case_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    cases = case_payload or load_v3_candidate()
    review = json.loads(SEMANTIC_REVIEW_PATH.read_text(encoding="utf-8"))
    entries = review.get("entries")
    if review.get("schema_version") != "scc-eval-v3-semantic-review-v1" or review.get("review_scope") != "implementation_reviewed_pending_controller" or not isinstance(review.get("structural_validation_note"), str) or not isinstance(entries, list):
        raise ValueError("v3_semantic_review_schema_invalid")
    ids = {case["case_id"] for case in cases["cases"]}
    core = {case["core_fact_key"] for case in cases["cases"]}
    if len(entries) != 15 or {entry.get("case_id") for entry in entries} != ids or {entry.get("core_fact_key") for entry in entries} != core:
        raise ValueError("v3_semantic_review_coverage_invalid")
    if any(entry.get("same_decision_point") is not False or entry.get("prior_overlap_checked") is not True or entry.get("review_status") != "implementation_reviewed_pending_controller" for entry in entries):
        raise ValueError("v3_semantic_review_status_invalid")
    return {"valid": True, "entry_count": 15, "manual_review_required": True}


def validate_v3_candidate_manifest(case_result: dict[str, Any] | None = None) -> dict[str, Any]:
    case_result = case_result or validate_v3_candidate_case_set()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    v2 = json.loads(V2_MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_case_set = {"path": "evaluation/case_sets/eval-set-v3-candidate.json", "canonical_sha256": case_result["canonical_sha256"], "case_count": 15, "split": {"conflict": 5, "no_conflict": 5, "insufficient_evidence": 5}}
    expected_fixture = {"path": "evaluation/fixtures/eval-v3-corpus-manifest.json", "canonical_sha256": corpus_manifest_payload(V3_CORPUS_PATHS)["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False}
    if manifest.get("manifest_version") != "scc-eval-manifest-v3-candidate" or manifest.get("status") != "candidate_for_controller_review" or manifest.get("case_set") != expected_case_set:
        raise ValueError("v3_candidate_manifest_identity_invalid")
    if manifest.get("required_thresholds") != v2["required_thresholds"] or manifest.get("scoring") != v2["scoring"] or manifest.get("fixture_corpus") != expected_fixture:
        raise ValueError("v3_candidate_manifest_baseline_invalid")
    if manifest.get("runtime_mode") != "evaluation_fixture" or manifest.get("formal_run_executed") is not False or manifest.get("provider_calls") != 0 or manifest.get("boundaries", {}).get("production_seed") is not False or manifest.get("boundaries", {}).get("protected_asset_source") is not False:
        raise ValueError("v3_candidate_manifest_boundary_invalid")
    selected = manifest.get("stability_protocol", {}).get("representative_case_ids", [])
    selected_cases = {case["case_id"]: case for case in load_v3_candidate()["cases"]}
    if len(selected) != 3 or len(set(selected)) != 3 or not all(item in selected_cases for item in selected) or {selected_cases[item]["expected_class"] for item in selected} != CLASSES or {selected_cases[item]["corpus_key"] for item in selected} != set(V3_CORPUS_PATHS):
        raise ValueError("v3_candidate_manifest_stability_invalid")
    corpus_manifest = json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8"))
    if corpus_manifest != corpus_manifest_payload(V3_CORPUS_PATHS):
        raise ValueError("v3_candidate_corpus_manifest_invalid")
    return {"valid": True, "status": manifest["status"], "canonical_sha256": case_result["canonical_sha256"], "corpus_canonical_sha256": expected_fixture["canonical_sha256"], "stability_case_ids": selected}


if __name__ == "__main__":
    result = validate_v3_candidate_case_set()
    print(json.dumps({"case_set": result, "semantic_review": validate_v3_semantic_review(load_v3_candidate()), "manifest": validate_v3_candidate_manifest(result)}, ensure_ascii=False, indent=2))
