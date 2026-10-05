"""Strict per-case current-contract scorer; never dispatches a Provider call."""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def expected_span_ids(case: dict) -> set[str]:
    return {f"fixture-span-{case['corpus_key']}-{item['chapter_number']}" for item in case["expected_evidence"]}


def score_one(case: dict, product: dict) -> dict:
    """Require class, category, direct Evidence and temporal contract on one claim."""
    if product.get("status") != "completed":
        return {"case_id": case["case_id"], "result": "terminal_failure", "errors": [product.get("error_code") or "run_not_completed"]}
    issues = product.get("issues")
    if not isinstance(issues, list):
        return {"case_id": case["case_id"], "result": "unscorable", "errors": ["issues_not_included"]}
    errors = []
    expected = case["expected_class"]
    if expected == "no_conflict":
        if issues:
            errors.append("false_positive_issue")
    elif expected == "insufficient_evidence":
        if len(issues) != 1 or issues[0].get("classification") != "insufficient_evidence" or issues[0].get("nature") != "insufficient_evidence":
            errors.append("insufficient_class_mismatch")
        else:
            evidence = issues[0].get("evidence", [])
            if issues[0].get("claim_text") != case["target_draft"]:
                errors.append("target_claim_mismatch")
            if any(x.get("sufficiency") != "insufficient" for x in evidence):
                errors.append("uncertainty_upgraded")
            if not expected_span_ids(case) <= {x.get("span_id") for x in evidence}:
                errors.append("missing_unknown_source")
    else:
        if len(issues) != 1 or issues[0].get("classification") != "conflict" or issues[0].get("nature") != "confirmed_conflict":
            errors.append("confirmed_conflict_class_mismatch")
        else:
            issue = issues[0]
            if issue.get("claim_text") != case["target_draft"]:
                errors.append("target_claim_mismatch")
            if issue.get("category") != case["expected_category"]:
                errors.append("category_mismatch")
            direct = {x.get("span_id") for x in issue.get("evidence", [])
                      if x.get("relation") == "contradicts" and x.get("sufficiency") == "sufficient"}
            if not expected_span_ids(case) <= direct:
                errors.append("required_direct_evidence_missing")
            # The validated product Issue does not persist temporal_basis. A completed
            # confirmed_conflict has passed the engine's temporal/rule qualification;
            # raw-model temporal policy must be reviewed separately against the
            # captured business request, not fabricated from product fields.
    return {"case_id": case["case_id"], "expected_class": expected,
            "result": "pass" if not errors else "fail", "errors": errors}


def score_all(products: dict[str, dict]) -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    rows = [score_one(case, products[case["case_id"]]) if case["case_id"] in products else
            {"case_id": case["case_id"], "result": "not_run", "errors": []} for case in cases]
    return {"schema_version": "current-contract-compare-v1-score", "case_count": len(rows),
            "run_count": sum(row["result"] != "not_run" for row in rows),
            "pass_count": sum(row["result"] == "pass" for row in rows),
            "rows": rows}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("products_json", help="Mapping from case_id to full product response with included issues")
    args = parser.parse_args()
    print(json.dumps(score_all(json.loads(pathlib.Path(args.products_json).read_text(encoding="utf-8"))), ensure_ascii=False, indent=2))
