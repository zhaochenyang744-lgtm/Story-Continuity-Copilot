"""Task 07l (prompt assistant-p5): the four fixes from the A1/A1b formal review. No model, no network.

1. `lookup_facts` keeps the newest facts when there are too many, and can look back with `chapter_to`.
2. The prompt tells the model a round holds at most four calls and the process line names only those.
3. The server checks the note's "查过…" claims against the steps (`assistant_coverage`)."""
from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import contextmanager

from app.assistant import ASSISTANT_PROMPT_VERSION, SYSTEM_PROMPT
from app.assistant_coverage import chapter_number, mentioned_chapters, note_problems, without_untrue
from app.assistant_tools import FACTS_MAX, TOOLS, SourceRegistry, ToolContext, ToolError, run_tool

from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, turn
from tests.test_assistant_limits import read


# --- lookup_facts ------------------------------------------------------------------------------------------------------
class FakeDb:
    """Just the tables `run_lookup_facts` reads: aliases, characters, and which chapter each fact's span lies in."""

    def __init__(self, chapters: int = 15):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            "CREATE TABLE v2_character_aliases(project_id TEXT, character_id TEXT, status TEXT, normalized_alias TEXT);"
            "CREATE TABLE v2_characters(id TEXT, project_id TEXT, name TEXT);"
            "CREATE TABLE v2_chapters(id TEXT, project_id TEXT, chapter_number INTEGER);"
            "CREATE TABLE v2_source_spans(id TEXT, project_id TEXT, chapter_id TEXT);")
        for n in range(1, chapters + 1):
            self.conn.execute("INSERT INTO v2_chapters VALUES(?,?,?)", (f"ch{n}", "p", n))
            self.conn.execute("INSERT INTO v2_source_spans VALUES(?,?,?)", (f"sp{n}", "p", f"ch{n}"))

    @contextmanager
    def connection(self):
        yield self.conn

    @staticmethod
    def _normalized_alias(value: str) -> str:
        return value.lower()


class FakeStore:
    def sources(self, task_id):
        return {}

    def add_source(self, *args):
        pass


def fact(number: int, chapter: int, subject: str, value: str) -> dict:
    return {"id": f"f{number:02d}", "subject": subject, "value": value, "source_span_id": f"sp{chapter}"}


def context(memory: list[dict], *, kind: str = "ask", max_chapter: int = 15, db: FakeDb | None = None) -> ToolContext:
    ctx = ToolContext(db or FakeDb(), "p", {"kind": kind}, {"max_chapter": max_chapter}, SourceRegistry(FakeStore(), "t"))
    ctx._memory = memory
    ctx._chapters = {n: {"title": f"第{n}章标题"} for n in range(1, 16)}
    return ctx


# Twenty facts over chapters 1-15: nine have Maren as subject, eleven only mention her in their text.
ABOUT = [1, 3, 5, 7, 9, 11, 13, 14, 15]
MENTION = [1, 2, 4, 6, 8, 10, 11, 12, 13, 14, 15]


def maren_facts() -> list[dict]:
    facts = [fact(index, chapter, "Maren", f"Maren 在第 {chapter} 章的状态") for index, chapter in enumerate(ABOUT, 1)]
    facts += [fact(100 + index, chapter, "Dorn", f"Dorn 在第 {chapter} 章提到 Maren") for index, chapter in enumerate(MENTION, 1)]
    return facts


