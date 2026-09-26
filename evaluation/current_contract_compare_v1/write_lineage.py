"""Record why V8 candidate inputs were excluded from the new comparison set."""
from __future__ import annotations

import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent


def main() -> None:
    old_path = ROOT / "evaluation/case_sets/eval-set-v8-candidate.json"
    new_path = HERE / "cases.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))["cases"]
    new = json.loads(new_path.read_text(encoding="utf-8"))["cases"]
    conflict_by_category = {row["expected_category"]: row["case_id"] for row in new
                            if row["expected_class"] == "conflict"}
    rows = []
    for case in old:
        rows.append({"v8_case_id": case["case_id"], "v8_class": case["expected_class"],
                     "v8_category": case.get("expected_category"),
                     "disposition": "excluded_as_input",
                     "thematic_replacement_case_id": conflict_by_category.get(case.get("expected_category"))
                     if case["expected_class"] == "conflict" else None,
                     "reason": "The V8 corpus and case wording are not inputs to this set. Its static fixture_anchor records do not satisfy the current timeless_rule contract; the new cases use their own author-confirmed rule or explicit story time. Pattern inspiration remains disclosed, and the two sets are not same-input comparisons."})
    payload = {"schema_version": "current-contract-compare-v1-v8-lineage",
               "old_case_set": str(old_path.relative_to(ROOT)).replace("\\", "/"),
               "old_case_set_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(),
               "new_case_set_sha256": hashlib.sha256(new_path.read_bytes()).hexdigest(),
               "old_case_count": len(rows), "retained_byte_identical_count": 0,
               "adaptation_disclosure": "Seen V8 challenge patterns informed the new synthetic works. The earlier cylinder seal motif was replaced with a pneumatic carrier readiness rule. This is development comparison material, not a blind holdout.",
               "rows": rows}
    with (HERE / "v8-lineage.json").open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"old_cases": len(rows), "retained": 0,
                      "thematic_category_mappings": sum(bool(row["thematic_replacement_case_id"]) for row in rows)}))


if __name__ == "__main__":
    main()
