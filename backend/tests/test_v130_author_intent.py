from __future__ import annotations

import json
import pathlib
import sqlite3
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


class CapturingProvider:
    available = True
    label = "v130-injected-stub"
    model_label = "v130-stub-model"

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def evaluate(self, request: dict) -> ProviderResult:
        self.requests.append(request)
        return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1, latency_ms=1)


class V130AuthorIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-author-intent-"))
        self.paths = AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected")
        self.provider = CapturingProvider()
        self.app = create_app(
            self.paths,
            provider=self.provider,
            executor=lambda fn, *args: fn(*args),
            settings=Stage13Settings.for_test(),
        )
        self.client = TestClient(self.app)
        registered = self._register(self.client, "v130-owner")
        self.user_id = registered["user"]["id"]
        self.tutorial_id = registered["onboarding"]["tutorial"]["project_id"]
        created = self.client.post("/api/projects", headers=idem(), json={"title": "Author Intent Empty"})
        self.assertEqual(created.status_code, 201, created.text)
        self.project_id = created.json()["data"]["project"]["id"]

    def _register(self, client: TestClient, account: str) -> dict:
        response = client.post(
            "/api/auth/register",
            headers=idem(),
            json={"account_name": account, "display_name": "Author", "password": "safe-password-v130", "recovery_email": f"{account}@example.test"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["data"]

    def _create_story(self, version: int, title: str = "Return to Grey Harbor", key: str | None = None):
        return self.client.post(
            f"/api/projects/{self.project_id}/author-intent/story-plans",
            headers=idem(key),
            json={
                "base_author_context_version": version,
                "title": title,
                "summary": "The crew returns.",
                "goal": "Resolve the bell mystery.",
                "status": "planned",
                "target_chapter_number": 12,
            },
        )

    def test_empty_state_and_tutorial_are_real_empty_not_seeded_intent(self):
        digests = set()
        for project_id in (self.project_id, self.tutorial_id):
            response = self.client.get(f"/api/projects/{project_id}/author-intent")
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()["data"]
            self.assertEqual(data["author_context_version"], 0)
            self.assertEqual((data["version"], data["parent_version"]), (0, None))
            self.assertEqual(len(data["snapshot_digest"]), 64)
            digests.add(data["snapshot_digest"])
            self.assertEqual((data["story_plans"], data["character_plans"], data["world_plans"]), ([], [], []))
        self.assertEqual(len(digests), 1)
        project = self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        self.assertEqual(project["author_context_version"], 0)

    def test_three_semantic_cruds_reorder_archive_and_monotonic_version(self):
        first = self._create_story(0)
        self.assertEqual(first.status_code, 201, first.text)
        first_id = first.json()["data"]["item"]["id"]
        second = self._create_story(1, "Second Arc")
        second_id = second.json()["data"]["item"]["id"]
        character = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/character-plans",
            headers=idem(),
            json={"base_author_context_version": 2, "name": "Wen Lan", "role_type": "ally", "goal": "Decode the tide table", "planned_state": "Keeps the compass", "notes": "Do not resolve early"},
        )
        self.assertEqual(character.status_code, 201, character.text)
        character_id = character.json()["data"]["item"]["id"]
        world = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/world-plans",
            headers=idem(),
            json={"base_author_context_version": 3, "name": "North Tide Gate", "category": "rule", "description": "Opens only after the fog bell.", "notes": "Fixed rule"},
        )
        self.assertEqual(world.status_code, 201, world.text)
        world_id = world.json()["data"]["item"]["id"]
        story_edited = self.client.patch(
            f"/api/projects/{self.project_id}/author-intent/story-plans/{first_id}",
            headers=idem(),
            json={"base_author_context_version": 4, "goal": "Resolve the bell mystery without changing canon."},
        )
        self.assertEqual((story_edited.status_code, story_edited.json()["data"]["author_context_version"]), (200, 5))
        character_edited = self.client.patch(
            f"/api/projects/{self.project_id}/author-intent/character-plans/{character_id}",
            headers=idem(),
            json={"base_author_context_version": 5, "planned_state": "Has handed over the compass"},
        )
        self.assertEqual((character_edited.status_code, character_edited.json()["data"]["author_context_version"]), (200, 6))
        world_edited = self.client.patch(
            f"/api/projects/{self.project_id}/author-intent/world-plans/{world_id}",
            headers=idem(),
            json={"base_author_context_version": 6, "notes": "Rule remains author intent only"},
        )
        self.assertEqual((world_edited.status_code, world_edited.json()["data"]["author_context_version"]), (200, 7))
        reordered = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/story-plans/reorder",
            headers=idem(),
            json={"base_author_context_version": 7, "ordered_ids": [second_id, first_id]},
        )
        self.assertEqual([item["id"] for item in reordered.json()["data"]["story_plans"]], [second_id, first_id])
        world_archived = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/world-plans/{world_id}/archive",
            headers=idem(),
            json={"base_author_context_version": 8, "confirm": True},
        )
        self.assertEqual((world_archived.status_code, world_archived.json()["data"]["author_context_version"], world_archived.json()["data"]["item"]["archived"]), (200, 9, True))
        character_archived = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/character-plans/{character_id}/archive",
            headers=idem(),
            json={"base_author_context_version": 9, "confirm": True},
        )
        story_archived = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/story-plans/{first_id}/archive",
            headers=idem(),
            json={"base_author_context_version": 10, "confirm": True},
        )
        self.assertEqual((character_archived.status_code, story_archived.status_code, story_archived.json()["data"]["author_context_version"]), (200, 200, 11))
        active = self.client.get(f"/api/projects/{self.project_id}/author-intent").json()["data"]
        all_items = self.client.get(f"/api/projects/{self.project_id}/author-intent?include_archived=true").json()["data"]
        self.assertEqual(active["world_plans"], [])
        self.assertEqual(active["character_plans"], [])
        self.assertEqual([item["id"] for item in active["story_plans"]], [second_id])
        self.assertEqual((len(all_items["world_plans"]), all_items["world_plans"][0]["id"]), (1, world_id))
        self.assertEqual((len(all_items["character_plans"]), len(all_items["story_plans"])), (1, 2))
        self.assertEqual(all_items["author_context_version"], 11)

    def test_conflict_idempotency_validation_and_owner_isolation(self):
        key = str(uuid.uuid4())
        first = self._create_story(0, key=key)
        replay = self._create_story(0, key=key)
        self.assertEqual((first.status_code, replay.status_code), (201, 201))
        self.assertEqual(first.json()["data"], replay.json()["data"])
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/author-intent").json()["data"]["author_context_version"], 1)
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_author_context_versions WHERE project_id=?",(self.project_id,)).fetchone()[0], 2)
        changed_replay = self._create_story(0, "Different", key)
        self.assertEqual((changed_replay.status_code, changed_replay.json()["error"]["code"]), (409, "idempotency_conflict"))
        stale = self._create_story(0, "Stale")
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (409, "author_context_version_conflict"))
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_author_context_versions WHERE project_id=?",(self.project_id,)).fetchone()[0], 2)
        unknown = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/world-plans",
            headers=idem(),
            json={"base_author_context_version": 1, "name": "Rule", "category": "rule", "description": "Valid", "unexpected": True},
        )
        invalid_enum = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/character-plans",
            headers=idem(),
            json={"base_author_context_version": 1, "name": "A", "role_type": "wizard"},
        )
        too_long = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/story-plans",
            headers=idem(),
            json={"base_author_context_version": 1, "title": "x" * 121, "status": "planned"},
        )
        null_patch = self.client.patch(
            f"/api/projects/{self.project_id}/author-intent/story-plans/{first.json()['data']['item']['id']}",
            headers=idem(),
            json={"base_author_context_version": 1, "summary": None},
        )
        bad_reorder = self.client.post(
            f"/api/projects/{self.project_id}/author-intent/story-plans/reorder",
            headers=idem(),
            json={"base_author_context_version": 1, "ordered_ids": []},
        )
        self.assertEqual((unknown.status_code, invalid_enum.status_code, too_long.status_code, null_patch.status_code, bad_reorder.status_code), (400, 400, 400, 422, 422))
        outsider = TestClient(self.app)
        self._register(outsider, "v130-outsider")
        self.assertEqual(outsider.get(f"/api/projects/{self.project_id}/author-intent").status_code, 404)
        denied = outsider.post(
            f"/api/projects/{self.project_id}/author-intent/story-plans",
            headers=idem(),
            json={"base_author_context_version": 1, "title": "Steal", "status": "planned"},
        )
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (404, "resource_not_found"))

    def test_run_binds_version_but_author_intent_never_enters_story_memory_or_provider_input(self):
        project = self.client.get(f"/api/projects/{self.tutorial_id}").json()["data"]
        with self.app.state.database.connection() as c:
            before = {
                table: c.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (self.tutorial_id,)).fetchone()[0]
                for table in ("v2_memory_records", "v2_outline_nodes", "v2_characters", "v2_world_entries")
            }
            memory_before = [tuple(row) for row in c.execute("SELECT * FROM v2_memory_records WHERE project_id=? ORDER BY id", (self.tutorial_id,)).fetchall()]
        created = self.client.post(
            f"/api/projects/{self.tutorial_id}/author-intent/story-plans",
            headers=idem(),
            json={"base_author_context_version": 0, "title": "SECRET AUTHOR PLAN", "status": "planned"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        run = self.client.post(
            f"/api/projects/{self.tutorial_id}/checks",
            headers=idem(),
            json={"draft_id": project["current_draft"]["id"], "draft_revision": project["current_draft"]["revision"]},
        )
        self.assertEqual(run.status_code, 202, run.text)
        run_id = run.json()["data"]["run_id"]
        viewed = self.client.get(f"/api/projects/{self.tutorial_id}/checks/{run_id}?include=metrics").json()["data"]
        self.assertEqual((run.json()["data"]["author_context_version"], viewed["author_context_version"], viewed["author_context_version_status"]), (1, 1, "recorded"))
        version_one=self.client.get(f"/api/projects/{self.tutorial_id}/author-intent?version=1&include_archived=true").json()["data"]
        self.assertEqual((viewed["author_context_resolvable"],viewed["author_context_snapshot_digest"]),(True,version_one["snapshot_digest"]))
        advanced=self.client.post(
            f"/api/projects/{self.tutorial_id}/author-intent/story-plans",headers=idem(),
            json={"base_author_context_version":1,"title":"Later plan","status":"planned"},
        )
        self.assertEqual(advanced.json()["data"]["author_context_version"],2)
        viewed_after=self.client.get(f"/api/projects/{self.tutorial_id}/checks/{run_id}").json()["data"]
        self.assertEqual((viewed_after["author_context_version"],viewed_after["author_context_snapshot_digest"]),(1,version_one["snapshot_digest"]))
        self.assertGreaterEqual(len(self.provider.requests), 1)
        request_text = json.dumps(self.provider.requests[-1], ensure_ascii=False, sort_keys=True)
        self.assertNotIn("SECRET AUTHOR PLAN", request_text)
        self.assertNotIn("author_context", request_text)
        with self.app.state.database.connection() as c:
            c.execute("UPDATE v2_runs SET author_context_snapshot_digest='tampered-digest' WHERE id=?",(run_id,))
        self.app.state.database.initialize()
        unresolved=self.client.get(f"/api/projects/{self.tutorial_id}/checks/{run_id}").json()["data"]
        self.assertEqual((unresolved["author_context_version_status"],unresolved["author_context_resolvable"],unresolved["author_context_snapshot_digest"]),("unresolvable",False,None))
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT author_context_snapshot_digest FROM v2_runs WHERE id=?",(run_id,)).fetchone()[0],"tampered-digest")
        with self.app.state.database.connection() as c:
            after = {
                table: c.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (self.tutorial_id,)).fetchone()[0]
                for table in ("v2_memory_records", "v2_outline_nodes", "v2_characters", "v2_world_entries")
            }
            memory_after = [tuple(row) for row in c.execute("SELECT * FROM v2_memory_records WHERE project_id=? ORDER BY id", (self.tutorial_id,)).fetchall()]
            c.execute("UPDATE v2_runs SET author_context_version=NULL,author_context_snapshot_digest=NULL WHERE id=?", (run_id,))
        self.assertEqual((before, memory_before), (after, memory_after))
        historical = self.client.get(f"/api/projects/{self.tutorial_id}/checks/{run_id}").json()["data"]
        self.assertIsNone(historical["author_context_version"])
        self.assertEqual(historical["author_context_version_status"], "not_recorded")
        self.assertEqual((historical["author_context_resolvable"],historical["author_context_snapshot_digest"]),(False,None))

    def test_existing_database_migrates_projects_to_zero_and_old_runs_to_null(self):
        with self.app.state.database.connection() as c:
            c.execute("ALTER TABLE v2_runs DROP COLUMN author_context_snapshot_digest")
            c.execute("ALTER TABLE v2_runs DROP COLUMN author_context_version")
            c.execute("ALTER TABLE v2_projects DROP COLUMN author_context_version")
            c.execute("DELETE FROM schema_migrations WHERE version=130")
            c.execute("DELETE FROM schema_migrations WHERE version=131")
        self.app.state.database.initialize()
        with self.app.state.database.connection() as c:
            project_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_projects)")}
            run_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_runs)")}
            project_versions = {row[0] for row in c.execute("SELECT author_context_version FROM v2_projects").fetchall()}
            run_versions = {row[0] for row in c.execute("SELECT author_context_version FROM v2_runs").fetchall()}
            run_digests = {row[0] for row in c.execute("SELECT author_context_snapshot_digest FROM v2_runs").fetchall()}
            migration_count = c.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=130").fetchone()[0]
            snapshot_migration_count = c.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=131").fetchone()[0]
        self.assertIn("author_context_version", project_columns)
        self.assertIn("author_context_version", run_columns)
        self.assertIn("author_context_snapshot_digest", run_columns)
        self.assertEqual(project_versions, {0})
        self.assertEqual(run_versions, {None})
        self.assertEqual(run_digests, {None})
        self.assertEqual(migration_count, 1)
        self.assertEqual(snapshot_migration_count, 1)

    def test_immutable_history_digest_and_project_scoped_version_reads(self):
        first=self._create_story(0,"Original Arc")
        first_data=first.json()["data"]; first_id=first_data["item"]["id"]
        second=self._create_story(1,"Later Arc")
        second_data=second.json()["data"]; second_id=second_data["item"]["id"]
        edited=self.client.patch(
            f"/api/projects/{self.project_id}/author-intent/story-plans/{first_id}",headers=idem(),
            json={"base_author_context_version":2,"title":"Edited Arc"},
        ).json()["data"]
        reordered=self.client.post(
            f"/api/projects/{self.project_id}/author-intent/story-plans/reorder",headers=idem(),
            json={"base_author_context_version":3,"ordered_ids":[second_id,first_id]},
        ).json()["data"]
        archived=self.client.post(
            f"/api/projects/{self.project_id}/author-intent/story-plans/{first_id}/archive",headers=idem(),
            json={"base_author_context_version":4,"confirm":True},
        ).json()["data"]
        self.assertEqual(len({first_data["snapshot_digest"],second_data["snapshot_digest"],edited["snapshot_digest"],reordered["snapshot_digest"],archived["snapshot_digest"]}),5)
        v1=self.client.get(f"/api/projects/{self.project_id}/author-intent?version=1&include_archived=true").json()["data"]
        v2=self.client.get(f"/api/projects/{self.project_id}/author-intent?version=2&include_archived=true").json()["data"]
        v4=self.client.get(f"/api/projects/{self.project_id}/author-intent?version=4&include_archived=true").json()["data"]
        v5=self.client.get(f"/api/projects/{self.project_id}/author-intent?version=5&include_archived=true").json()["data"]
        self.assertEqual((v1["story_plans"][0]["title"],v1["story_plans"][0]["archived"]),("Original Arc",False))
        self.assertEqual([item["title"] for item in v2["story_plans"]],["Original Arc","Later Arc"])
        self.assertEqual([item["id"] for item in v4["story_plans"]],[second_id,first_id])
        self.assertEqual((v5["story_plans"][1]["id"],v5["story_plans"][1]["archived"]),(first_id,True))
        self.assertEqual(v1["snapshot_digest"],first_data["snapshot_digest"])
        self.app.state.database.initialize()
        stable=self.client.get(f"/api/projects/{self.project_id}/author-intent?version=1&include_archived=true").json()["data"]
        self.assertEqual(stable,v1)
        other=self.client.post("/api/projects",headers=idem(),json={"title":"Other version scope"}).json()["data"]["project"]["id"]
        missing=self.client.get(f"/api/projects/{other}/author-intent?version=1")
        self.assertEqual((missing.status_code,missing.json()["error"]["code"]),(404,"author_context_version_not_found"))
        outsider=TestClient(self.app); self._register(outsider,"v130-history-outsider")
        self.assertEqual(outsider.get(f"/api/projects/{self.project_id}/author-intent?version=1").status_code,404)

    def test_snapshot_failure_rolls_back_live_rows_version_and_metadata(self):
        created=self._create_story(0,"Rollback Arc").json()["data"]
        item_id=created["item"]["id"]; db=self.app.state.database
        with db.connection() as c:
            before_item=dict(c.execute("SELECT * FROM v2_author_story_plans WHERE id=?",(item_id,)).fetchone())
            before_project=dict(c.execute("SELECT * FROM v2_projects WHERE id=?",(self.project_id,)).fetchone())
            before_versions=c.execute("SELECT COUNT(*) FROM v2_author_context_versions WHERE project_id=?",(self.project_id,)).fetchone()[0]
        original=db._write_author_context_snapshot
        def fail_snapshot(*_args,**_kwargs):raise sqlite3.OperationalError("injected_snapshot_failure")
        db._write_author_context_snapshot=fail_snapshot
        try:
            failed=self.client.patch(
                f"/api/projects/{self.project_id}/author-intent/story-plans/{item_id}",headers=idem(),
                json={"base_author_context_version":1,"title":"Must Roll Back"},
            )
        finally:
            db._write_author_context_snapshot=original
        self.assertEqual(failed.status_code,503,failed.text)
        with db.connection() as c:
            after_item=dict(c.execute("SELECT * FROM v2_author_story_plans WHERE id=?",(item_id,)).fetchone())
            after_project=dict(c.execute("SELECT * FROM v2_projects WHERE id=?",(self.project_id,)).fetchone())
            after_versions=c.execute("SELECT COUNT(*) FROM v2_author_context_versions WHERE project_id=?",(self.project_id,)).fetchone()[0]
        self.assertEqual(after_item,before_item)
        self.assertEqual(after_project["author_context_version"],before_project["author_context_version"])
        self.assertEqual(after_versions,before_versions)

    def test_mutable_only_migration_freezes_current_snapshot_and_is_idempotent(self):
        created=self._create_story(0,"Migrated Mutable Arc").json()["data"]
        with self.app.state.database.connection() as c:
            for table in ("v2_author_story_plan_versions","v2_author_character_plan_versions","v2_author_world_plan_versions"):
                c.execute(f"DELETE FROM {table} WHERE project_id=?",(self.project_id,))
            c.execute("DELETE FROM v2_author_context_versions WHERE project_id=?",(self.project_id,))
            c.execute("DELETE FROM schema_migrations WHERE version=131")
        self.app.state.database.initialize()
        migrated=self.client.get(f"/api/projects/{self.project_id}/author-intent?version=1&include_archived=true").json()["data"]
        self.assertEqual((migrated["story_plans"][0]["title"],migrated["parent_version"]),("Migrated Mutable Arc",0))
        first_digest=migrated["snapshot_digest"]
        self.app.state.database.initialize()
        repeated=self.client.get(f"/api/projects/{self.project_id}/author-intent?version=1&include_archived=true").json()["data"]
        self.assertEqual(repeated["snapshot_digest"],first_digest)
        with self.app.state.database.connection() as c:
            versions=c.execute("SELECT version,COUNT(*) count FROM v2_author_context_versions WHERE project_id=? GROUP BY version ORDER BY version",(self.project_id,)).fetchall()
        self.assertEqual([(row["version"],row["count"]) for row in versions],[(0,1),(1,1)])
        self.assertEqual(first_digest,created["snapshot_digest"])

    def test_reset_clears_only_target_author_history(self):
        self._create_story(0,"Reset Target")
        other=self.client.post("/api/projects",headers=idem(),json={"title":"Reset Other"}).json()["data"]["project"]["id"]
        other_created=self.client.post(
            f"/api/projects/{other}/author-intent/story-plans",headers=idem(),
            json={"base_author_context_version":0,"title":"Keep Other","status":"planned"},
        ).json()["data"]
        reset=self.client.post(f"/api/projects/{self.project_id}/reset",headers=idem(),json={"confirm":True,"reason":"fresh_start"})
        self.assertEqual((reset.status_code,reset.json()["data"]["author_context_version"]),(200,0))
        target=self.client.get(f"/api/projects/{self.project_id}/author-intent?version=0").json()["data"]
        self.assertEqual(target["story_plans"],[])
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/author-intent?version=1").status_code,404)
        preserved=self.client.get(f"/api/projects/{other}/author-intent?version=1").json()["data"]
        self.assertEqual((preserved["story_plans"][0]["title"],preserved["snapshot_digest"]),("Keep Other",other_created["snapshot_digest"]))


if __name__ == "__main__":
    unittest.main()
