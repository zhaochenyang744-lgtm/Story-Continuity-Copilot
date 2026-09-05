from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult
from app.stage13 import Stage13Settings


def idem(value: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class ProfileProvider:
    available = True
    label = "v130-profile-stub"
    model_label = "v130-profile-stub"

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, request: dict) -> ProviderResult:
        self.calls += 1
        return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1, latency_ms=1)


class V130ProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-profile-"))
        self.paths = AppPaths.from_project_root(root, protected_poc_root=root / "protected")
        self.provider = ProfileProvider()
        self.app = create_app(self.paths, provider=self.provider, settings=Stage13Settings.for_test())
        self.client = TestClient(self.app)
        self.account = "profile-owner"
        self.password = "safe-profile-password"
        created = self.client.post(
            "/api/auth/register",
            headers=idem(),
            json={"account_name": self.account, "display_name": "Initial Author", "password": self.password, "recovery_email": "profile-owner@example.test"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.user_id = created.json()["data"]["user"]["id"]

    def test_profile_update_persists_without_changing_credentials_or_session_identity(self):
        before = self.client.get("/api/auth/session").json()["data"]["user"]
        self.assertEqual((before["account_name"], before["display_name"], before["avatar_preset"], before["profile_revision"]), (self.account, "Initial Author", "continuity_violet", 1))
        key = str(uuid.uuid4())
        payload = {"base_profile_revision": 1, "display_name": "  Archive Editor  ", "avatar_preset": "archive_blue"}
        updated = self.client.patch("/api/auth/profile", headers=idem(key), json=payload)
        self.assertEqual(updated.status_code, 200, updated.text)
        user = updated.json()["data"]["user"]
        self.assertEqual((user["id"], user["account_name"], user["display_name"], user["avatar_preset"], user["profile_revision"]), (self.user_id, self.account, "Archive Editor", "archive_blue", 2))
        replay = self.client.patch("/api/auth/profile", headers=idem(key), json=payload)
        self.assertEqual(replay.json()["data"], updated.json()["data"])
        conflicting_replay = self.client.patch("/api/auth/profile", headers=idem(key), json={**payload, "display_name": "Changed"})
        self.assertEqual((conflicting_replay.status_code, conflicting_replay.json()["error"]["code"]), (409, "idempotency_conflict"))
        refreshed = self.client.get("/api/auth/session").json()["data"]["user"]
        self.assertEqual((refreshed["display_name"], refreshed["profile_revision"]), ("Archive Editor", 2))
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        display_login = self.client.post("/api/auth/login", json={"account_name": "Archive Editor", "password": self.password})
        self.assertEqual((display_login.status_code, display_login.json()["error"]["code"]), (401, "invalid_credentials"))
        login = self.client.post("/api/auth/login", json={"account_name": self.account, "password": self.password})
        self.assertEqual(login.status_code, 200, login.text)
        persisted = login.json()["data"]["user"]
        self.assertEqual((persisted["id"], persisted["display_name"], persisted["avatar_preset"], persisted["profile_revision"]), (self.user_id, "Archive Editor", "archive_blue", 2))
        self.assertEqual(self.provider.calls, 0)

    def test_revision_validation_visitor_rejection_and_account_isolation(self):
        updated = self.client.patch(
            "/api/auth/profile",
            headers=idem(),
            json={"base_profile_revision": 1, "display_name": "Owner Updated", "avatar_preset": "folio_rose"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        stale = self.client.patch(
            "/api/auth/profile",
            headers=idem(),
            json={"base_profile_revision": 1, "display_name": "Stale Write", "avatar_preset": "signal_amber"},
        )
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (409, "profile_revision_conflict"))
        invalid_avatar = self.client.patch(
            "/api/auth/profile",
            headers=idem(),
            json={"base_profile_revision": 2, "display_name": "Owner Updated", "avatar_preset": "external-url"},
        )
        self.assertEqual(invalid_avatar.status_code, 400)
        missing_key = self.client.patch(
            "/api/auth/profile",
            json={"base_profile_revision": 2, "display_name": "Owner Updated", "avatar_preset": "archive_blue"},
        )
        self.assertEqual((missing_key.status_code, missing_key.json()["error"]["code"]), (400, "missing_idempotency_key"))

        other = TestClient(self.app)
        other_created = other.post(
            "/api/auth/register",
            headers=idem(),
            json={"account_name": "profile-other", "display_name": "Other Author", "password": "safe-other-password", "recovery_email": "profile-other@example.test"},
        )
        self.assertEqual(other_created.status_code, 201, other_created.text)
        other_update = other.patch(
            "/api/auth/profile",
            headers=idem(),
            json={"base_profile_revision": 1, "display_name": "Other Updated", "avatar_preset": "signal_amber"},
        )
        self.assertEqual(other_update.status_code, 200, other_update.text)
        owner = self.client.get("/api/auth/session").json()["data"]["user"]
        self.assertEqual((owner["id"], owner["display_name"], owner["avatar_preset"]), (self.user_id, "Owner Updated", "folio_rose"))

        visitor = TestClient(self.app)
        visitor_created = visitor.post("/api/auth/visitor")
        self.assertEqual(visitor_created.status_code, 201, visitor_created.text)
        visitor_update = visitor.patch(
            "/api/auth/profile",
            headers=idem(),
            json={"base_profile_revision": 1, "display_name": "Visitor Changed", "avatar_preset": "archive_blue"},
        )
        self.assertEqual((visitor_update.status_code, visitor_update.json()["error"]["code"]), (403, "profile_update_not_allowed"))
        self.assertEqual(self.provider.calls, 0)

    def test_project_list_derives_real_chapter_and_word_counts_without_double_counting_current_draft(self):
        created = self.client.post(
            "/api/projects",
            headers=idem(),
            json={"title": "Counted Work", "genre": "Novel", "summary": "Real author-center data"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        project_id = created.json()["data"]["project"]["id"]
        with self.app.state.database.connection() as c:
            c.execute("UPDATE v2_drafts SET body=? WHERE project_id=?", ("第一 章\n草稿", project_id))
            c.execute(
                "INSERT INTO v2_chapters VALUES(?,?,?,?,?,?,?)",
                (f"ch-{uuid.uuid4()}", project_id, 1, "第一章", "", "旧 正文", 1),
            )
            c.execute(
                "INSERT INTO v2_chapters VALUES(?,?,?,?,?,?,?)",
                (f"ch-{uuid.uuid4()}", project_id, 2, "第二章", "", "第二章 正文", 1),
            )
        projects = self.client.get("/api/projects?q=&sort=updated_desc")
        self.assertEqual(projects.status_code, 200, projects.text)
        project = next(item for item in projects.json()["data"]["projects"] if item["id"] == project_id)
        self.assertEqual((project["chapter_count"], project["word_count"]), (2, 10))
        self.assertNotIn("body", project["current_draft"])
        self.assertEqual(self.provider.calls, 0)

    def test_existing_user_table_migrates_profile_defaults_idempotently(self):
        with self.app.state.database.connection() as c:
            c.execute("ALTER TABLE v2_users DROP COLUMN avatar_preset")
            c.execute("ALTER TABLE v2_users DROP COLUMN profile_revision")
            c.execute("DELETE FROM schema_migrations WHERE version=132")
        self.app.state.database.initialize()
        self.app.state.database.initialize()
        with self.app.state.database.connection() as c:
            columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_users)")}
            row = c.execute("SELECT account_name,display_name,avatar_preset,profile_revision FROM v2_users WHERE id=?", (self.user_id,)).fetchone()
            migration_count = c.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=132").fetchone()[0]
        self.assertTrue({"account_name", "display_name", "avatar_preset", "profile_revision"}.issubset(columns))
        self.assertEqual(tuple(row), (self.account, "Initial Author", "continuity_violet", 1))
        self.assertEqual(migration_count, 1)
        self.assertEqual(self.provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
