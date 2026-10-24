"""Development regression on the spent A2 sets: one pass over every spent pair, compared pass by pass with a baseline.

Not a registered evaluation. The baseline is the latest accepted prompt's runs on the same pairs (their report files, kept
under evaluation/results); each of its passes is scored on its own, so a new pass is read against how much one pass of the
same prompt moves. A development run may switch off named guards (`--ablate`) to measure what each one is worth; the switch
lives here, never in the product.

    python -m evaluation.regress --run-id r1-p45 --max-cny 20 --assistant-rates 2,8 --judge-rates 9,27 [--ablate give_up,read_only]
    python -m evaluation.regress --compare evaluation/results/<a report>.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from types import SimpleNamespace

from evaluation.assistant_a1.run import ROOT, Ledger, PricedProvider, rates
from evaluation.assistant_a2 import run as a2
from evaluation.assistant_a2 import score

PAIRS = (("eval_set_a2_formal", "eval_set_a2s_formal"), ("eval_set_a22_formal", "eval_set_a2s2_formal"),
         ("eval_set_a23_formal", "eval_set_a2s3_formal"), ("eval_set_a24_formal", "eval_set_a2s4_formal"))
SETS = ",".join(name for pair in PAIRS for name in pair)
_paths = a2.paths


def _short_paths(name, run_id, output=None):
    """Eight set names make a file name past Windows' path limit; a run over all of them is filed as "spent-all"."""
    return _paths("spent-all" if name == SETS else name, run_id, output)


a2.paths = _short_paths
# p44, the prompt v2.0.0 shipped: the first pair once, the other three pairs three times each.
BASELINE = ("a2-eval_set_a2_formal+eval_set_a2s_formal-d-p44-pair1-report.json",
            "a2-eval_set_a22_formal+eval_set_a2s2_formal-v-p44-pair2x3-report.json",
            "a2-eval_set_a23_formal+eval_set_a2s3_formal-v-p44-pair3x3-report.json",
            "a2-eval_set_a24_formal+eval_set_a2s4_formal-f4-p44-report.json")
# Per-pass measures (the three-pass ones cannot be read off one pass), and which way is better.
MEASURES = (("action_card_correct_rate", "卡片条目对", 1), ("action_evidence_support_rate", "依据撑得住", 1),
            ("no_action_correct_rate", "不该改时没出卡片", 1), ("unrequested_actions", "没要求的改动（处）", -1),
            ("injection_safe_all_runs", "注入安全", 1), ("confirm_exact_rate", "确认完全对", 1), ("undo_exact_rate", "撤销完全复原", 1),
            ("route_accuracy", "判断用法", 1), ("budget_compliance_rate", "预算内", 1), ("forced_finish_rate", "到步数上限", -1),
            ("latency_p90_seconds", "p90 用时（秒）", -1))

# No-action tasks of the spent pairs that ask for a thread to be given up, which v2.1 can do (`abandon_thread`).
NOW_SUPPORTED = {("eval_set_a22_formal", "a22f-w02-no-action-06"), ("eval_set_a23_formal", "a23f-w01-no-action-06"),
                 ("eval_set_a24_formal", "a24f-w02-no-06")}

NEVER = re.compile(r"(?!)")


def _off(name, value):
    def apply(module):
        setattr(module, name, value)
    return apply


# Guards a development run may switch off. Word lists are swapped for a pattern that never matches; whole checks for a stub.
ABLATIONS = {
    # The word lists (prose_subject, read_only, give_up, fact_not_thread) were switched off in g1 and taken out in v2.1 A.
    "value_numbers": _off("numbers_in", lambda text: set()),  # change_value_not_in_evidence
    "author_value": _off("_author_value_missing", lambda ctx, args, proposal: None),
    "second_look": _off("_second_look", lambda ctx, action, args, proposal, request_words: None),
}


def ablate(names):
    from app import assistant_actions
    for name in names:
        ABLATIONS[name](assistant_actions)


def passes(reports):
    """Each pass of the baseline over all four pairs: pass n of every pair run three times, with the first pair's one pass."""
    longest = max(r["runs"] for r in reports)
    return [[rec for r in reports for rec in r["records"] if rec["run_number"] == min(n, r["runs"])] for n in range(1, longest + 1)]


def values(records):
    return score.metrics({"records": records, "card_checks": []})[0]


def checks_of(report, run_number):
    return [c for c in report.get("card_checks", []) if c.get("run_number", 1) == run_number]


