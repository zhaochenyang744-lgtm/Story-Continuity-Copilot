"""Build an evaluation-only, seen comparison set from original synthetic stories."""
from __future__ import annotations

import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# Each axis is one close triplet: contradicted draft, supported control, and
# assertion for which the source explicitly lacks the decisive fact.
WORKS = [
    ("north_glass", "The North Glass Exchange", [
        ("world_rule", "Mira", [
            ("badge_rule", "The North Glass door opens only for a wearer of a blue badge; a red badge cannot open it.", "static_canon", "rule"),
            ("badge_roster", "At 10点 on the same day, Mira tried the North Glass door while wearing only a red badge and carrying no blue badge; the roster does not record whether it opened.", "dynamic_state", "status"),
            ("spare_register", "The spare blue badge register leaves its 11点 holder field blank.", "open_thread", "status"),
        ], "At 10点 on the same day, Mira opened the North Glass door while wearing only her red badge.", "At 10点 on the same day, Mira could not open North Glass with her only red badge.", "Mira held the spare blue badge at 11点, according to the two badge registers.", [1, 2], [1, 2], [2, 3], "The blue-only rule and Mira's red-only badge at the same 10点 jointly rule out her opening; neither source alone identifies both the rule and Mira's badge."),
        ("object_state", "pneumatic carrier", [
            ("carrier_ready_rule", "A North Glass pneumatic carrier is ready for dispatch only when its pressure gauge reads four bars and its valve cap is locked.", "static_canon", "rule"),
            ("carrier_inspection", "At 10点 on the same day, the North Glass pneumatic carrier gauge read four bars, but its valve cap remained loose and not locked throughout that minute.", "dynamic_state", "status"),
            ("cap_actor", "The carrier inspection does not record who loosened its valve cap.", "open_thread", "status"),
        ], "At 10点 on the same day, the North Glass pneumatic carrier was ready for dispatch.", "At 10点 on the same day, the North Glass pneumatic carrier was not ready despite its four-bar gauge.", "Mira loosened the carrier valve cap, according to the inspection and cap record.", [1, 2], [1, 2], [2, 3], "The dispatch rule and same-minute loose-cap inspection jointly exclude ready status."),
    ]),
    ("harbor_signal", "The Harbor Signal Ledger", [
        ("timeline", "harbor signal gate", [
            ("gate_log", "At 09点 on the same day, the harbor signal gate first opened and had never closed before then. At 10点 on that day, it first closed after opening.", "event_timeline", "event_occurred"),
            ("reopen_log", "The 11点 harbor signal gate log leaves any reopening and its operator unrecorded.", "open_thread", "status"),
        ], "At 09点 on the same day, the harbor signal gate first closed before it first opened.", "The gate logs establish that at 10点 the harbor signal gate first closed after its 09点 opening.", "The gate logs establish that Sera authorized a reopening at 11点.", [1], [1], [2], "The same-day log establishes first opening before first closing; a claimed first closing before opening reverses the event order."),
        ("character_knowledge", "Sera", [
            ("telegram_seal", "At 11点 on the same day, Sera had not opened the sealed telegram and did not know its code.", "character_knowledge", "knowledge"),
            ("later_recipient", "At 13点 Sera opened the telegram and learned its code, but the record does not identify who delivered it.", "event_timeline", "knowledge"),
        ], "At 11点 on the same day, Sera knew the telegram code.", "At 13点 Sera learned the telegram code after not knowing it at 11点.", "Vela delivered the telegram to Sera at 13点, according to the records.", [1], [1, 2], [1, 2], "The 11点 narrator record directly contradicts knowledge; the 13点 later transition is legitimate, while the messenger remains unknown."),
    ]),
    ("orchard_restoration", "The Orchard Restoration Register", [
        ("relationship", "Nera and Oren", [
            ("kinship_rule", "The Orchard Register's permanent kinship rule says that two people recorded as twins cannot be one another's parent.", "static_canon", "rule"),
            ("twin_register", "The birth register identifies Nera and Oren as twins, both children of Tala.", "static_canon", "relationship"),
            ("birth_order", "The birth register does not record which twin, Nera or Oren, was born first.", "open_thread", "status"),
        ], "Nera is Oren's mother.", "Nera lied, ‘I am Oren's mother,’ while the register records them as twins.", "The birth register establishes that Nera was born before Oren.", [1, 2], [1, 2], [3], "The actual permanent kinship rule plus twin registry jointly rule out Nera being Oren's mother; twin birth order remains unrecorded."),
        ("event_status", "restoration boat", [
            ("launch_rule", "The restoration boat's launch is complete only after both its manifest is signed and the boat departs the orchard quay.", "static_canon", "rule"),
            ("launch_log", "At 10点 on the same day, the restoration boat manifest remained unsigned and the boat remained at the orchard quay throughout that minute without departing.", "event_timeline", "event_occurred"),
            ("delay_cause", "The restoration log leaves the cause of the boat's delay unrecorded.", "open_thread", "status"),
        ], "At 10点 on the same day, the restoration boat had completed its launch.", "At 10点 on the same day, the restoration boat had not completed launch while its manifest was unsigned and it remained at the quay.", "Tala caused the restoration boat's delay, according to the launch and delay logs.", [1, 2], [1, 2], [2, 3], "The launch completion rule and the same-minute unsigned/no-departure log jointly exclude completed launch."),
    ]),
    ("basalt_observatory", "The Basalt Observatory Journal", [
        ("attribute", "lens R4", [
            ("lens_index", "At 18点 on the same day, the observatory index identifies lens R4 as the installed western aperture lens.", "dynamic_state", "identity"),
            ("west_lens", "At 18点 on the same day, the western aperture lens is clear glass, not amber glass.", "dynamic_state", "status"),
            ("grinder_blank", "The western lens R4 maintenance sheet leaves the glass grinder's name blank.", "open_thread", "status"),
        ], "At 18点 on the same day, lens R4 is amber glass.", "At 18点 lens R4 is clear glass; Vela recalls that it looked amber yesterday.", "The index and maintenance sheet establish that Vela ground lens R4.", [1, 2], [1, 2], [1, 3], "Two same-time observations bind R4 to the western lens and identify its material as clear glass."),
        ("location_action", "Vela", [
            ("gate_map", "Observatory Gate Four stands on the west pier, not the east pier.", "static_canon", "location"),
            ("watch_log", "At 18点 on the same day, Vela stood at Observatory Gate Four on the west pier, not the east pier.", "dynamic_state", "location"),
            ("later_watch", "At 19点 Vela moved from Gate Four on the west pier to the east pier; the watch record leaves her companion unnamed.", "event_timeline", "location"),
        ], "At 18点 on the same day, Vela stood on the east pier.", "At 19点 Vela moved from Gate Four on the west pier to the east pier.", "The 19点 watch record establishes that Sora accompanied Vela to the east pier.", [2], [3], [3], "The direct 18点 watch record places Vela at Gate Four on the west pier; the 19点 move is a legitimate later transition."),
    ]),
]

