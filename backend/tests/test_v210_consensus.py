"""v2.1: a change task runs three times at once and its card keeps what most runs proposed (`assistant_consensus`)."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import unittest
from unittest.mock import patch

from app import assistant_consensus
from app.assistant_store import SCHEMA

from tests.scripted_chat import answer_call, call, tool_items, turn
from tests.test_v200_changes import ChangeCase, change_call, refs


def item(task_id, ordinal, kind, target="", subject=None):
    after = {"subject": subject, "value": "x"} if subject is not None else {"status": "resolved"}
    return {"id": f"{task_id}-{ordinal}", "task_id": task_id, "project_id": "p", "ordinal": ordinal, "kind": kind, "target_id": target or f"new-{task_id}-{ordinal}",
            "before_json": "null", "after_json": json.dumps(after, ensure_ascii=False), "display_json": "{}", "evidence_json": "[]",
            "status": "proposed", "created_at": "t"}


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        self.c.execute("CREATE TABLE assistant_changes(id TEXT PRIMARY KEY, task_id TEXT, project_id TEXT, ordinal INTEGER, kind TEXT, target_id TEXT, "
                       "before_json TEXT, after_json TEXT, display_json TEXT, evidence_json TEXT, status TEXT, created_at TEXT)")
        self.c.execute("CREATE TABLE assistant_tasks(id TEXT PRIMARY KEY, consensus_json TEXT)")
        self.c.execute("INSERT INTO assistant_tasks(id) VALUES('T')")
        self.assertIn("assistant_changes", SCHEMA)

    def put(self, *rows):
        for row in rows:
            self.c.execute(f"INSERT INTO assistant_changes({','.join(row)}) VALUES({','.join('?' for _ in row)})", tuple(row.values()))

    def card(self, task_id="T"):
        return [(row["kind"], row["target_id"], row["ordinal"]) for row in
                self.c.execute("SELECT * FROM assistant_changes WHERE task_id=? ORDER BY ordinal", (task_id,))]

    def test_an_item_only_the_authors_run_proposed_goes(self):
        self.put(item("T", 1, "resolve_thread", "A"), item("T", 2, "change_fact", "B"), item("S1", 1, "resolve_thread", "A"),
                 item("S2", 1, "resolve_thread", "A"), item("S2", 2, "change_fact", "C"))
        self.assertTrue(assistant_consensus.merge(self.c, "T", ["S1", "S2"]))
        self.assertEqual(self.card(), [("resolve_thread", "A", 1)])
        record = json.loads(self.c.execute("SELECT consensus_json FROM assistant_tasks WHERE id='T'").fetchone()[0])
        self.assertEqual(record["runs"], 3)
        self.assertEqual(sorted((item["kind"], item["runs"], item["kept"]) for item in record["items"]),
                         [("change_fact", [0], False), ("change_fact", [2], False), ("resolve_thread", [0, 1, 2], True)])

    def test_an_item_the_other_two_proposed_is_added_after_the_authors(self):
        self.put(item("T", 1, "change_fact", "A"), item("S1", 1, "change_fact", "C"), item("S1", 2, "change_fact", "A"), item("S2", 1, "change_fact", "C"))
        self.assertTrue(assistant_consensus.merge(self.c, "T", ["S1", "S2"]))
        self.assertEqual(self.card(), [("change_fact", "A", 1), ("change_fact", "C", 2)])
        self.assertEqual(self.card("S1"), [("change_fact", "A", 2)])  # the borrowed item moved, the rest stays to be discarded

    def test_new_facts_are_matched_by_what_they_are_about(self):
        self.put(item("T", 1, "add_fact", subject="甄 宿微"), item("S1", 1, "add_fact", subject="甄宿微"), item("S2", 1, "add_fact", subject="谯映砚"))
        self.assertFalse(assistant_consensus.merge(self.c, "T", ["S1", "S2"]))
        self.assertEqual(len(self.card()), 1)

    def test_with_fewer_than_three_runs_the_authors_card_stands(self):
        self.put(item("T", 1, "change_fact", "B"), item("S1", 1, "change_fact", "A"))
        self.assertFalse(assistant_consensus.merge(self.c, "T", ["S1"]))
        self.assertEqual(self.card(), [("change_fact", "B", 1)])


class EveryRun(list):
    """Turns for a model that several runs share: whichever run asks gets the turn its conversation calls for."""

    def __init__(self, decide):
        super().__init__([decide])

    def pop(self, index=-1):
        return self[0]


class ThreeRunTests(ChangeCase):
    def three_runs(self):
        self.engine.settings = dataclasses.replace(self.engine.settings, assistant_change_runs=3)

    def decide(self, provider, messages):
        done = [m for m in messages if m["role"] == "tool"]
        if not done:
            return turn(call("list_threads"), call("read_chapter", chapter_number=self.last))
        if not any('"change"' in m["content"] for m in done):
            thread = next(entry["ref"] for entry in tool_items(messages) if entry["text"].startswith("伏笔：罗盘下落"))
            return turn(change_call(action="resolve_thread", target=thread, evidence=[refs(messages, self.last)[0]], request_words="最后一章"))
        return turn(answer_call("answered", [("最后一章写到了这条线的结果。", [refs(messages, self.last)[0]])]))

    def run_task(self):
        self.provider.turns = EveryRun(self.decide)
        r = self.post_task("change", context={"page": "materials"}, question="罗盘那条线最后一章已经收了")
        return self.task(r.json()["data"]["id"])

    def test_runs_that_agree_make_the_same_card_and_leave_nothing_behind(self):
        one = self.run_task()
        self.assertEqual([item["kind"] for item in one["changes"]], ["resolve_thread"])
        self.reject(one)
        self.three_runs()
        task = self.run_task()
        self.assertEqual(task["status"], "completed")
        self.assertEqual([item["kind"] for item in task["changes"]], ["resolve_thread"])
        self.assertNotIn(assistant_consensus.AGREED_NOTE, json.dumps(task, ensure_ascii=False))
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM assistant_tasks WHERE status=?", assistant_consensus.SHADOW_STATUS)[0]["n"], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM assistant_changes WHERE task_id NOT IN (SELECT id FROM assistant_tasks)")[0]["n"], 0)
        usage = {row["id"]: row for row in self.rows("SELECT id,input_tokens,cost_cny FROM assistant_tasks WHERE id IN (?,?)", one["id"], task["id"])}
        self.assertEqual(usage[task["id"]]["input_tokens"], 3 * usage[one["id"]]["input_tokens"])  # the hidden runs' cost is the task's

    def test_a_change_task_reserves_a_ceiling_for_each_run_and_settles_what_all_cost(self):
        self.three_runs()
        with patch.object(self.engine.stage13, "reserve_workflow", wraps=self.engine.stage13.reserve_workflow) as reserve:
            task = self.run_task()
        self.assertEqual(reserve.call_args.kwargs["reservation_microunits"], round(3 * self.engine.settings.assistant_task_max_cny * 1_000_000))
        settled = self.rows("SELECT reserved_microunits FROM v2_usage_reservations WHERE id=(SELECT reservation_id FROM assistant_tasks WHERE id=?)", task["id"])
        self.assertEqual(settled[0]["reserved_microunits"], round(9 * 0.01 * 1_000_000))  # three runs of three turns each

    def reject(self, task):
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/reject", headers=self.idem(), json={})
        self.assertEqual(r.status_code, 200, r.text)
