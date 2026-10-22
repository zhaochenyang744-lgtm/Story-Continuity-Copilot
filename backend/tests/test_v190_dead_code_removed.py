"""v1.9.0: what was removed stays removed, and what old versions left behind is untouched.

Removed: the revision plan (analysis type, three endpoints), the pre-writing brief and the question box as
things to *create*, and three endpoints no page called (outline, source-coverage-audits/{id}, onboarding/reopen).
Kept: the tables and migrations, the export of revision tasks an author already has, and the read of old
question records.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.project_export import project_snapshot
from app.provider import ProviderResult
from app.stage13 import Stage13Settings
from tests.legacy_story_qa import seed_story_qa

REVISION_TABLES = ("v2_revision_plan_candidates", "v2_revision_tasks", "v2_revision_task_versions", "v2_revision_candidate_decisions")


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4()), "Origin": "http://testserver"}


class _Provider:
    available = True
    label = "v190-test-provider"
    model_label = "v190-test-model"

    def evaluate(self, request):
        return ProviderResult({"issues": []}, 1, 1, latency_ms=1)


class RemovedEndpointsAndTypesTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v190-removed-"))
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=_Provider(),
                              executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
        self.client = TestClient(self.app)
        registered = self.client.post("/api/auth/register", headers=idem(), json={"account_name": "v190-owner", "display_name": "Author",
                                                                                  "password": "safe-password-v190", "recovery_email": "v190@example.test"})
        self.assertEqual(registered.status_code, 201, registered.text)
        self.user_id = registered.json()["data"]["user"]["id"]
        self.project_id = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        self.draft = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["current_draft"]

    def test_removed_endpoints_are_not_routes_any_more(self):
        p = f"/api/projects/{self.project_id}"
        gone = (
            ("post", f"{p}/analyses/run-1/revision-candidates/candidate-1/decision", {"base_task_version": 0, "decision": "rejected"}),
            ("get", f"{p}/revision-tasks", None),
            ("patch", f"{p}/revision-tasks/task-1", {"base_version": 1, "status": "completed"}),
            ("get", f"{p}/outline", None),
            ("get", f"{p}/source-coverage-audits/audit-1", None),
            ("post", "/api/onboarding/reopen", {"confirm": True}),
        )
        for method, url, body in gone:
            with self.subTest(method=method, url=url):
                response = self.client.request(method.upper(), url, headers=idem(), **({"json": body} if body is not None else {}))
                self.assertIn(response.status_code, (404, 405), response.text)

    def test_removed_analysis_types_cannot_be_created_or_listed(self):
        for kind in ("revision_plan", "context_brief", "story_qa"):
            with self.subTest(kind=kind):
                body = {"analysis_type": kind, "draft_id": self.draft["id"], "draft_revision": self.draft["revision"]}
                if kind == "revision_plan":
                    body["issue_ids"] = ["issue-1"]
                if kind == "story_qa":
                    body.update(question="罗盘现在在哪里？", scope=["confirmed"])
                response = self.client.post(f"/api/projects/{self.project_id}/analyses", headers=idem(), json=body)
                self.assertEqual(response.status_code, 400, response.text)  # the app answers every failed request validation with 400 invalid_request
        for kind in ("revision_plan", "context_brief"):
            with self.subTest(listed=kind):
                self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/analyses?analysis_type={kind}").status_code, 400)

    def test_the_analyses_the_pages_still_use_are_unchanged(self):
        for kind in ("plan_alignment", "change_impact", "foreshadow_scan", "story_qa"):
            with self.subTest(kind=kind):
                response = self.client.get(f"/api/projects/{self.project_id}/analyses?analysis_type={kind}")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["data"]["analysis_type"], kind)

    def test_an_old_question_record_is_still_read_and_its_run_cannot_be_started_again(self):
        run_id = seed_story_qa(self.app.state.database, self.project_id, self.draft["id"], self.draft["revision"],
                               question="罗盘现在在哪里？", scope=["confirmed", "written"], answer="在林默手里。")
        listed = self.client.get(f"/api/projects/{self.project_id}/analyses?analysis_type=story_qa&limit=20").json()["data"]
        self.assertEqual([run["run_id"] for run in listed["runs"]], [run_id])
        self.assertEqual((listed["run"]["question"], listed["run"]["analysis"]["answer"]), ("罗盘现在在哪里？", "在林默手里。"))
        retried = self.client.post(f"/api/projects/{self.project_id}/analyses/{run_id}/retry", headers=idem(), json={"client_request_id": str(uuid.uuid4())})
        self.assertEqual(retried.status_code, 404, retried.text)


class WhatOldVersionsLeftBehindTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v190-legacy-"))
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=_Provider(),
                              executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
        self.client = TestClient(self.app)
        registered = self.client.post("/api/auth/register", headers=idem(), json={"account_name": "v190-legacy", "display_name": "Author",
                                                                                  "password": "safe-password-v190", "recovery_email": "v190-legacy@example.test"})
        self.assertEqual(registered.status_code, 201, registered.text)
        self.user_id = registered.json()["data"]["user"]["id"]
        self.project_id = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]

    def test_the_revision_tables_and_their_migration_are_still_there(self):
        db = self.app.state.database
        db.initialize()
        with db.connection() as c:
            tables = {row["name"] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            migrated = c.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=130").fetchone()[0] if "schema_migrations" in tables else None
            columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_projects)")}
        self.assertTrue(set(REVISION_TABLES) <= tables)
        self.assertIn("revision_task_version", columns)
        self.assertIn(migrated, (None, 0, 1))

    def test_an_export_still_carries_the_revision_tasks_an_author_already_has(self):
        db = self.app.state.database
        with db.connection() as c:
            issue = c.execute("SELECT id,run_id FROM v2_issues WHERE project_id=? LIMIT 1", (self.project_id,)).fetchone()
            self.assertIsNotNone(issue, "the sample work carries a checked issue")
            c.execute("INSERT INTO v2_revision_plan_candidates(id,project_id,run_id,candidate_ordinal,issue_id,title,normalized_title,instruction,priority,evidence_json,decision_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      ("cand-old", self.project_id, issue["run_id"], 1, issue["id"], "核对罗盘", "核对罗盘", "回到当前草稿核对罗盘的下落。", "high", "[]", "accepted", "2026-01-01T00:00:00+00:00"))
            c.execute("INSERT INTO v2_revision_tasks(id,project_id,source_run_id,candidate_id,issue_id,title,normalized_title,instruction,priority,position,status,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      ("task-old", self.project_id, issue["run_id"], "cand-old", issue["id"], "核对罗盘", "核对罗盘", "回到当前草稿核对罗盘的下落。", "high", 1, "todo", 1,
                       "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
        exported = project_snapshot(db, self.user_id, self.project_id)["revision_tasks"]
        self.assertEqual(exported, [{"id": "task-old", "title": "核对罗盘", "instruction": "回到当前草稿核对罗盘的下落。", "priority": "high", "position": 1, "status": "todo", "version": 1}])


if __name__ == "__main__":
    unittest.main()
