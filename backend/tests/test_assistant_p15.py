"""Prompt assistant-p15, after a1c-formal-second: a reply without a tool call is followed by a call that must use a tool;
"the text says it is still unknown" is not_found; a process line is held to its action clauses, and a chapter it names
must be read or searched near it."""
from __future__ import annotations

import json
import unittest

from app.assistant import SYSTEM_PROMPT, say_matches_calls
from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, ref_of_chapter, turn


def calls(*made):
    return [{"name": name, "arguments": json.dumps(args, ensure_ascii=False)} for name, args in made]


WHOLE_BOOK = {"chapter_from": 1, "chapter_to": 30}


class SayFilterTests(unittest.TestCase):
    def test_a_whole_book_search_does_not_look_at_one_chapter(self):
        line = "我先读本章草稿和这条检查结果的依据，再核对第11章原文。"
        self.assertFalse(say_matches_calls(line, calls(("read_draft", {}), ("get_issues", {}), ("search_text", {"query": "姐妹", **WHOLE_BOOK}))))
        self.assertTrue(say_matches_calls(line, calls(("read_draft", {}), ("get_issues", {}), ("search_text", {"query": "姐妹", "chapter_from": 9, "chapter_to": 13}))))

    def test_the_text_of_a_chapter_is_not_reached_by_facts(self):
        made = calls(("lookup_facts", {"name": "聂沅絮", "chapter_to": 15}), ("lookup_facts", {"name": "黎斐筠", "chapter_to": 15}))
        self.assertFalse(say_matches_calls("我先查第15章结尾的细节，以及出场人物在第15章为止的最新状态。", made))
        self.assertTrue(say_matches_calls("我先查出场人物截至第15章的最新状态。", made))

    def test_context_is_not_held_but_this_pair_is(self):
        context = "关于第8章和第26章的出生地，我再用别的说法搜一遍。"
        self.assertTrue(say_matches_calls(context, calls(("search_text", {"query": "老家", **WHOLE_BOOK}))))
        # p17: announcing the conflict itself is a finding, and such a line is not shown.
        self.assertFalse(say_matches_calls("第8章和第26章对出生地的说法互相矛盾，我再用别的说法搜一遍。", calls(("search_text", {"query": "老家", **WHOLE_BOOK}))))
        pair = "第14章写八百升，第28章写一千二百升，我再核对这两处原文和计划。"
        self.assertFalse(say_matches_calls(pair, calls(("read_chapter", {"chapter_number": 14}), ("get_plans", {"chapter_number": 28}))))
        self.assertTrue(say_matches_calls(pair, calls(("read_chapter", {"chapter_number": 14}), ("read_chapter", {"chapter_number": 28}), ("get_plans", {}))))

    def test_a_carried_on_clause_shares_the_action(self):
        line = "我再核对第7章正文，以及第23、28章用左手的写法。"
        self.assertFalse(say_matches_calls(line, calls(("read_chapter", {"chapter_number": 7}), ("search_text", {"query": "左手", **WHOLE_BOOK}))))

    def test_closing_is_never_beside_the_line(self):
        self.assertFalse(say_matches_calls("我先提出两种改法，再收尾。", calls(("propose_edit", {}), ("propose_edit", {}))))
        self.assertTrue(say_matches_calls("我再核对第30章正文里各人收尾时的状态。", calls(("read_chapter", {"chapter_number": 30}))))


class ToolRequiredAfterAPlainReplyTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_the_call_after_a_reply_without_tools_must_use_a_tool(self):
        def close(provider, messages):
            return turn(answer_call("answered", [("苏岑把罗盘交给了温岚保管。", [ref_of_chapter(messages, 9)])]))
        task = self.run_ask(turn(call("read_chapter", chapter_number=9)), turn(content="苏岑把罗盘交给了温岚。", finish_reason="stop"), close)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([c["tool_choice"] for c in self.provider.calls], ["auto", "auto", "required"])


class PromptTextTests(unittest.TestCase):
    def test_unknown_in_the_text_is_not_found(self):
        self.assertIn("正文或事实里明确写着问到的这件事还不知道", SYSTEM_PROMPT)
        self.assertIn("也用 not_found，不用 answered", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
