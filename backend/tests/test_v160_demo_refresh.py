"""Sample works in existing accounts follow the current seed unless the author changed them (v1.6.0)."""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("SCC_DISABLE_DEFAULT_APP", "1")

from app.config import AppPaths
from app.main import create_app
from app.seed_data import CHAPTER_BODIES, DEMO_SEED_VERSION


class NoNetworkProvider:
    label = model_label = "demo-refresh-stub"
    available = True

    def evaluate(self, request):
        raise AssertionError("The demo refresh must never invoke a provider")


class DemoRefreshTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3080",
            "BACKEND_ORIGIN": "http://127.0.0.1:8080", "TRUSTED_HOSTS": "127.0.0.1:8080,testserver",
            "TRUSTED_ORIGINS": "http://127.0.0.1:3080,http://testserver",
        })
        self.env.start()
        self.temp = tempfile.TemporaryDirectory(prefix="scc-demo-refresh-")
        self.paths = AppPaths.from_project_root(pathlib.Path(self.temp.name), protected_poc_root=pathlib.Path(self.temp.name) / "protected")
        self.app = create_app(self.paths, provider=NoNetworkProvider())
        self.db = self.app.state.database
        visitor = self.app.state.stage13.create_visitor(None) if hasattr(self.app.state, "stage13") else None
        self.assertIsNotNone(visitor, "visitor accounts seed the sample works")
        with self.db.connection() as c:
            self.projects = {row["seed_key"]: row["id"] for row in c.execute("SELECT id,seed_key FROM v2_projects WHERE data_origin='demo_seed'")}
        # Since v1.7.0 a visitor has the one sample work.
        self.assertEqual(set(self.projects), {"grey_harbor"})

    def tearDown(self):
        self.temp.cleanup()
        self.env.stop()

    def age(self, project_id: str) -> None:
        """Make a sample work look as it was seeded before chapter bodies existed."""
        with self.db.connection() as c:
            c.execute("UPDATE v2_chapters SET body='' WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM v2_demo_seed_state WHERE project_id=?", (project_id,))

    def bodies(self, project_id: str) -> list[str]:
        with self.db.connection() as c:
            return [row["body"] for row in c.execute("SELECT body FROM v2_chapters WHERE project_id=? ORDER BY chapter_number", (project_id,))]

    def version(self, project_id: str) -> int | None:
        with self.db.connection() as c:
            row = c.execute("SELECT seed_version FROM v2_demo_seed_state WHERE project_id=?", (project_id,)).fetchone()
            return row["seed_version"] if row else None

    def restart(self) -> None:
        self.db.initialize()

    def test_new_sample_works_start_at_the_current_seed_version(self):
        for project_id in self.projects.values():
            self.assertEqual(self.version(project_id), DEMO_SEED_VERSION)
        self.assertEqual(self.bodies(self.projects["grey_harbor"])[0], CHAPTER_BODIES["ghe-ch-01"])

    def test_an_untouched_old_sample_work_is_recreated_from_the_current_seed(self):
        project_id = self.projects["grey_harbor"]
        self.age(project_id)
        self.assertEqual(set(self.bodies(project_id)), {""})
        self.restart()
        self.assertEqual(self.bodies(project_id)[0], CHAPTER_BODIES["ghe-ch-01"])
        self.assertEqual(self.version(project_id), DEMO_SEED_VERSION)
        with self.db.connection() as c:
            issues = c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=?", (project_id,)).fetchone()[0]
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(issues, 4)

    def test_a_sample_work_the_author_changed_is_left_as_it_is(self):
        project_id = self.projects["grey_harbor"]
        self.age(project_id)
        with self.db.connection() as c:
            draft = c.execute("SELECT * FROM v2_drafts WHERE project_id=?", (project_id,)).fetchone()
            c.execute("INSERT INTO v2_draft_revisions VALUES(?,?,?,?,?,?,?,?)",
                      (draft["id"], 2, draft["title"], "作者自己的改写。", "x", 1, None, draft["saved_at"]))
            c.execute("UPDATE v2_drafts SET body=?,revision=2 WHERE id=?", ("作者自己的改写。", draft["id"]))
        self.restart()
        self.assertEqual(set(self.bodies(project_id)), {""})
        with self.db.connection() as c:
            self.assertEqual(c.execute("SELECT body FROM v2_drafts WHERE project_id=?", (project_id,)).fetchone()["body"], "作者自己的改写。")
        # Recorded, so it is not reconsidered at every start.
        self.assertEqual(self.version(project_id), DEMO_SEED_VERSION)

    def test_the_refresh_runs_once_per_seed_version(self):
        project_id = self.projects["grey_harbor"]
        self.age(project_id)
        self.restart()
        with self.db.connection() as c:
            first = [row["id"] for row in c.execute("SELECT id FROM v2_chapters WHERE project_id=? ORDER BY chapter_number", (project_id,))]
        self.restart()
        with self.db.connection() as c:
            second = [row["id"] for row in c.execute("SELECT id FROM v2_chapters WHERE project_id=? ORDER BY chapter_number", (project_id,))]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
