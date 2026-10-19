"""Offline validator regression tests using marked synthetic tokens, not fiction."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CHECK = Path(__file__).resolve().parents[1] / "check.py"
spec = importlib.util.spec_from_file_location("a1c_check", CHECK)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
QUOTE = "甲乙丙丁戊己庚辛壬癸子丑"
TITLE = "第一章 测试"


class CheckerTests(unittest.TestCase):
    def setUp(self):
        c.DEV = True
        c.ERRORS.clear()
        c.POSITIONS.clear()
        c.COPY_ERRORS = 0
        c.WORKS = {"test": {"names": ["测试专名"], "shared_draft": {"body": "测试专名，拿着试验用的空白标签。"}}}
        c.SOURCES = {"test": {"chapters": {TITLE: "甲" * 1500 + QUOTE}, "numbers": {TITLE: 1}}}

    def qa(self):
        return {"id":"a1cd-test", "work":"test", "suite":"qa", "qa_type":"answerable_single", "question":"测试输入？", "paraphrased":False, "answer_points":["测试金标"], "forbidden_claims":[], "evidence_chapters":[TITLE], "evidence_quotes":[QUOTE], "deep":True}

    def test_first_han_ignores_prefix_punctuation(self):
        c.SOURCES["test"]["chapters"][TITLE] = "甲" * 1500 + "！ABC" + QUOTE
        self.assertEqual(c.quote_position("test", TITLE, "！ABC" + QUOTE, "test"), 1501)
        self.assertEqual(c.ERRORS, [])

    def test_1500_boundary_is_not_deep(self):
        c.SOURCES["test"]["chapters"][TITLE] = "甲" * 1499 + QUOTE
        task = self.qa()
        task["deep"] = False
        c.validate_qa(task)
        self.assertEqual(c.ERRORS, [])

    def test_1501_boundary_is_deep(self):
        c.validate_qa(self.qa())
        self.assertEqual(c.ERRORS, [])

    def test_forged_deep_rejected(self):
        task = self.qa()
        task["deep"] = False
        c.validate_qa(task)
        self.assertIn("a1cd-test:deep_position", c.ERRORS)

    def test_integer_deep_rejected(self):
        task = self.qa()
        task["deep"] = 1
        c.validate_qa(task)
        self.assertIn("a1cd-test:deep_type", c.ERRORS)

    def test_duplicate_exact_quote_rejected(self):
        c.SOURCES["test"]["chapters"][TITLE] = QUOTE + QUOTE
        self.assertEqual(c.quote_position("test", TITLE, QUOTE, "test"), 0)
        self.assertIn("test:quote_unique_source", c.ERRORS)

    def test_overlapping_quote_rejected(self):
        c.SOURCES["test"]["chapters"][TITLE] = "乙" * 13
        c.quote_position("test", TITLE, "乙" * 12, "test")
        self.assertIn("test:quote_unique_source", c.ERRORS)

    def test_absent_quote_rejected(self):
        c.quote_position("test", TITLE, "寅卯辰巳午未申酉戌亥", "test")
        self.assertIn("test:quote_unique_source", c.ERRORS)

    def test_short_quote_rejected(self):
        c.quote_position("test", TITLE, "乙丙丁戊", "test")
        self.assertIn("test:quote_length", c.ERRORS)

    def test_quote_position_deduplicates(self):
        for _ in range(2):
            c.quote_position("test", TITLE, QUOTE, "test", record=True)
        self.assertEqual(len(c.POSITIONS), 1)

    def test_wrong_recorded_position_rejected(self):
        c.review_quote_list([{"chapter":TITLE, "text":QUOTE, "han_position":1500}], "test", "test")
        self.assertIn("test:recorded_position", c.ERRORS)

    def test_quote_alignment_rejected(self):
        task = self.qa()
        task["evidence_quotes"] = []
        c.validate_qa(task)
        self.assertIn("a1cd-test:quote_alignment", c.ERRORS)

    def test_unknown_reference_rejected(self):
        c.refs(["第二章 测试"], "test", "test")
        self.assertIn("test:evidence_unknown", c.ERRORS)

    def test_eight_han_copy(self):
        self.assertTrue(c.grams("甲乙丙丁，戊己庚辛", []) & c.grams("甲乙丙丁戊己庚辛", []))
        self.assertFalse(c.grams("甲乙丙丁戊己庚", []))

    def test_name_exemption_breaks_gram(self):
        self.assertFalse(c.grams("甲乙丙丁测试专名戊己庚辛", ["测试专名"]))

    def test_selected_name_alone_rejected(self):
        task = self.qa()
        task.update(selection="测试专名", question="他拿什么？")
        c.validate_qa(task)
        self.assertIn("a1cd-test:selection_sentence", c.ERRORS)

    def test_selection_repeated_name_rejected(self):
        task = self.qa()
        task.update(selection="测试专名，拿着试验用的空白标签。", question="他测试专名拿什么？")
        c.validate_qa(task)
        self.assertIn("a1cd-test:selection_names", c.ERRORS)

    def test_name_with_period_is_not_selection_sentence(self):
        task = self.qa()
        task.update(selection="测试专名。", question="他拿什么？")
        c.WORKS["test"]["shared_draft"]["body"] = "测试专名。"
        c.validate_qa(task)
        self.assertIn("a1cd-test:selection_only_name", c.ERRORS)

    def test_follow_named_referent_rejected(self):
        task = self.qa()
        task.update(suite="follow_up", question="他测试专名拿什么？", first_question="测试专名在哪？", first_answer_points=["测试答案"])
        c.validate_qa(task, True)
        self.assertIn("a1cd-test:follow_names", c.ERRORS)

    def test_fix_hedge_rejected(self):
        task = {"id":"a1cd-test", "work":"test", "draft":"测试专名以为标签为空。", "conflict_sentence":"测试专名以为标签为空。", "category":"attribute", "fix_idea":"测试改法", "evidence_chapters":[TITLE]}
        c.validate_fix(task)
        self.assertIn("a1cd-test:conflict_narration", c.ERRORS)

    def test_fix_quoted_substring_rejected(self):
        task = {"id":"a1cd-test", "work":"test", "draft":"他说：“测试专名标签为空。”", "conflict_sentence":"测试专名标签为空。", "category":"attribute", "fix_idea":"测试改法", "evidence_chapters":[TITLE]}
        c.validate_fix(task)
        self.assertIn("a1cd-test:conflict_quote_context", c.ERRORS)

    def test_bom_and_cr_rejected(self):
        with tempfile.TemporaryDirectory(dir=CHECK.parent / "authoring") as temporary:
            path = Path(temporary) / "test.txt"
            path.write_bytes(b"\xef\xbb\xbfabc\r\n")
            c.read_utf8(path)
            self.assertEqual(c.ERRORS, ["encoding:bom", "encoding:cr"])

    def test_manifest_hash_and_coverage(self):
        with tempfile.TemporaryDirectory(dir=CHECK.parent / "authoring") as temporary, patch.object(c, "ROOT", Path(temporary)):
            (c.ROOT / "works").mkdir()
            (c.ROOT / "tasks.json").write_bytes(b"{}\n")
            (c.ROOT / "works/test.md").write_bytes(b"fixture\n")
            paths = ["tasks.json", "works/test.md"]
            lines = [hashlib.sha256((c.ROOT/p).read_bytes()).hexdigest() + "  " + p for p in paths]
            (c.ROOT / "set.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            c.manifest_checks()
            self.assertEqual(c.ERRORS, [])
            (c.ROOT / "tasks.json").write_bytes(b"[]\n")
            c.manifest_checks()
            self.assertIn("manifest:hash:1", c.ERRORS)
            c.ERRORS.clear()
            (c.ROOT / "set.sha256").write_text(lines[0] + "\n", encoding="utf-8", newline="\n")
            c.manifest_checks()
            self.assertIn("manifest:coverage_and_order", c.ERRORS)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory(dir=CHECK.parent / "authoring") as temporary, patch.object(c, "ROOT", Path(temporary)):
            with self.assertRaises(ValueError):
                c.local_path("../outside.json")

    def test_staged_dev_rejects_other_path_without_open(self):
        with tempfile.TemporaryDirectory(dir=CHECK.parent / "authoring") as temporary, patch.object(c, "ROOT", Path(temporary)), patch.object(sys, "argv", ["check.py", "--staged-dev"]), patch.object(c, "read_utf8", side_effect=AssertionError("must not read")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(c.main(), 1)

    def test_chinese_chapter_numbers(self):
        for title, expected in [("第三十章 测试", 30), ("第五十一章 测试", 51), ("第31章 测试", 31)]:
            self.assertEqual(c.chapter_number(title), expected)
        self.assertFalse(c.integer(True))

    def formal_tasks(self, first_deep=6, second_deep=6):
        """Only task-type tokens; no story, question or gold-answer content."""
        c.DEV = False
        c.WORKS = {"test_a":{}, "test_b":{}}
        tasks = []
        for wk, deep_limit in zip(c.WORKS, [first_deep, second_deep]):
            own = []
            for qt, count in [("answerable_single", 2), ("answerable_multi", 3), ("not_in_text", 2), ("conflicting", 2)]:
                own.extend({"work":wk, "suite":"qa", "qa_type":qt, "paraphrased":True, "selection":"fixture", "deep":False} for _ in range(count))
            own.extend({"work":wk, "suite":"recap", "upto_chapter":k} for k in [15, 30])
            own.extend({"work":wk, "suite":"fix", "category":category} for category in (["attribute", "world_rule"] if wk == "test_a" else ["object_state", "timeline"]))
            own.extend({"work":wk, "suite":"follow_up", "deep":False} for _ in range(2))
            eligible = [t for t in own if t["suite"] == "follow_up" or t.get("qa_type", "").startswith("answerable")]
            for task in eligible[:deep_limit]:
                task["deep"] = True
            tasks.extend(own)
        return tasks

    def test_formal_two_balanced_works(self):
        counts = c.task_distribution_checks(self.formal_tasks())
        self.assertEqual(counts, {"test_a":6, "test_b":6})
        self.assertEqual(c.ERRORS, [])

    def test_formal_five_and_seven_deep_allowed(self):
        c.task_distribution_checks(self.formal_tasks(5, 7))
        self.assertEqual(c.ERRORS, [])

    def test_formal_total_deep_below_twelve(self):
        c.task_distribution_checks(self.formal_tasks(5, 6))
        self.assertIn("deep_answerable_count", c.ERRORS)
        self.assertNotIn("test_a:deep_answerable_count", c.ERRORS)
        self.assertNotIn("test_b:deep_answerable_count", c.ERRORS)

    def test_formal_work_deep_below_five(self):
        c.task_distribution_checks(self.formal_tasks(4, 7))
        self.assertIn("test_a:deep_answerable_count", c.ERRORS)

    def test_formal_conflicting_deep_does_not_count(self):
        tasks = self.formal_tasks(5, 6)
        for task in tasks:
            if task.get("qa_type") == "conflicting":
                task["deep"] = True
        c.task_distribution_checks(tasks)
        self.assertIn("deep_answerable_count", c.ERRORS)

    def test_formal_per_work_qa_cannot_offset(self):
        tasks = self.formal_tasks()
        tasks[0]["qa_type"] = "answerable_multi"
        next(t for t in tasks if t["work"] == "test_b" and t.get("qa_type") == "answerable_multi")["qa_type"] = "answerable_single"
        c.task_distribution_checks(tasks)
        self.assertNotIn("qa_distribution", c.ERRORS)
        self.assertIn("test_a:qa_distribution", c.ERRORS)
        self.assertIn("test_b:qa_distribution", c.ERRORS)

    def test_formal_per_work_suite_cannot_offset(self):
        tasks = self.formal_tasks()
        tasks[0]["work"] = "test_b"
        c.task_distribution_checks(tasks)
        self.assertNotIn("task_distribution", c.ERRORS)
        self.assertIn("test_a:task_distribution", c.ERRORS)
        self.assertIn("test_b:task_distribution", c.ERRORS)

    def test_formal_each_work_needs_both_recaps(self):
        tasks = self.formal_tasks()
        for task in tasks:
            if task["suite"] == "recap":
                task["upto_chapter"] = 15 if task["work"] == "test_a" else 30
        c.task_distribution_checks(tasks)
        self.assertIn("test_a:recap_distribution", c.ERRORS)
        self.assertIn("test_b:recap_distribution", c.ERRORS)

    def test_formal_fix_requires_three_categories(self):
        tasks = self.formal_tasks()
        for task in tasks:
            if task["suite"] == "fix":
                task["category"] = "attribute"
        c.task_distribution_checks(tasks)
        self.assertIn("fix_categories", c.ERRORS)

    def test_formal_names_must_be_disjoint(self):
        c.DEV = False
        c.work_distribution_checks([{"source_file":"works/test-a.md", "names":["测试重名"]}, {"source_file":"works/test-b.md", "names":["测试重名"]}])
        self.assertIn("work_names_disjoint", c.ERRORS)

    def test_formal_requires_two_works(self):
        c.DEV = False
        c.work_distribution_checks([{"source_file":"works/test.md", "names":["测试名称"]}])
        self.assertIn("work_count", c.ERRORS)

    def test_position_ratios_cannot_offset_between_works(self):
        c.WORKS = {"test_a":{}, "test_b":{}}
        c.POSITIONS = {("test_a", TITLE, str(i)):100 for i in range(6)}
        c.POSITIONS.update({("test_b", TITLE, str(i)):2600 for i in range(12)})
        counts = c.position_distribution_checks()
        self.assertEqual(counts["test_b"]["evidence_after_2500"], 12)
        self.assertIn("test_a:quote_distribution_1500", c.ERRORS)
        self.assertIn("test_a:quote_distribution_2500", c.ERRORS)
        self.assertNotIn("test_b:quote_distribution_1500", c.ERRORS)

    def test_position_ratios_exact_boundaries(self):
        c.POSITIONS = {("test", TITLE, str(i)):p for i, p in enumerate([1500, 1500, 1500, 1501, 2501, 2501])}
        c.position_distribution_checks()
        self.assertEqual(c.ERRORS, [])

    def parse_synthetic_work(self, chapters=30, length=2500):
        # A Han counter fixture only: repeated one-character tokens, no fiction.
        source = "\n\n".join(f"# 第{i}章 测试\n\n测试名称" + "甲" * (length-4) for i in range(1, chapters+1))
        work = {"key":"test", "title":"计数测试", "language":"zh", "purpose":"general", "source_file":"works/test.md", "names":["测试名称"], "plans":[{"chapter":16, "text":"测试计划"}, {"chapter":31, "text":"测试计划"}], "foreshadows":[{"title":str(i), "planted_chapter":1, "status":"open"} for i in range(3)] + [{"title":"3", "planted_chapter":1, "status":"resolved", "resolved_chapter":2}], "shared_draft":{"chapter_title":"第三十一章 测试", "body":"乙" * 800 + "草稿测试专用", "draft_only_fact":"草稿测试专用"}}
        with patch.object(c, "read_utf8", return_value=source):
            return c.parse_work(work)

    def test_formal_uses_same_thirty_chapter_requirements(self):
        c.DEV = False
        parsed = self.parse_synthetic_work()
        self.assertEqual(len(parsed["chapters"]), 30)
        self.assertEqual(c.ERRORS, [])

    def test_formal_rejects_twenty_nine_chapters(self):
        c.DEV = False
        self.parse_synthetic_work(chapters=29)
        self.assertIn("test:chapter_count", c.ERRORS)

    def test_each_chapter_must_reach_2500_han(self):
        self.parse_synthetic_work(length=2499)
        self.assertIn("test:chapter:1:length:2499", c.ERRORS)


if __name__ == "__main__":
    unittest.main()
