"""Pool two or more long-form formal reports into one result and apply the bar to it (PLAN section 0f).

From v1.9 the formal gate is two new sets scored together: every figure in sections 4 and 5 is recomputed
from the pooled counts, never averaged across sets. Insufficient-evidence recall is the gaps found in both
sets over all of their gaps; the clean-chapter rate is the clean chapters of both sets with no card over
all of them; the single-chapter median, 90th percentile, mean and maximum are taken over every checked
chapter of both sets. All designated questions of all sets must be confirmed with the right category
(3 per set, so 6 for two).

The sets must have been run with the same code and prompts: each report records its commit (run.py
`code_identity`), and a gate result needs the same commit with no uncommitted changes in every report.
`--allow-mixed-runtime` exists only to check this module on spent reports from before that was recorded
(lf4 and lf5: 19/24 gaps, 11/15 clean chapters); a result built with it is never a gate result.

    python -m evaluation.longform.pooled REPORT.json REPORT.json [--out POOLED.json] [--allow-mixed-runtime]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from evaluation.longform import thresholds
from evaluation.longform.run import _stats
from evaluation.longform.score import aggregate

RUNTIME_KEYS = ("prompt_version", "model", "review_thinking", "concurrency", "adapter")
DESIGNATED_PER_SET = 3


def pool(reports: list[dict[str, Any]], allow_mixed_runtime: bool = False) -> dict[str, Any]:
    if len(reports) < 2:
        raise ValueError("pooling needs at least two reports")
    sets = [report.get("set_id") for report in reports]
    if len(set(sets)) != len(sets):
        raise ValueError(f"the same set appears twice: {sets}")
    if any(report.get("mode") != "formal" for report in reports):
        raise ValueError("only formal reports are pooled")
    runtimes = [{key: report.get(key) for key in RUNTIME_KEYS} | {"commit": (report.get("code") or {}).get("commit")}
                for report in reports]
    # One fixed commit with nothing uncommitted in the checker or the harness; reports from before v1.9 record no
    # commit at all, so they always count as mixed.
    unpinned = any(not (report.get("code") or {}).get("commit") or (report.get("code") or {}).get("dirty") is not False
                   for report in reports)
    mixed = unpinned or any(runtime != runtimes[0] for runtime in runtimes[1:])
    if mixed and not allow_mixed_runtime:
        raise ValueError(f"the reports were run with different code or prompts: {runtimes}")

    per_target = [row for report in reports for row in report["quality"]["per_target"]]
    quality = aggregate(per_target)
    records = [record for report in reports for record in report["records"].values()]
    done = [record for record in records if record["status"] == "completed"]
    cost_time = {
        "timing_valid": all(report["cost_time"].get("timing_valid") is True for report in reports),
        "single_chapter": {
            "seconds": _stats([record["seconds"] for record in done]),
            "cost_cny": _stats([record["check_cost"]["cost_cny"]["total"] for record in done]),
        },
        # Phase-5 selections stay per set: each set's own two 5-chapter and one 8-chapter selection.
        "selections": [dict(row, set_id=report["set_id"]) for report in reports for row in report["cost_time"].get("selections") or []],
    }
    stopped = [report.get("stopped_early") for report in reports if report.get("stopped_early") is not None]
    pooled = {
        "kind": "longform_formal_pooled", "sets": sets, "set_sha256": [report.get("set_sha256") for report in reports],
        "run_ids": [report.get("run_id") for report in reports], "runtime": runtimes[0] if not mixed else runtimes,
        "mixed_runtime": mixed, "spent_cny": sum((report.get("meter") or {}).get("spent_cny") or 0 for report in reports),
        "stopped_early": stopped or None, "quality": quality, "cost_time": cost_time,
    }
    pooled["threshold_result"] = evaluate(pooled, len(reports))
    return pooled


def evaluate(pooled: dict[str, Any], set_count: int) -> dict[str, Any]:
    """The registered bar on pooled figures. Designated: every one of the sets' 3 each, so 6 for two sets."""
    result = thresholds.evaluate(pooled)
    designated = pooled["quality"]["designated"]
    required = DESIGNATED_PER_SET * set_count
    result["checks"]["designated"] = designated["total"] == required and designated["confirmed_with_category"] == required
    result["designated_required"] = required
    result["gate_result"] = not pooled["mixed_runtime"]
    result["passed"] = result["approved_bar"] and pooled["mixed_runtime"] is False and all(value is True for value in result["checks"].values())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("reports", nargs="+", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--allow-mixed-runtime", action="store_true",
                        help="only for checking this module on spent reports; never a gate result")
    args = parser.parse_args(argv)
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    pooled = pool(reports, allow_mixed_runtime=args.allow_mixed_runtime)
    if args.out:
        args.out.write_text(json.dumps(pooled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    quality, single = pooled["quality"], pooled["cost_time"]["single_chapter"]
    summary = {
        "sets": pooled["sets"], "mixed_runtime": pooled["mixed_runtime"],
        "insufficient_evidence": f"{round(quality['insufficient_evidence_recall'] * quality['counts']['insufficient_evidence'])}/{quality['counts']['insufficient_evidence']}",
        "clean_targets_zero_card": f"{sum(1 for t in quality['per_target'] if t['clean'] and t['cards'] == 0)}/{quality['counts']['clean_targets']}",
        "conflict_recall": quality["conflict_recall"], "designated": quality["designated"]["confirmed_with_category"],
        "median_seconds": single["seconds"]["median"], "mean_cost_cny": single["cost_cny"]["mean"],
        "checks": pooled["threshold_result"]["checks"], "passed": pooled["threshold_result"]["passed"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
