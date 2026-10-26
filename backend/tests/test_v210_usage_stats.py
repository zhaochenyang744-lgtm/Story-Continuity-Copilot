"""v2.1 usage statistics (`app.usage_stats`, schema stats-v1): read-only, numbers and codes only, and the numbers are right."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
import tempfile
from datetime import datetime

from app import problem_codes, usage_stats
from app.assistant_store import AssistantStore

from tests.assistant_case import AssistantCase
from tests.usage_stats_fixture import SENTINEL, Fixture

APP = pathlib.Path(usage_stats.__file__).parent


class StatsCase(AssistantCase):
    def setUp(self):
        self.start()
        self.register()
        self.own_work()
        registered, work = self.user_id, self.project_id
        self.visitor()
        visitor, sample_work = self.user_id, self.project_id
        self.path = pathlib.Path(self.db.paths.database_path)
        with self.db.connection() as c:
            self.fixture = Fixture(c, registered, visitor, work, sample_work)
            self.fixture.populate()
        self.stats = self.run_stats()

    def run_stats(self, *args):
        out = pathlib.Path(tempfile.mkdtemp(prefix="stats-")) / "out.json"
        self.assertEqual(usage_stats.main(["--db", str(self.path), "--out", str(out), *args]), 0)
        return json.loads(out.read_text(encoding="utf-8"))

    def overall(self, segment="registered", **group):
        part = self.stats["segments"][segment]
        if not group:
            return part["overall"]
        [found] = [g for g in part["groups"] if all(g[key] == value for key, value in group.items())]
        return found


def week(stamp):
    year, number, _ = datetime.fromisoformat(stamp).isocalendar()
    return f"{year}-W{number:02d}"


class NoTextTests(StatsCase):
    def test_the_sentinel_is_in_the_database_and_never_in_any_output(self):
        with sqlite3.connect(self.path) as c:
            holders = [name for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                       if any(SENTINEL in str(value) for row in c.execute(f"SELECT * FROM {name}") for value in row)]
        self.assertGreaterEqual(len(holders), 12, holders)  # the text columns of the tasks, steps, sources, cards, plans, questions, chapters ...
        out = pathlib.Path(tempfile.mkdtemp())
        for fmt, name in (("json", "stats.json"), ("markdown", "stats.md")):
            self.assertEqual(usage_stats.main(["--db", str(self.path), "--format", fmt, "--out", str(out / name)]), 0)
            text = (out / name).read_text(encoding="utf-8")
            self.assertNotIn(SENTINEL, text)
            self.assertNotIn("正文", text)  # nothing quoting a chapter either
        self.assertNotIn(SENTINEL, json.dumps(self.stats, ensure_ascii=False))

    def test_standard_output_carries_the_same_json(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(usage_stats.main(["--db", str(self.path)]), 0)
        self.assertEqual(json.loads(buffer.getvalue())["schema"], "stats-v1")

    def test_a_code_column_that_held_a_sentence_comes_out_as_unrecognized(self):
        with self.db.connection() as c:
            c.execute("UPDATE assistant_tasks SET error_code=?,prompt_version=?,model_label=? WHERE error_code='provider_timeout'",
                      (f"这是一句{SENTINEL}", f"版本{SENTINEL}", f"模型{SENTINEL}"))
            c.execute("UPDATE assistant_steps SET diagnostics_json=? WHERE diagnostics_json LIKE '%people_unsupported%'",
                      (json.dumps({"problem_codes": [f"句子{SENTINEL}", "ref_unknown"], "repairs": 1, "dropped": 1, "dropped_codes": {f"码{SENTINEL}": 1}}, ensure_ascii=False),))
        stats = self.run_stats()
        text = json.dumps(stats, ensure_ascii=False)
        self.assertNotIn(SENTINEL, text)
        self.assertIn(usage_stats.UNRECOGNIZED, text)

    def test_only_allow_listed_columns_are_read_and_nothing_is_written(self):
        reads: set[tuple[str, str]] = set()
        writes: list[int] = []
        original = usage_stats.open_readonly

        def watched(path):
            connection = original(path)

            def authorizer(action, arg1, arg2, database, source):
                if action == sqlite3.SQLITE_READ:
                    reads.add((arg1, arg2))
                elif action not in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_PRAGMA, sqlite3.SQLITE_FUNCTION):
                    writes.append(action)
                return sqlite3.SQLITE_OK
            connection.set_authorizer(authorizer)
            return connection
        usage_stats.open_readonly = watched
        self.addCleanup(setattr, usage_stats, "open_readonly", original)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.run_stats()
        self.assertEqual(writes, [])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        outside = sorted((table, column) for table, column in reads
                         if table != "sqlite_master" and column not in usage_stats.ALLOWED.get(table, ()))
        self.assertEqual(outside, [])
        self.assertEqual({table for table, _ in reads} - {"sqlite_master"}, set(usage_stats.ALLOWED))  # and each table on the list is read
        # The text columns are on no list.
        for table, columns in usage_stats.ALLOWED.items():
            for column in columns:
                self.assertFalse(column.endswith(("_json",)) and column not in ("reasons_json", "diagnostics_json"), (table, column))
        self.assertNotRegex((APP / "usage_stats.py").read_text(encoding="utf-8").split('"""', 2)[2], r"SELECT\s+\*|\.\*\s+FROM")

    def test_the_database_is_opened_read_only(self):
        connection = usage_stats.open_readonly(self.path)
        self.addCleanup(connection.close)
        for statement in ("CREATE TABLE trial(a)", "UPDATE assistant_tasks SET status='x'", "DELETE FROM assistant_tasks", "INSERT INTO v2_users(id) VALUES('x')"):
            with self.assertRaises(sqlite3.Error, msg=statement):
                connection.execute(statement)
        self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
        self.assertEqual(usage_stats.main(["--db", str(self.path.parent / "no-such.sqlite3")]), 2)  # a missing file is not created