INSUFFICIENT_REASONS = {
    "world_rule": "The 10点 roster concerns Mira's red badge, while the 11点 spare-badge holder field is blank. Neither record identifies Mira as the later holder; this draft specifically claims the records establish that identity.",
    "object_state": "The inspection establishes the loose cap, while the actor field is unrecorded. Neither source attributes the loosening to Mira.",
    "timeline": "The 09点 opening and 10点 closing do not establish an 11点 reopening or its authorizer; the 11点 field explicitly leaves both unknown.",
    "character_knowledge": "The 11点 ignorance and 13点 learning fix Sera's knowledge transition, but neither identifies the courier. The draft asserts that the existing records establish Vela's role.",
    "relationship": "The twin register fixes kinship but explicitly leaves birth order blank; firstborn status cannot be inferred from twins being listed in that order.",
    "event_status": "The unsigned launch log establishes an incomplete launch and a delay, but the cause log leaves responsibility unrecorded. There is no source link to Tala.",
    "attribute": "The index links R4 to the western lens, while the maintenance sheet omits the grinder's name. The claimed recorded attribution to Vela lacks the identity link.",
    "location_action": "The 19点 move is established, but the same watch record leaves the companion unnamed. It does not identify Sora.",
}

# These are declared gold alternatives, not a claim that code can decide freeform
# narrative truth. The five two-source insufficiency rows need only their explicit
# unknown-field source; the other source is useful background, not a second minimum.
BACKGROUND_ONLY_INSUFFICIENT = {"world_rule", "object_state", "character_knowledge", "event_status", "attribute"}
STATE_CHANGE_CONTROLS = {"character_knowledge", "location_action"}
TIME_SCOPE = {
    "world_rule": "The rule applies without an expiry; Mira's badge and claimed opening are both at 10点 on the same day.",
    "object_state": "The rule applies without an expiry; the cap inspection and claimed ready status are both at 10点 on the same day.",
    "timeline": "Opening and first closing are ordered within the same day; the conflict refers to 09点.",
    "character_knowledge": "Knowledge at 11点 and learning at 13点 are distinct same-day states.",
    "relationship": "The permanent kinship rule and twin register concern the same pair without a time change.",
    "event_status": "The completion rule applies without an expiry; unsigned manifest, no departure, and claimed completion are at 10点 on the same day.",
    "attribute": "The R4 identity and glass observation are both at 18点 on the same day.",
    "location_action": "The 18点 west location and 19点 east move are different same-day states.",
}


