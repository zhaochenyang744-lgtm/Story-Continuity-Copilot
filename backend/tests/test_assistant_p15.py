"""Prompt assistant-p15, after a1c-formal-second: a reply without a tool call is followed by a call that must use a tool;
"the text says it is still unknown" is not_found; a process line is held to its action clauses, and a chapter it names
must be read or searched near it."""
from __future__ import annotations

import unittest

from app.assistant import SYSTEM_PROMPT
from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, ref_of_chapter, turn


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
