"""Prompt assistant-p53 (v2.1 unified interface plan, 2026-10-26): an answer may open with a lead sentence that sums up the
ones after it, and each sentence may carry a label, words of the sentence itself, so the page can list parallel sentences
with the label in bold. The model writes no formatting; the label and lead are checked like the rest of the answer."""
from __future__ import annotations

import unittest

from app.assistant import ANSWER_MAX_SENTENCES, ASSISTANT_PROMPT_VERSION, LABEL_MAX_CHARS, SYSTEM_PROMPT, validate_answer
from app.assistant_tools import ANSWER_SCHEMA

PASSAGES = {f"R{n}": {"ref": f"R{n}", "kind": "passage", "chapter_number": n, "text": f"第{n}章的一段原文。"} for n in range(1, 8)}
KNOWN = set(PASSAGES)
THREADS = ["移交单上的窄纸", "白色渡船的署名", "廊桥钥匙", "旧尺零点", "第十章的钟声"]


def listed(*, lead=True, labels=True):
    sentences = [{"text": f"{name}在第{n}章埋下，后面还没有收。", "refs": [f"R{n}"], **({"label": name} if labels else {})}
                 for n, name in enumerate(THREADS, 1)]
    if lead:
        sentences.insert(0, {"text": "现在还有五条伏笔没收。", "refs": ["R6"], "lead": True})
    return {"status": "answered", "sentences": sentences}


class AnswerFormatTests(unittest.TestCase):
    def test_a_lead_and_labels_are_kept_and_the_lead_is_not_counted(self):
        cleaned, problems = validate_answer(listed(), KNOWN, PASSAGES)
        self.assertEqual(problems, [])
        self.assertEqual(len(cleaned["sentences"]), ANSWER_MAX_SENTENCES + 1)
        self.assertTrue(cleaned["sentences"][0]["lead"])
        self.assertEqual([s.get("label") for s in cleaned["sentences"][1:]], THREADS)
        self.assertNotIn("label", cleaned["sentences"][0])

    def test_without_them_an_answer_is_as_before(self):
        cleaned, problems = validate_answer(listed(lead=False, labels=False), KNOWN, PASSAGES)
        self.assertEqual(problems, [])
        self.assertEqual(cleaned["sentences"][0], {"text": "移交单上的窄纸在第1章埋下，后面还没有收。", "refs": ["R1"]})

    def test_six_sentences_without_a_lead_are_still_too_many(self):
        answer = listed(lead=False)
        answer["sentences"].append({"text": "另有一条线在第6章。", "refs": ["R6"]})
        _, problems = validate_answer(answer, KNOWN, PASSAGES)
        self.assertTrue(any(problem.startswith(f"最多 {ANSWER_MAX_SENTENCES} 句") for problem in problems))

    def test_a_label_must_be_words_of_its_sentence_and_short(self):
        answer = listed(lead=False)
        answer["sentences"][1]["label"] = "渡船"  # words of "白色渡船的署名……": fine
        answer["sentences"][2]["label"] = "黑色渡船"
        answer["sentences"][3]["label"] = "旧" * (LABEL_MAX_CHARS + 1)
        cleaned, problems = validate_answer(answer, KNOWN, PASSAGES)
        self.assertIsNone(cleaned)
        self.assertEqual(len(problems), 2)
        self.assertIn("第 3 句的 label「黑色渡船」要原样出现在这句里", problems[0])

    def test_a_lead_on_a_later_sentence_is_refused(self):
        answer = listed(lead=False)
        answer["sentences"][1]["lead"] = True
        _, problems = validate_answer(answer, KNOWN, PASSAGES)
        self.assertEqual(problems, ["第 2 句标了 lead；只有第一句能是总述"])

    def test_once_the_repair_is_spent_a_bad_label_or_lead_is_dropped_not_fatal(self):
        answer = listed(lead=False)
        answer["sentences"][1]["label"] = "黑色渡船"
        answer["sentences"][2]["lead"] = True
        cleaned, problems = validate_answer(answer, KNOWN, PASSAGES, check_refusals=False, clip_note=True)
        self.assertEqual(problems, [])
        self.assertNotIn("label", cleaned["sentences"][1])
        self.assertNotIn("lead", cleaned["sentences"][2])

    def test_the_lead_still_needs_its_source(self):
        answer = listed()
        answer["sentences"][0]["refs"] = []
        _, problems = validate_answer(answer, KNOWN, PASSAGES)
        self.assertIn("第 1 句没有出处，每句都至少要带一个编号", problems)

    def test_the_tool_and_the_prompt_say_so(self):
        item = ANSWER_SCHEMA["properties"]["sentences"]["items"]["properties"]
        self.assertEqual((item["label"]["maxLength"], item["lead"]["type"]), (LABEL_MAX_CHARS, "boolean"))
        self.assertIn("lead 填 true", SYSTEM_PROMPT)
        self.assertIn("label", SYSTEM_PROMPT)
        self.assertEqual(ASSISTANT_PROMPT_VERSION, "assistant-p58")


if __name__ == "__main__":
    unittest.main()
