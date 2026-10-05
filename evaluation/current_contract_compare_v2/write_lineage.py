"""Record the immutable V1 source and one-to-one V2 revision lineage."""
from __future__ import annotations

import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
V1 = ROOT / "evaluation/current_contract_compare_v1"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    old_path, new_path = V1 / "cases.json", HERE / "cases.json"
    old = {x["case_id"]: x for x in json.loads(old_path.read_text(encoding="utf-8"))["cases"]}
    new = json.loads(new_path.read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in new:
        origin = case["lineage"]["v1_case_id"]
        if origin not in old or old[origin]["expected_class"] != case["expected_class"]:
            raise RuntimeError("v1_case_lineage_invalid:" + case["case_id"])
        rows.append({"v1_case_id": origin, "v2_case_id": case["case_id"],
                     "category": case["decision_category"], "class": case["expected_class"],
                     "change": case["lineage"]["change"],
                     "draft_changed": old[origin]["target_draft"] != case["target_draft"],
                     "evidence_policy_changed": True,
                     "reason": "V2 addresses independent round-two review of time scope, minimally sufficient evidence, state-change controls, wording, and strict capture-bound scoring."})
    payload = {"schema_version": "current-contract-compare-v2-v1-lineage",
               "v1_manifest_sha256": sha(V1 / "frozen-inputs.json"),
               "v1_cases_sha256": sha(old_path), "v2_cases_sha256": sha(new_path),
               "v1_case_count": len(old), "v2_case_count": len(new),
               "retained_byte_identical_count": 0,
               "status": "seen_development; not an independent holdout",
               "rows": rows}
    with (HERE / "v1-lineage.json").open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"mapped": len(rows), "v1_manifest_sha256": payload["v1_manifest_sha256"]}))


if __name__ == "__main__":
    main()