class LookupFactsTests(unittest.TestCase):
    def lookup(self, ctx: ToolContext, **args):
        outcome = run_tool("lookup_facts", ctx.task["kind"], ctx, {"name": "Maren", **args})
        return outcome.result, outcome

    def test_the_newest_twelve_are_kept_subject_matches_first_and_listed_oldest_to_newest(self):
        result, outcome = self.lookup(context(maren_facts()))
        facts = result["facts"]
        self.assertEqual((result["total_matched"], result["earlier_not_listed"], len(facts)), (20, 8, FACTS_MAX))
        self.assertEqual(outcome.count, FACTS_MAX)
        chapters = [item["chapter"] for item in facts]
        self.assertEqual(chapters, sorted(chapters))
        about = [item for item in facts if item["text"].startswith("Maren：")]
        mentions = [item for item in facts if item["text"].startswith("Dorn：")]
        self.assertEqual([item["chapter"] for item in about], ABOUT)  # every fact about her is kept
        self.assertEqual([item["chapter"] for item in mentions], [13, 14, 15])  # the newest mentions fill the rest
        self.assertEqual(chapters[-1], 15)

    def test_more_than_twelve_facts_about_her_keep_the_latest_twelve(self):
        facts = [fact(index, chapter, "Maren", f"状态 {chapter}") for index, chapter in enumerate(range(1, 16), 1)]
        facts.append(fact(99, 15, "Dorn", "Dorn 提到 Maren"))
        result, _ = self.lookup(context(facts))
        self.assertEqual([item["chapter"] for item in result["facts"]], list(range(4, 16)))
        self.assertEqual((result["total_matched"], result["earlier_not_listed"]), (16, 4))
        self.assertTrue(all(item["text"].startswith("Maren：") for item in result["facts"]))

    def test_few_matches_are_all_listed(self):
        result, _ = self.lookup(context(maren_facts()[:3]))
        self.assertEqual((result["total_matched"], result["earlier_not_listed"], len(result["facts"])), (3, 0, 3))

    def test_chapter_to_looks_back_and_the_counts_follow(self):
        ctx = context(maren_facts())
        result, outcome = self.lookup(ctx, chapter_to=12)
        self.assertEqual(max(item["chapter"] for item in result["facts"]), 12)
        self.assertEqual((result["total_matched"], result["earlier_not_listed"], len(result["facts"])), (14, 2, 12))
        self.assertEqual((result["chapter_to"], outcome.args), (12, {"name": "Maren", "chapter_to": 12}))
        result, _ = self.lookup(ctx, chapter_to=8)
        self.assertEqual((result["total_matched"], result["earlier_not_listed"], max(item["chapter"] for item in result["facts"])), (9, 0, 8))
        # Without it the arguments and the result carry no chapter_to.
        result, outcome = self.lookup(ctx)
        self.assertNotIn("chapter_to", result)
        self.assertEqual(outcome.args, {"name": "Maren"})
        for bad in (0, -1, "8", True, 2.5):
            with self.assertRaises(ToolError):
                self.lookup(ctx, chapter_to=bad)

    def test_a_recap_never_goes_past_its_last_chapter(self):
        ctx = context(maren_facts(), kind="recap", max_chapter=9)
        plain, _ = self.lookup(ctx)
        beyond, _ = self.lookup(ctx, chapter_to=15)
        for result in (plain, beyond):
            self.assertLessEqual(max(item["chapter"] for item in result["facts"]), 9)
            self.assertEqual(result["total_matched"], 5 + 5)  # chapters 1, 3, 5, 7, 9 about her; 1, 2, 4, 6, 8 mention her
        self.assertEqual(plain["facts"], beyond["facts"])
        earlier, _ = self.lookup(ctx, chapter_to=4)
        self.assertEqual(max(item["chapter"] for item in earlier["facts"]), 4)

    def test_an_alias_finds_the_facts_of_the_character(self):
        db = FakeDb()
        db.conn.execute("INSERT INTO v2_characters VALUES('c1','p','Maren')")
        db.conn.execute("INSERT INTO v2_character_aliases VALUES('p','c1','active','小玛')")
        result = run_tool("lookup_facts", "ask", context(maren_facts(), db=db), {"name": "小玛"}).result
        self.assertEqual((result["total_matched"], len(result["facts"])), (20, 12))

    def test_the_tool_text_says_newest_twelve_and_chapter_to(self):
        tool = TOOLS["lookup_facts"]
        self.assertIn("最晚的 12 条", tool.description)
        self.assertIn("chapter_to", tool.description)
        self.assertIn("total_matched", tool.description)
        self.assertIn("earlier_not_listed", tool.description)
        self.assertEqual(tool.parameters["properties"]["chapter_to"]["type"], "integer")
        self.assertEqual(tool.parameters["required"], ["name"])
        self.assertEqual(tool.summary({"name": "Maren"}, None), "查事实：Maren")
        self.assertEqual(tool.summary({"name": "Maren", "chapter_to": 8}, None), "查事实：Maren（截至第 8 章）")


