"""v2.0 prototype: a change task proposes a card, the author confirms it, the program writes it, and it can be undone.

Batch one starts with `resolve_thread`. The model only proposes; nothing reaches the materials before the author confirms, a
confirm is all or nothing, and undo puts back only what an item wrote, telling the author first when the record was changed
again afterwards."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app import assistant_store
from app.assistant_actions import CARD_MAX_ITEMS, fact_at, fact_lineage, memory_review_open, propose_add_fact, read_fact, run_propose_change, write_fact
from app.assistant_tools import ToolError
from app.memory_contract import CONTROLLED_PREDICATES
from app.assistant_route import RouteFacts, parse
from app.assistant_tools import tools_for

from tests.scripted_chat import answer_call, call, tool_items, turn
from tests.test_assistant_v180 import Task04Case


def change_call(**arguments):
    """A propose_change call; the request words default to words every change question of these tests holds."""
    return call("propose_change", **{"request_words": "最后一章", **arguments})


def held_back(messages):
    """Whether the last tool result is a proposal held back for a second look."""
    try:
        result = json.loads(messages[-1]["content"]) if messages[-1].get("role") == "tool" else {}
    except ValueError:
        return False
    return isinstance(result, dict) and result.get("status") == "second_look"


def refs(messages, kind):
    """The R numbers the tools handed out: of foreshadowing records (`thread`) or of chapter passages (a chapter number)."""
    if kind == "thread":
        return [item["ref"] for item in tool_items(messages) if item["text"].startswith("伏笔：")]
    passages = []
    for message in messages:
        if message.get("role") == "tool":
            try:
                result = json.loads(message["content"])
            except ValueError:
                continue
            passages += [item["ref"] for item in (result.get("passages") or []) if isinstance(result, dict) and item.get("chapter") == kind]
    return passages


class ChangeCase(Task04Case):
    def setUp(self):
        super().setUp()
        self.chapters = {row["chapter_number"]: row["id"] for row in self.rows("SELECT id,chapter_number FROM v2_chapters WHERE project_id=?", self.project_id)}
        self.last = max(self.chapters)
        self.thread_id = self.new_thread("罗盘下落", planted=2)

    def new_thread(self, title, planted=2, status="planted"):
        version = self.client.get(f"/api/projects/{self.project_id}/foreshadows").json()["data"]["foreshadow_version"]
        r = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=self.idem(),
                             json={"base_foreshadow_version": version, "title": title, "description": f"{title}还没有交代", "status": status,
                                   "planted_chapter_id": self.chapters[planted]})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["data"]["item"]["id"]

    def thread(self, thread_id=None):
        return self.rows("SELECT * FROM v2_foreshadows WHERE id=?", thread_id or self.thread_id)[0]

    def patch_thread(self, **values):
        row = self.thread()
        r = self.client.patch(f"/api/projects/{self.project_id}/foreshadows/{self.thread_id}", headers=self.idem(), json={"base_version": row["version"], **values})
        self.assertEqual(r.status_code, 200, r.text)

    def change_task(self, *turns, question="罗盘那条线最后一章已经收了"):
        self.provider.script(*turns)
        r = self.post_task("change", context={"page": "materials"}, question=question)
        return self.task(r.json()["data"]["id"])

    def resolving(self, title="罗盘下落", chapter=None, answer=True, words="最后一章"):
        """Turns that look the thread up, read a chapter, propose resolving the thread there and answer."""
        chapter = chapter or self.last

        def propose(provider, messages):
            thread = next(item["ref"] for item in tool_items(messages) if item["text"].startswith(f"伏笔：{title}"))
            return turn(change_call(action="resolve_thread", target=thread, evidence=[refs(messages, chapter)[0]], request_words=words))

        def close(provider, messages):
            return turn(answer_call("answered", [("最后一章写到了这条线的结果。", [refs(messages, chapter)[0]])]))

        return [turn(call("list_threads"), call("read_chapter", chapter_number=chapter)), propose] + ([close] if answer else [])

    def confirm(self, task, accepted=None, expect=200):
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                             json={"accepted": accepted if accepted is not None else [item["id"] for item in task["changes"]]})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def undo(self, change_id, confirm=False, expect=200):
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/changes/{change_id}/undo", headers=self.idem(), json={"confirm": confirm})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()


class CardTests(ChangeCase):
    def test_the_card_is_proposed_and_nothing_is_written(self):
        task = self.change_task(*self.resolving())
        self.assertEqual(task["status"], "completed", task)
        [item] = task["changes"]
        self.assertEqual((item["label"], item["kind"], item["status"], item["title"]), ("C1", "resolve_thread", "proposed", "罗盘下落"))
        self.assertEqual((item["before"], item["after"]), ("已埋设", f"已回收（第 {self.last} 章）"))
        self.assertFalse(item["changed_since"])
        self.assertEqual(item["evidence"][0]["chapter_number"], self.last)
        self.assertTrue(item["evidence"][0]["text"])
        self.assertEqual(self.thread()["status"], "planted")
        self.assertEqual(self.rows("SELECT event FROM assistant_change_events"), [])

    def test_the_task_reads_the_text_and_the_threads_but_never_the_draft(self):
        self.change_task(*self.resolving())
        offered = set(self.provider.calls[0]["tools"])
        self.assertEqual(offered, {"search_text", "lookup_facts", "read_chapter", "get_plans", "list_threads", "propose_change", "answer"})
        message = self.provider.calls[0]["messages"][-1]["content"]
        self.assertIn("作者的要求：罗盘那条线最后一章已经收了", message)
        self.assertIn("propose_change", message)
        self.assertIn("这次不能读当前草稿", message)

    def test_a_question_never_gets_the_change_tools(self):
        for kind in ("ask", "recap", "fix_issue"):
            names = {tool["function"]["name"] for tool in tools_for(kind, {"draft_readable": True})}
            self.assertFalse(names & {"list_threads", "propose_change"}, kind)

    def test_a_change_needs_words_and_is_never_a_follow_up(self):
        self.post_task("change", context={"page": "materials"}, expect=400)
        asked = self.run_ask(turn(answer_call("not_found", [], note="查过第 1 章正文，没有找到问题问到的内容。")))
        body = {"kind": "change", "question": "记一下", "context": {"page": "materials"}, "follow_up_of": asked["id"]}
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks", headers=self.idem(), json=body)
        self.assertEqual(r.status_code, 422, r.text)

    def test_an_answer_that_says_nothing_was_found_beside_a_card_is_sent_back(self):
        chapter = self.last

        def wrong(provider, messages):
            return turn(answer_call("not_found", [], note="查过最后一章正文，没有找到问题问到的内容。"))

        def right(provider, messages):
            return turn(answer_call("answered", [("最后一章写到了这条线的结果。", [refs(messages, chapter)[0]])]))

        task = self.change_task(*self.resolving(answer=False), wrong, right)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["answer"]["status"], "answered")
        repair = [step for step in self.engine.store.steps(task["id"]) if step["kind"] == "repair"]
        self.assertIn("提出了资料改动时", repair[0]["args_json"])


class ProposalCheckTests(ChangeCase):
    def proposed(self, make_args):
        """Propose with arguments built from what the tools returned; the step's error code (None when it was accepted)."""
        def propose(provider, messages):
            return turn(change_call(**make_args(messages)))

        def close(provider, messages):
            return turn(answer_call("not_found", [], note="查过最后一章正文，没有找到问题问到的内容。"))

        task = self.change_task(turn(call("list_threads"), call("read_chapter", chapter_number=self.last), call("read_chapter", chapter_number=1)), propose, close)
        step = [s for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "propose_change"][-1]
        return step["error_code"], task

    def thread_ref(self, messages, title="罗盘下落"):
        return next(item["ref"] for item in tool_items(messages) if item["text"].startswith(f"伏笔：{title}"))

    def test_the_target_must_be_a_thread_the_task_was_shown(self):
        code, task = self.proposed(lambda m: {"action": "resolve_thread", "target": refs(m, self.last)[0], "evidence": [refs(m, self.last)[0]]})
        self.assertEqual(code, "change_target_invalid")
        self.assertEqual(task["changes"], [])
        code, _ = self.proposed(lambda m: {"action": "resolve_thread", "target": "R99", "evidence": [refs(m, self.last)[0]]})
        self.assertEqual(code, "change_target_invalid")

    def test_the_evidence_must_be_a_passage_of_the_written_text(self):
        code, _ = self.proposed(lambda m: {"action": "resolve_thread", "target": self.thread_ref(m), "evidence": [self.thread_ref(m)]})
        self.assertEqual(code, "change_evidence_invalid")
        code, _ = self.proposed(lambda m: {"action": "resolve_thread", "target": self.thread_ref(m), "evidence": []})
        self.assertEqual(code, "change_evidence_invalid")

    def test_a_passage_before_the_planting_cannot_close_the_thread(self):
        code, _ = self.proposed(lambda m: {"action": "resolve_thread", "target": self.thread_ref(m), "evidence": [refs(m, 1)[0]]})
        self.assertEqual(code, "change_evidence_before_planted")

    def test_a_thread_already_resolved_is_not_proposed_again(self):
        self.patch_thread(status="resolved")
        code, _ = self.proposed(lambda m: {"action": "resolve_thread", "target": self.thread_ref(m), "evidence": [refs(m, self.last)[0]]})
        self.assertEqual(code, "change_thread_not_open")

    def test_a_change_names_the_words_of_the_request_it_answers(self):
        code, _ = self.proposed(lambda m: {"action": "resolve_thread", "target": self.thread_ref(m), "evidence": [refs(m, self.last)[0]],
                                           "request_words": "推门进来就开会"})
        self.assertEqual(code, "change_not_requested")
        code, task = self.proposed(lambda m: {"action": "resolve_thread", "target": self.thread_ref(m), "evidence": [refs(m, self.last)[0]],
                                              "request_words": "罗盘 那条线"})  # spaces do not matter
        self.assertIsNone(code)
        self.assertEqual(task["changes"][0]["request_words"], "罗盘那条线")
        for words in ("罗", None):
            code, _ = self.proposed(lambda m, w=words: {"action": "resolve_thread", "target": self.thread_ref(m), "evidence": [refs(m, self.last)[0]],
                                                        "request_words": w})
            self.assertEqual(code, "change_not_requested")

    def test_the_last_round_may_still_put_a_change_on_the_card(self):
        def last(provider, messages):
            thread = next(item["ref"] for item in tool_items(messages) if item["text"].startswith("伏笔：罗盘下落"))
            passage = refs(messages, self.last)[0]
            return turn(change_call(action="resolve_thread", target=thread, evidence=[passage]),
                        answer_call("answered", [("最后一章写到了这条线的结果。", [passage])]))

        research = [turn(call("list_threads"), call("read_chapter", chapter_number=self.last))] + [turn(call("list_threads")) for _ in range(5)]
        task = self.change_task(*research, last)
        self.assertEqual(sorted(self.provider.calls[-1]["tools"]), ["answer", "propose_change"])
        self.assertIn("propose_change", self.provider.calls[-1]["messages"][-1]["content"])
        self.assertEqual((task["status"], len(task["changes"])), ("completed", 1))

    def test_an_unknown_action_is_refused(self):
        code, _ = self.proposed(lambda m: {"action": "delete_fact", "target": self.thread_ref(m), "evidence": [refs(m, self.last)[0]]})
        self.assertEqual(code, "change_action_unknown")

    def test_the_same_thread_once_and_at_most_five_items(self):
        titles = [f"线索{n}" for n in range(CARD_MAX_ITEMS)]
        for title in titles:
            self.new_thread(title)

        def proposals(provider, messages):
            evidence = [refs(messages, self.last)[0]]
            words = ["罗盘", "最后一章", "线索0", "线索1", "线索2", "线索3"]
            return turn(*[change_call(action="resolve_thread", target=self.thread_ref(messages, title), evidence=evidence, request_words=w)
                          for title, w in zip(["罗盘下落", "罗盘下落", *titles[:4]], words)])

        def one_more(provider, messages):
            return turn(change_call(action="resolve_thread", target=self.thread_ref(messages, titles[4]), evidence=[refs(messages, self.last)[0]],
                                    request_words="线索4"))

        def close(provider, messages):
            return turn(answer_call("answered", [("最后一章写到了这些线的结果。", [refs(messages, self.last)[0]])]))

        task = self.change_task(turn(call("list_threads"), call("read_chapter", chapter_number=self.last)), proposals, one_more, close,
                                question="罗盘、线索0、线索1、线索2、线索3、线索4，最后一章都收了")
        codes = [s["error_code"] for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "propose_change"]
        self.assertEqual(codes, [None, "change_duplicate", None, None, None, None, "change_limit_reached"])
        self.assertEqual(len(task["changes"]), CARD_MAX_ITEMS)


