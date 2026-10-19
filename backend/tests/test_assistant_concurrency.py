"""The assistant under real concurrency (v1.8.0, task 07b): a real SQLite file, several threads, and no "database is locked".

Each thread drives its own HTTP client; the test executor runs a task inside its request, so one request is one task
running on one thread while the others do their own work against the same database file.
"""
from __future__ import annotations

import itertools
import json
import threading
import time
import unittest
import uuid

from fastapi.testclient import TestClient

from app.provider import ChatResult

from tests.assistant_case import AssistantCase
from tests.scripted_chat import ScriptedChatProvider, answer_call, call, ref_of_chapter

ROUNDS = 4  # tool rounds before the answer; the last of them reads chapter 9, which the answer cites
CHAPTERS = (6, 7, 8, 9)
JOIN_SECONDS = 180


class StatelessChat(ScriptedChatProvider):
    """Decides from the conversation alone what to say next, so any number of tasks can share it from different threads."""

    def __init__(self, delay: float = 0.02):
        super().__init__()
        self.delay = delay
        self._counter = itertools.count(1)

    def chat(self, messages, tools, tool_choice, max_tokens):
        time.sleep(self.delay)  # long enough for the other threads to be in the middle of their own work
        done = sum(1 for message in messages if message["role"] == "assistant" and message.get("tool_calls"))
        if done < ROUNDS:
            calls = [call("search_text", query="罗盘"), call("read_chapter", chapter_number=CHAPTERS[done]), call("lookup_facts", name="温岚"), call("get_issues")]
        else:
            calls = [answer_call("answered", [("苏岑把罗盘交给了温岚。", [ref_of_chapter(messages, 9)])])]
        prepared = [{"id": f"call_{next(self._counter)}", "name": item["name"], "arguments": item["arguments"]} for item in calls]
        return ChatResult({"content": None, "tool_calls": prepared}, 100, 50, 0.01, "tool_calls", 5)


