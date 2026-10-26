"""v2.1 batch two of the assistant's actions: `add_thread`, `edit_thread` and `abandon_thread`, and the two things an action now
registers (`risk`, `evidence_required`). They go through the same card, confirm, undo and redo as the first three; these tests
cover what is new: the checks of each proposal, what is written and put back, the author's edits in between, and how the
request list decides between the kinds."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app import assistant_actions, assistant_requests
from app.assistant_actions import ACTIONS, WANT_REFUSALS, run_propose_change
from app.assistant_tools import ERROR_HINTS, ERROR_TEXTS, ToolError, tools_for

from tests.scripted_chat import answer_call, call, tool_items, turn
from tests.test_v200_changes import ChangeCase, change_call, refs

NOTE = "（示意）改后的说明"


class ThreadActionCase(ChangeCase):
    def thread_turns(self, make, chapters=None, answer=True):
        """Turns that list the threads, read the chapters given (the last by default), propose what `make(messages)` returns and answer."""
        chapters = chapters or [self.last]

        def propose(provider, messages):
            return turn(change_call(**make(messages)))

        def close(provider, messages):
            return turn(answer_call("answered", [("最后一章写到了这件事。", [refs(messages, chapters[-1])[0]])]))

        return [turn(call("list_threads"), *[call("read_chapter", chapter_number=number) for number in chapters]), propose] + ([close] if answer else [])

    def thread_ref(self, messages, title="罗盘下落"):
        return next(item["ref"] for item in tool_items(messages) if item["text"].startswith(f"伏笔：{title}"))

    def step_error(self, task):
        return [s["error_code"] for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "propose_change"][-1]

    def threads(self, archived=False):
        return self.rows("SELECT * FROM v2_foreshadows WHERE project_id=?" + ("" if archived else " AND archived_at IS NULL"), self.project_id)

    def foreshadow_version(self):
        return self.rows("SELECT foreshadow_version v FROM v2_projects WHERE id=?", self.project_id)[0]["v"]

    def events(self, thread_id):
        return [r["event"] for r in self.rows("SELECT event FROM v2_foreshadow_versions WHERE item_id=? ORDER BY version", thread_id)]

    def redo(self, change_id, expect=200):
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/changes/{change_id}/redo", headers=self.idem(), json={})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def abandoning(self, title="罗盘下落", words="罗盘那条线", **extra):
        return self.thread_turns(lambda m: {"action": "abandon_thread", "target": self.thread_ref(m, title), "evidence": [], "request_words": words, **extra})

    def editing(self, value=NOTE, title="罗盘下落", words="罗盘那条伏笔", **extra):
        return self.thread_turns(lambda m: {"action": "edit_thread", "target": self.thread_ref(m, title), "value": value, "evidence": [], "request_words": words, **extra})

    def adding(self, title="门后的叩响", value="门后传来三声叩响，没有人应。", chapters=None, words="最后一章埋了个悬念", **extra):
        chapters = chapters or [self.last]

        def make(messages):
            return {"action": "add_thread", "title": title, "value": value, "evidence": [refs(messages, number)[0] for number in chapters],
                    "request_words": words, **extra}
        return self.thread_turns(make, chapters)

    ABANDON_ASK = "罗盘那条线不追了"
    EDIT_ASK = "罗盘那条伏笔的说明改一改"
    ADD_ASK = "最后一章埋了个悬念，加一条伏笔"


class RegistrationTests(ThreadActionCase):
    def test_every_action_registers_its_risk_and_whether_it_needs_evidence(self):
        self.assertEqual({kind: (action.risk, action.evidence_required) for kind, action in ACTIONS.items()},
                         {"resolve_thread": ("low", True), "change_fact": ("low", True), "add_fact": ("low", True), "add_thread": ("low", True),
                          "edit_thread": ("low", False), "abandon_thread": ("high", False)})
        self.assertEqual(assistant_actions.Action.__dataclass_fields__["risk"].default, "low")
        self.assertIs(assistant_actions.Action.__dataclass_fields__["evidence_required"].default, True)

    def test_the_card_data_carries_both(self):
        task = self.change_task(*self.resolving())
        self.assertEqual((task["changes"][0]["risk"], task["changes"][0]["evidence_required"]), ("low", True))
        task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        self.assertEqual((task["changes"][0]["risk"], task["changes"][0]["evidence_required"]), ("high", False))
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        self.assertEqual((task["changes"][0]["risk"], task["changes"][0]["evidence_required"]), ("low", False))
        self.confirm(task)
        ledger = self.client.get(f"/api/projects/{self.project_id}/assistant/changes").json()["data"]["changes"]
        self.assertEqual((ledger[0]["risk"], ledger[0]["evidence_required"]), ("low", False))

    def test_the_tool_takes_the_new_actions_and_an_empty_evidence(self):
        [schema] = [tool for tool in tools_for("change", {"draft_readable": False}) if tool["function"]["name"] == "propose_change"]
        properties = schema["function"]["parameters"]["properties"]
        self.assertEqual(properties["action"]["enum"], ["resolve_thread", "change_fact", "add_fact", "add_thread", "edit_thread", "abandon_thread"])
        self.assertEqual(properties["evidence"]["minItems"], 0)
        self.assertEqual(properties["title"]["maxLength"], 30)
        for kind in ("add_thread", "edit_thread", "abandon_thread"):
            self.assertIn(kind + "：", schema["function"]["description"])

    def test_an_action_that_needs_evidence_is_refused_without_it(self):
        task = self.change_task(*self.thread_turns(lambda m: {"action": "resolve_thread", "target": self.thread_ref(m), "evidence": []}))
        self.assertEqual(self.step_error(task), "change_evidence_invalid")
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        self.assertEqual(task["changes"][0]["evidence_required"], True)

    def test_evidence_that_is_given_is_checked_all_the_same(self):
        task = self.change_task(*self.thread_turns(lambda m: {"action": "abandon_thread", "target": self.thread_ref(m), "evidence": [self.thread_ref(m)],
                                                              "request_words": "罗盘那条线"}), question=self.ABANDON_ASK)
        self.assertEqual(self.step_error(task), "change_evidence_invalid")
        task = self.change_task(*self.thread_turns(lambda m: {"action": "edit_thread", "target": self.thread_ref(m), "value": NOTE, "evidence": ["R99"],
                                                              "request_words": "罗盘那条伏笔"}), question=self.EDIT_ASK)
        self.assertEqual(self.step_error(task), "change_evidence_invalid")
        task = self.change_task(*self.thread_turns(lambda m: {"action": "abandon_thread", "target": self.thread_ref(m), "evidence": [refs(m, self.last)[0]],
                                                              "request_words": "罗盘那条线"}), question=self.ABANDON_ASK)
        self.assertEqual(len(task["changes"][0]["evidence"]), 1)  # a real passage may stand beside the author's word


class AbandonThreadTests(ThreadActionCase):
    def test_a_thread_given_up_waits_on_the_card_with_no_evidence_and_nothing_is_written(self):
        version = self.foreshadow_version()
        task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        [item] = task["changes"]
        self.assertEqual((item["kind"], item["status"], item["title"], item["editable"]), ("abandon_thread", "proposed", "罗盘下落", False))
        self.assertEqual((item["before"], item["after"]), ("已埋设", "已放弃"))
        self.assertEqual((item["evidence"], item["request_words"]), ([], "罗盘那条线"))
        self.assertEqual(item["target"], {"kind": "foreshadow", "id": self.thread_id})
        self.assertFalse(item["changed_since"])
        self.assertEqual((self.thread()["status"], self.foreshadow_version()), ("planted", version))

    def test_confirm_marks_it_given_up_and_undo_puts_every_field_back(self):
        self.patch_thread(status="developing")
        before = dict(self.thread())
        task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        self.assertEqual(task["changes"][0]["before"], "推进中")
        version = self.foreshadow_version()
        self.confirm(task)
        row = self.thread()
        self.assertEqual((row["status"], row["resolved_chapter_id"], row["resolved_source_span_id"], row["version"]), ("abandoned", None, None, before["version"] + 1))
        self.assertEqual((row["title"], row["description"], row["planted_chapter_id"], row["archived_at"]),
                         (before["title"], before["description"], before["planted_chapter_id"], None))
        self.assertEqual((self.events(self.thread_id)[-1], self.foreshadow_version()), ("updated", version + 1))
        change = task["changes"][0]["id"]
        self.assertEqual(self.undo(change)["data"]["changes"][0]["status"], "undone")
        back = self.thread()
        for field in ("status", "resolved_chapter_id", "resolved_source_span_id", "title", "description", "planted_chapter_id", "planted_source_span_id", "archived_at"):
            self.assertEqual(back[field], before[field], field)
        self.assertEqual(back["version"], before["version"] + 2)
        self.redo(change)
        self.assertEqual(self.thread()["status"], "abandoned")
        self.assertEqual([r["event"] for r in self.rows("SELECT event FROM assistant_change_events ORDER BY rowid")], ["applied", "undone", "redone"])

    def test_the_ledger_shows_it_with_its_thread(self):
        task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        self.confirm(task)
        [entry] = self.client.get(f"/api/projects/{self.project_id}/assistant/changes").json()["data"]["changes"]
        self.assertEqual((entry["kind"], entry["target"], entry["after"], entry["risk"]), ("abandon_thread", {"kind": "foreshadow", "id": self.thread_id}, "已放弃", "high"))

    def test_a_thread_no_longer_open_cannot_be_given_up(self):
        for status in ("resolved", "abandoned"):
            self.patch_thread(status=status)
            task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
            self.assertEqual(self.step_error(task), "change_thread_not_open", status)
            self.assertEqual(task["changes"], [])
            self.patch_thread(status="planted", resolved_chapter_id=None)

    def test_the_thread_the_author_changed_since_the_card_stops_the_confirm(self):
        task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        self.patch_thread(status="developing")
        self.assertTrue(self.task(task["id"])["changes"][0]["changed_since"])
        error = self.confirm(task, expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_target_changed", {"changes": ["C1"]}))
        self.assertEqual(self.thread()["status"], "developing")

    def test_undo_after_the_author_edited_the_thread_asks_first(self):
        task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        self.confirm(task)
        self.patch_thread(status="developing")
        error = self.undo(task["changes"][0]["id"], expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_undo_conflict", {"later_changes": [], "author_changed": True}))
        self.assertEqual(self.thread()["status"], "developing")
        self.undo(task["changes"][0]["id"], confirm=True)
        self.assertEqual(self.thread()["status"], "planted")

    def test_it_has_no_value_to_reword(self):
        task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                             json={"accepted": [task["changes"][0]["id"]], "edits": {task["changes"][0]["id"]: "随便"}})
        self.assertEqual(r.status_code, 422, r.text)

    def test_the_author_saying_they_stop_following_it_gets_the_card(self):
        self.provider.script_route({"items": [{"about": "罗盘那条线", "ask": "不追了", "want": "abandon_thread"}]})
        task = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        self.assertEqual([item["kind"] for item in task["changes"]], ["abandon_thread"])
        self.assertEqual(len(self.provider.route_calls), 1)

    def test_a_thread_marked_resolved_on_words_that_give_it_up_is_the_wrong_kind(self):
        self.provider.script_route({"items": [{"about": "罗盘那条线", "ask": "不追了", "want": "abandon_thread"}]})
        task = self.change_task(*self.resolving(words="罗盘那条线"), question=self.ABANDON_ASK)
        self.assertEqual(self.step_error(task), "change_not_this_kind")
        self.assertEqual(task["changes"], [])

    def test_giving_up_asks_for_a_piece_that_gives_up(self):
        self.provider.script_route({"items": [{"about": "罗盘那条线", "ask": "怎么样了", "want": "look"}]})
        task = self.change_task(*self.abandoning(), question="罗盘那条线怎么样了")
        self.assertEqual(self.step_error(task), "change_read_only")
        self.provider.script_route({"items": [{"about": "罗盘那条线", "ask": "这次放弃", "want": "abandon_thread"}]})
        task = self.change_task(*self.abandoning(), question="罗盘那条线这次放弃")
        self.assertEqual(len(task["changes"]), 1)


class EditThreadTests(ThreadActionCase):
    def test_the_card_shows_the_old_and_the_new_note_in_full_and_waits(self):
        version = self.foreshadow_version()
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        [item] = task["changes"]
        self.assertEqual((item["kind"], item["editable"], item["title"], item["value"]), ("edit_thread", True, "罗盘下落", NOTE))
        self.assertEqual((item["before"], item["after"]), ("罗盘下落还没有交代", NOTE))
        self.assertEqual((item["evidence"], item["risk"], item["evidence_required"]), ([], "low", False))
        self.assertEqual((self.thread()["description"], self.foreshadow_version()), ("罗盘下落还没有交代", version))

    def test_a_note_in_the_authors_own_words_keeps_no_evidence(self):
        from app.assistant_actions import _takes_authors_words
        ask = "罗盘那条伏笔的说明补一句：温岚其实早就知道罗盘在哪"
        value = "罗盘下落还没有交代；温岚其实早就知道罗盘在哪。"
        task = self.change_task(*self.thread_turns(lambda m: {"action": "edit_thread", "target": self.thread_ref(m), "value": value,
                                                              "evidence": [refs(m, self.last)[0]], "request_words": "罗盘那条伏笔"}, [self.last]), question=ask)
        [item] = task["changes"]
        self.assertEqual((item["kind"], item["evidence"]), ("edit_thread", []))
        self.assertTrue(_takes_authors_words(value, ask))
        self.assertFalse(_takes_authors_words("罗盘最后落在温岚手里", "罗盘那条伏笔的说明和正文对不上，按正文改"))

    def test_confirm_writes_only_the_note_and_undo_puts_only_the_note_back(self):
        before = dict(self.thread())
        version = self.foreshadow_version()
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        self.confirm(task)
        row = self.thread()
        self.assertEqual((row["description"], row["version"]), (NOTE, before["version"] + 1))
        for field in ("status", "title", "resolved_chapter_id", "planted_chapter_id", "archived_at"):
            self.assertEqual(row[field], before[field], field)
        self.assertEqual((self.events(self.thread_id)[-1], self.foreshadow_version()), ("updated", version + 1))
        snapshot = self.rows("SELECT snapshot_json FROM v2_foreshadow_versions WHERE item_id=? AND version=?", self.thread_id, row["version"])[0]["snapshot_json"]
        self.assertIn(NOTE, snapshot)
        change = task["changes"][0]["id"]
        self.patch_thread(status="developing")  # the author moves another field meanwhile: the note alone is what the item holds
        self.undo(change)
        back = self.thread()
        self.assertEqual((back["description"], back["status"]), (before["description"], "developing"))
        self.redo(change)
        self.assertEqual(self.thread()["description"], NOTE)

    def test_a_thread_already_resolved_can_have_its_note_mended(self):
        self.patch_thread(status="resolved")
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        self.assertEqual(task["changes"][0]["kind"], "edit_thread")
        self.confirm(task)
        self.assertEqual((self.thread()["description"], self.thread()["status"]), (NOTE, "resolved"))

    def test_the_same_note_is_not_a_change(self):
        task = self.change_task(*self.editing(value="罗盘下落还没有交代"), question=self.EDIT_ASK)
        self.assertEqual(self.step_error(task), "change_no_difference")
        task = self.change_task(*self.editing(value="  罗盘下落还没有交代 "), question=self.EDIT_ASK)  # white space is not a difference
        self.assertEqual(self.step_error(task), "change_no_difference")
        self.assertEqual(task["changes"], [])

    def test_the_note_is_one_to_two_hundred_characters(self):
        for value in ("", "   ", "字" * 201, "见 mem-1234 那条"):
            task = self.change_task(*self.editing(value=value), question=self.EDIT_ASK)
            self.assertEqual(self.step_error(task), "change_value_invalid", value[:10])
        task = self.change_task(*self.editing(value="字" * 200), question=self.EDIT_ASK)
        self.assertEqual(len(task["changes"]), 1)

    def test_the_author_may_reword_the_note_before_confirming(self):
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        item = task["changes"][0]
        data = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                                json={"accepted": [item["id"]], "edits": {item["id"]: "作者自己的说明"}}).json()["data"]
        self.assertEqual(self.thread()["description"], "作者自己的说明")
        self.assertEqual((data["changes"][0]["edited_by_author"], data["changes"][0]["after"], data["changes"][0]["value"]), (True, "作者自己的说明", "作者自己的说明"))
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(), json={"accepted": [item["id"]]})
        self.assertEqual(r.status_code, 409, r.text)

    def test_an_empty_or_long_rewording_is_refused_and_writes_nothing(self):
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        item = task["changes"][0]
        for value in ("  ", "字" * 201):
            r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                                 json={"accepted": [item["id"]], "edits": {item["id"]: value}})
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "change_value_invalid"))
        self.assertEqual(self.thread()["description"], "罗盘下落还没有交代")

    def test_the_note_changed_since_the_card_stops_the_confirm_but_another_field_does_not(self):
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        self.patch_thread(status="developing")  # not the note
        self.assertFalse(self.task(task["id"])["changes"][0]["changed_since"])
        self.patch_thread(description="作者先改的说明")
        self.assertTrue(self.task(task["id"])["changes"][0]["changed_since"])
        error = self.confirm(task, expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_target_changed", {"changes": ["C1"]}))
        self.assertEqual(self.thread()["description"], "作者先改的说明")

    def test_undo_after_the_author_edited_the_note_asks_first(self):
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        self.confirm(task)
        self.patch_thread(description="作者后来又改的说明")
        error = self.undo(task["changes"][0]["id"], expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_undo_conflict", {"later_changes": [], "author_changed": True}))
        self.undo(task["changes"][0]["id"], confirm=True)
        self.assertEqual(self.thread()["description"], "罗盘下落还没有交代")

    def test_a_thread_archived_since_the_card_cannot_be_written(self):
        task = self.change_task(*self.editing(), question=self.EDIT_ASK)
        row = self.thread()
        r = self.client.post(f"/api/projects/{self.project_id}/foreshadows/{self.thread_id}/archive", headers=self.idem(), json={"base_version": row["version"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.confirm(task, expect=409)["error"]["code"], "change_target_changed")

    def test_the_note_of_a_thread_given_up_in_the_same_breath_is_one_change_per_thread(self):
        def both(provider, messages):
            thread = self.thread_ref(messages)
            return turn(change_call(action="abandon_thread", target=thread, evidence=[], request_words="罗盘那条线"),
                        change_call(action="edit_thread", target=thread, value=NOTE, evidence=[], request_words="说明改一改"))

        close = self.thread_turns(lambda m: {}, answer=True)[-1]
        task = self.change_task(turn(call("list_threads"), call("read_chapter", chapter_number=self.last)), both, close, question="罗盘那条线不追了，说明改一改")
        codes = [s["error_code"] for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "propose_change"]
        self.assertEqual(codes, [None, "change_duplicate"])

    def test_a_later_edit_goes_back_first_when_the_earlier_item_is_undone(self):
        first = self.change_task(*self.abandoning(), question=self.ABANDON_ASK)
        self.confirm(first)
        second = self.change_task(*self.editing(title="罗盘下落"), question=self.EDIT_ASK)
        self.confirm(second)
        error = self.undo(first["changes"][0]["id"], expect=409)["error"]
        self.assertEqual([item["id"] for item in error["details"]["later_changes"]], [second["changes"][0]["id"]])
        items = self.undo(first["changes"][0]["id"], confirm=True)["data"]["changes"]
        self.assertEqual([item["status"] for item in items], ["undone", "undone"])
        row = self.thread()
        self.assertEqual((row["status"], row["description"]), ("planted", "罗盘下落还没有交代"))


class AddThreadTests(ThreadActionCase):
    def test_the_card_shows_a_thread_the_materials_lack_and_writes_nothing(self):
        version, count = self.foreshadow_version(), len(self.threads())
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        [item] = task["changes"]
        self.assertEqual((item["kind"], item["title"], item["before"], item["editable"], item["value"]), ("add_thread", "门后的叩响", "资料里没有", True, "门后传来三声叩响，没有人应。"))
        self.assertEqual(item["after"], f"已埋设（第 {self.last} 章）：门后传来三声叩响，没有人应。")
        self.assertEqual((item["risk"], item["evidence_required"], item["target"]["kind"]), ("low", True, "foreshadow"))
        self.assertEqual(len(item["evidence"]), 1)
        self.assertEqual((len(self.threads()), self.foreshadow_version()), (count, version))

    def test_it_is_planted_where_the_earliest_passage_is(self):
        task = self.change_task(*self.adding(chapters=[self.last, 1]), question=self.ADD_ASK)  # the passages are not in order
        self.assertIn("（第 1 章）", task["changes"][0]["after"])
        self.confirm(task)
        [row] = [r for r in self.threads() if r["title"] == "门后的叩响"]
        self.assertEqual(row["planted_chapter_id"], self.chapters[1])
        self.assertTrue(row["planted_source_span_id"])

    def test_confirm_inserts_the_thread_and_undo_archives_it_and_redo_takes_it_back(self):
        version, count = self.foreshadow_version(), len(self.threads())
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        change = task["changes"][0]
        self.confirm(task)
        [row] = [r for r in self.threads() if r["title"] == "门后的叩响"]
        self.assertEqual((row["status"], row["version"], row["description"], row["resolved_chapter_id"], row["archived_at"]),
                         ("planted", 1, "门后传来三声叩响，没有人应。", None, None))
        self.assertEqual((row["id"], row["planted_chapter_id"]), (change["target"]["id"], self.chapters[self.last]))
        self.assertEqual((len(self.threads()), self.foreshadow_version(), self.events(row["id"])), (count + 1, version + 1, ["created"]))
        listed = self.client.get(f"/api/projects/{self.project_id}/foreshadows").json()["data"]["records"]
        self.assertIn("门后的叩响", [r["title"] for r in listed])
        self.assertEqual(self.undo(change["id"])["data"]["changes"][0]["status"], "undone")
        archived = self.rows("SELECT * FROM v2_foreshadows WHERE id=?", row["id"])[0]
        self.assertIsNotNone(archived["archived_at"])
        self.assertEqual((archived["version"], len(self.threads()), self.foreshadow_version(), self.events(row["id"])), (2, count, version + 2, ["created", "archived"]))
        listed = self.client.get(f"/api/projects/{self.project_id}/foreshadows").json()["data"]["records"]
        self.assertNotIn("门后的叩响", [r["title"] for r in listed])
        self.redo(change["id"])
        again = self.rows("SELECT * FROM v2_foreshadows WHERE id=?", row["id"])[0]
        self.assertEqual((again["archived_at"], again["version"], again["status"], self.events(row["id"])), (None, 3, "planted", ["created", "archived", "updated"]))
        self.assertEqual([r["event"] for r in self.rows("SELECT event FROM assistant_change_events ORDER BY rowid")], ["applied", "undone", "redone"])

    def test_the_ledger_points_at_the_new_thread(self):
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        self.confirm(task)
        [entry] = self.client.get(f"/api/projects/{self.project_id}/assistant/changes").json()["data"]["changes"]
        self.assertEqual((entry["kind"], entry["target"]), ("add_thread", {"kind": "foreshadow", "id": task["changes"][0]["target"]["id"]}))
        self.assertFalse(entry["changed_since"])

    def test_without_evidence_it_is_refused(self):
        task = self.change_task(*self.thread_turns(lambda m: {"action": "add_thread", "title": "门后的叩响", "value": "门后传来三声叩响。", "evidence": [],
                                                              "request_words": "最后一章埋了个悬念"}), question=self.ADD_ASK)
        self.assertEqual(self.step_error(task), "change_evidence_invalid")
        self.assertEqual(task["changes"], [])

    def test_a_title_the_materials_already_have_is_refused_however_it_is_written(self):
        self.new_thread("AB线")
        for title in ("罗盘下落", " 罗盘下落 ", "ＡＢ线", "ab线"):
            task = self.change_task(*self.adding(title=title), question=self.ADD_ASK)
            self.assertEqual(self.step_error(task), "change_thread_exists", title)
            self.assertEqual(task["changes"], [])
        self.assertIn("资料里已经有同名的伏笔", ERROR_HINTS["change_thread_exists"])
        self.assertEqual(ERROR_TEXTS["change_thread_exists"], "资料里已经有这条伏笔")

    def test_an_archived_thread_does_not_hold_its_title(self):
        row = self.thread()
        r = self.client.post(f"/api/projects/{self.project_id}/foreshadows/{self.thread_id}/archive", headers=self.idem(), json={"base_version": row["version"]})
        self.assertEqual(r.status_code, 200, r.text)
        task = self.change_task(*self.adding(title="罗盘下落"), question=self.ADD_ASK)
        self.assertEqual(len(task["changes"]), 1)

    def test_the_title_and_the_note_have_their_limits(self):
        for kwargs in ({"title": ""}, {"title": "字" * 31}, {"value": ""}, {"value": "字" * 201}, {"title": "见 mem-1234 那条"}):
            task = self.change_task(*self.adding(**kwargs), question=self.ADD_ASK)
            self.assertEqual(self.step_error(task), "change_value_invalid", kwargs)
        task = self.change_task(*self.adding(title="字" * 30, value="字" * 200), question=self.ADD_ASK)
        self.assertEqual(len(task["changes"]), 1)

    def test_a_work_with_as_many_threads_as_it_may_hold_gets_no_more(self):
        with patch("app.assistant_actions.FORESHADOW_MAX_RECORDS", len(self.threads())):
            task = self.change_task(*self.adding(), question=self.ADD_ASK)
        self.assertEqual(self.step_error(task), "change_thread_limit_reached")
        self.assertEqual(task["changes"], [])

    def test_two_threads_of_one_title_on_a_card_are_one(self):
        def twice(provider, messages):
            passage = [refs(messages, self.last)[0]]
            args = {"action": "add_thread", "evidence": passage, "value": "门后传来三声叩响。"}
            return turn(change_call(**args, title="门后的叩响", request_words="最后一章埋了个悬念"), change_call(**args, title=" 门后的叩响 ", request_words="再加一条"))

        close = self.thread_turns(lambda m: {}, answer=True)[-1]
        task = self.change_task(turn(call("list_threads"), call("read_chapter", chapter_number=self.last)), twice, close, question="最后一章埋了个悬念，再加一条")
        codes = [s["error_code"] for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "propose_change"]
        self.assertEqual(codes, [None, "change_duplicate"])

    def test_the_author_may_reword_the_note_but_not_the_title(self):
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        item = task["changes"][0]
        data = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                                json={"accepted": [item["id"]], "edits": {item["id"]: "作者自己的说明"}}).json()["data"]
        [row] = [r for r in self.threads() if r["title"] == "门后的叩响"]
        self.assertEqual(row["description"], "作者自己的说明")
        self.assertEqual((data["changes"][0]["edited_by_author"], data["changes"][0]["after"]), (True, f"已埋设（第 {self.last} 章）：作者自己的说明"))

    def test_a_thread_of_the_same_title_made_by_the_author_since_the_card_stops_the_confirm(self):
        count = len(self.threads())
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        self.new_thread("门后的叩响")
        self.assertTrue(self.task(task["id"])["changes"][0]["changed_since"])
        error = self.confirm(task, expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_target_changed", {"changes": ["C1"]}))
        self.assertEqual(len(self.threads()), count + 1)  # only the author's

    def test_a_redo_over_a_thread_of_the_same_title_is_refused(self):
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        change = task["changes"][0]["id"]
        self.confirm(task)
        self.undo(change)
        self.new_thread("门后的叩响")
        error = self.redo(change, expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_target_changed", {"changes": ["C1"]}))
        self.assertEqual(self.task(task["id"])["changes"][0]["status"], "undone")
        self.assertTrue(self.task(task["id"])["changes"][0]["changed_since"])

    def test_undo_after_the_author_edited_the_thread_asks_first_and_archives_on_their_word(self):
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        self.confirm(task)
        thread_id = task["changes"][0]["target"]["id"]
        row = self.thread(thread_id)
        r = self.client.patch(f"/api/projects/{self.project_id}/foreshadows/{thread_id}", headers=self.idem(), json={"base_version": row["version"], "description": "作者改过的说明"})
        self.assertEqual(r.status_code, 200, r.text)
        error = self.undo(task["changes"][0]["id"], expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_undo_conflict", {"later_changes": [], "author_changed": True}))
        self.assertIsNone(self.thread(thread_id)["archived_at"])
        self.undo(task["changes"][0]["id"], confirm=True)
        self.assertIsNotNone(self.thread(thread_id)["archived_at"])

    def test_undo_when_the_author_has_archived_it_already_takes_nothing_more(self):
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        self.confirm(task)
        thread_id = task["changes"][0]["target"]["id"]
        row = self.thread(thread_id)
        self.client.post(f"/api/projects/{self.project_id}/foreshadows/{thread_id}/archive", headers=self.idem(), json={"base_version": row["version"]})
        version = self.foreshadow_version()
        self.undo(task["changes"][0]["id"], confirm=True)
        self.assertEqual((self.thread(thread_id)["version"], self.foreshadow_version()), (row["version"] + 1, version))

    def test_a_later_item_on_the_new_thread_goes_back_first(self):
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        self.confirm(task)
        thread_id = task["changes"][0]["target"]["id"]
        edit = self.change_task(*self.editing(title="门后的叩响", words="门后的叩响"), question="门后的叩响那条伏笔的说明改一改")
        self.assertEqual(edit["changes"][0]["target"]["id"], thread_id)
        self.confirm(edit)
        error = self.undo(task["changes"][0]["id"], expect=409)["error"]
        self.assertEqual([item["id"] for item in error["details"]["later_changes"]], [edit["changes"][0]["id"]])
        self.undo(task["changes"][0]["id"], confirm=True)
        self.assertEqual(self.thread(thread_id)["description"], "门后传来三声叩响，没有人应。")
        self.assertIsNotNone(self.thread(thread_id)["archived_at"])

    def test_a_fact_review_open_does_not_hold_a_thread_back(self):
        task = self.change_task(*self.adding(), question=self.ADD_ASK)
        with patch("app.assistant_actions.memory_review_open", return_value="memory_delta"):
            self.confirm(task)
        self.assertIn("门后的叩响", [r["title"] for r in self.threads()])


class WantTests(ThreadActionCase):
    """What the request list says a piece of the sentence asks for decides which kinds of change may stand on it."""

    @staticmethod
    def piece(ask, want, *about):
        return {"about": list(about) or [ask], "ask": ask, "want": want}

    def setup_ctx(self, question):
        task = self.change_task(turn(answer_call("not_found", [], note="查过最后一章正文，没有找到问题问到的内容。")), question=question)
        ctx = self.ctx(task)
        passage = ctx.registry.register("passage", self.chapters[self.last], self.last, "", 0, 10, "示意的原文段落")
        thread = ctx.registry.register("foreshadow", self.thread_id, 2, None, None, None, "伏笔：罗盘下落（已埋设，第 2 章埋下）——罗盘下落还没有交代")
        return ctx, passage, thread

    def arguments(self, kind, passage, thread, words):
        return {
            "add_thread": {"action": "add_thread", "title": "门后的叩响", "value": "门后传来三声叩响。", "evidence": [passage]},
            "edit_thread": {"action": "edit_thread", "target": thread, "value": NOTE, "evidence": []},
            "abandon_thread": {"action": "abandon_thread", "target": thread, "evidence": []},
            "resolve_thread": {"action": "resolve_thread", "target": thread, "evidence": [passage]},
            "add_fact": {"action": "add_fact", "memory_type": "dynamic_state", "subject": "门后的叩响", "predicate": "status", "value": "没有人应", "evidence": [passage]},
        }[kind] | {"request_words": words}

    def outcome(self, ctx, args):
        try:
            return run_propose_change(ctx, args).result["change"]
        except ToolError as error:
            return error.code

    def test_the_constants_follow_the_new_actions(self):
        self.assertTrue({"new_thread", "thread_note", "abandon_thread"} <= set(assistant_requests.WANTS))
        self.assertEqual({kind: assistant_requests.ACTION_WANTS[kind] for kind in ("add_thread", "edit_thread", "abandon_thread")},
                         {"add_thread": "new_thread", "edit_thread": "thread_note", "abandon_thread": "abandon_thread"})
        self.assertEqual(set(assistant_requests.ACTION_WANTS), set(ACTIONS))
        self.assertNotIn("abandon_thread", WANT_REFUSALS)
        self.assertEqual(set(WANT_REFUSALS), {"look", "delete", "prose"})
        self.assertEqual(ERROR_TEXTS["change_not_this_kind"], "作者要的不是这种改动")
        self.assertEqual(ERROR_HINTS["change_not_this_kind"], "作者这几个字要的是另一种改动：按作者说的那种来提出，或者不提出。")

    def test_each_kind_goes_through_on_words_that_ask_for_it(self):
        for kind, want in (("add_thread", "new_thread"), ("edit_thread", "thread_note"), ("abandon_thread", "abandon_thread"), ("resolve_thread", "resolve_thread")):
            ctx, passage, thread = self.setup_ctx("罗盘那条线这样处理")
            ctx.requests = [self.piece("这样处理", want, "罗盘那条线")]
            self.assertEqual(self.outcome(ctx, self.arguments(kind, passage, thread, "罗盘那条线")), "C1", kind)

    def test_a_kind_the_words_do_not_ask_for_is_the_wrong_kind(self):
        wrong = {"new_thread": ("add_fact", "edit_thread", "abandon_thread", "resolve_thread"), "thread_note": ("add_fact", "add_thread", "abandon_thread", "resolve_thread"),
                 "abandon_thread": ("add_fact", "add_thread", "edit_thread", "resolve_thread"), "resolve_thread": ("add_thread", "edit_thread", "abandon_thread")}
        for want, kinds in wrong.items():
            for kind in kinds:
                ctx, passage, thread = self.setup_ctx("罗盘那条线这样处理")
                ctx.requests = [self.piece("这样处理", want, "罗盘那条线")]
                self.assertEqual(self.outcome(ctx, self.arguments(kind, passage, thread, "罗盘那条线")), "change_not_this_kind", f"{want} / {kind}")

    def test_the_old_pairs_keep_their_own_refusals(self):
        for want, kind, code in (("fact", "add_thread", "change_fact_not_thread"), ("fact", "edit_thread", "change_fact_not_thread"),
                                 ("fact", "abandon_thread", "change_fact_not_thread"), ("fact", "resolve_thread", "change_fact_not_thread"),
                                 ("resolve_thread", "add_fact", "change_thread_not_fact"), ("delete", "abandon_thread", "change_give_up_not_resolve"),
                                 ("prose", "edit_thread", "change_prose_not_fact"), ("look", "abandon_thread", "change_read_only")):
            ctx, passage, thread = self.setup_ctx("罗盘那条线这样处理")
            ctx.requests = [self.piece("这样处理", want, "罗盘那条线")]
            self.assertEqual(self.outcome(ctx, self.arguments(kind, passage, thread, "罗盘那条线")), code, f"{want} / {kind}")

    def test_a_piece_that_names_nothing_is_not_refused_on_its_kind(self):
        ctx, passage, thread = self.setup_ctx("罗盘那条线请读全")
        ctx.requests = [self.piece("请读全", "other", "罗盘那条线")]
        self.assertEqual(self.outcome(ctx, self.arguments("edit_thread", passage, thread, "罗盘那条线请读全")), "C1")

    def test_a_thread_added_on_the_authors_wish_for_one_goes_on_the_card_and_a_fact_does_not(self):
        self.provider.script_route({"items": [{"about": "最后一章的悬念", "ask": "加一条伏笔", "want": "new_thread"}]})
        task = self.change_task(*self.adding(words="最后一章的悬念"), question="最后一章的悬念，加一条伏笔")
        self.assertEqual([item["kind"] for item in task["changes"]], ["add_thread"])

        def fact(provider, messages):
            return turn(change_call(action="add_fact", memory_type="dynamic_state", subject="门后的叩响", predicate="status", value="没有人应",
                                    evidence=[refs(messages, self.last)[0]], request_words="最后一章的悬念"))

        close = self.thread_turns(lambda m: {})[-1]
        self.provider.script_route({"items": [{"about": "最后一章的悬念", "ask": "加一条伏笔", "want": "new_thread"}]})
        task = self.change_task(turn(call("read_chapter", chapter_number=self.last)), fact, close, question="最后一章的悬念，加一条伏笔")
        self.assertEqual(self.step_error(task), "change_not_this_kind")
        self.assertEqual(task["changes"], [])


if __name__ == "__main__":
    unittest.main()
