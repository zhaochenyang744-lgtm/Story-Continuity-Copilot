"""Prompt assistant-p18, after the p17 checks on both spent A1c pairs: a cited sentence about what the text does not say
is returned (and dropped once the repair is spent); a proposal repair says what is there and what is missing; a failed
check_passage is not retried."""
from __future__ import annotations

import sqlite3
import unittest

from app.assistant import SYSTEM_PROMPT, refusal_problems, refusal_sentences, validate_answer
from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, ref_of_chapter, turn
from tests.test_assistant_limits import read

SOURCES = {"R1": {"ref": "R1", "kind": "passage", "chapter_number": 8,
                  "text": "邵芃羽在接待廊的纸质登记表上撤回下一次预约，佟映葵当场划去了对应的占位。他没有写回信。"}}


def cited(*texts):
    return [{"text": text, "refs": ["R1"]} for text in texts]


class AbsenceSentenceTests(unittest.TestCase):
    def test_what_the_text_does_not_say_is_flagged(self):
        sentences = cited("第八章写的是邵芃羽在登记表上撤回，不是打电话取消。", "第八章写的是佟映葵当场划去了占位，没有写接待员另作处理。",
                          "正文没有提到电话。")
        self.assertEqual(refusal_sentences(sentences, SOURCES), [0, 1, 2])
        self.assertEqual(refusal_problems(sentences, SOURCES)[0], "第 1 句说的是原文没写什么或不是什么，这类话不能挂出处，写进 note")

    def test_story_content_and_two_sides_are_not(self):
        sentences = cited("邵芃羽在接待廊的纸质登记表上撤回下一次预约。", "他没有写回信。", "第8章写的是二十三岁，而第26章写的是二十七岁。")
        self.assertEqual(refusal_sentences(sentences, SOURCES), [])

    def test_a_fix_answer_is_not_held_to_it(self):
        cleaned, problems = validate_answer({"status": "answered", "sentences": cited("正文没有提到电话。")}, {"R1"}, SOURCES, "fix_issue")
        self.assertEqual(problems, [])


class AbsenceRepairTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    @staticmethod
    def reply(*texts):
        def build(provider, messages):
            refs = [ref_of_chapter(messages, 9)]
            return turn(answer_call("answered", [(text, refs) for text in texts]))
        return build

    def test_returned_once_then_dropped(self):
        task = self.run_ask(read(9), self.reply("苏岑把罗盘交给了温岚保管。", "第九章写的是交给温岚，不是交给别人。"),
                            self.reply("苏岑把罗盘交给了温岚保管。", "正文没有提到别人。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertIn("说的是原文没写什么或不是什么", self.all_messages())
        self.assertEqual([s["text"] for s in task["answer"]["sentences"]], ["苏岑把罗盘交给了温岚保管。"])


class PromptTextTests(unittest.TestCase):
    def test_a_failed_check_is_not_retried(self):
        self.assertIn("check_passage 返回错误（例如 input_budget_exceeded）时不要再试，直接用 propose_edit 提出改法", SYSTEM_PROMPT)


class ProposalRepairTextTests(unittest.TestCase):
    def test_the_repair_names_what_is_there_and_what_is_missing(self):
        from app import assistant_edits

        class Db:
            def __init__(self, rows):
                self.c = sqlite3.connect(":memory:")
                self.c.row_factory = sqlite3.Row
                self.c.execute("CREATE TABLE assistant_proposals (id TEXT, task_id TEXT, ordinal INT, kind TEXT, rationale TEXT)")
                for i, kind in enumerate(rows, 1):
                    self.c.execute("INSERT INTO assistant_proposals VALUES (?,?,?,?,?)", (f"p{i}", "t", i, kind, "理由"))

            def connection(self):
                return self.c

        class Ctx:
            def __init__(self, rows):
                self.db, self.task, self.scope = Db(rows), {"id": "t"}, {}

        problems = assistant_edits.validate_proposals(Ctx(["edit_this", "edit_this"]))
        self.assertEqual(len(problems), 1)
        self.assertIn("现在已有：edit_this ×2", problems[0])
        self.assertIn("intentional", problems[0])
        self.assertIn("还缺一个 edit_this", assistant_edits.validate_proposals(Ctx(["add_setup", "intentional"]))[0])
        self.assertEqual(assistant_edits.validate_proposals(Ctx(["edit_this", "intentional"])), [])


if __name__ == "__main__":
    unittest.main()


class P19PromptTests(unittest.TestCase):
    """assistant-p19: an edit request is answered in one or two cited sentences; edit_this replaces only the sentence."""

    def test_edit_request_answers_only_what_is_asked(self):
        self.assertIn("带出处的句子只回答问题里真正问的那件事，一般一两句；不要为了说明为什么不能改，去引用别的段落", SYSTEM_PROMPT)

    def test_edit_this_replaces_only_the_sentence(self):
        import inspect
        from app import assistant
        self.assertIn("edit_this 的 before 只放出问题的那一句本身，不要把旁边的句子或草稿里的批注一起改", inspect.getsource(assistant))
