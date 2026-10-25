"""v2.1 B long tasks (design 14): a plan the author approves, steps a runner takes in the background with its lease, a pause
to ask, a report and a card decided a group at a time. A scripted model; a runner killed mid-step and taken up again."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from app import long_tasks as lt

from tests.scripted_chat import call, turn
from tests.test_v200_changes import ChangeCase


class Crash(BaseException):
    """The runner's process dies: nothing in the runner catches it, its lease stays."""


def step_view(messages):
    """What a step showed the model: the threads by title (ref) and the passages by chapter (refs, in reading order)."""
    user = messages[1]["content"]
    threads = {title: ref for ref, title in re.findall(r"\[(R\d+)\] 伏笔：([^（]+)（", user)}
    chapters, current = {}, None
    for line in user.splitlines():
        heading = re.match(r"## 第 (\d+) 章", line)
        if heading:
            current = int(heading.group(1))
            continue
        passage = re.match(r"\[(R\d+)\] ", line)
        if passage and current is not None:
            chapters.setdefault(current, []).append(passage.group(1))
    return threads, chapters


def report(*items):
    return turn(call("report_threads", threads=list(items)))


class LongCase(ChangeCase):
    def setUp(self):
        super().setUp()
        self.long = self.app.state.long_tasks
        self.second = self.new_thread("旧尺零点", planted=3)

    def plan(self, kind="thread_audit", chapters=None):
        self.provider.script_route({"type": kind, "target": None, "chapters": chapters, "output": "list"})

    def create(self, question="那些还吊着的伏笔都替我过一遍", expect=202):
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/long-tasks", headers=self.idem(),
                             json={"question": question, "context": {"page": "materials"}})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()["data"] if expect == 202 else r.json()

    def view(self, task_id):
        r = self.client.get(f"/api/projects/{self.project_id}/assistant/long-tasks/{task_id}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["data"]

    def post(self, task_id, action, body=None, expect=None):
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/long-tasks/{task_id}/{action}", headers=self.idem(), json=body or {})
        if expect is not None:
            self.assertEqual(r.status_code, expect, r.text)
        return r

    def audit_turns(self, resolve_in=10, abandon=False):
        """A model that finds 罗盘下落 resolved in chapter `resolve_in` (and 旧尺零点 given up there with `abandon`), the rest open."""
        def decide(provider, messages):
            threads, chapters = step_view(messages)
            items = []
            if resolve_in in chapters and "罗盘下落" in threads:
                items.append({"thread": threads["罗盘下落"], "verdict": "resolved", "refs": [chapters[resolve_in][0]], "note": "这一章交代了罗盘的下落。"})
            if abandon and resolve_in in chapters and "旧尺零点" in threads:
                items.append({"thread": threads["旧尺零点"], "verdict": "abandoned", "refs": [chapters[resolve_in][-1]], "note": "写明不再追查零点。"})
            return report(*items)
        return decide

    def started(self, chapters=None, cap=None, turns=None):
        self.plan(chapters=chapters)
        task = self.create()
        if cap is not None:
            self.post(task["id"], "plan", {"cap_cny": cap}, expect=200)
        self.provider.script(*(turns or [self.audit_turns()] * 2))
        self.post(task["id"], "start", expect=202)
        return self.view(task["id"])


class PlanTests(LongCase):
    def test_a_plan_is_made_from_the_sentence_and_waits_for_the_author(self):
        self.plan()
        task = self.create()
        view = self.view(task["id"])
        self.assertEqual((view["kind"], view["status"]), ("long", "awaiting_plan"))
        proposed = view["plan"]["proposed"]
        self.assertEqual([step.get("chapters") for step in proposed["steps"]], [[1, 5], [6, 10], None])
        self.assertEqual(proposed["produces"], ["abandon_thread", "resolve_thread"])
        self.assertGreater(view["plan"]["est_chars"], 0)
        self.assertEqual(self.provider.route_calls[0]["messages"][1]["content"], "作者的话：那些还吊着的伏笔都替我过一遍")
        self.assertEqual(self.provider.calls, [])  # nothing of the manuscript is read before the author starts

    def test_the_author_narrows_the_chapters_and_sets_the_ceiling(self):
        self.plan()
        task = self.create()
        view = self.post(task["id"], "plan", {"chapters": [6, 10], "cap_cny": 9}, expect=200).json()["data"]
        self.assertEqual([step.get("chapters") for step in view["plan"]["proposed"]["steps"]], [[6, 10], None])
        self.assertEqual(view["plan"]["cap_cny"], lt.CAP_MAX)
        self.post(task["id"], "plan", {"chapters": [0, 40]}, expect=422)

    def test_a_kind_not_done_yet_ends_with_a_line_and_reads_nothing(self):
        self.plan(kind="none")
        view = self.view(self.create("帮我把第三卷重写一遍")["id"])
        self.assertEqual(view["status"], "completed")
        self.assertIn("现在还做不了", view["answer"]["note"])

    def test_a_visitor_has_no_long_tasks_and_an_author_one_at_a_time(self):
        self.plan()
        self.create()
        self.assertEqual(self.create(expect=409)["error"]["code"], "assistant_long_task_active")
        self.visitor()
        self.assertEqual(self.create(expect=403)["error"]["code"], "assistant_long_visitor_forbidden")


class RunTests(LongCase):
    def test_the_steps_read_their_chapters_and_the_card_and_report_come_out(self):
        view = self.started()
        self.assertEqual(view["status"], "completed", view)
        self.assertEqual([step["status"] for step in view["long_steps"]], ["done", "done", "done"])
        first, second = (self.provider.calls[0]["messages"][1]["content"], self.provider.calls[1]["messages"][1]["content"])
        self.assertIn("## 第 5 章", first)
        self.assertNotIn("## 第 6 章", first)
        self.assertIn("## 第 10 章", second)
        self.assertNotIn("## 第 5 章", second)
        self.assertIn("罗盘下落", first)
        [item] = view["changes"]
        self.assertEqual((item["kind"], item["title"], item["after"], item["status"]), ("resolve_thread", "罗盘下落", "已回收（第 10 章）", "proposed"))
        sections = view["answer"]["sections"]
        self.assertEqual([s["label"] for s in sections["已经收了"]], ["罗盘下落"])
        self.assertIn("旧尺零点", [s["label"] for s in sections["还开着"]])
        self.assertEqual(self.thread()["status"], "planted")  # nothing is written before the author confirms
        calls = self.rows("SELECT step,attempt,seq,role FROM assistant_long_calls WHERE task_id=? ORDER BY step,attempt,seq", view["id"])
        self.assertEqual([(c["step"], c["role"]) for c in calls], [(0, "plan"), (1, "loop"), (2, "loop")])
        cost = self.rows("SELECT cost_cny FROM assistant_tasks WHERE id=?", view["id"])[0]["cost_cny"]
        self.assertAlmostEqual(cost, sum(r["cost_cny"] for r in self.rows("SELECT cost_cny FROM assistant_long_calls WHERE task_id=?", view["id"])))

    def test_only_the_narrowed_chapters_are_read(self):
        self.plan()
        task = self.create()
        self.post(task["id"], "plan", {"chapters": [6, 10]}, expect=200)
        self.provider.script(self.audit_turns())
        self.post(task["id"], "start", expect=202)
        [only] = self.provider.calls
        self.assertNotIn("## 第 5 章", only["messages"][1]["content"])
        self.assertEqual(self.view(task["id"])["status"], "completed")

    def test_a_report_citing_outside_its_step_is_sent_back_once(self):
        def outside(provider, messages):
            threads, _ = step_view(messages)
            return report({"thread": threads["罗盘下落"], "verdict": "resolved", "refs": ["R999"], "note": "x"})
        view = self.started(turns=[self.audit_turns(), outside, self.audit_turns()])
        self.assertEqual(view["status"], "completed")
        self.assertIn("report_invalid", self.provider.calls[2]["messages"][-1]["content"])
        self.assertEqual(len(view["changes"]), 1)

    def test_a_report_that_will_not_validate_fails_the_task_and_gives_the_characters_back(self):
        def bad(provider, messages):
            return report({"thread": "R999", "verdict": "resolved", "refs": [], "note": "x"})
        self.own_work()
        view = self.started(turns=[bad, bad])
        self.assertEqual((view["status"], view["error_code"]), ("failed", "assistant_long_report_invalid"))
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM v2_character_usage WHERE id LIKE ?", f"chars-{self.reservation(view)}%")[0]["n"], 0)

    def reservation(self, view):
        return self.rows("SELECT reservation_id FROM assistant_tasks WHERE id=?", view["id"])[0]["reservation_id"]


class ResumeTests(LongCase):
    def test_a_runner_that_dies_mid_step_is_taken_up_when_its_lease_runs_out(self):
        self.plan()
        task = self.create()
        user = self.user_id
        self.long.start(user, self.project_id, task["id"])

        def bad_then_crash(provider, messages):
            threads, _ = step_view(messages)
            return report({"thread": threads["罗盘下落"], "verdict": "resolved", "refs": ["R999"]})
        self.provider.script(self.audit_turns(), bad_then_crash, Crash())
        with self.assertRaises(Crash):
            self.long.run(task["id"])
        step = self.rows("SELECT * FROM assistant_long_steps WHERE task_id=? AND ordinal=2", task["id"])[0]
        self.assertEqual((step["status"], step["attempt"]), ("running", 1))
        self.assertEqual(self.view(task["id"])["status"], "long_running")
        self.assertEqual(self.long.sweep(), [])  # the lease still holds

        self.provider.script(self.audit_turns())
        self.long.owner = "runner-after-restart"
        later = datetime.now(timezone.utc) + timedelta(seconds=lt.LEASE_SECONDS + 5)
        self.long.clock = lambda: later
        self.assertEqual(self.long.sweep(), [task["id"]])
        view = self.view(task["id"])
        self.assertEqual(view["status"], "completed")
        step = self.rows("SELECT * FROM assistant_long_steps WHERE task_id=? AND ordinal=2", task["id"])[0]
        self.assertEqual((step["status"], step["attempt"]), ("done", 2))
        self.assertEqual(len(view["changes"]), 1)  # step 2's card written once
        self.assertTrue(all("## 第 1 章" not in c["messages"][1]["content"] for c in self.provider.calls))  # step 1 not done again
        calls =self.rows("SELECT step,attempt,seq FROM assistant_long_calls WHERE task_id=? ORDER BY step,attempt,seq", task["id"])
        self.assertEqual([(c["step"], c["attempt"]) for c in calls], [(0, 0), (1, 1), (2, 1), (2, 2)])  # each call booked once
        cost = self.rows("SELECT cost_cny FROM assistant_tasks WHERE id=?", task["id"])[0]["cost_cny"]
        self.assertAlmostEqual(cost, 0.0002 + 3 * 0.01)

    def test_a_broken_record_fails_the_task_rather_than_be_patched(self):
        self.plan()
        task = self.create()
        self.long.start(self.user_id, self.project_id, task["id"])
        self.provider.script(self.audit_turns(resolve_in=3), Crash())
        with self.assertRaises(Crash):
            self.long.run(task["id"])
        with self.db.connection() as c:
            c.execute("DELETE FROM assistant_changes WHERE task_id=?", (task["id"],))
        self.long.clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=lt.LEASE_SECONDS + 5)
        self.long.owner = "another"
        self.long.sweep()
        view = self.view(task["id"])
        self.assertEqual((view["status"], view["error_code"]), ("failed", "assistant_long_record_broken"))


