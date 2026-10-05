"""Fail-closed structural, lineage, novelty, and no-run validation for V8 candidates."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V5_CORPUS_PATHS, V6_CORPUS_PATHS, V7_CORPUS_PATHS, V8_CORPUS_PATHS, corpus_manifest_payload, load_corpus

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "evaluation/case_sets/eval-set-v8-candidate.json"
MANIFEST_PATH = ROOT / "evaluation/manifests/eval-set-v8-candidate-manifest.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation/fixtures/eval-v8-corpus-manifest.json"
REVIEW_PATH = ROOT / "evaluation/v8-candidate-semantic-review.json"
PLAN_PATH = ROOT / "evaluation/manifests/eval-v8-first-formal-plan.json"
FORMAL_PATHS = (ROOT / "evaluation/case_sets/eval-set-v8.json", ROOT / "evaluation/manifests/eval-set-v8-manifest.json", ROOT / "evaluation/v8-semantic-review.json", ROOT / "evaluation/manifests/eval-set-v8-freeze-integrity.json")
WORKSPACE = ROOT / "evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal"
RESULTS = ROOT / "evaluation/results"
CLASSES = {"conflict", "no_conflict", "insufficient_evidence"}
CATEGORIES = {"attribute", "object_state", "relationship", "character_knowledge", "world_rule", "timeline", "event_status", "location_action"}
BOUNDARIES = {frozenset(("relationship", "world_rule")), frozenset(("timeline", "event_status")), frozenset(("location_action", "object_state"))}
FORBIDDEN = ("story-continuity-poc", "heldout", "held-out", "golden", ".env", "poc.sqlite")
SENSITIVE_KEYS = {"prompt", "prompt_body", "raw_provider_body", "provider_body", "reasoning_content", "chain_of_thought", "authorization", "api_key", "api_key_value"}
PRIOR_CASES = tuple(ROOT / "evaluation/case_sets" / name for name in ("eval-set-v5-candidate.json", "eval-set-v5.json", "eval-set-v6-candidate.json", "eval-set-v6.json", "eval-set-v7-candidate.json", "eval-set-v7.json"))
PRIOR_CORPORA = {**V5_CORPUS_PATHS, **V6_CORPUS_PATHS, **V7_CORPUS_PATHS}


def _read(path: pathlib.Path) -> dict[str, Any]: return json.loads(path.read_text(encoding="utf-8"))
def _sha(text: str) -> str: return hashlib.sha256(text.encode()).hexdigest()
def _normal(value: str) -> str: return re.sub(r"[^\w]", "", value).casefold()
def _ngrams(value: str, width: int = 24) -> set[str]:
    value = _normal(value); return {value[index:index + width] for index in range(max(0, len(value) - width + 1))}


def load_v8_candidate() -> dict[str, Any]:
    payload = _read(CASE_PATH)
    if (payload.get("schema_version") != "scc-eval-case-set-v8-candidate" or payload.get("status") != "candidate_for_controller_review" or payload.get("evaluation_only") is not True or payload.get("production_seed") is not False or payload.get("protected_asset_source") is not False or payload.get("formal_run_executed") is not False or payload.get("provider_calls") != 0):
        raise ValueError("v8_candidate_case_set_schema_or_boundary_invalid")
    return payload


def _corpora() -> dict[str, dict[str, Any]]: return {key: load_corpus(key, V8_CORPUS_PATHS) for key in V8_CORPUS_PATHS}


def _catalog(corpora: dict[str, dict[str, Any]]) -> dict[str, dict[tuple[int, str], str]]:
    output = {}
    for key, corpus in corpora.items():
        rows = {(chapter.get("chapter_number"), chapter.get("source_label")): chapter.get("body") for chapter in corpus.get("chapters", [])}
        if len(rows) != 8 or any(not isinstance(number, int) or not isinstance(label, str) or not label or not isinstance(body, str) or not body for (number, label), body in rows.items()): raise ValueError("v8_candidate_evidence_catalog_invalid")
        output[key] = rows
    return output


def _prior_cases() -> list[dict[str, Any]]: return [case for path in PRIOR_CASES for case in _read(path)["cases"]]
def _prior_corpora() -> list[dict[str, Any]]: return [load_corpus(key, PRIOR_CORPORA) for key in PRIOR_CORPORA]


def validate_v8_corpora(corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    corpora = corpora or _corpora()
    if set(corpora) != set(V8_CORPUS_PATHS) or len(corpora) != 4: raise ValueError("v8_candidate_corpus_scope_invalid")
    prior = _prior_corpora(); prior_text = "\n".join(chapter["body"] for corpus in prior for chapter in corpus["chapters"]); prior_ngram = set().union(*(_ngrams(chapter["body"], 32) for corpus in prior for chapter in corpus["chapters"]))
    prior_keys = {corpus["corpus_key"] for corpus in prior}; seen: set[str] = set()
    for key, corpus in corpora.items():
        lineage = corpus.get("lineage", {}); terms = [lineage.get("work_title"), *lineage.get("characters", []), *lineage.get("locations", []), lineage.get("core_design")]
        if (key in prior_keys or corpus.get("corpus_key") != key or corpus.get("evaluation_only") is not True or corpus.get("production_seed") is not False or corpus.get("protected_asset_source") is not False or corpus.get("generation") != {"method": "deterministic_original", "generator_version": "v8-candidate-1", "source_inputs": []} or corpus.get("title") != lineage.get("work_title") or len(corpus.get("chapters", [])) != 8 or len(corpus.get("memory", [])) != 4 or not all(isinstance(term, str) and term.strip() for term in terms) or any(_normal(term) in _normal(prior_text) or term in seen for term in terms)):
            raise ValueError("v8_candidate_corpus_novelty_or_boundary_invalid")
        seen.update(terms)
        if any(_ngrams(chapter["body"], 32) & prior_ngram for chapter in corpus["chapters"]): raise ValueError("v8_candidate_prior_evidence_text_reuse")
    _catalog(corpora); return {"valid": True, "corpus_count": 4, "chapter_counts": {key: 8 for key in corpora}}


def validate_v8_candidate_case_set(payload: dict[str, Any] | None = None, corpora: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = payload or load_v8_candidate(); corpora = corpora or _corpora(); validate_v8_corpora(corpora); catalog = _catalog(corpora); cases = payload.get("cases")
    required = {"case_id", "corpus_key", "seed_key", "target_draft", "target_claim_ordinal", "expected_class", "expected_category", "expected_severity", "expected_evidence", "source_lineage", "requires_multiple_direct_evidence", "each_expected_evidence_individually_insufficient", "challenge_tags", "category_boundary_pair", "retrieval_difficulty", "core_fact_key", "claim_shape", "decision_signature", "proper_nouns", "evidence_completeness_review", "rubric"}
    if not isinstance(cases, list) or len(cases) != 24 or any(not required <= set(case) for case in cases): raise ValueError("v8_candidate_case_count_or_fields_invalid")
    if any(len({case[field] for case in cases}) != 24 for field in ("case_id", "core_fact_key", "claim_shape", "decision_signature")): raise ValueError("v8_candidate_duplicate_case_or_semantic_identifier")
    prior = _prior_cases(); prior_values = {field: {case.get(field) for case in prior} for field in ("core_fact_key", "claim_shape", "decision_signature")}; prior_ngrams = set().union(*(_ngrams(case.get("target_draft", ""), 20) for case in prior))
    classes, corpus_counts, categories, tags, pairs, per_corpus = Counter(), Counter(), Counter(), Counter(), set(), defaultdict(Counter)
    for case in cases:
        if (case["corpus_key"] not in V8_CORPUS_PATHS or case["seed_key"] != case["corpus_key"] or case["target_claim_ordinal"] != 1 or case["expected_class"] not in CLASSES or _ngrams(case["target_draft"], 20) & prior_ngrams or any(case[field] in prior_values[field] for field in prior_values)):
            raise ValueError("v8_candidate_prior_identifier_or_case_boundary_invalid")
        evidence, lineage = case["expected_evidence"], case["source_lineage"]
        if not isinstance(evidence, list) or not evidence or not isinstance(lineage, list) or len(evidence) != len(lineage): raise ValueError("v8_candidate_evidence_or_lineage_schema_invalid")
        expected_lineage = []
        for item in evidence:
            semantic = (item.get("chapter_number"), item.get("source_label")); body = catalog[case["corpus_key"]].get(semantic)
            if body is None or item.get("body_sha256") != _sha(body): raise ValueError("v8_candidate_expected_evidence_unresolvable")
            expected_lineage.append({"corpus_key": case["corpus_key"], **item})
        if lineage != expected_lineage: raise ValueError("v8_candidate_cross_corpus_lineage_invalid")
        rubric = case["rubric"]
        if rubric != {"minimum_direct_evidence": len(evidence) if case["expected_class"] == "conflict" else 0, "requires_full_expected_evidence": case["expected_class"] == "conflict"}: raise ValueError("v8_candidate_rubric_invalid")
        classes[case["expected_class"]] += 1; corpus_counts[case["corpus_key"]] += 1; per_corpus[case["corpus_key"]][case["expected_class"]] += 1; tags.update(case["challenge_tags"])
        if case["expected_class"] == "conflict":
            review = case["evidence_completeness_review"]
            if (case["expected_category"] not in CATEGORIES or not case["expected_severity"] or len(evidence) < 2 or case["requires_multiple_direct_evidence"] is not True or case["each_expected_evidence_individually_insufficient"] is not True or not {"requires_multiple_direct_evidence", "conflicting_sources"} <= set(case["challenge_tags"]) or not isinstance(review, list) or len(review) != 3 or any(not isinstance(item, str) or not item.strip() for item in review)):
                raise ValueError("v8_candidate_conflict_joint_evidence_invalid")
            categories[case["expected_category"]] += 1
            if case["category_boundary_pair"] is not None: pairs.add(frozenset(case["category_boundary_pair"]))
        elif (case["expected_category"] is not None or case["requires_multiple_direct_evidence"] is not False or case["each_expected_evidence_individually_insufficient"] is not False or case["evidence_completeness_review"] is not None or case["category_boundary_pair"] is not None): raise ValueError("v8_candidate_non_conflict_contract_invalid")
        elif case["expected_class"] == "no_conflict" and (case["expected_severity"] is not None or "supported_control" not in case["challenge_tags"] or case["retrieval_difficulty"] != "direct_with_same_entity_distractor"): raise ValueError("v8_candidate_control_contract_invalid")
        elif case["expected_class"] == "insufficient_evidence" and (not case["expected_severity"] or "insufficient_evidence" not in case["challenge_tags"]): raise ValueError("v8_candidate_insufficient_contract_invalid")
    designated = {case["case_id"] for case in cases if "category_mismatch_regression" in case["challenge_tags"]}
    expected_designated = {
        "v8-dusk-viaduct-conflict-relationship",
        "v8-flint-garden-conflict-location_action",
        "v8-opal-nursery-conflict-timeline",
    }
    if classes != Counter({item: 8 for item in CLASSES}) or corpus_counts != Counter({key: 6 for key in V8_CORPUS_PATHS}) or any(per_corpus[key] != Counter({item: 2 for item in CLASSES}) for key in V8_CORPUS_PATHS) or categories != Counter({item: 1 for item in CATEGORIES}) or tags["requires_multiple_direct_evidence"] != 8 or tags["conflicting_sources"] != 8 or tags["supported_control"] != 8 or tags["insufficient_evidence"] != 8 or tags["category_mismatch_regression"] != 3 or designated != expected_designated or not BOUNDARIES <= pairs:
        raise ValueError("v8_candidate_quota_or_boundary_coverage_invalid")
    return {"valid": True, "case_count": 24, "class_counts": dict(classes), "corpus_counts": dict(corpus_counts), "conflict_categories": sorted(categories), "challenge_counts": dict(tags), "designated_category_mismatch_case_ids": sorted(designated), "category_boundary_pairs": sorted(sorted(pair) for pair in pairs), "canonical_sha256": canonical_sha256(payload)}


def validate_v8_semantic_review(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or load_v8_candidate(); review = _read(REVIEW_PATH); entries = review.get("entries", []); by_case = {case["case_id"]: case for case in payload["cases"]}
    if (review.get("schema_version") != "scc-eval-v8-semantic-review-v1" or review.get("status") != "candidate_for_controller_review" or review.get("formal_run_executed") is not False or review.get("provider_calls") != 0 or len(entries) != 24 or {entry.get("case_id") for entry in entries} != set(by_case)): raise ValueError("v8_semantic_review_schema_or_coverage_invalid")
    fields = ("evidence_a_alone_insufficient_reason", "evidence_b_alone_insufficient_reason", "joint_inference")
    for entry in entries:
        conflict = by_case[entry["case_id"]]["expected_class"] == "conflict"
        if (entry.get("review_status") != "completed_manual_semantic_review" or entry.get("same_decision_point") is not False or not all(isinstance(entry.get(key), str) and entry[key].strip() for key in ("decision_point", "prior_archetype_reference", "why_independent")) or (conflict and (entry.get("each_expected_evidence_individually_insufficient") is not True or any(not isinstance(entry.get(field), str) or not entry[field].strip() for field in fields))) or (not conflict and (entry.get("each_expected_evidence_individually_insufficient") is not False or any(entry.get(field) is not None for field in fields)))): raise ValueError("v8_semantic_review_joint_evidence_invalid")
    return {"valid": True, "entry_count": 24, "manual_review_completed": True, "joint_evidence_declarations": 8}


def validate_v8_plan() -> dict[str, Any]:
    """Validate the mutable run-state while retaining the immutable candidate checks."""
    plan = _read(PLAN_PATH)
    expected_inputs = {"case_set": "evaluation/case_sets/eval-set-v8.json", "manifest": "evaluation/manifests/eval-set-v8-manifest.json", "corpus_manifest": "evaluation/fixtures/eval-v8-corpus-manifest.json"}
    expected_outputs = {
        "checkpoint": "evaluation/results/eval-v8-first-formal-checkpoint.json",
        "results": "evaluation/results/eval-v8-first-formal-results.json",
        "report": "evaluation/results/eval-v8-first-formal-report.md",
        "bad_cases": "evaluation/results/eval-v8-first-formal-bad-cases.json",
        "stability": "evaluation/results/eval-v8-first-formal-stability.json",
        "run_manifest": "evaluation/results/eval-v8-first-formal-run-manifest.json",
        "api_scan": "evaluation/results/eval-v8-first-formal-api-corpus-scan.json",
        "post_run_integrity": "evaluation/results/v8-first-formal-post-run-integrity.json",
    }
    stability = plan.get("stability_protocol", {})
    protocol = plan.get("bad_case_protocol", {})
    if (plan.get("schema_version") != "scc-eval-v8-first-formal-plan-v1" or plan.get("runtime_contract") != {"model_label": "deepseek-v4-pro", "prompt_version": "continuity-review-v6"} or plan.get("planned_input_paths") != expected_inputs or plan.get("planned_output_paths") != expected_outputs or plan.get("provider_execution") != {"formal_cases": 24, "stability_representative_cases": 3, "additional_stability_calls": 6, "planned_provider_calls": 30} or stability.get("independent_runs_per_case") != 3 or stability.get("additional_calls_after_formal") != 6 or stability.get("terminal_failure_quality_stability") is not False or protocol.get("category_expected_and_predicted_retained") is not True or protocol.get("raw_provider_body_retained") is not False or protocol.get("chain_of_thought_retained") is not False):
        raise ValueError("v8_candidate_plan_or_formal_output_boundary_invalid")
    formal_present = all(path.exists() for path in FORMAL_PATHS)
    candidate_pre_freeze = (plan.get("formal_run_executed") is False and plan.get("provider_calls") == 0 and plan.get("status") == "not_run" and plan.get("controller_candidate_gate_passed") is False and plan.get("formal_inputs_frozen") is False and plan.get("real_provider_authorization_received") is False and stability.get("execution_status") == "not_run" and not any(path.exists() for path in FORMAL_PATHS) and not WORKSPACE.exists() and not any(RESULTS.glob("eval-v8-first-formal-*") ) and not (RESULTS / "v8-first-formal-post-run-integrity.json").exists())
    frozen_pre_run = (plan.get("formal_run_executed") is False and plan.get("provider_calls") == 0 and plan.get("status") in {"awaiting_real_provider_authorization", "approved_for_formal_run"} and plan.get("controller_candidate_gate_passed") is True and plan.get("formal_inputs_frozen") is True and isinstance(plan.get("real_provider_authorization_received"), bool) and stability.get("execution_status") == "not_run" and formal_present and not WORKSPACE.exists() and not any(RESULTS.glob("eval-v8-first-formal-*") ) and not (RESULTS / "v8-first-formal-post-run-integrity.json").exists())
    post_run = (plan.get("formal_run_executed") is True and plan.get("provider_calls") == 30 and plan.get("status") == "gate_failed" and plan.get("controller_candidate_gate_passed") is True and plan.get("formal_inputs_frozen") is True and plan.get("real_provider_authorization_received") is True and stability.get("execution_status") == "gate_failed" and formal_present)
    if candidate_pre_freeze:
        return {"valid": True, "lifecycle": "before_freeze", "status": "candidate_for_controller_review", "formal_run_executed": False, "provider_calls": 0, "formal_input_count": 0, "formal_result_count": 0, "formal_workspace_count": 0}
    if frozen_pre_run:
        return {"valid": True, "lifecycle": "pre_run", "status": "formal_inputs_frozen", "formal_run_executed": False, "provider_calls": 0, "formal_input_count": 8, "formal_result_count": 0, "formal_workspace_count": 0}
    if not post_run:
        raise ValueError("v8_candidate_plan_or_formal_output_boundary_invalid")
    # The candidate remains immutable after execution.  Delegate retained
    # artifact uniqueness, freeze hashes, and run accounting to the formal
    # lifecycle validator rather than accepting a completed plan on its word.
    from evaluation.validate_eval_set_v8 import validate_formal_freeze
    formal = validate_formal_freeze(plan_payload=plan)
    if (formal.get("lifecycle"), formal.get("formal_result_status"), formal.get("formal_result_count"), formal.get("formal_workspace_count"), formal.get("provider_calls")) != ("post_run", "gate_failed", 8, 24, 30):
        raise ValueError("v8_candidate_plan_post_run_result_mismatch")
    return {"valid": True, "lifecycle": "post_run", "status": "gate_failed", "formal_run_executed": True, "provider_calls": 30, "formal_input_count": 8, "formal_result_count": 8, "formal_workspace_count": 24, "formal_result_status": "gate_failed"}


def validate_v8_manifest(cases: dict[str, Any] | None = None) -> dict[str, Any]:
    cases = cases or validate_v8_candidate_case_set(); manifest = _read(MANIFEST_PATH); v7 = _read(ROOT / "evaluation/manifests/eval-set-v7-manifest.json")
    expected = {"path": "evaluation/case_sets/eval-set-v8-candidate.json", "canonical_sha256": cases["canonical_sha256"], "case_count": 24, "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8}, "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2}}
    corpus = corpus_manifest_payload(V8_CORPUS_PATHS)
    expected_stability = {"representative_case_ids": ["v8-dusk-viaduct-conflict-relationship", "v8-sable-tideglass-control-5", "v8-opal-nursery-insufficient-7"], "independent_runs_per_case": 3, "first_formal_runs_included_per_case": 1, "additional_calls_after_formal": 6, "execution_status": "not_run", "terminal_failure_quality_stability": False}
    runtime_contract = {"model_label": "deepseek-v4-pro", "prompt_version": "continuity-review-v6"}
    plan_stability = _read(PLAN_PATH).get("stability_protocol")
    allowed_plan_stability = {json.dumps(expected_stability, sort_keys=True), json.dumps({**expected_stability, "execution_status": "gate_failed"}, sort_keys=True)}
    if (manifest.get("manifest_version") != "scc-eval-manifest-v8-candidate" or manifest.get("status") != "candidate_for_controller_review" or manifest.get("case_set") != expected or manifest.get("fixture_corpus") != {"path": "evaluation/fixtures/eval-v8-corpus-manifest.json", "canonical_sha256": corpus["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False} or _read(CORPUS_MANIFEST_PATH) != corpus or manifest.get("runtime_contract") != runtime_contract or _read(PLAN_PATH).get("runtime_contract") != runtime_contract or manifest.get("scoring") != v7["scoring"] or manifest.get("required_thresholds") != v7["required_thresholds"] or manifest.get("stability_protocol") != expected_stability or json.dumps(plan_stability, sort_keys=True) not in allowed_plan_stability): raise ValueError("v8_candidate_manifest_hash_threshold_or_corpus_invalid")
    return {"valid": True, "canonical_sha256": cases["canonical_sha256"], "corpus_canonical_sha256": corpus["canonical_sha256"]}


def validate_forbidden_boundaries() -> dict[str, Any]:
    assets = [load_v8_candidate(), _read(MANIFEST_PATH), _read(REVIEW_PATH), _read(PLAN_PATH), *_corpora().values()]
    payload = json.dumps(assets, ensure_ascii=False).casefold()
    if any(token in payload for token in FORBIDDEN): raise ValueError("v8_candidate_forbidden_sensitive_or_protected_reference")
    def sensitive_nonzero(value: Any, key: str = "") -> bool:
        if key.casefold() in SENSITIVE_KEYS and value not in (None, False, 0, "", [], {}): return True
        if isinstance(value, dict): return any(sensitive_nonzero(child, str(name)) for name, child in value.items())
        if isinstance(value, list): return any(sensitive_nonzero(child, key) for child in value)
        return False
    if any(sensitive_nonzero(asset) for asset in assets): raise ValueError("v8_candidate_forbidden_sensitive_or_protected_reference")
    return {"valid": True, "forbidden_reference_count": 0}


def validate_all() -> dict[str, Any]:
    cases = validate_v8_candidate_case_set(); plan = validate_v8_plan()
    return {"case_set": cases, "corpora": validate_v8_corpora(), "semantic_review": validate_v8_semantic_review(), "manifest": validate_v8_manifest(cases), "formal_plan": plan, "forbidden_boundaries": validate_forbidden_boundaries(), "status": plan["status"], "lifecycle": plan["lifecycle"], "formal_run_executed": plan["formal_run_executed"], "provider_calls": plan["provider_calls"], "real_provider_calls": plan["provider_calls"]}

if __name__ == "__main__": print(json.dumps(validate_all(), ensure_ascii=False, indent=2))