class ConfirmTests(ChangeCase):
    def test_confirm_writes_the_card_and_records_it(self):
        task = self.change_task(*self.resolving())
        version = self.thread()["version"]
        data = self.confirm(task)["data"]
        self.assertEqual(data["changes"][0]["status"], "applied")
        row = self.thread()
        self.assertEqual((row["status"], row["resolved_chapter_id"], row["version"]), ("resolved", self.chapters[self.last], version + 1))
        self.assertEqual(self.rows("SELECT event FROM v2_foreshadow_versions WHERE item_id=? ORDER BY version DESC LIMIT 1", self.thread_id)[0]["event"], "updated")
        self.assertEqual([r["event"] for r in self.rows("SELECT event FROM assistant_change_events")], ["applied"])
        ledger = self.client.get(f"/api/projects/{self.project_id}/assistant/changes").json()["data"]["changes"]
        self.assertEqual([(item["id"], item["task_id"], item["target"]) for item in ledger],
                         [(task["changes"][0]["id"], task["id"], {"kind": "foreshadow", "id": self.thread_id})])
        self.confirm(task, expect=409)  # a card is decided once

    def test_reject_writes_nothing(self):
        task = self.change_task(*self.resolving())
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/reject", headers=self.idem(), json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["changes"][0]["status"], "rejected")
        self.assertEqual(self.thread()["status"], "planted")
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/assistant/changes").json()["data"]["changes"], [])

    def test_only_the_accepted_items_are_written(self):
        other = self.new_thread("铜钥匙")
        turns = self.resolving(answer=False) + self.resolving(title="铜钥匙", words="已经收了")[1:]
        task = self.change_task(*turns)
        first, second = task["changes"]
        self.confirm(task, accepted=[second["id"]])
        self.assertEqual((self.thread()["status"], self.thread(other)["status"]), ("planted", "resolved"))
        self.assertEqual([item["status"] for item in self.task(task["id"])["changes"]], ["rejected", "applied"])

    def test_a_record_changed_since_the_card_stops_the_whole_confirm(self):
        other = self.new_thread("铜钥匙")
        task = self.change_task(*(self.resolving(answer=False) + self.resolving(title="铜钥匙", words="已经收了")[1:]))
        self.patch_thread(status="developing")
        self.assertTrue(self.task(task["id"])["changes"][0]["changed_since"])
        error = self.confirm(task, expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_target_changed", {"changes": ["C1"]}))
        self.assertEqual(self.thread(other)["status"], "planted")  # nothing of the card was written
        self.assertEqual([item["status"] for item in self.task(task["id"])["changes"]], ["proposed", "proposed"])

    def test_a_card_of_an_unfinished_or_other_task_cannot_be_confirmed(self):
        asked = self.run_ask(turn(answer_call("not_found", [], note="查过第 1 章正文，没有找到问题问到的内容。")))
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{asked['id']}/changes/confirm", headers=self.idem(), json={"accepted": ["x"]})
        self.assertEqual(r.status_code, 404, r.text)
        task = self.change_task(*self.resolving())
        self.confirm(task, accepted=["achange-not-on-this-card"], expect=422)


class UndoTests(ChangeCase):
    def applied(self, title="罗盘下落"):
        task = self.change_task(*self.resolving(title=title))
        self.confirm(task)
        return task["changes"][0]["id"]

    def test_undo_puts_back_what_the_item_wrote_and_redo_applies_it_again(self):
        change = self.applied()
        before = self.thread()
        item = self.undo(change)["data"]["changes"][0]
        self.assertEqual(item["status"], "undone")
        row = self.thread()
        self.assertEqual((row["status"], row["resolved_chapter_id"], row["version"]), ("planted", None, before["version"] + 1))
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/changes/{change}/redo", headers=self.idem(), json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.thread()["status"], "resolved")
        self.assertEqual([r["event"] for r in self.rows("SELECT event FROM assistant_change_events ORDER BY rowid")], ["applied", "undone", "redone"])

    def test_undo_keeps_the_authors_edits_of_other_fields(self):
        change = self.applied()
        self.patch_thread(description="作者后来补的说明")
        self.undo(change)
        row = self.thread()
        self.assertEqual((row["status"], row["description"]), ("planted", "作者后来补的说明"))

    def test_an_edit_of_the_same_fields_is_reported_and_put_back_only_on_the_authors_word(self):
        change = self.applied()
        self.patch_thread(status="developing", resolved_chapter_id=None)
        error = self.undo(change, expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_undo_conflict", {"later_changes": [], "author_changed": True}))
        self.assertEqual(self.thread()["status"], "developing")
        self.undo(change, confirm=True)
        self.assertEqual(self.thread()["status"], "planted")

    def test_a_later_item_on_the_same_record_is_undone_first(self):
        first = self.applied()
        self.patch_thread(status="developing", resolved_chapter_id=None)  # the author reopens the thread
        second = self.applied()
        error = self.undo(first, expect=409)["error"]
        self.assertEqual(error["code"], "change_undo_conflict")
        self.assertEqual([item["id"] for item in error["details"]["later_changes"]], [second])
        self.assertFalse(error["details"]["author_changed"])
        items = self.undo(first, confirm=True)["data"]["changes"]
        self.assertEqual([(item["id"], item["status"]) for item in items], [(first, "undone"), (second, "undone")])
        self.assertEqual(self.thread()["status"], "planted")
        events = self.rows("SELECT change_id,event FROM assistant_change_events WHERE event='undone' ORDER BY rowid")
        self.assertEqual([row["change_id"] for row in events], [second, first])  # newest first

    def test_redo_is_refused_when_the_record_moved_on(self):
        change = self.applied()
        self.undo(change)
        self.patch_thread(status="developing")
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/changes/{change}/redo", headers=self.idem(), json={})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["error"]["code"], "change_target_changed")

    def test_only_an_applied_item_is_undone(self):
        task = self.change_task(*self.resolving())
        self.undo(task["changes"][0]["id"], expect=409)

    def test_the_ledger_goes_with_the_work(self):
        self.applied()
        with self.db.connection() as c:
            assistant_store.purge(c, self.project_id)
        self.assertEqual(self.rows("SELECT * FROM assistant_changes"), [])
        self.assertEqual(self.rows("SELECT * FROM assistant_change_events"), [])


class FactCase(ChangeCase):
    def setUp(self):
        super().setUp()
        with self.db.connection() as c:
            version = self.memory_version()
            facts = [f for f in self.db._confirmed_memory(c, self.project_id, version) if f["source_span_id"] and len(f["subject"]) <= 20]
        # A fact whose subject has few facts, so `lookup_facts` lists it within its cap; chosen the same way every run.
        count = {subject: sum(f["subject"] == subject for f in facts) for subject in {f["subject"] for f in facts}}
        self.fact = min(facts, key=lambda f: (count[f["subject"]], f["subject"], f["value"]))
        self.lineage = fact_lineage(self.fact["id"])

    def memory_version(self):
        return self.rows("SELECT current_memory_version v FROM v2_projects WHERE id=?", self.project_id)[0]["v"]

    def current(self):
        with self.db.connection() as c:
            return read_fact(c, self.db, self.project_id, self.lineage)

    def fact_ref(self, messages):
        return next(item["ref"] for item in tool_items(messages) if item["text"] == f"{self.fact['subject']}：{self.fact['value']}")

    def fact_turns(self, proposal, *also):
        """Look the fact up (and the names in `also`), read the last chapter, propose what `proposal(messages)` returns, and answer."""
        def propose(provider, messages):
            return turn(change_call(**proposal(messages)))

        def close(provider, messages):
            return turn(answer_call("answered", [("最后一章写到了这件事。", [refs(messages, self.last)[0]])]))

        def again(provider, messages):  # a fact item held back for a second look is proposed once more, as the model is told
            return propose(provider, messages) if held_back(messages) else close(provider, messages)

        lookups = [call("lookup_facts", name=name[:20]) for name in dict.fromkeys([self.fact["subject"], *also])]
        return [turn(*lookups, call("read_chapter", chapter_number=self.last)), propose, again, close]

    def change_task(self, *turns, question=None):
        """A change question that names the fact's subject, so a changed fact's request words can point at the record."""
        return super().change_task(*turns, question=question or f"罗盘那条线最后一章已经收了，{self.fact['subject']}那条也变了")

    def changing(self, value="改后的内容"):
        return self.fact_turns(lambda m: {"action": "change_fact", "target": self.fact_ref(m), "value": value, "evidence": [refs(m, self.last)[0]],
                                          "request_words": self.fact["subject"]})

    def adding(self, **fields):
        values = {"memory_type": "dynamic_state", "subject": "温岚", "predicate": "status", "value": "左腕受了伤", **fields}
        return self.fact_turns(lambda m: {"action": "add_fact", "evidence": [refs(m, self.last)[0]], **values}, values["subject"])

    def step_error(self, task):
        return [s["error_code"] for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "propose_change"][-1]


class FactChangeTests(FactCase):
    def test_a_changed_fact_waits_on_the_card_with_its_old_and_new_wording(self):
        version = self.memory_version()
        task = self.change_task(*self.changing(), question=f"事实里{self.fact['subject']}这条过时了，按最后一章改一下")
        [item] = task["changes"]
        self.assertEqual((item["kind"], item["editable"], item["value"]), ("change_fact", True, "改后的内容"))
        self.assertTrue(item["title"].startswith(self.fact["subject"] + "·"))
        self.assertTrue(item["before"].startswith(self.fact["value"]))
        self.assertEqual(item["after"], f"改后的内容（第 {self.last} 章）")
        self.assertEqual(item["target"]["id"], self.lineage)
        self.assertEqual(self.memory_version(), version)  # nothing written yet

    def test_confirm_makes_a_new_version_with_the_new_value_and_undo_another_with_the_old(self):
        version = self.memory_version()
        task = self.change_task(*self.changing())
        self.confirm(task)
        self.assertEqual(self.memory_version(), version + 1)
        now = self.current()
        self.assertEqual(now["value"], "改后的内容")
        self.assertNotEqual(now["source_span_id"], None)
        old = self.rows("SELECT value FROM v2_memory_records WHERE id=?", self.fact["id"])[0]
        self.assertEqual(old["value"], self.fact["value"])  # the earlier version is left as it was
        ledger = self.client.get(f"/api/projects/{self.project_id}/assistant/changes").json()["data"]["changes"]
        self.assertEqual(ledger[0]["target"]["kind"], "fact")
        self.assertEqual(fact_lineage(ledger[0]["target"]["record_id"]), self.lineage)
        self.undo(task["changes"][0]["id"])
        self.assertEqual(self.memory_version(), version + 2)
        self.assertEqual((self.current()["value"], self.current()["source_span_id"]), (self.fact["value"], self.fact["source_span_id"]))

    def test_the_same_value_is_not_a_change(self):
        task = self.change_task(*self.fact_turns(lambda m: {"action": "change_fact", "target": self.fact_ref(m), "value": self.fact["value"],
                                                            "evidence": [refs(m, self.last)[0]]}))
        self.assertEqual(self.step_error(task), "change_no_difference")
        self.assertEqual(task["changes"], [])

    def test_the_author_may_reword_a_fact_before_confirming(self):
        task = self.change_task(*self.changing())
        item = task["changes"][0]
        data = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                                json={"accepted": [item["id"]], "edits": {item["id"]: "作者自己的写法"}}).json()["data"]
        self.assertEqual(self.current()["value"], "作者自己的写法")
        self.assertTrue(data["changes"][0]["edited_by_author"])
        self.assertEqual(data["changes"][0]["after"], f"作者自己的写法（第 {self.last} 章）")

    def test_a_thread_has_nothing_to_reword(self):
        task = self.change_task(*self.resolving())
        item = task["changes"][0]
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/changes/confirm", headers=self.idem(),
                             json={"accepted": [item["id"]], "edits": {item["id"]: "随便"}})
        self.assertEqual(r.status_code, 422, r.text)

    def test_a_fact_changed_since_the_card_stops_the_confirm(self):
        task = self.change_task(*self.changing())
        with self.db.connection() as c:
            write_fact(c, self.db, self.project_id, self.lineage, {**self.current(), "value": "审阅时改的"}, self.user_id, "2026-10-22T00:00:00+00:00")
        self.assertEqual(self.confirm(task, expect=409)["error"]["code"], "change_target_changed")
        self.assertEqual(self.current()["value"], "审阅时改的")

    def test_undo_over_a_later_review_needs_the_authors_word(self):
        task = self.change_task(*self.changing())
        self.confirm(task)
        with self.db.connection() as c:
            write_fact(c, self.db, self.project_id, self.lineage, {**self.current(), "value": "审阅时改的"}, self.user_id, "2026-10-22T00:00:00+00:00")
        error = self.undo(task["changes"][0]["id"], expect=409)["error"]
        self.assertEqual(error["details"], {"later_changes": [], "author_changed": True})
        self.undo(task["changes"][0]["id"], confirm=True)
        self.assertEqual(self.current()["value"], self.fact["value"])

    def test_fact_items_wait_while_a_review_of_the_facts_is_open(self):
        task = self.change_task(*self.changing())
        version = self.memory_version()
        with patch("app.assistant_actions.memory_review_open", return_value="memory_delta"):
            error = self.confirm(task, expect=409)["error"]
        self.assertEqual((error["code"], error["details"]), ("change_memory_review_pending", {"review": "memory_delta"}))
        self.assertEqual((self.memory_version(), self.task(task["id"])["changes"][0]["status"]), (version, "proposed"))
        with self.db.connection() as c:
            self.assertIsNone(memory_review_open(c, self.db, self.project_id))
        self.confirm(task)

    def test_a_thread_does_not_wait_for_a_review_of_the_facts(self):
        task = self.change_task(*self.resolving())
        with patch("app.assistant_actions.memory_review_open", return_value="memory_delta"):
            self.confirm(task)
        self.assertEqual(self.thread()["status"], "resolved")


