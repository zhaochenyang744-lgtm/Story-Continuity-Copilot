"""Task 07b: process lines, phases, step details, out-of-scope, free-text guards, feedback, regenerate, edit-and-resend,
hand-edited adoption and the rollout switch. Everything runs on a scripted model."""
from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import patch

from app import assistant as assistant_module
from app.assistant import ASSISTANT_PROMPT_VERSION, SYSTEM_PROMPT, validate_answer
from app.assistant_store import ADDED_COLUMNS
from app.assistant_tools import ERROR_TEXTS, GENERIC_ERROR_TEXT, OUT_OF_SCOPE_TEXT, ToolError, error_text, result_refs, run_tool, tools_for

from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, text, turn
from tests.test_assistant import cite
from tests.test_assistant_limits import read
from tests.test_assistant_v180 import FINAL, Task04Case


def closing(content: str, *chapters: int):
    """A cited answer whose reply also carries free text (the model sometimes talks while it answers)."""
    inner = cite(*(chapters or (9,)))

    def build(provider, messages):
        scripted = inner(provider, messages)
        scripted["content"] = content
        return scripted
    return build


def says(task: dict) -> list[str]:
    return [step["summary"] for step in task["steps"] if step["kind"] == "say"]


class SayTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_the_prompt_asks_for_a_line_and_is_version_p5(self):
        self.assertEqual(ASSISTANT_PROMPT_VERSION, "assistant-p44")
        self.assertIn("content 里写一句话说明这一步具体要做什么", SYSTEM_PROMPT)
        self.assertIn("中文不超过 40 字，英文不超过 20 个词；只说打算，不下结论", SYSTEM_PROMPT)
        self.assertIn("不要只写文字", SYSTEM_PROMPT)
        self.assertIn("out_of_scope", SYSTEM_PROMPT)
        self.assertIn("note 只列出查过哪些地方", SYSTEM_PROMPT)
        self.assertIn("不写 R 编号", SYSTEM_PROMPT)
        task = self.run_ask(read(9), cite(9))
        self.assertEqual(self.rows("SELECT prompt_version FROM assistant_tasks")[0]["prompt_version"], "assistant-p44")
        self.assertEqual(task["status"], "completed")

    def test_a_tool_round_keeps_its_line_before_its_steps_and_the_closing_round_keeps_none(self):
        task = self.run_ask(
            turn(call("search_text", query="罗盘"), content="  先在全书里找罗盘出现的地方  "),
            read(9, content="再去第九章看原文"),
            closing("答案已经查到：结论是苏岑把罗盘交给了温岚。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([step["kind"] for step in task["steps"]], ["say", "tool", "say", "tool"])
        # v1.9.0: the line is written from the round's calls, not taken from the model (A1c SPEC addendum 14, item 38).
        self.assertEqual(says(task), ["我先搜正文「罗盘」。", "我再读第 9 章。"])
        line = task["steps"][0]
        self.assertEqual((line["tool"], line["group"], line["refs"], line["error_code"], line["error_text"], line["round"]), (None, None, [], None, None, 1))
        self.assertNotIn("答案已经查到", json.dumps(task, ensure_ascii=False))
        self.assertEqual([row["summary"] for row in self.rows("SELECT summary FROM assistant_steps WHERE kind='say' ORDER BY ordinal")], says(task))

    def test_nothing_the_model_writes_beside_its_calls_reaches_the_line(self):
        long = "先" + "查" * 80
        task = self.run_ask(
            read(1, content=long), read(2, content="第2章写的是苏岑交出罗盘，我再读"), read(3, content="先看 R2 那一条"),
            read(4, content="去查 span-1a2b3c 这段"), read(5, content="   "), read(6, content=None), cite(1))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(says(task), ["我先读第 1 章。"] + [f"我再读第 {n} 章。" for n in range(2, 7)])
        self.assertEqual(len([step for step in task["steps"] if step["kind"] == "tool"]), 6)

    def test_only_the_first_line_of_a_round_and_nothing_from_forced_or_plain_text_rounds(self):
        task = self.run_ask(
            text("我先想想要怎么查"),
            turn(call("read_chapter", chapter_number=1), call("read_chapter", chapter_number=2), content="先读前两章"),
            read(3, content="读第三章"), read(4, content="读第四章"), read(5, content="读第五章"), read(6, content="读第六章"),
            read(7, content="已经到了收尾，这句不该保存"), cite(1))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(says(task), ["我先读第 1、2 章。", "我再读第 3 章。", "我再读第 4 章。", "我再读第 5 章。", "我再读第 6 章。"])
        self.assertEqual(sum(step["kind"] == "protocol_error" for step in task["steps"]), 1)


class StepDetailTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_steps_share_a_group_per_line_and_tool_and_carry_their_refs(self):
        task = self.run_ask(
            turn(call("search_text", query="罗盘"), call("search_text", query="温岚"), call("lookup_facts", name="黄铜罗盘"), content="先搜两处正文，再查事实"),
            turn(call("read_chapter", chapter_number=9), call("read_chapter", chapter_number=99), content="读第九章"),
            cite(9))
        self.assertEqual(task["status"], "completed", task)
        tools = [step for step in task["steps"] if step["kind"] == "tool"]
        groups = [step["group"] for step in tools]
        self.assertTrue(all(groups))
        self.assertEqual(groups[0], groups[1])
        self.assertEqual(len({groups[0], groups[2], groups[3]}), 3)
        self.assertEqual(groups[3], groups[4])
        results = [json.loads(m["content"]) for m in self.provider.calls[1]["messages"] if m["role"] == "tool"]
        for step, result in zip(tools[:3], results[:3]):
            self.assertEqual(step["refs"], result_refs(result))
            self.assertTrue(step["refs"], step)
        self.assertEqual([step["refs"] for step in tools[3:]], [result_refs(json.loads(m["content"])) for m in self.provider.calls[2]["messages"] if m["role"] == "tool"][3:])
        self.assertEqual(tools[4]["refs"], [])
        # A later round with the same tool is another group.
        later = self.run_ask(read(9, content="读第九章"), read(10, content="再读第十章"), cite(9))
        reads = [step["group"] for step in later["steps"] if step["kind"] == "tool"]
        self.assertNotEqual(reads[0], reads[1])
        self.assertEqual(self.rows("SELECT refs_json FROM assistant_steps WHERE kind='say' LIMIT 1")[0]["refs_json"], None)

    def test_every_registered_source_comes_back_and_the_cited_ones_are_marked(self):
        task = self.run_ask(turn(call("search_text", query="罗盘")), read(9), cite(9))
        stored = self.rows("SELECT ref FROM assistant_sources")
        self.assertEqual(set(task["sources"]), {row["ref"] for row in stored})
        cited = {ref for sentence in task["answer"]["sentences"] for ref in sentence["refs"]}
        self.assertEqual({ref for ref, source in task["sources"].items() if source["cited"]}, cited)
        self.assertTrue(any(not source["cited"] for source in task["sources"].values()))
        self.assertEqual(list(task["sources"]), sorted(task["sources"], key=lambda ref: int(ref[1:])))
        for source in task["sources"].values():
            self.assertEqual(set(source), {"kind", "chapter_number", "chapter_title", "start", "end", "text", "cited"})

    def test_a_failed_step_is_returned_with_its_code_and_a_plain_reason(self):
        task = self.run_ask(
            turn(call("read_chapter", chapter_number=99), call("search_text", query=""), call("nonsense")),
            turn(answer_call("answered", [("没有出处的话。", ["R99"])])),
            read(9), cite(9))
        self.assertEqual(task["status"], "completed", task)
        failed = [(step["kind"], step["error_code"], step["error_text"]) for step in task["steps"] if step["error_code"]]
        self.assertEqual(failed, [("tool", "chapter_out_of_scope", "这一章不在可查范围内"), ("tool", "invalid_arguments", GENERIC_ERROR_TEXT),
                                  ("tool", "unknown_tool", GENERIC_ERROR_TEXT), ("repair", "citation_validation_failed", "引用没对上，重新整理回答")])
        ok = next(step for step in task["steps"] if step["kind"] == "tool" and step["result_count"])
        self.assertEqual((ok["error_code"], ok["error_text"]), (None, None))

    def test_the_reason_table(self):
        self.assertEqual(ERROR_TEXTS, {
            "proposal_before_not_unique": "原句在草稿里出现了不止一次", "proposal_issue_not_overlapped": "改的不是有问题的那一句",
            "proposal_after_contains_before": "改后的句子原样保留了原句", "edit_this_is_for_the_current_draft": "只能改本章草稿",
            "chapter_out_of_scope": "这一章不在可查范围内", "citation_validation_failed": "引用没对上，重新整理回答",
            "proposal_after_failed_check": "这句改后的话检查时仍有矛盾",
            # v2.0: a change the assistant proposes
            "change_target_invalid": "要改的资料没对上", "change_evidence_invalid": "依据不是读到过的正文段落",
            "change_evidence_before_planted": "依据在伏笔埋下之前", "change_thread_not_open": "这条伏笔已经不是待回收的状态",
            "change_duplicate": "这条资料已经提出过改动", "change_limit_reached": "一张卡片最多 5 条改动",
            "change_value_invalid": "改后的内容不合要求", "change_no_difference": "资料里已经是这样",
            "change_fields_invalid": "事实的类型或属性不在可选范围内", "change_fact_already_recorded": "资料里已经有这条事实",
            "change_check_existing": "先查一遍资料里已有的事实", "change_value_not_in_evidence": "改后内容里的数字在依据段落里没有",
            "change_give_up_not_resolve": "作者要的是放弃或删除，这一版不支持",
            "change_read_only": "作者只说要看这条资料，没有说要改", "change_prose_not_fact": "作者要改的是正文的句子，不是资料", "change_fact_not_thread": "作者说的是事实，不是伏笔", "change_held_back": "还有改动没有放进卡片，先处理它",
            "change_not_requested": "作者的话里没有提到这条资料",
            "change_request_words_taken": "作者这几个字已经对应了另一条改动"})
        self.assertEqual(error_text("assistant_protocol_error"), "这一步没成功")
        self.assertIsNone(error_text(None))

    def test_an_old_database_gets_the_new_columns_and_its_old_steps_still_show(self):
        task = self.run_ask(read(9), cite(9))
        with self.db.connection() as c:
            c.execute("DROP TABLE assistant_feedback")
            for table, columns in ADDED_COLUMNS.items():
                for name, _ in columns:
                    if name not in ("recheck_json", "adopted_draft_revision"):
                        c.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
        self.engine.store.initialize()
        self.engine.store.initialize()
        for table, columns in ADDED_COLUMNS.items():
            have = {row["name"] for row in self.rows(f"PRAGMA table_info({table})")}
            self.assertTrue({name for name, _ in columns} <= have, table)
        self.assertTrue(self.rows("SELECT name FROM sqlite_master WHERE name='assistant_feedback'"))
        again = self.task(task["id"])
        self.assertEqual([step["refs"] for step in again["steps"]], [[], []])
        self.assertEqual((again["feedback"], again["regenerated_from"], again["phase"]), (None, None, None))
        self.assertEqual(self.run_ask(read(9), cite(9))["status"], "completed")


class PhaseTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def view(self):
        task_id = self.rows("SELECT id FROM assistant_tasks")[0]["id"]
        return self.task(task_id)

    def test_the_phase_follows_the_model_and_the_tools(self):
        seen = []

        def thinking(provider, messages):
            view = self.view()
            seen.append(("thinking", view["status"], view["phase"], view["phase_tool"], view["phase_chapter"], view["phase_started_at"], view["started_at"], view["completed_at"]))
            return turn(call("read_chapter", chapter_number=9), call("lookup_facts", name="温岚"))

        def thinking_again(provider, messages):
            view = self.view()
            seen.append(("thinking", view["status"], view["phase"], view["phase_tool"], view["phase_chapter"], view["phase_started_at"], view["started_at"], view["completed_at"]))
            return cite(9)(provider, messages)

        real = assistant_module.run_tool

        def watched(name, kind, ctx, args):
            view = self.view()
            seen.append((name, view["status"], view["phase"], view["phase_tool"], view["phase_chapter"], view["phase_started_at"], view["started_at"], view["completed_at"]))
            return real(name, kind, ctx, args)

        self.provider.script(thinking, thinking_again)
        with patch.object(assistant_module, "run_tool", side_effect=watched):
            response = self.ask()
        queued = response.json()["data"]
        self.assertEqual((queued["status"], queued["phase"], queued["phase_tool"], queued["phase_chapter"], queued["phase_started_at"], queued["started_at"]),
                         ("queued", None, None, None, None, None))
        self.assertEqual([(label, status, phase, tool, chapter) for label, status, phase, tool, chapter, *_ in seen], [
            ("thinking", "running", "thinking", None, None),
            ("read_chapter", "running", "tool", "read_chapter", 9),
            ("lookup_facts", "running", "tool", "lookup_facts", None),
            ("thinking", "running", "thinking", None, None)])
        for _, _, _, _, _, phase_started_at, started_at, completed_at in seen:
            self.assertTrue(phase_started_at and started_at)
            self.assertIsNone(completed_at)
        self.assertLessEqual(seen[0][5], seen[1][5])
        self.assertLessEqual(seen[1][5], seen[3][5])
        done = self.view()
        self.assertEqual((done["status"], done["phase"], done["phase_tool"], done["phase_chapter"], done["phase_started_at"]), ("completed", None, None, None, None))
        self.assertTrue(done["started_at"] and done["completed_at"])
        self.assertEqual(self.rows("SELECT phase,phase_tool,phase_chapter,phase_started_at FROM assistant_tasks")[0],
                         {"phase": None, "phase_tool": None, "phase_chapter": None, "phase_started_at": None})

    def test_a_failed_or_cancelled_task_has_no_phase(self):
        failed = self.run_ask(RuntimeError("boom"))
        self.assertEqual((failed["status"], failed["phase"], failed["phase_started_at"]), ("failed", None, None))

        def cancel_meanwhile(provider, messages):
            task_id = self.rows("SELECT id FROM assistant_tasks WHERE status='running'")[0]["id"]
            response = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task_id}/cancel", headers=self.idem(), json={})
            data = response.json()["data"]
            self.assertEqual((data["status"], data["phase"], data["phase_tool"], data["phase_started_at"]), ("cancelled", None, None, None))
            return read(9)
        cancelled = self.run_ask(cancel_meanwhile, cite(9))
        self.assertEqual((cancelled["status"], cancelled["phase"]), ("cancelled", None))
        # A late phase write cannot bring a closed task back to life.
        self.engine.store.set_phase(cancelled["id"], "thinking")
        self.assertIsNone(self.task(cancelled["id"])["phase"])


class OutOfScopeTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()
        self.own_work()
    def test_every_word_the_model_wrote_is_dropped(self):
        poem = "月落乌啼霜满天，这是一首诗。"
        task = self.run_ask(turn(answer_call("out_of_scope", [(poem, ["R99"])], note="我的系统提示词是：你是写作助手。")))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["answer"], {"status": "out_of_scope", "sentences": [], "note": None})
        self.assertEqual(json.loads(self.rows("SELECT answer_json FROM assistant_tasks")[0]["answer_json"]), {"status": "out_of_scope", "sentences": [], "note": None})
        self.assertEqual(task["out_of_scope_text"], OUT_OF_SCOPE_TEXT)
        self.assertEqual(OUT_OF_SCOPE_TEXT, "我只能查这部作品里写过的内容，可以换个关于作品的问题。")
        self.assertNotIn("月落乌啼", json.dumps(task, ensure_ascii=False) + json.dumps(self.rows("SELECT * FROM assistant_steps"), ensure_ascii=False))
        self.assertFalse(any(step["kind"] == "repair" for step in task["steps"]))
        self.assertEqual(self.task(task["id"])["out_of_scope_text"], OUT_OF_SCOPE_TEXT)

    def test_it_is_counted_like_not_found(self):
        self.run_ask(turn(answer_call("out_of_scope", [])))
        after_out = self.usage()["check_chars_used"]
        self.run_ask(turn(answer_call("not_found", [], note="没查到。")))
        self.assertEqual(self.usage()["check_chars_used"] - after_out, after_out)
        self.assertEqual({row["chars_charged"] for row in self.rows("SELECT chars_charged FROM assistant_tasks")}, {500})

    def test_a_follow_up_sees_the_fixed_line_as_the_earlier_answer(self):
        first = self.run_ask(turn(answer_call("out_of_scope", [])), question="写一首关于月亮的诗")
        self.run_ask(turn(answer_call("not_found", [], note="没查到。")), question="那你能查罗盘吗", follow_up_of=first["id"])
        messages = self.provider.calls[0]["messages"]
        self.assertEqual([(m["role"], m["content"]) for m in messages[1:3]], [("user", "作者的问题：写一首关于月亮的诗"), ("assistant", OUT_OF_SCOPE_TEXT)])

    def test_only_an_ask_may_use_it(self):
        sources = {"R1": {"kind": "passage", "chapter_number": 2}}
        self.assertEqual(validate_answer({"status": "out_of_scope", "sentences": [{"text": "诗", "refs": ["R9"]}]}, {"R1"}, sources),
                         ({"status": "out_of_scope", "sentences": [], "note": None}, []))
        for kind in ("fix_issue", "recap"):
            cleaned, problems = validate_answer({"status": "out_of_scope", "sentences": []}, {"R1"}, sources, kind)
            self.assertEqual(cleaned, None)
            self.assertTrue(problems)
        scope = {"max_chapter": 10, "draft_readable": True, "issue_nature": "confirmed_conflict"}

        def statuses(kind):
            answer = next(tool for tool in tools_for(kind, scope) if tool["function"]["name"] == "answer")
            return answer["function"]["parameters"]["properties"]["status"]["enum"]
        self.assertIn("out_of_scope", statuses("ask"))
        self.assertNotIn("out_of_scope", statuses("fix_issue"))
        self.assertNotIn("answer", [tool["function"]["name"] for tool in tools_for("recap", scope)])