# --- the prompt ----------------------------------------------------------------------------------------------------------
class PromptTests(unittest.TestCase):
    def test_version_and_the_new_rules(self):
        self.assertEqual(ASSISTANT_PROMPT_VERSION, "assistant-p61")
        self.assertIn("一轮最多调用 6 次工具，说明只写这一轮实际要调用的那几项", SYSTEM_PROMPT)
        self.assertIn("要查的超过 6 项，就分到下一轮，下一轮再写新的说明", SYSTEM_PROMPT)
        self.assertIn("中文不超过 40 字，英文不超过 20 个词", SYSTEM_PROMPT)


# --- the note --------------------------------------------------------------------------------------------------------------
def tool_step(name: str, error: str | None = None, **args) -> dict:
    return {"kind": "tool", "tool_name": name, "args_json": json.dumps(args), "error_code": error}


def read_step(chapter: int, error: str | None = None) -> dict:
    return tool_step("read_chapter", error, chapter_number=chapter, from_char=0, max_chars=2000)


def search_step(low: int, high: int, error: str | None = None) -> dict:
    return tool_step("search_text", error, query="罗盘", chapter_from=low, chapter_to=high)


class NoteCoverageTests(unittest.TestCase):
    def test_the_four_clauses_of_the_formal_run(self):
        # a1f-fix-03: the note says chapters 5 and 7 were read, only 7 was.
        problems = note_problems("查过第13章草稿、本章检查结果、第5章与第7章正文", [tool_step("read_draft"), tool_step("get_issues"), read_step(7)])
        self.assertEqual(len(problems), 1)
        self.assertIn("第 5 章", problems[0])
        self.assertIn("第5章与第7章正文", problems[0])
        self.assertIn("去掉这一处说法", problems[0])
        self.assertIn("补查", problems[0])
        # The draft's last check result, and no chapter claim: fine.
        self.assertEqual(note_problems("以及本章草稿的最近一次检查结果（无检查结果）", [tool_step("get_issues")]), [])
        # A denial is not checked.
        self.assertEqual(note_problems("补前文铺垫的改法因第12章原文未取到", [read_step(3)]), [])
        # Two chapters named by Chinese numerals, both read.
        self.assertEqual(note_problems("查过第三十章、第七十一章正文", [read_step(30), read_step(71)]), [])

    def test_a_search_range_covers_the_chapters_inside_it(self):
        note = "搜过第2章与第9章正文"
        self.assertEqual(note_problems(note, [search_step(1, 10)]), [])
        self.assertEqual(note_problems(note, [search_step(3, 10)])[0].count("第 2 章"), 1)
        self.assertEqual(note_problems(note, [search_step(3, 10), read_step(2)]), [])
        self.assertEqual(len(note_problems(note, [search_step(1, 8)])), 1)

    def test_a_failed_call_does_not_count(self):
        self.assertEqual(len(note_problems("查过第7章正文", [read_step(7, "chapter_out_of_scope")])), 1)
        self.assertEqual(len(note_problems("查过第7章正文", [search_step(1, 10, "invalid_arguments")])), 1)
        self.assertEqual(len(note_problems("查过本章草稿", [tool_step("read_draft", "draft_not_in_scope")])), 1)
        self.assertEqual(len(note_problems("查过本章草稿的检查结果", [tool_step("get_issues", "draft_not_found")])), 1)

    def test_a_range_of_chapters(self):
        steps = [read_step(n) for n in (1, 2, 3, 5)]
        self.assertEqual(note_problems("查过第1至3章正文", steps), [])
        problems = note_problems("查过第1至5章正文", steps)
        self.assertEqual(len(problems), 1)
        self.assertIn("第 4 章", problems[0])
        self.assertEqual(len(note_problems("查过第三至六章正文", steps)), 1)  # 4 and 6 are missing
        self.assertEqual(note_problems("查过第三至五章正文", steps + [read_step(4)]), [])
        self.assertEqual(note_problems("查过第1-3章正文", steps), [])
        self.assertEqual(note_problems("读了第5章至第7章正文", [read_step(5), read_step(6), read_step(7)]), [])

    def test_a_list_of_chapters_in_one_phrase(self):
        self.assertEqual(note_problems("查过第2、9章正文", [read_step(2), read_step(9)]), [])
        self.assertEqual(len(note_problems("查过第2、9章正文", [read_step(2)])), 1)
        self.assertEqual(len(note_problems("查过第2章、第9章正文", [read_step(9)])), 1)

    def test_the_draft_rules(self):
        self.assertEqual(note_problems("查过本章草稿", [tool_step("read_draft")]), [])
        self.assertEqual(len(note_problems("查过本章草稿", [tool_step("get_issues")])), 1)
        self.assertEqual(note_problems("查过草稿的检查结果", [tool_step("get_issues")]), [])
        self.assertEqual(len(note_problems("查过草稿的检查结果", [tool_step("read_draft")])), 1)
        # "草稿" with "检查" asks for the check result only.
        self.assertEqual(note_problems("看了草稿检查", [tool_step("get_issues")]), [])

    def test_clauses_about_facts_plans_and_check_results_are_not_checked_by_chapter(self):
        for clause in ("查了第5章记录的事实", "看了第8章的计划和伏笔", "第5章的检查结果", "查过第12章相关伏笔"):
            self.assertEqual(note_problems(clause, []), [], clause)
        # ...but a mention of the text itself brings the check back.
        self.assertEqual(len(note_problems("查了第5章的事实和正文", [])), 1)
        self.assertEqual(len(note_problems("查过第5章", [])), 1)

    def test_denials_are_left_alone(self):
        for clause in ("第5章正文没查", "未读到第5章正文", "未取到第12章原文", "没能读取第6章正文", "没有找到问题问到的内容", "无法读取第3章正文"):
            self.assertEqual(note_problems(clause, []), [], clause)
        # Only the clause with the denial is skipped.
        self.assertEqual(len(note_problems("查过第5章正文，没有找到问题问到的内容", [])), 1)
        self.assertEqual(note_problems("查过第7章正文，没读第5章", [read_step(7)]), [])

    def test_no_note_or_no_claim(self):
        self.assertEqual(note_problems(None, []), [])
        self.assertEqual(note_problems("", []), [])
        self.assertEqual(note_problems("查过正文、谁的事实、计划，没有找到问题问到的内容。", []), [])

    def test_every_wrong_clause_is_named(self):
        problems = note_problems("查过第5章正文，查过第6章正文，查过第7章正文", [read_step(6)])
        self.assertEqual(len(problems), 2)
        self.assertIn("第 5 章", problems[0])
        self.assertIn("第 7 章", problems[1])

    def test_untrue_clauses_can_be_taken_out_of_the_note(self):
        steps = [read_step(7), tool_step("get_issues")]
        self.assertEqual(without_untrue("查过第5章正文，查过第7章正文，没有找到问题问到的内容。", steps),
                         "查过第7章正文，没有找到问题问到的内容。")
        self.assertEqual(without_untrue("查过第7章正文，查过第5章正文。", steps), "查过第7章正文。")
        self.assertEqual(without_untrue("查过本章草稿的检查结果；查过第5章正文", steps), "查过本章草稿的检查结果")
        self.assertIsNone(without_untrue("查过第5章正文", steps))
        self.assertEqual(without_untrue("查过第7章正文。", steps), "查过第7章正文。")
        self.assertIsNone(without_untrue(None, steps))

    def test_chinese_numbers(self):
        for text, number in (("5", 5), ("12", 12), ("三", 3), ("十", 10), ("十二", 12), ("二十", 20), ("三十", 30), ("七十一", 71),
                             ("一百", 100), ("一百零五", 105), ("两", 2)):
            self.assertEqual(chapter_number(text), number, text)
        self.assertIsNone(chapter_number("零"))
        self.assertIsNone(chapter_number("三x"))
        self.assertEqual(mentioned_chapters("第三至六章"), [(3, 6)])
        self.assertEqual(mentioned_chapters("第六至三章"), [(3, 6)])
        self.assertEqual(mentioned_chapters("第1至12章与第30章"), [(1, 12), (30, 30)])
        self.assertEqual(mentioned_chapters("第5个人物"), [])
        self.assertEqual(mentioned_chapters("第一次出现"), [])


class NoteInTheLoopTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_a_note_claiming_an_unread_chapter_is_sent_back_once_and_the_fixed_answer_is_kept(self):
        wrong = turn(answer_call("not_found", [], note="查过第2章与第9章正文，没有找到问题问到的内容。"))
        right = turn(answer_call("not_found", [], note="查过第9章正文，没有找到问题问到的内容。"))
        task = self.run_ask(read(9), wrong, right)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["answer"]["note"], "查过第9章正文，没有找到问题问到的内容。")
        self.assertEqual([step["kind"] for step in task["steps"]], ["say", "tool", "repair"])
        feedback = json.loads([m for m in self.provider.calls[2]["messages"] if m["role"] == "tool"][-1]["content"])
        self.assertEqual(feedback["error"], "answer_invalid")
        self.assertIn("第 2 章", feedback["problems"][0])
        self.assertIn("第2章与第9章正文", feedback["problems"][0])

    def test_the_model_may_look_it_up_instead(self):
        wrong = turn(answer_call("not_found", [], note="查过第2章与第9章正文，没有找到问题问到的内容。"))
        task = self.run_ask(read(9), wrong, read(2), wrong)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([step["kind"] for step in task["steps"]], ["say", "tool", "repair", "say", "tool"])

    def test_after_the_one_repair_the_untrue_places_are_dropped_and_the_answer_kept(self):
        wrong = turn(answer_call("not_found", [], note="查过第2章正文，没有找到问题问到的内容。"))
        task = self.run_ask(read(9), wrong, wrong)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["answer"]["note"], "没有找到问题问到的内容。")
        self.assertEqual([step["kind"] for step in task["steps"]], ["say", "tool", "repair"])

    def test_a_not_found_note_that_was_all_untrue_still_says_nothing_was_found(self):
        wrong = turn(answer_call("not_found", [], note="查过第2章正文"))
        task = self.run_ask(read(9), wrong, wrong)
        self.assertEqual((task["status"], task["answer"]["note"]), ("completed", "没有找到问题问到的内容。"))

    def test_a_search_covering_the_chapter_is_enough(self):
        task = self.run_ask(turn(call("search_text", query="罗盘")), turn(answer_call("not_found", [], note="搜过第2章与第9章正文，没有找到问题问到的内容。")))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([step["kind"] for step in task["steps"]], ["say", "tool"])

    def test_lookup_facts_with_chapter_to_in_the_loop(self):
        task = self.run_ask(turn(call("lookup_facts", name="温岚", chapter_to=5)), turn(call("lookup_facts", name="温岚", chapter_to=0)),
                            turn(answer_call("not_found", [], note="查了温岚的事实，没有找到问题问到的内容。")))
        self.assertEqual(task["status"], "completed", task)
        tools = [step for step in task["steps"] if step["kind"] == "tool"]
        self.assertEqual([step["summary"] for step in tools], ["查事实：温岚（截至第 5 章）", "查事实：温岚"])
        self.assertEqual([step["error_code"] for step in tools], [None, "invalid_arguments"])
        shown = [json.loads(m["content"]) for m in self.provider.calls[1]["messages"] if m["role"] == "tool"][0]
        self.assertEqual((shown["chapter_to"], [item["chapter"] for item in shown["facts"]], shown["total_matched"]), (5, [4], 1))
        self.assertEqual(shown["total_matched"] - shown["earlier_not_listed"], len(shown["facts"]))


if __name__ == "__main__":
    unittest.main()
