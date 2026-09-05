import pathlib
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult
from app import v2_database


def idem(value=None):
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class FactLifecycleProvider:
    label = "v130-fact-lifecycle-provider"
    model_label = "v130-fact-lifecycle-model"
    empty = False

    @property
    def available(self):
        return True

    def evaluate(self, request):
        if request.get("task") == "memory_initialization":
            source = request["sources"][0]
            return ProviderResult({"candidates": [
                {"memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": "在雾港", "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
                {"memory_type": "dynamic_state", "subject": "旧灯塔", "predicate": "status", "value": "仍在使用", "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
            ]})
        if request.get("task") == "memory_delta":
            if self.empty:
                return ProviderResult({"candidates": []}, input_tokens=4, output_tokens=1, latency_ms=1)
            source = request["sources"][0]
            status = next(item for item in request["memory"] if item["subject"] == "林默")
            lighthouse = next(item for item in request["memory"] if item["subject"] == "旧灯塔")
            return ProviderResult({"candidates": [
                {"change_kind": "changed_fact", "affected_memory_id": status["id"], "memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": "已离开雾港", "invalidation_reason": None, "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
                {"change_kind": "invalidated_fact", "affected_memory_id": lighthouse["id"], "memory_type": "dynamic_state", "subject": "旧灯塔", "predicate": "status", "value": "仍在使用", "invalidation_reason": "新章节明确灯塔已永久停用", "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
                {"change_kind": "new_fact", "affected_memory_id": None, "memory_type": "dynamic_state", "subject": "守塔人", "predicate": "location", "value": "北堤", "invalidation_reason": None, "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
            ]}, input_tokens=12, output_tokens=9, latency_ms=2)
        return ProviderResult({"issues": []}, input_tokens=3, output_tokens=1, latency_ms=1)


class MemoryDeltaFactLifecycleTests(unittest.TestCase):
    TABLES = ("v2_change_sets", "v2_change_set_items", "v2_memory_delta_decisions", "v2_memory_versions", "v2_memory_records", "v2_source_coverage_audits", "v2_commit_audits")

    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-memory-delta-"))
        self.provider = FactLifecycleProvider()
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=self.provider, executor=lambda fn, *args: fn(*args))
        self.client = TestClient(self.app)
        self.client.post("/api/auth/register", json={"account_name": f"fact-{uuid.uuid4().hex[:8]}", "display_name": "Fact Author", "password": "safe-password-123"}, headers=idem())
        preview = self.client.post("/api/imports/preview", files={"file": ("base.md", "# 第一章\n林默在雾港，旧灯塔仍在使用。".encode(), "text/markdown")}, headers=idem()).json()["data"]
        self.project = self.client.post(f"/api/imports/{preview['import_id']}/commit", json={"confirm": True, "title": "Fact lifecycle", "chapter_preview_ids": [item["preview_id"] for item in preview["detected"]["chapters"]]}, headers=idem()).json()["data"]["project"]["id"]
        initialization = self.client.post(f"/api/projects/{self.project}/memory/initializations", json={"source_revision": 1}, headers=idem()).json()["data"]["initialization"]
        for candidate in initialization["candidates"]:
            self.client.post(f"/api/projects/{self.project}/memory/initializations/{initialization['id']}/candidates/{candidate['id']}/decision", json={"decision": "accepted"}, headers=idem())
        committed = self.client.post(f"/api/projects/{self.project}/memory/initializations/{initialization['id']}/commit", json={"confirm": True}, headers=idem())
        self.assertEqual(committed.status_code, 200)
        change = self.client.post(f"/api/projects/{self.project}/source-change-sets/preview", json={"mode": "append", "input_method": "paste", "base_source_revision": 1, "content": "# 第二章\n林默离开雾港；旧灯塔永久停用；守塔人在北堤。"}, headers=idem()).json()["data"]["source_change_set"]
        self.client.post(f"/api/projects/{self.project}/source-change-sets/{change['id']}/commit", json={"confirm": True, "content_sha256": change["content_sha256"]}, headers=idem())

    def start(self):
        response = self.client.post(f"/api/projects/{self.project}/incremental-reviews", json={"source_revision": 2}, headers=idem())
        self.assertEqual(response.status_code, 202)
        return self.client.get(f"/api/projects/{self.project}/memory/delta").json()["data"]

    def decide(self, delta, candidate, decision, key=None, **extra):
        return self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/candidates/{candidate['id']}/decision", json={"decision": decision, **extra}, headers=idem(key))

    def counts(self):
        with self.app.state.database.connection() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (self.project,)).fetchone()[0] for table in self.TABLES}

    def test_accept_edit_and_invalidate_create_atomic_v2_and_auditable_changeset(self):
        delta = self.start()
        self.assertEqual([item["change_kind"] for item in delta["candidates"]], ["changed_fact", "invalidated_fact", "new_fact"])
        changed, invalidated, added = delta["candidates"]
        self.assertEqual((changed["before"]["value"], changed["after"]["value"]), ("在雾港", "已离开雾港"))
        self.assertEqual((invalidated["before"]["value"], invalidated["after"]), ("仍在使用", None))
        self.assertEqual(self.decide(delta, invalidated, "edited", after={"memory_type": "dynamic_state", "subject": "旧灯塔", "predicate": "status", "value": "停用"}, evidence_span_id=invalidated["source"]["span_id"]).status_code, 422)
        edit = {"memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": "已抵达北堤"}
        decision_key = str(uuid.uuid4())
        self.assertEqual(self.decide(delta, changed, "edited", decision_key, after=edit, evidence_span_id=changed["source"]["span_id"]).status_code, 200)
        self.assertEqual(self.decide(delta, changed, "edited", decision_key, after=edit, evidence_span_id=changed["source"]["span_id"]).status_code, 200)
        self.assertEqual(self.decide(delta, invalidated, "accepted").status_code, 200)
        self.assertEqual(self.decide(delta, added, "accepted").status_code, 200)
        commit_key = str(uuid.uuid4())
        first = self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit", json={"confirm": True}, headers=idem(commit_key))
        replay = self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit", json={"confirm": True}, headers=idem(commit_key))
        self.assertEqual((first.status_code, replay.status_code), (200, 200))
        result = first.json()["data"]
        self.assertEqual((result["memory_version"], result["change_set"]["change_set_kind"], result["change_set"]["status"]), (2, "memory_delta", "committed"))
        self.assertEqual([item["operation"] for item in result["change_set"]["items"]], ["replace", "retire", "add"])
        v1 = self.client.get(f"/api/projects/{self.project}/memory?version=1").json()["data"]["records"]
        v2 = self.client.get(f"/api/projects/{self.project}/memory?version=2").json()["data"]["records"]
        self.assertEqual({item["value"] for item in v1}, {"在雾港", "仍在使用"})
        self.assertIn("已抵达北堤", {item["value"] for item in v2})
        self.assertIn("北堤", {item["value"] for item in v2})
        retired = next(item for item in v2 if item["subject"] == "旧灯塔")
        self.assertEqual(retired["valid_to"], 1)
        with self.app.state.database.connection() as connection:
            active = self.app.state.database._confirmed_memory(connection, self.project, 2)
        self.assertNotIn("旧灯塔", {item["subject"] for item in active})

    def test_zero_candidates_creates_coverage_and_changeset_without_version_growth(self):
        self.provider.empty = True
        delta = self.start()
        self.assertEqual(delta["candidates"], [])
        result = self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit", json={"confirm": True}, headers=idem()).json()["data"]
        self.assertEqual((result["memory_version"], result["status"], result["change_set"]["items"]), (1, "covered_without_memory_change", []))
        self.assertEqual(result["change_set"]["status"], "rejected")

    def test_stale_source_revision_rejects_decisions_and_commit_without_writes(self):
        delta = self.start()
        change = self.client.post(f"/api/projects/{self.project}/source-change-sets/preview", json={"mode": "append", "input_method": "paste", "base_source_revision": 2, "content": "# 第三章\n新的修订。"}, headers=idem()).json()["data"]["source_change_set"]
        self.client.post(f"/api/projects/{self.project}/source-change-sets/{change['id']}/commit", json={"confirm": True, "content_sha256": change["content_sha256"]}, headers=idem())
        before = self.counts()
        self.assertEqual(self.decide(delta, delta["candidates"][0], "accepted").json()["error"]["code"], "memory_delta_stale")
        commit = self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit", json={"confirm": True}, headers=idem())
        self.assertEqual((commit.status_code, commit.json()["error"]["code"], self.counts()), (409, "memory_delta_stale", before))

    def test_late_commit_failure_rolls_back_every_business_write(self):
        delta = self.start()
        for candidate in delta["candidates"]:
            self.assertEqual(self.decide(delta, candidate, "accepted").status_code, 200)
        before = self.counts()
        original = v2_database.new_id

        def failing_id(prefix):
            if prefix == "commit":
                raise RuntimeError("injected late commit failure")
            return original(prefix)

        with patch("app.v2_database.new_id", side_effect=failing_id):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit", json={"confirm": True}, headers=idem())
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.client.get(f"/api/projects/{self.project}").json()["data"]["current_memory_version"], 1)


if __name__ == "__main__":
    unittest.main()