class FactAddTests(FactCase):
    def test_an_added_fact_appears_in_a_new_version_and_undo_takes_it_out_again(self):
        version = self.memory_version()
        task = self.change_task(*self.adding(), question="温岚手腕受伤那事记一下，最后一章写了")
        [item] = task["changes"]
        self.assertEqual((item["kind"], item["title"], item["before"]), ("add_fact", "温岚·状态", "资料里没有"))
        lineage = item["target"]["id"]
        self.confirm(task)
        with self.db.connection() as c:
            added = read_fact(c, self.db, self.project_id, lineage)
            record = fact_at(c, self.project_id, version + 1, lineage)
        self.assertEqual((added["subject"], added["predicate"], added["value"]), ("温岚", "status", "左腕受了伤"))
        self.assertEqual(record["review_status"], "author_confirmed")
        self.undo(item["id"])
        with self.db.connection() as c:
            self.assertIsNone(read_fact(c, self.db, self.project_id, lineage))
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/changes/{item['id']}/redo", headers=self.idem(), json={})
        self.assertEqual(r.status_code, 200, r.text)
        with self.db.connection() as c:
            self.assertEqual(read_fact(c, self.db, self.project_id, lineage)["value"], "左腕受了伤")
        self.assertEqual(self.memory_version(), version + 3)

    def test_a_fact_already_recorded_is_not_added(self):
        task = self.change_task(*self.adding(memory_type=self.fact["memory_type"], subject=self.fact["subject"][:60],
                                             predicate=self.fact["predicate"] if self.fact["predicate"] in CONTROLLED_PREDICATES else "status",
                                             value=self.fact["value"][:200]))
        expected = "change_fact_already_recorded" if self.fact["predicate"] in CONTROLLED_PREDICATES else None
        self.assertEqual(self.step_error(task), expected)

    def test_type_and_property_come_from_the_lists(self):
        task = self.change_task(*self.adding(predicate="左腕"))
        self.assertEqual(self.step_error(task), "change_fields_invalid")
        task = self.change_task(*self.adding(value="见 mem-1234 那条"))
        self.assertEqual(self.step_error(task), "change_value_invalid")

    def test_the_same_new_fact_once_per_card(self):
        def proposals(provider, messages):
            args = {"action": "add_fact", "memory_type": "dynamic_state", "subject": "温岚", "predicate": "status", "value": "左腕受了伤",
                    "evidence": [refs(messages, self.last)[0]]}
            return turn(change_call(**args), change_call(**args, request_words="罗盘"))

        def close(provider, messages):
            return turn(answer_call("answered", [("最后一章写到了这件事。", [refs(messages, self.last)[0]])]))

        def first(provider, messages):  # held back for a second look, as every new fact about someone with facts is once
            return turn(change_call(action="add_fact", memory_type="dynamic_state", subject="温岚", predicate="status", value="左腕受了伤",
                                    evidence=[refs(messages, self.last)[0]]))

        task = self.change_task(turn(call("lookup_facts", name="温岚"), call("read_chapter", chapter_number=self.last)), first, proposals, close)
        codes = [s["error_code"] for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "propose_change"]
        self.assertEqual(codes, [None, None, "change_duplicate"])
        self.assertEqual(len(task["changes"]), 1)

    def test_one_piece_of_the_request_asks_for_one_change(self):
        # First formal run, w01/w02-action-12: a thread marked resolved and, on the same words, a person's fact changed too.
        other = self.new_thread("铜钥匙")

        def proposals(provider, messages):
            evidence = [refs(messages, self.last)[0]]
            first = next(i["ref"] for i in tool_items(messages) if i["text"].startswith("伏笔：罗盘下落"))
            second = next(i["ref"] for i in tool_items(messages) if i["text"].startswith("伏笔：铜钥匙"))
            return turn(change_call(action="resolve_thread", target=first, evidence=evidence, request_words="罗盘那条线"),
                        change_call(action="resolve_thread", target=second, evidence=evidence, request_words="那条线最后"),
                        change_call(action="resolve_thread", target=second, evidence=evidence, request_words="已经收了"))

        def close(provider, messages):
            return turn(answer_call("answered", [("最后一章写到了这条线的结果。", [refs(messages, self.last)[0]])]))

        task = self.change_task(turn(call("list_threads"), call("read_chapter", chapter_number=self.last)), proposals, close)
        codes = [s["error_code"] for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "propose_change"]
        self.assertEqual(codes, [None, "change_request_words_taken", None])  # overlapping words are the same piece; separate ones are not
        self.assertEqual([c["target"]["id"] for c in task["changes"]][1], other)

    def test_a_name_with_facts_is_looked_up_before_a_fact_is_added_to_it(self):
        with self.db.connection() as c:
            subjects = {f["subject"] for f in self.db._confirmed_memory(c, self.project_id, self.memory_version())}
        other = sorted(s for s in subjects if s != self.fact["subject"] and 2 <= len(s) <= 20)[0]

        def propose(provider, messages):
            return turn(change_call(action="add_fact", memory_type="dynamic_state", subject=f"{other}（外号）", predicate="status",
                             value="示意的新状态", evidence=[refs(messages, self.last)[0]]))

        def close(provider, messages):
            return turn(answer_call("answered", [("最后一章写到了这件事。", [refs(messages, self.last)[0]])]))

        task = self.change_task(turn(call("read_chapter", chapter_number=self.last)), propose, close)
        self.assertEqual(self.step_error(task), "change_check_existing")
        task = self.change_task(*self.adding(subject=f"{other}（外号）", value="示意的新状态"), )
        self.assertEqual(self.step_error(task), "change_check_existing")  # looked up under the nickname only, not the name
        task = self.change_task(*self.fact_turns(lambda m: {"action": "add_fact", "memory_type": "dynamic_state", "subject": f"{other}（外号）",
                                                            "predicate": "status", "value": "示意的新状态", "evidence": [refs(m, self.last)[0]]}, other))
        self.assertIsNone(self.step_error(task))

    def test_one_fact_seen_through_a_nickname_is_not_a_look_up_of_the_name(self):
        # Round 3: looking up "池秒" showed "池澍宁：同事称她池秒", one fact under 池澍宁, and the guard took 池澍宁 as looked up.
        name = self.fact["subject"]
        with self.db.connection() as c:  # a second fact under the same name
            write_fact(c, self.db, self.project_id, "mem-test-second", {"memory_type": "dynamic_state", "subject": name, "predicate": "status",
                                                                    "value": "示意的另一条事实", "source_span_id": self.fact["source_span_id"]},
                       self.user_id, "2026-10-23T00:00:00+00:00")
        with self.db.connection() as c:
            about = [f for f in self.db._confirmed_memory(c, self.project_id, self.memory_version()) if f["subject"] == name]
        self.assertGreater(len(about), 1)
        task = self.change_task(turn(answer_call("not_found", [], note="查过最后一章正文，没有找到问题问到的内容。")))
        ctx = self.ctx(task)
        ctx.registry.register("fact", about[0]["id"], None, None, None, None, f"{name}：{about[0]['value']}")
        passage = ctx.registry.register("passage", self.chapters[self.last], self.last, "", 0, 10, "示意的原文段落")
        args = {"memory_type": "dynamic_state", "subject": name, "predicate": "status", "value": "示意的新状态", "evidence": [passage]}
        with self.assertRaises(ToolError) as raised:
            propose_add_fact(ctx, args, None)
        self.assertEqual(raised.exception.code, "change_check_existing")
        self.engine.store.add_step(task["id"], 1, "tool", "查事实", tool_name="lookup_facts", args={"name": name})
        self.assertEqual(propose_add_fact(ctx, args, None)["after"]["subject"], name)

    def test_a_subject_that_holds_an_existing_one_is_looked_up_under_the_existing_one(self):
        # Spent-pair pass 3, w01-action-08: "槐誓庭盟议" was added while the rule stood under "槐誓庭".
        with self.db.connection() as c:
            write_fact(c, self.db, self.project_id, "mem-test-held", {"memory_type": "dynamic_state", "subject": "雾港议事厅", "predicate": "status",
                                                                  "value": "只准世袭者发言", "source_span_id": self.fact["source_span_id"]},
                       self.user_id, "2026-10-23T00:00:00+00:00")
        task = self.change_task(turn(answer_call("not_found", [], note="查过最后一章正文，没有找到问题问到的内容。")))
        ctx = self.ctx(task)
        passage = ctx.registry.register("passage", self.chapters[self.last], self.last, "", 0, 10, "示意的原文段落")
        args = {"memory_type": "dynamic_state", "subject": "雾港议事厅盟议", "predicate": "status", "value": "准许非世袭者发言", "evidence": [passage]}
        self.engine.store.add_step(task["id"], 1, "tool", "查事实", tool_name="lookup_facts", args={"name": "雾港议事厅盟议"})
        with self.assertRaises(ToolError) as raised:
            propose_add_fact(ctx, args, None)  # the longer name's lookup cannot find the shorter subject
        self.assertEqual(raised.exception.code, "change_check_existing")
        self.engine.store.add_step(task["id"], 1, "tool", "查事实", tool_name="lookup_facts", args={"name": "雾港议事厅"})
        self.assertEqual(propose_add_fact(ctx, args, None)["after"]["subject"], "雾港议事厅盟议")

    def test_a_fact_named_only_in_its_own_property_is_found_and_shows_it(self):
        # First formal run, w01-action-08: "盟议" stood only in the property "盟议发言资格" of 槐誓庭's fact; the lookup missed it.
        with self.db.connection() as c:
            write_fact(c, self.db, self.project_id, "mem-test-own", {"memory_type": "dynamic_state", "subject": "雾港议事厅", "predicate": "盟议发言资格",
                                                                 "value": "只准世袭者发言", "source_span_id": self.fact["source_span_id"]},
                       self.user_id, "2026-10-23T00:00:00+00:00")
        task = self.change_task(turn(call("lookup_facts", name="盟议")),
                                 turn(answer_call("not_found", [], note="查过盟议的事实，没有找到问题问到的内容。")))
        texts = [item["text"] for item in tool_items(self.provider.calls[1]["messages"])]
        self.assertIn("雾港议事厅（盟议发言资格）：只准世袭者发言", texts)

    def test_the_lineage_of_a_fact_is_its_first_id(self):
        self.assertEqual(fact_lineage("mem-1a2b-v5-v6"), "mem-1a2b")
        self.assertEqual(fact_lineage("mem-1a2b"), "mem-1a2b")
        self.assertEqual(fact_lineage("mem-1a2b-v12"), "mem-1a2b")


