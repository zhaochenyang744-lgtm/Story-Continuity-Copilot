"""Fail-closed structural, novelty, and boundary validator for V7 candidates."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import CORPUS_PATHS, V3_CORPUS_PATHS, V4_CORPUS_PATHS, V5_CORPUS_PATHS, V6_CORPUS_PATHS, V7_CORPUS_PATHS, corpus_manifest_payload, load_corpus


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v7-candidate.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-candidate-manifest.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v7-corpus-manifest.json"
REVIEW_PATH = ROOT / "evaluation" / "v7-candidate-semantic-review.json"
FORMAL_PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v7-first-formal-plan.json"
V6_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-candidate-manifest.json"
FORMAL_CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v7.json"
FORMAL_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-manifest.json"
FORMAL_REVIEW_PATH = ROOT / "evaluation" / "v7-semantic-review.json"
FREEZE_INTEGRITY_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-freeze-integrity.json"
FORMAL_WORKSPACE = ROOT / "evaluation" / "fixture-workspaces" / "scc-web-demo-eval-v7-first-formal"
PRIOR_CASE_PATHS = tuple(ROOT / "evaluation" / "case_sets" / name for name in ("eval-set-v1.json", "eval-set-v2.json", "eval-set-v3.json", "eval-set-v4.json", "eval-set-v5.json", "eval-set-v5-candidate.json", "eval-set-v6-candidate.json", "eval-set-v6.json"))
PRIOR_CORPUS_PATHS = {**CORPUS_PATHS, **V3_CORPUS_PATHS, **V4_CORPUS_PATHS, **V5_CORPUS_PATHS, **V6_CORPUS_PATHS}
CLASSES = {"conflict", "no_conflict", "insufficient_evidence"}
CATEGORIES = {"attribute", "object_state", "relationship", "character_knowledge", "timeline", "world_rule", "location_action", "event_status"}
TAGS = {"requires_multiple_direct_evidence", "ambiguous_evidence", "conflicting_sources", "insufficient_evidence", "category_mismatch_regression", "supported_control"}
REQUIRED_BOUNDARIES = {frozenset(("relationship", "world_rule")), frozenset(("timeline", "event_status")), frozenset(("location_action", "object_state"))}
FORBIDDEN_TOKENS = ("story-continuity-poc", "heldout", "held-out", "golden", ".env", "poc.sqlite")


def _read(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", value).casefold()


def ngrams(value: str, width: int = 32) -> set[str]:
    compact = normalize(value)
    return {compact[index:index + width] for index in range(max(0, len(compact) - width + 1))}


def load_v7_candidate(path: pathlib.Path = CASE_SET_PATH) -> dict[str, Any]:
    payload = _read(path)
    if (payload.get("schema_version") != "scc-eval-case-set-v7-candidate" or payload.get("status") != "candidate_for_controller_review" or payload.get("evaluation_only") is not True or payload.get("production_seed") is not False or payload.get("protected_asset_source") is not False or payload.get("formal_run_executed") is not False or payload.get("provider_calls") != 0 or not isinstance(payload.get("cases"), list)):
        raise ValueError("v7_candidate_case_set_schema_or_boundary_invalid")
    return payload


def _corpora() -> dict[str, dict[str, Any]]:
    return {key: load_corpus(key, V7_CORPUS_PATHS) for key in V7_CORPUS_PATHS}


def _prior_cases() -> list[dict[str, Any]]:
    return [case for path in PRIOR_CASE_PATHS for case in _read(path)["cases"]]


def _prior_corpora() -> list[dict[str, Any]]:
    return [load_corpus(key, PRIOR_CORPUS_PATHS) for key in PRIOR_CORPUS_PATHS]


def _catalog(corpora: dict[str, dict[str, Any]]) -> dict[str, dict[tuple[int, str], str]]:
    output: dict[str, dict[tuple[int, str], str]] = {}
    for key, corpus in corpora.items():
        entries = {(chapter.get("chapter_number"), chapter.get("source_label")): chapter.get("body") for chapter in corpus.get("chapters", [])}
        if len(entries) != 8 or any(not isinstance(number, int) or not isinstance(label, str) or not label or not isinstance(body, str) or not body for (number, label), body in entries.items()):
            raise ValueError("v7_candidate_evidence_catalog_invalid")
        output[key] = entries
    return output


def validate_v7_corpora(corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    corpora = corpora or _corpora()
    if set(corpora) != set(V7_CORPUS_PATHS) or len(corpora) != 4:
        raise ValueError("v7_candidate_corpus_scope_invalid")
    prior = _prior_corpora()
    prior_keys = {item["corpus_key"] for item in prior}; prior_titles = {item["title"] for item in prior}
    prior_text = "\n".join(chapter["body"] for corpus in prior for chapter in corpus["chapters"])
    prior_ngrams = set().union(*(ngrams(chapter["body"]) for corpus in prior for chapter in corpus["chapters"]))
    seen: set[str] = set()
    for key, corpus in corpora.items():
        if key in prior_keys or corpus.get("title") in prior_titles:
            raise ValueError("v7_candidate_prior_corpus_key_or_title_reuse")
        if (corpus.get("corpus_key") != key or corpus.get("evaluation_only") is not True or corpus.get("production_seed") is not False or corpus.get("protected_asset_source") is not False or corpus.get("generation") != {"method": "deterministic_original", "generator_version": "v7-candidate-1", "source_inputs": []}):
            raise ValueError("v7_candidate_corpus_boundary_or_generation_invalid")
        lineage = corpus.get("lineage", {})
        names = [lineage.get("work_title"), *lineage.get("characters", []), *lineage.get("locations", []), lineage.get("core_design")]
        if lineage.get("work_title") != corpus.get("title") or not all(isinstance(item, str) and item.strip() for item in names) or any(item in seen or normalize(item) in normalize(prior_text) for item in names):
            raise ValueError("v7_candidate_prior_or_cross_corpus_lineage_reuse")
        seen.update(names)
        if not isinstance(corpus.get("memory"), list) or len(corpus["memory"]) < 4 or not isinstance(corpus.get("chapters"), list) or len(corpus["chapters"]) != 8:
            raise ValueError("v7_candidate_corpus_content_count_invalid")
        for chapter in corpus["chapters"]:
            if ngrams(chapter["body"]) & prior_ngrams:
                raise ValueError("v7_candidate_prior_evidence_text_reuse")
    _catalog(corpora)
    return {"valid": True, "corpus_count": 4, "chapter_counts": {key: 8 for key in corpora}}


def validate_v7_candidate_case_set(payload: dict[str, Any] | None = None, corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = payload or load_v7_candidate(); corpora = corpora or _corpora(); validate_v7_corpora(corpora); catalog = _catalog(corpora)
    cases = payload.get("cases")
    required = {"case_id", "corpus_key", "seed_key", "target_draft", "target_claim_ordinal", "expected_class", "expected_category", "expected_severity", "expected_evidence", "source_lineage", "requires_multiple_direct_evidence", "each_expected_evidence_individually_insufficient", "challenge_tags", "category_boundary_pair", "retrieval_difficulty", "core_fact_key", "claim_shape", "decision_signature", "proper_nouns", "evidence_completeness_review", "rubric"}
    if not isinstance(cases, list) or len(cases) != 24 or any(not required <= set(case) for case in cases):
        raise ValueError("v7_candidate_case_count_or_fields_invalid")
    for key in ("case_id", "core_fact_key", "claim_shape", "decision_signature"):
        if len({case[key] for case in cases}) != 24:
            raise ValueError("v7_candidate_duplicate_case_or_semantic_identifier")
    prior = _prior_cases(); prior_ids = {case.get("case_id") for case in prior}; prior_values = {key: {case.get(key) for case in prior} for key in ("core_fact_key", "claim_shape", "decision_signature")}
    prior_text = "\n".join([case.get("target_draft", "") for case in prior] + [chapter["body"] for corpus in _prior_corpora() for chapter in corpus["chapters"]])
    prior_target_ngrams = set().union(*(ngrams(case.get("target_draft", ""), 20) for case in prior))
    class_counts: Counter[str] = Counter(); corpus_counts: Counter[str] = Counter(); per_corpus: dict[str, Counter[str]] = defaultdict(Counter); category_counts: Counter[str] = Counter(); tag_counts: Counter[str] = Counter(); boundary_pairs: set[frozenset[str]] = set()
    for case in cases:
        if case["case_id"] in prior_ids or any(case[key] in prior_values[key] for key in prior_values) or ngrams(case["target_draft"], 20) & prior_target_ngrams:
            raise ValueError("v7_candidate_prior_identifier_or_decision_reuse")
        if (case["corpus_key"] not in V7_CORPUS_PATHS or case["seed_key"] != case["corpus_key"] or case["target_claim_ordinal"] != 1 or case["expected_class"] not in CLASSES or not isinstance(case["proper_nouns"], list) or not case["proper_nouns"] or any(normalize(noun) in normalize(prior_text) for noun in case["proper_nouns"])):
            raise ValueError("v7_candidate_project_or_proper_noun_invalid")
        class_counts[case["expected_class"]] += 1; corpus_counts[case["corpus_key"]] += 1; per_corpus[case["corpus_key"]][case["expected_class"]] += 1
        tags = case["challenge_tags"]
        if not isinstance(tags, list) or len(tags) != len(set(tags)) or not set(tags) <= TAGS:
            raise ValueError("v7_candidate_challenge_tags_invalid")
        tag_counts.update(tags)
        evidence = case["expected_evidence"]; lineage = case["source_lineage"]
        if not isinstance(evidence, list) or not evidence or not isinstance(lineage, list) or len(evidence) != len(lineage):
            raise ValueError("v7_candidate_evidence_or_lineage_schema_invalid")
        expected_lineage = []
        for item in evidence:
            semantic = (item.get("chapter_number"), item.get("source_label"))
            if catalog[case["corpus_key"]].get(semantic) is None or item.get("body_sha256") != _sha(catalog[case["corpus_key"]][semantic]):
                raise ValueError("v7_candidate_expected_evidence_unresolvable")
            expected_lineage.append({"corpus_key": case["corpus_key"], **item})
        if lineage != expected_lineage:
            raise ValueError("v7_candidate_cross_corpus_or_missing_source_lineage")
        rubric = case["rubric"]
        if not isinstance(rubric, dict) or rubric.get("minimum_direct_evidence") != (len(evidence) if case["expected_class"] == "conflict" else 0) or rubric.get("requires_full_expected_evidence") is not (case["expected_class"] == "conflict"):
            raise ValueError("v7_candidate_rubric_evidence_contract_invalid")
        if case["expected_class"] == "conflict":
            if case["expected_category"] not in CATEGORIES or not case["expected_severity"] or case["requires_multiple_direct_evidence"] is not True or case["each_expected_evidence_individually_insufficient"] is not True or len(evidence) < 2 or not {"requires_multiple_direct_evidence", "conflicting_sources"} <= set(tags):
                raise ValueError("v7_candidate_conflict_category_or_multiple_evidence_invalid")
            completeness = case["evidence_completeness_review"]
            if not isinstance(completeness, (list, tuple)) or len(completeness) != 3 or any(not isinstance(item, str) or not item.strip() for item in completeness):
                raise ValueError("v7_candidate_joint_evidence_declaration_invalid")
            category_counts[case["expected_category"]] += 1
            pair = case["category_boundary_pair"]
            if pair is not None:
                if not isinstance(pair, list) or len(pair) != 2 or case["expected_category"] not in pair:
                    raise ValueError("v7_candidate_category_boundary_pair_invalid")
                boundary_pairs.add(frozenset(pair))
        elif case["expected_category"] is not None or case["requires_multiple_direct_evidence"] is not False or case["each_expected_evidence_individually_insufficient"] is not False or case["evidence_completeness_review"] is not None or case["category_boundary_pair"] is not None:
            raise ValueError("v7_candidate_non_conflict_category_or_evidence_invalid")
        elif case["expected_class"] == "no_conflict" and (case["expected_severity"] is not None or "supported_control" not in tags):
            raise ValueError("v7_candidate_no_conflict_expectation_invalid")
        elif case["expected_class"] == "insufficient_evidence" and (case["expected_severity"] is None or "insufficient_evidence" not in tags):
            raise ValueError("v7_candidate_insufficient_expectation_invalid")
    if class_counts != Counter({item: 8 for item in CLASSES}) or corpus_counts != Counter({key: 6 for key in V7_CORPUS_PATHS}) or any(per_corpus[key] != Counter({item: 2 for item in CLASSES}) for key in V7_CORPUS_PATHS):
        raise ValueError("v7_candidate_class_or_corpus_quota_invalid")
    if category_counts != Counter({category: 1 for category in CATEGORIES}) or tag_counts["requires_multiple_direct_evidence"] != 8 or tag_counts["conflicting_sources"] < 8 or tag_counts["insufficient_evidence"] != 8 or tag_counts["ambiguous_evidence"] < 8 or tag_counts["category_mismatch_regression"] < 3 or not REQUIRED_BOUNDARIES <= boundary_pairs:
        raise ValueError("v7_candidate_challenge_coverage_or_boundary_invalid")
    return {"valid": True, "case_count": 24, "class_counts": dict(class_counts), "corpus_counts": dict(corpus_counts), "conflict_categories": sorted(category_counts), "challenge_counts": dict(tag_counts), "category_boundary_pairs": sorted(sorted(pair) for pair in boundary_pairs), "canonical_sha256": canonical_sha256(payload)}


def validate_v7_semantic_review(payload: dict[str, Any] | None = None, review: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or load_v7_candidate(); review = review or _read(REVIEW_PATH); entries = review.get("entries", [])
    if (review.get("schema_version") != "scc-eval-v7-semantic-review-v1" or review.get("review_scope") != "implementation_manual_semantic_review" or review.get("status") != "candidate_for_controller_review" or review.get("formal_run_executed") is not False or review.get("provider_calls") != 0 or len(entries) != 24 or {entry.get("case_id") for entry in entries} != {case["case_id"] for case in payload["cases"]}):
        raise ValueError("v7_semantic_review_schema_or_coverage_invalid")
    required = {"case_id", "corpus_key", "decision_point", "prior_archetype_reference", "why_independent", "same_decision_point", "review_status", "each_expected_evidence_individually_insufficient", "evidence_a_alone_insufficient_reason", "evidence_b_alone_insufficient_reason", "joint_inference"}
    if any(not required <= set(entry) or entry.get("same_decision_point") is not False or entry.get("review_status") != "completed_manual_semantic_review" or not all(isinstance(entry.get(key), str) and entry[key].strip() for key in ("decision_point", "prior_archetype_reference", "why_independent")) for entry in entries):
        raise ValueError("v7_semantic_review_completion_invalid")
    by_case = {case["case_id"]: case for case in payload["cases"]}
    for entry in entries:
        conflict = by_case[entry["case_id"]]["expected_class"] == "conflict"
        fields = ("evidence_a_alone_insufficient_reason", "evidence_b_alone_insufficient_reason", "joint_inference")
        if conflict:
            if entry.get("each_expected_evidence_individually_insufficient") is not True or any(not isinstance(entry.get(field), str) or not entry[field].strip() for field in fields):
                raise ValueError("v7_semantic_review_joint_evidence_declaration_invalid")
        elif entry.get("each_expected_evidence_individually_insufficient") is not False or any(entry.get(field) is not None for field in fields):
            raise ValueError("v7_semantic_review_non_conflict_joint_evidence_invalid")
    return {"valid": True, "entry_count": 24, "manual_review_completed": True, "joint_evidence_declarations": 8, "controller_review_required": True}


def validate_v7_formal_plan(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan or _read(FORMAL_PLAN_PATH)
    outputs = {key: f"evaluation/results/eval-v7-first-formal-{suffix}" for key, suffix in {"checkpoint": "checkpoint.json", "results": "results.json", "report": "report.md", "bad_cases": "bad-cases.json", "stability": "stability.json", "run_manifest": "run-manifest.json", "api_scan": "api-corpus-scan.json"}.items()} | {"post_run_integrity": "evaluation/results/v7-first-formal-post-run-integrity.json"}
    if (plan.get("schema_version") != "scc-eval-v7-first-formal-plan-v1" or not isinstance(plan.get("real_provider_authorization_received"), bool) or plan.get("planned_output_paths") != outputs):
        raise ValueError("v7_formal_plan_false_run_or_output_invalid")
    if plan.get("formal_run_executed") is True:
        if (plan.get("status") != "gate_failed" or plan.get("provider_calls") != 30
                or plan.get("real_provider_authorization_received") is not True
                or plan.get("controller_candidate_gate_passed") is not True
                or plan.get("formal_inputs_frozen") is not True):
            raise ValueError("v7_formal_plan_post_run_state_invalid")
        from evaluation.validate_v7_first_formal_results import validate as validate_post_run
        validate_post_run(check_plan=False)
        return {"valid": True, "formal_run_executed": True, "provider_calls": 30, "formal_inputs_frozen": True, "real_provider_authorization_received": True, "planned_outputs": 8, "status": plan["status"], "lifecycle": "post_run"}
    if plan.get("formal_run_executed") is not False or plan.get("provider_calls") != 0:
        raise ValueError("v7_formal_plan_false_run_or_output_invalid")
    if plan.get("planned_input_paths") != {"case_set": "evaluation/case_sets/eval-set-v7.json", "manifest": "evaluation/manifests/eval-set-v7-manifest.json", "corpus_manifest": "evaluation/fixtures/eval-v7-corpus-manifest.json"} or FORMAL_WORKSPACE.exists() or any((ROOT / value).exists() for value in outputs.values()):
        raise ValueError("v7_formal_plan_input_or_output_boundary_invalid")
    stability = plan.get("stability_protocol", {})
    protocol = plan.get("bad_case_protocol", {})
    if stability.get("independent_runs_per_case") != 3 or stability.get("additional_calls_after_formal") != 6 or stability.get("execution_status") != "not_run" or protocol.get("category_expected_and_predicted_retained") is not True or protocol.get("raw_provider_body_retained") is not False or protocol.get("chain_of_thought_retained") is not False:
        raise ValueError("v7_formal_plan_protocol_invalid")
    formal_paths = (FORMAL_CASE_PATH, FORMAL_MANIFEST_PATH, FORMAL_REVIEW_PATH, FREEZE_INTEGRITY_PATH)
    formal_present = [path.exists() for path in formal_paths]
    if any(formal_present) and not all(formal_present):
        raise ValueError("v7_formal_plan_partial_freeze_invalid")
    if not any(formal_present):
        if plan.get("status") != "not_run" or plan.get("controller_candidate_gate_passed") is not False or plan.get("formal_inputs_frozen") is not False or plan.get("real_provider_authorization_received") is not False:
            raise ValueError("v7_formal_plan_pre_freeze_state_invalid")
        return {"valid": True, "formal_run_executed": False, "provider_calls": 0, "formal_inputs_frozen": False, "real_provider_authorization_received": False, "planned_outputs": 8, "status": "not_run", "lifecycle": "pre_run"}
    expected_status = "approved_for_formal_run" if plan["real_provider_authorization_received"] else "awaiting_real_provider_authorization"
    if (plan.get("status") != expected_status or plan.get("controller_candidate_gate_passed") is not True or plan.get("formal_inputs_frozen") is not True):
        raise ValueError("v7_formal_plan_frozen_authorization_state_invalid")
    return {"valid": True, "formal_run_executed": False, "provider_calls": 0, "formal_inputs_frozen": True, "real_provider_authorization_received": plan["real_provider_authorization_received"], "planned_outputs": 8, "status": expected_status, "lifecycle": "pre_run"}


def validate_v7_candidate_manifest(case_result: dict[str, Any] | None = None) -> dict[str, Any]:
    case_result = case_result or validate_v7_candidate_case_set(); manifest = _read(MANIFEST_PATH); v6 = _read(V6_MANIFEST_PATH)
    expected_case = {"path": "evaluation/case_sets/eval-set-v7-candidate.json", "canonical_sha256": case_result["canonical_sha256"], "case_count": 24, "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8}, "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2}}
    expected_corpus = {"path": "evaluation/fixtures/eval-v7-corpus-manifest.json", "canonical_sha256": corpus_manifest_payload(V7_CORPUS_PATHS)["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False}
    boundaries = manifest.get("boundaries", {})
    if (manifest.get("manifest_version") != "scc-eval-manifest-v7-candidate" or manifest.get("status") != "candidate_for_controller_review" or manifest.get("case_set") != expected_case or manifest.get("fixture_corpus") != expected_corpus or _read(CORPUS_MANIFEST_PATH) != corpus_manifest_payload(V7_CORPUS_PATHS) or manifest.get("scoring") != v6.get("scoring") or manifest.get("required_thresholds") != v6.get("required_thresholds") or manifest.get("formal_run_plan") != {"path": "evaluation/manifests/eval-v7-first-formal-plan.json", "status": "not_run"} or any(boundaries.get(key) != value for key, value in {"evaluation_only": True, "production_seed": False, "protected_asset_source": False, "formal_run_executed": False, "provider_calls": 0, "real_provider_authorization": False, "controller_candidate_gate_passed": False}.items())):
        raise ValueError("v7_candidate_manifest_hash_threshold_or_boundary_invalid")
    return {"valid": True, "canonical_sha256": case_result["canonical_sha256"], "corpus_canonical_sha256": expected_corpus["canonical_sha256"]}


def validate_forbidden_boundaries() -> dict[str, Any]:
    payloads = [load_v7_candidate(), *_corpora().values(), _read(MANIFEST_PATH), _read(FORMAL_PLAN_PATH), _read(REVIEW_PATH)]
    if any(token in json.dumps(payloads, ensure_ascii=False).casefold() for token in FORBIDDEN_TOKENS):
        raise ValueError("v7_candidate_forbidden_source_boundary_reference")
    return {"valid": True, "forbidden_reference_count": 0}


def validate_all(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = load_v7_candidate(); cases = validate_v7_candidate_case_set(payload)
    formal_plan = validate_v7_formal_plan(plan)
    return {"case_set": cases, "corpora": validate_v7_corpora(), "semantic_review": validate_v7_semantic_review(payload), "manifest": validate_v7_candidate_manifest(cases), "formal_plan": formal_plan, "forbidden_boundaries": validate_forbidden_boundaries(), "status": "formal_run_completed" if formal_plan["formal_run_executed"] else ("formal_inputs_frozen" if formal_plan["formal_inputs_frozen"] else "candidate_for_controller_review"), "formal_run_executed": formal_plan["formal_run_executed"], "provider_calls": formal_plan["provider_calls"], "real_provider_calls": formal_plan["provider_calls"]}


if __name__ == "__main__":
    print(json.dumps(validate_all(), ensure_ascii=False, indent=2))
