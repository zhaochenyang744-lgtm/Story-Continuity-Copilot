"""The near-miss review (A2 addendum 11, A3 addendum 4).

A formal run that fails on quality checks alone is reviewed task by task: Opus reads every failing task and says whether
the question (two reasonable readings, a wrong expected answer) or the grader is at fault rather than the product; the user
decides. The tasks the user strikes, at most LIMIT across the formal pair, are left out and the run is scored again. Safety
checks keep the values of the unreviewed run, and safety tasks are never struck. The unreviewed result stays in the report.

    python -m evaluation.near_miss a2 <...-report.json> <review.json>

review.json: {"decided_by": "user", "decided_on": "YYYY-MM-DD",
              "excluded": [{"set": "eval_set_...", "task_id": "...", "fault": "question" | "grader", "reason": "..."}]}
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

LIMIT = 2
FAULTS = ("question", "grader")


def review(report, decision, score, safety, protected_suites):
    """Score `report` again without the tasks `decision` strikes; returns the report with `near_miss_review` set."""
    if report["gate"].get("supplement"):
        raise ValueError("near_miss_not_for_a_supplement")  # A2 addendum 12, A3 addendum 5
    failed = report["gate"]["failed"]
    if not failed:
        raise ValueError("near_miss_run_did_not_fail")
    if set(failed) & set(safety):
        raise ValueError("near_miss_safety_check_failed")
    if decision.get("decided_by") != "user":
        raise ValueError("near_miss_not_decided_by_user")
    excluded = decision.get("excluded") or []
    keys = {(x["set"], x["task_id"]) for x in excluded}
    if not keys or len(keys) > LIMIT:
        raise ValueError("near_miss_exclusion_count")
    if any(x.get("fault") not in FAULTS or not (x.get("reason") or "").strip() for x in excluded):
        raise ValueError("near_miss_exclusion_needs_fault_and_reason")
    suites = {(r["set"], r["task"]["id"]): r["task"]["suite"] for r in report["records"]}
    if keys - suites.keys():
        raise ValueError("near_miss_unknown_task")
    if any(suites[key] in protected_suites for key in keys):
        raise ValueError("near_miss_safety_task")
    kept = dict(report, records=[r for r in report["records"] if (r["set"], r["task"]["id"]) not in keys])
    values, _ = score.metrics(kept)
    values.update({name: report["metrics"].get(name) for name in safety})
    gate = score.evaluate(values)
    prefix = "not_a_formal_run:" if report["gate_decision"].startswith("not_a_formal_run:") else ""
    report["near_miss_review"] = {"decision": decision, "metrics": values, "gate": gate,
                                  "decision_before_review": report["gate_decision"]}
    report["gate_decision"] = prefix + "after_near_miss_review:" + gate["status"]
    return report


def markdown_section(report):
    done = report["near_miss_review"]
    lines = ["", "## 差一点的复核", "", f"复核前：{done['decision_before_review']}；复核后：{report['gate_decision']}", "",
             "| 去掉的题 | 题集 | 原因 | 说明 |", "|---|---|---|---|"]
    lines += [f"| {x['task_id']} | {x['set']} | {'题目' if x['fault'] == 'question' else '评分'} | {x['reason']} |"
              for x in done["decision"]["excluded"]]
    lines += ["", "| 指标 | 复核后 | 结果 |", "|---|---|---|"]
    for name, ok in done["gate"]["checks"].items():
        value = done["metrics"].get(name)
        shown = "—" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)
        lines.append(f"| {name} | {shown} | {'—' if ok is None else '过' if ok else '未过'} |")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("evaluation", choices=["a2", "a3"])
    p.add_argument("report", type=Path)
    p.add_argument("decision", type=Path)
    args = p.parse_args()
    package = {"a2": "evaluation.assistant_a2", "a3": "evaluation.assistant_a3"}[args.evaluation]
    score = importlib.import_module(package + ".score")
    thresholds = importlib.import_module(package + ".thresholds")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    decision = json.loads(args.decision.read_text(encoding="utf-8"))
    review(report, decision, score, thresholds.SAFETY_CHECKS, thresholds.SAFETY_SUITES)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = args.report.with_name(args.report.name.removesuffix("-report.json") + "-markdown.md")
    markdown.write_text(score.markdown(report) + markdown_section(report), encoding="utf-8")
    print(report["gate_decision"])


if __name__ == "__main__":
    main()
