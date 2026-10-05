"""Read-only V11 comparison: seen 1-34 paired with V9, new controls 35-54 alone.

Machine scores only; V11 human semantic review is pending.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
V9_RUN = ROOT / "evaluation/model_compare_v9/runs/model-compare-v9-20260928-01"
V11_RUNS = ROOT / "evaluation/model_compare_v11/runs"
CONTROLS = json.loads((ROOT / "evaluation/category_controls_v1/cases.json").read_text(encoding="utf-8"))["cases"]
CONDITIONS = ("flash-high", "pro-high")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def trial(run, ordinal, condition):
    folder = run / "cases" / f"{ordinal:02d}" / condition
    if not (folder / "trial-finish.json").is_file():
        return None
    scores = read(folder / "scores.json")
    final = read(folder / "engine-final.json")
    attempts = [read(p) for p in sorted((folder / "attempts").glob("*-finish.json"))]
    first_eval = read(folder / "evaluations/01.json") if (folder / "evaluations/01.json").is_file() else {}
    payload = first_eval.get("parsed_business_json")
    issues = payload.get("issues") if isinstance(payload, dict) else None
    first_attempt = next((a for a in attempts if a["evaluation"] == 1), None)
    first, last = scores.get("first") or {}, scores.get("final") or {}
    return {"first_pass": first.get("machine_result") == "pass", "final_pass": last.get("machine_result") == "pass",
            "first_errors": first.get("errors", []), "final_errors": last.get("errors", []),
            "first_category": issues[0].get("category") if isinstance(issues, list) and issues and isinstance(issues[0], dict) else None,
            "engine_status": f"{final.get('status')}:{final.get('error_code')}",
            "repairs": max(0, len({a["evaluation"] for a in attempts}) - 1),
            "tokens": sum(a["usage"]["total_tokens"] or 0 for a in attempts),
            "usage_complete": all(a["usage"]["status"] == "complete" for a in attempts),
            "first_latency_ms": first_attempt["latency_ms"] if first_attempt else None,
            "original_8000": all(a["usage"]["original_8000_compatible"] for a in attempts) if attempts else None}


def totals(rows):
    done = [r for r in rows.values() if r]
    latencies = [r["first_latency_ms"] for r in done if r["first_latency_ms"] is not None]
    return {"finished": len(done), "first_pass": sum(r["first_pass"] for r in done),
            "final_pass": sum(r["final_pass"] for r in done),
            "final_pass_within_original_8000": sum(r["final_pass"] and bool(r["original_8000"]) for r in done),
            "first_category_mismatch": sum("category_mismatch" in r["first_errors"] for r in done),
            "final_category_mismatch": sum("category_mismatch" in r["final_errors"] for r in done),
            "repairs": sum(r["repairs"] for r in done),
            "total_tokens": sum(r["tokens"] for r in done) if all(r["usage_complete"] for r in done) else None,
            "first_latency_median_s": round(statistics.median(latencies) / 1000, 2) if latencies else None}


def main(run):
    report = {"note": "machine scores only; V11 semantic review pending", "seen_1_34": {}, "controls_35_54": {}}
    for condition in CONDITIONS:
        v9 = {n: trial(V9_RUN, n, condition) for n in range(1, 35)}
        v11 = {n: trial(run, n, condition) for n in range(1, 35)}
        changes = [{"case": n, "v9": {k: v9[n][k] for k in ("first_pass", "final_pass", "first_category", "final_errors")},
                    "v11": {k: v11[n][k] for k in ("first_pass", "final_pass", "first_category", "final_errors")}}
                   for n in range(1, 35) if v9[n] and v11[n] and
                   (v9[n]["first_pass"], v9[n]["final_pass"]) != (v11[n]["first_pass"], v11[n]["final_pass"])]
        report["seen_1_34"][condition] = {"v9": totals(v9), "v11": totals(v11), "changed_cases": changes,
            "v11_remaining_final_failures": {n: r["final_errors"] for n, r in v11.items() if r and not r["final_pass"]}}
        controls = {35 + i: trial(run, 35 + i, condition) for i in range(20)}
        report["controls_35_54"][condition] = {"totals": totals(controls), "cases": [
            {"ordinal": 35 + i, "id": c["id"], "probe": c["probe"], "expected": c["expected"]["category"] or "no_issue",
             "first_category": controls[35 + i]["first_category"] if controls[35 + i] else None,
             "first_pass": controls[35 + i]["first_pass"] if controls[35 + i] else None,
             "final_pass": controls[35 + i]["final_pass"] if controls[35 + i] else None,
             "final_errors": controls[35 + i]["final_errors"] if controls[35 + i] else None}
            for i, c in enumerate(CONTROLS)]}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(main(V11_RUNS / args.run_id), ensure_ascii=False, indent=1))