def compare(new, baseline_dir, controls=()):
    """The new pass against every pass of the baseline prompt: the recorded runs, and any later run of it over all four pairs
    (`controls`, best run at the same time as the new one, since one pass of the same prompt moves more than three show)."""
    reports = [json.loads((baseline_dir / name).read_text(encoding="utf-8")) for name in BASELINE]
    base = [values(p) for p in passes(reports)]
    for n, p in enumerate(base, 1):
        exact = [c for r in reports for c in checks_of(r, min(n, r["runs"]))]
        if exact:
            p["confirm_exact_rate"] = sum(c["confirm_exact"] for c in exact) / len(exact)
            p["undo_exact_rate"] = sum(c["undo_exact"] for c in exact) / len(exact)
    base += [control["metrics"] for control in controls]
    now = new["metrics"]
    lines = [f"开发回归：{new['run_id']}（提示词 {new['environment']['prompt_version']}，关掉的护栏：{', '.join(new.get('ablations') or []) or '无'}）", "",
             f"| 项 | 基线每遍（p44{'，最后 ' + str(len(controls)) + ' 遍是对照' if controls else ''}） | 这次 | 判断 |", "|---|---|---|---|"]
    worse = []
    for key, label, better in MEASURES:
        seen = [p[key] for p in base if p.get(key) is not None]
        value = now.get(key)
        if value is None or not seen:
            continue
        low, high = min(seen), max(seen)
        verdict = "在波动内"
        if (better > 0 and value > high) or (better < 0 and value < low):
            verdict = "更好"
        if (better > 0 and value < low) or (better < 0 and value > high):
            verdict = "更差"
            worse.append(label)
        fmt = (lambda v: f"{v:.3f}") if isinstance(value, float) and key != "latency_p90_seconds" else (lambda v: f"{v:g}")
        lines.append(f"| {label} | {' / '.join(fmt(v) for v in seen)} | {fmt(value)} | {verdict} |")
    asked = [rec for rec in new["records"] if (rec["set"], rec["task"]["id"]) in NOW_SUPPORTED]
    if asked:
        # These were no-action tasks while a thread could not be given up (v2.0); from v2.1 the right card gives it up.
        rest = values([rec for rec in new["records"] if (rec["set"], rec["task"]["id"]) not in NOW_SUPPORTED])
        lines += ["", "作者要把伏笔标成放弃的 3 道（v2.0 时不该改，v2.1 起该出一条「伏笔标放弃」）："]
        lines += [f"- {rec['task']['id']}：" + ("、".join(item["kind"] for item in rec.get("changes") or []) or "没出卡片") for rec in asked]
        lines += [f"去掉这 3 道后：不该改时没出卡片 {rest['no_action_correct_rate']:.3f}，没要求的改动 {rest['unrequested_actions']} 处。"]
    lines += ["", f"费用 ¥{sum(r.get('assistant_cost_cny', 0) for r in new['records']):.2f}（助手）。"
              + ("更差：" + "、".join(worse) + "。" if worse else "没有一项落到基线每遍的范围之外。")]
    return "\n".join(lines), worse


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-cny", type=float, default=20)
    p.add_argument("--assistant-rates", type=rates)
    p.add_argument("--judge-rates", type=rates)
    p.add_argument("--ablate", default="")
    p.add_argument("--only", nargs="*")
    p.add_argument("--compare", help="a finished report to compare with the baseline, instead of running")
    p.add_argument("--baseline-dir", default=str(ROOT / "evaluation/results"))
    p.add_argument("--control", nargs="*", default=[], help="reports of later runs of the baseline prompt over all four pairs")
    args = p.parse_args()
    baseline_dir = pathlib.Path(args.baseline_dir)
    if args.compare:
        report = json.loads(pathlib.Path(args.compare).read_text(encoding="utf-8"))
    else:
        names = [n for n in args.ablate.split(",") if n]
        unknown = [n for n in names if n not in ABLATIONS]
        if unknown or not args.run_id or not args.assistant_rates or not args.judge_rates:
            p.error(f"unknown ablation {unknown}" if unknown else "--run-id, --assistant-rates and --judge-rates are required")
        ablate(names)
        run_args = SimpleNamespace(set=SETS, runs=1, resume=args.resume, run_id=args.run_id, only=args.only, dry_run=False,
                                   max_cny=args.max_cny, assistant_rates=args.assistant_rates, judge_rates=args.judge_rates,
                                   judge_model=a2.PRE_REGISTRATION["judging"]["judge_model"])
        ledger = Ledger(args.max_cny, args.assistant_rates, args.judge_rates)
        provider = PricedProvider(ledger)
        out = a2.preflight(run_args, provider)
        datasets = {name: a2.load_set(name) for name in a2.set_names(SETS)}
        report = a2.execute(run_args, datasets, provider, a2.Judge(provider, run_args.judge_model), ledger, out)
        report["ablations"] = names
        a2.write_json(out["report"], report)
        if not report["complete"]:
            print(json.dumps({"complete": False, "cost_cny": ledger.spent, "stop_reason": report.get("stop_reason")}))
            return 2
    controls = [json.loads(pathlib.Path(path).read_text(encoding="utf-8")) for path in args.control]
    text, worse = compare(report, baseline_dir, controls)
    print(text)
    if not args.compare:
        (pathlib.Path(a2.paths(SETS, args.run_id)["report"]).with_name(f"regress-{args.run_id}.md")).write_text(text + "\n", encoding="utf-8")
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
