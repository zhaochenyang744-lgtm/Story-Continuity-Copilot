"""Freeze the accepted 24+6 logical inputs without modifying upstream sets."""
from __future__ import annotations

import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V3 = ROOT / "evaluation/current_contract_compare_v3/cases.json"
G02_V2 = ROOT / "evaluation/current_flash_v2/cases.json"
G02_V4 = ROOT / "evaluation/current_flash_v4/cases.json"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body(case: dict) -> str:
    return case.get("body", case.get("body_repeat", "") * case.get("repeat_count", 0) + case.get("body_tail", ""))


def build() -> dict:
    v3 = json.loads(V3.read_text(encoding="utf-8"))["cases"]
    old = json.loads(G02_V2.read_text(encoding="utf-8"))["g02"]
    newer = json.loads(G02_V4.read_text(encoding="utf-8"))["g02"]
    if len(v3) != 24 or len(newer) != 6 or [(x["id"], body(x)) for x in newer[:4]] != [(x["id"], body(x)) for x in old]:
        raise RuntimeError("accepted_case_lineage_changed")
    rows = ([{"ordinal": index, "family": "comparison", "case_id": case["case_id"],
              "corpus_key": case["corpus_key"], "saved_draft": case["target_draft"],
              "accepted_gold_ref": "evaluation/current_contract_compare_v3/cases.json"}
             for index, case in enumerate(v3, 1)] +
            [{"ordinal": index + 25, "family": "g02", "case_id": case["id"],
              "saved_draft": body(case), "expected": case["expected"],
              "accepted_case_ref": "evaluation/current_flash_v4/cases.json",
              "body_lineage": "byte_identical_v2" if index < 4 else "byte_identical_v4"}
             for index, case in enumerate(newer)])
    if len(rows) != 30 or len({x["case_id"] for x in rows}) != 30:
        raise RuntimeError("case_identity_count_invalid")
    return {"schema_version": "current-flash-v5-30", "classification": "seen_development",
            "model": "deepseek-flash", "base_url": "https://api.deepseek.com",
            "logical_count": 30, "comparison_count": 24, "g02_count": 6,
            "source_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
                              for path in (V3, G02_V2, G02_V4)},
            "dialogue_note": "The V4 draft body is reused verbatim. Current quote-aware claim splitting must yield two complete attributed quotations; the old V4 captured request had three pieces including a closing-quote-only tail.",
            "cases": rows}


if __name__ == "__main__":
    with (HERE / "cases.json").open("x", encoding="utf-8") as output:
        json.dump(build(), output, ensure_ascii=False, indent=2)
