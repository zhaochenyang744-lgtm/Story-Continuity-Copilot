"""v2.2: the author's decisions, kept as records of their own and written only by a card the author confirms."""
from __future__ import annotations

import unittest

from app import assistant_decisions as decisions

from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, ref_of_chapter, turn


def record(statement="她第 7 章的年龄和第 3 章不同是有意的", kind="intentional", subjects=("苏岑",), chapters=(3, 7), **extra):
    return {"kind": kind, "statement": statement, "subjects": list(subjects), "chapters": list(chapters) if chapters else None,
            "foreshadow_id": None, "prefer_chapter": None, "quote": "她年龄不统一是故意的", "source": "box", "source_ref": None,
            "basis_chapter": 7, **extra}


class DecisionCardTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def answered(self):
        def cite(provider, messages):
            return turn(answer_call("answered", [("第九章写到了她。", [ref_of_chapter(messages, 9)])]))
        return self.run_ask(turn(call("read_chapter", chapter_number=9)), cite)

    def put(self, task, item=None, replaces=None):
        with self.db.connection() as c:
            decisions.card_item(c, task["id"], self.project_id, item or record(), replaces)
        return self.task(task["id"])

    def confirm(self, task, accepted=None, edits=None):
        items = [i["id"] for i in task["changes"] if i["status"] == "proposed"] if accepted is None else accepted
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                             json={"accepted": items, **({"edits": edits} if edits else {})})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["data"]

    def listing(self):
        r = self.client.get(f"/api/projects/{self.project_id}/decisions")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["data"]["decisions"]

    def test_a_questions_card_carries_a_decision_that_is_written_only_when_confirmed_and_undone_exactly(self):
        task = self.put(self.answered())
        item = task["changes"][0]
        self.assertEqual((item["kind"], item["title"], item["before"], item["status"]), ("add_decision", "记下决定·有意为之", "资料里没有", "proposed"))
        self.assertIn("管：苏岑；第 3–7 章", item["after"])
        self.assertEqual(self.listing(), [])
        self.confirm(task)
        listed = self.listing()
        self.assertEqual([(d["kind"], d["statement"], d["subjects"], d["chapters"], d["status"]) for d in listed],
                         [("intentional", "她第 7 章的年龄和第 3 章不同是有意的", ["苏岑"], [3, 7], "active")])
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/changes/{item['id']}/undo", headers=self.idem(), json={"confirm": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.listing(), [])
        ledger = self.client.get(f"/api/projects/{self.project_id}/assistant/changes").json()["data"]
        self.assertTrue(any(entry["kind"] == "add_decision" for entry in ledger["changes"]))

    def test_the_author_may_reword_the_decision_on_the_card(self):
        task = self.put(self.answered())
        item = task["changes"][0]
        self.confirm(task, [item["id"]], {item["id"]: "苏岑的年龄前后不同是故意的"})
        self.assertEqual(self.listing()[0]["statement"], "苏岑的年龄前后不同是故意的")

    def test_a_decision_that_replaces_another_supersedes_it_and_an_undo_brings_it_back(self):
        task = self.put(self.answered())
        self.confirm(task)
        old = self.listing()[0]
        task = self.put(self.answered(), record("年龄以第 3 章为准", kind="prefer", prefer_chapter=3), replaces=old)
        self.assertEqual(task["changes"][0]["title"], "记下决定·以哪处为准")
        self.confirm(task)
        self.assertEqual(sorted((d["kind"], d["status"]) for d in self.listing()), [("intentional", "superseded"), ("prefer", "active")])
        self.client.post(f"/api/projects/{self.project_id}/assistant/changes/{task['changes'][0]['id']}/undo", headers=self.idem(), json={"confirm": False})
        self.assertEqual([(d["kind"], d["status"]) for d in self.listing()], [("intentional", "active")])

    def test_the_materials_page_edits_and_deletes_a_decision_by_its_revision(self):
        self.confirm(self.put(self.answered()))
        decision = self.listing()[0]
        base = f"/api/projects/{self.project_id}/decisions/{decision['id']}"
        r = self.client.patch(base, headers=self.idem(), json={"base_revision": decision["revision"], "subjects": ["苏岑", "温岚"], "whole_work": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["data"]["decision"]["subjects"], r.json()["data"]["decision"]["chapters"]), (["苏岑", "温岚"], None))
        stale = self.client.patch(base, headers=self.idem(), json={"base_revision": decision["revision"], "statement": "旧版本上的改动"})
        self.assertEqual(stale.status_code, 409)
        r = self.client.post(base + "/delete", headers=self.idem(), json={"base_revision": decision["revision"] + 1})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.listing(), [])

    def test_the_tasks_words_or_chapters_pick_at_most_five_decisions(self):
        with self.db.connection() as c:
            for n in range(7):
                decisions.write(c, self.db, self.project_id, f"decision-{n}", record(f"第{n}条", subjects=(f"人物{n}",), chapters=(n + 1, n + 1)),
                                self.user_id, f"2026-10-30T00:00:0{n}")
            decisions.write(c, self.db, self.project_id, "decision-style", record("回答短一点", kind="style", subjects=(), chapters=None),
                            self.user_id, "2026-10-30T00:00:09")
            picked = decisions.relevant(c, self.project_id, "人物2和人物5怎么了", None)
            self.assertEqual([d["statement"] for d in picked], ["回答短一点", "第5条", "第2条"])  # the style always, then names, newest first
            self.assertEqual([d["statement"] for d in decisions.relevant(c, self.project_id, "", (3, 4))], ["回答短一点", "第3条", "第2条"])
            self.assertEqual(len(decisions.relevant(c, self.project_id, "".join(f"人物{n}" for n in range(7)), None)), decisions.RELEVANT_MAX)
            self.assertEqual(decisions.mark_stale(c, self.project_id, {7}, "2026-10-30T01:00:00"), 8)  # every one stands on chapter 7 here

    def test_decisions_go_into_the_export_and_with_the_work(self):
        self.confirm(self.put(self.answered()))
        snapshot = self.client.get(f"/api/projects/{self.project_id}/export?format=json")
        if snapshot.status_code == 200:
            self.assertIn("她第 7 章的年龄", snapshot.text)
        with self.db.connection() as c:
            from app.project_export import project_snapshot
            self.assertEqual(len(project_snapshot(self.db, self.user_id, self.project_id)["decisions"]), 1)
            self.db.purge_project(c, self.project_id)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM v2_author_decisions")[0]["n"], 0)

    def test_an_undone_resolve_may_be_remembered_as_a_thread_kept_open(self):
        from app.assistant_actions import change_view
        version = self.client.get(f"/api/projects/{self.project_id}/foreshadows").json()["data"]["foreshadow_version"]
        chapter = self.rows("SELECT id FROM v2_chapters WHERE project_id=? ORDER BY chapter_number LIMIT 1", self.project_id)[0]["id"]
        r = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=self.idem(), json={
            "base_foreshadow_version": version, "title": "冰下三声", "description": "三声敲击还没有交代", "status": "planted", "planted_chapter_id": chapter})
        self.assertEqual(r.status_code, 201, r.text)
        thread = {"id": r.json()["data"]["item"]["id"], "title": "冰下三声"}
        task = self.answered()
        stamp = "2026-10-30T02:00:00+00:00"
        with self.db.connection() as c:  # an undone "resolved" item, as the ledger keeps it
            c.execute("INSERT INTO assistant_changes(id,task_id,project_id,ordinal,kind,target_id,before_json,after_json,display_json,evidence_json,status,created_at,undone_at) "
                      "VALUES('achange-undone',?,?,1,'resolve_thread',?,'{}','{}',?,'[]','undone',?,?)",
                      (task["id"], self.project_id, thread["id"], '{"title": "x", "before": "a", "after": "b"}', stamp, stamp))
            self.assertTrue(change_view(c, self.db, c.execute("SELECT * FROM assistant_changes WHERE id='achange-undone'").fetchone())["rememberable"])
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/changes/achange-undone/remember", headers=self.idem(), json={})
        self.assertEqual(r.status_code, 200, r.text)
        item = r.json()["data"]["change"]
        self.assertEqual((item["kind"], item["title"], item["status"]), ("add_decision", "记下决定·先别收", "proposed"))
        self.assertIn(thread["title"], item["after"])
        again = self.client.post(f"/api/projects/{self.project_id}/assistant/changes/achange-undone/remember", headers=self.idem(), json={})
        self.assertEqual(again.status_code, 409)
        self.confirm(self.task(task["id"]), [item["id"]])
        self.assertEqual([(d["kind"], d["foreshadow_id"], d["source"]) for d in self.listing()], [("keep_open", thread["id"], "undo")])

    def test_the_model_cannot_propose_a_decision(self):
        from app.assistant_actions import ACTIONS
        from app.assistant_tools import ToolError
        with self.assertRaises(ToolError):
            ACTIONS["add_decision"].propose(None, {}, None)


if __name__ == "__main__":
    unittest.main()
