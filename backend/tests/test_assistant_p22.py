"""Prompt assistant-p22, after the third A1c formal run (2026-10-19). The recap missed lasting states because imported works
have no character records (the people of the confirmed facts now stand in) and a chapter-1 state fell behind newer facts
(lasting facts now come first); open threads must say what is open; the ending must come from the last two passages. A
jailbreak's rule restated as "作者这次给出的新规则是……" carried the text's refs (a1cs3f-safe-07); such restatements now go
back for repair like refusals, and are dropped once the repair is spent."""
from __future__ import annotations

import json
import unittest
import uuid

from app.assistant import ASSISTANT_PROMPT_VERSION, SYSTEM_PROMPT, refusal_problems, refusal_sentences, validate_answer
from app.assistant_recap import INSTRUCTION, ending_refs, validate

from tests.scripted_chat import call, turn
from tests.test_assistant_v180 import Task04Case, recap_answer

CH6 = {"kind": "passage", "chapter_number": 6, "start": 1200, "end": 1500, "text": "摘下迟声戒只会停止新纸鱼的产生，已经出现的纸鱼不会因此消失。"}
FACT = {"kind": "fact", "chapter_number": 6, "start": None, "end": None, "text": "迟声戒：摘下迟声戒只会停止新纸鱼的产生，已经出现的纸鱼不会因此消失。"}
SOURCES = {"R1": CH6, "R11": FACT}


class RestatedQuestionTests(unittest.TestCase):
    RESTATED = {"text": "作者这次给出的新规则是戒指一摘、已经出现的纸鱼也全部消失，与第六章正文和事实的写法相反。", "refs": ["R1", "R11"]}
    TEXT = {"text": "第六章正文写的是：摘下迟声戒只会停止新纸鱼的产生，已经出现的纸鱼不会因此消失。", "refs": ["R1"]}

    def test_a_cited_restatement_of_the_question_is_returned(self):
        self.assertEqual(refusal_sentences([self.TEXT, self.RESTATED], SOURCES), [1])
        cleaned, problems = validate_answer({"status": "answered", "sentences": [self.TEXT, self.RESTATED]}, {"R1", "R11"}, SOURCES)
        self.assertIsNone(cleaned)
        self.assertEqual(problems, ["第 2 句复述的是作者或问题里的说法，作品里没有这句；作者的说法写进 note，带出处的句子只写原文怎么写"])

    def test_other_openings(self):
        for text in ("你说的规则和第六章不同。", "问题里说戒指一摘纸鱼全消失。", "按你给出的新规则，纸鱼会全部消失。"):
            self.assertEqual(refusal_sentences([{"text": text, "refs": ["R1"]}], SOURCES), [0], text)
        for text in ("颛苇初摘下戒指后纸鱼仍在。", "作者在第六章写了这枚戒指。", "你在第六章写的是纸鱼不会消失。"):
            self.assertEqual(refusal_sentences([{"text": text, "refs": ["R1"]}], SOURCES), [], text)

    def test_a_quoted_opening_is_left_alone(self):
        source = {**CH6, "text": "你说的那条规矩，我记得清清楚楚，颛苇初答道。"}
        sentence = {"text": "你说的那条规矩，我记得清清楚楚，颛苇初这样回答。", "refs": ["R1"]}
        self.assertEqual(refusal_sentences([sentence], {"R1": source}), [])

    def test_the_prompt_says_so_and_the_version_moves(self):
        self.assertIn("不要写「作者这次给出的新规则是……」「你说的……」这类带出处的句子", SYSTEM_PROMPT)
        self.assertEqual(ASSISTANT_PROMPT_VERSION, "assistant-p58")
        self.assertEqual(len(refusal_problems([self.RESTATED], SOURCES)), 1)


def passage(chapter, start, end):
    return {"kind": "passage", "chapter_number": chapter, "start": start, "end": end, "text": "……"}


def recap(ending_ref):
    return {"previous_ending": [{"summary": "上一章的结尾。", "refs": [ending_ref]}], "character_state": [], "open_threads": [], "plan": []}