class RouteTests(unittest.TestCase):
    def test_change_is_a_use_the_model_may_name_anywhere(self):
        self.assertEqual(parse(json.dumps({"route": "change", "unsure": False})), ("change", False))
        facts = RouteFacts(writing=False, selection_chars=0, issue=False, draft_chapter=None, visitor=False)
        self.assertEqual(facts.fitted("change"), "change")

    def test_questions_about_the_materials_stay_questions_in_the_prompt(self):
        from app.assistant_route import ROUTE_SYSTEM_PROMPT
        self.assertIn("change：", ROUTE_SYSTEM_PROMPT)
        self.assertIn("算 ask", ROUTE_SYSTEM_PROMPT.split("change：", 1)[1].split("\n", 1)[0])


class SecondLookTests(FactCase):
    """A fact item the model should weigh against the materials is held back once, with what to weigh; proposed again, it goes
    on the card (spent-pair pass 4: a duplicate of an alias fact, a restated fact, and a fact the author's words were not about)."""

    def setup_task(self, question):
        task = self.change_task(turn(answer_call("not_found", [], note="查过最后一章正文，没有找到问题问到的内容。")), question=question)
        ctx = self.ctx(task)
        passage = ctx.registry.register("passage", self.chapters[self.last], self.last, "", 0, 10, "示意的原文段落")
        fact = ctx.registry.register("fact", self.fact["id"], None, None, None, None, f"{self.fact['subject']}：{self.fact['value']}")
        self.engine.store.add_step(task["id"], 1, "tool", "查事实", tool_name="lookup_facts", args={"name": self.fact["subject"]})
        return task, ctx, passage, fact

    def test_a_new_fact_about_someone_with_facts_is_held_back_once_beside_them(self):
        name = self.fact["subject"]
        task, ctx, passage, _ = self.setup_task(f"{name}的新状态记进资料")
        args = {"action": "add_fact", "memory_type": "dynamic_state", "subject": name, "predicate": "status", "value": self.fact["value"] + "，一直如此",
                "evidence": [passage], "request_words": name}
        held = run_propose_change(ctx, args).result
        self.assertEqual(held["status"], "second_look")
        self.assertIn(f"{name}：{self.fact['value']}", [item["text"] for item in held["existing"]])
        self.assertTrue(all(item["ref"].startswith("R") for item in held["existing"]))  # citable, and a target for change_fact
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM assistant_changes WHERE task_id=?", task["id"])[0]["n"], 0)
        self.assertEqual(run_propose_change(ctx, args).result["change"], "C1")
        task, ctx, passage, _ = self.setup_task(f"{name}的新状态记进资料")
        other = {**args, "evidence": [passage], "value": "鹦鹉螺号潜艇沉没"}  # a different matter about the same person: not held
        self.assertEqual(run_propose_change(ctx, other).result["change"], "C1")

    def test_a_changed_fact_that_keeps_the_old_words_is_held_back_and_a_new_state_is_not(self):
        name = self.fact["subject"]
        task, ctx, passage, fact = self.setup_task(f"{name}这条资料按最后一章改")
        restated = {"action": "change_fact", "target": fact, "value": self.fact["value"] + "，一直如此", "evidence": [passage], "request_words": name}
        held = run_propose_change(ctx, restated).result
        self.assertEqual(held["status"], "second_look")
        self.assertTrue(held["current"].startswith(self.fact["value"]))
        self.assertEqual(run_propose_change(ctx, restated).result["change"], "C1")
        task, ctx, passage, fact = self.setup_task(f"{name}这条资料按最后一章改")
        moved = {**restated, "target": fact, "evidence": [passage], "value": "鹦鹉螺号潜艇沉没"}
        self.assertEqual(run_propose_change(ctx, moved).result["change"], "C1")

    def test_words_that_share_nothing_with_the_record_are_held_back(self):
        task, ctx, passage, fact = self.setup_task("罗盘那条线最后一章已经收了")
        args = {"action": "change_fact", "target": fact, "value": "鹦鹉螺号潜艇沉没", "evidence": [passage], "request_words": "罗盘那条线"}
        held = run_propose_change(ctx, args).result
        self.assertEqual(held["status"], "second_look")
        self.assertIn("罗盘那条线", held["message"])
        self.assertNotIn("current", held)
        new = {"action": "add_fact", "memory_type": "dynamic_state", "subject": "鹦鹉螺号", "predicate": "status", "value": "潜艇沉没",
               "evidence": [passage], "request_words": "罗盘那条线"}
        self.assertEqual(run_propose_change(ctx, new).result["change"], "C1")  # a new fact has no record to share words with

    def test_a_new_fact_under_a_name_another_fact_holds_as_its_value_is_held_back(self):
        # 3-pass check, w01-no-action-01: "宿鸢跟甄宿微是同一个人" added under 宿鸢 beside "甄宿微 / 别名 / 宿鸢".
        with self.db.connection() as c:
            write_fact(c, self.db, self.project_id, "mem-test-alias", {"memory_type": "static_canon", "subject": self.fact["subject"], "predicate": "identity",
                                                                   "value": "鹦鹉螺", "source_span_id": self.fact["source_span_id"]},
                       self.user_id, "2026-10-23T00:00:00+00:00")
        task, ctx, passage, _ = self.setup_task(f"鹦鹉螺跟{self.fact['subject']}是同一个人，也存到事实里")
        args = {"action": "add_fact", "memory_type": "static_canon", "subject": "鹦鹉螺", "predicate": "identity", "value": f"鹦鹉螺就是{self.fact['subject']}",
                "evidence": [passage], "request_words": "鹦鹉螺跟"}
        held = run_propose_change(ctx, args).result
        self.assertEqual(held["status"], "second_look")
        self.assertIn(f"{self.fact['subject']}：鹦鹉螺", [item["text"] for item in held["existing"]])

    def test_the_last_round_puts_the_item_on_the_card_at_once(self):
        task, ctx, passage, fact = self.setup_task("罗盘那条线最后一章已经收了")
        ctx.last = True  # no round after it to propose again in
        args = {"action": "add_fact", "memory_type": "dynamic_state", "subject": "鹦鹉螺号", "predicate": "status", "value": "潜艇沉没",
                "evidence": [passage], "request_words": "罗盘那条线"}
        self.assertEqual(run_propose_change(ctx, args).result["change"], "C1")


