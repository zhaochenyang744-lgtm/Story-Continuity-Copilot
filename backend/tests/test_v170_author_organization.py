"""v1.7.0 author organisation: 「考虑中」 plans and author-defined setting categories."""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.stage13 import Stage13Settings
from app import author_organization


class AuthorOrganizationTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="v170-organization-"))
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                              executor=lambda fn, *args: fn(*args), settings=dataclasses.replace(Stage13Settings.for_test()))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        registered = self.client.post("/api/auth/register", headers=self.idem(), json={
            "account_name": f"ao{uuid.uuid4().hex[:8]}", "display_name": "AO", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        self.project_id = registered["onboarding"]["tutorial"]["project_id"]
        self.db = self.app.state.database

    @staticmethod
    def idem():
        return {"Idempotency-Key": str(uuid.uuid4())}

    def add_story_plan(self):
        plan_id = f"storyplan-{uuid.uuid4()}"
        with self.db.connection() as c:
            c.execute("INSERT INTO v2_author_story_plans(id,project_id,title,summary,goal,position,status,target_chapter_number,archived_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (plan_id, self.project_id, "灯塔里的航海日志", "", "", 1, "planned", 14, None, "2026-10-07T00:00:00Z", "2026-10-07T00:00:00Z"))
        return plan_id

    def categories(self):
        return self.client.get(f"/api/projects/{self.project_id}/setting-categories").json()["data"]

    def change(self, **payload):
        return self.client.post(f"/api/projects/{self.project_id}/setting-categories", headers=self.idem(), json=payload)

    def test_a_plan_can_be_marked_considering_and_back(self):
        plan_id = self.add_story_plan()
        marked = self.client.post(f"/api/projects/{self.project_id}/plan-states", headers=self.idem(), json={"kind": "story", "plan_id": plan_id, "considering": True})
        self.assertEqual(marked.status_code, 200, marked.text)
        states = self.client.get(f"/api/projects/{self.project_id}/plan-states").json()["data"]
        self.assertEqual(states["considering"], [{"kind": "story", "plan_id": plan_id}])
        with self.db.connection() as c:
            self.assertEqual(author_organization.considering_ids(c, self.project_id), {("story", plan_id)})
        self.client.post(f"/api/projects/{self.project_id}/plan-states", headers=self.idem(), json={"kind": "story", "plan_id": plan_id, "considering": False})
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/plan-states").json()["data"]["considering"], [])

    def test_unknown_plan_is_not_found(self):
        response = self.client.post(f"/api/projects/{self.project_id}/plan-states", headers=self.idem(), json={"kind": "world", "plan_id": "nope", "considering": True})
        self.assertEqual(response.status_code, 404)

    def test_builtin_categories_hold_entries_by_type(self):
        view = self.categories()
        keys = [item["key"] for item in view["categories"]]
        self.assertEqual(keys[:5], ["location", "rule", "organization", "object", "term"])
        with self.db.connection() as c:
            entries = c.execute("SELECT id,entry_type FROM v2_world_entries WHERE project_id=?", (self.project_id,)).fetchall()
        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(view["membership"][entry["id"]], entry["entry_type"])

    def test_author_categories_rename_assign_and_delete(self):
        with self.db.connection() as c:
            entry = c.execute("SELECT id,entry_type FROM v2_world_entries WHERE project_id=?", (self.project_id,)).fetchone()
        created = self.change(action="create", name="信号").json()["data"]
        custom = next(item for item in created["categories"] if item["name"] == "信号")
        self.assertFalse(custom["builtin"])
        moved = self.change(action="assign", entry_id=entry["id"], category=custom["key"]).json()["data"]
        self.assertEqual(moved["membership"][entry["id"]], custom["key"])
        self.assertEqual(next(item for item in moved["categories"] if item["key"] == custom["key"])["count"], 1)
        renamed = self.change(action="rename", category="location", name="港区").json()["data"]
        self.assertEqual(next(item for item in renamed["categories"] if item["key"] == "location")["name"], "港区")
        removed = self.change(action="delete", category=custom["key"]).json()["data"]
        self.assertNotIn(custom["key"], [item["key"] for item in removed["categories"]])
        self.assertEqual(removed["membership"][entry["id"]], entry["entry_type"])

    def test_category_names_are_validated(self):
        self.assertEqual(self.change(action="create", name="  ").status_code, 422)
        self.assertEqual(self.change(action="rename", name="新名字").status_code, 422)

    def test_reset_clears_the_organisation_tables(self):
        plan_id = self.add_story_plan()
        self.client.post(f"/api/projects/{self.project_id}/plan-states", headers=self.idem(), json={"kind": "story", "plan_id": plan_id, "considering": True})
        self.change(action="create", name="信号")
        reset = self.client.post(f"/api/projects/{self.project_id}/reset", headers=self.idem(), json={"confirm": True, "reason": "demo_recovery"})
        self.assertIn(reset.status_code, (200, 201), reset.text)
        with self.db.connection() as c:
            for table in author_organization.TABLES:
                self.assertEqual(c.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (self.project_id,)).fetchone()[0], 0, table)


if __name__ == "__main__":
    unittest.main()
