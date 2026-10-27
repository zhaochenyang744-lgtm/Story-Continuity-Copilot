"""A change card made from several runs of the same change task (v2.1): an item goes on the card when most runs proposed it.

One run of a change task (the model reading, then proposing items) is right on most cards and wrong on a few, and a wrong
item is seldom proposed twice. So a change task runs three times at once: the author's task (whose reading and answer the
author sees) and two hidden runs of the same request (status `shadow`, no reservation, no answer kept). When all three have
proposed what they will, an item stays when at least two runs proposed it, an item the author's run alone proposed goes, and
an item the other two proposed and the author's run did not is added from one of them, unless the author's run proposed
nothing: its answer then says why nothing should change, and the card follows it (p52; on the spent pairs two of the five
cards filled this way were no-action tasks made wrong, and none was made right). An author's run that tried to propose and
was refused or held back did not decide that nothing should change, and is filled like any other (A2 fifth formal run:
w02-action-03, whose fact the other two runs agreed on, lost to a field the author's run got wrong). The hidden runs are then deleted; what they
cost is the task's.

Items are matched by what they change: a record's kind and the record (its id). A new record is matched by its kind and the
words of the author's sentence it answers (its request words overlap), or failing those by the name it is about: three runs
often file one new fact under different names ("灰狼迁护用药安排" and the animal's name), and matched by name each stood alone
and the right one was dropped (p52, from the p51 gate run: three action cards lost so).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

SHADOW_STATUS = "shadow"
MAJORITY_OF_THREE = 2
# What the answer says when the card is not what the author's run proposed.
AGREED_NOTE = "卡片上只留了多次核对都得出的改动。"


def item_key(row: Any) -> tuple[str, str]:
    """What an item changes by its record, the same whichever run proposed it."""
    after = json.loads(row["after_json"] or "null") or {}
    if row["kind"].startswith("add_"):
        return row["kind"], "".join(str(after.get("subject") or after.get("title") or "").split())
    return row["kind"], row["target_id"]


def _spans(text: str, words: str) -> list[tuple[int, int]]:
    spans, start = [], text.find(words) if words else -1
    while start >= 0:
        spans.append((start, start + len(words)))
        start = text.find(words, start + 1)
    return spans


def _words(row: Any) -> str:
    return "".join(str(json.loads(row["display_json"] or "{}").get("request_words") or "").split())


def _same(question: str, one: Any, other: Any) -> bool:
    """Whether two items of different runs are the same change: one kind, and one record, or for a new record the same words of
    the author's sentence (overlapping) or the same name."""
    if one["kind"] != other["kind"]:
        return False
    if not one["kind"].startswith("add_"):
        return one["target_id"] == other["target_id"]
    a, b = _words(one), _words(other)
    if question and any(x < d and c < y for x, y in _spans(question, a) for c, d in _spans(question, b)):
        return True
    return item_key(one) == item_key(other)


def _groups(question: str, rows: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """The items of all runs gathered into changes: each with the runs that proposed it and their rows, by run."""
    groups: list[dict[str, Any]] = []
    for index, run in enumerate(rows):
        for row in rows[run]:
            group = next((g for g in groups if index not in g["runs"] and any(_same(question, row, other) for other in g["rows"])), None)
            if group is None:
                group = {"runs": [], "rows": [], "by_run": {}}
                groups.append(group)
            group["runs"].append(index)
            group["rows"].append(row)
            group["by_run"].setdefault(index, []).append(row)
    return groups


def merge(c: sqlite3.Connection, task_id: str, other_ids: list[str]) -> bool:
    """Put on the author's task the items most of the runs proposed (the author's task and `other_ids`, each run that finished),
    in the order the author's run proposed them, then those it lacked. Returns whether the card differs from what the author's
    run proposed. With fewer than three finished runs the author's run's card stands. What each run proposed and what the card
    kept is recorded with the task (`consensus_json`), so a run of the evaluation shows what the majority dropped and added."""
    rows = {run: c.execute("SELECT * FROM assistant_changes WHERE task_id=? AND status='proposed' ORDER BY ordinal", (run,)).fetchall()
            for run in [task_id, *other_ids]}
    task = c.execute("SELECT input_json FROM assistant_tasks WHERE id=?", (task_id,)).fetchone()
    question = "".join(str((json.loads(task["input_json"]) if task and task["input_json"] else {}).get("question") or "").split())
    groups = _groups(question, rows)
    majority = len(rows) >= 3
    tried = bool(rows[task_id]) or c.execute("SELECT 1 FROM assistant_steps WHERE task_id=? AND tool_name='propose_change' LIMIT 1",
                                             (task_id,)).fetchone() is not None
    for group in groups:
        agreed = len(set(group["runs"])) >= MAJORITY_OF_THREE
        group["kept"] = (agreed if majority else 0 in group["runs"]) and (0 in group["runs"] or tried)
    _record(c, task_id, groups, len(rows))
    if not majority:
        return False
    kept = [row for row in rows[task_id] if any(g["kept"] and row in g["by_run"].get(0, []) for g in groups)]
    borrowed = [g["rows"][0] for g in groups if g["kept"] and 0 not in g["runs"]]
    for row in rows[task_id]:
        if row not in kept:
            c.execute("DELETE FROM assistant_changes WHERE id=?", (row["id"],))
    for ordinal, row in enumerate([*kept, *borrowed], 1):
        c.execute("UPDATE assistant_changes SET task_id=?,ordinal=? WHERE id=?", (task_id, ordinal, row["id"]))
    return len(kept) != len(rows[task_id]) or bool(borrowed)


def _record(c: sqlite3.Connection, task_id: str, groups: list[dict[str, Any]], runs: int) -> None:
    """Each change any run proposed, which runs proposed it (0 is the author's run) and whether the card keeps it."""
    items = []
    for group in groups:
        first = group["by_run"].get(0, group["rows"])[0]
        display = json.loads(first["display_json"] or "{}")
        items.append({"kind": first["kind"], "title": display.get("title"), "after": display.get("after"),
                      "request_words": display.get("request_words"), "runs": sorted(set(group["runs"])), "kept": group["kept"]})
    c.execute("UPDATE assistant_tasks SET consensus_json=? WHERE id=?", (json.dumps({"runs": runs, "items": items}, ensure_ascii=False), task_id))


def record_usage(c: sqlite3.Connection, task_id: str, runs: list[dict[str, Any]]) -> None:
    """The steps and cost of each run, the author's run first, kept with the task's record (`consensus_json`, `run_usage`)."""
    row = c.execute("SELECT consensus_json FROM assistant_tasks WHERE id=?", (task_id,)).fetchone()
    record = json.loads(row["consensus_json"]) if row and row["consensus_json"] else {}
    c.execute("UPDATE assistant_tasks SET consensus_json=? WHERE id=?", (json.dumps({**record, "run_usage": runs}, ensure_ascii=False), task_id))


def discard(c: sqlite3.Connection, run_ids: list[str]) -> None:
    """Delete hidden runs and all they left (steps, sources, items not taken onto the card)."""
    for run in run_ids:
        for table in ("assistant_changes", "assistant_steps", "assistant_sources"):
            c.execute(f"DELETE FROM {table} WHERE task_id=?", (run,))
        c.execute("DELETE FROM assistant_tasks WHERE id=? AND status=?", (run, SHADOW_STATUS))