class GroundedTests(SecondLookTests):
    """What an item says comes from its evidence, and from the author only what the evidence bears out (A2 second formal run)."""

    def passage(self, ctx, text):
        return ctx.registry.register("passage", self.chapters[self.last], self.last, "", 0, len(text), text)

    def adding(self, ctx, passage, **fields):
        ctx.last = True  # straight onto the card, past the second look
        return run_propose_change(ctx, {"action": "add_fact", "memory_type": "dynamic_state", "subject": "鹦鹉螺号", "predicate": "location",
                                        "evidence": [passage], "request_words": "鹦鹉螺号", **fields}).result

    def refused(self, ctx, passage, **fields):
        with self.assertRaises(ToolError) as raised:
            self.adding(ctx, passage, **fields)
        return raised.exception.code

    def test_a_number_the_evidence_does_not_state_is_refused(self):
        # w01-no-action-03: a birthday the text never gives, added on an unrelated passage.
        task, ctx, _, _ = self.setup_task("鹦鹉螺号的生日按八月十二号加进去")
        self.assertEqual(self.refused(ctx, self.passage(ctx, "她总把拓纸带在身上。"), value="生日是八月十二号"), "change_value_not_in_evidence")
        stated = self.passage(ctx, "鹦鹉螺号的生日是8月12日，那天下了雨。")  # figures and Chinese numerals are the same numbers
        self.assertEqual(self.adding(ctx, stated, value="生日是八月十二号")["change"], "C1")

    def test_a_chapter_mentioned_in_the_value_is_not_a_number_it_states(self):
        task, ctx, _, _ = self.setup_task("鹦鹉螺号现在停在北港")
        self.assertEqual(self.adding(ctx, self.passage(ctx, "鹦鹉螺号已经停进北港。"), value="自第18章起停在北港")["change"], "C1")

    def test_a_value_the_author_names_and_the_text_does_not_is_held_back_once(self):
        # w02-no-action-04: the author put the bell in a drawer at the service desk; the text has it on the duty desk. Authors also
        # put the text's state in words of their own, so it is a second look, not a refusal.
        task, ctx, _, _ = self.setup_task("鹦鹉螺号到了港口，位置那条替我写成服务台后面的抽屉")
        duty = self.passage(ctx, "铃最后放在值班台门边的小托架上，试过不挡手。")
        args = {"action": "add_fact", "memory_type": "dynamic_state", "subject": "鹦鹉螺号", "predicate": "location", "evidence": [duty],
                "request_words": "鹦鹉螺号", "value": "值班台门边的小托架", "author_value": "服务台后面的抽屉"}
        held = run_propose_change(ctx, args).result
        self.assertEqual(held["status"], "second_look")
        self.assertIn("服务台后面的抽屉", held["message"])
        self.assertEqual(run_propose_change(ctx, args).result["change"], "C1")
        task, ctx, _, _ = self.setup_task("鹦鹉螺号到了港口，位置那条替我写成服务台后面的抽屉")
        duty = self.passage(ctx, "铃最后放在值班台门边的小托架上，试过不挡手。")
        ignored = {**args, "evidence": [duty], "author_value": "值班台"}  # not the author's words: ignored, not refused
        self.assertEqual(run_propose_change(ctx, ignored).result["change"], "C1")

    def test_a_thread_the_author_gives_up_is_not_marked_resolved(self):
        # w02-no-action-06: "把这条伏笔改为放弃" became a resolved thread.
        task = self.change_task(*self.resolving(), question="罗盘那条线最后一章我不追了，改为放弃")
        self.assertEqual(self.step_error(task), "change_give_up_not_resolve")
        self.assertEqual(task["changes"], [])

    def test_a_record_the_author_only_asked_to_read_is_not_changed(self):
        # Second pair, p41, injection-07: "通行安排那条请读全，再……补上" rewrote the record that carried a hidden note.
        task, ctx, _, fact = self.setup_task("资料里鹦鹉螺号那条请读全，再按最后一章把船长补上")
        passage = self.passage(ctx, "鹦鹉螺号的船长是尼摩。")
        with self.assertRaises(ToolError) as raised:
            run_propose_change(ctx, {"action": "change_fact", "target": fact, "value": "鹦鹉螺号潜艇沉没", "evidence": [passage], "request_words": "鹦鹉螺号那条请读全"})
        self.assertEqual(raised.exception.code, "change_read_only")
        self.assertEqual(self.adding(ctx, passage, value="船长是尼摩", request_words="把船长补上")["change"], "C1")  # the clause that asks

    def test_a_fact_asked_about_in_a_facts_words_is_not_a_thread_marked_resolved(self):
        # Second pair, p41, action-08: "尺子折过的事也改掉旧说法" marked a thread resolved.
        task = self.change_task(*self.resolving(words="罗盘那条旧说法"), question="罗盘那条旧说法最后一章改掉")
        self.assertEqual(self.step_error(task), "change_fact_not_thread")
        task = self.change_task(*self.resolving(words="罗盘那条线"), question="罗盘那条线最后一章已经收了")
        self.assertEqual(task["changes"][0]["kind"], "resolve_thread")

    def test_a_sentence_of_the_text_is_not_a_fact(self):
        # Third formal run, w01-no-action-05: "第20章最后一句绕得有点长，帮我拆短" came back as a fact holding the rewrite.
        task, ctx, _, _ = self.setup_task("第20章最后一句绕得有点长，帮我拆短")
        passage = self.passage(ctx, "在那之前，今天能交出的，是钱怎样少了。")
        with self.assertRaises(ToolError) as raised:
            run_propose_change(ctx, {"action": "add_fact", "memory_type": "dynamic_state", "subject": "第20章最后一句", "predicate": "status",
                                     "value": "在那之前，今天能交出的只有三样。", "evidence": [passage], "request_words": "第20章最后一句"})
        self.assertEqual(raised.exception.code, "change_prose_not_fact")

    def test_a_new_fact_under_the_same_subject_that_repeats_some_of_one_is_held_back(self):
        # Third formal run, w02-no-action-02: "双齿筹不会因换手便成为所有权证明" beside "双齿筹（用途）：……不是物件所有权凭证".
        with self.db.connection() as c:
            write_fact(c, self.db, self.project_id, "mem-test-tally", {"memory_type": "static_canon", "subject": "鹦鹉螺号", "predicate": "identity",
                                                                   "value": "标示称量轮次，不是物件所有权凭证", "source_span_id": self.fact["source_span_id"]},
                       self.user_id, "2026-10-23T00:00:00+00:00")
        task, ctx, _, _ = self.setup_task("鹦鹉螺号这个用途限制再存一条")
        self.engine.store.add_step(task["id"], 1, "tool", "查事实", tool_name="lookup_facts", args={"name": "鹦鹉螺号"})
        passage = self.passage(ctx, "鹦鹉螺号不会因换手便成为任何物件的所有权证明。")
        args = {"action": "add_fact", "memory_type": "dynamic_state", "subject": "鹦鹉螺号", "predicate": "rule",
                "value": "不会因换手便成为任何物件的所有权证明", "evidence": [passage], "request_words": "鹦鹉螺号这个用途限制"}
        held = run_propose_change(ctx, args).result
        self.assertEqual(held["status"], "second_look")
        self.assertTrue(any("标示称量轮次" in item["text"] for item in held["existing"]))

    def test_the_round_before_the_last_still_holds_back_but_the_last_does_not(self):
        task, ctx, passage, fact = self.setup_task("罗盘那条线最后一章已经收了")
        args = {"action": "change_fact", "target": fact, "value": "鹦鹉螺号潜艇沉没", "evidence": [passage], "request_words": "罗盘那条线"}
        ctx.forced = True  # the round before the last: forced, yet a round follows
        self.assertEqual(run_propose_change(ctx, args).result["status"], "second_look")
        task, ctx, passage, fact = self.setup_task("罗盘那条线最后一章已经收了")
        ctx.forced = ctx.last = True
        self.assertEqual(run_propose_change(ctx, {**args, "target": fact, "evidence": [passage]}).result["change"], "C1")

    def test_the_answer_waits_while_an_item_is_held_back_in_its_round(self):
        # Three cards of the second formal run came out empty: the item was held back and the answer in the same round closed the task.
        name = self.fact["subject"]

        def propose_and_answer(provider, messages):
            return turn(change_call(action="add_fact", memory_type="dynamic_state", subject=name, predicate="status", value=self.fact["value"] + "，一直如此",
                                    evidence=[refs(messages, self.last)[0]], request_words=name),
                        answer_call("answered", [("最后一章写到了这件事。", [refs(messages, self.last)[0]])]))

        task = self.change_task(turn(call("lookup_facts", name=name), call("read_chapter", chapter_number=self.last)), propose_and_answer,
                                propose_and_answer, question=f"{name}的新状态记进资料")
        answers = [s["error_code"] for s in self.engine.store.steps(task["id"]) if s["tool_name"] == "answer"]
        self.assertEqual(answers[0], "change_held_back")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(len(task["changes"]), 1)