class FixOutOfScopeTests(Task04Case):
    def test_a_fix_cannot_end_out_of_scope(self):
        task = self.fix(self.proposals_turn(), turn(answer_call("out_of_scope", [])), FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["answer"]["status"], "not_found")
        self.assertEqual([(s["kind"], s["error_code"]) for s in task["steps"] if s["kind"] == "repair"], [("repair", "citation_validation_failed")])


class GuardTests(Task04Case):
    def test_a_note_with_an_internal_id_is_repaired_once(self):
        task = self.run_ask(turn(answer_call("not_found", [], note="查了 span-1a2b3c4d，没找到。")), turn(answer_call("not_found", [], note="查了正文，没找到。")))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["answer"]["note"], "查了正文，没找到。")
        self.assertEqual([s["kind"] for s in task["steps"]], ["repair"])
        feedback = [m for m in self.provider.calls[1]["messages"] if m["role"] == "tool"][-1]["content"]
        self.assertIn("note", feedback)
        failed = self.run_ask(turn(answer_call("not_found", [], note="见 mem-0f0f0f0f")), turn(answer_call("not_found", [], note="见 claim-0f0f0f0f")))
        self.assertEqual((failed["status"], failed["error_code"]), ("failed", "citation_validation_failed"))

    def test_a_reason_with_an_internal_id_is_withdrawn_and_proposed_again(self):
        sentence = self.issue("confirmed_conflict")["sentence"]
        leaky = turn(call("propose_edit", kind="edit_this", before=sentence, after="苏岑摸了摸空着的内袋，罗盘仍在温岚手里。", rationale="依据 mem-0a1b2c3d 只改物件位置。"),
                     call("propose_edit", kind="intentional", rationale="这是有意留下的疑点。"))
        clean = turn(call("propose_edit", kind="edit_this", before=sentence, after="苏岑摸了摸空着的内袋，罗盘仍在温岚手里。", rationale="只改物件位置。"))
        task = self.fix(leaky, FINAL, clean, FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([s["kind"] for s in task["steps"] if s["kind"] == "repair"], ["repair"])
        self.assertEqual({p["kind"] for p in task["proposals"]}, {"edit_this", "intentional"})
        self.assertEqual(len(task["proposals"]), 2)
        self.assertNotIn("mem-0a1b2c3d", json.dumps(task, ensure_ascii=False))
        self.assertEqual(len({p["proposal"] for p in task["proposals"]}), 2)
        self.assertIn("理由里出现了内部标识", self.all_messages())
        # Proposed again with the same leak, the repair is spent and the task fails (and the leak is never stored).
        again = self.fix(leaky, FINAL, leaky, FINAL)
        self.assertEqual((again["status"], again["error_code"]), ("failed", "citation_validation_failed"))
        self.assertNotIn("mem-0a1b2c3d", json.dumps(self.rows("SELECT rationale FROM assistant_proposals WHERE rationale LIKE '%mem-%'")))

    def test_an_after_with_an_internal_id_is_refused_by_the_tool(self):
        task = self.fix(self.proposals_turn(), FINAL)
        ctx = self.ctx(task)
        sentence = ctx.scope["issue_sentence"]
        before = len(self.rows("SELECT * FROM assistant_proposals"))
        with self.assertRaises(ToolError) as caught:
            run_tool("propose_edit", "fix_issue", ctx, {"kind": "edit_this", "before": sentence, "after": "苏岑摸着 span-1a2b3c 内袋。", "rationale": "理由"})
        self.assertEqual(caught.exception.code, "proposal_text_internal_id")
        with self.assertRaises(ToolError) as caught:
            run_tool("propose_edit", "fix_issue", ctx, {"kind": "add_setup", "chapter_number": 9, "after": "她收好了 claim-ab12cd。", "rationale": "理由"})
        self.assertEqual(caught.exception.code, "proposal_text_internal_id")
        self.assertEqual(len(self.rows("SELECT * FROM assistant_proposals")), before)


class InternalErrorTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_an_unexpected_error_keeps_only_its_type_name(self):
        task = self.run_ask(RuntimeError("稿子里的秘密句子：温岚的口令是冷瓷盆"))
        self.assertEqual((task["status"], task["error_code"]), ("failed", "internal_error"))
        row = self.rows("SELECT internal_error_type FROM assistant_tasks")[0]
        self.assertEqual(row["internal_error_type"], "RuntimeError")
        dump = json.dumps({table: self.rows(f"SELECT * FROM {table}") for table in ("assistant_tasks", "assistant_steps", "assistant_sources")}, ensure_ascii=False)
        self.assertNotIn("冷瓷盆", dump)
        self.assertNotIn("internal_error_type", task)
        self.assertNotIn("RuntimeError", json.dumps(task))

    def test_a_database_error_is_named_without_its_message(self):
        with patch.object(self.engine, "_initial_messages", side_effect=sqlite3.OperationalError("database is locked")):
            task = self.run_ask(turn(answer_call("not_found", [], note="x")))
        self.assertEqual(task["error_code"], "internal_error")
        self.assertEqual(self.rows("SELECT internal_error_type FROM assistant_tasks")[0]["internal_error_type"], "OperationalError")
        self.assertNotIn("locked", json.dumps(self.rows("SELECT * FROM assistant_tasks")))

    def test_other_failures_and_successes_leave_it_empty(self):
        self.run_ask(read(9), cite(9))
        self.run_ask(turn(answer_call("answered", [("甲。", ["R99"])]), ), turn(answer_call("answered", [("乙。", ["R98"])])))
        self.assertEqual({row["internal_error_type"] for row in self.rows("SELECT internal_error_type FROM assistant_tasks")}, {None})


if __name__ == "__main__":
    unittest.main()
