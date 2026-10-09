"""v1.7.0: one sample work (示例作品) per account, from seed/sample_work.json."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import seed_data
from app.config import AppPaths
from app.main import create_app

BACKEND = pathlib.Path(__file__).resolve().parents[1]


class PublishedSampleWorkTests(unittest.TestCase):
    def test_the_published_sample_work_is_complete_and_consistent(self):
        data = seed_data._load(seed_data.SAMPLE_WORK_PATH)
        self.assertEqual(len(data["chapters"]), 10)
        self.assertEqual(sorted(issue["nature"] for issue in data["draft_issues"]), sorted(seed_data.NATURE_CLASSIFICATION))
        for issue in data["draft_issues"]:
            self.assertIn(issue["sentence"], data["draft"]["body"])
        self.assertLessEqual(len("".join(data["draft"]["body"].split())), 3000, "visitors check at most 3,000 characters")

    def test_the_published_sample_work_seeds_a_full_project(self):
        # Run in a fresh interpreter without the test fixture override, so the published file is used.
        script = textwrap.dedent("""
            import json, pathlib, sys, tempfile, uuid
            from fastapi.testclient import TestClient
            from app.config import AppPaths
            from app.main import create_app
            root = pathlib.Path(tempfile.mkdtemp(prefix="v170-sample-"))
            app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), executor=lambda fn, *args: fn(*args))
            client = TestClient(app)
            data = client.post("/api/auth/register", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
                "account_name": "s" + uuid.uuid4().hex[:8], "display_name": "S", "password": "valid-password-99",
                "recovery_email": uuid.uuid4().hex[:8] + "@example.test"}).json()["data"]
            pid = data["onboarding"]["tutorial"]["project_id"]
            db = app.state.database
            with db.connection() as c:
                count = lambda sql: c.execute(sql, (pid,)).fetchone()[0]
                print(json.dumps({
                    "chapters": count("SELECT COUNT(*) FROM v2_chapters WHERE project_id=?"),
                    "characters": count("SELECT COUNT(*) FROM v2_characters WHERE project_id=?"),
                    "aliases": count("SELECT COUNT(*) FROM v2_character_aliases WHERE project_id=?"),
                    "settings": count("SELECT COUNT(*) FROM v2_world_entries WHERE project_id=?"),
                    "foreshadows": count("SELECT COUNT(*) FROM v2_foreshadows WHERE project_id=?"),
                    "plans": count("SELECT (SELECT COUNT(*) FROM v2_author_story_plans WHERE project_id=?1)+(SELECT COUNT(*) FROM v2_author_character_plans WHERE project_id=?1)+(SELECT COUNT(*) FROM v2_author_world_plans WHERE project_id=?1)"),
                    "considering": count("SELECT COUNT(*) FROM v2_plan_states WHERE project_id=?"),
                    "issues": count("SELECT COUNT(*) FROM v2_issues WHERE project_id=?"),
                    "memory": count("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=?"),
                    "fk": c.execute("PRAGMA foreign_key_check").fetchall() == [],
                }))
            reset = client.post(f"/api/projects/{pid}/reset", headers={"Idempotency-Key": str(uuid.uuid4())}, json={"confirm": True, "reason": "demo_recovery"})
            with db.connection() as c:
                print(json.dumps({"reset": reset.status_code, "foreshadows_after_reset": c.execute("SELECT COUNT(*) FROM v2_foreshadows WHERE project_id=?", (pid,)).fetchone()[0],
                                  "fk_after_reset": c.execute("PRAGMA foreign_key_check").fetchall() == []}))
        """)
        env = {key: value for key, value in os.environ.items() if key != "STORY_SAMPLE_WORK_FILE"}
        env.update({"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3000", "BACKEND_ORIGIN": "http://127.0.0.1:8000",
                    "TRUSTED_HOSTS": "127.0.0.1:8000,testserver", "TRUSTED_ORIGINS": "http://127.0.0.1:3000,http://testserver", "PYTHONIOENCODING": "utf-8"})
        result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        seeded, after_reset = [json.loads(line) for line in result.stdout.strip().splitlines()[-2:]]
        published = seed_data._load(seed_data.SAMPLE_WORK_PATH)
        self.assertEqual(seeded["chapters"], len(published["chapters"]))
        self.assertEqual(seeded["characters"], len(published["characters"]))
        self.assertEqual(seeded["aliases"], sum(len(person.get("aliases") or []) for person in published["characters"]))
        self.assertEqual(seeded["settings"], len(published["settings"]))
        self.assertEqual(seeded["foreshadows"], len(published["foreshadows"]))
        self.assertEqual(seeded["plans"], len(published["plans"]))
        self.assertEqual(seeded["considering"], sum(1 for plan in published["plans"] if plan["status"] == "considering"))
        self.assertEqual(seeded["issues"], 4)
        self.assertEqual(seeded["memory"], len(published["memory"]))
        self.assertTrue(seeded["fk"])
        self.assertEqual((after_reset["reset"], after_reset["foreshadows_after_reset"], after_reset["fk_after_reset"]), (200, len(published["foreshadows"]), True))


class SampleFactReviewTests(unittest.TestCase):
    """The sample check can be taken all the way: decide every finding, review the fact change, record it."""

    def test_only_the_state_update_proposes_a_fact_change_and_it_points_at_the_compass_record(self):
        data = seed_data._load(seed_data.SAMPLE_WORK_PATH)
        proposals = [(issue["nature"], issue["proposed_memory_change"]) for issue in data["draft_issues"] if issue.get("proposed_memory_change")]
        self.assertEqual([nature for nature, _ in proposals], ["state_change"])
        change = proposals[0][1]
        self.assertEqual(change["operation"], "replace")
        records = [(f"sample-memory-{index}", record) for index, record in enumerate(data["memory"], 1)]
        target = dict(records)[change["affected_memory_id"]]
        self.assertEqual((change["memory_type"], change["subject"], change["predicate"]), (target["type"], target["subject"], target["predicate"]))
        self.assertEqual(data["seed_version"], 5)

    def test_deciding_the_sample_findings_leads_to_one_recordable_fact_change(self):
        script = textwrap.dedent("""
            import json, pathlib, tempfile, uuid
            from fastapi.testclient import TestClient
            from app.config import AppPaths
            from app.main import create_app
            root = pathlib.Path(tempfile.mkdtemp(prefix="v170-fact-review-"))
            app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), executor=lambda fn, *args: fn(*args))
            client = TestClient(app)
            headers = lambda: {"Idempotency-Key": str(uuid.uuid4())}
            data = client.post("/api/auth/register", headers=headers(), json={
                "account_name": "f" + uuid.uuid4().hex[:8], "display_name": "F", "password": "valid-password-99",
                "recovery_email": uuid.uuid4().hex[:8] + "@example.test"}).json()["data"]
            pid = data["onboarding"]["tutorial"]["project_id"]
            project = client.get(f"/api/projects/{pid}").json()["data"]
            run = client.get(f"/api/projects/{pid}/checks/{project['latest_run']['run_id']}?include=issues,evidence").json()["data"]
            out = {"flags": {issue["nature"]: issue["has_memory_proposal"] for issue in run["issues"]}}
            def post(path, body):
                response = client.post(f"/api/projects/{pid}{path}", headers=headers(), json=body)
                return response.status_code, response.json()
            # Before any decision there is nothing to review.
            out["early"] = post("/memory/change-sets", {"run_id": run["run_id"], "source_run_revision": run["source_revision"], "resolved_revision": run["current_revision"]})[0]
            # Keeping every finding on purpose except the one that carries the fact change is not enough ...
            for issue in run["issues"]:
                if issue["nature"] == "state_change" or "keep_intentional" not in (issue.get("available_actions") or []):
                    continue
                post(f"/issues/{issue['id']}/decision", {"run_id": run["run_id"], "source_revision": run["source_revision"], "decision": "false_positive"})
            state = next(issue for issue in run["issues"] if issue["nature"] == "state_change")
            post(f"/issues/{state['id']}/decision", {"run_id": run["run_id"], "source_revision": run["source_revision"], "decision": "keep_intentional"})
            code, body = post("/memory/change-sets", {"run_id": run["run_id"], "source_run_revision": run["source_revision"], "resolved_revision": run["current_revision"]})
            out["review"] = code
            change_set = body["data"]["change_set"]
            out["items"] = [{"operation": item["operation"], "value": item["after"]["value"], "before": item["before"]["subject"]} for item in change_set["items"]]
            before_version = client.get(f"/api/projects/{pid}").json()["data"]["current_memory_version"]
            code, body = post(f"/memory/change-sets/{change_set['id']}/commit", {"confirm": True, "accepted_item_ids": [item["id"] for item in change_set["items"]], "rejected_item_ids": []})
            out["commit"] = code
            out["version_step"] = client.get(f"/api/projects/{pid}").json()["data"]["current_memory_version"] - before_version
            # ... and when the state update is not kept as a change, there is nothing to record at all.
            second = client.post("/api/auth/register", headers=headers(), json={
                "account_name": "g" + uuid.uuid4().hex[:8], "display_name": "G", "password": "valid-password-99",
                "recovery_email": uuid.uuid4().hex[:8] + "@example.test"}).json()["data"]
            pid = second["onboarding"]["tutorial"]["project_id"]
            project = client.get(f"/api/projects/{pid}").json()["data"]
            run = client.get(f"/api/projects/{pid}/checks/{project['latest_run']['run_id']}?include=issues,evidence").json()["data"]
            for issue in run["issues"]:
                if "false_positive" in (issue.get("available_actions") or []):
                    post(f"/issues/{issue['id']}/decision", {"run_id": run["run_id"], "source_revision": run["source_revision"], "decision": "false_positive"})
            code, body = post("/memory/change-sets", {"run_id": run["run_id"], "source_run_revision": run["source_revision"], "resolved_revision": run["current_revision"]})
            out["none"] = [code, body["error"]["code"]]
            print(json.dumps(out, ensure_ascii=False))
        """)
        env = {key: value for key, value in os.environ.items() if key != "STORY_SAMPLE_WORK_FILE"}
        env.update({"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3000", "BACKEND_ORIGIN": "http://127.0.0.1:8000",
                    "TRUSTED_HOSTS": "127.0.0.1:8000,testserver", "TRUSTED_ORIGINS": "http://127.0.0.1:3000,http://testserver", "PYTHONIOENCODING": "utf-8"})
        result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        out = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(out["flags"], {"confirmed_conflict": False, "state_change": True, "possible_conflict": False, "insufficient_evidence": False})
        self.assertEqual(out["early"], 409, "undecided findings still block the review")
        self.assertEqual((out["review"], out["commit"], out["version_step"]), (201, 200, 1), out)
        self.assertEqual(out["items"], [{"operation": "replace", "value": "放在档案室的桌上", "before": "黄铜罗盘"}])
        self.assertEqual(out["none"], [422, "no_reviewable_changes"])


class SingleSampleMigrationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3000", "BACKEND_ORIGIN": "http://127.0.0.1:8000",
            "TRUSTED_HOSTS": "127.0.0.1:8000,testserver", "TRUSTED_ORIGINS": "http://127.0.0.1:3000,http://testserver"})
        self.env.start()
        self.addCleanup(self.env.stop)
        root = pathlib.Path(tempfile.mkdtemp(prefix="v170-migration-"))
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), executor=lambda fn, *args: fn(*args))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.db = self.app.state.database

    def register(self):
        data = self.client.post("/api/auth/register", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
            "account_name": f"m{uuid.uuid4().hex[:8]}", "display_name": "M", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        return data["user"]["id"], data["onboarding"]["tutorial"]["project_id"]

    def samples(self, user_id):
        with self.db.connection() as c:
            return [dict(row) for row in c.execute("SELECT id,data_origin,seed_key FROM v2_projects WHERE user_id=? AND data_origin IN ('demo_seed','tutorial_seed')", (user_id,))]

    def test_every_account_ends_with_one_sample_work_and_the_migration_runs_once(self):
        author, tutorial = self.register()
        old_account, old_tutorial = self.register()
        with self.db.connection() as c:
            # An author who edited the tutorial and also has the three pre-tutorial demo works.
            c.execute("UPDATE v2_drafts SET body='作者改过的草稿。' WHERE project_id=?", (tutorial,))
            for seed_key, title in (("grey_harbor", "灰港回声"), ("paper_moon", "纸月档案"), ("zero_garden", "零点花园")):
                self.db._create_project(c, author, title, "", "", "demo_seed", seed_key)
            # An account from before the tutorial: demo works only, tour still marked active.
            self.db.purge_project(c, old_tutorial)
            c.execute("UPDATE v2_users SET onboarding_tutorial_project_id=NULL,onboarding_status='active' WHERE id=?", (old_account,))
            for seed_key, title in (("paper_moon", "纸月档案"), ("zero_garden", "零点花园")):
                self.db._create_project(c, old_account, title, "", "", "demo_seed", seed_key)
            real = self.db._create_project(c, author, "我自己的书", "", "", "user_created")
            c.execute("DELETE FROM v2_release_migrations WHERE name='v170_single_sample'")
        self.db.initialize()
        with self.db.connection() as c:
            for user_id in (author, old_account):
                samples = self.samples(user_id)
                self.assertEqual([row["data_origin"] for row in samples], ["tutorial_seed"])
                pointer = c.execute("SELECT onboarding_tutorial_project_id FROM v2_users WHERE id=?", (user_id,)).fetchone()[0]
                self.assertEqual(pointer, samples[0]["id"])
                draft = c.execute("SELECT body FROM v2_drafts WHERE project_id=?", (samples[0]["id"],)).fetchone()["body"]
                self.assertEqual(draft, seed_data.DRAFT["body"], "edited sample works are replaced too")
            self.assertEqual(c.execute("SELECT onboarding_status FROM v2_users WHERE id=?", (old_account,)).fetchone()[0], "skipped")
            self.assertTrue(c.execute("SELECT 1 FROM v2_projects WHERE id=?", (real,)).fetchone(), "real works are never touched")
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        before = self.samples(author)
        self.db.initialize()
        self.assertEqual(self.samples(author), before, "the migration runs once")

    def test_visitors_get_one_sample_work(self):
        visitor = self.app.state.stage13.create_visitor(None)
        self.assertEqual(len(visitor["seeded_projects"]), 1)
        with self.db.connection() as c:
            row = c.execute("SELECT data_origin,seed_key FROM v2_projects WHERE id=?", (visitor["seeded_projects"][0]["id"],)).fetchone()
        self.assertEqual((row["data_origin"], row["seed_key"]), ("demo_seed", "grey_harbor"))


if __name__ == "__main__":
    unittest.main()
