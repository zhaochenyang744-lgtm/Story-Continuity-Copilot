"""v2.2: the author's decisions, kept as records of their own and written only by a card the author confirms."""
from __future__ import annotations

import json
import unittest

from app import assistant_decisions as decisions

from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, ref_of_chapter, turn


def record(statement="她第 7 章的年龄和第 3 章不同是有意的", kind="intentional", subjects=("苏岑",), chapters=(3, 7), **extra):
    return {"kind": kind, "statement": statement, "subjects": list(subjects), "chapters": list(chapters) if chapters else None,
            "foreshadow_id": None, "prefer_chapter": None, "quote": "她年龄不统一是故意的", "source": "box", "source_ref": None,
            "basis_chapter": 7, **extra}

def clear_sample(case):
    """The sample work comes with two decisions of its own; these tests start from none."""
    with case.db.connection() as c:
        c.execute("DELETE FROM v2_author_decisions WHERE project_id=?", (case.project_id,))


class DecisionCardTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()
        clear_sample(self)

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


class UseTests(AssistantCase):
    """A decision in force reaches the tasks it touches: in the prompt, citable, and kept by the change card."""

    def setUp(self):
        self.start()
        self.register()
        clear_sample(self)
        self.name = self.rows("SELECT DISTINCT subject FROM v2_memory_records WHERE project_id=? LIMIT 1", self.project_id)[0]["subject"]
        with self.db.connection() as c:
            decisions.write(c, self.db, self.project_id, "decision-age", record(f"{self.name}前后年龄不同是有意的", subjects=(self.name,), chapters=None),
                            self.user_id, "2026-10-30T00:00:00+00:00")

    def test_the_decision_is_in_the_prompt_with_a_number_the_answer_may_cite(self):
        def cite_decision(provider, messages):
            first = next(m["content"] for m in messages if m["role"] == "user")
            self.assertIn("作者定过的决定", first)
            ref = first.split("[", 1)[1].split("]", 1)[0]
            return turn(answer_call("answered", [("作者定过这处年龄不同是有意的。", [ref])]))
        task = self.run_ask(cite_decision, question=f"{self.name}的年龄前后不一样吗？")
        self.assertEqual(task["status"], "completed", task.get("error_code"))
        self.assertEqual([s["kind"] for s in task["sources"].values()], ["decision"])

    def test_a_question_about_someone_else_is_not_given_the_decision(self):
        def look(provider, messages):
            self.assertNotIn("作者定过的决定", next(m["content"] for m in messages if m["role"] == "user"))
            return turn(call("read_chapter", chapter_number=9))
        def cite(provider, messages):
            return turn(answer_call("answered", [("第九章写到了。", [ref_of_chapter(messages, 9)])]))
        self.run_ask(look, cite, question="第九章那个陌生人是谁？")

    def test_a_thread_kept_open_is_not_marked_resolved(self):
        from app.assistant_actions import propose_resolve_thread
        from app.assistant_tools import ToolError
        version = self.client.get(f"/api/projects/{self.project_id}/foreshadows").json()["data"]["foreshadow_version"]
        chapter = self.rows("SELECT id FROM v2_chapters WHERE project_id=? ORDER BY chapter_number LIMIT 1", self.project_id)[0]["id"]
        r = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=self.idem(), json={
            "base_foreshadow_version": version, "title": "冰下三声", "description": "三声敲击还没有交代", "status": "planted", "planted_chapter_id": chapter})
        thread = r.json()["data"]["item"]["id"]
        with self.db.connection() as c:
            decisions.write(c, self.db, self.project_id, "decision-open", record("冰下三声先别收", kind="keep_open", subjects=("冰下三声",), chapters=None,
                                                                              foreshadow_id=thread), self.user_id, "2026-10-30T00:00:01+00:00")
        from types import SimpleNamespace
        ctx = SimpleNamespace(db=self.db, project_id=self.project_id)
        with self.assertRaises(ToolError) as raised:
            propose_resolve_thread(ctx, {"evidence": []}, {"object_id": thread})
        self.assertEqual(raised.exception.code, "change_thread_kept_open")


class LongTaskTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()
        clear_sample(self)
        self.name = self.rows("SELECT DISTINCT subject FROM v2_memory_records WHERE project_id=? LIMIT 1", self.project_id)[0]["subject"]
        self.found = {"text": f"{self.name}的年龄两处写法不同", "options": [{"key": "a", "chapter": 3, "quote": "十七岁"}, {"key": "b", "chapter": 9, "quote": "十八岁"}]}

    def test_a_question_the_author_has_decided_is_answered_by_the_decision(self):
        from app.long_tasks import LongTasks as LongTaskRunner
        decided = LongTaskRunner._decided
        with self.db.connection() as c:
            self.assertIsNone(decided(c, self.project_id, self.found))
            decisions.write(c, self.db, self.project_id, "decision-prefer", record(f"{self.name}的年龄以第 3 章为准", kind="prefer", subjects=(self.name,),
                                                                                chapters=None, prefer_chapter=3), self.user_id, "2026-10-30T00:00:00+00:00")
            self.assertEqual(decided(c, self.project_id, self.found), ("a", "decision-prefer"))
            other = {**self.found, "text": "罗盘的去向两处写法不同"}
            self.assertIsNone(decided(c, self.project_id, other))  # another matter: asked as before

    def test_the_authors_pick_becomes_a_decision_for_the_end_of_the_report(self):
        from app.long_tasks import LongTasks as LongTaskRunner
        def cite(provider, messages):
            return turn(answer_call("answered", [("第九章写到了她。", [ref_of_chapter(messages, 9)])]))
        self.run_ask(turn(call("read_chapter", chapter_number=9)), cite)
        with self.db.connection() as c:
            task_id = c.execute("SELECT id FROM assistant_tasks WHERE project_id=? LIMIT 1", (self.project_id,)).fetchone()["id"]
            LongTaskRunner._choice_card(c, self.project_id, task_id, {**self.found, "choices": ["a", "b", "both", "you_decide"]}, "both")
            item = c.execute("SELECT * FROM assistant_changes WHERE task_id=?", (task_id,)).fetchone()
        self.assertEqual(item["kind"], "add_decision")
        self.assertIn("两处都保留", json.loads(item["display_json"])["after"])


class RecognitionTests(AssistantCase):
    """The author's sentence read for a decision beside the task (`assistant_recognize`), the card the program makes of it."""

    def setUp(self):
        self.start(assistant_recognize_decisions=True)
        self.register()
        clear_sample(self)
        self.names = [row["subject"] for row in self.rows("SELECT DISTINCT subject FROM v2_memory_records WHERE project_id=?", self.project_id)]

    def asked(self, question, decision):
        self.provider.script_route({"decision": decision})

        def cite(provider, messages):
            return turn(answer_call("answered", [("第九章写到了这里。", [ref_of_chapter(messages, 9)])]))
        return self.run_ask(turn(call("read_chapter", chapter_number=9)), cite, question=question)

    def decision(self, name, **extra):
        return {"kind": "intentional", "statement": f"{name}前后年龄不同是有意的", "words": "是故意的", "subjects": [name], "chapters": [3, 7], **extra}

    def test_a_question_that_also_says_a_decision_gets_its_card_and_a_line(self):
        name = self.names[0]
        task = self.asked(f"{name}年龄前后不一样是故意的，你看看第九章还有哪里提到", self.decision(name))
        self.assertEqual(task["status"], "completed")
        self.assertEqual([(i["kind"], i["status"]) for i in task["changes"]], [("add_decision", "proposed")])
        self.assertIn(name, task["changes"][0]["after"])
        self.assertEqual(task["changes"][0]["quote"], f"{name}年龄前后不一样是故意的，你看看第九章还有哪里提到")
        from app.assistant import DECISION_CARD_LINE
        self.assertIn(DECISION_CARD_LINE, task["answer"]["note"])
        recognized = self.provider.route_calls[0]["messages"][1]["content"]
        self.assertIn("是故意的", recognized)
        self.assertNotIn("第九章写到了", recognized)  # the call reads the author's words only

    def test_no_decision_no_card(self):
        task = self.asked("她的年龄前后不一样吗？", None)
        self.assertNotIn("changes", task)

    def test_words_that_are_not_the_authors_or_names_not_the_works_are_not_kept(self):
        name = self.names[0]
        task = self.asked(f"{name}的年龄你查一下", self.decision(name))  # "是故意的" is not in the sentence
        self.assertNotIn("changes", task)
        task = self.asked(f"{name}和花无影年龄不一样是故意的", self.decision(name, subjects=[name, "花无影"]))
        self.assertEqual(task["changes"][0]["after"].count("花无影"), 0)  # a name the work does not have is left out

    def test_a_preferred_chapter_must_be_the_works(self):
        name = self.names[0]
        task = self.asked(f"{name}的年龄以第九十九章为准", self.decision(name, kind="prefer", words="以第九十九章为准", prefer_chapter=99))
        self.assertNotIn("changes", task)

    def test_a_new_decision_about_the_same_name_replaces_the_old_one(self):
        name = self.names[0]
        task = self.asked(f"{name}年龄前后不一样是故意的", self.decision(name))
        self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                         json={"accepted": [task["changes"][0]["id"]]})
        task = self.asked(f"{name}的年龄还是以第三章为准吧", self.decision(name, kind="prefer", words="以第三章为准", prefer_chapter=3, statement=f"{name}的年龄以第三章为准"))
        self.assertEqual(task["changes"][0]["replaces"], f"{name}前后年龄不同是有意的")


