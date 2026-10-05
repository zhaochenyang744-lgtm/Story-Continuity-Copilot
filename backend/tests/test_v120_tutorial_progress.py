from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.stage13 import Stage13Settings
from app.v2_database import V2Database


EVENTS = [
    "memory_source_opened",
    "continuity_issue_located",
    "evidence_opened",
    "author_decision_recorded",
]


def idem(value: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class CountingProvider:
    available = True
    label = "v120-must-not-be-called"

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, _request):
        self.calls += 1
        raise AssertionError("v1.2.0 tutorial progress must not call Provider")


class V120TutorialProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v120-progress-"))
        self.provider = CountingProvider()
        self.app = create_app(
            AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected"),
            provider=self.provider,
            executor=lambda fn, *args: fn(*args),
            settings=Stage13Settings.for_test(),
        )
        self.client = TestClient(self.app)

    def register(self, client: TestClient, account: str) -> dict:
        response = client.post(
            "/api/auth/register",
            headers=idem(),
            json={
                "account_name": account,
                "display_name": "Tutorial Author",
                "password": "safe-password-v120",
                "recovery_email": f"{account}@example.test",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["data"]

    def progress(self, client: TestClient | None = None) -> dict | None:
        response = (client or self.client).get("/api/onboarding")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["progress"]

    def event(
        self,
        project_id: str,
        event: str,
        *,
        client: TestClient | None = None,
        key: str | None = None,
        **extra,
    ):
        return (client or self.client).post(
            "/api/onboarding/progress",
            headers=idem(key),
            json={
                "tutorial_version": "1.2.0",
                "project_id": project_id,
                "event": event,
                **extra,
            },
        )

    def test_registration_and_four_events_are_durable_and_provider_free(self):
        registered = self.register(self.client, "v120-events")
        project_id = registered["onboarding"]["tutorial"]["project_id"]
        initial = registered["onboarding"]["progress"]
        self.assertEqual(
            initial,
            {
                "tutorial_version": "1.2.0",
                "tutorial_project_id": project_id,
                "current_step": 1,
                "completed_events": [],
                "revision": 1,
                "updated_at": initial["updated_at"],
            },
        )
        for step, event in enumerate(EVENTS, 2):
            response = self.event(project_id, event)
            self.assertEqual(response.status_code, 200, response.text)
            progress = response.json()["data"]
            self.assertEqual((progress["current_step"], progress["revision"]), (step, step))
            self.assertEqual(progress["completed_events"], EVENTS[: step - 1])
            self.assertEqual(self.progress(), progress)
        self.assertEqual(self.provider.calls, 0)

    def test_business_and_key_replays_return_current_canonical_state(self):
        project_id = self.register(self.client, "v120-idempotent")["onboarding"]["tutorial"]["project_id"]
        first_key = str(uuid.uuid4())
        first = self.event(project_id, EVENTS[0], key=first_key).json()["data"]
        duplicate_key = self.event(project_id, EVENTS[0], key=first_key).json()["data"]
        duplicate_business = self.event(project_id, EVENTS[0]).json()["data"]
        self.assertEqual(first["revision"], 2)
        self.assertEqual((duplicate_key["revision"], duplicate_business["revision"]), (2, 2))
        second = self.event(project_id, EVENTS[1]).json()["data"]
        replay_after_advance = self.event(project_id, EVENTS[0], key=first_key)
        self.assertEqual(replay_after_advance.status_code, 200, replay_after_advance.text)
        self.assertEqual(replay_after_advance.json()["data"], second)
        conflict = self.event(project_id, EVENTS[2], key=first_key)
        self.assertEqual((conflict.status_code, conflict.json()["error"]["code"]), (409, "idempotency_conflict"))

    def test_out_of_order_events_never_reduce_step(self):
        project_id = self.register(self.client, "v120-order")["onboarding"]["tutorial"]["project_id"]
        high = self.event(project_id, EVENTS[3]).json()["data"]
        low = self.event(project_id, EVENTS[0]).json()["data"]
        self.assertEqual((high["current_step"], low["current_step"]), (5, 5))
        self.assertEqual(low["completed_events"], [EVENTS[0], EVENTS[3]])
        self.assertEqual((high["revision"], low["revision"]), (2, 3))

    def test_logout_login_and_second_client_restore_exact_progress(self):
        account = "v120-sessions"
        project_id = self.register(self.client, account)["onboarding"]["tutorial"]["project_id"]
        expected = self.event(project_id, EVENTS[0]).json()["data"]
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        logged_in = self.client.post(
            "/api/auth/login",
            json={"account_name": account, "password": "safe-password-v120"},
        )
        self.assertEqual(logged_in.status_code, 200, logged_in.text)
        self.assertEqual(self.progress(), expected)

        second = TestClient(self.app)
        second_login = second.post(
            "/api/auth/login",
            json={"account_name": account, "password": "safe-password-v120"},
        )
        self.assertEqual(second_login.status_code, 200, second_login.text)
        self.assertEqual(self.progress(second), expected)
        advanced = self.event(project_id, EVENTS[1], client=second).json()["data"]
        self.assertEqual(self.progress(second), advanced)
        self.assertEqual(self.provider.calls, 0)

    def test_invalid_identity_project_version_event_schema_and_csrf_fail_closed(self):
        own = self.register(self.client, "v120-owner")
        own_tutorial = own["onboarding"]["tutorial"]["project_id"]
        with self.app.state.database.connection() as connection:
            ordinary = self.app.state.database._create_project(
                connection,
                own["user"]["id"],
                "普通作品",
                "",
                "",
                "user_blank",
            )
        outsider = TestClient(self.app)
        foreign = self.register(outsider, "v120-outsider")["onboarding"]["tutorial"]["project_id"]
        before = self.progress()

        wrong_project = self.event(ordinary, EVENTS[0])
        foreign_project = self.event(foreign, EVENTS[0])
        wrong_version = self.client.post(
            "/api/onboarding/progress",
            headers=idem(),
            json={"tutorial_version": "1.1.0", "project_id": own_tutorial, "event": EVENTS[0]},
        )
        wrong_event = self.client.post(
            "/api/onboarding/progress",
            headers=idem(),
            json={"tutorial_version": "1.2.0", "project_id": own_tutorial, "event": "made_up"},
        )
        extra = self.event(own_tutorial, EVENTS[0], next_step=5)
        missing_key = self.client.post(
            "/api/onboarding/progress",
            json={"tutorial_version": "1.2.0", "project_id": own_tutorial, "event": EVENTS[0]},
        )
        csrf = self.client.post(
            "/api/onboarding/progress",
            headers={**idem(), "Origin": "http://evil.example"},
            json={"tutorial_version": "1.2.0", "project_id": own_tutorial, "event": EVENTS[0]},
        )
        self.assertEqual((wrong_project.status_code, wrong_project.json()["error"]["code"]), (409, "tutorial_progress_target_invalid"))
        self.assertEqual((foreign_project.status_code, foreign_project.json()["error"]["code"]), (409, "tutorial_progress_target_invalid"))
        for response in (wrong_version, wrong_event, extra):
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (400, "invalid_request"))
        self.assertEqual((missing_key.status_code, missing_key.json()["error"]["code"]), (400, "missing_idempotency_key"))
        self.assertEqual((csrf.status_code, csrf.json()["error"]["code"]), (403, "cross_site_request_rejected"))
        self.assertEqual(self.progress(), before)

        visitor = TestClient(self.app)
        self.assertEqual(visitor.post("/api/auth/visitor").status_code, 201)
        visitor_result = visitor.post(
            "/api/onboarding/progress",
            headers=idem(),
            json={"tutorial_version": "1.2.0", "project_id": own_tutorial, "event": EVENTS[0]},
        )
        self.assertEqual((visitor_result.status_code, visitor_result.json()["error"]["code"]), (409, "tutorial_unavailable"))

    def test_complete_skip_import_hide_progress_and_reopen_resets_fixture_and_progress(self):
        project_id = self.register(self.client, "v120-lifecycle")["onboarding"]["tutorial"]["project_id"]
        advanced = self.event(project_id, EVENTS[2]).json()["data"]
        skipped = self.client.post("/api/onboarding/skip", headers=idem(), json={"confirm": True})
        self.assertEqual((skipped.status_code, skipped.json()["data"]["progress"]), (200, None))
        self.assertIsNone(self.progress())
        reopened = self.client.post("/api/onboarding/reopen", headers=idem(), json={"confirm": True})
        reset = reopened.json()["data"]["progress"]
        self.assertEqual((reset["current_step"], reset["completed_events"]), (1, []))
        self.assertGreater(reset["revision"], advanced["revision"])
        tutorial = self.client.get(f"/api/projects/{project_id}").json()["data"]
        self.assertEqual((tutorial["title"], tutorial["chapter_count"], tutorial["data_origin"]), ("教学模式 · 灰港回声", 10, "tutorial_seed"))
        completed = self.client.post("/api/onboarding/complete", headers=idem(), json={"confirm": True})
        self.assertEqual((completed.status_code, self.progress()), (200, None))

        reopened_again = self.client.post("/api/onboarding/reopen", headers=idem(), json={"confirm": True})
        self.assertEqual(reopened_again.status_code, 200, reopened_again.text)
        preview = self.client.post(
            "/api/imports/preview",
            headers=idem(),
            files={"file": ("real.md", "# 第一章\n真实内容。".encode(), "text/markdown")},
        ).json()["data"]
        imported = self.client.post(
            f"/api/imports/{preview['import_id']}/commit",
            headers=idem(),
            json={"confirm": True, "title": "真实作品", "chapter_preview_ids": [item["preview_id"] for item in preview["detected"]["chapters"]]},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        onboarding = self.client.get("/api/onboarding").json()["data"]
        self.assertEqual((onboarding["status"], onboarding["progress"], onboarding["real_project_count"]), ("completed", None, 1))
        self.assertEqual(self.client.get("/api/projects?q=教学模式").json()["data"]["projects"], [])
        self.assertEqual(self.provider.calls, 0)

    def test_migration_is_idempotent_and_does_not_reactivate_completed_accounts(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v120-migration-"))
        paths = AppPaths.from_project_root(root, protected_poc_root=root / "protected")
        paths.prepare_runtime()
        with sqlite3.connect(paths.database_path) as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE v2_users(id TEXT PRIMARY KEY,account_name TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,password_hash TEXT NOT NULL,created_at TEXT NOT NULL,account_type TEXT NOT NULL DEFAULT 'registered',visitor_expires_at TEXT,recovery_email_hash TEXT,recovery_email_masked TEXT,recovery_email_verified_at TEXT,onboarding_status TEXT NOT NULL DEFAULT 'completed',onboarding_tutorial_project_id TEXT,onboarding_completed_at TEXT);
                CREATE TABLE v2_projects(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),title TEXT NOT NULL,genre TEXT NOT NULL DEFAULT '',summary TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,metadata_revision INTEGER NOT NULL,data_origin TEXT NOT NULL,seed_key TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,current_memory_version INTEGER NOT NULL DEFAULT 1,source_revision INTEGER NOT NULL DEFAULT 1);
                INSERT INTO v2_users(id,account_name,display_name,password_hash,created_at,onboarding_status,onboarding_tutorial_project_id) VALUES('active-user','active-user','Active','x','2026-01-01T00:00:00+00:00','active','tutorial-project');
                INSERT INTO v2_users(id,account_name,display_name,password_hash,created_at,onboarding_status,onboarding_tutorial_project_id) VALUES('complete-user','complete-user','Complete','x','2026-01-01T00:00:00+00:00','completed','completed-project');
                INSERT INTO v2_projects VALUES('tutorial-project','active-user','Tutorial','','','active',1,'tutorial_seed','grey_harbor','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',4,1);
                INSERT INTO v2_projects VALUES('completed-project','complete-user','Old Tutorial','','','active',1,'tutorial_seed','grey_harbor','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',4,1);
                """
            )
        database = V2Database(paths)
        database.initialize()
        with database.connection() as connection:
            first = dict(connection.execute("SELECT * FROM v2_users WHERE id='active-user'").fetchone())
            completed = dict(connection.execute("SELECT * FROM v2_users WHERE id='complete-user'").fetchone())
            migration_count = connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=120").fetchone()[0]
        database.initialize()
        with database.connection() as connection:
            second = dict(connection.execute("SELECT * FROM v2_users WHERE id='active-user'").fetchone())
            second_migration_count = connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=120").fetchone()[0]
        self.assertEqual(first, second)
        self.assertEqual((first["onboarding_tutorial_version"], first["onboarding_current_step"], first["onboarding_progress_revision"]), ("1.2.0", 1, 1))
        self.assertIsNone(completed["onboarding_tutorial_version"])
        self.assertEqual(completed["onboarding_status"], "completed")
        self.assertEqual((migration_count, second_migration_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
