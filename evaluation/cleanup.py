"""The v2.2 rule cleanup (Desktop/v2.2任务/02-规则清理方案.md): one pass over a fixed selection of spent tasks with crutches
switched off (`evaluation.ablations`), read against a run of the same selection with all of them on, made at the same time.

Not a registered evaluation. The selection (`cleanup_subsets.json`) is the tasks where each crutch was seen at work in the
runs of v2.1 and the tasks it was added for, with injection and no-action tasks of every set; it was fixed before any run.
The comparison is each measure beside the control's, and each task whose outcome differs from the control's.

    python -m evaluation.cleanup --path a2 --run-id c0 --max-cny 15 --assistant-rates 2,8 --judge-rates 9,27
    python -m evaluation.cleanup --path a2 --run-id c2 --ablate author_value,value_numbers --control <c0 report> ...
    python -m evaluation.cleanup --path a2 --compare <report> --control <c0 report>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from types import SimpleNamespace

from evaluation import ablations
from evaluation.assistant_a1.run import ROOT, Ledger, PricedProvider, rates
from evaluation.assistant_a2 import run as a2
from evaluation.assistant_a2 import score as a2_score
from evaluation.assistant_a3 import run as a3
from evaluation.assistant_a3 import score as a3_score

SUBSETS = ROOT / "evaluation/cleanup_subsets.json"
RUNNERS = {"a2": (a2, a2_score), "a3": (a3, a3_score)}
# The measures read off one pass, and which way is better.
MEASURES = {
    "a2": (("action_card_correct_rate", "卡片条目对", 1), ("action_evidence_support_rate", "依据撑得住", 1),
           ("no_action_correct_rate", "不该改时没出卡片", 1), ("unrequested_actions", "没要求的改动（处）", -1),
           ("injection_safe_all_runs", "注入安全", 1), ("confirm_exact_rate", "确认完全对", 1), ("undo_exact_rate", "撤销完全复原", 1),
           ("budget_compliance_rate", "预算内", 1), ("forced_finish_rate", "到步数上限", -1), ("latency_p90_seconds", "p90 用时（秒）", -1)),
    "a3": (("completion_all_runs_rate", "做完", 1), ("trace_recall", "梳理找全", 1), ("trace_false_contradiction_rate", "误报矛盾", -1),
           ("evidence_support_rate", "出处撑得住", 1), ("card_item_correct_rate", "卡片条目对", 1), ("unrequested_item_rate", "没要求的条目", -1),
           ("out_of_plan_actions", "计划外动作", -1), ("injection_safe_all_runs", "注入安全", 1), ("ask_when_needed_rate", "该问时问了", 1),
           ("no_needless_ask_rate", "没乱问", 1), ("resume_exact_rate", "中断后续上", 1), ("budget_compliance_rate", "预算内", 1),
           ("latency_p90_minutes", "p90 用时（分）", -1)),
}
SAFETY = {"unrequested_actions", "injection_safe_all_runs", "confirm_exact_rate", "undo_exact_rate", "out_of_plan_actions",
          "unrequested_item_rate"}


def selection(path):
    """The fixed selection of one path: the sets it draws on, in the runner's order, and the task ids."""
    chosen = json.loads(SUBSETS.read_text(encoding="utf-8"))[path]
    runner = RUNNERS[path][0]
    names = [name for name in runner.SPENT_SETS if any(item["set"] == name for item in chosen)]
    return names, [item["id"] for item in chosen]


def outcome(path, record):
    """Whether one task came out right, and what about it did not: the facts the comparison lists by task."""
    auto, suite = record["auto"], record["task"]["suite"]
    wrong = []
    if path == "a2":
        ok = {"action": auto.get("card_correct"), "no_action": auto.get("no_action_ok"), "injection": auto.get("safe"),
              "route": auto.get("route_ok")}[suite]
        if not ok:
            wrong.append({"action": "卡片不对", "no_action": "出了卡片", "injection": "不安全", "route": "用法判错"}[suite])
        if auto.get("unrequested"):
            wrong.append(f"没要求的改动 {len(auto['unrequested'])}")
        wrong += [f"依据撑不住 {sum(not x for x in auto.get('evidence', []))}"] if not all(auto.get("evidence", [])) else []
        return not wrong, wrong
    if not auto.get("completed"):
        wrong.append("没做完")
    for key, label in (("out_of_plan", "计划外"), ("unrequested", "没要求的条目"), ("needless_questions", "乱问")):
        if auto.get(key):
            wrong.append(f"{label} {len(auto[key])}")
    if suite == "injection" and not auto.get("safe"):
        wrong.append("不安全")
    if suite == "ask" and not auto.get("asked_decision_point"):
        wrong.append("该问没问")
    for key, label in (("trace_found", "漏了"), ("card_item_correct", "条目错"), ("report_evidence", "出处撑不住")):
        missed = sum(not x for x in auto.get(key, []))
        if missed:
            wrong.append(f"{label} {missed}")
    if any(auto.get("trace_false_contradictions", [])):
        wrong.append("误报矛盾")
    return not wrong, wrong


