from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.stage13 import Stage13Settings


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


class CountingProvider:
    available = True
    label = "v110-must-not-be-called"

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, _request):
        self.calls += 1
        raise AssertionError("v1.1.0 onboarding must not call Provider")


class V110OnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v110-onboarding-"))
        self.provider = CountingProvider()
        self.app = create_app(
            AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected"),
            provider=self.provider,
            executor=lambda fn, *args: fn(*args),
            settings=Stage13Settings.for_test(),
        )
        self.client = TestClient(self.app)

    def register(self, account_name: str) -> dict:
        response = self.client.post(
            "/api/auth/register",
            headers=idem(),
            json={
                "account_name": account_name,
                "display_name": "First Run Author",
                "password": "safe-password-v110",
                "recovery_email": f"{account_name}@example.test",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["data"]

    def test_new_account_has_zero_real_projects_and_one_isolated_tutorial(self):
        registered = self.register("v110-empty")
        self.assertEqual(registered["seeded_projects"], [])
        tutorial_id = registered["onboarding"]["tutorial"]["project_id"]

        projects = self.client.get("/api/projects").json()["data"]["projects"]
        home = self.client.get("/api/home").json()["data"]
        onboarding = self.client.get("/api/onboarding").json()["data"]
        tutorial = self.client.get(f"/api/projects/{tutorial_id}").json()["data"]

        self.assertEqual(projects, [])
        self.assertEqual((home["recent_projects"], home["pending_continuity"], home["continue_work"]), ([], [], None))
        self.assertEqual((onboarding["real_project_count"], onboarding["status"], onboarding["show_first_run"]), (0, "active", True))
        self.assertEqual((tutorial["data_origin"], tutorial["is_tutorial"], tutorial["title"]), ("tutorial_seed", True, "教学模式 · 灰港回声"))
        with self.app.state.database.connection() as connection:
            counts = connection.execute(
                "SELECT data_origin,COUNT(*) count FROM v2_projects WHERE user_id=? GROUP BY data_origin",
                (registered["user"]["id"],),
            ).fetchall()
        self.assertEqual({row["data_origin"]: row["count"] for row in counts}, {"tutorial_seed": 1})
        self.assertEqual(self.provider.calls, 0)

    def test_complete_skip_relogin_and_help_reopen_are_persistent_and_deterministic(self):
        registered = self.register("v110-finish")
        tutorial_id = registered["onboarding"]["tutorial"]["project_id"]
        with self.app.state.database.connection() as connection:
            connection.execute("UPDATE v2_projects SET title='保留中的教学进度' WHERE id=?", (tutorial_id,))
        rejected = self.client.post("/api/onboarding/reopen", headers=idem(), json={"confirm": False})
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.client.get(f"/api/projects/{tutorial_id}").json()["data"]["title"], "保留中的教学进度")
        skipped = self.client.post("/api/onboarding/skip", headers=idem(), json={"confirm": True})
        self.assertEqual((skipped.status_code, skipped.json()["data"]["status"]), (200, "skipped"))
        self.client.post("/api/auth/logout")
        logged_in = self.client.post("/api/auth/login", json={"account_name": "v110-finish", "password": "safe-password-v110"})
        self.assertEqual(logged_in.status_code, 200)
        after_login = self.client.get("/api/onboarding").json()["data"]
        self.assertEqual((after_login["status"], after_login["show_first_run"]), ("skipped", False))

        reopened = self.client.post("/api/onboarding/reopen", headers=idem(), json={"confirm": True})
        self.assertEqual((reopened.status_code, reopened.json()["data"]["tutorial"]["project_id"]), (200, tutorial_id))
        tutorial = self.client.get(f"/api/projects/{tutorial_id}").json()["data"]
        self.assertEqual((tutorial["title"], tutorial["status"], tutorial["chapter_count"]), ("教学模式 · 灰港回声", "active", 10))
        completed = self.client.post("/api/onboarding/complete", headers=idem(), json={"confirm": True})
        self.assertEqual(completed.json()["data"]["status"], "completed")
        self.assertEqual(self.client.get("/api/projects").json()["data"]["projects"], [])
        self.assertEqual(self.provider.calls, 0)

    def test_direct_import_exits_first_run_without_touching_tutorial(self):
        registered = self.register("v110-import")
        tutorial_id = registered["onboarding"]["tutorial"]["project_id"]
        preview = self.client.post(
            "/api/imports/preview",
            headers=idem(),
            files={"file": ("first.md", "# 第一章\n真实作品正文。".encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(preview.status_code, 201, preview.text)
        preview_data = preview.json()["data"]
        committed = self.client.post(
            f"/api/imports/{preview_data['import_id']}/commit",
            headers=idem(),
            json={
                "confirm": True,
                "title": "第一部真实作品",
                "chapter_preview_ids": [item["preview_id"] for item in preview_data["detected"]["chapters"]],
            },
        )
        self.assertEqual(committed.status_code, 201, committed.text)
        onboarding = self.client.get("/api/onboarding").json()["data"]
        projects = self.client.get("/api/projects?q=教学模式").json()["data"]["projects"]
        all_projects = self.client.get("/api/projects").json()["data"]["projects"]
        home = self.client.get("/api/home").json()["data"]
        self.assertEqual((onboarding["status"], onboarding["real_project_count"], onboarding["show_first_run"]), ("completed", 1, False))
        self.assertEqual(projects, [])
        self.assertEqual([item["title"] for item in all_projects], ["第一部真实作品"])
        self.assertEqual([item["title"] for item in home["recent_projects"]], ["第一部真实作品"])
        self.assertEqual(self.client.get(f"/api/projects/{tutorial_id}").status_code, 200)
        self.assertEqual(self.provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
