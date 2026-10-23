"""The assistant's limits (v1.8.0 task 03): rounds, cost, time, protocol errors, cancelling, scope, quotas, visitors, the project guard."""
from __future__ import annotations

import json
import unittest

from app.assistant import ASSISTANT_MAX_ROUNDS
from app.stage13 import ASSISTANT_TASK_CHARS

from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, raw_call, ref_of_chapter, text, tool_items, turn
from tests.test_assistant import cite


def read(chapter: int, **kwargs):
    return turn(call("read_chapter", chapter_number=chapter), **kwargs)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class LoopLimitTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_the_seventh_round_offers_only_answer_and_requires_it(self):
        task = self.run_ask(*[read(n) for n in range(1, 7)], cite(1, words="只读了前几章。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(len(self.provider.calls), ASSISTANT_MAX_ROUNDS - 1)
        for earlier in self.provider.calls[:6]:
            self.assertEqual(earlier["tool_choice"], "auto")
            self.assertIn("search_text", earlier["tools"])
        last = self.provider.calls[6]
        self.assertEqual((last["tools"], last["tool_choice"]), (["answer"], "required"))
        self.assertIn("步数或预算已到", last["messages"][-1]["content"])
        self.assertEqual(task["usage"]["steps"], 7)
        self.assertEqual(task["coverage"]["not_checked"][-1], "步数或预算已到，没有查完")

    def test_an_answer_rejected_in_the_seventh_round_is_repaired_in_the_eighth(self):
        task = self.run_ask(*[read(n) for n in range(1, 7)], turn(answer_call("answered", [("结论。", ["R99"])])), cite(1))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["usage"]["steps"], ASSISTANT_MAX_ROUNDS)
        self.assertEqual(self.provider.calls[7]["tool_choice"], "required")
        self.assertEqual(sum(s["kind"] == "repair" for s in task["steps"]), 1)

    def test_a_task_that_cannot_answer_on_the_last_round_fails_and_gives_the_characters_back(self):
        task = self.run_ask(*[read(n) for n in range(1, 8)], read(8))
        self.assertEqual((task["status"], task["error_code"]), ("failed", "assistant_no_answer"))
        self.assertEqual(self.usage()["check_chars_used"], 0)

    def test_cost_at_the_force_threshold_ends_the_search(self):
        # One call already past the line (p12: two calls of ¥0.13 would be stopped a call earlier, by the expected cost).
        task = self.run_ask(read(1, cost=0.26), cite(1, words="先到这里。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([call["tool_choice"] for call in self.provider.calls], ["auto", "required"])
        self.assertEqual(self.provider.calls[1]["tools"], ["answer"])

    def test_cost_beyond_the_ceiling_stops_the_task_and_returns_the_characters(self):
        task = self.run_ask(read(1, cost=0.2), read(2, cost=0.2), cite(1))
        self.assertEqual((task["status"], task["error_code"]), ("failed", "assistant_budget_exhausted"))
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(self.usage()["check_chars_used"], 0)
        self.assertEqual(task["coverage"]["not_checked"][-1], "步数或预算已到，没有查完")
        # The daily budget carries what was really spent, not the ceiling that was reserved.
        self.assertEqual(self.rows("SELECT reserved_microunits r FROM v2_usage_reservations WHERE workflow_kind='assistant_task'")[0]["r"], 400_000)

    def test_cost_falls_back_to_the_token_rates(self):
        task = self.run_ask(read(1, cost=None, input_tokens=1_000_000, output_tokens=500_000), cite(1))  # rates in test settings: 1 and 2 per million
        self.assertEqual((task["status"], task["error_code"]), ("failed", "assistant_budget_exhausted"))
        self.assertAlmostEqual(self.rows("SELECT cost_cny FROM assistant_tasks")[0]["cost_cny"], 2.0)

    def test_the_wall_clock_forces_the_answer(self):
        clock = FakeClock()
        self.engine.clock = clock

        def slow(provider, messages):
            clock.now += 100
            return read(2)
        task = self.run_ask(read(1), slow, cite(1, words="时间到了。"))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([call["tool_choice"] for call in self.provider.calls], ["auto", "auto", "required"])

    def test_plain_text_twice_in_a_row_is_a_protocol_error(self):
        task = self.run_ask(text("我觉得是的。"), text("真的是的。"))
        self.assertEqual((task["status"], task["error_code"]), ("failed", "assistant_protocol_error"))
        self.assertEqual([step["kind"] for step in task["steps"]], ["protocol_error", "protocol_error"])
        self.assertIn("没有调用工具", self.provider.calls[1]["messages"][-1]["content"])
        self.assertEqual(self.usage()["check_chars_used"], 0)

    def test_one_plain_text_reply_is_forgiven(self):
        task = self.run_ask(text("先想一想。"), read(9), text("再想想。"), cite(9))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual([step["kind"] for step in task["steps"]], ["protocol_error", "say", "tool", "protocol_error"])

    def test_only_six_calls_run_in_a_round(self):
        task = self.run_ask(turn(*[call("search_text", query=word) for word in ("罗盘", "雾钟", "渡船", "潮表", "灯塔", "缆绳", "电台")]), read(9), cite(9))
        self.assertEqual(task["status"], "completed", task)
        results = [m for m in self.provider.calls[1]["messages"] if m["role"] == "tool"]
        self.assertEqual(len(results), 7)
        self.assertEqual(json.loads(results[6]["content"]), {"error": "too_many_calls"})
        self.assertNotIn("error", json.loads(results[5]["content"]))
        steps = [step["summary"] for step in task["steps"]]
        self.assertEqual(steps[7], "搜正文：「电台」（超出每轮上限，没有执行）")
        self.assertNotIn("电台", steps[0])  # the line names only the calls that run

    def test_tool_errors_go_back_to_the_model_and_the_loop_goes_on(self):
        task = self.run_ask(
            turn(call("read_chapter", chapter_number=12), call("nope", x=1), raw_call("search_text", "{not json"), call("search_text", query="")),
            read(9), cite(9))
        self.assertEqual(task["status"], "completed", task)
        results = [json.loads(m["content"]) for m in self.provider.calls[1]["messages"] if m["role"] == "tool"]
        self.assertEqual([r.get("error") for r in results], ["chapter_out_of_scope", "unknown_tool", "invalid_arguments", "invalid_arguments"])
        self.assertEqual(task["coverage"]["checked"], ["读过第 9 章"])  # a call that failed checked nothing

    def test_the_model_being_unavailable_gives_the_characters_back(self):
        from app.provider import ProviderTimeout, ProviderFailure
        for failure, code in ((ProviderTimeout(), "provider_timeout"), (ProviderFailure(), "provider_failure")):
            task = self.run_ask(failure)
            self.assertEqual((task["status"], task["error_code"]), ("failed", code))
        self.assertEqual(self.usage()["check_chars_used"], 0)

    def test_an_unexpected_error_fails_the_task_as_internal(self):
        task = self.run_ask(RuntimeError("boom"))
        self.assertEqual((task["status"], task["error_code"]), ("failed", "internal_error"))
        self.assertEqual(self.usage()["check_chars_used"], 0)


class CancelTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()
        self.own_work()
    def test_cancelling_a_running_task_stops_it_before_the_next_round_and_keeps_the_characters(self):
        def cancel_meanwhile(provider, messages):
            task_id = self.rows("SELECT id FROM assistant_tasks")[0]["id"]
            response = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task_id}/cancel", headers=self.idem(), json={})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["data"]["status"], "cancelled")
            return read(9)
        task = self.run_ask(cancel_meanwhile, cite(9))
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(task["usage"]["chars_charged"], ASSISTANT_TASK_CHARS)
        self.assertEqual(self.usage()["check_chars_used"], ASSISTANT_TASK_CHARS)
        self.assertIsNone(task["answer"])
        # The ceiling that was reserved becomes the cost actually incurred.
        self.assertEqual(self.rows("SELECT reserved_microunits r FROM v2_usage_reservations WHERE workflow_kind='assistant_task'")[0]["r"], 10_000)
        self.assertEqual(self.ask(expect=None, headers=self.idem()).status_code, 202)  # the work is free for the next question

    def test_a_finished_task_cannot_be_cancelled_and_replays_are_safe(self):
        task = self.run_ask(read(9), cite(9))
        key = self.idem()
        for _ in range(2):
            response = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/cancel", headers=key, json={})
            self.assertEqual((response.status_code, response.json()["data"]["status"]), (200, "completed"))
        self.assertEqual(self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/nope/cancel", headers=self.idem(), json={}).status_code, 404)


class ScopeTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_chapters_beyond_the_scope_and_a_draft_off_the_writing_page_are_refused(self):
        task = self.run_ask(turn(call("read_chapter", chapter_number=11), call("read_draft"), call("get_issues")), read(1), cite(1, words="x"), page="chapters")
        results = [json.loads(m["content"]) for m in self.provider.calls[1]["messages"] if m["role"] == "tool"]
        self.assertEqual([r["error"] for r in results], ["chapter_out_of_scope", "draft_not_in_scope", "draft_not_in_scope"])
        self.assertNotIn("read_draft", self.provider.calls[0]["tools"])
        self.assertNotIn("get_issues", self.provider.calls[0]["tools"])
        self.assertIn("这次不能读当前草稿", self.provider.calls[0]["messages"][-1]["content"])
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["coverage"]["not_checked"], ["已确认事实", "计划"])

    def test_a_chapter_that_does_not_exist_is_not_found(self):
        from app.assistant_tools import ToolContext, SourceRegistry, run_tool, ToolError
        task_id = self.run_ask(read(1), cite(1))["id"]
        row = self.engine.store.row(task_id)
        scope = {"max_chapter": 12, "draft_readable": False}
        ctx = ToolContext(self.db, self.project_id, dict(row), scope, SourceRegistry(self.engine.store, task_id))
        with self.assertRaises(ToolError) as caught:
            run_tool("read_chapter", "ask", ctx, {"chapter_number": 11})
        self.assertEqual(caught.exception.code, "chapter_not_found")

    def test_the_draft_stays_as_it_was_when_the_task_began(self):
        draft = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["current_draft"]
        original = self.rows("SELECT body FROM v2_drafts WHERE id=?", draft["id"])[0]["body"]

        def author_saves_meanwhile(provider, messages):
            response = self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}", headers=self.idem(),
                                         json={"base_revision": draft["revision"], "body": "全新的草稿，和之前毫无关系。", "title": "新"})
            self.assertEqual(response.status_code, 200, response.text)
            return turn(call("read_draft"))
        task = self.run_ask(author_saves_meanwhile, text("再等等"), cite(1), page="writing")
        shown = json.loads([m for m in self.provider.calls[1]["messages"] if m["role"] == "tool"][0]["content"])
        self.assertEqual("".join(item["text"] for item in shown["passages"]), original)
        self.assertNotIn("全新的草稿", self.all_messages())
        self.assertEqual(self.rows("SELECT draft_revision FROM assistant_tasks")[0]["draft_revision"], draft["revision"])
        self.assertTrue(task["id"])