class CheckTests(AssistantCase):
    """The sample work's check, held against the author's decisions, and a check decision's note made into a card."""

    def setUp(self):
        self.start(assistant_recognize_decisions=True)
        self.register()
        clear_sample(self)
        project = self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        self.run = self.client.get(f"/api/projects/{self.project_id}/checks/{project['latest_run']['run_id']}?include=issues,evidence").json()["data"]
        self.issue = next(issue for issue in self.run["issues"] if "keep_intentional" in (issue.get("available_actions") or []))
        names = [row["subject"] for row in self.rows("SELECT DISTINCT subject FROM v2_memory_records WHERE project_id=?", self.project_id)]
        self.name = next((n for n in sorted(names, key=len, reverse=True) if n in self.issue["claim_text"]), names[0])

    def test_a_finding_a_decision_covers_is_passed_over_and_one_it_does_not_is_kept(self):
        from app import assistant_cover
        with self.db.connection() as c:
            decisions.write(c, self.db, self.project_id, "decision-cover", record(f"{self.name}这处前后不同是有意的", subjects=(self.name,), chapters=None),
                            self.user_id, "2026-10-30T00:00:00+00:00")
        self.provider.script_route(*([{"covers": 1, "draft_follows_preferred": None}] * 20))
        passed = assistant_cover.cover_run(self.db, self.provider, self.project_id, self.run["run_id"])
        self.assertGreaterEqual(passed, 1)
        issues = self.client.get(f"/api/projects/{self.project_id}/checks/{self.run['run_id']}?include=issues").json()["data"]["issues"]
        covered = next(issue for issue in issues if issue["id"] == self.issue["id"])
        self.assertEqual((covered["reused_decision"]["status"], covered["reused_decision"]["statement"]), ("author_decision", f"{self.name}这处前后不同是有意的"))
        self.assertFalse(covered["reused_decision"]["possibly_out_of_date"])
        with self.db.connection() as c:
            decisions.mark_stale(c, self.project_id, {7}, "2026-10-30T00:00:01+00:00")
        issues = self.client.get(f"/api/projects/{self.project_id}/checks/{self.run['run_id']}?include=issues").json()["data"]["issues"]
        self.assertTrue(next(issue for issue in issues if issue["id"] == self.issue["id"])["reused_decision"]["possibly_out_of_date"])
        messages = self.provider.route_calls[0]["messages"][1]["content"]
        self.assertIn("作者定过的决定", messages)
        # Deleted, the decision no longer passes the finding over.
        listed = self.client.get(f"/api/projects/{self.project_id}/decisions").json()["data"]["decisions"][0]
        self.client.post(f"/api/projects/{self.project_id}/decisions/{listed['id']}/delete", headers=self.idem(), json={"base_revision": listed["revision"]})
        issues = self.client.get(f"/api/projects/{self.project_id}/checks/{self.run['run_id']}?include=issues").json()["data"]["issues"]
        self.assertIsNone(next(issue for issue in issues if issue["id"] == self.issue["id"])["reused_decision"])

    def test_a_finding_is_held_against_the_decisions_before_the_check_reads_as_completed(self):
        from unittest import mock
        from app import assistant_cover
        with self.db.connection() as c:
            decisions.write(c, self.db, self.project_id, "decision-cover", record(f"{self.name}这处前后不同是有意的", subjects=(self.name,), chapters=None),
                            self.user_id, "2026-10-30T00:00:00+00:00")
        engine = self.app.state.engine

        def review(data):  # one finding on the draft's first sentence that names the decision's subject
            claim = next(claim for claim in data["claims"] if self.name in claim["text"]) if any(self.name in cl["text"] for cl in data["claims"]) else data["claims"][0]
            return {"status": "completed", "issues": [{"claim_span_id": claim["id"], "status": "conflict", "category": "continuity", "severity": "high",
                                                       "evidence_status": "sufficient", "explanation": f"{self.name}前后写法不同", "evidence": []}]}
        seen = []
        real = assistant_cover.cover_run

        def watched(db, provider, project_id, run_id, issues=None):
            with db.connection() as c:
                seen.append(c.execute("SELECT status FROM v2_runs WHERE id=?", (run_id,)).fetchone()["status"])
            return real(db, provider, project_id, run_id, issues)
        self.provider.script_route(*([{"covers": 1, "draft_follows_preferred": None}] * 5))
        draft = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["current_draft"]
        with mock.patch.object(engine, "execute", review), mock.patch.object(type(engine.provider), "available", True, create=True), \
                mock.patch.object(assistant_cover, "cover_run", watched):
            r = self.client.post(f"/api/projects/{self.project_id}/checks", headers=self.idem(), json={"draft_id": draft["id"], "draft_revision": draft["revision"]})
        self.assertEqual(r.status_code, 202, r.text)
        run = self.client.get(f"/api/projects/{self.project_id}/checks/{r.json()['data']['run_id']}?include=issues").json()["data"]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(seen, ["running"])  # held against the decisions while the run was still running
        self.assertEqual(run["issues"][0]["reused_decision"]["status"], "author_decision")

    def test_no_decision_no_call(self):
        from app import assistant_cover
        self.provider.script_route()
        self.assertEqual(assistant_cover.cover_run(self.db, self.provider, self.project_id, self.run["run_id"]), 0)
        self.assertEqual(self.provider.route_calls, [])

    def test_a_note_that_says_a_decision_makes_a_card_once_scoped_to_the_finding(self):
        self.provider.script_route({"decision": {"kind": "intentional", "statement": "这处前后不同是有意的", "words": "是故意这么写的", "subjects": [], "chapters": None}})
        body = {"run_id": self.run["run_id"], "source_revision": self.run["source_revision"], "decision": "keep_intentional", "note": "这里是故意这么写的"}
        headers = self.idem()
        r = self.client.post(f"/api/projects/{self.project_id}/issues/{self.issue['id']}/decision", headers=headers, json=body)
        self.assertIn(r.status_code, (200, 201), r.text)
        card = r.json()["data"]["memory_card"]
        task = self.task(card["task_id"])
        item = task["changes"][0]
        self.assertEqual((item["kind"], item["status"], item["quote"]), ("add_decision", "proposed", "这里是故意这么写的"))
        self.assertNotIn("管：全书", item["after"])  # a note naming nobody is scoped to the finding (its names), never the whole work
        again = self.client.post(f"/api/projects/{self.project_id}/issues/{self.issue['id']}/decision", headers=headers, json=body)
        self.assertEqual(again.json()["data"].get("memory_card", card), card)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM assistant_changes WHERE kind='add_decision'")[0]["n"], 1)

    def test_a_note_that_says_no_decision_makes_no_card(self):
        self.provider.script_route({"decision": None})
        body = {"run_id": self.run["run_id"], "source_revision": self.run["source_revision"], "decision": "false_positive", "note": "看着像错其实没问题"}
        r = self.client.post(f"/api/projects/{self.project_id}/issues/{self.issue['id']}/decision", headers=self.idem(), json=body)
        self.assertNotIn("memory_card", r.json()["data"])


