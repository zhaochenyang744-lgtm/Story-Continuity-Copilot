"""v2.2: a draft sentence that takes one of two versions an earlier text gives is looked at with the other version in view."""
from __future__ import annotations

import unittest

from app import review_screening as screening
from app.passages import PassageIndex, split_passages


def index_of(chapters: dict[int, str], names: list[str]) -> PassageIndex:
    passages = []
    for number, body in chapters.items():
        passages.extend(split_passages(body, span_id=f"span-{number}", chapter_id=f"chapter-{number}", chapter_number=number))
    return PassageIndex(passages, names, [])


class ValueTests(unittest.TestCase):
    def test_a_number_and_what_it_counts(self):
        self.assertEqual(screening.values("商霁葵当年三十一岁，入夜后的第四声钟"), {("岁", 31), ("声", 4)})
        self.assertEqual(screening.values("那块木牌固定有六条边"), {("边", 6)})
        self.assertEqual(screening.values("木牌一共五边"), {("边", 5)})

    def test_another_number_of_the_same_kind_for_the_same_name_is_a_split(self):
        index = index_of({1: "这是商霁葵二十七岁的这一年，她仍是祭司。", 6: "商霁葵在这一年三十一岁，并未跨过新年。"}, ["商霁葵"])
        claim = "商霁葵当年三十一岁，这一年她的生辰尚未到来。"
        both = [screening.passage_entry(p) for p in index.passages]
        self.assertTrue(screening.value_split(claim, both, index))
        agreeing = [screening.passage_entry(p) for p in index.passages if p.chapter_number == 6]
        self.assertFalse(screening.value_split(claim, agreeing, index))
        other = index_of({1: "温岚二十七岁那年第一次出海。"}, ["商霁葵", "温岚"])
        self.assertFalse(screening.value_split(claim, [screening.passage_entry(p) for p in other.passages], other))  # someone else's age


class SamePointTests(unittest.TestCase):
    def test_the_other_chapters_version_of_the_point_comes_first_one_per_chapter(self):
        filler = "院子里有风，晒过的草叶有气味。" * 20
        index = index_of({4: filler + "裴栖蘅是骨雨匣最初的制作者，这只匣没有另请旁人代工。",
                          5: filler + "虞澈蓁说若有人因失望离开，她也不拦。",
                          9: filler + "虞澈蓁是骨雨匣最初的制作者，这只匣没有另请旁人代工。"}, ["骨雨匣", "虞澈蓁", "裴栖蘅"])
        picked = index.same_point("那只最早的骨雨匣出自虞澈蓁一人之手，没有另请旁人制作。", before_chapter=11)
        self.assertEqual({p.chapter_number for p in picked}, {4, 9})
        self.assertEqual(index.same_point("天黑了。", before_chapter=11), [])


if __name__ == "__main__":
    unittest.main()
