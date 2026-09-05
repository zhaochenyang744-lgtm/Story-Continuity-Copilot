from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderInvalidJson, ProviderResult, ProviderTimeout
from app.stage13 import Stage13Settings


def idem(value: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": value or str(uuid.uuid4()), "Origin": "http://testserver"}


class BoundedToolsProvider:
    available = True
    label = "bounded-tools-test-provider"
    model_label = "bounded-tools-test-model"

    def __init__(self):
        self.requests: list[dict] = []
        self.mode = "valid"

    def evaluate(self, request):
        self.requests.append(request)
        task = request.get("task")
        if task not in {"story_qa", "foreshadow_scan"}:
            return ProviderResult({"issues": []}, 1, 1, latency_ms=1)
        if self.mode == "invalid_json":
            raise ProviderInvalidJson()
        if self.mode == "timeout":
            raise ProviderTimeout()
        if task == "story_qa":
            if self.mode == "insufficient":
                return ProviderResult({"answer_status": "insufficient", "answer": "Provider 猜测没有答案。", "findings": []}, 4, 2, latency_ms=1)
            if self.mode == "partial_planned":
                plan = request["layers"]["planned"]["story_plans"][0]
                return ProviderResult({"answer_status": "partial", "answer": "当前计划给出部分方向，但不是已写事实。", "findings": [{"layer": "planned", "stance": "context", "text": "答案仅来自作者计划。", "evidence": [{"source_type": "author_context", "source_id": plan["id"]}]}]}, 6, 3, latency_ms=1)
            memory = request["layers"]["confirmed"]["memory_records"][0]
            source = request["layers"]["written"]["source_spans"][0] if request["layers"]["written"]["source_spans"] else None
            if self.mode == "invalid_evidence":
                return ProviderResult({"answer_status": "answered", "answer": "错误引用。", "findings": [{"layer": "confirmed", "stance": "supports", "text": "错误引用。", "evidence": [{"source_type": "memory_record", "source_id": "missing"}]}]}, 4, 2, latency_ms=1)
            if self.mode == "conflicting":
                return ProviderResult({"answer_status": "conflicting", "answer": "已确认事实与已写正文存在冲突。", "findings": [
                    {"layer": "confirmed", "stance": "supports", "text": "Story Memory 保留原事实。", "evidence": [{"source_type": "memory_record", "source_id": memory["id"]}]},
                    {"layer": "written", "stance": "contradicts", "text": "正文出现相反信息。", "evidence": [{"source_type": "source_span", "source_id": source["id"]}]},
                ]}, 8, 4, latency_ms=1)
            return ProviderResult({"answer_status": "answered", "answer": "依据已确认事实，可以给出有界回答。", "findings": [{"layer": "confirmed", "stance": "supports", "text": "该结论来自当前 Story Memory。", "evidence": [{"source_type": "memory_record", "source_id": memory["id"]}]}]}, 6, 3, latency_ms=1)
        if self.mode == "zero_candidates":
            return ProviderResult({"summary": "Provider 自称没有候选。", "candidates": []}, 5, 2, latency_ms=1)
        source = request["layers"]["written"]["source_spans"][0]
        evidence = [{"source_type": "source_span", "source_id": source["id"], "relation": "planted"}]
        if self.mode == "invalid_evidence":
            evidence = [{"source_type": "source_span", "source_id": "missing", "relation": "planted"}]
        first_status = "resolved" if self.mode == "contradictory_status" else "planted"
        return ProviderResult({"summary": "发现三条需要作者判断的伏笔候选。", "candidates": [
            {"title": "潮汐表的缺口", "description": "正文中的缺口可能在后续解释。", "suggested_status": first_status, "evidence": evidence},
            {"title": "北门雾钟", "description": "雾钟重复出现，可能仍在发展。", "suggested_status": "developing", "evidence": [{"source_type": "source_span", "source_id": source["id"], "relation": "developing"}]},
            {"title": "潮声回信", "description": "一封回信可能成为后续线索。", "suggested_status": "planted", "evidence": [{"source_type": "source_span", "source_id": source["id"], "relation": "planted"}]},
        ]}, 10, 5, latency_ms=1)


class V130StoryQaForeshadowTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-qa-foreshadow-"))
        self.provider = BoundedToolsProvider()
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=self.provider, executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
        self.client = TestClient(self.app)
        registered = self.client.post("/api/auth/register", headers=idem(), json={"account_name": "bounded-owner", "display_name": "Author", "password": "safe-password-v130", "recovery_email": "bounded-owner@example.test"})
        self.assertEqual(registered.status_code, 201, registered.text)
        self.project_id = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        self.project = self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        with self.app.state.database.connection() as connection:
            source = connection.execute("SELECT s.id,s.chapter_id FROM v2_source_spans s WHERE s.project_id=? ORDER BY s.id LIMIT 1", (self.project_id,)).fetchone()
            self.source_id, self.chapter_id = source["id"], source["chapter_id"]

    def analysis(self, analysis_type: str, **extra):
        draft = self.project["current_draft"]
        return self.client.post(f"/api/projects/{self.project_id}/analyses", headers=idem(), json={"analysis_type": analysis_type, "draft_id": draft["id"], "draft_revision": draft["revision"], **extra})

    def foreshadow_payload(self, version=0, title="失落的潮汐表"):
        return {"base_foreshadow_version": version, "title": title, "description": "作者计划在后续章节解释它的来历。", "status": "planted", "planted_chapter_id": self.chapter_id, "planted_source_span_id": self.source_id}

    def test_author_records_cas_idempotency_references_archive_and_isolation(self):
        key = str(uuid.uuid4())
        created = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=idem(key), json=self.foreshadow_payload())
        self.assertEqual(created.status_code, 201, created.text)
        record = created.json()["data"]["item"]
        self.assertEqual((record["version"], record["status"], record["planted"]["source_span_id"]), (1, "planted", self.source_id))
        self.assertTrue(record["planted"]["source_path"].endswith(f"/sources#span-{self.source_id}"))
        replay = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=idem(key), json=self.foreshadow_payload())
        self.assertEqual(replay.json()["data"], created.json()["data"])
        conflict = self.client.patch(f"/api/projects/{self.project_id}/foreshadows/{record['id']}", headers=idem(), json={"base_version": 2, "status": "developing"})
        self.assertEqual((conflict.status_code, conflict.json()["error"]["code"]), (409, "foreshadow_version_conflict"))
        updated = self.client.patch(f"/api/projects/{self.project_id}/foreshadows/{record['id']}", headers=idem(), json={"base_version": 1, "status": "developing"})
        self.assertEqual((updated.status_code, updated.json()["data"]["item"]["version"]), (200, 2))
        archived = self.client.post(f"/api/projects/{self.project_id}/foreshadows/{record['id']}/archive", headers=idem(), json={"base_version": 2})
        self.assertEqual((archived.status_code, archived.json()["data"]["item"]["version"]), (200, 3))
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/foreshadows").json()["data"]["records"], [])
        outsider = TestClient(self.app)
        outsider.post("/api/auth/register", headers=idem(), json={"account_name": "bounded-outsider", "display_name": "Other", "password": "safe-password-v130", "recovery_email": "bounded-outsider@example.test"})
        self.assertEqual(outsider.get(f"/api/projects/{self.project_id}/foreshadows").status_code, 404)
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_foreshadow_versions WHERE item_id=?", (record["id"],)).fetchone()[0], 3)

    def test_author_record_validation_duplicate_and_illegal_reference_fail_closed(self):
        created = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=idem(), json=self.foreshadow_payload())
        self.assertEqual(created.status_code, 201, created.text)
        duplicate = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=idem(), json=self.foreshadow_payload(1, "  失落的潮汐表  "))
        self.assertEqual((duplicate.status_code, duplicate.json()["error"]["code"]), (409, "foreshadow_duplicate"))
        invalid = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=idem(), json={**self.foreshadow_payload(1, "另一条线索"), "planted_source_span_id": "missing"})
        self.assertEqual((invalid.status_code, invalid.json()["error"]["code"]), (422, "foreshadow_reference_invalid"))
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_foreshadows WHERE project_id=?", (self.project_id,)).fetchone()[0], 1)

    def test_author_record_count_and_version_limits_are_enforced(self):
        stamp = "2026-09-05T00:00:00+00:00"
        with self.app.state.database.connection() as connection:
            connection.executemany(
                "INSERT INTO v2_foreshadows VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(f"foreshadow-limit-{index}", self.project_id, f"伏笔 {index}", f"伏笔 {index}", "用于验证活动记录上限。", "planned", None, None, None, None, 1, None, stamp, stamp) for index in range(200)],
            )
            connection.execute("UPDATE v2_projects SET foreshadow_version=200 WHERE id=?", (self.project_id,))
        limited = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=idem(), json=self.foreshadow_payload(200, "第 201 条伏笔"))
        self.assertEqual((limited.status_code, limited.json()["error"]["code"]), (409, "foreshadow_limit_reached"))
        with self.app.state.database.connection() as connection:
            connection.execute("UPDATE v2_projects SET foreshadow_version=2147483647 WHERE id=?", (self.project_id,))
        versioned = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=idem(), json=self.foreshadow_payload(2147483647, "版本溢出伏笔"))
        self.assertEqual((versioned.status_code, versioned.json()["error"]["code"]), (409, "foreshadow_version_limit"))

    def test_story_qa_scope_answer_conflict_insufficient_and_no_implicit_write(self):
        author = self.client.get(f"/api/projects/{self.project_id}/author-intent?include_archived=true").json()["data"]
        if not author["story_plans"]:
            created_plan = self.client.post(f"/api/projects/{self.project_id}/author-intent/story-plans", headers=idem(), json={"base_author_context_version": author["author_context_version"], "title": "回到雾港", "summary": "作者计划让林默回到雾港。", "goal": "验证计划层问答。", "status": "planned", "target_chapter_number": 1})
            self.assertEqual(created_plan.status_code, 201, created_plan.text)
        before = {}
        with self.app.state.database.connection() as connection:
            for table in ("v2_memory_records", "v2_author_context_versions", "v2_foreshadows", "v2_draft_revisions"):
                before[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        answered = self.analysis("story_qa", question="林默知道什么？", scope=["confirmed"])
        self.assertEqual(answered.status_code, 202, answered.text)
        view = self.client.get(f"/api/projects/{self.project_id}/analyses/{answered.json()['data']['run_id']}").json()["data"]
        self.assertEqual((view["analysis"]["answer_status"], view["question"], view["scope"]), ("answered", "林默知道什么？", ["confirmed"]))
        request = self.provider.requests[-1]
        self.assertEqual(request["layers"]["planned"], {"story_plans": [], "character_plans": [], "world_plans": []})
        self.assertEqual(request["layers"]["written"]["source_spans"], [])
        self.provider.mode = "conflicting"
        conflict = self.analysis("story_qa", question="正文与事实一致吗？", scope=["confirmed", "written"])
        conflict_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{conflict.json()['data']['run_id']}").json()["data"]
        self.assertEqual(conflict_view["analysis"]["answer_status"], "conflicting")
        self.assertEqual({item["stance"] for item in conflict_view["analysis"]["findings"]}, {"supports", "contradicts"})
        self.provider.mode = "insufficient"
        insufficient = self.analysis("story_qa", question="没有证据的问题？", scope=["confirmed"])
        insufficient_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{insufficient.json()['data']['run_id']}").json()["data"]
        self.assertEqual(insufficient_view["analysis"]["answer"], "当前证据不足以回答这个问题。")
        self.assertNotIn("Provider 猜测", insufficient_view["analysis"]["answer"])
        self.provider.mode = "partial_planned"
        partial = self.analysis("story_qa", question="作者下一步计划是什么？", scope=["planned"])
        partial_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{partial.json()['data']['run_id']}").json()["data"]
        self.assertEqual((partial_view["analysis"]["answer_status"], partial_view["analysis"]["findings"][0]["layer"]), ("partial", "planned"))
        planned_request = self.provider.requests[-1]
        self.assertEqual(planned_request["layers"]["confirmed"]["memory_records"], [])
        self.assertEqual(planned_request["layers"]["written"]["source_spans"], [])
        self.assertEqual(planned_request["layers"]["written"]["draft_claims"], [])
        self.assertEqual(planned_request["layers"]["written"]["draft"]["excerpt"], "")
        with self.app.state.database.connection() as connection:
            for table, count in before.items():
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], count)

    def test_story_qa_invalid_evidence_and_invalid_json_fail_closed(self):
        for mode, code in (("invalid_evidence", "evidence_unresolvable"), ("invalid_json", "invalid_json")):
            self.provider.mode = mode
            response = self.analysis("story_qa", question="问题", scope=["confirmed"])
            run_id = response.json()["data"]["run_id"]
            view = self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
            self.assertEqual((view["status"], view["error_code"]), ("failed", code))
            with self.app.state.database.connection() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_analysis_results WHERE run_id=?", (run_id,)).fetchone()[0], 0)

    def test_scan_candidates_require_author_decisions_and_support_multiple_choices(self):
        scan = self.analysis("foreshadow_scan")
        self.assertEqual(scan.status_code, 202, scan.text)
        run_id = scan.json()["data"]["run_id"]
        view = self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertEqual((view["status"], len(view["analysis"]["candidates"])), ("completed", 3))
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_foreshadows WHERE project_id=?", (self.project_id,)).fetchone()[0], 0)
        first, second, third = view["analysis"]["candidates"]
        accept_key = str(uuid.uuid4())
        accepted = self.client.post(f"/api/projects/{self.project_id}/analyses/{run_id}/foreshadow-candidates/{first['id']}/decision", headers=idem(accept_key), json={"base_foreshadow_version": 0, "decision": "accepted"})
        self.assertEqual((accepted.status_code, accepted.json()["data"]["decision_status"]), (200, "accepted"))
        replay = self.client.post(f"/api/projects/{self.project_id}/analyses/{run_id}/foreshadow-candidates/{first['id']}/decision", headers=idem(accept_key), json={"base_foreshadow_version": 0, "decision": "accepted"})
        self.assertEqual(replay.json()["data"], accepted.json()["data"])
        edited = self.client.post(f"/api/projects/{self.project_id}/analyses/{run_id}/foreshadow-candidates/{second['id']}/decision", headers=idem(), json={"base_foreshadow_version": 1, "decision": "edited", "edited": {"title": "作者确认的雾钟", "description": "作者明确保留这一回收线索。", "status": "developing", "planted_chapter_id": self.chapter_id, "planted_source_span_id": self.source_id}})
        self.assertEqual((edited.status_code, edited.json()["data"]["decision_status"]), (200, "edited"))
        rejected = self.client.post(f"/api/projects/{self.project_id}/analyses/{run_id}/foreshadow-candidates/{third['id']}/decision", headers=idem(), json={"base_foreshadow_version": 2, "decision": "rejected"})
        self.assertEqual((rejected.status_code, rejected.json()["data"]["decision_status"]), (200, "rejected"))
        refreshed = self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertFalse(refreshed["is_stale"])
        self.assertEqual([item["decision_status"] for item in refreshed["analysis"]["candidates"]], ["accepted", "edited", "rejected"])
        records = self.client.get(f"/api/projects/{self.project_id}/foreshadows").json()["data"]
        self.assertEqual((records["foreshadow_version"], len(records["records"]), {item["title"] for item in records["records"]}), (2, 2, {"潮汐表的缺口", "作者确认的雾钟"}))

    def test_candidate_cross_project_reference_failure_rolls_back_atomically(self):
        scan = self.analysis("foreshadow_scan")
        run_id = scan.json()["data"]["run_id"]
        candidate = self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]["analysis"]["candidates"][0]
        outsider = TestClient(self.app)
        foreign = outsider.post("/api/auth/register", headers=idem(), json={"account_name": "bounded-foreign-source", "display_name": "Other", "password": "safe-password-v130", "recovery_email": "bounded-foreign-source@example.test"}).json()["data"]["onboarding"]["tutorial"]["project_id"]
        with self.app.state.database.connection() as connection:
            foreign_source = connection.execute("SELECT id,chapter_id FROM v2_source_spans WHERE project_id=? ORDER BY id LIMIT 1", (foreign,)).fetchone()
        failed = self.client.post(f"/api/projects/{self.project_id}/analyses/{run_id}/foreshadow-candidates/{candidate['id']}/decision", headers=idem(), json={"base_foreshadow_version": 0, "decision": "edited", "edited": {"title": "跨项目来源", "description": "该引用必须被拒绝。", "status": "planted", "planted_chapter_id": foreign_source["chapter_id"], "planted_source_span_id": foreign_source["id"]}})
        self.assertEqual((failed.status_code, failed.json()["error"]["code"]), (422, "foreshadow_reference_invalid"))
        second_project = self.client.post("/api/projects", headers=idem(), json={"title": "隔离项目"}).json()["data"]["project"]["id"]
        crossed = self.client.post(f"/api/projects/{second_project}/analyses/{run_id}/foreshadow-candidates/{candidate['id']}/decision", headers=idem(), json={"base_foreshadow_version": 0, "decision": "rejected"})
        self.assertEqual(crossed.status_code, 404)
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT decision_status FROM v2_foreshadow_candidates WHERE id=?", (candidate["id"],)).fetchone()[0], "pending")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_foreshadow_candidate_decisions WHERE candidate_id=?", (candidate["id"],)).fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_foreshadows WHERE project_id=?", (self.project_id,)).fetchone()[0], 0)

    def test_scan_zero_evidence_invalid_evidence_timeout_and_stale_are_safe(self):
        self.provider.mode = "zero_candidates"
        zero = self.analysis("foreshadow_scan")
        zero_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{zero.json()['data']['run_id']}").json()["data"]
        self.assertEqual(zero_view["analysis"], {"summary": "当前未发现有可采信已写证据的伏笔候选。", "items": [], "evidence_status": "insufficient", "candidates": []})
        self.provider.mode = "invalid_evidence"
        invalid = self.analysis("foreshadow_scan")
        invalid_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{invalid.json()['data']['run_id']}").json()["data"]
        self.assertEqual((invalid_view["status"], invalid_view["error_code"]), ("failed", "evidence_unresolvable"))
        self.provider.mode = "timeout"
        timed = self.analysis("foreshadow_scan")
        timed_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{timed.json()['data']['run_id']}").json()["data"]
        self.assertEqual((timed_view["status"], timed_view["error_code"]), ("timed_out", "provider_timeout"))
        self.provider.mode = "valid"
        current = self.analysis("foreshadow_scan")
        run_id = current.json()["data"]["run_id"]
        self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=idem(), json=self.foreshadow_payload())
        stale = self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertTrue(stale["is_stale"])
        candidate = stale["analysis"]["candidates"][0]
        decision = self.client.post(f"/api/projects/{self.project_id}/analyses/{run_id}/foreshadow-candidates/{candidate['id']}/decision", headers=idem(), json={"base_foreshadow_version": 1, "decision": "rejected"})
        self.assertEqual((decision.status_code, decision.json()["error"]["code"]), (409, "foreshadow_candidate_stale"))
        self.provider.mode = "contradictory_status"
        contradictory = self.analysis("foreshadow_scan")
        contradictory_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{contradictory.json()['data']['run_id']}").json()["data"]
        self.assertEqual((contradictory_view["status"], contradictory_view["error_code"]), ("failed", "evidence_unresolvable"))

    def test_list_cancel_retry_and_migration_repeatability(self):
        queued = []
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-qa-cancel-"))
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=BoundedToolsProvider(), executor=lambda fn, *args: queued.append((fn, args)), settings=Stage13Settings.for_test())
        client = TestClient(app)
        registered = client.post("/api/auth/register", headers=idem(), json={"account_name": "bounded-cancel", "display_name": "Author", "password": "safe-password-v130", "recovery_email": "bounded-cancel@example.test"}).json()["data"]
        project_id = registered["onboarding"]["tutorial"]["project_id"]
        project = client.get(f"/api/projects/{project_id}").json()["data"]
        draft = project["current_draft"]
        created = client.post(f"/api/projects/{project_id}/analyses", headers=idem(), json={"analysis_type": "story_qa", "draft_id": draft["id"], "draft_revision": draft["revision"], "question": "问题", "scope": ["confirmed"]}).json()["data"]
        concurrent = client.post(f"/api/projects/{project_id}/analyses", headers=idem(), json={"analysis_type": "story_qa", "draft_id": draft["id"], "draft_revision": draft["revision"], "question": "第二个问题", "scope": ["confirmed"]})
        self.assertEqual((concurrent.status_code, concurrent.json()["error"]["code"]), (409, "run_already_active"))
        listed = client.get(f"/api/projects/{project_id}/analyses?analysis_type=story_qa").json()["data"]
        self.assertEqual(listed["run"]["run_id"], created["run_id"])
        cancelled = client.post(f"/api/projects/{project_id}/analyses/{created['run_id']}/cancel", headers=idem(), json={"client_request_id": str(uuid.uuid4())})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        retried = client.post(f"/api/projects/{project_id}/analyses/{created['run_id']}/retry", headers=idem(), json={"client_request_id": str(uuid.uuid4())})
        self.assertEqual((retried.status_code, retried.json()["data"]["run"]["run_type"]), (202, "story_qa"))
        fn, args = queued[0]
        fn(*args)
        cancelled_view = client.get(f"/api/projects/{project_id}/analyses/{created['run_id']}").json()["data"]
        self.assertEqual((cancelled_view["status"], cancelled_view.get("analysis")), ("cancelled", None))
        with app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_analysis_results WHERE run_id=?", (created["run_id"],)).fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_foreshadow_candidates WHERE run_id=?", (created["run_id"],)).fetchone()[0], 0)
        app.state.database.initialize()
        with app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=135").fetchone()[0], 1)
            self.assertIn("foreshadow_version", {row["name"] for row in connection.execute("PRAGMA table_info(v2_projects)")})


if __name__ == "__main__":
    unittest.main()