class ReviewFixTests(AssistantCase):
    """The front-end review of 2026-10-30 (Desktop/v2.2任务/13-前端评审报告.md), its findings on the backend."""

    def setUp(self):
        self.start(assistant_recognize_decisions=True)
        self.register()
        clear_sample(self)
        self.names = [row["subject"] for row in self.rows("SELECT DISTINCT subject FROM v2_memory_records WHERE project_id=?", self.project_id)]
        self.name = max(self.names, key=len)

    def thread(self, title):
        version = self.client.get(f"/api/projects/{self.project_id}/foreshadows").json()["data"]["foreshadow_version"]
        chapter = self.rows("SELECT id FROM v2_chapters WHERE project_id=? ORDER BY chapter_number LIMIT 1", self.project_id)[0]["id"]
        r = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=self.idem(), json={
            "base_foreshadow_version": version, "title": title, "description": "还没有交代", "status": "planted", "planted_chapter_id": chapter})
        return r.json()["data"]["item"]["id"]

    def test_a_thread_kept_open_is_given_when_named_by_part_of_its_title_and_every_decision_when_asked_about_them(self):  # E02
        thread = self.thread("白色渡船与失去的署名")
        with self.db.connection() as c:
            decisions.write(c, self.db, self.project_id, "decision-open", record("白色渡船那条先别收", kind="keep_open", subjects=("白色渡船与失去的署名",),
                                                                              chapters=None, foreshadow_id=thread), self.user_id, "2026-10-30T00:00:00+00:00")
            decisions.write(c, self.db, self.project_id, "decision-age", record(f"{self.name}前后不同是有意的", subjects=(self.name,), chapters=None),
                            self.user_id, "2026-10-30T00:00:01+00:00")
            self.assertEqual([d["id"] for d in decisions.relevant(c, self.project_id, "白色渡船这条现在该回收吗？")], ["decision-open"])
            self.assertEqual(decisions.relevant(c, self.project_id, "我之前决定哪些伏笔先别收？"), [])
            self.assertEqual({d["id"] for d in decisions.relevant(c, self.project_id, "我之前决定哪些伏笔先别收？", authors_words=True)},
                             {"decision-open", "decision-age"})

    def test_a_writing_preference_is_how_to_write_not_a_source(self):  # E02
        with self.db.connection() as c:
            decisions.write(c, self.db, self.project_id, "decision-style", record("以后回答短一点", kind="style", subjects=(), chapters=None),
                            self.user_id, "2026-10-30T00:00:00+00:00")

        def look(provider, messages):
            first = next(m["content"] for m in messages if m["role"] == "user")
            self.assertIn("作者对回答的写法偏好", first)
            self.assertIn("以后回答短一点", first)
            self.assertNotIn("作者定过的决定（作者自己确认过", first)
            return turn(call("read_chapter", chapter_number=9))

        def cite(provider, messages):
            return turn(answer_call("answered", [("第九章写到了。", [ref_of_chapter(messages, 9)])]))
        self.provider.script_route({"decision": None})
        task = self.run_ask(look, cite, question="第九章写了什么？")
        self.assertEqual(task["status"], "completed")
        self.assertNotIn("decision", [s["kind"] for s in task["sources"].values()])

    def recognized(self, sentence, found):
        from app import assistant_recognize
        with self.db.connection() as c:
            return assistant_recognize.ground(c, self.project_id, sentence, {"words": "", "subjects": [], "chapters": None, "prefer_chapter": None,
                                                                            "thread": "", "statement": "决定", **found})

    def test_the_chapter_that_holds_is_not_the_chapters_covered_and_a_name_inside_a_phrase_is_found(self):  # E03
        record_, _ = self.recognized(f"关于{self.name}的说法，以后以第3章为准", {"kind": "prefer", "words": "以第3章为准", "subjects": [f"{self.name}的说法"],
                                                                          "chapters": [3, 3], "prefer_chapter": 3})
        self.assertEqual((record_["chapters"], record_["prefer_chapter"], record_["subjects"]), (None, 3, [self.name]))

    def test_a_new_decision_replaces_the_one_about_a_name_the_author_says(self):  # E03
        with self.db.connection() as c:
            decisions.write(c, self.db, self.project_id, "decision-old", record(f"{self.name}这处是有意的", subjects=(self.name,), chapters=None),
                            self.user_id, "2026-10-30T00:00:00+00:00")
        _, replaces = self.recognized(f"关于{self.name}，我改主意了：以后以第3章为准", {"kind": "prefer", "words": "以第3章为准", "prefer_chapter": 3})
        self.assertEqual(replaces["id"], "decision-old")

    def test_another_name_of_the_works_stands_for_its_name(self):  # A4 dev run: 蓼仔 for 孟苒箴
        with self.db.connection() as c:
            version = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (self.project_id,)).fetchone()[0]
            span = c.execute("SELECT id FROM v2_source_spans WHERE project_id=? LIMIT 1", (self.project_id,)).fetchone()[0]
            c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status) "
                      "VALUES('mem-alias',?,?,'character',?,'别名','阿岑、小岑',?,'author_confirmed')", (self.project_id, version, self.name, span))
        record_, _ = self.recognized("阿岑的年岁两版都别统一，是故意的", {"kind": "intentional", "words": "是故意的", "subjects": ["阿岑", "年岁"]})
        self.assertEqual(record_["subjects"], [self.name])
        with self.db.connection() as c:
            decisions.write(c, self.db, self.project_id, "decision-age", record(f"{self.name}前后不同是有意的", subjects=(self.name,), chapters=None),
                            self.user_id, "2026-10-30T00:00:00+00:00")
            self.assertEqual([d["id"] for d in decisions.relevant(c, self.project_id, "小岑的年岁到底该引用哪一处？")], ["decision-age"])

    def test_giving_a_thread_up_is_not_keeping_it_open(self):  # E04
        self.thread("移交单上的窄纸")
        found = {"kind": "keep_open", "thread": "移交单上的窄纸"}
        self.assertIsNone(self.recognized("我决定放弃移交单上的窄纸这条伏笔，不再继续写它", {**found, "words": "放弃"}))
        self.assertIsNotNone(self.recognized("移交单上的窄纸那条先别收，后面还要写", {**found, "words": "先别收"}))

    def test_a_decision_with_nothing_to_look_up_says_so_instead_of_not_found(self):  # E05
        from app.assistant import DECISION_ONLY_LINE
        self.provider.script_route({"decision": {"kind": "style", "statement": "以后回答短一点", "words": "回答短一点", "subjects": [], "chapters": None}})
        task = self.run_ask(turn(answer_call("not_found", [], note="只能查正文，这句话没有要查的内容。")), question="以后回答短一点")
        self.assertEqual(task["answer"]["note"], DECISION_ONLY_LINE)
        self.assertEqual([i["kind"] for i in task["changes"]], ["add_decision"])