class AskTests(LongCase):
    def costly(self, resolve_in=10):
        decide = self.audit_turns(resolve_in)

        def step(provider, messages):
            return {**decide(provider, messages), "cost": 0.6}
        return step

    def test_at_the_ceiling_the_task_asks_and_goes_on_with_a_higher_one(self):
        view = self.started(cap=0.5, turns=[self.costly()])
        self.assertEqual(view["status"], "waiting_author")
        [question] = view["questions"]
        self.assertEqual((question["kind"], question["choices"]), ("budget", ["continue", "stop"]))
        self.assertEqual(view["progress"]["done"], 1)
        self.post(view["id"], "answer", {"question_id": question["id"], "choice": "continue", "cap_cny": 0.4}, expect=422)
        self.provider.script(self.audit_turns())
        self.post(view["id"], "answer", {"question_id": question["id"], "choice": "continue", "cap_cny": 2}, expect=202)
        view = self.view(view["id"])
        self.assertEqual((view["status"], view["plan"]["cap_cny"]), ("completed", 2))
        self.assertEqual(len(view["changes"]), 1)

    def test_stop_at_the_ceiling_hands_over_what_is_done_and_gives_back_what_was_not_read(self):
        self.own_work()
        view = self.started(cap=0.5, turns=[self.costly(resolve_in=3)])
        [question] = view["questions"]
        planned = view["plan"]["est_chars"]
        self.post(view["id"], "answer", {"question_id": question["id"], "choice": "stop"}, expect=202)
        view = self.view(view["id"])
        self.assertEqual(view["status"], "stopped")
        self.assertIn("中途停下了", view["answer"]["note"])
        self.assertEqual([s["label"] for s in view["answer"]["sections"]["已经收了"]], ["罗盘下落"])
        read = self.rows("SELECT characters FROM v2_character_usage WHERE id=?", f"chars-{self.reservation(view)}-read")[0]["characters"]
        self.assertEqual(read, view["plan"]["chars_read"])
        self.assertLess(read, planned)

    def test_stop_while_it_waits_ends_it(self):
        view = self.started(cap=0.5, turns=[self.costly()])
        self.post(view["id"], "stop", expect=200)
        self.assertEqual(self.view(view["id"])["status"], "stopped")

    def reservation(self, view):
        return self.rows("SELECT reservation_id FROM assistant_tasks WHERE id=?", view["id"])[0]["reservation_id"]


