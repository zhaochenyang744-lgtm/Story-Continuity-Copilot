"""Read-only paired comparison of a finished V9 run with V8 on the same arms.

Only machine scores are compared. V8 recorded zero disagreement between its final
machine and completed human scores; V9 human semantic review is still pending,
so this output is not a quality verdict.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
V8_RUN = ROOT / "evaluation/model_compare_v8/runs/model-compare-v8-20260927-01"
V9_RUNS = ROOT / "evaluation/model_compare_v9/runs"
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
    first_attempt = next((a for a in attempts if a["evaluation"] == 1), None)
    return {
        "first_pass": (scores.get("first") or {}).get("machine_result") == "pass",
        "final_pass": (scores.get("final") or {}).get("machine_result") == "pass",
        "final_errors": (scores.get("final") or {}).get("errors", []),
        "engine_status": f"{final.get('status')}:{final.get('error_code')}",
        "repairs": max(0, len({a["evaluation"] for a in attempts}) - 1),
        "posts": len(attempts),
        "tokens": [a["usage"]["total_tokens"] for a in attempts],
        "usage_complete": all(a["usage"]["status"] == "complete" for a in attempts),
        "first_latency_ms": first_attempt["latency_ms"] if first_attempt else None,
        "original_8000": all(a["usage"]["original_8000_compatible"] for a in attempts) if attempts else None,
    }


def summarize(run):
    result = {}
    for condition in CONDITIONS:
        rows = {n: trial(run, n, condition) for n in range(1, 35)}
        done = {n: r for n, r in rows.items() if r}
        latencies = [r["first_latency_ms"] for r in done.values() if r["first_latency_ms"] is not None]
        result[condition] = {
            "finished": len(done),
            "first_pass": sum(r["first_pass"] for r in done.values()),
            "final_pass": sum(r["final_pass"] for r in done.values()),
            "final_pass_within_original_8000": sum(r["final_pass"] and bool(r["original_8000"]) for r in done.values()),
            "repairs": sum(r["repairs"] for r in done.values()),
            "posts": sum(r["posts"] for r in done.values()),
            "total_tokens": sum(sum(r["tokens"]) for r in done.values()) if all(r["usage_complete"] for r in done.values()) else None,
            "first_latency_median_s": round(statistics.median(latencies) / 1000, 2) if latencies else None,
            "rows": rows,
        }
    return result


def main(v9_run):
    v9, v8 = summarize(v9_run), summarize(V8_RUN)
    report = {"note": "machine scores only; V9 semantic review pending", "conditions": {}}
    for condition in CONDITIONS:
        changes = []
        for n in range(1, 35):
            old, new = v8[condition]["rows"][n], v9[condition]["rows"][n]
            if old and new and (old["final_pass"], old["first_pass"]) != (new["final_pass"], new["first_pass"]):
                changes.append({"case": n, "v8": {k: old[k] for k in ("first_pass", "final_pass", "engine_status", "final_errors")},
                                "v9": {k: new[k] for k in ("first_pass", "final_pass", "engine_status", "final_errors")}})
        report["conditions"][condition] = {
            "v8": {k: v for k, v in v8[condition].items() if k != "rows"},
            "v9": {k: v for k, v in v9[condition].items() if k != "rows"},
            "case_04": {"v8": v8[condition]["rows"][4], "v9": v9[condition]["rows"][4]},
            "changed_cases": changes,
        }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(main(V9_RUNS / args.run_id), ensure_ascii=False, indent=1))