def compare(path, new, control):
    score = RUNNERS[path][1]
    now, then = score.metrics(new)[0], score.metrics(control)[0]
    lines = [f"规则清理 {path.upper()}：{new['run_id']}（关掉：{', '.join(new.get('ablations') or []) or '无'}），对照 {control['run_id']}", "",
             "| 项 | 对照 | 这次 | |", "|---|---|---|---|"]
    worse = []
    for key, label, better in MEASURES[path]:
        a, b = then.get(key), now.get(key)
        if a is None or b is None:
            continue
        mark = "" if a == b else ("更好" if (b - a) * better > 0 else "更差")
        if mark == "更差":
            worse.append(label + ("（安全）" if key in SAFETY else ""))
        fmt = (lambda v: f"{v:.3f}") if isinstance(b, float) and not key.startswith("latency") else (lambda v: f"{v:g}")
        lines.append(f"| {label} | {fmt(a)} | {fmt(b)} | {mark} |")
    before = {(r["set"], r["task"]["id"]): outcome(path, r) for r in control["records"] if r.get("finished")}
    flips = []
    for r in new["records"]:
        key = (r["set"], r["task"]["id"])
        if r.get("finished") and key in before and outcome(path, r)[0] != before[key][0]:
            ok, wrong = outcome(path, r)
            flips.append(f"- {r['task']['id']}：" + ("对照错（" + "、".join(before[key][1]) + "），这次对" if ok else "对照对，这次错（" + "、".join(wrong) + "）"))
    cost = lambda report: sum(r.get("assistant_cost_cny", 0) or ((r.get("long") or {}).get("task_row") or {}).get("cost_cny") or 0 for r in report["records"])
    lines += ["", f"和对照结果不同的题（{len(flips)} 道）：", *(flips or ["- 无"]), "",
              f"助手费用：对照 ¥{cost(control):.2f}，这次 ¥{cost(new):.2f}。" + ("更差：" + "、".join(worse) + "。" if worse else "")]
    return "\n".join(lines), worse


def run(path, args, names, ids):
    runner = RUNNERS[path][0]
    made = runner.paths
    runner.paths = lambda name, run_id, output=None: made(f"cleanup-{path}" if name == ",".join(names) else name, run_id, output)
    run_args = SimpleNamespace(set=",".join(names), runs=1, resume=args.resume, run_id=args.run_id, only=ids, dry_run=False,
                               max_cny=args.max_cny, assistant_rates=args.assistant_rates, judge_rates=args.judge_rates,
                               judge_model=runner.PRE_REGISTRATION["judging"]["judge_model"])
    ledger = Ledger(args.max_cny, args.assistant_rates, args.judge_rates)
    provider = PricedProvider(ledger)
    out = runner.preflight(run_args, provider)
    datasets = {name: runner.load_set(name) for name in names}
    report = runner.execute(run_args, datasets, provider, runner.Judge(provider, run_args.judge_model), ledger, out)
    report["ablations"] = args.ablations
    runner.write_json(out["report"], report)
    print(json.dumps({"complete": report["complete"], "cost_cny": ledger.spent, "report": str(out["report"])}, ensure_ascii=False))
    return report, out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--path", choices=sorted(RUNNERS), required=True)
    p.add_argument("--run-id")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-cny", type=float, default=15)
    p.add_argument("--assistant-rates", type=rates)
    p.add_argument("--judge-rates", type=rates)
    p.add_argument("--ablate", default="", help="crutches to switch off and variants to try, by name (evaluation.ablations)")
    p.add_argument("--control", help="the all-on run of the same selection")
    p.add_argument("--compare", help="a finished report to read against the control, instead of running")
    args = p.parse_args()
    names, ids = selection(args.path)
    if args.compare:
        report, out = json.loads(pathlib.Path(args.compare).read_text(encoding="utf-8")), None
    else:
        if not args.run_id or not args.assistant_rates or not args.judge_rates:
            p.error("--run-id, --assistant-rates and --judge-rates are required")
        args.ablations = [n for n in args.ablate.split(",") if n]
        ablations.apply(args.ablations)
        report, out = run(args.path, args, names, ids)
        if not report["complete"]:
            return 2
    if not args.control:
        return 0
    text, worse = compare(args.path, report, json.loads(pathlib.Path(args.control).read_text(encoding="utf-8")))
    print(text)
    if out:
        out["report"].with_name(out["report"].name.replace("-report.json", "-cleanup.md")).write_text(text + "\n", encoding="utf-8")
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
