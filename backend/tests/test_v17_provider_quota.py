"""A long chapter and a nearly spent provider quota.

A check dispatches at least one request per batch of four claims, and every dispatch counts against the
author's rolling 24-hour provider quota (30 for a guest). A chapter that needed more attempts than
remained used to fail halfway and discard everything it had already judged. Now a check is refused
before any attempt is spent when the quota cannot cover even its minimum, and a quota that still runs
out mid-chapter leaves the unjudged claims undecided while the judged ones are kept.
"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.engine import CONTINUITY_MAX_CLAIMS_PER_BATCH, ContinuityEngine
from app.main import create_app
from app.provider import ProviderDispatchDenied, ProviderResult
from app.stage13 import Stage13Settings

from tests.test_v17_partial_review_results import Poisoned, data

QUOTA = "provider_attempt_quota_exceeded"


class DeniedAfter(Poisoned):
    """Answers the first `allowed` dispatches, then refuses every later one the way the usage guard does."""

    def __init__(self, allowed: int, code: str = QUOTA, concurrency: int | None = None):
        super().__init__(None)
        self.allowed, self.code, self.calls = allowed, code, 0
        if concurrency:
            self.continuity_batch_concurrency = concurrency

    def evaluate(self, request):
        self.calls += 1
        if self.calls > self.allowed:
            raise ProviderDispatchDenied(self.code)
        return super().evaluate(request)


class QuotaRunsOutMidChapterTests(unittest.TestCase):
    def test_judged_batches_are_kept_and_the_rest_is_undecided(self):
        payload = data(12)  # three batches of four
        result = ContinuityEngine(DeniedAfter(1)).execute(payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([item["claim_span_id"] for item in result["issues"]], [f"claim-v17-{index}" for index in range(1, 5)])
        self.assertEqual([row["claim_span_id"] for row in result["undecided_claims"]], [f"claim-v17-{index}" for index in range(5, 13)])
        self.assertEqual({row["error_code"] for row in result["undecided_claims"]}, {QUOTA})
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (1, 1))

    def test_the_same_holds_with_parallel_batches(self):
        result = ContinuityEngine(DeniedAfter(2, concurrency=4)).execute(data(16))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["issues"]) + result["undecided_claim_count"], 16)
        self.assertEqual(len(result["issues"]), 8)

    def test_no_quota_at_all_still_fails_closed(self):
        result = ContinuityEngine(DeniedAfter(0)).execute(data(8))
        self.assertEqual((result["status"], result["error_code"]), ("failed", QUOTA))
        self.assertNotIn("issues", result)

    def test_another_dispatch_refusal_is_still_a_run_failure(self):
        result = ContinuityEngine(DeniedAfter(1, code="usage_context_invalid")).execute(data(12))
        self.assertEqual((result["status"], result["error_code"]), ("failed", "usage_context_invalid"))


class QuotaPreflightApiTests(unittest.TestCase):
    """The API refuses a check the remaining quota cannot cover before any provider attempt."""

    def start(self, attempts: int):
        provider = Poisoned(None)
        root = pathlib.Path(tempfile.mkdtemp(prefix="v17-quota-"))
        settings = dataclasses.replace(Stage13Settings.for_test(), registered_provider_attempts=attempts)
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                         provider=provider, executor=lambda fn, *args: fn(*args), settings=settings)
        client = TestClient(app)
        registered = client.post("/api/auth/register", headers=self.idem(), json={
            "account_name": f"quota{uuid.uuid4().hex[:8]}", "display_name": "Quota", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        project_id = registered["onboarding"]["tutorial"]["project_id"]
        self.addCleanup(client.close)
        return app, client, provider, project_id

    @staticmethod
    def idem():
        return {"Idempotency-Key": str(uuid.uuid4())}

    def save(self, client, project_id, sentences: int):
        draft = client.get(f"/api/projects/{project_id}").json()["data"]["current_draft"]
        body = "".join(f"第{index}句，林默走进港务局。" for index in range(1, sentences + 1))
        response = client.patch(f"/api/projects/{project_id}/drafts/{draft['id']}", headers=self.idem(),
                                json={"title": draft.get("title") or "quota", "body": body, "base_revision": draft["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_a_chapter_the_quota_cannot_cover_is_refused_before_any_attempt(self):
        app, client, provider, project_id = self.start(attempts=2)
        draft = self.save(client, project_id, 3 * CONTINUITY_MAX_CLAIMS_PER_BATCH)
        response = client.post(f"/api/projects/{project_id}/checks", headers=self.idem(),
                               json={"draft_id": draft["id"], "draft_revision": draft["revision"]})
        self.assertEqual(response.status_code, 429, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], "provider_attempt_quota_insufficient")
        self.assertEqual(error["details"], {"claims": 12, "required_min": 3, "remaining": 2})
        self.assertEqual(provider.requests, [])
        with app.state.database.connection() as c:
            attempts = c.execute("SELECT COUNT(*) FROM v2_provider_attempts").fetchone()[0]
            reservations = c.execute("SELECT COUNT(*) FROM v2_usage_reservations").fetchone()[0]
            run = c.execute("SELECT status,error_code FROM v2_runs WHERE run_type='continuity' ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertEqual((attempts, reservations), (0, 0))
        self.assertEqual((run["status"], run["error_code"]), ("failed", "provider_attempt_quota_insufficient"))

    def test_a_chapter_the_quota_covers_runs(self):
        _app, client, provider, project_id = self.start(attempts=3)
        draft = self.save(client, project_id, 3 * CONTINUITY_MAX_CLAIMS_PER_BATCH)
        response = client.post(f"/api/projects/{project_id}/checks", headers=self.idem(),
                               json={"draft_id": draft["id"], "draft_revision": draft["revision"]})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(provider.requests)


if __name__ == "__main__":
    unittest.main()
