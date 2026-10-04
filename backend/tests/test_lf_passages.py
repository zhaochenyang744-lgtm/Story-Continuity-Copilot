"""Passage splitting and retrieval for long chapters (long-text phase 3).

A ~2,500-character chapter is split into 400-600-character passages at sentence ends, and checks
retrieve passages, never text from the checked chapter or later.
"""
from __future__ import annotations

import unittest

from app.passages import (
    PASSAGE_MAX,
    PASSAGE_MIN,
    TAIL_SLACK,
    FactKey,
    PassageIndex,
    split_passages,
    terms,
)


def chapter_body(seed: str, sentences: int = 60) -> str:
    return "".join(f"{seed}第{i}次走过长街，看见路边的灯一盏盏亮起来。" for i in range(sentences))


def passages_of(chapters: dict[int, str]):
    return [p for number, body in chapters.items()
            for p in split_passages(body, span_id=f"span-{number}", chapter_id=f"chapter-{number}", chapter_number=number)]


class SplitTests(unittest.TestCase):
    def test_passages_end_at_sentence_ends_within_bounds_and_keep_offsets(self):
        body = chapter_body("林默")
        passages = split_passages(body, span_id="s", chapter_id="c", chapter_number=3)
        self.assertGreater(len(passages), 2)
        for passage in passages:
            self.assertEqual(body[passage.start:passage.end], passage.text)
            self.assertTrue(passage.text.endswith("。"))
            self.assertLessEqual(len(passage.text), PASSAGE_MAX + TAIL_SLACK)
            self.assertEqual(passage.chapter_number, 3)
        for passage in passages[:-1]:
            self.assertGreaterEqual(len(passage.text), PASSAGE_MIN)
        self.assertEqual([p.ordinal for p in passages], list(range(1, len(passages) + 1)))
        self.assertEqual(len({p.id for p in passages}), len(passages))
        self.assertEqual("".join(p.text for p in passages), body)

    def test_a_sentence_longer_than_the_maximum_is_cut(self):
        body = "雾" * (PASSAGE_MAX * 2 + 50) + "。"
        passages = split_passages(body, span_id="s", chapter_id="c", chapter_number=1)
        self.assertTrue(all(len(p.text) <= PASSAGE_MAX + TAIL_SLACK for p in passages))
        self.assertEqual("".join(p.text for p in passages), body)

    def test_a_short_chapter_is_one_passage(self):
        passages = split_passages("林默在雾港。\n他等船。", span_id="s", chapter_id="c", chapter_number=1)
        self.assertEqual([p.text for p in passages], ["林默在雾港。\n他等船。"])

    def test_attribute_classes_add_a_shared_term(self):
        self.assertIn("§眼", terms("赤色的眼眸古井无波"))
        self.assertIn("§眼", terms("紫发碧眼的萝莉"))
        self.assertIn("§国", terms("我的祖国法兰西"))


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.chapters = {
            1: chapter_body("路人") + "北堤门只在清晨开启，任何人不得夜里通行。" + chapter_body("路人", 10),
            2: chapter_body("行人") + "银钥匙由林默保管。" + chapter_body("行人", 10),
            3: chapter_body("旅人") + "北堤门在夜里开启了，银钥匙不见了。",
        }
        self.passages = passages_of(self.chapters)

    def test_finds_the_passage_that_holds_the_evidence(self):
        index = PassageIndex(self.passages, ["林默", "北堤门"])
        hits = index.search("夜里北堤门开着，没人拦。", before_chapter=3, k=3)
        self.assertIn("北堤门只在清晨开启", hits[0][1].text)

    def test_never_returns_the_checked_chapter_or_later(self):
        index = PassageIndex(self.passages, ["北堤门"])
        for before in (1, 2, 3):
            hits = index.search("北堤门在夜里开启了，银钥匙不见了。", before_chapter=before, k=20)
            self.assertTrue(all(p.chapter_number < before for _, p in hits))
        self.assertEqual(index.search("北堤门", before_chapter=1), [])

    def test_at_most_per_chapter_passages_from_one_chapter(self):
        index = PassageIndex(self.passages)
        hits = index.search("走过长街，看见路边的灯", before_chapter=3, k=20, per_chapter=2)
        counts = {}
        for _, passage in hits:
            counts[passage.chapter_number] = counts.get(passage.chapter_number, 0) + 1
        self.assertTrue(counts and max(counts.values()) <= 2)

    def test_fact_route_finds_evidence_that_shares_no_words_with_the_query_beyond_the_entity(self):
        market = [f"小曦今天第{i}次去集市，买了些菜回家。" for i in range(40)]
        chapters = {
            1: "".join(market[:20] + ["那是个红发如瀑的小女孩，笑起来很甜。"] + market[20:]),
            2: "".join(f"小曦第{i}次和哥哥说起学校的事，哥哥只是点头。" for i in range(40)),
        }
        passages = passages_of(chapters)
        # The query shares far more words with chapter 2 than with the hair in chapter 1.
        query = "小曦和哥哥说起学校的事，哥哥看着她一头乌黑的短发。"
        plain = PassageIndex(passages, ["小曦"]).search(query, before_chapter=3, k=1)
        routed = PassageIndex(passages, ["小曦"], [FactKey("小曦 外貌 红发、乌黑以外的发色，八岁", 1)]).search(query, before_chapter=3, k=1)
        self.assertNotIn("红发如瀑", plain[0][1].text)
        self.assertIn("红发如瀑", routed[0][1].text)

    def test_fact_route_respects_the_chapter_limit(self):
        index = PassageIndex(self.passages, facts=[FactKey("北堤门 开放 夜里开启了", 3)])
        hits = index.search("北堤门夜里开启", before_chapter=3, k=20)
        self.assertTrue(all(p.chapter_number < 3 for _, p in hits))

    def test_english_text_is_retrieved_by_its_words(self):
        chapters = {
            1: "A named person may open the Clove Bridge archive only when that person wears the roster pin. " * 3,
            2: "The dusk ledger lists Iven Sorr, and no other person, as the current wearer of the roster pin. " * 3,
            3: "Palo Neris polishes the bridge rail with chalk paste. " * 3,
        }
        index = PassageIndex(passages_of(chapters), ["Palo Neris", "Iven Sorr"])
        hits = index.search("Palo Neris alone may open the Clove Bridge archive.", before_chapter=4, k=3)
        self.assertIn(1, [p.chapter_number for _, p in hits])
        self.assertIn("w:archive", terms("The ARCHIVE opens."))
        # Full stops end English sentences, so passages still break at sentence ends.
        passages = split_passages("One more step. " * 100, span_id="s", chapter_id="c", chapter_number=1)
        self.assertTrue(all(p.text.endswith(".") and len(p.text) <= PASSAGE_MAX + TAIL_SLACK for p in passages))

    def test_results_have_no_duplicates(self):
        index = PassageIndex(self.passages, ["北堤门"], [FactKey("北堤门 规则 只在清晨开启", 1)])
        hits = index.search("北堤门只在清晨开启", before_chapter=3, k=20)
        ids = [p.id for _, p in hits]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
