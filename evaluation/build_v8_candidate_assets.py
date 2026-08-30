"""Build deterministic, evaluation-only V8 candidate assets; never formal inputs."""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation" / "fixtures"


def canonical(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


CORPORA = {
    "dusk_viaduct": {
        "title": "The Dusk Viaduct Archive", "characters": ["Palo Neris", "Iven Sorr"], "locations": ["Clove Bridge", "Moth Vault"],
        "design": "bridge archives, pin custody, and measured lantern routes",
        "chapters": [
            ("Roster-pin condition", "roster_pin_rule", "A named person may open the Clove Bridge archive only when that person wears the archive's silver roster pin; the rule does not name its current wearer."),
            ("Pin custody ledger", "roster_pin_ledger", "The dusk ledger lists Iven Sorr, and no other person, as the current wearer of the silver roster pin."),
            ("Seal condition", "seal_definition", "The Moth Vault tube counts as sealed exactly when its neck thread is both uncut and blue."),
            ("Thread inspection", "thread_inspection", "The tube inspection records an uncut neck thread whose dye is gray, not blue."),
            ("Span lamp count", "lamp_count", "The Clove Bridge maintenance sheet records six lanterns along the east span; a separate west-span entry records nine and is not part of the east span."),
            ("Rail polish", "rail_polish", "Palo Neris polishes the bridge rail with chalk paste; an unrelated vault list mentions oil for hinges."),
            ("Pending weight", "pending_weight", "The vault parcel has been weighed, but the ledger leaves its final weight outcome pending."),
            ("Blank bearer", "blank_bearer", "A transfer tag records that a tube changed hands but leaves the bearer name blank."),
        ],
        "conflicts": [("relationship", [1, 2], "Palo Neris alone may open the Clove Bridge archive.", ["relationship", "world_rule"]), ("object_state", [3, 4], "The Moth Vault tube remains sealed.", ["location_action", "object_state"])],
        "controls": [(5, "The east span of Clove Bridge has six lanterns."), (6, "Palo Neris uses chalk paste on the bridge rail.")],
        "unknowns": [(7, "The vault parcel's final weight was recorded as forty stones.", "pending_outcome"), (8, "Iven Sorr carried the transferred tube.", "blank_identity")],
    },
    "sable_tideglass": {
        "title": "The Sable Tideglass Office", "characters": ["Yara Cett", "Brom Olt"], "locations": ["Pewter Room", "Violet Slip"],
        "design": "parcel classifications, receipt procedure, and tideglass measurements",
        "chapters": [
            ("Receipt scope", "receipt_scope", "Paper receipt is mandatory only for a parcel classified large; this scope statement does not classify any parcel."),
            ("Parcel classification", "parcel_classification", "The Violet Slip dispatch card classifies the tideglass parcel as large, while an unrelated sample pouch is marked small."),
            ("Facet-count convention", "facet_count_rule", "The official tideglass facet count is the number of facets listed in the certified measuring card."),
            ("Certified measuring card", "facet_measurement", "The certified card lists seventeen facets for the tideglass lens."),
            ("Stamp color", "stamp_color", "Yara Cett applies a violet stamp to the sealed parcel; Brom Olt's blue desk stamp concerns a different invoice."),
            ("Slip shelving", "slip_shelving", "The Violet Slip is shelved in the Pewter Room after noon review."),
            ("Unranked notes", "unranked_notes", "Two dispatch notes propose different couriers and explicitly assign neither note priority."),
            ("Preparation only", "preparation_only", "Brom Olt prepared a receipt envelope, but no source records whether any receipt was issued."),
        ],
        "conflicts": [("world_rule", [1, 2], "The tideglass parcel may be sent without a paper receipt.", ["relationship", "world_rule"]), ("attribute", [3, 4], "The certified tideglass lens has twelve facets.", None)],
        "controls": [(5, "Yara Cett uses a violet stamp on the sealed parcel."), (6, "The Violet Slip is shelved in the Pewter Room after review.")],
        "unknowns": [(7, "Yara Cett was the selected courier.", "no_priority"), (8, "Brom Olt issued the parcel receipt.", "preparation_without_result")],
    },
    "flint_garden": {
        "title": "The Flint Garden Registry", "characters": ["Noma Rusk", "Eli Vann"], "locations": ["Frost Court", "Kite Shed"],
        "design": "garden notices, coded repairs, and final-gate completion records",
        "chapters": [
            ("Route-code map", "route_code_map", "On the Flint Garden registry, repair code K-4 denotes work performed in Frost Court; the map does not identify a particular repair."),
            ("Repair receipt", "repair_receipt", "Eli Vann's hinge repair receipt bears route code K-4; another receipt for a gate latch bears K-9."),
            ("Completion definition", "completion_definition", "A seed-gate delivery is complete only if both the delivery stamp is present and the final gate latch is closed."),
            ("Latch log", "latch_log", "The seed-gate log records a delivery stamp, but says the final gate latch remained open."),
            ("Pruning tool", "pruning_tool", "Noma Rusk trims the frost hedge with a crescent shear; a nearby rake entry refers to leaf collection only."),
            ("Court bell", "court_bell", "Frost Court opens after one brass bell and two reed bells."),
            ("Unconfirmed cause", "unconfirmed_cause", "A cracked pot was found after rain, but no record identifies whether wind, frost, or a person caused it."),
            ("Inspection without outcome", "inspection_without_outcome", "The Kite Shed gate was inspected, but the inspector recorded no pass or fail result."),
        ],
        "conflicts": [("location_action", [1, 2], "Eli Vann repaired the hinge in Kite Shed.", ["location_action", "object_state"]), ("event_status", [3, 4], "The seed-gate delivery was complete.", ["timeline", "event_status"])],
        "controls": [(5, "Noma Rusk trims the frost hedge with a crescent shear."), (6, "Frost Court opens after one brass bell and two reed bells.")],
        "unknowns": [(7, "Frost caused the cracked pot.", "unconfirmed_causation"), (8, "The Kite Shed gate passed inspection.", "inspection_without_outcome")],
    },
    "opal_nursery": {
        "title": "The Opal Nursery Ledger", "characters": ["Rhea Mott", "Cian Dusk"], "locations": ["Lantern Ward", "Moss Dock"],
        "design": "sealed notices, dawn tags, and nursery transfer conditions",
        "chapters": [
            ("Notice knowledge condition", "notice_knowledge_rule", "Before dawn, the sealed opal notice is the only permitted channel for the Lantern Ward transfer; a person knows the transfer only after signing that notice."),
            ("Notice receipt book", "notice_receipt_book", "At 04:50 the receipt book shows the sealed opal notice signed only by Rhea Mott; Cian Dusk has no notice receipt."),
            ("Dawn-tag convention", "dawn_tag_rule", "A transfer tagged afterglow is logged after the ward's dawn bell has rung."),
            ("Transfer tag", "transfer_tag", "The Moss Dock transfer entry is tagged afterglow."),
            ("Cradle fabric", "cradle_fabric", "The Lantern Ward cradle is lined with amber felt; a dock blanket is described as green wool."),
            ("Dock ledger shelf", "dock_ledger_shelf", "Rhea Mott files the Moss Dock ledger in the Lantern Ward cabinet."),
            ("Pending count", "pending_count", "The nursery count sheet lists seedlings examined but leaves the surviving total blank."),
            ("Unidentified parcel", "unidentified_parcel", "A parcel reached Moss Dock, but its seal mark does not identify the nursery sender."),
        ],
        "conflicts": [("character_knowledge", [1, 2], "At 04:50, Cian Dusk knew the Lantern Ward transfer destination.", None), ("timeline", [3, 4], "The Moss Dock transfer was logged before the dawn bell.", ["timeline", "event_status"])],
        "controls": [(5, "The Lantern Ward cradle is lined with amber felt."), (6, "Rhea Mott files the Moss Dock ledger in the Lantern Ward cabinet.")],
        "unknowns": [(7, "The nursery recorded thirty surviving seedlings.", "blank_outcome"), (8, "Rhea Mott sent the parcel to Moss Dock.", "unconfirmed_identity")],
    },
}


def make_corpus(key: str, spec: dict[str, Any]) -> dict[str, Any]:
    chapters = [{"chapter_number": index, "title": title, "source_label": label, "body": body} for index, (title, label, body) in enumerate(spec["chapters"], 1)]
    return {"schema_version": "scc-evaluation-only-corpus-v1", "corpus_key": key, "title": spec["title"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False,
            "generation": {"method": "deterministic_original", "generator_version": "v8-candidate-1", "source_inputs": []},
            "lineage": {"work_title": spec["title"], "characters": spec["characters"], "locations": spec["locations"], "core_design": spec["design"]},
            "chapters": chapters,
            "memory": [{"memory_type": "static_canon", "subject": spec["characters"][0], "predicate": "fixture_anchor", "value": f"{key}-{index}", "source": {"chapter_number": index, "source_label": chapters[index-1]["source_label"]}} for index in (1, 3, 5, 7)]}


def build() -> dict[str, Any]:
    corpora = {key: make_corpus(key, spec) for key, spec in CORPORA.items()}
    for key, payload in corpora.items():
        (FIXTURES / f"eval-v8-{key.replace('_', '-')}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    corpus_manifest = {"schema_version": "scc-evaluation-only-corpus-manifest-v1", "evaluation_only": True, "production_seed": False, "protected_asset_source": False,
        "files": [{"corpus_key": key, "path": f"evaluation/fixtures/eval-v8-{key.replace('_', '-')}.json", "sha256": hashlib.sha256((FIXTURES / f"eval-v8-{key.replace('_', '-')}.json").read_bytes()).hexdigest()} for key in corpora],
        "canonical_sha256": canonical([{key: value} for key, value in corpora.items()])}
    (FIXTURES / "eval-v8-corpus-manifest.json").write_text(json.dumps(corpus_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    def evidence(key: str, index: int) -> dict[str, Any]:
        chapter = corpora[key]["chapters"][index - 1]
        return {"chapter_number": index, "source_label": chapter["source_label"], "body_sha256": digest(chapter["body"])}
    cases, review = [], []
    for key, spec in CORPORA.items():
        for number, (category, source_numbers, target, boundary) in enumerate(spec["conflicts"], 1):
            ident = f"v8-{key.replace('_', '-')}-conflict-{category}"
            evidence_rows = [evidence(key, index) for index in source_numbers]
            signature = f"v8|{category}|joined_definition_and_observation|{key}|{number}"
            case = {"case_id": ident, "corpus_key": key, "seed_key": key, "target_draft": target, "target_claim_ordinal": 1, "expected_class": "conflict", "expected_category": category, "expected_severity": "high", "expected_evidence": evidence_rows,
                "source_lineage": [{"corpus_key": key, **item} for item in evidence_rows], "requires_multiple_direct_evidence": True, "each_expected_evidence_individually_insufficient": True,
                # Exactly one designated regression per required boundary pair.
                # The remaining boundary cases stay in the set as boundary
                # coverage, but must not silently inflate a 3/3 scorecard.
                "challenge_tags": ["requires_multiple_direct_evidence", "conflicting_sources", *(["category_mismatch_regression"] if category in {"relationship", "location_action", "timeline"} else [])], "category_boundary_pair": boundary,
                "retrieval_difficulty": "paired_direct", "core_fact_key": f"v8-{key}-{category}-joined", "claim_shape": f"v8-conflict-{category}-joint-inference", "decision_signature": signature, "proper_nouns": [*spec["characters"], *spec["locations"]],
                "evidence_completeness_review": ["Evidence A defines the governing condition but does not establish the relevant observed person, state, code, tag, or record.", "Evidence B supplies that observed fact but does not define why it controls the draft claim.", "Together the rule or convention and the observed record establish that the draft is incompatible with the evidence."],
                "rubric": {"minimum_direct_evidence": 2, "requires_full_expected_evidence": True}}
            cases.append(case)
            review.append({"case_id": ident, "corpus_key": key, "decision_point": f"V8 {category} joint inference", "prior_archetype_reference": "new V8 original decision structure", "why_independent": "New corpus, entities, evidence text, core fact, and decision signature.", "same_decision_point": False, "review_status": "completed_manual_semantic_review", "each_expected_evidence_individually_insufficient": True,
                "evidence_a_alone_insufficient_reason": case["evidence_completeness_review"][0], "evidence_b_alone_insufficient_reason": case["evidence_completeness_review"][1], "joint_inference": case["evidence_completeness_review"][2]})
        for index, target in spec["controls"]:
            ident = f"v8-{key.replace('_', '-')}-control-{index}"; row = evidence(key, index)
            cases.append({"case_id": ident, "corpus_key": key, "seed_key": key, "target_draft": target, "target_claim_ordinal": 1, "expected_class": "no_conflict", "expected_category": None, "expected_severity": None, "expected_evidence": [row], "source_lineage": [{"corpus_key": key, **row}], "requires_multiple_direct_evidence": False, "each_expected_evidence_individually_insufficient": False, "challenge_tags": ["supported_control"], "category_boundary_pair": None, "retrieval_difficulty": "direct_with_same_entity_distractor", "core_fact_key": f"v8-{key}-control-{index}", "claim_shape": f"v8-supported-control-with-distractor-{key}-{index}", "decision_signature": f"v8|control|same_entity_distractor|{key}|{index}", "proper_nouns": [*spec["characters"], *spec["locations"]], "evidence_completeness_review": None, "rubric": {"minimum_direct_evidence": 0, "requires_full_expected_evidence": False}})
            review.append({"case_id": ident, "corpus_key": key, "decision_point": "direct supported control with same-entity distractor", "prior_archetype_reference": "new V8 original control", "why_independent": "New V8 entity and direct source.", "same_decision_point": False, "review_status": "completed_manual_semantic_review", "each_expected_evidence_individually_insufficient": False, "evidence_a_alone_insufficient_reason": None, "evidence_b_alone_insufficient_reason": None, "joint_inference": None})
        for index, target, reason in spec["unknowns"]:
            ident = f"v8-{key.replace('_', '-')}-insufficient-{index}"; row = evidence(key, index)
            cases.append({"case_id": ident, "corpus_key": key, "seed_key": key, "target_draft": target, "target_claim_ordinal": 1, "expected_class": "insufficient_evidence", "expected_category": None, "expected_severity": "low", "expected_evidence": [row], "source_lineage": [{"corpus_key": key, **row}], "requires_multiple_direct_evidence": False, "each_expected_evidence_individually_insufficient": False, "challenge_tags": ["insufficient_evidence", "ambiguous_evidence", reason], "category_boundary_pair": None, "retrieval_difficulty": reason, "core_fact_key": f"v8-{key}-unknown-{reason}", "claim_shape": f"v8-insufficient-{reason}-{key}", "decision_signature": f"v8|insufficient|{reason}|{key}|{index}", "proper_nouns": [*spec["characters"], *spec["locations"]], "evidence_completeness_review": None, "rubric": {"minimum_direct_evidence": 0, "requires_full_expected_evidence": False}})
            review.append({"case_id": ident, "corpus_key": key, "decision_point": f"insufficient evidence: {reason}", "prior_archetype_reference": "new V8 original uncertainty", "why_independent": "New V8 entity and unresolved record.", "same_decision_point": False, "review_status": "completed_manual_semantic_review", "each_expected_evidence_individually_insufficient": False, "evidence_a_alone_insufficient_reason": None, "evidence_b_alone_insufficient_reason": None, "joint_inference": None})
    case_payload = {"schema_version": "scc-eval-case-set-v8-candidate", "status": "candidate_for_controller_review", "evaluation_only": True, "production_seed": False, "protected_asset_source": False, "formal_run_executed": False, "provider_calls": 0, "cases": cases}
    case_hash = canonical(case_payload)
    (ROOT / "evaluation/case_sets/eval-set-v8-candidate.json").write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_payload = {"schema_version": "scc-eval-v8-semantic-review-v1", "review_scope": "implementation_manual_semantic_review", "status": "candidate_for_controller_review", "formal_run_executed": False, "provider_calls": 0, "entries": review}
    (ROOT / "evaluation/v8-candidate-semantic-review.json").write_text(json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    v7 = json.loads((ROOT / "evaluation/manifests/eval-set-v7-manifest.json").read_text(encoding="utf-8"))
    v8_stability = {"representative_case_ids": ["v8-dusk-viaduct-conflict-relationship", "v8-sable-tideglass-control-5", "v8-opal-nursery-insufficient-7"], "independent_runs_per_case": 3, "first_formal_runs_included_per_case": 1, "additional_calls_after_formal": 6, "execution_status": "not_run", "terminal_failure_quality_stability": False}
    manifest = {"manifest_version": "scc-eval-manifest-v8-candidate", "status": "candidate_for_controller_review", "case_set": {"path": "evaluation/case_sets/eval-set-v8-candidate.json", "canonical_sha256": case_hash, "case_count": 24, "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8}, "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2}}, "fixture_corpus": {"path": "evaluation/fixtures/eval-v8-corpus-manifest.json", "canonical_sha256": corpus_manifest["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False}, "runtime_contract": {"model_label": "deepseek-v4-pro", "prompt_version": "continuity-review-v6"}, "scoring": v7["scoring"], "required_thresholds": v7["required_thresholds"], "stability_protocol": v8_stability, "formal_run_plan": {"path": "evaluation/manifests/eval-v8-first-formal-plan.json", "status": "not_run"}, "boundaries": {"evaluation_only": True, "production_seed": False, "protected_asset_source": False, "formal_run_executed": False, "provider_calls": 0, "real_provider_authorization": False, "controller_candidate_gate_passed": False}}
    (ROOT / "evaluation/manifests/eval-set-v8-candidate-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    outputs = {key: f"evaluation/results/eval-v8-first-formal-{suffix}" for key, suffix in {"checkpoint": "checkpoint.json", "results": "results.json", "report": "report.md", "bad_cases": "bad-cases.json", "stability": "stability.json", "run_manifest": "run-manifest.json", "api_scan": "api-corpus-scan.json"}.items()} | {"post_run_integrity": "evaluation/results/v8-first-formal-post-run-integrity.json"}
    plan = {"schema_version": "scc-eval-v8-first-formal-plan-v1", "status": "not_run", "controller_candidate_gate_passed": False, "formal_inputs_frozen": False, "real_provider_authorization_received": False, "formal_run_executed": False, "provider_calls": 0, "runtime_contract": {"model_label": "deepseek-v4-pro", "prompt_version": "continuity-review-v6"}, "planned_input_paths": {"case_set": "evaluation/case_sets/eval-set-v8.json", "manifest": "evaluation/manifests/eval-set-v8-manifest.json", "corpus_manifest": "evaluation/fixtures/eval-v8-corpus-manifest.json"}, "planned_output_paths": outputs, "provider_execution": {"formal_cases": 24, "stability_representative_cases": 3, "additional_stability_calls": 6, "planned_provider_calls": 30}, "stability_protocol": v8_stability, "bad_case_protocol": {"category_expected_and_predicted_retained": True, "raw_provider_body_retained": False, "chain_of_thought_retained": False}}
    (ROOT / "evaluation/manifests/eval-v8-first-formal-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"case_canonical_sha256": case_hash, "corpus_canonical_sha256": corpus_manifest["canonical_sha256"], "case_count": len(cases)}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
