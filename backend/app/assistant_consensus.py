"""A change card made from several runs of the same change task (v2.1): an item goes on the card when most runs proposed it.

One run of a change task (the model reading, then proposing items) is right on most cards and wrong on a few, and a wrong
item is seldom proposed twice. So a change task runs three times at once: the author's task (whose reading and answer the
author sees) and two hidden runs of the same request (status `shadow`, no reservation, no answer kept). When all three have
proposed what they will, an item stays when at least two runs proposed it, an item the author's run alone proposed goes, and
an item the other two proposed and the author's run did not is added from one of them. The hidden runs are then deleted; what
they cost is the task's.

On the spent A2 pairs, three passes of the shipped prompt (p44) taken this way would have had 0.958 of cards right against
0.907 for one pass, and one unrequested item left of five. Two runs, keeping what both proposed, did worse (0.856): one run's
miss is the card's.

Items are matched by what they change: a record's kind and the record (its id), or for a new record its kind and the name it
is about (its subject or title, spaces taken out).
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

SHADOW_STATUS = "shadow"
MAJORITY_OF_THREE = 2
# What the answer says when the card is not what the author's run proposed.
AGREED_NOTE = "卡片上只留了多次核对都得出的改动。"


def item_key(row: Any) -> tuple[str, str]:
    """What an item changes, the same whichever run proposed it."""
    after = json.loads(row["after_json"] or "null") or {}
    if row["kind"].startswith("add_"):
        return row["kind"], "".join(str(after.get("subject") or after.get("title") or "").split())
    return row["kind"], row["target_id"]


def merge(c: sqlite3.Connection, task_id: str, other_ids: list[str]) -> bool:
    """Put on the author's task the items most of the runs proposed (the author's task and `other_ids`, each run that finished),
    in the order the author's run proposed them, then those it lacked. Returns whether the card differs from what the author's
    run proposed. With fewer than three finished runs the author's run's card stands."""
    if len(other_ids) + 1 < 3:
        return False
    rows = {run: c.execute("SELECT * FROM assistant_changes WHERE task_id=? AND status='proposed' ORDER BY ordinal", (run,)).fetchall()
            for run in [task_id, *other_ids]}
    counts = Counter(key for run_rows in rows.values() for key in {item_key(row) for row in run_rows})
    agreed = {key for key, n in counts.items() if n >= MAJORITY_OF_THREE}
    own = {item_key(row): row for row in rows[task_id]}
    kept = [row for row in rows[task_id] if item_key(row) in agreed]
    borrowed = []
    for run in other_ids:
        for row in rows[run]:
            key = item_key(row)
            if key in agreed and key not in own and key not in {item_key(other) for other in borrowed}:
                borrowed.append(row)
    for row in rows[task_id]:
        if item_key(row) not in agreed:
            c.execute("DELETE FROM assistant_changes WHERE id=?", (row["id"],))
    for ordinal, row in enumerate([*kept, *borrowed], 1):
        c.execute("UPDATE assistant_changes SET task_id=?,ordinal=? WHERE id=?", (task_id, ordinal, row["id"]))
    return set(own) != agreed


def discard(c: sqlite3.Connection, run_ids: list[str]) -> None:
    """Delete hidden runs and all they left (steps, sources, items not taken onto the card)."""
    for run in run_ids:
        for table in ("assistant_changes", "assistant_steps", "assistant_sources"):
            c.execute(f"DELETE FROM {table} WHERE task_id=?", (run,))
        c.execute("DELETE FROM assistant_tasks WHERE id=? AND status=?", (run, SHADOW_STATUS))
