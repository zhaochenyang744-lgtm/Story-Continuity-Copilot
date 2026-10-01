from __future__ import annotations

import unittest

from app.brief_citations import render_sources
from app.internal_ids import strip_internal_ids
from app.memory_contract import CONTROLLED_PREDICATES, predicate_label


class StripInternalIdsTest(unittest.TestCase):
    def test_bracketed_ids_are_removed_with_their_brackets(self):
        text = (
            "已确认的记忆（mem-7f545ece-6bc4-4ace-b0aa-e5642b516010）表明温岚不知道。"
            "依据是第4章原文（span-227b2727-022a-4ba6-9e0d-8113840bc4a5）。"
            "草稿称黎舟已告知（draft-claim-draft-e5b61529-e84c-4aad-9503-4aec0c9857b8-r1-4），这并未说明温岚是否知情。"
        )
        self.assertEqual(
            strip_internal_ids(text),
            "已确认的记忆表明温岚不知道。依据是第4章原文。草稿称黎舟已告知，这并未说明温岚是否知情。",
        )

    def test_id_lists_truncated_ids_and_seed_ids(self):
        self.assertEqual(strip_internal_ids("两条证据（mem-7f545ece，span-227b2727）冲突。"), "两条证据冲突。")
        self.assertEqual(strip_internal_ids("教学里（grey-harbor-claim-3）提到罗盘。"), "教学里提到罗盘。")
        self.assertEqual(strip_internal_ids("（编号：mem-7f545ece-6bc4-4ace-b0aa-e5642b516010）记录有效。"), "记录有效。")

    def test_ordinary_text_is_unchanged(self):
        for text in ("第 10 章 21:05 收到三次求救码。", "版本 v2-final 未变。", "Story Memory 里没有 rule 记录。"):
            self.assertEqual(strip_internal_ids(text), text)


class PredicateLabelTest(unittest.TestCase):
    def test_every_controlled_predicate_has_author_wording(self):
        for predicate in CONTROLLED_PREDICATES:
            self.assertNotEqual(predicate_label(predicate), "其他属性", predicate)

    def test_brief_renders_memory_records_without_raw_keys(self):
        maps = {"memory_record": {"mem-1": {"subject": "灰港雾钟", "predicate": "rule", "value": "只在北潮闸完全关闭后敲响一次"}}}
        text = render_sources([{"source_type": "memory_record", "source_id": "mem-1"}], maps)
        self.assertIn("已确认记忆记录（灰港雾钟 · 规则）", text)
        self.assertNotIn("rule", text)


if __name__ == "__main__":
    unittest.main()