class NumbersTests(StatsCase):
    def test_the_shape_is_stats_v1(self):
        self.assertEqual(self.stats["schema"], "stats-v1")
        self.assertEqual(set(self.stats), {"schema", "meta", "segments", "traces"})
        self.assertEqual(list(self.stats["segments"]), ["registered", "visitor", "sample"])
        self.assertEqual(list(self.overall()), ["cards", "tasks", "status", "status_rate", "error_codes", "feedback", "steps", "elapsed_seconds", "cost_cny",
                                                "chars_charged", "input_tokens", "output_tokens", "rules", "long"])  # the cards come first
        self.assertEqual(set(self.stats["segments"]["sample"]), {"overall", "groups"})
        self.assertEqual(self.stats["meta"]["missing_columns"], {})

    def test_sample_visitor_and_registered_are_counted_apart(self):
        meta = self.stats["meta"]["tasks_by_segment"]
        # registered: 4 asks + 1 later ask + 1 change + 4 long tasks; visitor: 1; sample: 2 (the hidden shadow run is nobody's task)
        self.assertEqual(meta, {"registered": 10, "visitor": 1, "sample": 2})
        self.assertEqual(self.overall()["tasks"], 10)
        self.assertEqual(self.overall("visitor")["tasks"], 1)
        self.assertEqual(self.overall("sample")["tasks"], 2)
        self.assertEqual(self.overall("sample")["cards"]["all"]["confirmed"], 1)
        self.assertEqual(self.overall()["cards"]["all"]["proposed"], 5)  # the sample work's card is not in it
        self.assertEqual(self.overall("sample")["error_codes"], {"provider_timeout": 1})
        self.assertNotIn("provider_timeout", self.overall()["error_codes"])

    def test_cards_by_kind_with_their_rates(self):
        cards = self.overall()["cards"]
        self.assertEqual(cards["by_kind"]["add_fact"], {"proposed": 4, "confirmed": 3, "rejected": 1, "undone": 1, "edited": 1,
                                                       "confirm_rate": 0.75, "reject_rate": 0.25, "undo_rate": 0.3333})
        self.assertEqual(cards["by_kind"]["resolve_thread"]["proposed"], 1)
        self.assertEqual((cards["by_kind"]["resolve_thread"]["confirm_rate"], cards["by_kind"]["resolve_thread"]["undo_rate"]), (0.0, None))
        self.assertEqual(cards["all"]["proposed"], 5)
        self.assertEqual(cards["all"]["confirm_rate"], 0.6)

    def test_status_shares_feedback_and_the_spread_of_a_group(self):
        group = self.overall(kind="ask", prompt_version="p-test-1", week=week("2026-10-05T08:00:00+00:00"))
        self.assertEqual(group["tasks"], 4)
        self.assertEqual(group["status"], {"completed": 3, "failed": 1, "stopped": 0, "unfinished": 0})
        self.assertEqual(group["status_rate"]["completed"], 0.75)
        self.assertEqual(group["error_codes"], {"citation_validation_failed": 1})
        self.assertEqual(group["feedback"], {"up": 2, "down": 1, "down_rate": 0.3333, "down_reasons": {"wrong": 1, "verbose": 0, "not_found": 0, "bad_source": 1}})
        self.assertEqual(group["cost_cny"], {"median": 0.25, "p90": 0.4})
        self.assertEqual(group["steps"], {"median": 3.5, "p90": 5.0})
        self.assertEqual(group["elapsed_seconds"], {"median": 25.0, "p90": 40.0})
        self.assertEqual(group["chars_charged"], {"median": 500.0, "p90": 500.0})
        # another prompt version and another week are other groups
        later = self.overall(kind="ask", prompt_version="p-test-2")
        self.assertEqual((later["tasks"], later["week"], later["feedback"]["down_rate"]), (1, week("2026-10-12T08:00:00+00:00"), 1.0))

    def test_the_overall_row_adds_the_groups_up(self):
        part = self.stats["segments"]["registered"]
        self.assertEqual(sum(group["tasks"] for group in part["groups"]), part["overall"]["tasks"])
        self.assertEqual(part["overall"]["feedback"]["down"], 2)
        self.assertEqual(part["overall"]["status"], {"completed": 6, "failed": 2, "stopped": 1, "unfinished": 1})

    def test_the_rules_that_failed_the_repairs_and_the_dropped(self):
        rules = self.overall()["rules"]
        self.assertEqual(rules["failed_codes"], {"ref_unknown": 2, "thread_unknown": 2, "conflict_malformed": 2, "ref_outside_step": 1, "sentence_no_ref": 1})
        self.assertEqual(rules["failed_code_tasks"]["ref_unknown"], 1)  # one task, twice
        self.assertEqual(rules["dropped_codes"], {"people_unsupported": 1, "thread_unknown": 1})
        self.assertEqual(rules["apply_dropped_codes"], {"change_evidence_invalid": 1})
        # a plain task has one repair at most (two ask tasks); a long task counts the calls (1 + 1 + 1)
        self.assertEqual((rules["repairs"], rules["repaired_tasks"]), (5, 4))
        self.assertEqual(rules["dropped"], 2)

    def test_long_tasks(self):
        long = self.overall(kind="long")["long"]
        self.assertEqual(long["tasks"], 4)
        self.assertEqual(long["plan_types"], {"thread_audit": 2, "tidy": 1, "trace": 1})
        self.assertEqual(long["origin"], {"mode": 2, "route": 1, "unknown": 1})
        self.assertEqual((long["planned"], long["range_edited"], long["range_edited_rate"], long["cap_edited"], long["cap_edited_rate"]), (4, 1, 0.25, 1, 0.25))
        self.assertEqual((long["asked"], long["asked_rate"], long["question_kinds"]), (2, 0.5, {"budget": 1, "decision": 1}))
        self.assertEqual(long["stopped_by"], {"cost_cap": 1, "none": 2, "program_error": 1})
        self.assertEqual(long["cost_cap_stop_rate"], 0.25)
        self.assertEqual(long["steps"], {"total": 4, "with_repair": 3, "repairs": 3, "with_dropped": 1, "dropped": 1, "not_done": 1})
        self.assertEqual(long["step_seconds"], {"median": 40.0, "p90": 60.0})
        self.assertEqual(self.overall()["long"]["tasks"], 4)
        self.assertEqual(self.overall(kind="ask", prompt_version="p-test-1")["long"]["tasks"], 0)

    def test_since_and_until_cut_by_the_day_a_task_was_made(self):
        later = self.run_stats("--since", "2026-10-10")
        self.assertEqual(later["meta"]["tasks"], 1)
        self.assertEqual(self.run_stats("--until", "2026-10-05")["meta"]["tasks"], 12)
        self.assertEqual(self.run_stats("--until", "2026-10-04")["meta"]["tasks"], 0)

    def test_traces_list_the_thumbs_down_the_failed_and_the_undone_without_text(self):
        traces = {trace["task_id"]: trace for trace in self.stats["traces"]}
        why = {trace["task_id"]: trace["why"] for trace in self.stats["traces"]}
        self.assertEqual(sorted(sorted(w) for w in why.values()), [["card_undone"], ["failed"], ["failed", "thumbs_down"], ["failed", "thumbs_down"], ["thumbs_down"]])
        failed = next(trace for trace in traces.values() if trace["error_code"] == "citation_validation_failed")
        self.assertEqual((failed["kind"], failed["prompt_version"], failed["model"], failed["status"], failed["segment"]), ("ask", "p-test-1", "deepseek-flash", "failed", "registered"))
        self.assertEqual(sorted(failed["why"]), ["failed", "thumbs_down"])
        self.assertEqual(failed["feedback"], {"down": 1, "reasons": {"bad_source": 1, "wrong": 1}})
        self.assertEqual([(s["kind"], s["tool"], s["result_count"], s["error_code"], s["rule_codes"], s["elapsed_ms"]) for s in failed["steps"]],
                         [("tool", "read_chapter", 1, None, [], 80), ("repair", None, None, "citation_validation_failed", ["ref_unknown", "sentence_no_ref"], 700),
                          ("repair", None, None, "citation_validation_failed", ["ref_unknown"], 650)])
        self.assertEqual((failed["cost_cny"], failed["elapsed_seconds"]), (0.4, 40.0))
        undone = next(trace for trace in traces.values() if trace["why"] == ["card_undone"])
        self.assertEqual((undone["kind"], undone["cards"]), ("change", {"proposed": 5, "confirmed": 3, "rejected": 1, "undone": 1, "edited": 1}))
        long = next(trace for trace in traces.values() if trace["kind"] == "long")
        self.assertEqual((long["status"], long["error_code"], long["long"]["stopped_by"], long["long"]["plan_type"]), ("failed", "assistant_long_report_invalid", "program_error", "trace"))
        self.assertEqual(long["long"]["steps"][0]["rule_codes"], ["conflict_malformed", "conflict_malformed"])
        self.assertEqual(len(traces), 5)  # the failed ask, the other thumbs-down, the undone change, the failed long task and the sample's failed ask

    def test_markdown_for_people(self):
        out = pathlib.Path(tempfile.mkdtemp()) / "stats.md"
        self.assertEqual(usage_stats.main(["--db", str(self.path), "--format", "markdown", "--out", str(out)]), 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("stats-v1", text)
        self.assertLess(text.index("卡片"), text.index("失败码"))
        self.assertIn("ref_unknown", text)
        self.assertIn("add_fact", text)


class OlderDatabaseTests(StatsCase):
    def test_a_database_from_before_this_release_is_read_with_the_missing_columns_empty(self):
        old = pathlib.Path(tempfile.mkdtemp()) / "old.sqlite3"
        with sqlite3.connect(old) as c:
            c.execute("CREATE TABLE assistant_tasks(id TEXT, project_id TEXT, user_id TEXT, kind TEXT, status TEXT, error_code TEXT, steps_used INTEGER, input_tokens INTEGER,"
                      "output_tokens INTEGER, cost_cny REAL, chars_charged INTEGER, prompt_version TEXT, model_label TEXT, created_at TEXT, started_at TEXT, completed_at TEXT)")
            c.execute("INSERT INTO assistant_tasks VALUES('atask-1','p','u','ask','completed',NULL,2,1,1,0.1,500,'v1','m','2026-10-05T08:00:00+00:00','2026-10-05T08:00:00+00:00','2026-10-05T08:00:10+00:00')")
        connection = usage_stats.open_readonly(old)
        self.addCleanup(connection.close)
        stats = usage_stats.build(connection)
        self.assertEqual(stats["segments"]["registered"]["overall"]["tasks"], 1)
        self.assertIn("assistant_steps", stats["meta"]["missing_columns"])
        self.assertIn("internal_error_type", stats["meta"]["missing_columns"]["assistant_tasks"])


class CodesTests(StatsCase):
    def test_every_code_used_is_listed_and_every_listed_code_is_used(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in APP.glob("*.py") if path.name != "problem_codes.py")
        used = set(re.findall(r'Problem\(\s*"([a-z_]+)"', source)) | {"absence_cited", "attribution_cited", "refusal_cited", "people_unsupported"}
        self.assertEqual(sorted(used - set(problem_codes.CODES)), [])
        listed_elsewhere = {code for code in problem_codes.CODES if f'"{code}"' not in source}
        self.assertEqual(sorted(listed_elsewhere - {"change_evidence_invalid", "change_fact_already_recorded"}), [])  # those two are raised in assistant_actions as ToolError codes
        for code in problem_codes.CODES:
            self.assertRegex(code, r"^[a-z]+(_[a-z]+)*$")

    def test_a_problem_is_its_sentence(self):
        problem = problem_codes.Problem("ref_unknown", "第 1 句引用了不存在的编号 R9")
        self.assertEqual(problem, "第 1 句引用了不存在的编号 R9")
        self.assertEqual(json.dumps([problem], ensure_ascii=False), '["第 1 句引用了不存在的编号 R9"]')
        self.assertEqual(problem_codes.codes_of([problem, "plain"]), ["ref_unknown", "other"])


class PurgeTests(StatsCase):
    def test_deleting_a_work_removes_the_new_columns_with_the_rest(self):
        with self.db.connection() as c:
            before = c.execute("SELECT COUNT(*) FROM assistant_long_plans").fetchone()[0]
            from app import assistant_store
            assistant_store.purge(c, self.fixture.work)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM assistant_long_plans WHERE task_id IN (SELECT id FROM assistant_tasks WHERE project_id=?)", (self.fixture.work,)).fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM assistant_steps WHERE task_id IN (SELECT id FROM assistant_tasks WHERE project_id=?)", (self.fixture.work,)).fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM assistant_long_plans").fetchone()[0], before - 4)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM assistant_long_steps").fetchone()[0], 0)
