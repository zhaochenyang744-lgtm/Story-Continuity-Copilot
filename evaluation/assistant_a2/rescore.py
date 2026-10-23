"""Score a finished A2 report again under the current scorer, without running any task (for a registered addendum that
changes how a run is scored). Judgments are kept by key, so only the questions the current scorer adds are asked; the
original report is left as it was and the result is written beside it with "-rescored" in its name.

    python -m evaluation.assistant_a2.rescore --report <...-report.json> --judge-rates 9,27
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

from evaluation.assistant_a1.run import Ledger, PricedProvider, git, rates, write_json

from . import score
from .judge import Judge
from .thresholds import PRE_REGISTRATION

# Before 39f3956 a change's quotes were judged one by one ("evidence:<item>:<n>"); now once together ("evidence:<item>").
OLD_EVIDENCE_KEY = re.compile(r"^evidence:.+:\d+$")


def rescore(report, judge, ledger=None, ask_again=()):
    """`ask_again`: questions whose registered wording changed, so their earlier verdicts are dropped and asked anew."""
    for row in report["records"]:
        if not row.get("finished"):
            continue
        row["judgments"] = [j for j in row.get("judgments", []) if not OLD_EVIDENCE_KEY.match(j["key"]) and j["question"] not in ask_again]
        if ledger:
            ledger.task_id, ledger.run_number = row["task"]["id"], row["run_number"]
        score.grade(row, judge)
    report["rescored"] = {"at_utc": datetime.now(timezone.utc).isoformat(), "code": git("rev-parse", "HEAD"),
                          "judge_cost_cny": ledger.spent if ledger else 0.0, "asked_again": sorted(ask_again)}
    return score.refresh(report)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report", type=pathlib.Path, required=True)
    p.add_argument("--judge-rates", type=rates, required=True)
    p.add_argument("--judge-model", default=PRE_REGISTRATION["judging"]["judge_model"])
    p.add_argument("--max-cny", type=float, default=2)
    p.add_argument("--ask-again", nargs="*", default=[], help="questions whose wording changed (their verdicts are asked anew)")
    args = p.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    ledger = Ledger(args.max_cny, args.judge_rates, args.judge_rates)
    ledger.category, ledger.phase = "judge", "judge"
    rescore(report, Judge(PricedProvider(ledger), args.judge_model), ledger, set(args.ask_again))
    base = args.report.with_name(args.report.name.replace("-report.json", "-rescored"))
    write_json(base.with_name(base.name + "-report.json"), report)
    write_json(base.with_name(base.name + "-audit.json"), score.audit(report))
    base.with_name(base.name + "-markdown.md").write_text(score.markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["gate_decision"], "judge_cost_cny": ledger.spent}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