class ConcurrencyCase(AssistantCase):
    def setUp(self):
        self.start(provider=StatelessChat(), registered_workflows=1000, registered_check_chars=10_000_000, registered_provider_attempts=100_000)
        self.errors: list[BaseException] = []
        self.responses: list[str] = []

    def new_client(self) -> TestClient:
        client = TestClient(self.app)
        self.addCleanup(client.close)
        return client

    def new_author(self) -> tuple[TestClient, str]:
        client = self.new_client()
        data = client.post("/api/auth/register", headers=self.idem(), json={
            "account_name": f"cc{uuid.uuid4().hex[:8]}", "display_name": "Concurrent", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        return client, data["onboarding"]["tutorial"]["project_id"]

    def ask_in(self, client: TestClient, project_id: str) -> None:
        response = client.post(f"/api/projects/{project_id}/assistant/tasks", headers=self.idem(),
                               json={"kind": "ask", "question": "苏岑知道罗盘被调包了吗？", "context": {"page": "writing"}})
        self.responses.append(response.text)
        self.assertEqual(response.status_code, 202, response.text)

    def guarded(self, work, *args):
        def run():
            try:
                work(*args)
            except BaseException as error:  # reported on the main thread
                self.errors.append(error)
        return threading.Thread(target=run, daemon=True)

    def run_threads(self, *threads: threading.Thread) -> None:
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + JOIN_SECONDS
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        self.assertFalse([thread for thread in threads if thread.is_alive()], "a thread did not finish")
        self.assertEqual(self.errors, [])
        self.assertFalse([text for text in self.responses if "locked" in text.lower()])

    def assert_tasks_completed(self, expected: int) -> None:
        tasks = self.rows("SELECT status,error_code,internal_error_type,steps_used FROM assistant_tasks")
        self.assertEqual(len(tasks), expected)
        self.assertEqual([task for task in tasks if task["status"] != "completed"], [], "every task completes")
        self.assertEqual({task["internal_error_type"] for task in tasks}, {None})
        steps = self.rows("SELECT task_id,kind FROM assistant_steps")
        self.assertEqual(sum(1 for step in steps if step["kind"] == "tool"), expected * ROUNDS * 4)


class TwoWorksTests(ConcurrencyCase):
    def test_two_works_run_assistant_tasks_at_the_same_time(self):
        authors = [self.new_author(), self.new_author()]
        gate = threading.Barrier(len(authors))

        def work(client, project_id):
            gate.wait()
            for _ in range(3):
                self.ask_in(client, project_id)

        self.run_threads(*[self.guarded(work, client, project_id) for client, project_id in authors])
        self.assert_tasks_completed(6)
        self.assertEqual({row["project_id"] for row in self.rows("SELECT project_id FROM assistant_tasks")}, {project_id for _, project_id in authors})
        for _, project_id in authors:
            self.assertEqual(len(self.rows("SELECT * FROM assistant_tasks WHERE project_id=?", project_id)), 3)


class AssistantAndCheckTests(ConcurrencyCase):
    def test_an_assistant_task_and_a_whole_chapter_check_run_on_one_work_together(self):
        client, project_id = self.new_author()
        checker = self.new_client()
        checker.cookies.update(client.cookies)
        chapters = [row["id"] for row in self.rows("SELECT id FROM v2_chapters WHERE project_id=? AND chapter_number IN (2,9) ORDER BY chapter_number", project_id)]
        gate = threading.Barrier(2)
        runs_before = len(checker.get(f"/api/projects/{project_id}/chapter-checks").json()["data"]["runs"])

        def ask_repeatedly():
            gate.wait()
            for _ in range(3):
                self.ask_in(client, project_id)

        def check_repeatedly():
            gate.wait()
            for _ in range(3):
                response = checker.post(f"/api/projects/{project_id}/chapter-checks", headers=self.idem(), json={"chapter_ids": chapters})
                self.responses.append(response.text)
                self.assertEqual(response.status_code, 202, response.text)

        self.run_threads(self.guarded(ask_repeatedly), self.guarded(check_repeatedly))
        self.assert_tasks_completed(3)
        runs = checker.get(f"/api/projects/{project_id}/chapter-checks").json()["data"]["runs"]
        self.assertEqual([run["status"] for run in runs], ["completed"] * (runs_before + 3))
        self.assertTrue(self.provider.reviews, "the checks really reached the reviewer")


class ReadWhileWritingTests(ConcurrencyCase):
    def test_a_check_result_with_several_evidence_is_read_while_another_connection_writes(self):
        client, project_id = self.new_author()
        issue_id = self.rows("SELECT i.id FROM v2_issues i JOIN v2_runs r ON r.id=i.run_id WHERE i.project_id=? AND r.run_type='continuity' ORDER BY i.rowid", project_id)[0]["id"]
        with self.db.connection() as c:  # an issue with three pieces of evidence, as the locking bug needed
            for suffix in ("second", "third"):
                c.execute("INSERT INTO v2_evidence(id,project_id,issue_id,chapter_id,span_id,excerpt,relation,sufficiency,related_memory_ids_json,source_revision) "
                          "SELECT id||'-'||?,project_id,issue_id,chapter_id,span_id,excerpt,relation,sufficiency,related_memory_ids_json,source_revision "
                          "FROM v2_evidence WHERE issue_id=? LIMIT 1", (suffix, issue_id))
            c.execute("CREATE TABLE IF NOT EXISTS concurrency_scratch(n INTEGER)")
        self.assertGreaterEqual(self.rows("SELECT COUNT(*) n FROM v2_evidence WHERE issue_id=?", issue_id)[0]["n"], 3)
        stop = threading.Event()
        writes = []

        def write_meanwhile():
            while not stop.is_set():
                with self.db.connection() as c:  # holds the database's write lock for a moment, over and over
                    c.execute("BEGIN IMMEDIATE")
                    c.execute("INSERT INTO concurrency_scratch VALUES(?)", (len(writes),))
                    time.sleep(0.01)
                writes.append(1)
                time.sleep(0.002)

        def ask_repeatedly():
            try:
                for _ in range(4):
                    self.ask_in(client, project_id)
            finally:
                stop.set()

        self.run_threads(self.guarded(write_meanwhile), self.guarded(ask_repeatedly))
        self.assertGreater(len(writes), 3, "the other connection really was writing")
        self.assert_tasks_completed(4)
        reads = self.rows("SELECT result_count,refs_json FROM assistant_steps WHERE tool_name='get_issues'")
        self.assertEqual(len(reads), 4 * ROUNDS)
        # Every read of the result brought back the issue and its (at least three) pieces of evidence.
        self.assertTrue(all(row["result_count"] and len(json.loads(row["refs_json"])) >= 4 for row in reads), reads[:2])


if __name__ == "__main__":
    unittest.main()