def build() -> tuple[list[dict], list[dict]]:
    corpora, cases = [], []
    for key, title, axes in WORKS:
        chapters, memory = [], []
        for axis_index, axis in enumerate(axes):
            category, subject, sources, conflict, control, insufficient, conflict_refs, control_refs, insufficient_refs, rationale = axis
            positions = []
            for label, body, memory_type, predicate in sources:
                number = len(chapters) + 1
                chapters.append({"chapter_number": number, "title": label.replace("_", " ").title(),
                                 "source_label": label, "body": body})
                memory.append({"memory_type": memory_type, "subject": subject, "predicate": predicate,
                               "value": body, "source": {"chapter_number": number, "source_label": label}})
                positions.append(number)
            for label, draft, refs in (("conflict", conflict, conflict_refs), ("no_conflict", control, control_refs),
                                        ("insufficient_evidence", insufficient, insufficient_refs)):
                required = [positions[i - 1] for i in refs]
                minimum = required
                optional = []
                if label == "insufficient_evidence" and category in BACKGROUND_ONLY_INSUFFICIENT:
                    minimum, optional = [required[-1]], required[:-1]
                if label == "no_conflict" and category == "location_action":
                    # The 19点 move itself is sufficient; the 18点 west watch
                    # record may also be cited as genuine prior-state context.
                    minimum, optional = [required[-1]], [positions[1]]
                ident = f"ccv2-{key}-{category}-{label}"
                evidence_at = lambda n: {"chapter_number": n, "source_label": chapters[n-1]["source_label"],
                                         "body_sha256": sha(chapters[n-1]["body"])}
                allowed = (["confirmed_conflict"] if label == "conflict" else
                           ["insufficient_evidence"] if label == "insufficient_evidence" else
                           ["no_issue", "state_change"] if category in STATE_CHANGE_CONTROLS else ["no_issue"])
                cases.append({"case_id": ident, "corpus_key": key, "target_draft": draft,
                              "target_claim_ordinal": 1, "expected_class": label,
                              "expected_category": category if label == "conflict" else None,
                              "decision_category": category,
                              "expected_nature": "confirmed_conflict" if label == "conflict" else ("none" if label == "no_conflict" else "insufficient_evidence"),
                              "expected_evidence": [evidence_at(n) for n in required],
                              "minimum_sufficient_evidence_sets": [[evidence_at(n) for n in minimum]],
                              "recommended_context": [evidence_at(n) for n in optional],
                              "allowed_outcomes": allowed,
                              "evidence_relation": "contradicts" if label == "conflict" else ("context" if label == "insufficient_evidence" else "supports"),
                              "evidence_sufficiency": "insufficient" if label == "insufficient_evidence" else "sufficient",
                              "time_scope": TIME_SCOPE[category],
                              "lineage": {"v1_case_id": ident.replace("ccv2-", "ccv1-"),
                                          "change": "revised_same_time_premise" if category in {"world_rule", "object_state", "event_status"} else
                                          "revised_scoring_or_context"},
                              "requires_all_expected_evidence": label == "conflict" and len(required) > 1,
                              "temporal_policy": "same_explicit_time" if category in {"timeline", "character_knowledge", "location_action", "attribute"} and label == "conflict" else ("timeless_rule" if category in {"world_rule", "object_state", "event_status", "relationship"} and label == "conflict" else "not_required"),
                              "label_reason": rationale if label == "conflict" else ("The cited sources and current draft permit this close control without a contradiction." if label == "no_conflict" else INSUFFICIENT_REASONS[category]),
                              "forbidden_inference": "Do not infer a new fact from an empty, pending or unrecorded field." if label == "insufficient_evidence" else "Do not erase time or source attribution.",
                              "axis_index": axis_index + 1, "seen_development": True})
        corpora.append({"schema_version": "scc-evaluation-only-corpus-v1", "corpus_key": key,
                        "title": title, "evaluation_only": True, "production_seed": False,
                        "protected_asset_source": False,
                        "generation": {"method": "synthetic_current_contract_adaptation", "generator_version": "current-contract-compare-v2",
                                       "source_inputs": ["evaluation/case_sets/eval-set-v8-candidate.json"],
                                       "lineage_note": "New works and wording; challenge shapes adapted from the seen V8 candidate. This set is exposed development material."},
                        "chapters": chapters, "memory": memory})
    return corpora, cases


def write_new(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def main() -> None:
    corpora, cases = build()
    for corpus in corpora:
        write_new(HERE / "corpora" / f"{corpus['corpus_key']}.json", corpus)
    write_new(HERE / "cases.json", {"schema_version": "current-contract-compare-v2", "status": "seen_development_candidate",
                                     "evaluation_only": True, "real_provider_calls": 0, "cases": cases})


if __name__ == "__main__":
    main()
