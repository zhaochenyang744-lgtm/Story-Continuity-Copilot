"""Stage 11L-A uses only product APIs; database reads are assertions, never setup."""

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderInvalidJson, ProviderResult, ProviderTimeout


def idem(value=None):
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class TwoRoundProvider:
    """Injected deterministic Provider for 11L-A; no network or credentials."""

    label = "stage11l-a-test-provider"
    model_label = "stage11l-a-test-model"

    def __init__(self):
        self.failure = None
        self.delta_requests = []

    @property
    def available(self):
        return True

    def evaluate(self, request):
        task = request.get("task")
        if task == "memory_initialization":
            source = request["sources"][0]
            return ProviderResult({"candidates": [
                {"memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": "在雾港", "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
                {"memory_type": "open_thread", "subject": "北堤门", "predicate": "status", "value": "待确认", "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
            ]}, input_tokens=5, output_tokens=3, latency_ms=1)
        if task == "memory_delta":
            if self.failure == "timeout":
                raise ProviderTimeout()
            if self.failure == "invalid_json":
                raise ProviderInvalidJson()
            source = request["sources"][0]
            self.delta_requests.append(request)
            if self.failure == "schema":
                return ProviderResult({"candidates": [{"not": "a candidate"}]})
            if self.failure == "evidence":
                return ProviderResult({"candidates": [{"memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": "坏证据", "chapter_id": "foreign", "source_span_id": "foreign"}]})
            value = "已离开雾港" if "第一轮" in source["body"] else "已抵达北堤"
            return ProviderResult({"candidates": [
                {"memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": value, "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
                {"memory_type": "open_thread", "subject": "北堤门", "predicate": "status", "value": "待作者确认", "chapter_id": source["chapter_id"], "source_span_id": source["id"]},
            ]}, input_tokens=7, output_tokens=4, latency_ms=2)
        return ProviderResult({"issues": []}, input_tokens=6, output_tokens=2, latency_ms=1)


class Stage11LTwoRoundApiTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-11l-a-"))
        self.provider = TwoRoundProvider()
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=self.provider, executor=lambda fn, *args: fn(*args))
        self.client = TestClient(self.app)
        self.account = f"stage11l-{uuid.uuid4().hex[:8]}"
        self.password = "safe-password-123"
        self.client.post("/api/auth/register", json={"account_name": self.account, "display_name": "11L 作者", "password": self.password}, headers=idem())
        self.project = self._project("11L 两轮作品")
        self._initialize(self.project)

    def _project(self, title):
        preview = self.client.post("/api/imports/preview", files={"file": ("base.md", "# 第一章\n林默在雾港。".encode(), "text/markdown")}, headers=idem()).json()["data"]
        response = self.client.post(f"/api/imports/{preview['import_id']}/commit", json={"confirm": True, "title": title, "chapter_preview_ids": [row["preview_id"] for row in preview["detected"]["chapters"]]}, headers=idem())
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]["project"]["id"]

    def _initialize(self, project):
        initialization = self.client.post(f"/api/projects/{project}/memory/initializations", json={"source_revision": 1}, headers=idem()).json()["data"]["initialization"]
        for candidate in initialization["candidates"]:
            if candidate["review_priority"] == "core":
                response = self.client.post(f"/api/projects/{project}/memory/initializations/{initialization['id']}/candidates/{candidate['id']}/decision", json={"decision": "accepted"}, headers=idem())
                self.assertEqual(response.status_code, 200)
        committed = self.client.post(f"/api/projects/{project}/memory/initializations/{initialization['id']}/commit", json={"confirm": True}, headers=idem())
        self.assertEqual(committed.status_code, 200)

    def _append(self, project, revision, body):
        preview = self.client.post(f"/api/projects/{project}/source-change-sets/preview", json={"mode": "append", "input_method": "paste", "base_source_revision": revision, "content": body}, headers=idem())
        self.assertEqual(preview.status_code, 201)
        change = preview.json()["data"]["source_change_set"]
        committed = self.client.post(f"/api/projects/{project}/source-change-sets/{change['id']}/commit", json={"confirm": True, "content_sha256": change["content_sha256"]}, headers=idem())
        self.assertEqual(committed.status_code, 200)
        return committed.json()["data"]

    def _start(self, project, revision, key=None):
        response = self.client.post(f"/api/projects/{project}/incremental-reviews", json={"source_revision": revision}, headers=idem(key))
        delta = self.client.get(f"/api/projects/{project}/memory/delta").json()["data"]
        return response, delta

    def _decide_and_commit(self, project, delta, edited=False):
        for candidate in delta["candidates"]:
            if candidate["review_priority"] != "core":
                continue
            payload = {"decision": "accepted"}
            if edited:
                payload = {"decision": "edited", "after": {"memory_type": candidate["memory_type"], "subject": candidate["subject"], "predicate": candidate["predicate"], "value": "编辑后抵达北堤"}, "evidence_span_id": candidate["source"]["span_id"]}
            decision = self.client.post(f"/api/projects/{project}/memory/deltas/{delta['id']}/candidates/{candidate['id']}/decision", json=payload, headers=idem())
            self.assertEqual(decision.status_code, 200)
        response = self.client.post(f"/api/projects/{project}/memory/deltas/{delta['id']}/commit", json={"confirm": True}, headers=idem())
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def _counts(self, project):
        tables = ("v2_issues", "v2_evidence", "v2_memory_delta_candidates", "v2_memory_delta_decisions", "v2_memory_versions", "v2_source_coverage_audits")
        with self.app.state.database.connection() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in tables}

    def test_two_api_rounds_are_monotonic_recoverable_and_confirmed_only(self):
        other = self._project("11L 隔离项目")
        other_snapshot = self._counts(other)
        first_change = self._append(self.project, 1, "# 第二章\n第一轮：林默已离开雾港。")
        self.assertEqual(first_change["source_change_set"]["target_source_revision"], 2)
        start_one, delta_one = self._start(self.project, 2)
        self.assertEqual(start_one.status_code, 202)
        self.assertEqual(delta_one["coverage"]["status"], "update_pending")
        self.assertEqual({candidate["review_priority"] for candidate in delta_one["candidates"]}, {"core", "supporting"})
        result_one = self._decide_and_commit(self.project, delta_one)
        self.assertEqual(result_one["memory_version"], 2)
        self.assertEqual(result_one["delta"]["coverage"]["counts"]["pending_canon_count"], 0)
        self.client.post("/api/auth/logout")
        login = self.client.post("/api/auth/login", json={"account_name": self.account, "password": self.password})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get(f"/api/projects/{self.project}").json()["data"]["current_memory_version"], 2)
        self.assertEqual(self._counts(other), other_snapshot)
        second_change = self._append(self.project, 2, "# 第三章\n第二轮：林默已抵达北堤。")
        self.assertEqual(second_change["source_change_set"]["target_source_revision"], 3)
        start_two, delta_two = self._start(self.project, 3)
        self.assertEqual(start_two.status_code, 202)
        result_two = self._decide_and_commit(self.project, delta_two, edited=True)
        self.assertEqual((result_two["memory_version"], result_two["coverage_audit"]["status"]), (3, "covered_with_memory_change"))
        for revision, delta in ((2, delta_one), (3, delta_two)):
            runs = [self.client.get(f"/api/projects/{self.project}/checks/{run_id}?include=metrics").json()["data"] for run_id in (delta["continuity_run_id"], delta["memory_delta_run_id"])]
            self.assertEqual({run["run_type"] for run in runs}, {"continuity", "memory_delta"})
            for run in runs:
                self.assertEqual((run["source_revision"], run["lineage_status"], run["is_stale"]), (revision, "incremental_source_revision", False))
                self.assertTrue(run["source_change_set_id"])
                self.assertTrue(run["source_span_ids"])
                self.assertEqual(run["metrics"]["provenance"]["source_memory_version"], revision - 1)
        memory = self.client.get(f"/api/projects/{self.project}/memory").json()["data"]
        self.assertEqual(memory["memory_version"], 3)
        self.assertNotIn("待作者确认", [row["value"] for row in memory["records"]])
        self.assertTrue(all(request["memory"] for request in self.provider.delta_requests))
        self.assertTrue(all("待作者确认" not in item["value"] for request in self.provider.delta_requests for item in request["memory"]))
        self.assertEqual(self._counts(other), other_snapshot)

    def test_timeout_json_schema_and_evidence_fail_without_half_writes_then_new_key_retries(self):
        self._append(self.project, 1, "# 第二章\n第一轮失败注入。")
        for failure, error in (("timeout", "provider_timeout"), ("invalid_json", "invalid_json"), ("schema", "schema_invalid"), ("evidence", "evidence_unresolvable")):
            with self.subTest(failure=failure):
                root = pathlib.Path(tempfile.mkdtemp(prefix="scc-11l-failure-"))
                provider = TwoRoundProvider(); provider.failure = failure
                app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=provider, executor=lambda fn, *args: fn(*args))
                client = TestClient(app)
                account = f"failure-{uuid.uuid4().hex[:8]}"
                client.post("/api/auth/register", json={"account_name": account, "display_name": "Failure", "password": self.password}, headers=idem())
                preview = client.post("/api/imports/preview", files={"file": ("base.md", b"# First\nLin Mo.", "text/markdown")}, headers=idem()).json()["data"]
                project = client.post(f"/api/imports/{preview['import_id']}/commit", json={"confirm": True, "title": "Failure", "chapter_preview_ids": [row["preview_id"] for row in preview["detected"]["chapters"]]}, headers=idem()).json()["data"]["project"]["id"]
                initialization = client.post(f"/api/projects/{project}/memory/initializations", json={"source_revision": 1}, headers=idem()).json()["data"]["initialization"]
                core = next(row for row in initialization["candidates"] if row["review_priority"] == "core")
                client.post(f"/api/projects/{project}/memory/initializations/{initialization['id']}/candidates/{core['id']}/decision", json={"decision": "accepted"}, headers=idem())
                client.post(f"/api/projects/{project}/memory/initializations/{initialization['id']}/commit", json={"confirm": True}, headers=idem())
                change = client.post(f"/api/projects/{project}/source-change-sets/preview", json={"mode": "append", "input_method": "paste", "base_source_revision": 1, "content": "# Second\nFirst round."}, headers=idem()).json()["data"]["source_change_set"]
                client.post(f"/api/projects/{project}/source-change-sets/{change['id']}/commit", json={"confirm": True, "content_sha256": change["content_sha256"]}, headers=idem())
                with app.state.database.connection() as connection:
                    before = {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in ("v2_issues", "v2_evidence", "v2_memory_delta_candidates", "v2_memory_delta_decisions", "v2_memory_versions", "v2_source_coverage_audits")}
                failed = client.post(f"/api/projects/{project}/incremental-reviews", json={"source_revision": 2}, headers=idem()).json()["data"]
                delta = client.get(f"/api/projects/{project}/memory/delta").json()["data"]
                self.assertEqual((delta["status"], delta["error_code"]), ("failed", error))
                with app.state.database.connection() as connection:
                    after = {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in before}
                self.assertEqual(after, before)
                run = client.get(f"/api/projects/{project}/checks/{failed['memory_delta_run_id']}").json()["data"]
                self.assertEqual(run["error_code"], error)
                provider.failure = None
                retry = client.post(f"/api/projects/{project}/incremental-reviews", json={"source_revision": 2}, headers=idem()).json()["data"]
                self.assertNotEqual(failed["memory_delta_run_id"], retry["memory_delta_run_id"])

    def test_idempotency_and_cross_account_are_closed_without_business_writes(self):
        self._append(self.project, 1, "# 第二章\n第一轮幂等。")
        key = str(uuid.uuid4())
        first, delta = self._start(self.project, 2, key)
        replay, _ = self._start(self.project, 2, key)
        conflict, _ = self._start(self.project, 999, key)
        self.assertEqual((first.status_code, replay.status_code, conflict.status_code), (202, 202, 409))
        before = self._counts(self.project)
        stranger = TestClient(self.app)
        stranger.post("/api/auth/register", json={"account_name": f"stranger-{uuid.uuid4().hex[:8]}", "display_name": "Stranger", "password": self.password}, headers=idem())
        core = next(candidate for candidate in delta["candidates"] if candidate["review_priority"] == "core")
        for method, url, payload in (("get", f"/api/projects/{self.project}/memory/delta", None), ("post", f"/api/projects/{self.project}/incremental-reviews", {"source_revision": 2}), ("post", f"/api/projects/{self.project}/memory/deltas/{delta['id']}/candidates/{core['id']}/decision", {"decision": "accepted"}), ("post", f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit", {"confirm": True})):
            response = getattr(stranger, method)(url, json=payload, headers=idem()) if payload else getattr(stranger, method)(url)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self._counts(self.project), before)


if __name__ == "__main__":
    unittest.main()
