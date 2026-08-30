from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult, ProviderTimeout


def idem(value: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class LifecycleProvider:
    label = "stage12-injected-provider"
    model_label = "stage12-injected-model"

    def __init__(self):
        self.calls = 0
        self.mode = "success"
        self.entered = threading.Event()
        self.release = threading.Event()

    @property
    def available(self):
        return True

    def evaluate(self, request):
        self.calls += 1
        task = request.get("task")
        if task == "memory_initialization":
            source = request["sources"][0]
            return ProviderResult({"candidates": [{"memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": "在雾港", "chapter_id": source["chapter_id"], "source_span_id": source["id"]}]})
        if self.mode == "blocking":
            self.entered.set()
            if not self.release.wait(5):
                raise AssertionError("test provider release was not signalled")
        if self.mode == "timeout":
            raise ProviderTimeout()
        if task == "memory_delta":
            source = request["sources"][0]
            return ProviderResult({"candidates": [{"memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": "已离开雾港", "chapter_id": source["chapter_id"], "source_span_id": source["id"]}]}, input_tokens=7, output_tokens=3, latency_ms=4)
        return ProviderResult({"issues": []}, input_tokens=11, output_tokens=5, latency_ms=6)


class CapturingExecutor:
    def __init__(self):
        self.tasks = []

    def __call__(self, function, *args):
        self.tasks.append((function, args))

    def run_next(self):
        function, args = self.tasks.pop(0)
        function(*args)


class Stage12RunLifecycleTests(unittest.TestCase):
    BUSINESS_TABLES = (
        "v2_issues",
        "v2_evidence",
        "v2_decisions",
        "v2_change_sets",
        "v2_change_set_items",
        "v2_memory_delta_candidates",
        "v2_memory_delta_decisions",
        "v2_memory_candidates",
        "v2_memory_candidate_decisions",
        "v2_memory_records",
        "v2_source_coverage_audits",
        "v2_memory_versions",
        "v2_commit_audits",
    )

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="scc-stage12-"))
        self.provider = LifecycleProvider()
        self.executor = CapturingExecutor()
        self.app = create_app(AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected"), provider=self.provider, executor=self.executor)
        self.client = TestClient(self.app)
        registered = self.client.post("/api/auth/register", json={"account_name": "lifecycle-author", "display_name": "Lifecycle", "password": "safe-password-123"}, headers=idem()).json()["data"]
        self.project = registered["seeded_projects"][0]["id"]
        self.other_project = registered["seeded_projects"][1]["id"]
        self.draft = self.client.get(f"/api/projects/{self.project}").json()["data"]["current_draft"]

    def counts(self):
        with self.app.state.database.connection() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (self.project,)).fetchone()[0] for table in self.BUSINESS_TABLES}

    def emit_counts(self, scenario, before, after):
        if os.environ.get("STAGE12_EVIDENCE") == "1":
            print(
                "STAGE12_COUNTS "
                + json.dumps(
                    {"scenario": scenario, "before": before, "after": after},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

    def create_run(self):
        response = self.client.post(f"/api/projects/{self.project}/checks", json={"draft_id": self.draft["id"], "draft_revision": self.draft["revision"]}, headers=idem())
        self.assertEqual(response.status_code, 202)
        return response.json()["data"]["run_id"]

    def view(self, run_id):
        return self.client.get(f"/api/projects/{self.project}/checks/{run_id}?include=issues,evidence,metrics").json()["data"]

    def test_state_events_metrics_and_terminal_cas_are_auditable(self):
        run_id = self.create_run()
        queued = self.view(run_id)
        self.assertEqual((queued["status"], queued["stage"], queued["started_at"], queued["duration_ms"]), ("queued", "queued", None, None))
        self.assertEqual([(event["sequence"], event["status"], event["stage"]) for event in queued["transitions"]], [(1, "queued", "queued")])
        self.executor.run_next()
        completed = self.view(run_id)
        self.assertEqual((completed["status"], completed["stage"], completed["attempt_number"], completed["root_run_id"]), ("completed", "completed", 1, run_id))
        self.assertIsNotNone(completed["started_at"])
        self.assertIsNotNone(completed["completed_at"])
        self.assertGreaterEqual(completed["duration_ms"], 0)
        self.assertEqual(completed["provider_metrics"], {"latency_ms": 6, "input_tokens": 11, "output_tokens": 5, "cost_cny": None, "cost_available": False})
        self.assertEqual([event["sequence"] for event in completed["transitions"]], list(range(1, len(completed["transitions"]) + 1)))
        self.assertFalse(self.app.state.database.finish_run(self.project, run_id, {"status": "failed", "error_code": "internal_run_error", "retryable": True}))
        self.assertFalse(self.app.state.database.advance_run(self.project, run_id, "late_worker"))
        self.assertEqual(self.view(run_id)["status"], "completed")

    def test_concurrent_terminal_compare_and_set_has_exactly_one_winner(self):
        run_id = self.create_run()
        barrier = threading.Barrier(3)
        outcomes = []

        def finish(result):
            barrier.wait()
            outcomes.append(
                self.app.state.database.finish_run(self.project, run_id, result)
            )

        workers = [
            threading.Thread(
                target=finish,
                args=({"status": "completed", "issues": []},),
            ),
            threading.Thread(
                target=finish,
                args=(
                    {
                        "status": "timed_out",
                        "error_code": "provider_timeout",
                        "retryable": True,
                    },
                ),
            ),
        ]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sorted(outcomes), [False, True])
        viewed = self.view(run_id)
        self.assertIn(viewed["status"], {"completed", "timed_out"})
        terminal_events = [
            event
            for event in viewed["transitions"]
            if event["status"] in {"completed", "failed", "timed_out", "cancelled"}
        ]
        self.assertEqual(len(terminal_events), 1)

    def test_frozen_transition_table_and_budget_compatibility(self):
        before = self.counts()
        cases = (
            ({"status": "failed", "error_code": "schema_invalid", "retryable": True}, "failed", "schema_invalid"),
            ({"status": "timed_out", "error_code": "provider_timeout", "retryable": True}, "timed_out", "provider_timeout"),
            ({"status": "budget_paused", "error_code": "budget_paused", "retryable": True}, "failed", "budget_guard_exceeded"),
        )
        for result, expected_status, expected_error in cases:
            run_id = self.create_run()
            self.assertTrue(self.app.state.database.finish_run(self.project, run_id, result))
            viewed = self.view(run_id)
            self.assertEqual((viewed["status"], viewed["stage"], viewed["error_code"]), (expected_status, expected_status, expected_error))
            self.assertFalse(self.app.state.database.finish_run(self.project, run_id, {"status": "completed", "issues": []}))
            self.assertEqual(self.view(run_id)["status"], expected_status)
        self.emit_counts("failed_timed_out_budget_compatibility", before, self.counts())

    def test_queued_cancel_csrf_idempotency_isolation_and_zero_business_delta(self):
        before = self.counts()
        run_id = self.create_run()
        key = str(uuid.uuid4())
        body = {"client_request_id": "cancel-1"}
        first = self.client.post(f"/api/projects/{self.project}/checks/{run_id}/cancel", json=body, headers=idem(key))
        replay = self.client.post(f"/api/projects/{self.project}/checks/{run_id}/cancel", json=body, headers=idem(key))
        conflict = self.client.post(f"/api/projects/{self.project}/checks/{run_id}/cancel", json={"client_request_id": "cancel-2"}, headers=idem(key))
        self.assertEqual((first.status_code, replay.status_code, conflict.status_code), (200, 200, 409))
        self.assertEqual(first.json()["data"], replay.json()["data"])
        self.assertEqual((self.view(run_id)["status"], self.provider.calls, self.counts()), ("cancelled", 0, before))
        self.emit_counts("queued_cancel", before, self.counts())
        self.assertEqual(self.client.post(f"/api/projects/{self.project}/checks/{run_id}/cancel", json={}, headers=idem()).status_code, 409)
        self.assertEqual(self.client.post(f"/api/projects/{self.project}/checks/{run_id}/retry", json={}, headers={**idem(), "Origin": "https://evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/projects/{self.other_project}/checks/{run_id}/retry", json={}, headers=idem()).status_code, 404)
        outsider = TestClient(self.app)
        outsider.post("/api/auth/register", json={"account_name": "other-lifecycle", "display_name": "Other", "password": "safe-password-123"}, headers=idem())
        self.assertEqual(outsider.post(f"/api/projects/{self.project}/checks/{run_id}/retry", json={}, headers=idem()).status_code, 404)

    def test_running_cancel_discards_late_provider_success(self):
        before = self.counts()
        run_id = self.create_run()
        self.provider.mode = "blocking"
        worker = threading.Thread(target=self.executor.run_next)
        worker.start()
        self.assertTrue(self.provider.entered.wait(3))
        cancelled = self.client.post(f"/api/projects/{self.project}/checks/{run_id}/cancel", json={}, headers=idem())
        self.assertEqual((cancelled.status_code, cancelled.json()["data"]["stage"]), (200, "cancelling"))
        self.provider.release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        terminal = self.view(run_id)
        self.assertEqual((terminal["status"], terminal["stage"], terminal["error_code"], self.provider.calls), ("cancelled", "cancelled", "author_cancelled", 1))
        self.assertEqual(terminal.get("issues", []), [])
        self.assertEqual(self.counts(), before)
        self.emit_counts("running_cancel_late_success", before, self.counts())

    def test_timeout_retry_idempotency_unfinished_zero_writes_and_stale_lineage(self):
        before = self.counts()
        run_id = self.create_run()
        self.provider.mode = "timeout"
        self.executor.run_next()
        old = self.view(run_id)
        self.assertEqual((old["status"], old["error_code"], self.counts()), ("timed_out", "provider_timeout", before))
        self.emit_counts("timeout", before, self.counts())
        key = str(uuid.uuid4())
        body = {"client_request_id": "retry-1"}
        first = self.client.post(f"/api/projects/{self.project}/checks/{run_id}/retry", json=body, headers=idem(key))
        replay = self.client.post(f"/api/projects/{self.project}/checks/{run_id}/retry", json=body, headers=idem(key))
        conflict = self.client.post(f"/api/projects/{self.project}/checks/{run_id}/retry", json={"client_request_id": "retry-2"}, headers=idem(key))
        self.assertEqual((first.status_code, replay.status_code, conflict.status_code), (202, 202, 409))
        new_run = first.json()["data"]["run"]
        self.assertNotEqual(new_run["run_id"], run_id)
        self.assertEqual((new_run["retry_of_run_id"], new_run["root_run_id"], new_run["attempt_number"]), (run_id, run_id, 2))
        self.assertEqual((self.view(run_id)["status"], self.view(new_run["run_id"])["status"], self.counts()), ("timed_out", "queued", before))
        self.emit_counts("unfinished_retry", before, self.counts())
        self.executor.tasks.clear()
        self.client.patch(f"/api/projects/{self.project}/drafts/{self.draft['id']}", json={"base_revision": self.draft["revision"], "body": "谱系已变化。"}, headers=idem())
        stale = self.client.post(f"/api/projects/{self.project}/checks/{run_id}/retry", json={"client_request_id": "stale"}, headers=idem())
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (409, "run_retry_lineage_stale"))

    def prepare_incremental(self):
        preview = self.client.post("/api/imports/preview", files={"file": ("base.md", "# 第一章\n林默在雾港。".encode(), "text/markdown")}, headers=idem()).json()["data"]
        project = self.client.post(f"/api/imports/{preview['import_id']}/commit", json={"confirm": True, "title": "Incremental", "chapter_preview_ids": [item["preview_id"] for item in preview["detected"]["chapters"]]}, headers=idem()).json()["data"]["project"]["id"]
        initialization = self.client.post(f"/api/projects/{project}/memory/initializations", json={"source_revision": 1}, headers=idem()).json()["data"]["initialization"]
        core = next(item for item in initialization["candidates"] if item["review_priority"] == "core")
        self.client.post(f"/api/projects/{project}/memory/initializations/{initialization['id']}/candidates/{core['id']}/decision", json={"decision": "accepted"}, headers=idem())
        self.client.post(f"/api/projects/{project}/memory/initializations/{initialization['id']}/commit", json={"confirm": True}, headers=idem())
        change = self.client.post(f"/api/projects/{project}/source-change-sets/preview", json={"mode": "append", "input_method": "paste", "base_source_revision": 1, "content": "# 第二章\n林默已离开雾港。"}, headers=idem()).json()["data"]["source_change_set"]
        self.client.post(f"/api/projects/{project}/source-change-sets/{change['id']}/commit", json={"confirm": True, "content_sha256": change["content_sha256"]}, headers=idem())
        return project, change["id"]

    def test_incremental_pair_cancel_and_retry_preserve_source_and_memory_lineage(self):
        project, change_id = self.prepare_incremental()
        calls_before = self.provider.calls
        started = self.client.post(f"/api/projects/{project}/incremental-reviews", json={"source_revision": 2}, headers=idem()).json()["data"]
        continuity_id, delta_id = started["continuity_run_id"], started["memory_delta_run_id"]
        cancelled = self.client.post(f"/api/projects/{project}/checks/{delta_id}/cancel", json={}, headers=idem())
        self.assertEqual(cancelled.status_code, 200)
        for run_id in (continuity_id, delta_id):
            self.assertEqual(self.client.get(f"/api/projects/{project}/checks/{run_id}").json()["data"]["status"], "cancelled")
        with self.app.state.database.connection() as connection:
            before = {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in self.BUSINESS_TABLES}
            source_changes = connection.execute("SELECT COUNT(*) FROM v2_source_change_sets WHERE project_id=?", (project,)).fetchone()[0]
            memory_versions = connection.execute("SELECT COUNT(*) FROM v2_memory_versions WHERE project_id=?", (project,)).fetchone()[0]
        retried = self.client.post(f"/api/projects/{project}/checks/{continuity_id}/retry", json={}, headers=idem())
        self.assertEqual(retried.status_code, 202)
        data = retried.json()["data"]
        self.assertTrue(data["paired"])
        self.assertNotEqual((data["continuity_run_id"], data["memory_delta_run_id"]), (continuity_id, delta_id))
        for item in data["runs"]:
            self.assertEqual((item["attempt_number"], item["status"]), (2, "queued"))
        with self.app.state.database.connection() as connection:
            after = {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in self.BUSINESS_TABLES}
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_source_change_sets WHERE project_id=?", (project,)).fetchone()[0], source_changes)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_memory_versions WHERE project_id=?", (project,)).fetchone()[0], memory_versions)
            self.assertEqual({row[0] for row in connection.execute("SELECT DISTINCT source_change_set_id FROM v2_runs WHERE incremental_batch_id=?", (data["batch_id"],)).fetchall()}, {change_id})
        self.assertEqual((after, self.provider.calls), (before, calls_before))
        self.emit_counts("paired_queued_cancel_and_unfinished_retry", before, after)

    def test_incremental_pair_timeout_is_atomic_and_successful_retry_is_paired(self):
        project, _ = self.prepare_incremental()
        started = self.client.post(
            f"/api/projects/{project}/incremental-reviews",
            json={"source_revision": 2},
            headers=idem(),
        ).json()["data"]
        with self.app.state.database.connection() as connection:
            before = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)
                ).fetchone()[0]
                for table in self.BUSINESS_TABLES
            }
        self.provider.mode = "timeout"
        self.executor.run_next()
        for run_id in (
            started["continuity_run_id"],
            started["memory_delta_run_id"],
        ):
            viewed = self.client.get(
                f"/api/projects/{project}/checks/{run_id}?include=issues,evidence,metrics"
            ).json()["data"]
            self.assertEqual((viewed["status"], viewed.get("issues", [])), ("timed_out", []))
        with self.app.state.database.connection() as connection:
            failed_counts = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)
                ).fetchone()[0]
                for table in self.BUSINESS_TABLES
            }
        self.assertEqual(failed_counts, before)
        self.emit_counts("paired_timeout", before, failed_counts)

        self.provider.mode = "success"
        retried = self.client.post(
            f"/api/projects/{project}/checks/{started['memory_delta_run_id']}/retry",
            json={"client_request_id": "paired-timeout-retry"},
            headers=idem(),
        ).json()["data"]
        self.assertTrue(retried["paired"])
        self.assertEqual(
            {(item["run_type"], item["attempt_number"]) for item in retried["runs"]},
            {("continuity", 2), ("memory_delta", 2)},
        )
        self.executor.run_next()
        for run_id in (
            retried["continuity_run_id"],
            retried["memory_delta_run_id"],
        ):
            self.assertEqual(
                self.client.get(f"/api/projects/{project}/checks/{run_id}").json()[
                    "data"
                ]["status"],
                "completed",
            )
        delta = self.client.get(f"/api/projects/{project}/memory/delta").json()["data"]
        self.assertEqual(delta["status"], "in_review")
        self.assertGreater(len(delta["candidates"]), 0)

    def test_running_incremental_cancel_discards_late_pair_results(self):
        project, _ = self.prepare_incremental()
        started = self.client.post(
            f"/api/projects/{project}/incremental-reviews",
            json={"source_revision": 2},
            headers=idem(),
        ).json()["data"]
        with self.app.state.database.connection() as connection:
            before = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)
                ).fetchone()[0]
                for table in self.BUSINESS_TABLES
            }
        self.provider.mode = "blocking"
        worker = threading.Thread(target=self.executor.run_next)
        worker.start()
        self.assertTrue(self.provider.entered.wait(3))
        cancelled = self.client.post(
            f"/api/projects/{project}/checks/{started['continuity_run_id']}/cancel",
            json={"client_request_id": "cancel-running-pair"},
            headers=idem(),
        )
        self.assertEqual(cancelled.status_code, 200)
        self.provider.release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        for run_id in (
            started["continuity_run_id"],
            started["memory_delta_run_id"],
        ):
            viewed = self.client.get(
                f"/api/projects/{project}/checks/{run_id}?include=issues,evidence"
            ).json()["data"]
            self.assertEqual((viewed["status"], viewed.get("issues", [])), ("cancelled", []))
        with self.app.state.database.connection() as connection:
            after = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)
                ).fetchone()[0]
                for table in self.BUSINESS_TABLES
            }
        self.assertEqual(after, before)
        self.emit_counts("paired_running_cancel_late_results", before, after)

    def test_legacy_budget_paused_maps_to_safe_failed_state(self):
        run_id = self.create_run()
        with self.app.state.database.connection() as connection:
            stamp = self.view(run_id)["created_at"]
            connection.execute("UPDATE v2_runs SET status='budget_paused',stage='budget_paused',error_code='session_guard_paused',retryable=1,completed_at=? WHERE id=?", (stamp, run_id))
        mapped = self.view(run_id)
        self.assertEqual((mapped["status"], mapped["stage"], mapped["error_code"], mapped["retryable"]), ("failed", "failed", "budget_guard_exceeded", True))

    def test_stage11_database_migrates_lifecycle_columns_and_events_idempotently(self):
        run_id = self.create_run()
        lifecycle_columns = (
            "started_at",
            "cancel_requested_at",
            "duration_ms",
            "retry_of_run_id",
            "root_run_id",
            "attempt_number",
            "incremental_batch_id",
        )
        with self.app.state.database.connection() as connection:
            connection.execute("DROP TABLE v2_run_events")
            for column in lifecycle_columns:
                connection.execute(f"ALTER TABLE v2_runs DROP COLUMN {column}")
            connection.execute("DELETE FROM schema_migrations WHERE version=17")

        self.app.state.database.initialize()
        self.app.state.database.initialize()
        with self.app.state.database.connection() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(v2_runs)").fetchall()
            }
            migrated = connection.execute(
                "SELECT root_run_id,attempt_number FROM v2_runs WHERE id=?", (run_id,)
            ).fetchone()
            events = connection.execute(
                "SELECT sequence,status,stage FROM v2_run_events WHERE run_id=?",
                (run_id,),
            ).fetchall()
        self.assertTrue(set(lifecycle_columns) <= columns)
        self.assertEqual((migrated["root_run_id"], migrated["attempt_number"]), (run_id, 1))
        self.assertEqual([tuple(event) for event in events], [(1, "queued", "queued")])


if __name__ == "__main__":
    unittest.main()
