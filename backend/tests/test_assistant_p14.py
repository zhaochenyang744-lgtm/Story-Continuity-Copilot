"""Prompt assistant-p14: a process line that names more than the round's calls is not shown; cited sentences name people
and add nothing; a recap item is one thing. The lines below are from the p12/p13 checks on the spent A1c pair."""
from __future__ import annotations

import json
import unittest

from app.assistant import SYSTEM_PROMPT, say_matches_calls
from app.assistant_recap import INSTRUCTION
from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, ref_of_chapter, turn


def calls(*made):
    return [{"name": name, "arguments": json.dumps(args, ensure_ascii=False)} for name, args in made]


SEARCH_ALL = {"chapter_from": 1, "chapter_to": 30}


class SayMatchesCallsTests(unittest.TestCase):
    def test_a_chapter_to_read_must_be_read(self):
        made = calls(("read_chapter", {"chapter_number": 25}), ("search_text", {"query": "长杆", **SEARCH_ALL}), ("lookup_facts", {"name": "长杆"}))
        self.assertFalse(say_matches_calls("我再读第25章和第26章相关段落，并查探沙长杆的事实。", made))
        self.assertTrue(say_matches_calls("我再读第25章相关段落，并查探沙长杆的事实。", made))

    def test_a_chapter_to_check_is_reached_by_a_search_over_it(self):
        made = calls(("read_chapter", {"chapter_number": 7}), ("search_text", {"query": "左手", "chapter_from": 22, "chapter_to": 28}))
        self.assertTrue(say_matches_calls("我再核对第7章正文里惯用手那句的原文，以及第23、28章用左手的写法。", made))
        self.assertFalse(say_matches_calls("第7章和第21章对平面数目的说法不同，我再核对这两处原文。", calls(("read_chapter", {"chapter_number": 7}))))

    def test_chinese_numerals_and_lists(self):
        made = calls(("lookup_facts", {"name": "雁尾栈道"}), ("get_plans", {"chapter_number": 31}))
        self.assertFalse(say_matches_calls("我先核对第20章封闭决定的期限说法，以及第29、30章里栈道封闭的现状。", made))
        self.assertTrue(say_matches_calls("我再查一下第三章的写法。", calls(("search_text", {"query": "方孔", "chapter_from": 1, "chapter_to": 5}))))
        self.assertFalse(say_matches_calls("我再查一下第三章的写法。", calls(("search_text", {"query": "方孔", "chapter_from": 1, "chapter_to": 12}))))

    def test_a_chapter_plan_or_draft_is_not_a_chapter_to_read(self):
        self.assertTrue(say_matches_calls("我先查第十三章的计划。", calls(("get_plans", {"chapter_number": 13}))))
        self.assertTrue(say_matches_calls("我再搜几个说法，并读一下第30章草稿。", calls(("search_text", {"query": "何泽珩", **SEARCH_ALL}), ("read_draft", {}))))
        self.assertTrue(say_matches_calls("我再查第19章之后罗针有没有换人保管。", calls(("search_text", {"query": "罗针", "chapter_from": 20, "chapter_to": 30}))))

    def test_named_material_needs_its_call(self):
        searches = calls(("search_text", {"query": "宿营", **SEARCH_ALL}), ("search_text", {"query": "扎营", **SEARCH_ALL}))
        self.assertFalse(say_matches_calls("我先在正文里搜宿营、扎营相关的段落，并查相关人物的事实。", searches))
        self.assertTrue(say_matches_calls("我先在正文里搜宿营、扎营相关的段落。", searches))
        self.assertTrue(say_matches_calls("我再查计划和伏笔记录里关于罗针的条目。", calls(("get_plans", {}))))
        self.assertFalse(say_matches_calls("我先检查改后的句子和前文有没有矛盾，再提出两种方向不同的改法。", calls(("check_passage", {"text": "雾格板开有九处方孔。"}))))
        self.assertTrue(say_matches_calls("我先检查改后的这句和前文有没有矛盾。", calls(("check_passage", {"text": "雾格板开有九处方孔。"}))))
        self.assertTrue(say_matches_calls("改后这句的检查没能执行，我直接提出两种改法。", calls(("propose_edit", {}), ("propose_edit", {}))))

    def test_a_quoted_word_must_be_searched(self):
        made = calls(("search_text", {"query": "预约说明", "chapter_from": 1, "chapter_to": 12}), ("search_text", {"query": "试用", "chapter_from": 1, "chapter_to": 12}))
        self.assertFalse(say_matches_calls("我再查一下正文里「预约说明」和「来访」的相关内容。", made))
        self.assertTrue(say_matches_calls("我再查一下正文里「预约说明」和「试用」的相关内容。", made))
        self.assertTrue(say_matches_calls("我搜「登记次序」。", calls(("search_text", {"query": "登记 次序"}))))

    def test_a_line_naming_nothing_checkable_is_kept(self):
        self.assertTrue(say_matches_calls("I'll search the text for the feedback.", calls(("search_text", {"query": "反馈"}))))


class UnmatchedLineIsNotShownTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_the_line_is_dropped_and_the_task_goes_on(self):
        def search(provider, messages):
            return turn(call("read_chapter", chapter_number=9), content="我先读第9章，并查苏岑的事实。")

        def close(provider, messages):
            return turn(answer_call("answered", [("苏岑把罗盘交给了温岚保管。", [ref_of_chapter(messages, 9)])]))
        task = self.run_ask(search, close)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([s for s in task["steps"] if s["kind"] == "say"], [])
        self.assertEqual([s["tool"] for s in task["steps"] if s["kind"] == "tool"], ["read_chapter"])

    def test_a_matching_line_is_shown(self):
        def search(provider, messages):
            return turn(call("read_chapter", chapter_number=9), content="我先读第9章。")

        def close(provider, messages):
            return turn(answer_call("answered", [("苏岑把罗盘交给了温岚保管。", [ref_of_chapter(messages, 9)])]))
        task = self.run_ask(search, close)
        self.assertEqual([s["summary"] for s in task["steps"] if s["kind"] == "say"], ["我先读第9章。"])


class PromptTextTests(unittest.TestCase):
    def test_sentences_add_nothing_and_name_people(self):
        self.assertIn("不补出处里没写的动作、原因或先后关系", SYSTEM_PROMPT)
        self.assertIn("不同出处里的事不要拼成一句", SYSTEM_PROMPT)
        self.assertIn("句子里说到人物时写出名字，不用「他」「她」开头", SYSTEM_PROMPT)

    def test_a_recap_item_is_one_thing(self):
        self.assertIn("每条只写一件事，挂的出处要直接写着这件事；不要把不同出处里的两件事拼成一条", INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
