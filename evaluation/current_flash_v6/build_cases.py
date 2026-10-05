"""Build 24 preserved comparison inputs plus 10 deduplicated V6 controls."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
CONTROL = ROOT / "docs/flash-v6-independent-acceptance-evidence/semantics/control-matrix.json"
V5_CASES = ROOT / "evaluation/current_flash_v5/cases.json"
ADAPTATION = HERE / "INPUT-ADAPTATION.md"
LENS_EXTRA = {"id": "L4", "body": "At 14:00 today, lens Q8 was logged for routine cleaning. The note does not identify its installed aperture or material."}


def write_x(path: pathlib.Path, payload: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def controls() -> dict:
    return json.loads(CONTROL.read_text(encoding="utf-8"))


def corpus(fixture_key: str, fixture: dict) -> dict:
    sources = list(fixture["sources"])
    if fixture_key == "lens":
        sources.append({**LENS_EXTRA, "body_sha256_raw_utf8": hashlib.sha256(LENS_EXTRA["body"].encode("utf-8")).hexdigest()})
    by_id = {item["id"]: (index, item) for index, item in enumerate(sources, 1)}
    if len(by_id) != len(sources):
        raise ValueError("duplicate_v6_source")
    chapters = []
    for index, source in enumerate(sources, 1):
        body = source["body"]
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != source["body_sha256_raw_utf8"]:
            raise ValueError("v6_source_body_hash_drift")
        chapters.append({"chapter_number": index, "title": f"Synthetic {fixture_key} source {source['id']}",
                         "source_label": source["id"], "body": body})
    memories = []
    source_memory = list(fixture.get("memory", []))
    if fixture_key == "lens":
        source_memory.append({"source_id": "L4", "value": LENS_EXTRA["body"]})
    elif not source_memory:
        source_memory.append({"source_id": sources[0]["id"], "value": sources[0]["body"]})
    for item in source_memory:
        index, source = by_id[item["source_id"]]
        if item["value"] != source["body"]:
            raise ValueError("v6_memory_source_body_mismatch")
        memories.append({"memory_type": "dynamic_state", "subject": fixture_key,
                         "predicate": "identity" if item["source_id"] == "L1" else "status",
                         "value": item["value"], "source": {"chapter_number": index,
                             "source_label": item["source_id"]}})
    return {"schema_version": "scc-evaluation-only-corpus-v1", "corpus_key": "v6_" + fixture_key,
            "title": "V6 synthetic " + fixture_key, "evaluation_only": True,
            "production_seed": False, "protected_asset_source": False,
            "generation": {"method": "v6_control_matrix_exact_source_body",
                           "control_matrix_sha256": sha(CONTROL), "input_adaptation_sha256": sha(ADAPTATION),
                           "classification": "seen_development"},
            "chapters": chapters, "memory": memories}


def build() -> dict:
    matrix = controls()
    if matrix["control_count"] != 12 or matrix["unique_business_input_count"] != 10:
        raise ValueError("v6_control_count_drift")
    old = json.loads(V5_CASES.read_text(encoding="utf-8"))["cases"]
    comparison = [{**item, "evaluation_kind": "preserved_v5_comparison",
                   "source_case_id": item["case_id"]} for item in old if item["family"] == "comparison"]
    if len(comparison) != 24:
        raise ValueError("v6_old_case_count_drift")
    seen: dict[tuple[str, str], dict] = {}
    for control in matrix["controls"]:
        fixture = control["fixture"]
        if fixture not in matrix["fixtures"]:
            raise ValueError("v6_control_fixture_unknown")
        key = (fixture, control["draft"])
        if key not in seen:
            seen[key] = {"ordinal": len(comparison) + len(seen) + 1, "family": "comparison",
                         "evaluation_kind": "v6_seen_control", "case_id": "v6-" + control["id"].lower(),
                         "corpus_key": "v6_" + fixture, "fixture_key": fixture,
                         "saved_draft": control["draft"], "control_ids": [],
                         "selected_source_labels": (["L1", "L2", "L4"] if fixture == "lens" else
                                                    matrix["fixtures"][fixture]["selected_source_ids"])}
        seen[key]["control_ids"].append(control["id"])
    if len(seen) != 10:
        raise ValueError("v6_unique_control_input_count_drift")
    return {"schema_version": "current-flash-v6-34-input-v2", "classification": "seen_development",
            "logical_count": 34, "comparison_lineage_count": 24, "new_control_count": 10,
            "source_hashes": {"v5_cases": sha(V5_CASES), "v6_control_matrix": sha(CONTROL),
                              "v6_input_adaptation": sha(ADAPTATION)},
            "cases": comparison + list(seen.values())}


def write() -> None:
    matrix = controls()
    (HERE / "corpora-v2").mkdir(exist_ok=True)
    for fixture_key, fixture in sorted(matrix["fixtures"].items()):
        write_x(HERE / "corpora-v2" / ("v6_" + fixture_key + ".json"), corpus(fixture_key, fixture))
    write_x(HERE / "cases-v2.json", build())


if __name__ == "__main__":
    write()
