"""v1.7.0: writing analyses read plans from the plan tables, and author materials are gone.

Before v1.7.0 the analyses read plans through a one-time mirror into author materials: a plan edited
after it was first mirrored dropped out of the analyses, and no plan's target chapter reached them.
"""
from __future__ import annotations

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
from app.v2_database import V2Database

MATERIAL_TABLES = ("v2_author_materials", "v2_author_material_versions", "v2_author_comparisons", "v2_author_comparison_decisions")


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


class RecordingProvider:
    available = True
    label = "plans-stub"
    model_label = "plans-stub-model"

    def __init__(self):
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        planned = request["layers"]["planned"]["story_plans"]
        if request.get("task") == "plan_alignment":
            claim = request["layers"]["written"]["draft_claims"][0]
            return ProviderResult({"summary": "已对照。", "items": [
                {"story_plan_id": plan["id"], "status": "planned_covered", "explanation": "写到了。",
                 "evidence": [{"source_type": "draft_claim", "source_id": claim["id"]}]} for plan in planned]}, 10, 5, latency_ms=1)
        source = {"source_type": "author_context", "source_id": planned[0]["id"]} if planned else {"source_type": "draft_claim", "source_id": request["layers"]["written"]["draft_claims"][0]["id"]}
        return ProviderResult({"summary": "写前回顾。", "summary_sources": [source],
                               "items": [{"section": "related_plan" if planned else "recent_source", "text": "延续计划。", "sources": [source]}]}, 10, 5, latency_ms=1)


class PlansReachAnalysesTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v170-plans-"))
        self.root = root
        self.provider = RecordingProvider()
        self.client = TestClient(create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=self.provider,
                                            executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test()))
        registered = self.client.post("/api/auth/register", headers=idem(), json={"account_name": "plans-owner", "display_name": "Author",
                                                                                  "password": "safe-password-v170", "recovery_email": "plans@example.test"})
        self.assertEqual(registered.status_code, 201, registered.text)
        self.project_id = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        self.project = self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        draft = self.project["current_draft"]
        saved = self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}", headers=idem(),
                                  json={"base_revision": draft["revision"], "body": "林默带着潮汐表返回雾港。她听见北门的雾钟。"})
        self.assertEqual(saved.status_code, 200, saved.text)

    def _project(self):
        return self.client.get(f"/api/projects/{self.project_id}").json()["data"]

    def _plan(self, path, body):
        response = self.client.post(f"/api/projects/{self.project_id}/author-intent/{path}", headers=idem(),
                                    json={"base_author_context_version": self._project()["author_context_version"], **body})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["data"]["item"]["id"]

    def _analysis(self, kind):
        draft = self._project()["current_draft"]
        return self.client.post(f"/api/projects/{self.project_id}/analyses", headers=idem(),
                                json={"analysis_type": kind, "draft_id": draft["id"], "draft_revision": draft["revision"]})

    def _planned_layer(self, kind="context_brief"):
        before = len(self.provider.requests)
        started = self._analysis(kind)
        self.assertEqual(started.status_code, 202, started.text)
        self.assertEqual(len(self.provider.requests), before + 1)
        return self.provider.requests[-1]["layers"]["planned"]

    def test_an_edited_plan_reaches_the_analysis_with_its_fields_and_target_chapter(self):
        chapter = self._project()["current_draft"]["chapter_number"]
        story = self._plan("story-plans", {"title": "返航", "summary": "本章完成返航。", "goal": "让返航落到正文。", "status": "in_progress",
                                           "target_chapter_number": chapter})
        self._planned_layer()
        edited = self.client.patch(f"/api/projects/{self.project_id}/author-intent/story-plans/{story}", headers=idem(),
                                   json={"base_author_context_version": self._project()["author_context_version"], "summary": "改过的返航计划。"})
        self.assertEqual(edited.status_code, 200, edited.text)
        planned = self._planned_layer()
        item = next(plan for plan in planned["story_plans"] if plan["id"] == story)
        self.assertEqual((item["summary"], item["goal"], item["status"], item["target_chapter_number"]),
                         ("改过的返航计划。", "让返航落到正文。", "in_progress", chapter))

    def test_character_and_world_plans_keep_their_own_fields(self):
        character = self._plan("character-plans", {"name": "林默", "role_type": "protagonist", "goal": "找到父亲", "planned_state": "开始怀疑潮汐表"})
        world = self._plan("world-plans", {"name": "北门雾钟", "category": "rule", "description": "只在闸门关闭后敲响"})
        planned = self._planned_layer()
        self.assertEqual([(item["id"], item["role_type"], item["planned_state"]) for item in planned["character_plans"]],
                         [(character, "protagonist", "开始怀疑潮汐表")])
        self.assertEqual([(item["id"], item["category"], item["description"]) for item in planned["world_plans"]],
                         [(world, "rule", "只在闸门关闭后敲响")])

    def test_considering_and_archived_plans_stay_out_and_alignment_needs_a_decided_plan(self):
        considering = self._plan("story-plans", {"title": "也许以后", "summary": "还在想。"})
        archived = self._plan("story-plans", {"title": "放弃的线", "summary": "不写了。"})
        state = self.client.post(f"/api/projects/{self.project_id}/plan-states", headers=idem(),
                                 json={"kind": "story", "plan_id": considering, "considering": True})
        self.assertEqual(state.status_code, 200, state.text)
        gone = self.client.post(f"/api/projects/{self.project_id}/author-intent/story-plans/{archived}/archive", headers=idem(),
                                json={"base_author_context_version": self._project()["author_context_version"], "confirm": True})
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual(self._planned_layer()["story_plans"], [])
        refused = self._analysis("plan_alignment")
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (422, "analysis_plan_unavailable"))
        decided = self._plan("story-plans", {"title": "返航", "summary": "本章完成返航。"})
        self.assertEqual([item["id"] for item in self._planned_layer("plan_alignment")["story_plans"]], [decided])

    def test_author_material_tables_and_endpoints_are_gone(self):
        with sqlite3.connect(self.root / "runtime" / "data" / "demo.sqlite3") as c:
            tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(tables & set(MATERIAL_TABLES))
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/author-context/materials").status_code, 404)
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/analyses?analysis_type=author_material_comparison").status_code, 400)


class DropMigrationTests(unittest.TestCase):
    def test_an_older_database_loses_the_material_tables_and_a_second_start_is_a_no_op(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v170-drop-"))
        paths = AppPaths.from_project_root(root, protected_poc_root=root / "protected")
        V2Database(paths).initialize()
        with sqlite3.connect(paths.database_path) as c:
            # What a v1.6.1 start leaves behind (it recreates the tables, possibly with rows).
            c.execute("CREATE TABLE v2_author_materials(id TEXT PRIMARY KEY,project_id TEXT)")
            c.execute("CREATE TABLE v2_author_material_versions(material_id TEXT REFERENCES v2_author_materials(id))")
            c.execute("CREATE TABLE v2_author_comparisons(id TEXT PRIMARY KEY,material_id TEXT REFERENCES v2_author_materials(id))")
            c.execute("CREATE TABLE v2_author_comparison_decisions(comparison_id TEXT REFERENCES v2_author_comparisons(id))")
            c.execute("INSERT INTO v2_author_materials VALUES('m1','p1')")
            c.execute("INSERT INTO v2_author_comparisons VALUES('c1','m1')")
            c.execute("INSERT INTO v2_author_comparison_decisions VALUES('c1')")
        V2Database(paths).initialize()
        V2Database(paths).initialize()
        with sqlite3.connect(paths.database_path) as c:
            tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertFalse(tables & set(MATERIAL_TABLES))


if __name__ == "__main__":
    unittest.main()