class CardTests(LongCase):
    def test_a_group_is_confirmed_on_its_own_and_a_give_up_alone(self):
        view = self.started(turns=[self.audit_turns(abandon=True)] * 2)
        by_kind = {item["kind"]: item for item in view["changes"]}
        self.assertEqual(set(by_kind), {"resolve_thread", "abandon_thread"})
        everything = [item["id"] for item in view["changes"]]
        r = self.post(view["id"], "changes/confirm", {"accepted": everything, "within": everything}, expect=422)
        self.assertEqual(r.json()["error"]["code"], "assistant_long_confirm_alone")
        resolve = [by_kind["resolve_thread"]["id"]]
        view = self.post(view["id"], "changes/confirm", {"accepted": resolve, "within": resolve}, expect=200).json()["data"]
        states = {item["kind"]: item["status"] for item in view["changes"]}
        self.assertEqual(states, {"resolve_thread": "applied", "abandon_thread": "proposed"})  # the other group waits
        self.assertEqual(self.thread()["status"], "resolved")
        give_up = [by_kind["abandon_thread"]["id"]]
        self.post(view["id"], "changes/confirm", {"accepted": give_up, "within": give_up}, expect=200)
        self.assertEqual(self.thread(self.second)["status"], "abandoned")

    def test_a_short_task_card_cannot_be_decided_by_group(self):
        task = self.change_task(*self.resolving())
        r = self.client.post(f"/api/projects/{self.project_id}/assistant/long-tasks/{task['id']}/changes/confirm", headers=self.idem(),
                             json={"accepted": [task["changes"][0]["id"]], "within": [task["changes"][0]["id"]]})
        self.assertEqual(r.status_code, 404, r.text)


