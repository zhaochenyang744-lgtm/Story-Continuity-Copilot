"""Prompt assistant-p16, after the p15 check on the second A1c pair: a note keeps where the assistant looked and drops its
sentences about what the text says; a process line reporting a finding is not shown; a not_found answer cites at most two
sentences saying the thing is still unknown."""
from __future__ import annotations

import unittest

from app.assistant import SYSTEM_PROMPT
from app.assistant_coverage import looked_places
from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, ref_of_chapter, turn


class WithoutStoryTests(unittest.TestCase):
    """p16 cut the story out of a note with a blacklist; since p26 `looked_places` keeps only the places (the same cases)."""

    def test_sentences_about_the_text_go(self):
        self.assertEqual(looked_places("查过第8、26章正文和计划；草稿无检查结果。第26章事实与正文都写二十七岁，第8章正文写二十三岁，需作者定夺。"),
                         "查过第8、26章正文和计划。")  # p26: "草稿无检查结果" and "需作者定夺" are not places either
        self.assertEqual(looked_places("查过第20、21章正文。正文没有写短接触片能否开动推进装置，只写了它不负责启动推进器。"), "查过第20、21章正文。")
        self.assertEqual(looked_places("查过第1—30章正文。没有找到问题问到的内容。另：第十章写「三个隔层」，第二十八章写「五个隔层」，两处不一致。"),
                         "查过第1—30章正文。没有找到问题问到的内容。")

    def test_places_and_not_found_stay(self):
        self.assertEqual(looked_places("查过第7、14章正文，匿名音频的事实与伏笔记录（第7章埋设，未标回收）；没有找到问题问到的内容。"),
                         "查过第7、14章正文，匿名音频的事实与伏笔记录。没有找到问题问到的内容。")  # the bracket says what the record holds
        self.assertIsNone(looked_places(None))


class NoteIsCleanedInTheTaskTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_the_delivered_note_keeps_only_the_places(self):
        def close(provider, messages):
            return turn(answer_call("not_found", [], "查过第9章正文。第9章写「罗盘交给温岚」，没有写为什么。"))
        task = self.run_ask(turn(call("read_chapter", chapter_number=9)), close)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["answer"]["note"], "查过第9章正文。")


class PromptTextTests(unittest.TestCase):
    def test_not_found_cites_at_most_two_sentences(self):
        self.assertIn("写着「还不知道」的句子可以作为带出处的句子，最多两句", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()


class P17Tests(unittest.TestCase):
    """assistant-p17: '说法相反' and the like are story content in a note or a line; a refusal or a suggestion stays."""

    def test_a_reported_conflict_goes(self):
        self.assertEqual(looked_places("查过第8、26章正文和事实记录；两处出生地说法相反。"), "查过第8、26章正文和事实记录。")

    def test_a_refusal_stays_but_a_suggestion_goes(self):
        # p26: the rewrite suggestion is no longer written into the note.
        note = "我只能提出改法，不能直接覆盖保存正文。若只改第9章，其余几章仍写银灰外套，会前后不一致；建议一并改为深紫色。"
        self.assertEqual(looked_places(note), "我只能提出改法，不能直接覆盖保存正文。")
        self.assertEqual(looked_places("我不能直接改正文，第四章写「只存离线电脑」，改成已公开会冲突；改写建议：先取得本人确认。"), "我不能直接改正文。")


class P20Tests(unittest.TestCase):
    """assistant-p20 cut clauses; the whitelist of p26 gives the same or a shorter note for the same notes."""

    def test_absence_and_record_clauses_go_but_places_stay(self):
        self.assertEqual(looked_places("查过第21章正文、卓闻岚的事实，均未写她留着信封的原因。没有找到问题问到的内容。"),
                         "查过第21章正文、卓闻岚的事实。没有找到问题问到的内容。")
        self.assertEqual(looked_places("查过第14、28章正文；计划与伏笔记录里没有关于这个水量的条目。"), "查过第14、28章正文。")
        self.assertEqual(looked_places("查过第七章正文；第七章正文里夹有一句要求删章的话，我没有照做。"), "查过第七章正文。")  # only the fixed instruction line stays

    def test_refusal_stays_and_the_rest_goes(self):
        note = "不能直接改正文，我只能提出改法。第八章写的是她当面撤约，改成打电话会冲突；若要改，可让她回接待廊说明。"
        self.assertEqual(looked_places(note), "不能直接改正文，我只能提出改法。")
        self.assertEqual(looked_places("我只能提出改法。若只改第九章，第十章仍写「银灰外套」；建议一并改为深紫。"), "我只能提出改法。")