class RecapEndingTests(unittest.TestCase):
    SOURCES = {"R1": passage(14, 2600, 2900), "R2": passage(14, 2900, 3200), "R7": passage(14, 900, 1300), "R9": passage(13, 3000, 3300)}

    def test_the_ending_is_the_last_two_passages(self):
        self.assertEqual(ending_refs(self.SOURCES, 15), {"R1", "R2"})
        for ref in ("R1", "R2"):
            cleaned, problems = validate(recap(ref), set(self.SOURCES), self.SOURCES, 15, INTERNAL)
            self.assertEqual(problems, [], ref)

    def test_an_earlier_passage_goes_back_for_repair(self):
        cleaned, problems = validate(recap("R7"), set(self.SOURCES), self.SOURCES, 15, INTERNAL)
        self.assertIsNone(cleaned)
        self.assertEqual(problems, ["previous_ending 要写上一章最后的事，引用上一章最后两段之一（候选 previous_ending 里的段落）"])

    def test_once_the_repair_is_spent_it_is_accepted(self):
        cleaned, problems = validate(recap("R7"), set(self.SOURCES), self.SOURCES, 15, INTERNAL, strict_ending=False)
        self.assertEqual(problems, [])

    def test_one_ending_only_and_the_first_is_kept_once_the_repair_is_spent(self):
        # p25: "最后那两段" drew two ending items and the recap failed twice on the count.
        two = {**recap("R1"), "previous_ending": [{"summary": "上一章的结尾。", "refs": ["R1"]}, {"summary": "最后一句。", "refs": ["R2"]}]}
        cleaned, problems = validate(two, set(self.SOURCES), self.SOURCES, 15, INTERNAL)
        self.assertEqual(problems, ["previous_ending 只能写 1 条，现在是 2 条"])
        cleaned, problems = validate(two, set(self.SOURCES), self.SOURCES, 15, INTERNAL, strict_ending=False)
        self.assertEqual(problems, [])
        self.assertEqual(cleaned["sections"]["previous_ending"], [{"summary": "上一章的结尾。", "refs": ["R1"]}])
        cleaned, problems = validate({**recap("R1"), "previous_ending": []}, set(self.SOURCES), self.SOURCES, 15, INTERNAL, strict_ending=False)
        self.assertIsNone(cleaned)

    def test_the_candidates_are_enough_for_the_people_they_give(self):
        from app.assistant_recap import ENDING
        self.assertIn("不要再为他们调用 lookup_facts", ENDING)

    def test_the_instruction_asks_for_what_is_open_and_lasting_states(self):
        self.assertIn("「还没收的线」每条同时挂这条线的伏笔记录（record）和埋下它的正文段落（source）", INSTRUCTION)
        self.assertIn("截止时仍然成立的身份或处境", INSTRUCTION)
        self.assertIn("「上一章停在哪」只写一条，写上一章最后那两段里的事", INSTRUCTION)


class _Internal:
    @staticmethod
    def search(text):
        return None


INTERNAL = _Internal()


class RecapPeopleTests(Task04Case):
    def setUp(self):
        super().setUp()
        self.save("温岚在门边停下。温岚回头。")

    def candidates(self):
        self.provider.script(turn(call("lookup_facts", name="温岚")), recap_answer)
        task = self.task(self.post_task("recap").json()["data"]["id"])
        self.assertEqual(task["status"], "completed", task)
        message = self.provider.calls[0]["messages"][1]["content"]
        return json.JSONDecoder().raw_decode(message[message.index('{"content_kind"'):])[0]["candidates"]

    def test_without_character_records_the_people_of_the_facts_stand_in(self):
        with self.db.connection() as c:
            c.execute("DELETE FROM v2_character_aliases WHERE project_id=?", (self.project_id,))
            c.execute("DELETE FROM v2_characters WHERE project_id=?", (self.project_id,))
        states = self.candidates()["character_state"]
        self.assertEqual(states[0]["name"], "温岚")
        self.assertTrue(states[0]["facts"])

    def test_a_lasting_state_from_chapter_one_is_kept_beside_newer_facts(self):
        with self.db.connection() as c:
            current = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (self.project_id,)).fetchone()[0]
            base = dict(c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=? AND subject='温岚' LIMIT 1",
                                  (self.project_id, current)).fetchone())
            spans = {row[1]: row[0] for row in c.execute("SELECT s.id,ch.chapter_number FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id WHERE s.project_id=?",
                                                          (self.project_id,))}
            rows = [dict(base, id="m-" + uuid.uuid4().hex[:12], memory_type="dynamic_state", predicate="status", value="仍是见习记录员，没有正式编号", source_span_id=spans[1])]
            rows += [dict(base, id="m-" + uuid.uuid4().hex[:12], memory_type="event_timeline", predicate="event_occurred", value=f"第{n}章抄完一页潮位表", source_span_id=spans[n])
                     for n in (5, 6, 7, 8)]
            for row in rows:
                c.execute(f"INSERT INTO v2_memory_records({','.join(row)}) VALUES({','.join('?' for _ in row)})", tuple(row.values()))
        state = next(s for s in self.candidates()["character_state"] if s["name"] == "温岚")
        texts = [f["text"] for f in state["facts"]]
        self.assertIn("温岚：仍是见习记录员，没有正式编号", texts)
        self.assertLessEqual(len(texts), 6)

    def test_an_open_thread_carries_its_record(self):
        # p24: the planting passage does not say the thread is still open; the record does.
        span = self.rows("SELECT s.id,ch.id chapter_id FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id WHERE s.project_id=? AND ch.chapter_number=9", self.project_id)[0]
        r = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=self.idem(),
                             json={"base_foreshadow_version": 0, "title": "罗盘下落", "description": "罗盘为何没有归还", "status": "planted",
                                   "planted_chapter_id": span["chapter_id"], "planted_source_span_id": span["id"]})
        self.assertEqual(r.status_code, 201, r.text)
        thread = self.candidates()["open_threads"][0]
        self.assertEqual(thread["record"]["chapter"], 9)
        self.assertTrue(thread["record"]["text"].startswith("伏笔：罗盘下落——罗盘为何没有归还（截至第"))
        self.assertEqual(thread["source"]["chapter"], 9)
        sources = self.rows("SELECT kind FROM assistant_sources WHERE ref=?", thread["record"]["ref"])
        self.assertIn("foreshadow", {row["kind"] for row in sources})


if __name__ == "__main__":
    unittest.main()
