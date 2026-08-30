"""Strict structural, lineage, separation, and boundary validator for V5 candidate assets."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import (
    CORPUS_PATHS,
    V3_CORPUS_PATHS,
    V4_CORPUS_PATHS,
    V5_CORPUS_PATHS,
    corpus_manifest_payload,
    load_corpus,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v5-candidate.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v5-candidate-manifest.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v5-corpus-manifest.json"
SEMANTIC_REVIEW_PATH = ROOT / "evaluation" / "v5-candidate-semantic-review.json"
FORMAL_PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v5-first-formal-plan.json"
V4_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v4-candidate-manifest.json"
PRIOR_CASE_PATHS = tuple(ROOT / "evaluation" / "case_sets" / name for name in (
    "eval-set-v1.json", "eval-set-v2.json", "eval-set-v3.json", "eval-set-v4.json"
))
PRIOR_CORPUS_PATHS = {**CORPUS_PATHS, **V3_CORPUS_PATHS, **V4_CORPUS_PATHS}
CLASSES = {"conflict", "no_conflict", "insufficient_evidence"}
CONFLICT_CATEGORIES = {
    "attribute", "object_state", "relationship", "character_knowledge",
    "timeline", "world_rule", "location_action", "event_status",
}
CHALLENGE_TAGS = {
    "requires_multiple_direct_evidence", "ambiguous_evidence", "conflicting_sources",
    "insufficient_evidence", "category_mismatch_regression", "supported_control",
}
ALLOWED_MEMORY_TYPES = {"static_canon", "dynamic_state", "event_timeline", "character_knowledge", "open_thread"}
FORBIDDEN_SOURCE_TOKENS = ("story-continuity-poc", "heldout", "held-out", "golden", ".env", "poc.sqlite")


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text).casefold()


def ngrams(text: str, width: int) -> set[str]:
    compact = normalize(text)
    return {compact[index:index + width] for index in range(max(0, len(compact) - width + 1))}


def load_v5_candidate(path: pathlib.Path = CASE_SET_PATH) -> dict[str, Any]:
    payload = _read_json(path)
    if (
        payload.get("schema_version") != "scc-eval-case-set-v5-candidate"
        or payload.get("status") != "candidate_for_controller_review"
        or payload.get("formal_run_executed") is not False
        or payload.get("provider_calls") != 0
        or not isinstance(payload.get("cases"), list)
    ):
        raise ValueError("v5_candidate_case_set_schema_or_boundary_invalid")
    return payload


def _load_v5_corpora(corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    return corpora or {key: load_corpus(key, V5_CORPUS_PATHS) for key in V5_CORPUS_PATHS}


def _prior_cases() -> list[dict[str, Any]]:
    return [case for path in PRIOR_CASE_PATHS for case in _read_json(path)["cases"]]


def _prior_corpora() -> list[dict[str, Any]]:
    return [load_corpus(key, PRIOR_CORPUS_PATHS) for key in PRIOR_CORPUS_PATHS]


def _corpus_catalog(corpora: dict[str, dict[str, Any]]) -> dict[str, dict[tuple[int, str], str]]:
    catalog: dict[str, dict[tuple[int, str], str]] = {}
    for key, corpus in corpora.items():
        locations: dict[tuple[int, str], str] = {}
        for chapter in corpus["chapters"]:
            semantic = (chapter.get("chapter_number"), chapter.get("source_label"))
            if semantic in locations or not isinstance(semantic[0], int) or not isinstance(semantic[1], str) or not semantic[1]:
                raise ValueError("v5_candidate_evidence_catalog_invalid")
            locations[semantic] = chapter.get("body")
        catalog[key] = locations
    return catalog


def validate_v5_corpora(corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    corpora = _load_v5_corpora(corpora)
    if set(corpora) != set(V5_CORPUS_PATHS) or len(corpora) != 4:
        raise ValueError("v5_candidate_corpus_scope_invalid")
    prior_cases = _prior_cases()
    prior_corpus_keys = {case.get("corpus_key") for case in prior_cases}
    prior_text = "\n".join(
        [case.get("target_draft", "") for case in prior_cases]
        + [chapter.get("body", "") for corpus in _prior_corpora() for chapter in corpus["chapters"]]
    )
    prior_titles = {corpus.get("title") for corpus in _prior_corpora()}
    prior_evidence_normalized = {normalize(chapter["body"]) for corpus in _prior_corpora() for chapter in corpus["chapters"]}
    prior_evidence_ngrams = set().union(*(ngrams(chapter["body"], 16) for corpus in _prior_corpora() for chapter in corpus["chapters"]))
    seen_lineage_tokens: set[str] = set()
    chapter_counts: dict[str, int] = {}
    for key, corpus in corpora.items():
        if key in prior_corpus_keys or corpus.get("title") in prior_titles:
            raise ValueError("v5_candidate_prior_corpus_key_or_title_reuse")
        if corpus.get("corpus_key") != key or corpus.get("evaluation_only") is not True or corpus.get("production_seed") is not False or corpus.get("protected_asset_source") is not False:
            raise ValueError("v5_candidate_corpus_boundary_invalid")
        generation = corpus.get("generation")
        if generation != {"method": "deterministic_original", "generator_version": "v5-candidate-1", "source_inputs": []}:
            raise ValueError("v5_candidate_corpus_generation_lineage_invalid")
        lineage = corpus.get("lineage")
        if not isinstance(lineage, dict) or lineage.get("work_title") != corpus.get("title") or any(not isinstance(lineage.get(field), list) or not lineage[field] for field in ("characters", "locations")) or not isinstance(lineage.get("core_design"), str):
            raise ValueError("v5_candidate_corpus_lineage_invalid")
        lineage_tokens = set([lineage["work_title"], *lineage["characters"], *lineage["locations"], lineage["core_design"]])
        for token in lineage_tokens:
            if not isinstance(token, str) or not token.strip() or token in seen_lineage_tokens or normalize(token) in normalize(prior_text):
                raise ValueError("v5_candidate_prior_or_cross_corpus_lineage_reuse")
            seen_lineage_tokens.add(token)
        chapters = corpus.get("chapters")
        memory = corpus.get("memory")
        if not isinstance(chapters, list) or len(chapters) != 8 or not isinstance(memory, list) or len(memory) < 4:
            raise ValueError("v5_candidate_corpus_content_count_invalid")
        for chapter in chapters:
            body = chapter.get("body")
            if not isinstance(body, str) or not body.strip() or normalize(body) in prior_evidence_normalized or ngrams(body, 16) & prior_evidence_ngrams:
                raise ValueError("v5_candidate_prior_evidence_text_reuse")
        if any(record.get("memory_type") not in ALLOWED_MEMORY_TYPES for record in memory):
            raise ValueError("v5_candidate_corpus_memory_type_invalid")
        chapter_counts[key] = len(chapters)
    _corpus_catalog(corpora)
    return {"valid": True, "corpus_count": 4, "chapter_counts": chapter_counts}


def _validate_rubric(case: dict[str, Any]) -> None:
    rubric = case.get("rubric")
    required = {"decision_rule", "expected_class_reason", "expected_category_reason", "minimum_direct_evidence", "requires_full_expected_evidence", "forbidden_inference"}
    if not isinstance(rubric, dict) or set(rubric) != required:
        raise ValueError("v5_candidate_rubric_schema_invalid")
    if any(not isinstance(rubric[field], str) or not rubric[field].strip() for field in required - {"minimum_direct_evidence", "requires_full_expected_evidence"}):
        raise ValueError("v5_candidate_rubric_text_invalid")
    if not isinstance(rubric["minimum_direct_evidence"], int) or rubric["minimum_direct_evidence"] < 0 or not isinstance(rubric["requires_full_expected_evidence"], bool):
        raise ValueError("v5_candidate_rubric_requirement_invalid")


def validate_v5_candidate_case_set(payload: dict[str, Any] | None = None, corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = payload or load_v5_candidate()
    if payload.get("formal_run_executed") is not False or payload.get("provider_calls") != 0:
        raise ValueError("v5_candidate_formal_or_provider_field_false_report")
    corpora = _load_v5_corpora(corpora)
    validate_v5_corpora(corpora)
    catalog = _corpus_catalog(corpora)
    cases = payload.get("cases")
    required = {
        "case_id", "corpus_key", "seed_key", "target_draft", "target_claim_ordinal", "expected_class",
        "expected_category", "expected_severity", "expected_evidence", "source_lineage", "challenge_tags",
        "retrieval_difficulty", "core_fact_key", "claim_shape", "decision_signature", "proper_nouns", "rubric",
    }
    if not isinstance(cases, list) or len(cases) != 24 or any(not required <= set(case) for case in cases):
        raise ValueError("v5_candidate_case_count_or_fields_invalid")
    unique_fields = ("case_id", "core_fact_key", "claim_shape", "decision_signature")
    if any(len({case[field] for case in cases}) != 24 for field in unique_fields):
        raise ValueError("v5_candidate_duplicate_case_or_semantic_identifier")
    classes = Counter(case["expected_class"] for case in cases)
    corpora_counts = Counter(case["corpus_key"] for case in cases)
    if classes != Counter({item: 8 for item in CLASSES}) or corpora_counts != Counter({key: 6 for key in V5_CORPUS_PATHS}):
        raise ValueError("v5_candidate_global_quota_invalid")
    per_corpus: dict[str, Counter] = defaultdict(Counter)
    categories: Counter = Counter()
    prior = _prior_cases()
    prior_ids = {case.get("case_id") for case in prior}
    prior_core = {case.get("core_fact_key") for case in prior if case.get("core_fact_key")}
    prior_shapes = {case.get("claim_shape") for case in prior if case.get("claim_shape")}
    prior_signatures = {case.get("decision_signature") for case in prior if case.get("decision_signature")}
    prior_targets = {normalize(case.get("target_draft", "")) for case in prior}
    prior_target_ngrams = set().union(*(ngrams(case.get("target_draft", ""), 12) for case in prior))
    prior_text = normalize("\n".join(case.get("target_draft", "") for case in prior) + "\n" + "\n".join(chapter["body"] for corpus in _prior_corpora() for chapter in corpus["chapters"]))
    for case in cases:
        _validate_rubric(case)
        if case["case_id"] in prior_ids or case["core_fact_key"] in prior_core or case["claim_shape"] in prior_shapes or case["decision_signature"] in prior_signatures:
            raise ValueError("v5_candidate_prior_identifier_or_core_fact_reuse")
        target = case["target_draft"]
        if not isinstance(target, str) or not target.strip() or normalize(target) in prior_targets or ngrams(target, 12) & prior_target_ngrams:
            raise ValueError("v5_candidate_prior_target_text_reuse")
        if not isinstance(case["proper_nouns"], list) or not case["proper_nouns"] or any(not isinstance(token, str) or not token.strip() or normalize(token) in prior_text for token in case["proper_nouns"]):
            raise ValueError("v5_candidate_prior_proper_noun_reuse")
        if case["corpus_key"] not in V5_CORPUS_PATHS or case["seed_key"] != case["corpus_key"] or case["target_claim_ordinal"] != 1:
            raise ValueError("v5_candidate_project_isolation_invalid")
        if case["expected_class"] not in CLASSES:
            raise ValueError("v5_candidate_class_invalid")
        per_corpus[case["corpus_key"]][case["expected_class"]] += 1
        tags = case["challenge_tags"]
        if not isinstance(tags, list) or len(tags) != len(set(tags)) or not set(tags) <= CHALLENGE_TAGS:
            raise ValueError("v5_candidate_challenge_tags_invalid")
        evidence = case["expected_evidence"]
        lineage = case["source_lineage"]
        if not isinstance(evidence, list) or not evidence or not isinstance(lineage, list) or len(lineage) != len(evidence):
            raise ValueError("v5_candidate_evidence_or_lineage_schema_invalid")
        expected_lineage = []
        for item in evidence:
            semantic = (item.get("chapter_number"), item.get("source_label"))
            body = catalog[case["corpus_key"]].get(semantic)
            if body is None or item.get("body_sha256") != _text_sha256(body):
                raise ValueError("v5_candidate_expected_evidence_unresolvable")
            expected_lineage.append({"corpus_key": case["corpus_key"], **item})
        if lineage != expected_lineage:
            raise ValueError("v5_candidate_cross_corpus_or_missing_source_lineage")
        rubric = case["rubric"]
        if case["expected_class"] == "conflict":
            categories[case["expected_category"]] += 1
            if case["expected_category"] not in CONFLICT_CATEGORIES or not case["expected_severity"]:
                raise ValueError("v5_candidate_conflict_category_invalid")
            if not case.get("requires_multiple_direct_evidence") or "requires_multiple_direct_evidence" not in tags or len(evidence) < 2:
                raise ValueError("v5_candidate_multiple_direct_evidence_invalid")
            if rubric["minimum_direct_evidence"] != len(evidence) or rubric["requires_full_expected_evidence"] is not True:
                raise ValueError("v5_candidate_conflict_rubric_evidence_invalid")
        else:
            if case["expected_category"] is not None:
                raise ValueError("v5_candidate_non_conflict_category_invalid")
            if case["expected_class"] == "no_conflict" and (case["expected_severity"] is not None or "supported_control" not in tags):
                raise ValueError("v5_candidate_no_conflict_expectation_invalid")
            if case["expected_class"] == "insufficient_evidence" and ("insufficient_evidence" not in tags or rubric["minimum_direct_evidence"] != 0):
                raise ValueError("v5_candidate_insufficient_challenge_invalid")
    if any(per_corpus[key] != Counter({item: 2 for item in CLASSES}) for key in V5_CORPUS_PATHS):
        raise ValueError("v5_candidate_per_corpus_quota_invalid")
    if categories != Counter({category: 1 for category in CONFLICT_CATEGORIES}):
        raise ValueError("v5_candidate_conflict_category_coverage_invalid")
    coverage = Counter(tag for case in cases for tag in case["challenge_tags"])
    if coverage["requires_multiple_direct_evidence"] < 4 or coverage["ambiguous_evidence"] < 4 or coverage["conflicting_sources"] < 4 or coverage["insufficient_evidence"] != 8 or coverage["category_mismatch_regression"] != 3:
        raise ValueError("v5_candidate_challenge_coverage_invalid")
    return {
        "valid": True,
        "status": payload["status"],
        "case_count": 24,
        "class_counts": dict(classes),
        "corpus_counts": dict(corpora_counts),
        "conflict_categories": sorted(categories),
        "challenge_counts": dict(coverage),
        "canonical_sha256": canonical_sha256(payload),
    }


def validate_v5_semantic_review(case_payload: dict[str, Any] | None = None, review: dict[str, Any] | None = None) -> dict[str, Any]:
    case_payload = case_payload or load_v5_candidate()
    review = review or _read_json(SEMANTIC_REVIEW_PATH)
    entries = review.get("entries")
    if review.get("schema_version") != "scc-eval-v5-semantic-review-v1" or review.get("review_scope") != "pending_controller_review" or review.get("status") != "candidate_for_controller_review" or review.get("formal_run_executed") is not False or review.get("provider_calls") != 0:
        raise ValueError("v5_semantic_review_schema_or_boundary_invalid")
    ids = {case["case_id"] for case in case_payload["cases"]}
    if not isinstance(entries, list) or len(entries) != 24 or {entry.get("case_id") for entry in entries} != ids:
        raise ValueError("v5_semantic_review_coverage_invalid")
    if any(entry.get("same_decision_point") is not None or entry.get("review_status") != "pending_controller_review" or not all(isinstance(entry.get(field), str) and entry[field].strip() for field in ("decision_point", "prior_archetype_reference", "why_independent")) for entry in entries):
        raise ValueError("v5_semantic_review_status_invalid")
    return {"valid": True, "entry_count": 24, "manual_review_required": True}


def validate_v5_formal_plan(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan or _read_json(FORMAL_PLAN_PATH)
    if plan.get("schema_version") != "scc-eval-v5-first-formal-plan-v1" or plan.get("status") != "not_run" or plan.get("formal_run_executed") is not False or plan.get("provider_calls") != 0 or plan.get("controller_candidate_gate_passed") is not False or plan.get("real_provider_authorization_received") is not False:
        raise ValueError("v5_formal_plan_false_report")
    outputs = plan.get("planned_output_paths")
    if not isinstance(outputs, dict) or set(outputs) != {"checkpoint", "results", "report", "bad_cases", "stability", "run_manifest", "api_scan", "post_run_integrity"}:
        raise ValueError("v5_formal_plan_output_schema_invalid")
    expected_outputs = {
        "checkpoint": "evaluation/results/eval-v5-first-formal-checkpoint.json",
        "results": "evaluation/results/eval-v5-first-formal-results.json",
        "report": "evaluation/results/eval-v5-first-formal-report.md",
        "bad_cases": "evaluation/results/eval-v5-first-formal-bad-cases.json",
        "stability": "evaluation/results/eval-v5-first-formal-stability.json",
        "run_manifest": "evaluation/results/eval-v5-first-formal-run-manifest.json",
        "api_scan": "evaluation/results/eval-v5-first-formal-api-corpus-scan.json",
        "post_run_integrity": "evaluation/results/v5-first-formal-post-run-integrity.json",
    }
    if outputs != expected_outputs:
        raise ValueError("v5_formal_plan_output_schema_invalid")
    existing = []
    for value in outputs.values():
        path = (ROOT / value).resolve()
        if (ROOT / "evaluation" / "results").resolve() not in path.parents:
            raise ValueError("v5_formal_plan_output_exists_or_escapes_results")
        existing.append(path.exists())
    if any(existing) and not all(existing):
        raise ValueError("v5_formal_plan_output_exists_or_escapes_results")
    if all(existing):
        # The plan is an immutable candidate-era snapshot. After its authorized
        # once-only execution, planned outputs are accepted only as one complete,
        # hash-frozen, independently revalidated result bundle.
        from evaluation.validate_v5_first_formal_results import validate as validate_results
        validate_results()
    stability = plan.get("stability_protocol", {})
    if stability.get("independent_runs_per_case") != 3 or stability.get("additional_calls_after_formal") != 6 or stability.get("execution_status") != "not_run":
        raise ValueError("v5_formal_plan_stability_invalid")
    if plan.get("bad_case_protocol", {}).get("raw_provider_body_retained") is not False or plan.get("bad_case_protocol", {}).get("chain_of_thought_retained") is not False:
        raise ValueError("v5_formal_plan_bad_case_sanitization_invalid")
    return {"valid": True, "status": "not_run", "planned_outputs": len(outputs), "retained_outputs_present": all(existing)}


def validate_v5_candidate_manifest(case_result: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    case_result = case_result or validate_v5_candidate_case_set()
    manifest = manifest or _read_json(MANIFEST_PATH)
    v4 = _read_json(V4_MANIFEST_PATH)
    if manifest.get("manifest_version") != "scc-eval-manifest-v5-candidate" or manifest.get("status") != "candidate_for_controller_review" or manifest.get("formal_run_executed") is not False or manifest.get("provider_calls") != 0:
        raise ValueError("v5_candidate_manifest_identity_or_boundary_invalid")
    expected_case = {
        "path": "evaluation/case_sets/eval-set-v5-candidate.json",
        "canonical_sha256": case_result["canonical_sha256"],
        "case_count": 24,
        "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8},
        "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2},
    }
    expected_corpus = {
        "path": "evaluation/fixtures/eval-v5-corpus-manifest.json",
        "canonical_sha256": corpus_manifest_payload(V5_CORPUS_PATHS)["canonical_sha256"],
        "evaluation_only": True,
        "production_seed": False,
        "protected_asset_source": False,
    }
    if manifest.get("case_set") != expected_case or manifest.get("fixture_corpus") != expected_corpus or manifest.get("runtime_mode") != "evaluation_fixture":
        raise ValueError("v5_candidate_manifest_hash_or_scope_invalid")
    if _read_json(CORPUS_MANIFEST_PATH) != corpus_manifest_payload(V5_CORPUS_PATHS):
        raise ValueError("v5_candidate_corpus_manifest_hash_mismatch")
    thresholds = manifest.get("required_thresholds", {})
    for key, value in v4["required_thresholds"].items():
        if thresholds.get(key) != value:
            raise ValueError("v5_candidate_threshold_below_or_changed_from_v4")
    expected_new = {
        "conflict_category_accuracy_min": 0.75,
        "designated_category_mismatch_regression_required_correct": 3,
        "designated_category_mismatch_regression_required_total": 3,
        "expected_evidence_recall_min": 0.8,
        "multi_direct_evidence_full_set_recall_min": 0.75,
    }
    if any(thresholds.get(key) != value for key, value in expected_new.items()):
        raise ValueError("v5_candidate_new_threshold_invalid")
    boundaries = manifest.get("boundaries", {})
    if boundaries.get("formal_run_executed") is not False or boundaries.get("provider_calls") != 0 or boundaries.get("real_provider_authorization") is not False or boundaries.get("controller_candidate_gate_passed") is not False:
        raise ValueError("v5_candidate_manifest_false_formal_or_provider_field")
    selected = manifest.get("stability_protocol", {}).get("representative_case_ids", [])
    by_id = {case["case_id"]: case for case in load_v5_candidate()["cases"]}
    if len(selected) != 3 or len(set(selected)) != 3 or not all(item in by_id for item in selected) or {by_id[item]["expected_class"] for item in selected} != CLASSES or manifest["stability_protocol"].get("additional_calls_after_formal") != 6 or manifest["stability_protocol"].get("execution_status") != "not_run":
        raise ValueError("v5_candidate_stability_selection_invalid")
    validate_v5_formal_plan()
    return {"valid": True, "status": manifest["status"], "canonical_sha256": case_result["canonical_sha256"], "corpus_canonical_sha256": expected_corpus["canonical_sha256"], "stability_case_ids": selected}


def validate_forbidden_boundaries() -> dict[str, Any]:
    payloads = [load_v5_candidate(), *_load_v5_corpora().values(), _read_json(MANIFEST_PATH), _read_json(FORMAL_PLAN_PATH)]
    serialized = json.dumps(payloads, ensure_ascii=False).casefold()
    if any(token in serialized for token in FORBIDDEN_SOURCE_TOKENS):
        raise ValueError("v5_candidate_forbidden_source_boundary_reference")
    return {"valid": True, "forbidden_reference_count": 0}


def validate_all() -> dict[str, Any]:
    case_payload = load_v5_candidate()
    case_result = validate_v5_candidate_case_set(case_payload)
    return {
        "case_set": case_result,
        "corpora": validate_v5_corpora(),
        "semantic_review": validate_v5_semantic_review(case_payload),
        "manifest": validate_v5_candidate_manifest(case_result),
        "formal_plan": validate_v5_formal_plan(),
        "forbidden_boundaries": validate_forbidden_boundaries(),
        "formal_run_executed": False,
        "provider_calls": 0,
        "status": "candidate_for_controller_review",
    }


if __name__ == "__main__":
    print(json.dumps(validate_all(), ensure_ascii=False, indent=2))
