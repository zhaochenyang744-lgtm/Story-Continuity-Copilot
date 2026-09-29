"""The per-project token guard is a rolling 24-hour window sized for thinking review.

Live smoke (2026-09-29): the guard summed every run the project ever had against 40,000 tokens. One
incremental review with thinking used about 61,000, after which every AI feature of that project
failed as budget_guard_exceeded for good.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from app.config import AppPaths
from app.engine import ContinuityEngine, MemoryDeltaEngine
from app.v2_database import PROJECT_TOKEN_LIMIT_24H, V2Database


class Stub:
    label = "stub"
    model_label = "stub"
    available = True


class ProjectTokenWindowTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v14-window-"))
        self.db = V2Database(AppPaths.from_project_root(root, protected_poc_root=root / "protected")); self.db.initialize()
        registered, _ = self.db.register({"account_name": f"window{uuid.uuid4().hex[:8]}", "display_name": "Window",
                                          "password": "window-local-password-123"}, str(uuid.uuid4()))
        user = registered["user"]["id"]
        with self.db.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            self.project = self.db._create_project(c, user, "零点花园", "科幻", "s", "demo_seed", "zero_garden")
        draft = self.db.project(user, self.project)["current_draft"]
        patched, _ = self.db.patch_draft(user, self.project, draft["id"], {"body": "凌晨三点，萤苔发出蓝光。", "base_revision": draft["revision"]},
                                         str(uuid.uuid4()))
        run, _, _ = self.db.create_run(user, self.project, {"draft_id": draft["id"], "draft_revision": patched["revision"]},
                                       str(uuid.uuid4()), ContinuityEngine(Stub()).provenance())
        self.run = run["run_id"]

    def spend(self, tokens, hours_ago):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        with self.db.connection() as c:
            c.execute("UPDATE v2_runs SET input_tokens=?,output_tokens=0,created_at=? WHERE id=?", (tokens, stamp, self.run))

    def test_one_long_thinking_review_no_longer_exhausts_the_project(self):
        self.spend(61_000, hours_ago=0)
        self.assertFalse(self.db.session_budget_exhausted(self.project))

    def test_the_limit_applies_within_24_hours_and_expires_after(self):
        self.spend(PROJECT_TOKEN_LIMIT_24H, hours_ago=1)
        self.assertTrue(self.db.session_budget_exhausted(self.project))
        self.spend(PROJECT_TOKEN_LIMIT_24H, hours_ago=25)
        self.assertFalse(self.db.session_budget_exhausted(self.project))
        self.spend(PROJECT_TOKEN_LIMIT_24H - 1, hours_ago=2)
        self.assertFalse(self.db.session_budget_exhausted(self.project))


class MemoryDeltaSchemaTests(unittest.TestCase):
    def test_schema_states_the_lengths_the_validator_enforces(self):
        request = MemoryDeltaEngine(Stub())._request({"source_revision": 2, "sources": [], "memory": []})
        candidate = request["output_schema"]["candidates"][0]
        self.assertIn("at most 240 characters", candidate["invalidation_reason"])
        self.assertIn("at most 240 characters", candidate["value"])
        self.assertIn("at most 80 characters", candidate["subject"])


if __name__ == "__main__":
    unittest.main()
