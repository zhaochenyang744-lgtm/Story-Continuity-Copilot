"""The regression halves after the failed formal runs (A2 addendum 9, A3 addendum 3): the spent sets' tasks split, kind by kind,
into a half to tune on and a half held back to check for tuning to the tasks. Written once, before either half is run, and
kept with the registration; run with `python -m evaluation.make_halves`."""
from __future__ import annotations

import json
import re
from collections import defaultdict

from evaluation.assistant_a1.run import ROOT
from evaluation.assistant_a2 import run as a2
from evaluation.assistant_a3 import run as a3

OUT = ROOT / "evaluation" / "regression_halves.json"
# A3 addendum 3: no tidying in v2.1; a narrowed or injection task that asks to tidy the materials goes with it.
TIDY = re.compile(r"库里|跟资料|和资料|与资料|资料作|资料对|漏的和过期|缺项|缺了|增补|旧值|补换|资料和正文")
OLD_PAIR = "eval_set_a24_formal"  # the latest pair before the fifth: two of each kind per half, so old skills stay checked
OLD_PER_KIND = 2


def split(tasks, key):
    """Each group of `key`, in id order: even places to tune, odd held back."""
    groups, halves = defaultdict(list), {"tune": [], "hold": []}
    for task in tasks:
        groups[key(task)].append(task["id"])
    for ids in groups.values():
        for i, task_id in enumerate(sorted(ids)):
            halves["tune" if i % 2 == 0 else "hold"].append(task_id)
    return halves


def a2_halves():
    kinds = lambda t: (t["suite"], tuple(sorted(e["kind"] for e in t.get("expected_actions", []))))
    result = {"tune": {}, "hold": {}}
    for name in ("eval_set_a25_formal", "eval_set_a2s5_formal"):
        halves = split(a2.load_set(name)["tasks"], kinds)
        for half in result:
            result[half][name] = sorted(halves[half])
    old = defaultdict(list)
    for task in a2.load_set(OLD_PAIR)["tasks"]:
        if task["suite"] == "action" and len(task["expected_actions"]) == 1:
            old[task["expected_actions"][0]["kind"]].append(task["id"])
    for half, start in (("tune", 0), ("hold", OLD_PER_KIND)):
        result[half][OLD_PAIR] = sorted(i for ids in old.values() for i in sorted(ids)[start:start + OLD_PER_KIND])
    return result


def a3_halves():
    result = {"tune": {}, "hold": {}}
    for name in ("eval_set_a3_formal", "eval_set_a3s_formal", "eval_set_a3_dev", "eval_set_a3d2_dev"):
        tasks = [t for t in a3.load_set(name)["tasks"] if t["suite"] != "tidy" and not TIDY.search(t.get("request") or "")]
        halves = split(tasks, lambda t: t["suite"])
        for half in result:
            result[half][name] = sorted(halves[half])
    return result


def main():
    halves = {"a2": a2_halves(), "a3": a3_halves(),
              "rule": "each kind of task in id order, even places tune and odd are held back; the held half is looked at once, at the end"}
    OUT.write_text(json.dumps(halves, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for part in ("a2", "a3"):
        for half in ("tune", "hold"):
            print(part, half, {name: len(ids) for name, ids in halves[part][half].items()})


if __name__ == "__main__":
    main()