class QuotaTests(AssistantCase):
    def test_a_task_costs_five_hundred_characters_and_one_workflow_and_settles_to_the_real_cost(self):
        self.start()
        self.register()
        self.own_work()
        before = self.usage()
        self.assertEqual((before["check_chars_remaining"], before["assistant_task_chars"]), (60_000, 500))
        reserved = []
        self.run_ask(lambda p, m: (reserved.append(self.rows("SELECT reserved_microunits r FROM v2_usage_reservations WHERE workflow_kind='assistant_task'")[0]["r"]), read(9, cost=0.05))[1], cite(9))
        self.assertEqual(reserved, [300_000])  # the ceiling is held while the task runs
        after = self.usage()
        self.assertEqual((after["check_chars_used"], after["check_chars_remaining"]), (500, 59_500))
        reservation = self.rows("SELECT * FROM v2_usage_reservations WHERE workflow_kind='assistant_task'")
        self.assertEqual(len(reservation), 1)
        self.assertEqual(reservation[0]["reserved_microunits"], 60_000)  # two calls at 0.05 and 0.01
        self.assertEqual(self.rows("SELECT chars_charged,cost_cny FROM assistant_tasks")[0]["chars_charged"], 500)
        self.assertEqual(len(self.rows("SELECT * FROM v2_provider_attempts")), 2)  # every model call reserved an attempt

    def test_too_few_characters_refuse_the_task_before_anything_is_created(self):
        self.start(registered_check_chars=1000)
        self.register()
        self.own_work()
        for _ in range(2):
            self.run_ask(read(9), cite(9))
        self.provider.script()
        response = self.ask(expect=429)
        error = response.json()["error"]
        self.assertEqual((error["code"], error["details"]["remaining"]), ("character_quota_exceeded", 0))
        self.assertEqual(len(self.rows("SELECT * FROM assistant_tasks")), 2)
        self.assertEqual(len(self.rows("SELECT * FROM v2_usage_reservations WHERE workflow_kind='assistant_task'")), 2)
        self.assertEqual(self.provider.calls, [])

    def test_the_model_not_being_configured_is_a_503(self):
        self.start()
        self.register()
        self.own_work()
        self.provider.available = False
        error = self.ask(expect=503).json()["error"]
        self.assertEqual(error["code"], "provider_unavailable")
        self.assertEqual(self.rows("SELECT * FROM assistant_tasks"), [])

    def test_only_one_task_runs_per_work(self):
        self.start()
        self.register()
        self.own_work()
        seen = []

        def second_question(provider, messages):
            seen.append(self.ask(expect=None))
            return read(9)
        task = self.run_ask(second_question, cite(9))
        self.assertEqual(task["status"], "completed")
        self.assertEqual((seen[0].status_code, seen[0].json()["error"]["code"]), (409, "assistant_task_running"))
        self.assertEqual(len(self.rows("SELECT * FROM assistant_tasks")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM v2_character_usage")), 1)

    def test_the_project_token_guard_is_apart_from_the_run_guard(self):
        self.start(assistant_project_token_limit=1000)
        self.register()
        self.own_work()
        self.run_ask(read(9, input_tokens=700, output_tokens=600), cite(9))
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM v2_runs WHERE run_type='continuity' AND result_origin!='demo_preset'")[0]["n"], 0)
        self.assertFalse(self.db.session_budget_exhausted(self.project_id))  # the assistant's tokens are not v2_runs tokens
        error = self.ask(expect=429).json()["error"]
        self.assertEqual(error["code"], "assistant_project_budget_exceeded")
        self.assertEqual(len(self.rows("SELECT * FROM assistant_tasks")), 1)
        self.assertEqual(self.usage()["check_chars_used"], 500)

    def test_the_task_ceiling_and_visitor_limit_come_from_the_environment(self):
        import os
        from unittest.mock import patch
        from app.stage13 import Stage13Settings
        env = {"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3000", "BACKEND_ORIGIN": "http://127.0.0.1:8000",
               "TRUSTED_HOSTS": "127.0.0.1:8000", "TRUSTED_ORIGINS": "http://127.0.0.1:3000"}
        with patch.dict(os.environ, env, clear=False):
            default = Stage13Settings.from_env()
            self.assertEqual((default.visitor_assistant_tasks, default.assistant_task_max_cny, default.assistant_project_token_limit), (3, 0.30, 3_000_000))
            with patch.dict(os.environ, {"VISITOR_ASSISTANT_TASKS_24H": "5", "ASSISTANT_TASK_MAX_CNY": "0.5", "ASSISTANT_PROJECT_TOKEN_LIMIT_24H": "9000"}):
                tuned = Stage13Settings.from_env()
                self.assertEqual((tuned.visitor_assistant_tasks, tuned.assistant_task_max_cny, tuned.assistant_project_token_limit), (5, 0.5, 9000))


class VisitorTests(AssistantCase):
    def test_a_visitor_asks_only_on_the_sample_work_three_times_apart_from_checks(self):
        self.start()
        self.visitor()
        usage = self.usage()
        self.assertEqual((usage["assistant_tasks_limit"], usage["assistant_tasks_remaining"], usage["checks_remaining"]), (3, 3, 3))
        other = self.client.post("/api/projects", headers=self.idem(), json={"title": "我的作品"}).json()["data"]["project"]["id"]
        error = self.ask(project_id=other, expect=403).json()["error"]
        self.assertEqual(error["code"], "assistant_visitor_sample_only")
        for _ in range(3):
            self.run_ask(read(9), cite(9))
        error = self.ask(expect=429).json()["error"]
        self.assertEqual(error["code"], "workflow_quota_exceeded")
        usage = self.usage()
        self.assertEqual((usage["assistant_tasks_remaining"], usage["checks_remaining"]), (0, 3))
        for number in range(3):  # the three checks are still all there
            self.stage13.reserve_workflow(self.user_id, self.project_id, "continuity", f"run-{number}")
        with self.assertRaises(Exception) as caught:
            self.stage13.reserve_workflow(self.user_id, self.project_id, "continuity", "run-3")
        self.assertEqual(caught.exception.code, "workflow_quota_exceeded")
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM v2_character_usage")[0]["n"], 0)  # visitors are not charged characters

    def test_assistant_tasks_do_not_use_up_a_visitors_checks_either(self):
        self.start()
        self.visitor()
        for number in range(3):
            self.stage13.reserve_workflow(self.user_id, self.project_id, "continuity", f"run-{number}")
        self.assertEqual(self.run_ask(read(9), cite(9))["status"], "completed")

    def test_the_visitor_limit_can_be_tuned(self):
        self.start(visitor_assistant_tasks=1)
        self.visitor()
        self.run_ask(read(9), cite(9))
        self.assertEqual(self.ask(expect=429).json()["error"]["code"], "workflow_quota_exceeded")


class CoverageTests(unittest.TestCase):
    def step(self, tool, args, error=None):
        return {"kind": "tool", "tool_name": tool, "args_json": json.dumps(args, ensure_ascii=False), "error_code": error}

    def test_coverage_is_worked_out_from_the_steps(self):
        scope = {"max_chapter": 10, "draft_readable": True}
        steps = [self.step("search_text", {"query": "罗盘", "chapter_from": 1, "chapter_to": 4}), self.step("search_text", {"query": "调包", "chapter_from": 3, "chapter_to": 10}),
                 self.step("search_text", {"query": "错误", "chapter_from": 1, "chapter_to": 10}, "invalid_arguments"),
                 self.step("read_chapter", {"chapter_number": 9}), self.step("read_chapter", {"chapter_number": 2}), self.step("lookup_facts", {"name": "苏岑"}),
                 self.step("get_plans", {}), self.step("get_issues", {})]
        coverage = build_coverage(steps, scope, False)
        self.assertEqual(coverage["checked"], ["第 1–10 章正文（搜过：罗盘、调包）", "读过第 2、9 章", "已确认事实：苏岑", "计划和伏笔记录", "本章检查结果"])
        self.assertEqual(coverage["not_checked"], ["本章草稿"])
        self.assertEqual(build_coverage([], scope, True), {"checked": [], "not_checked": ["正文", "已确认事实", "本章草稿", "计划", "步数或预算已到，没有查完"]})
        self.assertEqual(build_coverage([], {"max_chapter": 10, "draft_readable": False}, False)["not_checked"], ["正文", "已确认事实", "计划"])
        split = build_coverage([self.step("search_text", {"query": "a", "chapter_from": 1, "chapter_to": 2}), self.step("search_text", {"query": "b", "chapter_from": 5, "chapter_to": 5})], scope, False)
        self.assertEqual(split["checked"], ["第 1–2、5 章正文（搜过：a、b）"])
        # A check of a picked passage has looked at that part of the draft: only the rest of the draft is left unread.
        checked = build_coverage([self.step("check_passage", {"chapter_to": 10})], scope, False)
        self.assertEqual(checked["not_checked"], ["已确认事实", "本章草稿的其他部分", "计划"])


from app.assistant import build_coverage  # noqa: E402  (kept next to its test)

if __name__ == "__main__":
    unittest.main()
