"""Structural and overlap validation for the controller-review-only V4 candidate."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V4_CORPUS_PATHS, corpus_catalog, corpus_manifest_payload, load_corpus


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v4-candidate.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v4-candidate-manifest.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v4-corpus-manifest.json"
SEMANTIC_REVIEW_PATH = ROOT / "evaluation" / "v4-candidate-semantic-review.json"
PRIOR_CASE_PATHS = (
    ROOT / "evaluation" / "case_sets" / "eval-set-v1.json",
    ROOT / "evaluation" / "case_sets" / "eval-set-v2.json",
    ROOT / "evaluation" / "case_sets" / "eval-set-v3.json",
)
V3_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v3-manifest.json"
CLASSES = {"conflict", "no_conflict", "insufficient_evidence"}
REQUIRED_CATEGORIES = {"attribute", "timeline", "relationship", "character_knowledge", "world_rule"}
ALLOWED_MEMORY_TYPES = {"static_canon", "dynamic_state", "event_timeline", "character_knowledge", "open_thread"}


def load_v4_candidate(path: pathlib.Path = CASE_SET_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "scc-eval-case-set-v4-candidate" or payload.get("status") != "candidate_for_controller_review" or not isinstance(payload.get("cases"), list):
        raise ValueError("invalid_v4_candidate_case_set_schema")
    return payload


def normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text).casefold()


def ngrams(text: str, width: int = 8) -> set[str]:
    compact = normalize(text)
    return {compact[index:index + width] for index in range(max(0, len(compact) - width + 1))}


def _prior_cases() -> list[dict[str, Any]]:
    return [case for path in PRIOR_CASE_PATHS for case in json.loads(path.read_text(encoding="utf-8"))["cases"]]


def prior_decision_signature(case: dict[str, Any]) -> str | None:
    """Return a stable structural signature for historical cases lacking one."""
    declared = case.get("decision_signature")
    if isinstance(declared, str) and declared.strip():
        return declared
    shape = case.get("claim_shape")
    if not isinstance(shape, str) or not shape.strip():
        return None
    return f"{case.get('expected_class')}|{case.get('expected_category') or 'none'}|{shape}|legacy"


def validate_v4_corpus_memory_types(corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, int]:
    """Ensure candidate fixtures only use Memory types expressible by production APIs."""
    corpora = corpora or {key: load_corpus(key, V4_CORPUS_PATHS) for key in V4_CORPUS_PATHS}
    if set(corpora) != set(V4_CORPUS_PATHS):
        raise ValueError("v4_candidate_corpus_scope_invalid")
    counts: dict[str, int] = {}
    for key, corpus in corpora.items():
        records = corpus.get("memory")
        if not isinstance(records, list) or any(record.get("memory_type") not in ALLOWED_MEMORY_TYPES for record in records):
            raise ValueError("v4_candidate_corpus_memory_type_invalid")
        counts[key] = len(records)
    return counts


def validate_v4_candidate_case_set(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or load_v4_candidate()
    cases = payload["cases"]
    required = {"case_id", "corpus_key", "seed_key", "target_draft", "target_claim_ordinal", "expected_class", "expected_category", "expected_severity", "expected_evidence", "rubric", "retrieval_difficulty", "core_fact_key", "claim_shape", "decision_signature", "proper_nouns"}
    if len(cases) != 15 or any(not required <= set(case) for case in cases):
        raise ValueError("v4_candidate_case_count_or_fields_invalid")
    ids = [case["case_id"] for case in cases]
    core_facts = [case["core_fact_key"] for case in cases]
    claim_shapes = [case["claim_shape"] for case in cases]
    signatures = [case["decision_signature"] for case in cases]
    if len(ids) != len(set(ids)) or len(core_facts) != len(set(core_facts)) or len(claim_shapes) != len(set(claim_shapes)) or len(signatures) != len(set(signatures)):
        raise ValueError("v4_candidate_ids_or_core_facts_not_unique")
    if any(not isinstance(case["target_draft"], str) or not case["target_draft"].strip() or not isinstance(case["rubric"], str) or not case["rubric"].strip() or not isinstance(case["claim_shape"], str) or not case["claim_shape"].strip() or not isinstance(case["decision_signature"], str) or not case["decision_signature"].strip() or not isinstance(case["proper_nouns"], list) for case in cases):
        raise ValueError("v4_candidate_text_invalid")
    classes = Counter(case["expected_class"] for case in cases)
    corpora = Counter(case["corpus_key"] for case in cases)
    if classes != Counter({"conflict": 5, "no_conflict": 5, "insufficient_evidence": 5}) or set(corpora) != set(V4_CORPUS_PATHS) or any(value != 5 for value in corpora.values()):
        raise ValueError("v4_candidate_balance_invalid")
    validate_v4_corpus_memory_types()
    catalog = corpus_catalog(V4_CORPUS_PATHS)
    if len(catalog) != 3 or any(len(catalog[key]) < 7 for key in V4_CORPUS_PATHS) or sum(len(catalog[key]) for key in V4_CORPUS_PATHS) < 21:
        raise ValueError("v4_candidate_corpus_fact_coverage_invalid")
    by_corpus: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        by_corpus[case["corpus_key"]].add(case["expected_class"])
        if case["corpus_key"] not in catalog or case["seed_key"] != case["corpus_key"] or case["target_claim_ordinal"] != 1 or case["expected_class"] not in CLASSES or not case["expected_evidence"]:
            raise ValueError("v4_candidate_case_scope_invalid")
        if any((item.get("chapter_number"), item.get("source_label")) not in catalog[case["corpus_key"]] for item in case["expected_evidence"]):
            raise ValueError("v4_candidate_expected_evidence_unresolvable")
        if case["expected_class"] == "conflict":
            if case["expected_category"] not in REQUIRED_CATEGORIES or not case["expected_severity"]:
                raise ValueError("v4_candidate_conflict_expectation_invalid")
        elif case["expected_category"] is not None:
            raise ValueError("v4_candidate_non_conflict_category_invalid")
    if any(by_corpus[key] != CLASSES for key in V4_CORPUS_PATHS):
        raise ValueError("v4_candidate_each_corpus_must_cover_classes")
    categories = {case["expected_category"] for case in cases if case["expected_class"] == "conflict"}
    multi = [case for case in cases if case.get("requires_multiple_direct_evidence") and case["expected_class"] == "conflict" and len(case["expected_evidence"]) >= 2]
    invalid_multi = [case for case in cases if case.get("requires_multiple_direct_evidence") and case not in multi]
    difficult = sum(case["retrieval_difficulty"] == "nearby_distractor" for case in cases)
    if not REQUIRED_CATEGORIES <= categories or len(multi) < 2 or invalid_multi or difficult < 5:
        raise ValueError("v4_candidate_coverage_invalid")
    prior = _prior_cases()
    prior_ids = {case["case_id"] for case in prior}
    prior_core_facts = {case.get("core_fact_key") for case in prior}
    prior_claim_shapes = {case.get("claim_shape") for case in prior if isinstance(case.get("claim_shape"), str)}
    prior_signatures = {signature for case in prior if (signature := prior_decision_signature(case))}
    prior_normalized = {normalize(case["target_draft"]) for case in prior}
    prior_hashes = {hashlib.sha256(case["target_draft"].encode("utf-8")).hexdigest() for case in prior}
    prior_ngrams = set().union(*(ngrams(case["target_draft"]) for case in prior))
    prior_text = "\n".join(item["target_draft"] for item in prior)
    for case in cases:
        target = case["target_draft"]
        if case["case_id"] in prior_ids or case["core_fact_key"] in prior_core_facts or normalize(target) in prior_normalized or hashlib.sha256(target.encode("utf-8")).hexdigest() in prior_hashes:
            raise ValueError("v4_candidate_exact_prior_overlap")
        if case["claim_shape"] in prior_claim_shapes:
            raise ValueError("v4_candidate_prior_claim_shape_overlap")
        if case["decision_signature"] in prior_signatures:
            raise ValueError("v4_candidate_prior_decision_signature_overlap")
        if ngrams(target) & prior_ngrams:
            raise ValueError("v4_candidate_sentence_skeleton_overlap")
        if any(token and not re.fullmatch(r"[东西南北中][堤塔站桥门巷]", token) and token in prior_text for token in case["proper_nouns"]):
            raise ValueError("v4_candidate_proper_noun_overlap")
    return {"valid": True, "status": payload["status"], "case_count": 15, "class_counts": dict(classes), "corpus_counts": dict(corpora), "conflict_categories": sorted(categories), "multiple_direct_evidence_cases": len(multi), "nearby_distractor_cases": difficult, "canonical_sha256": canonical_sha256(payload)}


def validate_v4_semantic_review(case_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    cases = case_payload or load_v4_candidate()
    review = json.loads(SEMANTIC_REVIEW_PATH.read_text(encoding="utf-8"))
    entries = review.get("entries")
    if review.get("schema_version") != "scc-eval-v4-semantic-review-v2" or review.get("review_scope") != "pending_controller_review" or not isinstance(review.get("structural_validation_note"), str) or not isinstance(entries, list):
        raise ValueError("v4_semantic_review_schema_invalid")
    ids = {case["case_id"] for case in cases["cases"]}
    core = {case["core_fact_key"] for case in cases["cases"]}
    if len(entries) != 15 or {entry.get("case_id") for entry in entries} != ids or {entry.get("core_fact_key") for entry in entries} != core or any(entry.get("same_decision_point") is not None or not isinstance(entry.get("prior_archetype_reference"), str) or not entry["prior_archetype_reference"].strip() or entry.get("review_status") != "pending_controller_review" for entry in entries):
        raise ValueError("v4_semantic_review_coverage_or_status_invalid")
    return {"valid": True, "entry_count": 15, "manual_review_required": True}


def validate_v4_candidate_manifest(case_result: dict[str, Any] | None = None) -> dict[str, Any]:
    case_result = case_result or validate_v4_candidate_case_set()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    v3 = json.loads(V3_MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_case_set = {"path": "evaluation/case_sets/eval-set-v4-candidate.json", "canonical_sha256": case_result["canonical_sha256"], "case_count": 15, "split": {"conflict": 5, "no_conflict": 5, "insufficient_evidence": 5}}
    expected_fixture = {"path": "evaluation/fixtures/eval-v4-corpus-manifest.json", "canonical_sha256": corpus_manifest_payload(V4_CORPUS_PATHS)["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False}
    if manifest.get("manifest_version") != "scc-eval-manifest-v4-candidate" or manifest.get("status") != "candidate_for_controller_review" or manifest.get("case_set") != expected_case_set:
        raise ValueError("v4_candidate_manifest_identity_invalid")
    if manifest.get("required_thresholds") != v3["required_thresholds"] or manifest.get("scoring") != v3["scoring"] or manifest.get("fixture_corpus") != expected_fixture or manifest.get("runtime_mode") != "evaluation_fixture" or manifest.get("formal_run_executed") is not False or manifest.get("provider_calls") != 0:
        raise ValueError("v4_candidate_manifest_baseline_or_boundary_invalid")
    selected = manifest.get("stability_protocol", {}).get("representative_case_ids", [])
    selected_cases = {case["case_id"]: case for case in load_v4_candidate()["cases"]}
    if len(selected) != 3 or len(set(selected)) != 3 or not all(item in selected_cases for item in selected) or {selected_cases[item]["expected_class"] for item in selected} != CLASSES or {selected_cases[item]["corpus_key"] for item in selected} != set(V4_CORPUS_PATHS):
        raise ValueError("v4_candidate_manifest_stability_invalid")
    if json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8")) != corpus_manifest_payload(V4_CORPUS_PATHS):
        raise ValueError("v4_candidate_corpus_manifest_invalid")
    return {"valid": True, "status": manifest["status"], "canonical_sha256": case_result["canonical_sha256"], "corpus_canonical_sha256": expected_fixture["canonical_sha256"], "stability_case_ids": selected}


if __name__ == "__main__":
    result = validate_v4_candidate_case_set()
    print(json.dumps({"case_set": result, "semantic_review": validate_v4_semantic_review(load_v4_candidate()), "manifest": validate_v4_candidate_manifest(result)}, ensure_ascii=False, indent=2))
