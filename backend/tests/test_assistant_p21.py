"""Prompt assistant-p21, after the dev check of the fixed chapter check (2026-10-18): a sentence that cites only facts may
not name a person those facts do not mention (a1csf-safe-06 failed twice on "柏临序向米若珈说明……" citing one fact about
米若珈's record keeping); it is returned for repair, and dropped once the repair is spent."""
from __future__ import annotations

import unittest

from app.assistant import ASSISTANT_PROMPT_VERSION, SYSTEM_PROMPT, unsupported_people, unsupported_people_problems, validate_answer

FACT = {"ref": "R13", "kind": "fact", "chapter_number": 12, "text": "米若珈的记录工作：继续记录仍需征得来者同意，已有材料不能因为延续就自动扩大用途。"}
PASSAGE = {"ref": "R3", "kind": "passage", "chapter_number": 12,
           "text": "他把确定的范围告诉贺隽宁，再向米若珈说明继续记录仍需征得来者同意，已有材料不能因为延续就自动扩大用途。柏临序没有让大家轮流表达感想。"}
SOURCES = {"R13": FACT, "R3": PASSAGE}
PEOPLE = frozenset({"米若珈", "柏临序", "贺隽宁"})
SENTENCE = "第十二章里，柏临序向米若珈说明已有材料不能因为延续就自动扩大用途。"


class UnsupportedPeopleTests(unittest.TestCase):
    def test_a_fact_only_sentence_naming_someone_else_is_returned(self):
        self.assertEqual(unsupported_people({"text": SENTENCE, "refs": ["R13"]}, SOURCES, PEOPLE), ["柏临序"])
        cleaned, problems = validate_answer({"status": "answered", "sentences": [{"text": SENTENCE, "refs": ["R13"]}]}, {"R13", "R3"}, SOURCES, people=PEOPLE)
        self.assertIsNone(cleaned)
        self.assertEqual(problems, ["第 1 句只引了事实，事实里却没有柏临序；写某人对谁说了什么、做了什么，要引正文段落，或者不写这一句"])

    def test_citing_the_passage_too_is_fine(self):
        self.assertEqual(unsupported_people({"text": SENTENCE, "refs": ["R13", "R3"]}, SOURCES, PEOPLE), [])
        cleaned, problems = validate_answer({"status": "answered", "sentences": [{"text": SENTENCE, "refs": ["R13", "R3"]}]}, {"R13", "R3"}, SOURCES, people=PEOPLE)
        self.assertEqual(problems, [])

    def test_a_fact_only_sentence_naming_only_its_own_people_is_fine(self):
        sentence = {"text": "第十二章里，米若珈的记录仍需征得来者同意。", "refs": ["R13"]}
        self.assertEqual(unsupported_people_problems([sentence], SOURCES, PEOPLE), [])

    def test_without_known_people_nothing_changes(self):
        self.assertEqual(unsupported_people({"text": SENTENCE, "refs": ["R13"]}, SOURCES, frozenset()), [])

    def test_after_the_repair_the_check_is_left_to_the_drop(self):
        # validate_answer with check_refusals=False (the repair is spent) does not fail on it; the engine drops the sentence.
        cleaned, problems = validate_answer({"status": "answered", "sentences": [{"text": SENTENCE, "refs": ["R13"]}]}, {"R13"}, SOURCES,
                                            check_refusals=False, clip_note=True, people=PEOPLE)
        self.assertEqual(problems, [])
        self.assertEqual(len(cleaned["sentences"]), 1)

    def test_once_the_repair_is_spent_the_sentence_is_dropped(self):
        from app.assistant import without_unsupported_people
        good = {"text": "第四章里，米若珈的记录仍需征得来者同意。", "refs": ["R13"]}
        bad = {"text": SENTENCE, "refs": ["R13"]}
        kept, problems = without_unsupported_people({"status": "answered", "sentences": [good, bad], "note": None}, SOURCES, PEOPLE)
        self.assertEqual((kept["sentences"], problems), ([good], []))
        # Nothing left to stand on: the answer fails with the reason.
        kept, problems = without_unsupported_people({"status": "answered", "sentences": [bad], "note": None}, SOURCES, PEOPLE)
        self.assertIsNone(kept)
        self.assertEqual(len(problems), 1)
        # A not_found keeps its note.
        kept, problems = without_unsupported_people({"status": "not_found", "sentences": [bad], "note": "没找到。"}, SOURCES, PEOPLE)
        self.assertEqual((kept["sentences"], problems), ([], []))

    def test_the_prompt_says_so_and_the_version_moves(self):
        self.assertIn("只引了事实、没引正文段落的句子，只写那条事实里出现的人", SYSTEM_PROMPT)
        self.assertEqual(ASSISTANT_PROMPT_VERSION, "assistant-p51")


if __name__ == "__main__":
    unittest.main()