class ChargeTests(LongCase):
    def test_starting_spends_what_the_plan_reads_and_a_quota_too_small_refuses_there(self):
        self.own_work()
        self.plan()
        task = self.create()
        view = self.view(task["id"])
        planned = view["plan"]["est_chars"]
        self.assertEqual(view["usage"]["chars_charged"], 500)  # the plan is charged like a question
        with self.db.connection() as c:  # the day's other checks leave one character short of the plan
            c.execute("INSERT INTO v2_character_usage VALUES(?,?,?,?,?,?,?)",
                      ("chars-filler", self.user_id, self.project_id, None, "check", self.settings.registered_check_chars - 500 - planned + 1,
                       datetime.now(timezone.utc).isoformat()))
        r = self.post(task["id"], "start", expect=429)
        self.assertEqual(r.json()["error"]["code"], "character_quota_exceeded")
        self.assertEqual(self.view(task["id"])["status"], "awaiting_plan")  # nothing started, the author may narrow it
        with self.db.connection() as c:
            c.execute("UPDATE v2_character_usage SET characters=characters-1 WHERE id='chars-filler'")
        self.provider.script(self.audit_turns(), self.audit_turns())
        self.post(task["id"], "start", expect=202)
        view = self.view(task["id"])
        self.assertEqual((view["status"], view["usage"]["chars_charged"]), ("completed", 500 + planned))
