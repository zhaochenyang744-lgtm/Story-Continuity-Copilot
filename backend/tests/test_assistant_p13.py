"""Prompt assistant-p13: an over-long note is cut back once the repair is spent, process lines name what is looked for rather
than exact search words, and the recap's character states are lasting states rather than one moment of the last chapter."""
from __future__ import annotations

import unittest

from app.assistant import NOTE_MAX_CHARS, SYSTEM_PROMPT, clipped_note, validate_answer
from app.assistant_recap import INSTRUCTION
from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, ref_of_chapter, turn
from tests.test_assistant_limits import read

SOURCES = {"R1": {"ref": "R1", "kind": "passage", "chapter_number": 4, "text": "栖翎把反馈贴在门上。"}}
LONG_NOTE = "我只能提出改法，不能直接改正文。" + "可以把这一句改成别的说法，" * 20 + "最后一句。"


class ClippedNoteTests(unittest.TestCase):
    def test_cut_at_the_last_sentence_end_inside_the_limit(self):
        self.assertEqual(clipped_note(LONG_NOTE), "我只能提出改法，不能直接改正文。")

    def test_without_a_sentence_end_the_limit_is_kept(self):
        clipped = clipped_note("字" * 300)
        self.assertEqual(len(clipped), NOTE_MAX_CHARS)
        self.assertTrue(clipped.endswith("。"))


class ValidateNoteTests(unittest.TestCase):
    def answer(self, note, **flags):
        return validate_answer({"status": "answered", "sentences": [{"text": "栖翎把反馈贴在门上。", "refs": ["R1"]}], "note": note},
                               {"R1"}, SOURCES, "ask", **flags)

    def test_before_the_repair_a_long_note_is_returned_with_its_length(self):
        cleaned, problems = self.answer(LONG_NOTE)
        self.assertIsNone(cleaned)
        self.assertEqual(problems, [f"note 现在有 {len(LONG_NOTE)} 字，超过 200 字上限；删到 200 字以内，只留最要紧的一两句"])

    def test_after_the_repair_a_long_note_is_cut_back(self):
        cleaned, problems = self.answer(LONG_NOTE, clip_note=True)
        self.assertEqual(problems, [])
        self.assertEqual(cleaned["note"], "我只能提出改法，不能直接改正文。")

    def test_a_note_that_is_not_text_still_fails(self):
        cleaned, problems = self.answer(["不是文字"], clip_note=True)
        self.assertIsNone(cleaned)
        self.assertEqual(problems, ["note 必须是不超过 200 字的文字"])


class LongNoteRepairTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    @staticmethod
    def reply(note):
        def build(provider, messages):
            return turn(answer_call("answered", [("苏岑把罗盘交给了温岚保管。", [ref_of_chapter(messages, 9)])], note))
        return build

    def test_a_note_too_long_twice_is_cut_back_and_the_answer_delivered(self):
        task = self.run_ask(read(9), self.reply(LONG_NOTE), self.reply(LONG_NOTE))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(sum(step["kind"] == "repair" for step in task["steps"]), 1)
        self.assertEqual(task["answer"]["note"], "我只能提出改法，不能直接改正文。")


class PromptTextTests(unittest.TestCase):
    def test_the_note_for_an_edit_request_is_short(self):
        self.assertIn("note 一共不超过 200 字：「不能直接改」只写一句。", SYSTEM_PROMPT)  # p26: no rewrite suggestion to count

    def test_process_lines_do_not_list_search_words_or_later_steps(self):
        self.assertIn("说明里不要列具体的搜索词，只说要找哪方面的内容", SYSTEM_PROMPT)
        self.assertIn("说明只写这一轮的调用，不写之后才做的事", SYSTEM_PROMPT)
        self.assertIn("调用 check_passage 时，说明就写「检查改后的这句和前文有没有矛盾」", SYSTEM_PROMPT)
        self.assertNotIn("搜正文里的「冷瓷盆」", SYSTEM_PROMPT)

    def test_recap_states_are_lasting_states(self):
        self.assertIn("这一栏写会延续到下一章的状态", INSTRUCTION)
        self.assertIn("不写上一章里的一个动作、表情或一句话", INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
