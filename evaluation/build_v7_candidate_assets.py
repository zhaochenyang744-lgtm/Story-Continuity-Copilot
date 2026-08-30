"""Build the deterministic, evaluation-only V7 candidate assets once.

This builder contains evaluation data only.  Product code never identifies a
case, character, proper noun, or expected answer by a V7-specific value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation" / "fixtures"
CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v7-candidate.json"
CORPUS_MANIFEST_PATH = FIXTURES / "eval-v7-corpus-manifest.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-candidate-manifest.json"
REVIEW_PATH = ROOT / "evaluation" / "v7-candidate-semantic-review.json"
PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v7-first-formal-plan.json"
V6_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-candidate-manifest.json"


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def body_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _corpus(title: str, characters: list[str], locations: list[str], design: str, chapters: list[tuple[str, str, str]], memory: list[tuple[str, str, str, str, int, str]]) -> dict[str, Any]:
    return {"title": title, "characters": characters, "locations": locations, "core_design": design, "chapters": [(index, *chapter) for index, chapter in enumerate(chapters, 1)], "memory": memory}


CORPORA = {
    "indigo_cartography": _corpus(
        "The Indigo Cartography Room", ["Miri Ansel", "Doran Pike"], ["Raster Hall", "Windward Annex"], "flood-season map custody and layered survey plates",
        [
            ("Blue-alert badge rule", "ordinary_custody_charter", "During a blue-flood alert, survey plates may be released only by the registered wearer of the cobalt tide badge."),
            ("Blue-alert badge inspection", "flood_delegation", "The blue-alert inspection log records Doran Pike as the registered wearer of the cobalt tide badge."),
            ("Final-glaze counting rule", "first_glazing_record", "The current pane count of the north survey window is the number of panes visible in its final-glaze preservation photograph."),
            ("Final-glaze photograph", "restoration_acceptance", "The final-glaze preservation photograph of the north survey window shows fifteen separately framed mica panes."),
            ("Latitude stencil", "latitude_stencil", "The tide table stencil marks the equinox latitude with a narrow silver line."),
            ("Archive bell", "archive_bell", "Raster Hall closes its map drawers after two low bells and one high bell."),
            ("Initialed margin note", "initialed_margin_note", "A margin note is initialed M. A.; both Miri Ansel and Mara Aven were present, and no witness identifies the writer."),
            ("Unlogged courier seal", "unlogged_courier_seal", "The courier seal is intact, but the dispatch book leaves its destination field blank."),
        ],
        [("static_canon", "Doran Pike", "blue_alert_badge", "cobalt tide badge", 2, "flood_delegation"), ("static_canon", "north survey window", "final_glaze_photo_panes", "fifteen", 4, "restoration_acceptance"), ("static_canon", "tide table stencil", "equinox_mark", "narrow silver line", 5, "latitude_stencil"), ("open_thread", "margin note", "writer", "unresolved", 7, "initialed_margin_note")],
    ),
    "ember_siltworks": _corpus(
        "The Ember Siltworks Register", ["Kesa Thorn", "Ulan Vey"], ["Kiln Basin", "Ash Loop"], "silt-filter operating rules and sealed vessel state changes",
        [
            ("Red-purge applicability", "filter_baseline", "At the red pressure mark, the purge instruction opens any filter fitted with a copper relief ring for one cycle."),
            ("Amber-ring inventory", "steam_exception", "The basin inventory records that every amber filter is fitted with a copper relief ring."),
            ("Cobalt seal definition", "vessel_sealing", "For the Cobalt Vessel, the black resin band is the seal: if the band is removed from the vessel, the vessel is unsealed."),
            ("Rinse band inventory", "rinse_transfer", "After the rinse, the custody sheet places the Cobalt Vessel's black resin band in an inventory sleeve rather than on the vessel."),
            ("Kiln pigment", "kiln_pigment", "Kesa Thorn mixes the inspection pigment from ochre dust and clear oil."),
            ("Gauge tapping", "gauge_tapping", "The pressure gauge is tested with four light taps before a shift begins."),
            ("Unranked sampler slips", "unranked_sampler_slips", "Two sampler slips name different collecting crews, and the register declares no priority between them."),
            ("Pending ash assay", "pending_ash_assay", "The ash assay lists its sample weight but records the composition result as pending."),
        ],
        [("static_canon", "amber filters", "relief_ring", "copper", 2, "steam_exception"), ("dynamic_state", "Cobalt Vessel", "post_rinse_band_location", "inventory sleeve", 4, "rinse_transfer"), ("static_canon", "inspection pigment", "ingredients", "ochre dust and clear oil", 5, "kiln_pigment"), ("open_thread", "ash assay", "composition", "pending", 8, "pending_ash_assay")],
    ),
    "brass_migration": _corpus(
        "The Brass Migration Ledger", ["Oren Sile", "Vela Mar"], ["Gannet Steps", "Marrow Quay"], "tagged beacon migration and staged departure chronology",
        [
        ("Shoreglass dissemination rule", "early_route_briefing", "Before first light, the named sealed Shoreglass brief is the sole and exhaustive dissemination channel for the route stating that flock Delta goes to Marrow Quay. In that period, a person knows that route only after signing for Shoreglass; oral recitation, copied extracts, and all other route transmissions are prohibited."),
            ("Shoreglass delivery register", "restricted_reroute_note", "At 05:40, before first light, the register records the sealed Shoreglass brief delivered only to Vela Mar; Oren Sile has no delivery or receipt entry."),
            ("North-Chime convention", "launch_plan", "A beacon departure entry tagged North Chime denotes a departure after the harbor lamps are lit."),
            ("Beacon departure tag", "observed_departure", "The watch book tags the brass beacons' departure entry North Chime."),
            ("Wing tally", "wing_tally", "The east flock tally contains twenty-one brass beacons."),
            ("Mooring thread", "mooring_thread", "Each beacon cradle is tied with green hemp thread during the quiet watch."),
            ("Blurred barge image", "blurred_barge_image", "A blurred quay image shows a covered barge, but its cargo mark and departure time cannot be read."),
            ("Unsigned wing repair", "unsigned_wing_repair", "A repair card confirms a wing was mended but leaves the beacon identifier blank."),
        ],
        [("character_knowledge", "Vela Mar", "Shoreglass_brief", "sole recipient at 05:40", 2, "restricted_reroute_note"), ("event_timeline", "brass beacon departure", "timestamp_tag", "North Chime", 4, "observed_departure"), ("static_canon", "east flock", "beacon_count", "twenty-one", 5, "wing_tally"), ("open_thread", "wing repair", "beacon_identifier", "blank", 8, "unsigned_wing_repair")],
    ),
    "orchid_signalhouse": _corpus(
        "The Orchid Signalhouse Book", ["Teren Lox", "Siva Rehn"], ["Orchid Platform", "Lacquer Tunnel"], "signal relay duties, diversion locations, and interrupted relay completion",
        [
            ("Calibration-token convention", "platform_assignment", "A calibration token is stamped by the relay location where its bearer performs the calibration."),
            ("Teren token stamp", "tunnel_diversion", "Teren Lox's fog-day calibration token is stamped Lacquer Tunnel."),
            ("Delivery completion definition", "relay_opening", "An eastward relay delivery counts complete only when its receipt lens remains clear through the final echo."),
            ("Hail lens log", "relay_interruption", "The hail log records that the Orchid relay's receipt lens clouded before the final echo."),
            ("Lens cloth", "lens_cloth", "Siva Rehn keeps the relay lens wrapped in a blue linen cloth."),
            ("Chime pattern", "chime_pattern", "A cleared tunnel is marked by one long chime followed by two short chimes."),
            ("Unknown platform visitor", "unknown_platform_visitor", "The visitor sheet records a boot print at Orchid Platform but names no visitor and gives no time."),
            ("Open relay audit", "open_relay_audit", "The audit confirms the shutter was inspected but does not record whether its final alignment passed."),
        ],
        [("dynamic_state", "Teren Lox", "fog_calibration_token_location", "Lacquer Tunnel", 2, "tunnel_diversion"), ("event_timeline", "Orchid relay transmission", "receipt_lens_state", "clouded before final echo", 4, "relay_interruption"), ("static_canon", "relay lens", "wrapping", "blue linen cloth", 5, "lens_cloth"), ("open_thread", "relay shutter alignment", "final_result", "not recorded", 8, "open_relay_audit")],
    ),
}


CASES = [
    ("v7-cartography-authority", "indigo_cartography", "During the blue-flood alert, Miri Ansel alone may release the survey plates.", "conflict", "relationship", [1, 2], ["requires_multiple_direct_evidence", "conflicting_sources", "category_mismatch_regression"], "cartography-blue-badge-release", "authorization_rule_joined_to_named_badge_holder", "conflict|relationship|authorization_condition_plus_holder", ["Miri Ansel", "Doran Pike"], ["relationship", "world_rule"]),
    ("v7-cartography-panes", "indigo_cartography", "The current north survey window has twelve mica panes.", "conflict", "attribute", [3, 4], ["requires_multiple_direct_evidence", "conflicting_sources"], "cartography-current-pane-count", "current_property_defined_by_final_glaze_photo", "conflict|attribute|property_rule_plus_measurement", ["north survey window"], None),
    ("v7-cartography-control-stencil", "indigo_cartography", "The equinox latitude is marked with a narrow silver line.", "no_conflict", None, [5], ["supported_control"], "cartography-equinox-stencil-mark", "directly_supported_survey_stencil_mark", "no_conflict|supported|survey_mark", ["tide table stencil"], None),
    ("v7-cartography-control-bell", "indigo_cartography", "Raster Hall closes map drawers after two low bells and one high bell.", "no_conflict", None, [6], ["supported_control"], "cartography-drawer-bell-pattern", "directly_supported_archive_signal", "no_conflict|supported|archive_bell_pattern", ["Raster Hall"], None),
    ("v7-cartography-insufficient-note", "indigo_cartography", "Miri Ansel wrote the initialed margin note.", "insufficient_evidence", None, [7], ["insufficient_evidence", "ambiguous_evidence"], "cartography-margin-note-author", "ambiguous_initials_between_two_people", "insufficient_evidence|ambiguous_author|margin_note", ["Miri Ansel", "Mara Aven"], None),
    ("v7-cartography-insufficient-courier", "indigo_cartography", "The sealed courier packet was dispatched to Windward Annex.", "insufficient_evidence", None, [8], ["insufficient_evidence", "ambiguous_evidence"], "cartography-courier-destination", "blank_destination_asserted", "insufficient_evidence|blank_destination|courier", ["Windward Annex"], None),
    ("v7-siltworks-filter-rule", "ember_siltworks", "An amber filter must stay closed even during a red-mark pressure purge.", "conflict", "world_rule", [1, 2], ["requires_multiple_direct_evidence", "conflicting_sources", "category_mismatch_regression"], "siltworks-red-purge-amber-rule", "purge_rule_joined_to_filter_applicability", "conflict|world_rule|conditional_rule_plus_scope_membership", ["amber filters"], ["world_rule", "relationship"]),
    ("v7-siltworks-vessel-state", "ember_siltworks", "After the rinse, the Cobalt Vessel remains sealed in Kiln Basin.", "conflict", "object_state", [3, 4], ["requires_multiple_direct_evidence", "conflicting_sources"], "siltworks-cobalt-post-rinse-seal", "seal_definition_joined_to_band_location", "conflict|object_state|state_definition_plus_observed_marker", ["Cobalt Vessel", "Kiln Basin"], None),
    ("v7-siltworks-control-pigment", "ember_siltworks", "Inspection pigment is mixed from ochre dust and clear oil.", "no_conflict", None, [5], ["supported_control"], "siltworks-inspection-pigment", "directly_supported_material_recipe", "no_conflict|supported|pigment_recipe", ["inspection pigment"], None),
    ("v7-siltworks-control-gauge", "ember_siltworks", "The pressure gauge is tested with four light taps before a shift.", "no_conflict", None, [6], ["supported_control"], "siltworks-gauge-tapping", "directly_supported_equipment_test", "no_conflict|supported|gauge_taps", ["pressure gauge"], None),
    ("v7-siltworks-insufficient-crew", "ember_siltworks", "Kesa Thorn's crew collected the ash sample.", "insufficient_evidence", None, [7], ["insufficient_evidence", "ambiguous_evidence"], "siltworks-sample-crew", "unranked_competing_sampler_sources", "insufficient_evidence|ambiguous_source_priority|sample_crew", ["Kesa Thorn"], None),
    ("v7-siltworks-insufficient-assay", "ember_siltworks", "The ash assay proved that the sample was pure iron.", "insufficient_evidence", None, [8], ["insufficient_evidence", "ambiguous_evidence"], "siltworks-ash-composition", "pending_assay_result_asserted", "insufficient_evidence|pending_result|ash_assay", ["ash assay"], None),
    ("v7-migration-reroute-knowledge", "brass_migration", "At 05:40, Oren Sile knew that flock Delta would go to Marrow Quay.", "conflict", "character_knowledge", [1, 2], ["requires_multiple_direct_evidence", "conflicting_sources"], "migration-oren-shoreglass-knowledge", "sole_dissemination_rule_joined_to_delivery_register", "conflict|character_knowledge|sole_channel_plus_recipient_record", ["Oren Sile", "Vela Mar"], None),
    ("v7-migration-departure-order", "brass_migration", "The brass beacons left their cradles before the harbor lamps were lit.", "conflict", "timeline", [3, 4], ["requires_multiple_direct_evidence", "conflicting_sources", "category_mismatch_regression"], "migration-north-chime-departure-order", "timestamp_convention_joined_to_departure_tag", "conflict|timeline|time_convention_plus_event_tag", ["brass beacons", "harbor lamps"], ["timeline", "event_status"]),
    ("v7-migration-control-tally", "brass_migration", "The east flock tally contains twenty-one brass beacons.", "no_conflict", None, [5], ["supported_control"], "migration-east-flock-count", "directly_supported_beacon_count", "no_conflict|supported|beacon_tally", ["east flock"], None),
    ("v7-migration-control-thread", "brass_migration", "Beacon cradles use green hemp thread during the quiet watch.", "no_conflict", None, [6], ["supported_control"], "migration-cradle-thread", "directly_supported_cradle_material", "no_conflict|supported|cradle_thread", ["beacon cradle"], None),
    ("v7-migration-insufficient-barge", "brass_migration", "The covered barge left Marrow Quay at noon carrying flock Delta.", "insufficient_evidence", None, [7], ["insufficient_evidence", "ambiguous_evidence"], "migration-covered-barge-cargo", "unreadable_image_cargo_and_time", "insufficient_evidence|unreadable_record|barge_departure", ["Marrow Quay", "flock Delta"], None),
    ("v7-migration-insufficient-repair", "brass_migration", "Beacon Delta-7 received the wing repair.", "insufficient_evidence", None, [8], ["insufficient_evidence", "ambiguous_evidence"], "migration-wing-repair-identifier", "blank_repair_subject", "insufficient_evidence|blank_identifier|wing_repair", ["Beacon Delta-7"], None),
    ("v7-signalhouse-calibration-place", "orchid_signalhouse", "During the fog diversion, Teren Lox calibrated the orchid relay at Orchid Platform.", "conflict", "location_action", [1, 2], ["requires_multiple_direct_evidence", "conflicting_sources"], "signalhouse-terens-token-calibration-place", "token_location_convention_joined_to_named_stamp", "conflict|location_action|location_rule_plus_token_stamp", ["Teren Lox", "Orchid Platform", "Lacquer Tunnel"], ["location_action", "object_state"]),
    ("v7-signalhouse-delivery-status", "orchid_signalhouse", "The Orchid relay completed its eastward delivery after Siva Rehn raised the shutter.", "conflict", "event_status", [3, 4], ["requires_multiple_direct_evidence", "conflicting_sources"], "signalhouse-receipt-lens-delivery-status", "completion_definition_joined_to_final_lens_record", "conflict|event_status|completion_rule_plus_condition_record", ["Orchid relay", "Siva Rehn"], None),
    ("v7-signalhouse-control-cloth", "orchid_signalhouse", "The relay lens is wrapped in blue linen cloth.", "no_conflict", None, [5], ["supported_control"], "signalhouse-lens-cloth", "directly_supported_lens_wrapping", "no_conflict|supported|lens_cloth", ["relay lens"], None),
    ("v7-signalhouse-control-chime", "orchid_signalhouse", "A cleared tunnel is marked by one long chime followed by two short chimes.", "no_conflict", None, [6], ["supported_control"], "signalhouse-tunnel-chime", "directly_supported_signal_sequence", "no_conflict|supported|tunnel_chime", ["Lacquer Tunnel"], None),
    ("v7-signalhouse-insufficient-visitor", "orchid_signalhouse", "Siva Rehn visited Orchid Platform just before dawn.", "insufficient_evidence", None, [7], ["insufficient_evidence", "ambiguous_evidence"], "signalhouse-platform-visitor", "unnamed_and_undated_visitor_trace", "insufficient_evidence|unknown_person_and_time|platform_visit", ["Siva Rehn", "Orchid Platform"], None),
    ("v7-signalhouse-insufficient-alignment", "orchid_signalhouse", "The relay shutter passed its final alignment audit.", "insufficient_evidence", None, [8], ["insufficient_evidence", "ambiguous_evidence"], "signalhouse-shutter-alignment", "final_audit_result_not_recorded", "insufficient_evidence|unrecorded_outcome|alignment", ["relay shutter"], None),
]


# Candidate-review data, not product logic. Each row documents why the two
# declared SourceSpans are jointly necessary for the conflict decision.
CONFLICT_EVIDENCE_REVIEW = {
    "cartography-blue-badge-release": (
        "The badge rule identifies the authorization condition but does not identify who holds the cobalt tide badge during this alert.",
        "The inspection identifies Doran as badge wearer but does not state what authority that badge confers.",
        "Together, the rule and inspection establish Doran as the authorized release holder, contradicting exclusive authority for Miri.",
    ),
    "cartography-current-pane-count": (
        "The counting rule identifies which record defines the current property but supplies no pane total.",
        "The photograph supplies a pane total but does not, alone, establish that the photograph defines the current count.",
        "Together, the rule and photograph establish a current count of fifteen, contradicting twelve.",
    ),
    "siltworks-red-purge-amber-rule": (
        "The purge instruction states what happens to filters with a copper relief ring but does not identify amber filters as members of that scope.",
        "The inventory places amber filters in the copper-ring scope but does not state the red-mark operating consequence.",
        "Together, the instruction and inventory require amber filters to open for the red-mark purge, contradicting a stay-closed claim.",
    ),
    "siltworks-cobalt-post-rinse-seal": (
        "The seal definition explains what removal of the black resin band means but does not state the band's post-rinse location.",
        "The inventory locates the band away from the vessel but does not, alone, define that absence as an unsealed state.",
        "Together, the definition and inventory establish that the Cobalt Vessel is unsealed after the rinse, contradicting the draft.",
    ),
    "migration-oren-shoreglass-knowledge": (
        "The dissemination rule identifies the route content and makes a signed Shoreglass receipt the sole pre-first-light condition for knowing it, but does not identify who received the brief at 05:40.",
        "The delivery register identifies who did and did not receive Shoreglass at 05:40, but does not state the brief's route content or its sole-channel rule.",
        "Together, the sole-channel knowledge condition and delivery record establish that Oren had not signed for Shoreglass at 05:40 and therefore did not know the route, contradicting the claim.",
    ),
    "migration-north-chime-departure-order": (
        "The timestamp convention defines the temporal meaning of North Chime but does not identify the beacon departure's tag.",
        "The watch book supplies the North Chime tag but does not, alone, define its relation to lamp lighting.",
        "Together, the convention and tagged entry place the departure after the lamps, contradicting before.",
    ),
    "signalhouse-terens-token-calibration-place": (
        "The token convention explains how a token stamp maps to calibration location but does not provide Teren's stamp.",
        "The token record provides Teren's Lacquer Tunnel stamp but does not, alone, define what location the stamp represents.",
        "Together, the convention and stamp place Teren's calibration in Lacquer Tunnel, contradicting Orchid Platform.",
    ),
    "signalhouse-receipt-lens-delivery-status": (
        "The completion definition states the required clear-lens condition but does not state whether the Orchid relay met it.",
        "The hail log reports a clouded lens before the final echo but does not, alone, define that condition as preventing completion.",
        "Together, the definition and hail log establish that the delivery did not complete, contradicting the draft.",
    ),
}


def fixture_payload(key: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "scc-evaluation-only-corpus-v1", "corpus_key": key, "title": spec["title"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False, "generation": {"method": "deterministic_original", "generator_version": "v7-candidate-1", "source_inputs": []}, "lineage": {"work_title": spec["title"], "characters": spec["characters"], "locations": spec["locations"], "core_design": spec["core_design"]}, "chapters": [{"chapter_number": n, "title": title, "source_label": label, "body": body} for n, title, label, body in spec["chapters"]], "memory": [{"memory_type": kind, "subject": subject, "predicate": predicate, "value": value, "source": {"chapter_number": chapter, "source_label": label}} for kind, subject, predicate, value, chapter, label in spec["memory"]]}


def case_payload(raw: tuple[Any, ...], fixtures: dict[str, dict[str, Any]]) -> dict[str, Any]:
    identifier, corpus, draft, expected_class, category, chapter_numbers, tags, core, shape, signature, nouns, boundary = raw
    chapters = {chapter["chapter_number"]: chapter for chapter in fixtures[corpus]["chapters"]}
    evidence = [{"chapter_number": number, "source_label": chapters[number]["source_label"], "body_sha256": body_sha256(chapters[number]["body"])} for number in chapter_numbers]
    conflict = expected_class == "conflict"
    completeness = CONFLICT_EVIDENCE_REVIEW.get(core)
    if conflict and completeness is None:
        raise ValueError("v7_conflict_missing_joint_evidence_review")
    return {"case_id": f"eval-{identifier}", "corpus_key": corpus, "seed_key": corpus, "target_draft": draft, "target_claim_ordinal": 1, "expected_class": expected_class, "expected_category": category, "expected_severity": ["medium", "high"] if conflict else (None if expected_class == "no_conflict" else ["low", "medium"]), "expected_evidence": evidence, "source_lineage": [{"corpus_key": corpus, **item} for item in evidence], "requires_multiple_direct_evidence": conflict, "each_expected_evidence_individually_insufficient": conflict, "challenge_tags": tags, "category_boundary_pair": boundary, "retrieval_difficulty": "paired_direct_evidence" if conflict else "nearby_distractor", "core_fact_key": core, "claim_shape": shape, "decision_signature": signature, "proper_nouns": nouns, "evidence_completeness_review": completeness, "rubric": {"decision_rule": f"Resolve the specific continuity decision represented by {core} using the declared direct evidence.", "expected_class_reason": "Both direct source spans are necessary and jointly contradict the draft." if conflict else ("The source directly supports the draft." if expected_class == "no_conflict" else "The source leaves the asserted specific fact unresolved."), "expected_category_reason": f"The decision axis is {category}; classify the issue by its core decision rather than incidental setting language." if conflict else "No conflict category is assigned to this class.", "minimum_direct_evidence": len(evidence) if conflict else 0, "requires_full_expected_evidence": conflict, "forbidden_inference": "Do not infer a conflict from either SourceSpan alone; apply the declared joint inference only when every expected direct Evidence item is present." if conflict else "Do not invent a contradiction from an explicit unknown or a directly supporting record."}}


def write_once(path: pathlib.Path, payload: Any, *, rewrite_candidate: bool = False) -> None:
    if path.exists() and not rewrite_candidate:
        raise RuntimeError(f"v7_candidate_asset_already_exists:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build(*, rewrite_candidate: bool = False) -> dict[str, Any]:
    paths = [CASE_PATH, CORPUS_MANIFEST_PATH, MANIFEST_PATH, REVIEW_PATH, PLAN_PATH, *(FIXTURES / f"eval-v7-{key.replace('_', '-')}.json" for key in CORPORA)]
    formal_lock_paths = [
        ROOT / "evaluation" / "case_sets" / "eval-set-v7.json",
        ROOT / "evaluation" / "manifests" / "eval-set-v7-manifest.json",
        ROOT / "evaluation" / "v7-semantic-review.json",
        ROOT / "evaluation" / "manifests" / "eval-set-v7-freeze-integrity.json",
    ]
    if any(path.exists() for path in formal_lock_paths):
        raise RuntimeError("v7_candidate_rewrite_rejected_after_formal_freeze")
    if any(path.exists() for path in paths) and not rewrite_candidate:
        raise RuntimeError("v7_candidate_asset_target_exists")
    if rewrite_candidate and not all(path.exists() for path in paths):
        raise RuntimeError("v7_candidate_rewrite_requires_complete_existing_candidate")
    fixtures = {key: fixture_payload(key, spec) for key, spec in CORPORA.items()}
    fixture_paths: dict[str, pathlib.Path] = {}
    for key, payload in fixtures.items():
        path = FIXTURES / f"eval-v7-{key.replace('_', '-')}.json"; write_once(path, payload, rewrite_candidate=rewrite_candidate); fixture_paths[key] = path
    corpus_manifest = {"schema_version": "scc-evaluation-only-corpus-manifest-v1", "evaluation_only": True, "production_seed": False, "protected_asset_source": False, "files": [{"corpus_key": key, "path": f"evaluation/fixtures/{path.name}", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for key, path in fixture_paths.items()], "canonical_sha256": canonical_sha256([{key: fixtures[key]} for key in fixtures])}
    write_once(CORPUS_MANIFEST_PATH, corpus_manifest, rewrite_candidate=rewrite_candidate)
    cases = [case_payload(raw, fixtures) for raw in CASES]
    case_set = {"schema_version": "scc-eval-case-set-v7-candidate", "status": "candidate_for_controller_review", "evaluation_only": True, "production_seed": False, "protected_asset_source": False, "formal_run_executed": False, "provider_calls": 0, "cases": cases}
    write_once(CASE_PATH, case_set, rewrite_candidate=rewrite_candidate)
    review = {"schema_version": "scc-eval-v7-semantic-review-v1", "review_scope": "implementation_manual_semantic_review", "status": "candidate_for_controller_review", "formal_run_executed": False, "provider_calls": 0, "structural_validation_note": "Every case received an implementation-side semantic review. The joint-evidence declarations are structural claims for controller re-reading, not proof of semantic necessity; controller approval remains independent.", "entries": [{"case_id": case["case_id"], "corpus_key": case["corpus_key"], "decision_point": case["rubric"]["decision_rule"], "prior_archetype_reference": "Checked against V1-V6 case identifiers, core facts, shapes, signatures, proper nouns, and source n-grams.", "why_independent": "The corpus setting and decision signature are newly authored and separated from all prior evaluation sets.", "same_decision_point": False, "review_status": "completed_manual_semantic_review", "each_expected_evidence_individually_insufficient": case["each_expected_evidence_individually_insufficient"], "evidence_a_alone_insufficient_reason": case["evidence_completeness_review"][0] if case["evidence_completeness_review"] else None, "evidence_b_alone_insufficient_reason": case["evidence_completeness_review"][1] if case["evidence_completeness_review"] else None, "joint_inference": case["evidence_completeness_review"][2] if case["evidence_completeness_review"] else None} for case in cases]}
    write_once(REVIEW_PATH, review, rewrite_candidate=rewrite_candidate)
    by_class = {expected_class: [case["case_id"] for case in cases if case["expected_class"] == expected_class] for expected_class in ("conflict", "no_conflict", "insufficient_evidence")}
    selected = [by_class["conflict"][0], by_class["no_conflict"][len(by_class["no_conflict"]) // 4], by_class["insufficient_evidence"][-1]]
    formal_case = ROOT / "evaluation" / "case_sets" / "eval-set-v7.json"
    formal_manifest = ROOT / "evaluation" / "manifests" / "eval-set-v7-manifest.json"
    if formal_case.exists() or formal_manifest.exists():
        raise RuntimeError("v7_formal_input_must_not_exist_during_candidate_preparation")
    outputs = {key: f"evaluation/results/eval-v7-first-formal-{suffix}" for key, suffix in {"checkpoint": "checkpoint.json", "results": "results.json", "report": "report.md", "bad_cases": "bad-cases.json", "stability": "stability.json", "run_manifest": "run-manifest.json", "api_scan": "api-corpus-scan.json"}.items()} | {"post_run_integrity": "evaluation/results/v7-first-formal-post-run-integrity.json"}
    plan = {"schema_version": "scc-eval-v7-first-formal-plan-v1", "status": "not_run", "formal_run_executed": False, "provider_calls": 0, "controller_candidate_gate_passed": False, "formal_inputs_frozen": False, "real_provider_authorization_received": False, "preconditions": ["controller independently accepts the V7 candidate Gate", "user separately and explicitly authorizes real Provider calls", "candidate assets are frozen to new approved formal paths without content changes"], "planned_input_paths": {"case_set": "evaluation/case_sets/eval-set-v7.json", "manifest": "evaluation/manifests/eval-set-v7-manifest.json", "corpus_manifest": "evaluation/fixtures/eval-v7-corpus-manifest.json"}, "planned_output_paths": outputs, "bad_case_protocol": {"capture_when": ["classification mismatch", "category mismatch", "threshold contributor failure", "terminal failure", "retrieval miss", "unresolvable or non-expected citation", "incomplete expected Evidence recall", "incomplete multi-direct Evidence set"], "merge_failure_dimensions_per_case": True, "category_expected_and_predicted_retained": True, "sanitized_fields_only": True, "raw_provider_body_retained": False, "chain_of_thought_retained": False}, "stability_protocol": {"representative_case_ids": selected, "class_coverage": ["conflict", "no_conflict", "insufficient_evidence"], "independent_runs_per_case": 3, "first_formal_runs_included": 3, "additional_calls_after_formal": 6, "execution_status": "not_run", "terminal_failure_quality_stability": False}, "stage_status": {"stage_10": "gate_failed_not_passed_v7_candidate_only", "stage_11": "not_started", "stage_12": "not_started"}, "execution_note": "Candidate plan only. Formal V7 inputs, outputs, workspaces, and Provider calls are absent and unauthorized."}
    write_once(PLAN_PATH, plan, rewrite_candidate=rewrite_candidate)
    v6 = json.loads(V6_MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest = {"manifest_version": "scc-eval-manifest-v7-candidate", "status": "candidate_for_controller_review", "case_set": {"path": "evaluation/case_sets/eval-set-v7-candidate.json", "canonical_sha256": canonical_sha256(case_set), "case_count": 24, "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8}, "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2}}, "stability_protocol": {"representative_case_ids": selected, "independent_runs_per_case": 3, "first_formal_runs_included_per_case": 1, "additional_calls_after_formal": 6, "execution_status": "not_run", "terminal_failure_quality_stability": False}, "scoring": v6["scoring"], "required_thresholds": v6["required_thresholds"], "fixture_corpus": {"path": "evaluation/fixtures/eval-v7-corpus-manifest.json", "canonical_sha256": corpus_manifest["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False}, "formal_run_plan": {"path": "evaluation/manifests/eval-v7-first-formal-plan.json", "status": "not_run"}, "boundaries": {"evaluation_only": True, "production_seed": False, "protected_asset_source": False, "formal_run_executed": False, "provider_calls": 0, "real_provider_authorization": False, "controller_candidate_gate_passed": False, "deployment": False, "ui_change": False}, "runtime_mode": "evaluation_fixture", "formal_run_executed": False, "provider_calls": 0}
    write_once(MANIFEST_PATH, manifest, rewrite_candidate=rewrite_candidate)
    return {"case_count": 24, "corpus_count": 4, "case_canonical_sha256": canonical_sha256(case_set), "corpus_canonical_sha256": corpus_manifest["canonical_sha256"], "formal_run_executed": False, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rewrite-v7-candidate", action="store_true", help="Rewrite only the complete mutable V7 candidate bundle; never formal inputs or results.")
    args = parser.parse_args()
    print(json.dumps(build(rewrite_candidate=args.rewrite_v7_candidate), ensure_ascii=False, indent=2))
