"""Fail-closed structural and separation validator for the V6 candidate only."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import (
    CORPUS_PATHS, V3_CORPUS_PATHS, V4_CORPUS_PATHS, V5_CORPUS_PATHS,
    V6_CORPUS_PATHS, corpus_manifest_payload, load_corpus,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v6-candidate.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-candidate-manifest.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v6-corpus-manifest.json"
SEMANTIC_REVIEW_PATH = ROOT / "evaluation" / "v6-candidate-semantic-review.json"
FORMAL_PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v6-first-formal-plan.json"
V5_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v5-candidate-manifest.json"
PRIOR_CASE_PATHS = tuple(ROOT / "evaluation" / "case_sets" / name for name in (
    "eval-set-v1.json", "eval-set-v2.json", "eval-set-v3.json", "eval-set-v4.json",
    "eval-set-v5.json", "eval-set-v5-candidate.json",
))
PRIOR_CORPUS_PATHS = {**CORPUS_PATHS, **V3_CORPUS_PATHS, **V4_CORPUS_PATHS, **V5_CORPUS_PATHS}
CLASSES = {"conflict", "no_conflict", "insufficient_evidence"}
CONFLICT_CATEGORIES = {
    "attribute", "object_state", "relationship", "character_knowledge",
    "timeline", "world_rule", "location_action", "event_status",
}
CHALLENGE_TAGS = {
    "requires_multiple_direct_evidence", "ambiguous_evidence", "conflicting_sources",
    "insufficient_evidence", "category_mismatch_regression", "supported_control",
}
FORBIDDEN_SOURCE_TOKENS = ("story-continuity-poc", "heldout", "held-out", "golden", ".env", "poc.sqlite")


def _read(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text).casefold()


def ngrams(text: str, width: int = 16) -> set[str]:
    compact = normalize(text)
    return {compact[i:i + width] for i in range(max(0, len(compact) - width + 1))}


def load_v6_candidate(path: pathlib.Path = CASE_SET_PATH) -> dict[str, Any]:
    payload = _read(path)
    if (payload.get("schema_version") != "scc-eval-case-set-v6-candidate"
            or payload.get("status") != "candidate_for_controller_review"
            or payload.get("evaluation_only") is not True
            or payload.get("production_seed") is not False
            or payload.get("protected_asset_source") is not False
            or payload.get("formal_run_executed") is not False
            or payload.get("provider_calls") != 0
            or not isinstance(payload.get("cases"), list)):
        raise ValueError("v6_candidate_case_set_schema_or_boundary_invalid")
    return payload


def _v6_corpora(corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    return corpora or {key: load_corpus(key, V6_CORPUS_PATHS) for key in V6_CORPUS_PATHS}


def _prior_cases() -> list[dict[str, Any]]:
    return [case for path in PRIOR_CASE_PATHS for case in _read(path)["cases"]]


def _prior_corpora() -> list[dict[str, Any]]:
    return [load_corpus(key, PRIOR_CORPUS_PATHS) for key in PRIOR_CORPUS_PATHS]


def _catalog(corpora: dict[str, dict[str, Any]]) -> dict[str, dict[tuple[int, str], str]]:
    catalog: dict[str, dict[tuple[int, str], str]] = {}
    for key, corpus in corpora.items():
        entries = {(item.get("chapter_number"), item.get("source_label")): item.get("body") for item in corpus["chapters"]}
        if len(entries) != 8 or any(not isinstance(number, int) or not isinstance(label, str) or not label or not isinstance(body, str) or not body for (number, label), body in entries.items()):
            raise ValueError("v6_candidate_evidence_catalog_invalid")
        catalog[key] = entries
    return catalog


def validate_v6_corpora(corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    corpora = _v6_corpora(corpora)
    if set(corpora) != set(V6_CORPUS_PATHS) or len(corpora) != 4:
        raise ValueError("v6_candidate_corpus_scope_invalid")
    prior = _prior_corpora()
    prior_keys = {corpus["corpus_key"] for corpus in prior}
    prior_titles = {corpus["title"] for corpus in prior}
    prior_text = "\n".join(chapter["body"] for corpus in prior for chapter in corpus["chapters"])
    prior_ngrams = set().union(*(ngrams(chapter["body"]) for corpus in prior for chapter in corpus["chapters"]))
    seen_lineage: set[str] = set()
    for key, corpus in corpora.items():
        if key in prior_keys or corpus.get("title") in prior_titles:
            raise ValueError("v6_candidate_prior_corpus_key_or_title_reuse")
        if (corpus.get("corpus_key") != key or corpus.get("evaluation_only") is not True
                or corpus.get("production_seed") is not False or corpus.get("protected_asset_source") is not False
                or corpus.get("generation") != {"method": "deterministic_original", "generator_version": "v6-candidate-1", "source_inputs": []}):
            raise ValueError("v6_candidate_corpus_boundary_or_generation_invalid")
        lineage = corpus.get("lineage")
        if not isinstance(lineage, dict) or lineage.get("work_title") != corpus.get("title") or not isinstance(lineage.get("core_design"), str):
            raise ValueError("v6_candidate_corpus_lineage_invalid")
        names = [lineage["work_title"], *lineage.get("characters", []), *lineage.get("locations", []), lineage["core_design"]]
        if not all(isinstance(item, str) and item.strip() for item in names) or any(item in seen_lineage or normalize(item) in normalize(prior_text) for item in names):
            raise ValueError("v6_candidate_prior_or_cross_corpus_lineage_reuse")
        seen_lineage.update(names)
        if not isinstance(corpus.get("chapters"), list) or len(corpus["chapters"]) != 8 or not isinstance(corpus.get("memory"), list) or len(corpus["memory"]) < 4:
            raise ValueError("v6_candidate_corpus_content_count_invalid")
        for chapter in corpus["chapters"]:
            body = chapter.get("body")
            if not isinstance(body, str) or not body.strip() or ngrams(body) & prior_ngrams:
                raise ValueError("v6_candidate_prior_evidence_text_reuse")
    _catalog(corpora)
    return {"valid": True, "corpus_count": 4, "chapter_counts": {key: 8 for key in corpora}}


def _validate_rubric(case: dict[str, Any]) -> None:
    required = {"decision_rule", "expected_class_reason", "expected_category_reason", "minimum_direct_evidence", "requires_full_expected_evidence", "forbidden_inference"}
    rubric = case.get("rubric")
    if not isinstance(rubric, dict) or set(rubric) != required or not isinstance(rubric["minimum_direct_evidence"], int) or not isinstance(rubric["requires_full_expected_evidence"], bool):
        raise ValueError("v6_candidate_rubric_schema_invalid")
    if any(not isinstance(rubric[key], str) or not rubric[key].strip() for key in required - {"minimum_direct_evidence", "requires_full_expected_evidence"}):
        raise ValueError("v6_candidate_rubric_text_invalid")


def validate_v6_candidate_case_set(payload: dict[str, Any] | None = None, corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = payload or load_v6_candidate()
    if payload.get("formal_run_executed") is not False or payload.get("provider_calls") != 0:
        raise ValueError("v6_candidate_formal_or_provider_field_false_report")
    corpora = _v6_corpora(corpora)
    validate_v6_corpora(corpora)
    catalog = _catalog(corpora)
    cases = payload.get("cases")
    required = {"case_id", "corpus_key", "seed_key", "target_draft", "target_claim_ordinal", "expected_class", "expected_category", "expected_severity", "expected_evidence", "source_lineage", "requires_multiple_direct_evidence", "challenge_tags", "retrieval_difficulty", "core_fact_key", "claim_shape", "decision_signature", "proper_nouns", "rubric"}
    if not isinstance(cases, list) or len(cases) != 24 or any(not required <= set(case) for case in cases):
        raise ValueError("v6_candidate_case_count_or_fields_invalid")
    for field in ("case_id", "core_fact_key", "claim_shape", "decision_signature"):
        if len({case[field] for case in cases}) != 24:
            raise ValueError("v6_candidate_duplicate_case_or_semantic_identifier")
    classes, keys, categories, coverage = Counter(), Counter(), Counter(), Counter()
    per_corpus: dict[str, Counter] = defaultdict(Counter)
    prior = _prior_cases()
    prior_ids = {case.get("case_id") for case in prior}
    prior_identifiers = {field: {case.get(field) for case in prior} for field in ("core_fact_key", "claim_shape", "decision_signature")}
    prior_text = "\n".join([case.get("target_draft", "") for case in prior] + [chapter["body"] for corpus in _prior_corpora() for chapter in corpus["chapters"]])
    prior_target_ngrams = set().union(*(ngrams(case.get("target_draft", ""), 12) for case in prior))
    for case in cases:
        _validate_rubric(case)
        if case["case_id"] in prior_ids or any(case[field] in prior_identifiers[field] for field in prior_identifiers):
            raise ValueError("v6_candidate_prior_identifier_or_core_fact_reuse")
        if not isinstance(case["target_draft"], str) or not case["target_draft"].strip() or ngrams(case["target_draft"], 12) & prior_target_ngrams:
            raise ValueError("v6_candidate_prior_target_text_reuse")
        nouns = case["proper_nouns"]
        if not isinstance(nouns, list) or not nouns or any(not isinstance(noun, str) or not noun.strip() or normalize(noun) in normalize(prior_text) for noun in nouns):
            raise ValueError("v6_candidate_prior_proper_noun_reuse")
        if case["corpus_key"] not in V6_CORPUS_PATHS or case["seed_key"] != case["corpus_key"] or case["target_claim_ordinal"] != 1 or case["expected_class"] not in CLASSES:
            raise ValueError("v6_candidate_project_or_class_invalid")
        classes[case["expected_class"]] += 1; keys[case["corpus_key"]] += 1; per_corpus[case["corpus_key"]][case["expected_class"]] += 1
        tags = case["challenge_tags"]
        if not isinstance(tags, list) or len(tags) != len(set(tags)) or not set(tags) <= CHALLENGE_TAGS:
            raise ValueError("v6_candidate_challenge_tags_invalid")
        coverage.update(tags)
        evidence, lineage = case["expected_evidence"], case["source_lineage"]
        if not isinstance(evidence, list) or not evidence or not isinstance(lineage, list) or len(evidence) != len(lineage):
            raise ValueError("v6_candidate_evidence_or_lineage_schema_invalid")
        expected_lineage = []
        for item in evidence:
            semantic = (item.get("chapter_number"), item.get("source_label"))
            if catalog[case["corpus_key"]].get(semantic) is None or item.get("body_sha256") != _sha(catalog[case["corpus_key"]][semantic]):
                raise ValueError("v6_candidate_expected_evidence_unresolvable")
            expected_lineage.append({"corpus_key": case["corpus_key"], **item})
        if lineage != expected_lineage:
            raise ValueError("v6_candidate_cross_corpus_or_missing_source_lineage")
        rubric = case["rubric"]
        if case["expected_class"] == "conflict":
            categories[case["expected_category"]] += 1
            if case["expected_category"] not in CONFLICT_CATEGORIES or not case["expected_severity"] or not case["requires_multiple_direct_evidence"] or "requires_multiple_direct_evidence" not in tags or len(evidence) < 2 or rubric["minimum_direct_evidence"] != len(evidence) or rubric["requires_full_expected_evidence"] is not True:
                raise ValueError("v6_candidate_conflict_category_or_multiple_evidence_invalid")
        elif case["expected_category"] is not None or case["requires_multiple_direct_evidence"]:
            raise ValueError("v6_candidate_non_conflict_category_or_evidence_invalid")
        elif case["expected_class"] == "no_conflict" and (case["expected_severity"] is not None or "supported_control" not in tags):
            raise ValueError("v6_candidate_no_conflict_expectation_invalid")
        elif case["expected_class"] == "insufficient_evidence" and ("insufficient_evidence" not in tags or rubric["minimum_direct_evidence"] != 0):
            raise ValueError("v6_candidate_insufficient_challenge_invalid")
    if classes != Counter({item: 8 for item in CLASSES}) or keys != Counter({key: 6 for key in V6_CORPUS_PATHS}) or any(per_corpus[key] != Counter({item: 2 for item in CLASSES}) for key in V6_CORPUS_PATHS):
        raise ValueError("v6_candidate_class_or_corpus_quota_invalid")
    if categories != Counter({category: 1 for category in CONFLICT_CATEGORIES}):
        raise ValueError("v6_candidate_conflict_category_coverage_invalid")
    if coverage["requires_multiple_direct_evidence"] < 8 or coverage["conflicting_sources"] < 4 or coverage["ambiguous_evidence"] + coverage["insufficient_evidence"] < 8 or coverage["insufficient_evidence"] != 8 or coverage["category_mismatch_regression"] < 3:
        raise ValueError("v6_candidate_challenge_coverage_invalid")
    return {"valid": True, "status": payload["status"], "case_count": 24, "class_counts": dict(classes), "corpus_counts": dict(keys), "conflict_categories": sorted(categories), "challenge_counts": dict(coverage), "canonical_sha256": canonical_sha256(payload)}


def validate_v6_semantic_review(case_payload: dict[str, Any] | None = None, review: dict[str, Any] | None = None) -> dict[str, Any]:
    case_payload = case_payload or load_v6_candidate(); review = review or _read(SEMANTIC_REVIEW_PATH)
    entries = review.get("entries", [])
    if (review.get("schema_version") != "scc-eval-v6-semantic-review-v1" or review.get("review_scope") != "pending_controller_review" or review.get("status") != "candidate_for_controller_review" or review.get("formal_run_executed") is not False or review.get("provider_calls") != 0):
        raise ValueError("v6_semantic_review_schema_or_boundary_invalid")
    if len(entries) != 24 or {entry.get("case_id") for entry in entries} != {case["case_id"] for case in case_payload["cases"]}:
        raise ValueError("v6_semantic_review_coverage_invalid")
    if any(entry.get("same_decision_point") is not None or entry.get("review_status") != "pending_controller_review" or not all(isinstance(entry.get(field), str) and entry[field].strip() for field in ("decision_point", "prior_archetype_reference", "why_independent")) for entry in entries):
        raise ValueError("v6_semantic_review_status_invalid")
    if len({entry["decision_point"] for entry in entries}) != 24:
        raise ValueError("v6_semantic_review_duplicate_decision_point")
    return {"valid": True, "entry_count": 24, "manual_review_required": True}


def validate_v6_formal_plan(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan or _read(FORMAL_PLAN_PATH)
    expected_outputs = {"checkpoint": "evaluation/results/eval-v6-first-formal-checkpoint.json", "results": "evaluation/results/eval-v6-first-formal-results.json", "report": "evaluation/results/eval-v6-first-formal-report.md", "bad_cases": "evaluation/results/eval-v6-first-formal-bad-cases.json", "stability": "evaluation/results/eval-v6-first-formal-stability.json", "run_manifest": "evaluation/results/eval-v6-first-formal-run-manifest.json", "api_scan": "evaluation/results/eval-v6-first-formal-api-corpus-scan.json", "post_run_integrity": "evaluation/results/v6-first-formal-post-run-integrity.json"}
    if (plan.get("schema_version") != "scc-eval-v6-first-formal-plan-v1" or plan.get("controller_candidate_gate_passed") is not True or plan.get("planned_output_paths") != expected_outputs):
        raise ValueError("v6_formal_plan_false_report_or_outputs_invalid")
    planned_inputs = {"case_set": "evaluation/case_sets/eval-set-v6.json", "manifest": "evaluation/manifests/eval-set-v6-manifest.json", "corpus_manifest": "evaluation/fixtures/eval-v6-corpus-manifest.json"}
    formal_inputs = [ROOT / planned_inputs["case_set"], ROOT / planned_inputs["manifest"]]
    if plan.get("planned_input_paths") != planned_inputs or not all(path.exists() for path in formal_inputs):
        raise ValueError("v6_formal_plan_frozen_input_invalid")
    stability = plan.get("stability_protocol", {})
    if stability.get("independent_runs_per_case") != 3 or stability.get("additional_calls_after_formal") != 6 or stability.get("terminal_failure_quality_stability") is not False:
        raise ValueError("v6_formal_plan_stability_invalid")
    protocol = plan.get("bad_case_protocol", {})
    if protocol.get("merge_failure_dimensions_per_case") is not True or protocol.get("raw_provider_body_retained") is not False or protocol.get("chain_of_thought_retained") is not False:
        raise ValueError("v6_formal_plan_bad_case_protocol_invalid")
    output_paths = {name: ROOT / value for name, value in expected_outputs.items()}
    workspace = ROOT / "evaluation" / "fixture-workspaces" / "scc-web-demo-eval-v6-first-formal"
    if plan.get("status") == "not_run":
        if (plan.get("formal_run_executed") is not False or plan.get("provider_calls") != 0 or plan.get("real_provider_authorization_received") is not False or stability.get("execution_status") != "not_run" or any(path.exists() for path in output_paths.values()) or workspace.exists()):
            raise ValueError("v6_formal_plan_pre_run_state_invalid")
        return {"valid": True, "lifecycle": "pre_run", "planned_outputs": 8, "formal_input_freeze_present": True, "controller_candidate_gate_passed": True, "status": "not_run", "formal_run_executed": False, "provider_calls": 0}
    if plan.get("status") != "gate_failed" or plan.get("formal_run_executed") is not True or plan.get("provider_calls") != 30 or plan.get("real_provider_authorization_received") is not True or stability.get("execution_status") != "gate_failed" or not all(path.is_file() for path in output_paths.values()) or not workspace.is_dir():
        raise ValueError("v6_formal_plan_post_run_state_invalid")
    from evaluation.validate_v6_first_formal_results import validate as validate_results
    result = validate_results()
    if result.get("status") != "gate_failed" or result.get("formal_case_count") != 24 or result.get("provider_run_count") != 30 or result.get("actual_provider_http_attempts") != 30 or result.get("successful_provider_responses") != 30 or result.get("run_status_totals") != {"completed": 30}:
        raise ValueError("v6_formal_plan_post_run_result_mismatch")
    stage = plan.get("stage_status")
    if stage != {"stage_10": "gate_failed_not_passed", "stage_11": "not_started", "stage_12": "not_started", "v7_or_repeat_authorized": False}:
        raise ValueError("v6_formal_plan_stage_boundary_invalid")
    audit = plan.get("post_run_audit")
    if not isinstance(audit, dict) or audit.get("source") != "frozen_results_rows_and_bad_cases" or audit.get("known_artifact_limitation") != "The frozen V6 Bad Case artifact records failure_dimensions but omits expected_category and predicted_category; this audit derives category detail from the immutable results rows." or not isinstance(audit.get("bad_cases"), list) or len(audit["bad_cases"]) != 7:
        raise ValueError("v6_formal_plan_post_run_audit_invalid")
    return {"valid": True, "lifecycle": "post_run", "planned_outputs": 8, "formal_input_freeze_present": True, "controller_candidate_gate_passed": True, "status": "gate_failed", "formal_run_executed": True, "provider_calls": 30, "result_validator": result}


def validate_v6_candidate_manifest(case_result: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    case_result = case_result or validate_v6_candidate_case_set(); manifest = manifest or _read(MANIFEST_PATH); v5 = _read(V5_MANIFEST_PATH)
    if (manifest.get("manifest_version") != "scc-eval-manifest-v6-candidate" or manifest.get("status") != "candidate_for_controller_review" or manifest.get("formal_run_executed") is not False or manifest.get("provider_calls") != 0):
        raise ValueError("v6_candidate_manifest_identity_or_boundary_invalid")
    expected_case = {"path": "evaluation/case_sets/eval-set-v6-candidate.json", "canonical_sha256": case_result["canonical_sha256"], "case_count": 24, "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8}, "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2}}
    expected_corpus = {"path": "evaluation/fixtures/eval-v6-corpus-manifest.json", "canonical_sha256": corpus_manifest_payload(V6_CORPUS_PATHS)["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False}
    if manifest.get("case_set") != expected_case or manifest.get("fixture_corpus") != expected_corpus or manifest.get("runtime_mode") != "evaluation_fixture" or _read(CORPUS_MANIFEST_PATH) != corpus_manifest_payload(V6_CORPUS_PATHS):
        raise ValueError("v6_candidate_manifest_hash_or_scope_invalid")
    if manifest.get("scoring") != v5.get("scoring") or manifest.get("required_thresholds") != v5.get("required_thresholds"):
        raise ValueError("v6_candidate_threshold_below_or_changed_from_v5")
    boundaries = manifest.get("boundaries", {})
    if any(boundaries.get(key) != value for key, value in {"evaluation_only": True, "production_seed": False, "protected_asset_source": False, "formal_run_executed": False, "provider_calls": 0, "real_provider_authorization": False, "controller_candidate_gate_passed": False}.items()):
        raise ValueError("v6_candidate_manifest_false_formal_or_provider_field")
    selected = manifest.get("stability_protocol", {}).get("representative_case_ids", []); by_id = {case["case_id"]: case for case in load_v6_candidate()["cases"]}
    if len(selected) != 3 or len(set(selected)) != 3 or not all(item in by_id for item in selected) or {by_id[item]["expected_class"] for item in selected} != CLASSES:
        raise ValueError("v6_candidate_stability_selection_invalid")
    validate_v6_formal_plan()
    return {"valid": True, "canonical_sha256": case_result["canonical_sha256"], "corpus_canonical_sha256": expected_corpus["canonical_sha256"], "stability_case_ids": selected}


def validate_forbidden_boundaries() -> dict[str, Any]:
    payloads = [load_v6_candidate(), *_v6_corpora().values(), _read(MANIFEST_PATH), _read(FORMAL_PLAN_PATH)]
    if any(token in json.dumps(payloads, ensure_ascii=False).casefold() for token in FORBIDDEN_SOURCE_TOKENS):
        raise ValueError("v6_candidate_forbidden_source_boundary_reference")
    return {"valid": True, "forbidden_reference_count": 0}


def validate_all() -> dict[str, Any]:
    payload = load_v6_candidate(); case_result = validate_v6_candidate_case_set(payload)
    plan = validate_v6_formal_plan()
    return {"case_set": case_result, "corpora": validate_v6_corpora(), "semantic_review": validate_v6_semantic_review(payload), "manifest": validate_v6_candidate_manifest(case_result), "formal_plan": plan, "forbidden_boundaries": validate_forbidden_boundaries(), "formal_run_executed": plan["formal_run_executed"], "provider_calls": plan["provider_calls"], "real_provider_calls": plan["provider_calls"], "status": "candidate_for_controller_review", "lifecycle": plan["lifecycle"]}


if __name__ == "__main__":
    print(json.dumps(validate_all(), ensure_ascii=False, indent=2))