from tests.test_v210_long_tasks import LongCase  # noqa: E402


class LongRecognitionTests(LongCase):
    """A long task's request read for a decision beside its plan call; the card waits for the end of the report."""

    def setUp(self):
        super().setUp()
        clear_sample(self)
        import dataclasses
        self.long.settings = dataclasses.replace(self.long.settings, assistant_recognize_decisions=True)

    def script(self, decision):
        from app.assistant_recognize import SYSTEM_PROMPT
        def answer(provider, messages):
            if messages[0]["content"] == SYSTEM_PROMPT:
                return {"decision": decision}
            return {"type": "thread_audit", "target": None, "chapters": None, "output": "list"}
        self.provider.script_route(answer, answer)

    def test_a_request_that_also_keeps_a_thread_open_gets_its_card(self):
        self.script({"kind": "keep_open", "statement": "罗盘下落这条伏笔先别收", "words": "先别收", "subjects": [], "chapters": None, "thread": "罗盘下落"})
        task = self.create("罗盘下落那条先别收，其余还吊着的伏笔都替我过一遍")
        view = self.view(task["id"])
        self.assertEqual(view["status"], "awaiting_plan")
        self.assertEqual([(i["kind"], i["status"]) for i in view["changes"]], [("add_decision", "proposed")])
        self.assertIn("罗盘下落", view["changes"][0]["after"])
        self.assertEqual([r["role"] for r in self.rows("SELECT role FROM assistant_long_calls WHERE task_id=? ORDER BY seq", task["id"])], ["plan", "requests"])

    def test_a_request_with_no_decision_has_no_card(self):
        self.script(None)
        task = self.create()
        self.assertEqual(self.view(task["id"])["changes"], [])


if __name__ == "__main__":
    unittest.main()
