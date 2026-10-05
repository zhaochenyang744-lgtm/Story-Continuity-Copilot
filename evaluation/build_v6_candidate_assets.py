"""Build the deterministic, evaluation-only V6 candidate assets once."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation" / "fixtures"
CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v6-candidate.json"
CORPUS_MANIFEST_PATH = FIXTURES / "eval-v6-corpus-manifest.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-candidate-manifest.json"
REVIEW_PATH = ROOT / "evaluation" / "v6-candidate-semantic-review.json"
PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v6-first-formal-plan.json"
V5_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v5-candidate-manifest.json"


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def body_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_once(path: pathlib.Path, payload: Any, *, rewrite_candidate: bool = False) -> None:
    if path.exists() and not rewrite_candidate:
        raise RuntimeError(f"v6_candidate_asset_already_exists:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


CORPORA: dict[str, dict[str, Any]] = {
    "lumen_tidehouse": {
        "title": "The Saffron Tidehouse",
        "characters": ["Iven Rusk", "Talia Quill"],
        "locations": ["Meridian Intake", "Brackwater Gantry"],
        "core_design": "surge-audit custody and calibrated tidal machinery",
        "chapters": [
            (1, "Retired balance card", "retired_balance_card", "A retired balance card lists the Lumen counterweight at forty-two kilograms before the alloy insert was installed."),
            (2, "Acceptance weighing", "acceptance_weighing", "Talia Quill signed the acceptance weighing: the alloy-fitted Lumen counterweight measured fifty-seven kilograms, replacing the retired figure."),
            (3, "Pre-surge custody", "pre_surge_custody", "Before the surge alarm, the Driftglass Crate was strapped to rack seven inside Meridian Intake."),
            (4, "Post-surge transfer", "post_surge_transfer", "The post-surge custody ledger transfers the Driftglass Crate to locker two at Brackwater Gantry and marks Meridian rack seven empty."),
            (5, "Impeller cadence", "impeller_cadence", "Iven Rusk timed the north impeller at Meridian Intake: each complete cycle lasted nine minutes."),
            (6, "Reserve valve mark", "reserve_valve_mark", "The reserve sluice valve carries one saffron stripe around its handwheel for night identification."),
            (7, "Vane handover note", "vane_handover_note", "The vane handover note is signed only R. S.; the blackout roster lists both Rina Sol and Rook Sable, and no entry resolves which person the initials denote."),
            (8, "Sample route amendment", "sample_route_amendment", "The sample route amendment names Nacre Pier only after a calibration, but the calibration's effective time is unrecorded and the surge log does not say whether the amendment then applied."),
        ],
        "memory": [
            ("static_canon", "Lumen counterweight", "accepted_mass", "fifty-seven kilograms", 2, "acceptance_weighing"),
            ("dynamic_state", "Driftglass Crate", "post_surge_location", "locker two at Brackwater Gantry", 4, "post_surge_transfer"),
            ("static_canon", "north impeller", "cycle_duration", "nine minutes", 5, "impeller_cadence"),
            ("static_canon", "reserve sluice valve", "night_mark", "one saffron stripe", 6, "reserve_valve_mark"),
        ],
    },
    "velvet_signal_yard": {
        "title": "Velvet Signal Yard",
        "characters": ["Neris Vale", "Odo Prynn"],
        "locations": ["Juniper Relay Yard", "Cipher Loft"],
        "core_design": "emergency rail authority and sealed briefing circulation",
        "chapters": [
            (1, "Ordinary duty charter", "ordinary_duty_charter", "The ordinary charter gives Neris Vale departure authority while Odo Prynn inspects signal lamps without dispatch power."),
            (2, "Amber emergency rider", "amber_emergency_rider", "An amber-flag rider temporarily assigns departure authority to Odo Prynn until the yard returns to green, overriding the ordinary charter."),
            (3, "Earlier phrase briefing", "earlier_phrase_briefing", "At dusk Neris Vale read the earlier relay phrase Willow Nine; Odo Prynn was absent from that briefing."),
            (4, "Revised sealed memo", "revised_sealed_memo", "The midnight memo replaces Willow Nine with Marble Six, records delivery only to Odo Prynn, and states Neris Vale was not informed."),
            (5, "Bell cadence", "bell_cadence", "Juniper Relay Yard announces a clear branch with three short bell strokes followed by one long stroke."),
            (6, "Lever binding", "lever_binding", "Switch lever C is wrapped with violet cord so gloved operators can distinguish it in fog."),
            (7, "Relay advisory provenance", "relay_advisory_provenance", "An unsigned advisory recommends isolating the phantom-aspect circuit, but the register does not confirm its author, inspector authority, or whether it was an official finding."),
            (8, "Observer register", "observer_register", "The final observer line in the Cipher Loft register is blank, with no witness identity recorded."),
        ],
        "memory": [
            ("static_canon", "amber-flag dispatch", "temporary_authority", "Odo Prynn", 2, "amber_emergency_rider"),
            ("character_knowledge", "Odo Prynn", "revised_phrase", "Marble Six", 4, "revised_sealed_memo"),
            ("static_canon", "clear-branch bell", "cadence", "three short then one long", 5, "bell_cadence"),
            ("static_canon", "switch lever C", "tactile_binding", "violet cord", 6, "lever_binding"),
        ],
    },
    "quartz_aviary": {
        "title": "The Quartz Aviary Ledger",
        "characters": ["Elian Moss", "Pera Dune"],
        "locations": ["Starling Vault", "Indigo Roost"],
        "core_design": "aviary procedure chronology and age-bound entry exceptions",
        "chapters": [
            (1, "Dawn procedure card", "dawn_procedure_card", "The printed dawn procedure schedules seed mist before the first wing count in Starling Vault."),
            (2, "Alarm-day execution log", "alarm_day_execution_log", "On alarm day Elian Moss completed the first wing count, then released seed mist afterward because the reservoir seal was checked late."),
            (3, "Copper tag rule", "copper_tag_rule", "The aviary rule requires every glasswing bird to wear a copper ankle tag before ordinary roost entry."),
            (4, "Hatchling exception", "hatchling_exception", "A quarantine exception permits glasswing fledglings younger than three days to enter Indigo Roost untagged through the nursery hatch."),
            (5, "Vault temperature", "vault_temperature", "Pera Dune logged Starling Vault at eighteen degrees Celsius throughout the quiet watch."),
            (6, "Keeper notebook", "keeper_notebook", "Pera Dune records feeding totals in a black linen notebook kept beneath the eastern perch."),
            (7, "Blue feather intake bundle", "blue_feather_intake_bundle", "One unsigned intake label calls the blue feather an Indigo Gull feather and another calls it Sky Tern; neither label has a custody signature, and the ledger declares no source-priority rule."),
            (8, "Incubator readiness sheet", "incubator_readiness_sheet", "Incubator bay four logged heat, humidity, and the required turning cycle, but the final dawn-count result cell is blank and no hatch observation was recorded."),
        ],
        "memory": [
            ("event_timeline", "alarm-day seed mist", "actual_order", "after the first wing count", 2, "alarm_day_execution_log"),
            ("static_canon", "untagged hatchling entry", "exception", "glasswing fledglings younger than three days", 4, "hatchling_exception"),
            ("dynamic_state", "Starling Vault", "quiet_watch_temperature", "eighteen degrees Celsius", 5, "vault_temperature"),
            ("static_canon", "Pera Dune", "feeding_notebook", "black linen notebook", 6, "keeper_notebook"),
        ],
    },
    "cinder_lantern_ferry": {
        "title": "Cinder Lantern Ferry",
        "characters": ["Sora Fen", "Bram Latch"],
        "locations": ["Vesper Landing", "Ashen Channel"],
        "core_design": "storm-diverted inspection movement and interrupted crossing status",
        "chapters": [
            (1, "Beacon assignment", "beacon_assignment", "The morning assignment schedules Sora Fen to inspect the Vesper beacon after disembarking at Vesper Landing."),
            (2, "Storm movement log", "storm_movement_log", "The storm log reroutes Sora Fen to inspect the beacon repeater aboard the ferry in Ashen Channel and records that she never disembarked at Vesper Landing."),
            (3, "Crossing departure", "crossing_departure", "The Lantern Crossing opened eastbound when Bram Latch released the stern line at first light."),
            (4, "Mid-channel suspension", "mid_channel_suspension", "A cinder squall suspended the Lantern Crossing mid-channel; the ferry returned every passenger west and the eastbound passage did not complete."),
            (5, "Lantern fuel", "lantern_fuel", "Deck lanterns on the ferry burn filtered juniper oil stored in square blue tins."),
            (6, "Whistle register", "whistle_register", "Bram Latch carries a brass whistle engraved with two narrow rings."),
            (7, "Engine recovery worksheet", "engine_recovery_worksheet", "The recovery worksheet confirms that the intake screen was cleared, but it does not record whether the timing chain was reset or whether propulsion resumed after the repair."),
            (8, "Pouch receipt", "pouch_receipt", "The sealed pouch receipt has a blank recipient field; no person is recorded as accepting it."),
        ],
        "memory": [
            ("dynamic_state", "Sora Fen", "storm_inspection_location", "aboard the ferry in Ashen Channel", 2, "storm_movement_log"),
            ("event_timeline", "Lantern Crossing", "eastbound_status", "suspended and returned west", 4, "mid_channel_suspension"),
            ("static_canon", "deck lanterns", "fuel", "filtered juniper oil", 5, "lantern_fuel"),
            ("static_canon", "Bram Latch whistle", "material_and_mark", "brass with two narrow rings", 6, "whistle_register"),
        ],
    },
}


CASES: list[dict[str, Any]] = [
    # Saffron Tidehouse
    {"id":"eval-v6-lumen-conflict-counterweight-mass","corpus":"lumen_tidehouse","draft":"The current Lumen counterweight still weighs forty-two kilograms.","class":"conflict","category":"attribute","evidence":[1,2],"tags":["requires_multiple_direct_evidence","conflicting_sources","category_mismatch_regression"],"core":"lumen-accepted-counterweight-mass","shape":"retired_mass_card_replaced_by_acceptance_weighing","signature":"conflict|attribute|retired_mass_plus_acceptance_measurement","nouns":["Lumen counterweight"],"decision":"Whether a retired mass entry or a signed post-installation weighing controls the counterweight's measured property.","prior":"Earlier evaluations contain supersession patterns but not a calibrated mass changed by a physical insert.","why":"The Lumen counterweight decision joins a pre-modification balance card to a post-installation acceptance measurement, making a measured intrinsic property—not custody, schedule, or event completion—the decisive axis."},
    {"id":"eval-v6-lumen-conflict-crate-location","corpus":"lumen_tidehouse","draft":"At the post-surge audit, the Driftglass Crate is still secured in Meridian Intake rack seven.","class":"conflict","category":"object_state","evidence":[3,4],"tags":["requires_multiple_direct_evidence","conflicting_sources","category_mismatch_regression"],"core":"lumen-driftglass-post-surge-custody","shape":"pre_surge_rack_state_replaced_by_transfer_ledger","signature":"conflict|object_state|before_custody_plus_after_transfer","nouns":["Driftglass Crate","Meridian Intake"],"decision":"Where the named crate is held after a surge-triggered custody transfer.","prior":"Prior object checks do not use an emergency custody handoff between intake infrastructure and a gantry locker.","why":"The Driftglass Crate decision requires a before-state and a post-surge transfer record; it tests time-indexed custody of one named object rather than the object's material or a person's action location."},
    {"id":"eval-v6-lumen-control-impeller-cadence","corpus":"lumen_tidehouse","draft":"The north impeller at Meridian Intake repeats a nine-minute cycle.","class":"no_conflict","category":None,"evidence":[5],"tags":["supported_control"],"core":"lumen-impeller-nine-minute-cadence","shape":"directly_supported_mechanical_cycle_duration","signature":"no_conflict|supported|impeller_cadence_log","nouns":["Meridian Intake"],"decision":"Whether the draft preserves the logged cycle duration of the north impeller.","prior":"This is a direct operating-cadence control in tidal machinery, not a prior capacity, angle, or schedule scenario.","why":"The Meridian Intake control is grounded by one timing observation and asks only whether a mechanical rhythm is preserved, providing a new supported decision with no source-precedence dependency."},
    {"id":"eval-v6-lumen-control-valve-stripe","corpus":"lumen_tidehouse","draft":"The reserve sluice valve is marked by a saffron stripe.","class":"no_conflict","category":None,"evidence":[6],"tags":["supported_control"],"core":"lumen-reserve-valve-night-mark","shape":"directly_supported_tactile_visual_equipment_mark","signature":"no_conflict|supported|reserve_valve_stripe","nouns":["reserve sluice valve"],"decision":"Whether the reserve valve's night-identification mark matches the equipment record.","prior":"Prior controls do not use a tidehouse valve's visual night mark as their decision point.","why":"The reserve sluice valve check is a single-source equipment-identification control whose saffron marking is independent of all V1–V5 entities, locations, and continuity mechanisms."},
    {"id":"eval-v6-lumen-insufficient-vane-person","corpus":"lumen_tidehouse","draft":"Rina Sol signed the west-vane handover during the blackout.","class":"insufficient_evidence","category":None,"evidence":[7],"tags":["insufficient_evidence","ambiguous_evidence"],"core":"lumen-vane-handover-initials-ambiguous","shape":"ambiguous_initials_refer_to_two_roster_people","signature":"insufficient_evidence|entity_reference_ambiguity|vane_handover","nouns":["Rina Sol","Rook Sable"],"decision":"Whether the ambiguous initials R. S. in a handover note identify Rina Sol rather than Rook Sable.","prior":"Prior insufficient-evidence cases do not turn on an unresolved shared-initial reference between two named blackout-roster workers.","why":"The V6 decision is entity-reference ambiguity: the source supplies a real handover signature and two plausible roster referents, but no resolving link. It is neither a missing actor assertion nor an alternative causal account."},
    {"id":"eval-v6-lumen-insufficient-sample-destination","corpus":"lumen_tidehouse","draft":"During the surge, the route amendment already required the sealed sample to go to Nacre Pier.","class":"insufficient_evidence","category":None,"evidence":[8],"tags":["insufficient_evidence","ambiguous_evidence"],"core":"lumen-sample-route-effective-time-unknown","shape":"conditional_route_has_unrecorded_effective_time","signature":"insufficient_evidence|temporal_applicability_unknown|sample_amendment","nouns":["Nacre Pier"],"decision":"Whether a conditional route amendment applied at the surge when its calibration effective time is absent.","prior":"Prior uncertain delivery cases do not depend on the temporal applicability of a recorded conditional amendment.","why":"This is not a blank-destination case: Nacre Pier is named in the source, while the missing decision point is when that conditional route took effect. The draft asserts applicability at a specific time the record never establishes."},
    # Velvet Signal Yard
    {"id":"eval-v6-velvet-conflict-amber-authority","corpus":"velvet_signal_yard","draft":"During an amber flag, Neris Vale alone retains departure authority at Juniper Relay Yard.","class":"conflict","category":"relationship","evidence":[1,2],"tags":["requires_multiple_direct_evidence","conflicting_sources","category_mismatch_regression"],"core":"velvet-amber-departure-authority","shape":"ordinary_role_charter_overridden_by_emergency_delegation","signature":"conflict|relationship|ordinary_authority_plus_emergency_rider","nouns":["Neris Vale","Juniper Relay Yard"],"decision":"Who holds dispatch authority when an emergency rider temporarily overrides ordinary duties.","prior":"Prior relationship cases do not combine railway dispatch duties with a flag-scoped delegation override.","why":"The amber-flag decision compares baseline role authority with a bounded emergency reassignment between Neris Vale and Odo Prynn, making interpersonal authorization—not a world rule—the core relation."},
    {"id":"eval-v6-velvet-conflict-revised-phrase-knowledge","corpus":"velvet_signal_yard","draft":"Neris Vale knew the revised phrase Marble Six before the midnight dispatch.","class":"conflict","category":"character_knowledge","evidence":[3,4],"tags":["requires_multiple_direct_evidence","conflicting_sources"],"core":"velvet-neris-revised-phrase-knowledge","shape":"earlier_phrase_access_displaced_by_exclusive_revised_briefing","signature":"conflict|character_knowledge|old_phrase_plus_sealed_revision_distribution","nouns":["Neris Vale","Marble Six"],"decision":"Whether access to an earlier phrase implies knowledge of a sealed replacement sent only to another operator.","prior":"Prior knowledge boundaries do not use versioned relay phrases and exclusive sealed distribution.","why":"The Marble Six decision requires both Neris Vale's earlier Willow Nine briefing and the exclusive revised memo, testing version-specific knowledge rather than general participation or duty."},
    {"id":"eval-v6-velvet-control-bell-cadence","corpus":"velvet_signal_yard","draft":"A clear branch is announced by three short bell strokes and then one long stroke.","class":"no_conflict","category":None,"evidence":[5],"tags":["supported_control"],"core":"velvet-clear-branch-bell-cadence","shape":"directly_supported_signal_bell_sequence","signature":"no_conflict|supported|clear_branch_cadence","nouns":["Juniper Relay Yard"],"decision":"Whether the draft reproduces the yard's recorded clear-branch bell cadence.","prior":"No prior control uses an acoustic rail-yard code with this ordered stroke pattern.","why":"The clear-branch case is a direct signal-code control grounded in one operational record and is independent from chronological event-order conflicts despite containing an ordered sound sequence."},
    {"id":"eval-v6-velvet-control-violet-cord","corpus":"velvet_signal_yard","draft":"Switch lever C is wrapped with violet cord for recognition in fog.","class":"no_conflict","category":None,"evidence":[6],"tags":["supported_control"],"core":"velvet-lever-c-violet-binding","shape":"directly_supported_switch_tactile_binding","signature":"no_conflict|supported|lever_binding","nouns":["Switch lever C"],"decision":"Whether the lever's fog-recognition binding matches the yard record.","prior":"Prior visual markers do not concern a tactile binding on railway switching equipment.","why":"Switch lever C supplies a distinct supported equipment-mark decision in the Juniper Relay Yard, with no inheritance from V5 material, location, or event-status facts."},
    {"id":"eval-v6-velvet-insufficient-phantom-cause","corpus":"velvet_signal_yard","draft":"The official signal inspector ordered the phantom-aspect circuit isolated.","class":"insufficient_evidence","category":None,"evidence":[7],"tags":["insufficient_evidence","ambiguous_evidence"],"core":"velvet-phantom-advisory-authority-unverified","shape":"unsigned_advisory_asserted_as_official_inspector_order","signature":"insufficient_evidence|source_authority_unconfirmed|relay_advisory","nouns":["signal inspector"],"decision":"Whether an unsigned advisory can be attributed to an authorised inspector as an official order.","prior":"Prior uncertain-source cases do not distinguish an unsigned emergency advisory from an authorised railway inspection finding.","why":"The source supplies a recommendation but withholds provenance, authority, and official status. The V6 decision tests source legitimacy rather than an unknown physical cause or a character's private knowledge."},
    {"id":"eval-v6-velvet-insufficient-observer-name","corpus":"velvet_signal_yard","draft":"Kelm Orr witnessed the final relay test from Cipher Loft.","class":"insufficient_evidence","category":None,"evidence":[8],"tags":["insufficient_evidence","ambiguous_evidence"],"core":"velvet-final-test-observer-blank","shape":"blank_observer_register_asserted_as_named_witness","signature":"insufficient_evidence|blank_witness|relay_test","nouns":["Kelm Orr","Cipher Loft"],"decision":"Whether a blank witness line can establish a named observer at the final relay test.","prior":"Prior missing-person evidence does not use a formal rail-test observer register.","why":"The Cipher Loft case tests an unsupported witness identity in a blank register, distinct from actor responsibility, character knowledge, and role authorization decisions."},
    # Quartz Aviary
    {"id":"eval-v6-quartz-conflict-seed-mist-order","corpus":"quartz_aviary","draft":"On alarm day, seed mist was released before the first wing count in Starling Vault.","class":"conflict","category":"timeline","evidence":[1,2],"tags":["requires_multiple_direct_evidence","conflicting_sources"],"core":"quartz-alarm-day-mist-count-order","shape":"scheduled_order_displaced_by_alarm_day_execution_sequence","signature":"conflict|timeline|procedure_schedule_plus_actual_log","nouns":["Starling Vault"],"decision":"Whether the planned dawn sequence or the alarm-day execution log determines actual event order.","prior":"Prior timeline cases do not contrast an aviary procedure card with an alarm-driven execution reversal.","why":"The seed-mist decision joins planned order to observed alarm-day order, testing which of two events happened first rather than whether either event completed."},
    {"id":"eval-v6-quartz-conflict-hatchling-tag-exception","corpus":"quartz_aviary","draft":"Every glasswing, including a newly hatched fledgling, must wear a copper tag before entering any roost.","class":"conflict","category":"world_rule","evidence":[3,4],"tags":["requires_multiple_direct_evidence","conflicting_sources"],"core":"quartz-untagged-hatchling-entry-exception","shape":"global_tag_rule_bounded_by_age_specific_quarantine_exception","signature":"conflict|world_rule|general_requirement_plus_hatchling_exception","nouns":["glasswing","Indigo Roost"],"decision":"Whether a universal tag assertion survives an explicit age-bound quarantine exception.","prior":"Prior world-rule cases do not use biological age, quarantine routing, and a nursery-hatch exception.","why":"The glasswing decision requires the general copper-tag rule and the under-three-day exception, testing a system-wide norm with a scoped exemption rather than one object's state."},
    {"id":"eval-v6-quartz-control-vault-temperature","corpus":"quartz_aviary","draft":"Starling Vault remained at eighteen degrees Celsius during the quiet watch.","class":"no_conflict","category":None,"evidence":[5],"tags":["supported_control"],"core":"quartz-starling-vault-quiet-temperature","shape":"directly_supported_environmental_temperature_log","signature":"no_conflict|supported|vault_temperature","nouns":["Starling Vault"],"decision":"Whether the quiet-watch temperature agrees with the keeper's environmental log.","prior":"Prior property controls do not use a bird-vault environmental reading during a named watch.","why":"The Starling Vault case is a direct environmental measurement control and does not reuse V5's disputed material, angle, or object custody decision points."},
    {"id":"eval-v6-quartz-control-keeper-notebook","corpus":"quartz_aviary","draft":"Pera Dune keeps feeding totals in a black linen notebook beneath the eastern perch.","class":"no_conflict","category":None,"evidence":[6],"tags":["supported_control"],"core":"quartz-pera-feeding-notebook","shape":"directly_supported_keeper_recording_tool_and_storage","signature":"no_conflict|supported|keeper_notebook","nouns":["Pera Dune"],"decision":"Whether the keeper's recording tool and storage place match the aviary record.","prior":"No earlier supported case concerns a keeper's feeding ledger stored beneath a perch.","why":"Pera Dune's notebook is a new single-source supported fact combining a personal tool and its storage location without invoking an unresolved location-action claim."},
    {"id":"eval-v6-quartz-insufficient-feather-species","corpus":"quartz_aviary","draft":"The blue feather is definitively an Indigo Gull feather.","class":"insufficient_evidence","category":None,"evidence":[7],"tags":["insufficient_evidence","ambiguous_evidence","conflicting_sources"],"core":"quartz-blue-feather-unranked-source-disagreement","shape":"two_unsigned_species_labels_lack_priority_rule","signature":"insufficient_evidence|conflicting_sources_no_priority|feather_intake","nouns":["Indigo Gull","Sky Tern"],"decision":"Whether one of two conflicting unsigned species labels controls when the ledger supplies no authority or priority rule.","prior":"Prior insufficient-evidence cases do not use competing specimen labels whose conflict is unresolved by any provenance ranking.","why":"The V6 decision contains evidence on both sides, but neither label is authenticated and no priority rule exists. It therefore tests unresolved source precedence, not merely an absent species attribution."},
    {"id":"eval-v6-quartz-insufficient-incubator-result","corpus":"quartz_aviary","draft":"Because every readiness condition was logged, incubator bay four hatched twin chicks before dawn.","class":"insufficient_evidence","category":None,"evidence":[8],"tags":["insufficient_evidence","ambiguous_evidence"],"core":"quartz-incubator-readiness-not-outcome","shape":"necessary_conditions_recorded_but_final_outcome_absent","signature":"insufficient_evidence|necessary_conditions_not_sufficient|incubator_dawn_count","nouns":["Incubator bay four"],"decision":"Whether recorded heat, humidity, and turning conditions establish an unrecorded hatch outcome.","prior":"Prior outcome gaps do not distinguish known prerequisite conditions from a separately missing dawn observation.","why":"This V6 case has partial direct support for prerequisites but no observation of the asserted result. It tests the invalid leap from necessary conditions to outcome, rather than a simple blank-result assertion."},
    # Cinder Lantern Ferry
    {"id":"eval-v6-cinder-conflict-sora-inspection-place","corpus":"cinder_lantern_ferry","draft":"Sora Fen inspected the Vesper beacon while standing on Vesper Landing.","class":"conflict","category":"location_action","evidence":[1,2],"tags":["requires_multiple_direct_evidence","conflicting_sources"],"core":"cinder-sora-storm-inspection-location","shape":"scheduled_disembark_action_replaced_by_onboard_storm_action","signature":"conflict|location_action|assignment_place_plus_movement_log","nouns":["Sora Fen","Vesper Landing"],"decision":"Where Sora Fen actually performed the beacon inspection after a storm reroute.","prior":"Prior location-action cases do not combine a shore assignment with an onboard repeater inspection and explicit non-disembarkation.","why":"Sora Fen's case needs the planned landing task and the storm movement log to locate her actual action, distinguishing action place from the ferry's own object state."},
    {"id":"eval-v6-cinder-conflict-crossing-completion","corpus":"cinder_lantern_ferry","draft":"The Lantern Crossing completed its eastbound passage after departing at first light.","class":"conflict","category":"event_status","evidence":[3,4],"tags":["requires_multiple_direct_evidence","conflicting_sources"],"core":"cinder-lantern-crossing-completion-status","shape":"opened_departure_followed_by_midchannel_suspension_and_return","signature":"conflict|event_status|departure_plus_noncompletion_log","nouns":["Lantern Crossing"],"decision":"Whether departure establishes completion when a later log records suspension and return.","prior":"Prior event-status cases do not use a ferry passage that opens, reverses mid-channel, and returns every passenger.","why":"The Lantern Crossing decision separates event initiation from completion by requiring both the departure and suspension records; it is not merely an ordering question."},
    {"id":"eval-v6-cinder-control-lantern-fuel","corpus":"cinder_lantern_ferry","draft":"The ferry's deck lanterns burn filtered juniper oil from square blue tins.","class":"no_conflict","category":None,"evidence":[5],"tags":["supported_control"],"core":"cinder-deck-lantern-juniper-fuel","shape":"directly_supported_vessel_lantern_fuel_and_container","signature":"no_conflict|supported|deck_lantern_fuel","nouns":["deck lanterns"],"decision":"Whether the stated lantern fuel and container match the ferry inventory.","prior":"Earlier controls do not concern vessel lighting fuel stored in square tins.","why":"The ferry lantern case is a new inventory-supported control with no chronology, exception, or uncertain attribution component."},
    {"id":"eval-v6-cinder-control-bram-whistle","corpus":"cinder_lantern_ferry","draft":"Bram Latch carries a brass whistle engraved with two narrow rings.","class":"no_conflict","category":None,"evidence":[6],"tags":["supported_control"],"core":"cinder-bram-brass-whistle-mark","shape":"directly_supported_personal_signal_tool_description","signature":"no_conflict|supported|bram_whistle","nouns":["Bram Latch"],"decision":"Whether Bram Latch's whistle description agrees with the vessel register.","prior":"No prior supported decision uses a ferry officer's engraved brass signal tool.","why":"Bram Latch's whistle supplies an independent person-equipment control with a distinctive material and engraving, not a disputed intrinsic-property case."},
    {"id":"eval-v6-cinder-insufficient-engine-knock-cause","corpus":"cinder_lantern_ferry","draft":"After the intake screen was cleared, the ferry's timing chain was reset and propulsion resumed.","class":"insufficient_evidence","category":None,"evidence":[7],"tags":["insufficient_evidence","ambiguous_evidence"],"core":"cinder-recovery-partial-repair-compound-claim","shape":"one_repair_step_confirmed_but_remaining_steps_and_result_missing","signature":"insufficient_evidence|partial_compound_claim|engine_recovery","nouns":["timing chain","propulsion"],"decision":"Whether confirmation of one repair step establishes a compound claim about a second repair and resumed propulsion.","prior":"Prior insufficient-evidence cases do not split a repair narrative into one recorded prerequisite and two unrecorded completion claims.","why":"The V6 source directly confirms screen clearing, while timing-chain reset and propulsion resumption remain unrecorded. This tests partial evidence for a compound operational claim, not an unknown cause or a blank outcome field."},
    {"id":"eval-v6-cinder-insufficient-pouch-recipient","corpus":"cinder_lantern_ferry","draft":"Mara Venn accepted the sealed pouch at the end of the watch.","class":"insufficient_evidence","category":None,"evidence":[8],"tags":["insufficient_evidence","ambiguous_evidence"],"core":"cinder-sealed-pouch-recipient-blank","shape":"blank_receipt_recipient_asserted_as_named_person","signature":"insufficient_evidence|blank_recipient|sealed_pouch","nouns":["Mara Venn"],"decision":"Whether a receipt with no recipient can support naming a person who accepted the pouch.","prior":"Prior blank records do not concern chain-of-custody acceptance aboard a ferry.","why":"The sealed-pouch decision targets unsupported recipient identity in a custody receipt, distinct from the unknown actor, witness, and destination decisions elsewhere in V6."},
]


def fixture_payload(key: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "scc-evaluation-only-corpus-v1",
        "corpus_key": key,
        "title": spec["title"],
        "evaluation_only": True,
        "production_seed": False,
        "protected_asset_source": False,
        "generation": {"method": "deterministic_original", "generator_version": "v6-candidate-1", "source_inputs": []},
        "lineage": {"work_title": spec["title"], "characters": spec["characters"], "locations": spec["locations"], "core_design": spec["core_design"]},
        "chapters": [{"chapter_number": n, "title": title, "source_label": label, "body": body} for n, title, label, body in spec["chapters"]],
        "memory": [
            {"memory_type": memory_type, "subject": subject, "predicate": predicate, "value": value, "source": {"chapter_number": chapter_number, "source_label": source_label}}
            for memory_type, subject, predicate, value, chapter_number, source_label in spec["memory"]
        ],
    }


def case_payload(raw: dict[str, Any], fixtures: dict[str, dict[str, Any]]) -> dict[str, Any]:
    chapters = {chapter["chapter_number"]: chapter for chapter in fixtures[raw["corpus"]]["chapters"]}
    evidence = [
        {"chapter_number": number, "source_label": chapters[number]["source_label"], "body_sha256": body_sha256(chapters[number]["body"])}
        for number in raw["evidence"]
    ]
    expected_class = raw["class"]
    is_conflict = expected_class == "conflict"
    rubric = {
        "decision_rule": raw["decision"],
        "expected_class_reason": "The complete direct source set contradicts the draft." if is_conflict else ("The cited source directly supports the draft." if expected_class == "no_conflict" else "The source explicitly leaves the asserted specific fact unknown, blank, pending, or unconfirmed."),
        "expected_category_reason": f"The decision axis is {raw['category']} under the declared category boundary." if is_conflict else "No conflict category is assigned to this class.",
        "minimum_direct_evidence": len(evidence) if is_conflict else 0,
        "requires_full_expected_evidence": is_conflict,
        "forbidden_inference": "Do not decide from one half of the paired source context." if is_conflict else ("Do not invent a conflict when the source supports the claim." if expected_class == "no_conflict" else "Do not convert explicit uncertainty into no_conflict or conflict."),
    }
    return {
        "case_id": raw["id"],
        "corpus_key": raw["corpus"],
        "seed_key": raw["corpus"],
        "target_draft": raw["draft"],
        "target_claim_ordinal": 1,
        "expected_class": expected_class,
        "expected_category": raw["category"],
        "expected_severity": ["medium", "high"] if is_conflict else (None if expected_class == "no_conflict" else ["low", "medium"]),
        "expected_evidence": evidence,
        "source_lineage": [{"corpus_key": raw["corpus"], **item} for item in evidence],
        "requires_multiple_direct_evidence": is_conflict,
        "challenge_tags": raw["tags"],
        "retrieval_difficulty": "nearby_distractor",
        "core_fact_key": raw["core"],
        "claim_shape": raw["shape"],
        "decision_signature": raw["signature"],
        "proper_nouns": raw["nouns"],
        "rubric": rubric,
    }


def build(*, rewrite_candidate: bool = False) -> dict[str, Any]:
    output_paths = [CASE_PATH, CORPUS_MANIFEST_PATH, MANIFEST_PATH, REVIEW_PATH, PLAN_PATH, *(FIXTURES / f"eval-v6-{key.replace('_', '-')}.json" for key in CORPORA)]
    if not rewrite_candidate and any(path.exists() for path in output_paths):
        raise RuntimeError("v6_candidate_asset_target_exists")
    if rewrite_candidate and not all(path.exists() for path in output_paths):
        raise RuntimeError("v6_candidate_rewrite_requires_complete_existing_candidate")
    fixtures = {key: fixture_payload(key, spec) for key, spec in CORPORA.items()}
    fixture_paths: dict[str, pathlib.Path] = {}
    for key, payload in fixtures.items():
        path = FIXTURES / f"eval-v6-{key.replace('_', '-')}.json"
        write_once(path, payload, rewrite_candidate=rewrite_candidate)
        fixture_paths[key] = path
    corpus_manifest = {
        "schema_version": "scc-evaluation-only-corpus-manifest-v1",
        "evaluation_only": True,
        "production_seed": False,
        "protected_asset_source": False,
        "files": [{"corpus_key": key, "path": f"evaluation/fixtures/{path.name}", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for key, path in fixture_paths.items()],
        "canonical_sha256": canonical_sha256([{key: fixtures[key]} for key in fixtures]),
    }
    write_once(CORPUS_MANIFEST_PATH, corpus_manifest, rewrite_candidate=rewrite_candidate)
    cases = [case_payload(raw, fixtures) for raw in CASES]
    case_set = {
        "schema_version": "scc-eval-case-set-v6-candidate",
        "status": "candidate_for_controller_review",
        "evaluation_only": True,
        "production_seed": False,
        "protected_asset_source": False,
        "formal_run_executed": False,
        "provider_calls": 0,
        "cases": cases,
    }
    write_once(CASE_PATH, case_set, rewrite_candidate=rewrite_candidate)
    review = {
        "schema_version": "scc-eval-v6-semantic-review-v1",
        "review_scope": "pending_controller_review",
        "status": "candidate_for_controller_review",
        "formal_run_executed": False,
        "provider_calls": 0,
        "structural_validation_note": "Automated checks establish structure, lineage, quotas, prior-set separation, decision-signature novelty, and hash integrity; the controller must independently judge semantic labels and non-isomorphism.",
        "entries": [
            {"case_id": raw["id"], "corpus_key": raw["corpus"], "decision_point": raw["decision"], "prior_archetype_reference": raw["prior"], "why_independent": raw["why"], "same_decision_point": None, "review_status": "pending_controller_review"}
            for raw in CASES
        ],
    }
    write_once(REVIEW_PATH, review, rewrite_candidate=rewrite_candidate)
    v5_manifest = json.loads(V5_MANIFEST_PATH.read_text(encoding="utf-8"))
    selected = [
        "eval-v6-lumen-conflict-counterweight-mass",
        "eval-v6-quartz-control-vault-temperature",
        "eval-v6-cinder-insufficient-engine-knock-cause",
    ]
    plan = {
        "schema_version": "scc-eval-v6-first-formal-plan-v1",
        "status": "not_run",
        "formal_run_executed": False,
        "provider_calls": 0,
        "controller_candidate_gate_passed": False,
        "real_provider_authorization_received": False,
        "preconditions": ["controller independently accepts the V6 candidate Gate", "user separately and explicitly authorizes real Provider calls", "candidate assets are frozen to new approved formal paths without content changes"],
        "planned_input_paths": {"case_set": "evaluation/case_sets/eval-set-v6.json", "manifest": "evaluation/manifests/eval-set-v6-manifest.json", "corpus_manifest": "evaluation/fixtures/eval-v6-corpus-manifest.json"},
        "planned_output_paths": {key: f"evaluation/results/eval-v6-first-formal-{suffix}" for key, suffix in {"checkpoint":"checkpoint.json","results":"results.json","report":"report.md","bad_cases":"bad-cases.json","stability":"stability.json","run_manifest":"run-manifest.json","api_scan":"api-corpus-scan.json"}.items()} | {"post_run_integrity": "evaluation/results/v6-first-formal-post-run-integrity.json"},
        "bad_case_protocol": {"capture_when": ["classification mismatch", "category mismatch", "threshold contributor failure", "terminal failure", "retrieval miss", "unresolvable or non-expected citation", "incomplete expected Evidence recall", "incomplete multi-direct Evidence set"], "merge_failure_dimensions_per_case": True, "sanitized_fields_only": True, "raw_provider_body_retained": False, "chain_of_thought_retained": False},
        "stability_protocol": {"representative_case_ids": selected, "class_coverage": ["conflict", "no_conflict", "insufficient_evidence"], "independent_runs_per_case": 3, "first_formal_runs_included": 3, "additional_calls_after_formal": 6, "execution_status": "not_run", "terminal_failure_quality_stability": False},
        "execution_note": "Candidate plan only. No V6 formal input, result, checkpoint, report, Bad Case, stability, run manifest, API scan, workspace, or integrity artifact exists.",
    }
    write_once(PLAN_PATH, plan, rewrite_candidate=rewrite_candidate)
    manifest = {
        "manifest_version": "scc-eval-manifest-v6-candidate",
        "status": "candidate_for_controller_review",
        "case_set": {"path": "evaluation/case_sets/eval-set-v6-candidate.json", "canonical_sha256": canonical_sha256(case_set), "case_count": 24, "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8}, "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2}},
        "stability_protocol": {"representative_case_ids": selected, "independent_runs_per_case": 3, "first_formal_runs_included_per_case": 1, "additional_calls_after_formal": 6, "execution_status": "not_run", "terminal_failure_quality_stability": False},
        "scoring": v5_manifest["scoring"],
        "required_thresholds": v5_manifest["required_thresholds"],
        "fixture_corpus": {"path": "evaluation/fixtures/eval-v6-corpus-manifest.json", "canonical_sha256": corpus_manifest["canonical_sha256"], "evaluation_only": True, "production_seed": False, "protected_asset_source": False},
        "formal_run_plan": {"path": "evaluation/manifests/eval-v6-first-formal-plan.json", "status": "not_run"},
        "boundaries": {"evaluation_only": True, "production_seed": False, "protected_asset_source": False, "formal_run_executed": False, "provider_calls": 0, "real_provider_authorization": False, "controller_candidate_gate_passed": False, "deployment": False, "ui_change": False},
        "runtime_mode": "evaluation_fixture",
        "formal_run_executed": False,
        "provider_calls": 0,
    }
    write_once(MANIFEST_PATH, manifest, rewrite_candidate=rewrite_candidate)
    return {"case_count": len(cases), "corpus_count": len(fixtures), "case_canonical_sha256": canonical_sha256(case_set), "corpus_canonical_sha256": corpus_manifest["canonical_sha256"], "formal_run_executed": False, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rewrite-v6-candidate", action="store_true", help="Rewrite only the complete mutable V6 candidate bundle; never formal inputs or results.")
    args = parser.parse_args()
    print(json.dumps(build(rewrite_candidate=args.rewrite_v6_candidate), ensure_ascii=False, indent=2))
