"""Task 07o (prompt assistant-p12): the closing call is forced by the expected cost of the next call, refusals and rewrite advice
stay out of cited sentences, the fix prompt asks for a self-check, and the recap asks for the latest state and every open thread.
Everything runs on a scripted model; nothing is sent anywhere."""
from __future__ import annotations

import re
import unittest

from app.assistant import (ASSISTANT_FORCE_ANSWER_CNY, ASSISTANT_NEXT_ROUND_FACTOR, ASSISTANT_PROMPT_VERSION, FORCE_NOTICE, REFUSAL_PROBLEM,
                           SYSTEM_PROMPT, refusal_problems, should_force_answer, validate_answer)
from app.assistant_recap import ENDING, INSTRUCTION

from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, ref_of_chapter, turn
from tests.test_assistant import cite
from tests.test_assistant_limits import read
from tests.test_assistant_v180 import FINAL, Task04Case


class ShouldForceAnswerTests(unittest.TestCase):
    def test_the_first_call_has_nothing_to_go_by(self):
        self.assertFalse(should_force_answer(0.0, None, 0.25))
        self.assertTrue(should_force_answer(0.25, None, 0.25))  # as before: the money is already spent

    def test_money_already_at_the_line_forces_whatever_the_last_call_cost(self):
        self.assertTrue(should_force_answer(0.25, 0.0, 0.25))
        self.assertTrue(should_force_answer(0.26, 0.001, 0.25))

    def test_the_expected_next_call_pushing_past_the_line_forces(self):
        # ¥0.15 spent, the last call ¥0.06: two such calls more would reach ¥0.27.
        self.assertTrue(should_force_answer(0.15, 0.06, 0.25))
        self.assertFalse(should_force_answer(0.15, 0.04, 0.25))

    def test_landing_exactly_on_the_line_does_not_force(self):
        # Binary fractions, so the sums are exact: 0.125 + 2 × 0.0625 = 0.25.
        self.assertFalse(should_force_answer(0.125, 0.0625, 0.25, factor=2.0))
        self.assertTrue(should_force_answer(0.125, 0.0625 + 1 / 1024, 0.25, factor=2.0))
        self.assertTrue(should_force_answer(0.125 + 1 / 1024, 0.0625, 0.25, factor=2.0))

    def test_the_failing_formal_run_would_have_been_stopped_in_time(self):
        # a1cf-f1-qa-07 pass 2: six calls whose cost grew about ¥0.02 each time; the old line (¥0.25 spent) fired after the sixth.
        spent, last, calls_made = 0.0, None, 0
        for call_cost in (0.006, 0.025, 0.044, 0.064, 0.083, 0.102):
            if should_force_answer(spent, last, ASSISTANT_FORCE_ANSWER_CNY):
                break
            spent, last, calls_made = spent + call_cost, call_cost, calls_made + 1
        self.assertEqual(calls_made, 4)  # the fifth call is the closing one
        self.assertLessEqual(spent + 0.083, 0.30)  # and it still fits under the ceiling

    def test_the_factor_leaves_room_for_two_growing_calls(self):
        self.assertGreater(ASSISTANT_NEXT_ROUND_FACTOR, 1.3)


class ForcedByExpectedCostTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_the_closing_call_comes_before_the_money_is_gone(self):
        # Each call costs ¥0.0625 (exact in binary). After two calls ¥0.125 + 2 × ¥0.0625 lands exactly on ¥0.25 and goes on;
        # after the third, ¥0.1875 + ¥0.125 is past it, so the fourth call is the closing one although only ¥0.1875 is spent.
        task = self.run_ask(read(1, cost=0.0625), read(2, cost=0.0625), read(3, cost=0.0625), cite(1, words="先到这里。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([c["tool_choice"] for c in self.provider.calls], ["auto", "auto", "auto", "required"])
        self.assertEqual(self.provider.calls[3]["tools"], ["answer"])
        self.assertEqual(self.provider.calls[3]["messages"][-1]["content"], FORCE_NOTICE)
        self.assertEqual(task["coverage"]["not_checked"][-1], "步数或预算已到，没有查完")

    def test_the_first_call_is_never_forced_by_the_estimate(self):
        task = self.run_ask(read(1, cost=0.12), cite(1))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(self.provider.calls[0]["tool_choice"], "auto")
        self.assertEqual(len(self.provider.calls), 2)

    def test_cheap_calls_are_not_cut_short(self):
        task = self.run_ask(*[read(n, cost=0.01) for n in range(1, 6)], cite(1))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([c["tool_choice"] for c in self.provider.calls], ["auto"] * 6)

    def test_a_point_check_is_not_counted_as_a_search_call(self):
        # The review inside check_passage is paid for, but it is a one-off: it does not make the next call look dearer.
        task = self.run_ask(turn(call("check_passage", text="苏岑把罗盘交给了温岚。"), cost=0.01), read(9, cost=0.01), cite(9))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([c["tool_choice"] for c in self.provider.calls], ["auto", "auto", "auto"])


class RefusalSentenceTests(unittest.TestCase):
    def sentences(self, *texts):
        return [{"text": words, "refs": ["R1"]} for words in texts]

    def problems(self, *texts, source=""):
        return refusal_problems(self.sentences(*texts), {"R1": {"text": source, "kind": "passage", "chapter_number": 4}})

    def test_refusals_are_sent_back(self):
        for words in ("我无法把第四章的反馈改成已经公开发布。", "我不能直接修改正文。", "只能提出改法，不能直接改。",
                      "「我无法修改第四章。」", "  我无法把它改好。"):
            with self.subTest(words):
                self.assertEqual(len(self.problems(words)), 1)
                self.assertIn(REFUSAL_PROBLEM, self.problems(words)[0])

    def test_numbered_rewrite_advice_is_sent_back(self):
        for words in ("改法一：把「冷瓷盆」改为「铜盆」。", "改法二：删去这一句。", "改法三：补一句铺垫。", "改法1：换个说法。", "1. 改法一：换掉这句。"):
            with self.subTest(words):
                self.assertEqual(len(self.problems(words)), 1)

    def test_the_replace_form_is_sent_back(self):
        for words in ("把「两人并肩站在桥上」改为「一人先过桥」。", "把第四章的反馈改成已经公开发布。", "把……改成……"):
            with self.subTest(words):
                self.assertEqual(len(self.problems(words)), 1)

    def test_the_problem_names_the_sentence_and_the_rule(self):
        found = self.problems("栖翎在第四章留下反馈。", "我无法把它改成已发布。")
        self.assertEqual(found, ["第 2 句是拒绝或改写建议，拒绝和改写建议写进 note，不要挂出处"])

    def test_plain_sentences_about_the_work_are_left_alone(self):
        for words in ("第四章里栖翎留下了一条反馈。", "苏岑把罗盘交给了温岚。", "她把旧稿改成了新稿。", "温岚没有改变主意。",
                      "桥上同时只能站一个人。"):
            with self.subTest(words):
                self.assertEqual(self.problems(words, source="他们都没说话。"), [])

    def test_a_line_the_work_itself_says_is_not_mistaken_for_a_refusal(self):
        source = "栖翎低声说：「我不能再等了，」她转身离开，「我无法回到那座桥上去。」"
        self.assertEqual(self.problems("我不能再等了。", source=source), [])
        self.assertEqual(self.problems("「我不能再等了，」栖翎说。", source=source), [])
        self.assertEqual(self.problems("我无法回到那座桥上去，栖翎说。", source=source), [])

    def test_a_line_the_cited_source_does_not_hold_is_still_sent_back(self):
        self.assertEqual(len(self.problems("我无法把第四章的反馈改成已经公开发布。", source="栖翎低声说：「我不能再等了，」她转身离开。")), 1)

    def test_a_short_opening_found_in_the_source_proves_nothing(self):
        self.assertEqual(len(self.problems("我不能，所以只给改法。", source="我不能，她说。")), 1)

    def test_only_the_cited_sources_count(self):
        sources = {"R1": {"text": "无关的一段。"}, "R2": {"text": "「我不能再等了，」她说。"}}
        sentence = [{"text": "我不能再等了。", "refs": ["R1"]}]
        self.assertEqual(len(refusal_problems(sentence, sources)), 1)
        self.assertEqual(refusal_problems([{"text": "我不能再等了。", "refs": ["R2"]}], sources), [])


class ValidateAnswerRefusalTests(unittest.TestCase):
    SOURCES = {"R1": {"ref": "R1", "kind": "passage", "chapter_number": 4, "text": "栖翎把反馈贴在门上。"}}

    def answer(self, words, kind):
        return validate_answer({"status": "answered", "sentences": [{"text": words, "refs": ["R1"]}]}, {"R1"}, self.SOURCES, kind)

    def test_an_ask_answer_with_a_refusal_is_returned_with_the_reason(self):
        cleaned, problems = self.answer("我无法把第四章的反馈改成已经公开发布。", "ask")
        self.assertIsNone(cleaned)
        self.assertEqual(problems, ["第 1 句是拒绝或改写建议，拒绝和改写建议写进 note，不要挂出处"])

    def test_the_refusal_belongs_in_the_note(self):
        cleaned, problems = validate_answer(
            {"status": "answered", "sentences": [{"text": "栖翎把反馈贴在门上。", "refs": ["R1"]}], "note": "我只能提出改法，不能直接改正文。"},
            {"R1"}, self.SOURCES, "ask")
        self.assertEqual(problems, [])
        self.assertEqual(cleaned["note"], "我只能提出改法，不能直接改正文。")

    def test_a_fix_answer_is_not_held_to_the_rule(self):
        for words in ("改法一：把「贴在门上」改为「放在桌上」。", "我无法确定这是不是有意的。"):
            cleaned, problems = self.answer(words, "fix_issue")
            self.assertEqual(problems, [])
            self.assertIsNotNone(cleaned)

    def test_out_of_scope_is_untouched(self):
        cleaned, problems = validate_answer({"status": "out_of_scope", "sentences": [{"text": "我无法回答。", "refs": []}]}, set(), {}, "ask")
        self.assertEqual((cleaned["status"], problems), ("out_of_scope", []))


class RefusalRepairTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    @staticmethod
    def reply(first_words, second_words=None, note=None):
        def build(provider, messages):
            refs = [ref_of_chapter(messages, 9)]
            return turn(answer_call("answered", [(first_words, refs)] + ([(second_words, refs)] if second_words else []), note))
        return build

    def test_a_refusal_sentence_is_returned_once_and_the_corrected_answer_is_delivered(self):
        task = self.run_ask(read(9), self.reply("我无法把第九章改成已经公开发布。"), self.reply("苏岑把罗盘交给了温岚保管。", note="我只能提出改法，不能直接改正文。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(sum(step["kind"] == "repair" for step in task["steps"]), 1)
        sent_back = self.provider.calls[2]["messages"][-1]
        self.assertEqual(sent_back["role"], "tool")
        self.assertIn("拒绝和改写建议写进 note，不要挂出处", sent_back["content"])
        self.assertEqual([s["text"] for s in task["answer"]["sentences"]], ["苏岑把罗盘交给了温岚保管。"])
        self.assertEqual(task["answer"]["note"], "我只能提出改法，不能直接改正文。")

    def test_rewrite_advice_is_returned_too(self):
        task = self.run_ask(read(9), self.reply("苏岑把罗盘交给了温岚保管。", "改法一：把「交给」改为「还给」。"), self.reply("苏岑把罗盘交给了温岚保管。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertIn("第 2 句是拒绝或改写建议", self.all_messages())
        self.assertEqual(len(task["answer"]["sentences"]), 1)

    def test_after_the_repair_a_cited_refusal_is_dropped_and_the_rest_delivered(self):
        task = self.run_ask(read(9), self.reply("我无法修改正文。"), self.reply("我不能修改正文。", "苏岑把罗盘交给了温岚保管。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([s["text"] for s in task["answer"]["sentences"]], ["苏岑把罗盘交给了温岚保管。"])

    def test_a_second_refusal_after_the_repair_fails_the_task_and_gives_the_characters_back(self):
        task = self.run_ask(read(9), self.reply("我无法修改正文。"), self.reply("我不能修改正文。"))
        self.assertEqual((task["status"], task["error_code"]), ("failed", "citation_validation_failed"))
        self.assertEqual(task["usage"]["chars_charged"], 0)


class FixTaskIsNotHeldToTheRule(Task04Case):
    def test_a_fix_answer_may_list_its_proposals_as_sentences(self):
        def listing(provider, messages):
            ref = re.search(r'"ref": "(R\d+)"', messages[1]["content"]).group(1)
            return turn(answer_call("answered", [("改法一：把这一句改为只写温岚拿着罗盘。", [ref])]))
        task = self.fix(self.proposals_turn(), listing)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(sum(step["kind"] == "repair" for step in task["steps"]), 0)
        self.assertTrue(task["answer"]["sentences"][0]["text"].startswith("改法一"))


class PromptTextTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(ASSISTANT_PROMPT_VERSION, "assistant-p50")

    def test_a_search_that_finds_nothing_ends_in_not_found(self):
        self.assertIn("用两三种不同说法搜过、仍然没有，就用 not_found 收尾，不要一直搜下去", SYSTEM_PROMPT)

    def test_a_request_to_edit_the_text_is_answered_with_the_note(self):
        self.assertIn("作者在问题里要求直接改正文时", SYSTEM_PROMPT)
        self.assertIn("带出处的句子只回答问题里能从作品查到的部分", SYSTEM_PROMPT)
        self.assertIn("「不能直接改」写进 note", SYSTEM_PROMPT)
        self.assertIn("note 里不写改写建议，也不要写成带出处的句子", SYSTEM_PROMPT)  # p26: the suggestion is no longer written into the note

    def test_an_edit_is_checked_against_its_ground_and_then_by_check_passage(self):
        self.assertIn("提出 edit_this 前，先对照检查结果里给出的依据（规则或前文）核对一遍，改后的句子不能再违反它", SYSTEM_PROMPT)
        self.assertIn("准备写进 edit_this 的改后文字，如果步数和预算还够，先用 check_passage 检查", SYSTEM_PROMPT)
        self.assertIn("没有矛盾再用 propose_edit 提出", SYSTEM_PROMPT)
        self.assertIn("如果还有矛盾，换一种改法", SYSTEM_PROMPT)

    def test_the_recap_lists_every_open_thread_and_the_latest_change_of_state(self):
        self.assertIn("伏笔记录里截止时还没回收的条目，都要列进「还没收的线」，最多 4 条；超过 4 条时挑和下一章计划最相关的", INSTRUCTION)
        self.assertIn("优先写到截止章为止发生过变化的状态：受伤或康复、身份或职务的变化、拿到或交出物件、学会或失去某种能力", INSTRUCTION)
        self.assertIn("写的必须是截止章为止最晚的那一条", INSTRUCTION)
        # The limits and the ending are as they were.
        self.assertIn("最多调用 6 次工具", ENDING)


if __name__ == "__main__":
    unittest.main()
