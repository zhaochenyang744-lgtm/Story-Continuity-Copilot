from __future__ import annotations

import unittest

from backend.app.v2_database import V2Database


class ImportStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        # _parse_import is deliberately pure; bypass filesystem-backed construction.
        self.database = V2Database.__new__(V2Database)

    def parse(self, text: str):
        return self.database._parse_import(text)

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
