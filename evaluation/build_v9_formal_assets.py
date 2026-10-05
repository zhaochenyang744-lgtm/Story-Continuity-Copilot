"""Convert the user-authored V9 held-out file into formal evaluation assets.

The conversion is mechanical: corpora, cases and gold come only from
evaluation/eval_set_v9_authoring/cases.json, whose SHA-256 the author recorded
in cases.sha256. Every chapter becomes an author-confirmed Memory record
(permanent rules as static_canon/rule, other records as dynamic_state/status),
because the current contract grounds a timeless-rule conflict only in a cited
static_canon rule. Stability representatives are chosen by a fixed rule, not
by reading case content.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUTHORING = ROOT / "evaluation/eval_set_v9_authoring"
FIXTURES = ROOT / "evaluation/fixtures"
CASE_SET = ROOT / "evaluation/case_sets/eval-set-v9.json"
MANIFEST = ROOT / "evaluation/manifests/eval-set-v9-manifest.json"
PLAN = ROOT / "evaluation/manifests/eval-v9-first-formal-plan.json"
CORPUS_MANIFEST = FIXTURES / "eval-v9-corpus-manifest.json"
RUNTIME_CONTRACT = {"model_label": "deepseek-flash", "review_thinking": "high",
                    "prompt_version": "continuity-review-v20-decisive-fact-category"}
# Unchanged from V5-V8 (evaluation/manifests/eval-set-v8-manifest.json).
REQUIRED_THRESHOLDS = {"macro_f1_min": 0.8, "conflict_recall_min": 0.8, "insufficient_evidence_recall_min": 0.8,
                       "no_conflict_false_positive_rate_max": 0.2, "retrieval_expected_evidence_hit_at_5_min": 0.8,
                       "cited_evidence_precision": 1, "schema_validity": 1, "evidence_resolvability_grounding": 1,
                       "fail_closed_safety_paths": 1, "conflict_category_accuracy_min": 0.75,
                       "designated_category_mismatch_regression_required_correct": 3,
                       "designated_category_mismatch_regression_required_total": 3,
                       "expected_evidence_recall_min": 0.8, "multi_direct_evidence_full_set_recall_min": 0.75}
OUTPUTS = {key: f"evaluation/results/eval-v9-first-formal-{suffix}" for key, suffix in {
    "checkpoint": "checkpoint.json", "results": "results.json", "report": "report.md", "bad_cases": "bad-cases.json",
    "stability": "stability.json", "run_manifest": "run-manifest.json", "api_scan": "api-corpus-scan.json"}.items()}


def canonical(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def authored() -> tuple[dict[str, Any], str]:
    raw = (AUTHORING / "cases.json").read_bytes()
    recorded = (AUTHORING / "cases.sha256").read_text(encoding="utf-8").split()[0].lower()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != recorded:
        raise RuntimeError("authored_cases_hash_mismatch")
    return json.loads(raw.decode("utf-8")), actual


def corpus_path(key: str) -> pathlib.Path:
    return FIXTURES / f"eval-v9-{key.replace('_', '-')}.json"


def make_corpus(corpus: dict[str, Any]) -> dict[str, Any]:
    chapters = [{"chapter_number": index, "title": chapter.get("title") or chapter["label"], "source_label": chapter["label"],
                 "body": chapter["body"]} for index, chapter in enumerate(corpus["chapters"], 1)]
    subject = corpus.get("title") or corpus["key"]
    memory = [{"memory_type": "static_canon" if chapter["is_rule"] else "dynamic_state",
               "subject": subject, "predicate": "rule" if chapter["is_rule"] else "status", "value": chapter["body"],
               "source": {"chapter_number": index, "source_label": chapter["label"]}}
              for index, chapter in enumerate(corpus["chapters"], 1)]
    return {"schema_version": "scc-evaluation-only-corpus-v1", "corpus_key": corpus["key"], "title": subject,
            "evaluation_only": True, "production_seed": False, "protected_asset_source": False,
            "generation": {"method": "user_authored_held_out", "generator_version": "v9-authoring-1", "source_inputs": []},
            "lineage": {"work_title": subject, "language": corpus.get("language"), "characters": [], "locations": [],
                        "core_design": "user-authored held-out corpus"},
            "chapters": chapters, "memory": memory}


def representatives(cases: list[dict[str, Any]]) -> list[str]:
    ordered = sorted(cases, key=lambda case: case["case_id"])
    picks = [next(c for c in ordered if "category_mismatch_regression" in c["challenge_tags"]),
             next(c for c in ordered if c["expected_class"] == "no_conflict"),
             next(c for c in ordered if c["expected_class"] == "insufficient_evidence")]
    return [case["case_id"] for case in picks]


def build() -> dict[str, Any]:
    source, source_sha = authored()
    corpora = {corpus["key"]: make_corpus(corpus) for corpus in source["corpora"]}
    for key, payload in corpora.items():
        corpus_path(key).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    corpus_manifest = {"schema_version": "scc-evaluation-only-corpus-manifest-v1", "evaluation_only": True,
                       "production_seed": False, "protected_asset_source": False,
                       "files": [{"corpus_key": key, "path": f"evaluation/fixtures/{corpus_path(key).name}",
                                  "sha256": hashlib.sha256(corpus_path(key).read_bytes()).hexdigest()} for key in corpora],
                       "canonical_sha256": canonical([{key: value} for key, value in corpora.items()])}
    CORPUS_MANIFEST.write_text(json.dumps(corpus_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases = []
    for item in source["cases"]:
        key = item["corpus"]
        chapters = {chapter["source_label"]: chapter for chapter in corpora[key]["chapters"]}
        evidence = [{"chapter_number": chapters[label]["chapter_number"], "source_label": label,
                     "body_sha256": digest(chapters[label]["body"])} for label in item["evidence"]]
        conflict = item["expected_class"] == "conflict"
        tags = [item["expected_class"]]
        if conflict and len(evidence) > 1:
            tags.append("requires_multiple_direct_evidence")
        if item.get("designated_regression") is True:
            tags.append("category_mismatch_regression")
        cases.append({"case_id": f"v9-{item['id']}", "authored_id": item["id"], "corpus_key": key, "seed_key": key,
                      "target_draft": item["draft"], "target_claim_ordinal": 1, "expected_class": item["expected_class"],
                      "expected_category": item["category"] if conflict else None,
                      "expected_severity": "high" if conflict else ("low" if item["expected_class"] == "insufficient_evidence" else None),
                      "expected_evidence": evidence, "source_lineage": [{"corpus_key": key, **row} for row in evidence],
                      "requires_multiple_direct_evidence": conflict and len(evidence) > 1, "challenge_tags": tags,
                      "rubric": {"minimum_direct_evidence": len(evidence) if conflict else 0, "requires_full_expected_evidence": conflict}})
    case_payload = {"schema_version": "scc-eval-case-set-v9", "status": "held_out_user_authored", "evaluation_only": True,
                    "production_seed": False, "protected_asset_source": False, "formal_run_executed": False,
                    "provider_calls": 0, "authoring_source_sha256": source_sha, "cases": cases}
    CASE_SET.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    split = {name: sum(case["expected_class"] == name for case in cases) for name in ("conflict", "no_conflict", "insufficient_evidence")}
    stability = {"representative_case_ids": representatives(cases), "selection_rule": "first by case_id among designated regressions, no_conflict, insufficient_evidence",
                 "independent_runs_per_case": 3, "first_formal_runs_included_per_case": 1, "additional_calls_after_formal": 6,
                 "execution_status": "not_run", "terminal_failure_quality_stability": False}
    v8 = json.loads((ROOT / "evaluation/manifests/eval-set-v8-manifest.json").read_text(encoding="utf-8"))
    manifest = {"manifest_version": "scc-eval-manifest-v9", "status": "candidate_for_controller_review",
                "case_set": {"path": "evaluation/case_sets/eval-set-v9.json", "canonical_sha256": canonical(case_payload),
                             "case_count": len(cases), "split": split},
                "fixture_corpus": {"path": "evaluation/fixtures/eval-v9-corpus-manifest.json", "canonical_sha256": corpus_manifest["canonical_sha256"],
                                   "evaluation_only": True, "production_seed": False, "protected_asset_source": False},
                "authoring": {"path": "evaluation/eval_set_v9_authoring/cases.json", "sha256": source_sha, "author": source.get("author") or "user",
                              "classification": "held_out_user_authored"},
                "runtime_contract": RUNTIME_CONTRACT, "scoring": v8["scoring"], "required_thresholds": REQUIRED_THRESHOLDS,
                "stability_protocol": stability, "formal_run_plan": {"path": "evaluation/manifests/eval-v9-first-formal-plan.json", "status": "not_run"}}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan = {"schema_version": "scc-eval-v9-first-formal-plan-v1", "status": "not_run", "controller_candidate_gate_passed": False,
            "formal_inputs_frozen": False, "real_provider_authorization_received": False, "formal_run_executed": False, "provider_calls": 0,
            "runtime_contract": RUNTIME_CONTRACT, "planned_output_paths": {**OUTPUTS, "post_run_integrity": "evaluation/results/v9-first-formal-post-run-integrity.json"},
            "provider_execution": {"formal_cases": len(cases), "stability_representative_cases": 3, "additional_stability_calls": 6,
                                   "planned_provider_calls": len(cases) + 6},
            "stability_protocol": stability}
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"authoring_sha256": source_sha, "case_canonical_sha256": manifest["case_set"]["canonical_sha256"],
            "corpus_canonical_sha256": corpus_manifest["canonical_sha256"], "cases": len(cases), "split": split,
            "stability_representatives": stability["representative_case_ids"]}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
