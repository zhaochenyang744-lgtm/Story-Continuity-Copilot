"""Create-only offline rescore of frozen V2 records; performs no fixture or API run."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import pathlib
import re
from datetime import datetime, timezone

from evaluation.current_contract_compare_v3.score import score_one, score_raw_one

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V2 = HERE.parent / "current_contract_compare_v2"
PRESERVATION = ROOT / "docs/g02-citation-repair-evidence/independent-round3-root/v2-preservation-final.json"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_x(path: pathlib.Path, data: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def reserve_run_dir(run_id: str) -> pathlib.Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", run_id):
        raise ValueError("invalid_run_id")
    parent = HERE / "runs"
    parent.mkdir(exist_ok=True)
    destination = parent / run_id
    # Reserve identity before reading any corpus, capture, or saved API record.
    destination.mkdir(exist_ok=False)
    return destination


def verify_v2(cases_doc: dict) -> dict:
    protected = json.loads(PRESERVATION.read_text(encoding="utf-8"))["files"]
    for relative, digest in protected.items():
        path = ROOT / relative
        if not path.is_file() or sha(path) != digest:
            raise RuntimeError("protected_v2_hash_mismatch:" + relative)
    expected = {"v2_cases_sha256": V2 / "cases.json",
                "v2_capture_sha256": V2 / "actual-inputs.json",
                "v2_saved_api_sha256": V2 / "api-score-probe-results-v2.json"}
    for key, path in expected.items():
        if cases_doc[key] != sha(path):
            raise RuntimeError("v3_source_hash_mismatch:" + key)
    return {key: sha(path) for key, path in expected.items()}


def _same_business_content(actual: dict, captured: dict) -> bool:
    a = copy.deepcopy(actual)
    b = copy.deepcopy(captured)
    if len(a.get("claims", [])) != len(b.get("claims", [])):
        return False
    for ac, bc in zip(a["claims"], b["claims"]):
        ac["id"] = bc["id"]
    return a == b


def analyze() -> tuple[dict, dict]:
    cases_doc = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    digests = verify_v2(cases_doc)
    capture = json.loads((V2 / "actual-inputs.json").read_text(encoding="utf-8"))
    saved = json.loads((V2 / "api-score-probe-results-v2.json").read_text(encoding="utf-8"))
    captured = {x["case_id"]: x["business_request"] for x in capture["rows"]}
    cases = {x["lineage"]["v2_case_id"]: x for x in cases_doc["cases"]}
    if len(captured) != 24 or len(cases) != 24 or len(saved["rows"]) != 26:
        raise RuntimeError("v2_record_count_mismatch")
    rows = []
    for old in saved["rows"]:
        old_id, variant = old["case_id"], old["variant"]
        case = cases[old_id]
        request = old["business_request"]
        if not _same_business_content(request, captured[old_id]):
            raise RuntimeError("business_capture_drift:" + old_id + ":" + variant)
        first = score_raw_one(case, old["raw_first"], request)
        repair = score_raw_one(case, old["raw_repair"], request) if old.get("raw_repair") is not None else None
        final = score_one(case, old["final_product"], request)
        rows.append({"v3_case_id": case["case_id"], "v2_record_id": old_id, "variant": variant,
                     "input_origin": "exact_frozen_v2_capture_file_sha256; saved_v2_request_equal_after_ephemeral_claim_id_normalization; no_new_api",
                     "raw_first": first, "raw_repair": repair, "final_product": final})
    summary = {"schema_version": "current-contract-compare-v3-offline-rescore",
               "run_kind": "saved_v2_offline_rescore", "new_api_runs": 0, "real_provider_calls": 0,
               "v2_input_hashes": digests, "case_count": len(cases), "saved_record_count": len(rows),
               "raw_first_machine_pass": sum(x["raw_first"]["machine_result"] == "pass" for x in rows),
               "final_machine_pass": sum(x["final_product"]["machine_result"] == "pass" for x in rows),
               "raw_repair_present": sum(x["raw_repair"] is not None for x in rows),
               "category_delta_rows": [x["v3_case_id"] for x in rows if
                                       "category_mismatch" in x["final_product"]["errors"]],
               "semantic_status": "pending_manual_review"}
    return summary, {"schema_version": "current-contract-compare-v3-rescore-rows", "rows": rows}


def execute(run_id: str) -> pathlib.Path:
    destination = reserve_run_dir(run_id)
    try:
        summary, rows = analyze()
        write_x(destination / "rows.json", rows)
        write_x(destination / "summary.json", {**summary, "created_at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        write_x(destination / "first-failure.json", {"run_id": run_id,
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__, "error": str(exc),
                "note": "This is this V3 attempt's first failure, not a reconstruction of a V2 failure."})
        raise
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(execute(args.run_id))
