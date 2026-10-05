"""Read-only supplementary audit; leaves the frozen scorer and original outputs intact."""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prediction(payload):
    issues = payload.get("issues") if isinstance(payload, dict) else None
    if not isinstance(issues, list):
        return None
    if not issues:
        return "no_conflict"
    first = issues[0]
    if first.get("nature") == "confirmed_conflict" or first.get("status") == "conflict":
        return "conflict"
    if first.get("nature") == "insufficient_evidence" or first.get("status") == "insufficient_evidence":
        return "insufficient_evidence"
    return None


def audit(run_id):
    root = HERE / "runs" / run_id
    if not root.is_dir() or not (root / "summary.json").exists():
        raise RuntimeError("complete_run_required")
    files = sorted((root / "cases").glob("*.json"))
    records = [read(path) for path in files]
    if len(records) != 48:
        raise RuntimeError("expected_48_case_records")
    v8 = []
    for record in (r for r in records if r["family"] == "v8"):
        model = record["model_outputs"][0]["business_json"] if record["model_outputs"] else None
        claim = record["model_outputs"][0]["input_refs"]["claims"][0]
        supplied = {int(span["id"].rsplit("-", 1)[-1]) for span in claim["allowed_evidence"]}
        expected = {item["chapter_number"] for item in record["expected"]["evidence"]}
        v8.append({"case_id": record["case_id"], "expected_class": record["expected"]["class"],
                   "first_model_class": prediction(model), "product_class": record["score_row"]["predicted_class"],
                   "model_output_count": len(record["model_outputs"]),
                   "expected_evidence_chapters": sorted(expected), "actual_prompt_evidence_chapters": sorted(supplied),
                   "expected_in_actual_prompt": expected <= supplied,
                   "retrieval_top5_hit": record["score_row"]["retrieval_hit_at_5"],
                   "product_status": record["product"]["status"]})
    g01 = [{"case_id": r["case_id"], "expected": r["expected"], "first": r["first_model_class"],
            "product": r["product_class"], "status": r["product"]["status"]} for r in records if r["family"] == "g01"]
    g02 = [{"case_id": r["case_id"], "product_status": r["product"]["status"],
            "coverage": (r["product"].get("analysis") or {}).get("draft_coverage"),
            "first_model_output_count": len(r["model_outputs"]), "human_item_semantics": "requires_review"}
           for r in records if r["family"] == "g02"]
    g03 = [{"case_id": r["case_id"], "product_status": r["product"]["status"],
            "error_code": r["product"].get("error_code"),
            "target_status": r["product"].get("retrieval", {}).get("target_source", {}).get("status"),
            "target_fact_in_supplied_excerpt": any("星钥始终由乔霁保管。" in span.get("body", "")
               for output in r["model_outputs"] for span in output.get("input_refs", {}).get("source_spans", [])),
            "product_evidence_status": (r["product"].get("analysis") or {}).get("evidence_status"),
            "human_item_semantics": "requires_review"} for r in records if r["family"] == "g03"]
    stability = []
    for case_id in ("v8-dusk-viaduct-conflict-relationship", "v8-sable-tideglass-control-5", "v8-opal-nursery-insufficient-7"):
        trio = [r for r in records if r["case_id"] == case_id and r["family"] in {"v8", "v8_stability"}]
        stability.append({"case_id": case_id, "classes": [r["score_row"]["predicted_class"] for r in trio],
                          "three_runs_present": len(trio) == 3})
    output = {"run_id": run_id, "method": "postrun_read_only_audit_v1", "script_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
              "v8": v8, "v8_first_class_correct": sum(r["first_model_class"] == r["expected_class"] for r in v8),
              "v8_product_class_correct": sum(r["product_class"] == r["expected_class"] for r in v8),
              "v8_expected_evidence_in_actual_prompt": sum(r["expected_in_actual_prompt"] for r in v8),
              "v8_conflicts_with_full_expected_prompt_evidence": sum(r["expected_in_actual_prompt"] for r in v8 if r["expected_class"] == "conflict"),
              "g01": g01, "g02": g02, "g03": g03, "stability": stability,
              "scope_warning": "V8 frozen scorer uses DB top-five retrieval; current engine supplies only a selected subset to the model. Do not treat top-five hit as prompt evidence recall."}
    path = root / "postrun-audit.json"
    with path.open("x", encoding="utf-8") as target:
        json.dump(output, target, ensure_ascii=False, indent=2)
    print(json.dumps({"run_id": run_id, "v8_first": output["v8_first_class_correct"],
                      "v8_product": output["v8_product_class_correct"],
                      "actual_prompt_evidence": output["v8_expected_evidence_in_actual_prompt"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    audit(parser.parse_args().run_id)
