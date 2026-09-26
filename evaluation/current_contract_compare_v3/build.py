"""Create-only V3 gold metadata over immutable V2 stories and business inputs."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
V2 = HERE.parent / "current_contract_compare_v2"

# Classify the *insufficient assertion*, not its neighboring conflict axis.
# These categories follow the core-decision definitions in provider.py.
INSUFFICIENT_CATEGORY = {
    "world_rule": ("object_state", "The unknown 11点 holder of a named badge is the object's time-specific holder state."),
    "object_state": ("relationship", "The missing fact is Mira's responsibility for loosening the cap, not whether the cap is loose."),
    "timeline": ("relationship", "Sera's named authorization for reopening is an authority relation; the reopening time is context."),
    "character_knowledge": ("relationship", "The unknown courier is a named person's delivery role/responsibility; Sera's learning is context, not the decision."),
    "relationship": ("timeline", "Whether Nera was born before Oren is birth-event ordering; twin kinship is context."),
    "event_status": ("relationship", "The unknown cause attributed to Tala is named responsibility for the delay, not whether launch completed."),
    "attribute": ("relationship", "Who ground lens R4 is named responsibility for work; R4's material is context, not an intrinsic-property question."),
    "location_action": ("location_action", "Who accompanied Vela during the 19点 move concerns an action at a location; companion-role relationship is also plausible and requires human adjudication."),
}

INSUFFICIENT_SCOPE = {
    "world_rule": "The 11点 holder field is blank; the 10点 red-badge encounter is background only.",
    "object_state": "The 10点 inspection records a loose cap; it does not name the actor who loosened it.",
    "timeline": "The 11点 log leaves reopening and operator unrecorded; it cannot establish Sera's authorization.",
    "character_knowledge": "The 13点 learning is recorded, but the same source does not identify the courier.",
    "relationship": "The permanent twin register does not record which birth occurred first.",
    "event_status": "The 10点 delay is recorded, while its cause and Tala's responsibility are unrecorded.",
    "attribute": "The R4 maintenance sheet has a blank grinder field; the 18点 lens identity is background.",
    "location_action": "The 19点 move is recorded, but its companion field is unnamed.",
}


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    source = json.loads((V2 / "cases.json").read_text(encoding="utf-8"))
    corpora = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in (V2 / "corpora").glob("*.json")}
    cases = copy.deepcopy(source["cases"])
    for case in cases:
        axis = case["decision_category"]
        old_id = case["case_id"]
        case["case_id"] = old_id.replace("ccv2-", "ccv3-", 1)
        case["lineage"]["v2_case_id"] = old_id
        case["lineage"]["change_from_v2"] = "gold_minimum_or_category_or_metadata_only"
        old_scope = case.pop("time_scope")
        case["axis_time_context"] = old_scope
        source_lookup = {x["chapter_number"]: x["body"] for x in corpora[case["corpus_key"]]["chapters"]}
        case["case_time_scope"] = {
            "draft": case["target_draft"],
            "minimum_source_texts": [source_lookup[x["chapter_number"]] for x in case["minimum_sufficient_evidence_sets"][0]],
            "note": INSUFFICIENT_SCOPE[axis] if case["expected_class"] == "insufficient_evidence" else
                    ("Same-time contradiction or timeless rule is described by the draft and minimum source texts above."
                     if case["expected_class"] == "conflict" else
                     "The control's stated time or transition is read against its cited source texts above."),
        }
        case["category_axis"] = axis
        if case["expected_class"] == "insufficient_evidence":
            category, reason = INSUFFICIENT_CATEGORY[axis]
            case["decision_category"] = category
            case["category_reason"] = reason
            case["category_policy"] = "manual_variant" if axis == "location_action" else "fixed"
            case["category_candidates"] = ["location_action", "relationship"] if axis == "location_action" else [category]
        else:
            case["category_reason"] = "The conflict or compatible control retains the independently reviewed axis category."
            case["category_policy"] = "fixed"
            case["category_candidates"] = [axis]
        if old_id == "ccv2-north_glass-world_rule-conflict":
            rule, roster = case["minimum_sufficient_evidence_sets"][0]
            case["minimum_sufficient_evidence_sets"] = [[rule]]
            case["recommended_context"] = [roster]
            case["expected_evidence"] = [rule]
            case["requires_all_expected_evidence"] = False
            case["label_reason"] = ("The draft itself says Mira wore only a red badge at 10点; the blue-only door rule alone contradicts her claimed opening. "
                                    "The same-time roster confirms her badge and is optional corroboration.")
    return {"schema_version": "current-contract-compare-v3", "status": "seen_development_candidate",
            "evaluation_only": True, "real_provider_calls": 0,
            "v2_cases_sha256": sha(V2 / "cases.json"),
            "v2_capture_sha256": sha(V2 / "actual-inputs.json"),
            "v2_saved_api_sha256": sha(V2 / "api-score-probe-results-v2.json"),
            "business_inputs_changed": False, "cases": cases}


if __name__ == "__main__":
    with (HERE / "cases.json").open("x", encoding="utf-8") as handle:
        json.dump(build(), handle, ensure_ascii=False, indent=2)
