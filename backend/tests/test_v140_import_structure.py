from __future__ import annotations

import unittest

from app.v2_database import V2Database
from app.database import DomainError


class ImportStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        # _parse_import is deliberately pure; bypass filesystem-backed construction.
        self.database = V2Database.__new__(V2Database)

    def parse(self, text: str):
        return self.database._parse_import(text)

    def assert_audited(self, text, audit):
        for key in ("coverage_complete", "order_preserved", "no_duplicate_source_assignment"):
            self.assertTrue(audit[key], key)
        self.assertEqual(
            audit["retained_body_characters"] + audit["structural_heading_characters"] + audit["excluded_directory_characters"],
            len(text),
        )

    def test_volume_headings_merge_into_next_chapter_only(self):
        text = "第一卷 风起\n第一章 雨夜\n雨水落在门边。\n第二章 来客\n访客收起伞。\n第二卷 潮落\n第三章 归舟\n木船靠上码头。\n"
        chapters, _, warnings, audit = self.parse(text)
        self.assertEqual([c["title"] for c in chapters], ["第一卷 风起 · 雨夜", "来客", "第二卷 潮落 · 归舟"])
        self.assertEqual([c["body"] for c in chapters], ["雨水落在门边。\n", "访客收起伞。\n", "木船靠上码头。\n"])
        self.assertEqual(warnings.count("grouping_heading_merged"), 1)
        self.assert_audited(text, audit)

    def test_chapter_heading_groups_sections(self):
        text = "第一章 雨夜\n第一节\n看守员关好窗。\n第二节\n雨声渐渐停了。\n"
        chapters, _, warnings, audit = self.parse(text)
        self.assertEqual([c["title"] for c in chapters], ["第一章 雨夜 · 第一节", "第二节"])
        self.assertIn("grouping_heading_merged", warnings)
        self.assert_audited(text, audit)

    def test_markdown_volume_heading_merges_without_hashes(self):
        text = "# 第一卷 风起\n# 第一章 雨夜\n看守员关好窗。\n"
        chapters, strategy, warnings, audit = self.parse(text)
        self.assertEqual(strategy, "markdown_heading")
        self.assertEqual([c["title"] for c in chapters], ["第一卷 风起 · 第一章 雨夜"])
        self.assertIn("grouping_heading_merged", warnings)
        self.assert_audited(text, audit)

    def test_consecutive_grouping_headings_keep_order_and_title_limit(self):
        for title in ("雨夜", "雨" * 125):
            with self.subTest(title=title):
                text = f"# 第一部\n## 第一卷 风起\n### {title}\n看守员关好窗。\n"
                chapters, _, warnings, audit = self.parse(text)
                self.assertEqual([c["title"] for c in chapters], [f"第一部 · 第一卷 风起 · {title}"[:120]])
                self.assertEqual(warnings.count("grouping_heading_merged"), 1)
                self.assert_audited(text, audit)

    def test_grouping_blank_lines_are_structural_and_prefix_is_preserved(self):
        prefix = "\ufeff\r\n"
        group = "第一卷 风起\r\n \t\r\n\r\n"
        heading = "第一章 雨夜\r\n"
        body = "看守员关好窗。\r\n"
        text = prefix + group + heading + body
        chapters, _, warnings, audit = self.parse(text)
        self.assertEqual([c["title"] for c in chapters], ["第一卷 风起 · 雨夜"])
        self.assertEqual(chapters[0]["body"], prefix + body)
        self.assertEqual(audit["structural_heading_characters"], len(group + heading))
        self.assertIn("grouping_heading_merged", warnings)
        self.assert_audited(text, audit)

    def test_trailing_empty_heading_and_whitespace_stay_in_last_body(self):
        for trailing in ("第十一章（待续）", "# 第十一章（待续）\n \t\n"):
            with self.subTest(trailing=trailing):
                heading = "# " if trailing.startswith("#") else ""
                text = f"{heading}第一章 雨夜\n看守员关好窗。\n{heading}第二章 来客\n访客收起伞。\n{trailing}"
                chapters, _, warnings, audit = self.parse(text)
                self.assertEqual(len(chapters), 2)
                self.assertEqual(chapters[-1]["body"], "访客收起伞。\n" + trailing)
                self.assertEqual(warnings, ["trailing_heading_kept_in_body"])
                self.assert_audited(text, audit)

    def test_grouping_and_trailing_heading_can_coexist(self):
        text = "第一卷 风起\n第一章 雨夜\n看守员关好窗。\n第二章（待续）\n"
        chapters, _, warnings, audit = self.parse(text)
        self.assertEqual([c["title"] for c in chapters], ["第一卷 风起 · 雨夜"])
        self.assertEqual(chapters[0]["body"], "看守员关好窗。\n第二章（待续）\n")
        self.assertEqual(warnings, ["grouping_heading_merged", "trailing_heading_kept_in_body"])
        self.assert_audited(text, audit)

    def test_single_empty_heading_keeps_previous_behavior(self):
        with self.assertRaises(DomainError) as caught:
            self.parse("第一章 雨夜\n \n")
        self.assertEqual((caught.exception.code, caught.exception.status), ("chapter_detection_failed", 422))
        text = "开篇正文。\n第一章 雨夜\n \n"
        chapters, _, warnings, audit = self.parse(text)
        self.assertEqual(chapters[0]["body"], "开篇正文。\n \n")
        self.assertEqual(warnings, [])
        self.assert_audited(text, audit)

    def test_directory_exclusions_do_not_become_grouping_or_trailing_headings(self):
        for text in (
            "第一章 目录\n1(chapter1.html)\n第二章 雨夜\n看守员关好窗。\n",
            "第一章 雨夜\n看守员关好窗。\n第二章 目录\n1(chapter1.html)\n",
        ):
            with self.subTest(text=text), self.assertRaises(DomainError) as caught:
                self.parse(text)
            self.assertEqual((caught.exception.code, caught.exception.status), ("chapter_detection_failed", 422))

    def test_directory_residue_is_excluded_without_losing_opening_chapter(self) -> None:
        text = (
            "白夜\n1\n" + "车站笼在雾里。" * 12 + "\n2\n" + "钟声穿过广场。" * 12 + "\n"
            "第二章 目录\n1(chapter108.html)\n2(chapter18.html)\n返回总目录(chapter122.html)\n\n"
            "1\n" + "雨声落在窗沿。" * 12 + "\n2\n" + "脚步停在门外。" * 12 + "\n"
            "第三章 目录\n1(chapter31.html)\n返回目录(chapter122.html)\n"
            "1\n" + "天色渐渐亮起。" * 12 + "\n"
        )

        chapters, strategy, warnings, audit = self.parse(text)

        self.assertEqual(strategy, "chapter_heading")
        self.assertEqual([chapter["title"] for chapter in chapters], ["第1章（由后续章界推定）", "第二章", "第三章"])
        self.assertFalse(any(".html" in chapter["body"] for chapter in chapters))
        self.assertTrue(chapters[0]["body"].startswith("白夜\n1\n"))
        self.assertIn("\n1\n", chapters[1]["body"])
        self.assertEqual(sum(chapter["excluded_index_line_count"] for chapter in chapters), 5)
        self.assertEqual(warnings, ["directory_index_removed", "numeric_headings_preserved_as_subsections", "leading_chapter_inferred"])
        self.assertTrue(audit["coverage_complete"])
        self.assertTrue(audit["order_preserved"])
        self.assertTrue(audit["no_duplicate_source_assignment"])
        self.assertEqual(
            audit["retained_body_characters"] + audit["structural_heading_characters"] + audit["excluded_directory_characters"],
            len(text),
        )
        excerpt = self.database._import_excerpt(chapters[1]["body"])
        self.assertTrue(excerpt.startswith("雨声落在窗沿。"))
        self.assertNotIn("\n1\n", excerpt)
        self.assertLessEqual(len(excerpt.splitlines()), 3)

    def test_repeated_numeric_sections_without_chapter_markers_are_preserved(self) -> None:
        text = "1\n" + "甲" * 30 + "\n2\n" + "乙" * 30 + "\n1\n" + "丙" * 30

        chapters, strategy, warnings, audit = self.parse(text)

        self.assertEqual(strategy, "single_chapter_fallback")
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]["body"], text)
        self.assertIn("ambiguous_numeric_headings_preserved_as_single_chapter", warnings)
        self.assertEqual(audit["numeric_interpretation"], "ambiguous_preserved")
        self.assertTrue(audit["coverage_complete"])

    def test_clean_monotonic_numeric_headings_can_define_chapters(self) -> None:
        text = "前置空白保留\n1\n" + "甲" * 30 + "\n2\n" + "乙" * 30 + "\n3\n" + "丙" * 30

        chapters, strategy, warnings, audit = self.parse(text)

        self.assertEqual(strategy, "numeric_heading")
        self.assertEqual(len(chapters), 3)
        self.assertTrue(chapters[0]["body"].startswith("前置空白保留\n"))
        self.assertEqual(warnings, [])
        self.assertEqual(audit["numeric_interpretation"], "chapters")
        self.assertTrue(audit["coverage_complete"])

    def test_markdown_prefix_whitespace_is_accounted_for(self) -> None:
        text = "\n# 第一章\n" + "正文" * 12 + "\n# 第二章\n" + "续文" * 12

        chapters, strategy, _, audit = self.parse(text)

        self.assertEqual(strategy, "markdown_heading")
        self.assertEqual(len(chapters), 2)
        self.assertTrue(chapters[0]["body"].startswith("\n"))
        self.assertTrue(audit["coverage_complete"])


if __name__ == "__main__":
    unittest.main()
