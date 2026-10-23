"""Prompt assistant-p14: a process line that names more than the round's calls is not shown; cited sentences name people
and add nothing; a recap item is one thing. The lines below are from the p12/p13 checks on the spent A1c pair."""
from __future__ import annotations

import unittest

from app.assistant import SYSTEM_PROMPT
from app.assistant_recap import INSTRUCTION
from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, ref_of_chapter, turn


class UnmatchedLineIsNotShownTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_a_line_promising_more_is_replaced_by_one_written_from_the_calls(self):
        # v1.9.0: the line shown is written from the round's calls (A1c SPEC addendum 14, item 38).
        def search(provider, messages):
            return turn(call("read_chapter", chapter_number=9), content="我先读第9章，并查苏岑的事实。")

        def close(provider, messages):
            return turn(answer_call("answered", [("苏岑把罗盘交给了温岚保管。", [ref_of_chapter(messages, 9)])]))
        task = self.run_ask(search, close)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([s["summary"] for s in task["steps"] if s["kind"] == "say"], ["我先读第 9 章。"])
        self.assertEqual([s["tool"] for s in task["steps"] if s["kind"] == "tool"], ["read_chapter"])

    def test_a_matching_line_is_written_from_the_calls_too(self):
        def search(provider, messages):
            return turn(call("read_chapter", chapter_number=9), content="我先读第9章。")

        def close(provider, messages):
            return turn(answer_call("answered", [("苏岑把罗盘交给了温岚保管。", [ref_of_chapter(messages, 9)])]))
        task = self.run_ask(search, close)
        self.assertEqual([s["summary"] for s in task["steps"] if s["kind"] == "say"], ["我先读第 9 章。"])


class PromptTextTests(unittest.TestCase):
    def test_sentences_add_nothing_and_name_people(self):
        self.assertIn("不补出处里没写的动作、原因或先后关系", SYSTEM_PROMPT)
        self.assertIn("不同出处里的事不要拼成一句", SYSTEM_PROMPT)
        self.assertIn("句子里说到人物时写出名字，不用「他」「她」开头", SYSTEM_PROMPT)

    def test_a_recap_item_is_one_thing(self):
        self.assertIn("每条只写一件事，挂的出处要直接写着这件事；不要把不同出处里的两件事拼成一条", INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
