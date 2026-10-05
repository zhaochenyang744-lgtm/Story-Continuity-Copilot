"""Character quotas (v1.6.0).

Authors meet a daily character budget instead of a count of provider dispatches: a check spends the
characters of what it checks, a registered author has 60,000 a day and one whole-book import, and a
visitor checks one chapter of up to 3,000 characters at a time. Dispatch counts remain only as a
runaway backstop.
"""
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
from app.text_content import written_chars

from tests.test_v17_partial_review_results import Poisoned

SENTENCE = "林默走进港务局，把航图摊在桌上。"


class CharacterQuotaTests(unittest.TestCase):
    def start(self, **overrides):
        root = pathlib.Path(tempfile.mkdtemp(prefix="v160-quota-"))
        settings = dataclasses.replace(Stage13Settings.for_test(), **overrides)
        self.provider = Poisoned(None)
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                              provider=self.provider, executor=lambda fn, *args: fn(*args), settings=settings)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        registered = self.client.post("/api/auth/register", headers=self.idem(), json={
            "account_name": f"chars{uuid.uuid4().hex[:8]}", "display_name": "Chars", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        self.project_id = registered["onboarding"]["tutorial"]["project_id"]

    @staticmethod
    def idem():
        return {"Idempotency-Key": str(uuid.uuid4())}

    def save(self, sentences: int):
        draft = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["current_draft"]
        body = SENTENCE * sentences
        response = self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}", headers=self.idem(),
                                     json={"title": draft.get("title") or "chars", "body": body, "base_revision": draft["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"], written_chars(body)

    def check(self, draft):
        return self.client.post(f"/api/projects/{self.project_id}/checks", headers=self.idem(),
                                json={"draft_id": draft["id"], "draft_revision": draft["revision"]})

    def usage(self):
        response = self.client.get("/api/account/usage")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_a_check_spends_the_characters_it_checks(self):
        self.start()
        before = self.usage()
        self.assertEqual((before["account_type"], before["check_chars_limit"], before["check_chars_remaining"], before["imports_remaining"]),
                         ("registered", 60_000, 60_000, 1))
        draft, chars = self.save(4)
        self.assertEqual(self.check(draft).status_code, 202)
        after = self.usage()
        self.assertEqual((after["check_chars_used"], after["check_chars_remaining"]), (chars, 60_000 - chars))

    def test_a_check_beyond_the_daily_characters_is_refused_before_any_dispatch(self):
        self.start(registered_check_chars=1_000)
        draft, chars = self.save(80)
        self.assertGreater(chars, 1_000)
        response = self.check(draft)
        self.assertEqual(response.status_code, 429, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], "character_quota_exceeded")
        self.assertEqual(error["details"], {"characters": chars, "remaining": 1_000, "limit": 1_000})
        self.assertEqual(self.provider.requests, [])
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_character_usage").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_usage_reservations").fetchone()[0], 0)
            run = c.execute("SELECT status,error_code FROM v2_runs WHERE run_type='continuity' ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertEqual((run["status"], run["error_code"]), ("failed", "character_quota_exceeded"))

    def test_the_spend_is_atomic_with_the_workflow_reservation(self):
        self.start(registered_workflows=1)
        stage13 = self.app.state.stage13
        user_id = self.client.get("/api/auth/session").json()["data"]["user"]["id"]
        stage13.reserve_workflow(user_id, self.project_id, "continuity", None, characters=10, character_kind="check")
        with self.assertRaises(Exception):
            stage13.reserve_workflow(user_id, self.project_id, "continuity", None, characters=10, character_kind="check")
        self.assertEqual(self.usage()["check_chars_used"], 10)

    def test_one_whole_book_import_a_day(self):
        self.start()
        stage13 = self.app.state.stage13
        user_id = self.client.get("/api/auth/session").json()["data"]["user"]["id"]
        stage13.reserve_workflow(user_id, None, "memory_initialization", None, characters=300_000, character_kind="import")
        with self.assertRaises(Exception) as caught:
            stage13.reserve_workflow(user_id, None, "memory_initialization", None, characters=1_000, character_kind="import")
        self.assertEqual(getattr(caught.exception, "code", None), "import_quota_exceeded")
        self.assertEqual(self.usage()["imports_remaining"], 0)
        # Imports do not spend the daily check characters.
        self.assertEqual(self.usage()["check_chars_used"], 0)

    def test_a_visitor_checks_one_chapter_of_up_to_the_visitor_limit(self):
        self.start(visitor_check_chars=200)
        guest = TestClient(self.app)
        self.addCleanup(guest.close)
        visitor = guest.post("/api/auth/visitor", headers=self.idem())
        self.assertEqual(visitor.status_code, 201, visitor.text)
        user_id = visitor.json()["data"]["user"]["id"]
        stage13 = self.app.state.stage13
        stage13.reserve_workflow(user_id, None, "continuity", None, characters=200, character_kind="check")
        with self.assertRaises(Exception) as caught:
            stage13.reserve_workflow(user_id, None, "continuity", None, characters=201, character_kind="check")
        self.assertEqual(getattr(caught.exception, "code", None), "visitor_check_too_long")
        usage = guest.get("/api/account/usage").json()["data"]
        self.assertEqual((usage["account_type"], usage["check_chars_per_check"]), ("visitor", 200))
        self.assertEqual(usage["checks_remaining"], usage["checks_limit"] - 1)

    def test_backstop_defaults_cover_a_whole_book_import(self):
        settings = Stage13Settings.for_test()
        self.assertGreaterEqual(dataclasses.replace(settings).registered_check_chars, 60_000)
        self.assertEqual((settings.visitor_check_chars, settings.registered_imports), (3_000, 1))


if __name__ == "__main__":
    unittest.main()