class DisplayTests(unittest.TestCase):
    """How a fact item reads on the card and in the ledger (the v2.0 visual pass)."""

    class Chapter:
        def __init__(self, number):
            self.number = number

        def execute(self, *args):
            number = self.number

            class Row:
                def fetchone(self):
                    return {"chapter_number": number}
            return Row()

    def test_a_value_has_no_full_stop_before_its_chapter_and_names_a_chapter_once(self):
        from app.assistant_actions import _fact_label
        label = lambda value, number: _fact_label(self.Chapter(number), {"value": value, "source_span_id": "span"})
        self.assertEqual(label("由温岚保管。", 10), "由温岚保管（第 10 章）")
        self.assertEqual(label("第4章上午尚不知道廊桥钥匙的含义", 4), "第4章上午尚不知道廊桥钥匙的含义")
        self.assertEqual(label("自第十八章起允许非世袭证人发言", 18), "自第十八章起允许非世袭证人发言")
        self.assertEqual(label("第4章上午尚不知道", 10), "第4章上午尚不知道（第 10 章）")  # another chapter: still given

    def test_a_property_in_the_authors_own_words_names_itself(self):
        from app.assistant_actions import _fact_title
        self.assertEqual(_fact_title({"subject": "温岚", "predicate": "status"}), "温岚·状态")
        self.assertEqual(_fact_title({"subject": "麴承荫", "predicate": "旧誓附页认知"}), "麴承荫·旧誓附页认知")
        self.assertEqual(_fact_title({"subject": "温岚", "predicate": "some_key"}), "温岚·其他属性")


if __name__ == "__main__":
    unittest.main()
