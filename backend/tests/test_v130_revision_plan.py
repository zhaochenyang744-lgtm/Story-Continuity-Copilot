from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderInvalidJson, ProviderResult, ProviderTimeout
from app.stage13 import Stage13Settings


def idem(value: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": value or str(uuid.uuid4()), "Origin": "http://testserver"}


class RevisionPlanProvider:
    available = True
    label = "revision-plan-test-provider"
    model_label = "revision-plan-test-model"

    def __init__(self):
        self.mode = "valid"
        self.requests: list[dict] = []

    def evaluate(self, request):
        self.requests.append(request)
        if request.get("task") == "revision_plan":
            if self.mode == "timeout":
                raise ProviderTimeout()
            if self.mode == "invalid_json":
                raise ProviderInvalidJson()
            issues = request["selected_issues"]
            candidates = []
            for index, issue in enumerate(issues):
                evidence_id = "missing" if self.mode == "invalid_evidence" else issue["evidence"][0]["id"]
                candidates.append({
                    "issue_id": issue["id"],
                    "title": "重复任务" if self.mode == "duplicate" else f"修订任务 {index + 1}",
                    "instruction": "回到同一草稿，依据已写来源手动修正这处叙述。",
                    "priority": "high" if issue["severity"] == "high" else "medium",
                    "evidence": [{"source_type": "issue_evidence", "source_id": evidence_id}],
                })
            if self.mode == "zero":
                candidates = []
            return ProviderResult({"summary": "已生成作者可审阅的修订建议。", "candidates": candidates}, 12, 6, latency_ms=1)

        claim = next((item for item in request["claims"] if item["allowed_evidence"]), None)
        if claim is None:
            return ProviderResult({"issues": []}, 4, 2, latency_ms=1)
        source = claim["allowed_evidence"][0]
        return ProviderResult({"issues": [{
            "claim_span_id": claim["id"],
            "status": "conflict",
            "category": "object_state",
            "severity": "high",
            "explanation": "当前草稿与既有来源需要作者核对。",
            "evidence": [{
                "chapter_id": source["chapter_id"],
                "span_id": source["id"],
                "relation": "contradicts",
                "sufficiency": "sufficient",
                "related_memory_ids": [],
            }],
            "proposed_memory_change": None,
        }]}, 8, 4, latency_ms=1)


class V130RevisionPlanTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-revision-plan-"))
        self.provider = RevisionPlanProvider()
        self.app = create_app(
            AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
            provider=self.provider,
            executor=lambda fn, *args: fn(*args),
            settings=Stage13Settings.for_test(),
        )
        self.client = TestClient(self.app)
        registered = self.client.post("/api/auth/register", headers=idem(), json={
            "account_name": f"revision-{uuid.uuid4().hex[:10]}",
            "display_name": "Revision Author",
            "password": "safe-password-v130",
            "recovery_email": f"revision-{uuid.uuid4().hex[:10]}@example.test",
        })
        self.assertEqual(registered.status_code, 201, registered.text)
        self.project_id = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        self.project = self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        draft_summary = self.project["current_draft"]
        self.draft = self.client.get(f"/api/projects/{self.project_id}/drafts/{draft_summary['id']}").json()["data"]
        with self.app.state.database.connection() as connection:
            rows = connection.execute(
                "SELECT i.id FROM v2_issues i JOIN v2_runs r ON r.id=i.run_id WHERE i.project_id=? AND i.status='open' AND r.status='completed' ORDER BY i.id",
                (self.project_id,),
            ).fetchall()
            self.issue_ids = [row["id"] for row in rows]
        self.assertGreaterEqual(len(self.issue_ids), 3)

    def analysis(self, issue_ids: list[str], draft: dict | None = None):
        current = draft or self.draft
        return self.client.post(f"/api/projects/{self.project_id}/analyses", headers=idem(), json={
            "analysis_type": "revision_plan",
            "draft_id": current["id"],
            "draft_revision": current["revision"],
            "issue_ids": issue_ids,
        })

    def view(self, run_id: str):
        return self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]

    def decide(self, run_id: str, candidate_id: str, version: int, decision: str, edited: dict | None = None, key: str | None = None):
        payload = {"base_task_version": version, "decision": decision}
        if edited is not None:
            payload["edited"] = edited
        return self.client.post(
            f"/api/projects/{self.project_id}/analyses/{run_id}/revision-candidates/{candidate_id}/decision",
            headers=idem(key),
            json=payload,
        )

    def test_partial_accept_edit_reject_cas_idempotency_and_no_canon_write(self):
        memory_before = self.project["current_memory_version"]
        created = self.analysis(self.issue_ids[:3])
        self.assertEqual(created.status_code, 202, created.text)
        run_id = created.json()["data"]["run_id"]
        view = self.view(run_id)
        self.assertEqual((view["status"], len(view["analysis"]["candidates"]), view["source_run_id"]), ("completed", 3, view["analysis"]["source_run_id"]))
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/revision-tasks").json()["data"]["tasks"], [])

        first, second, third = view["analysis"]["candidates"]
        key = str(uuid.uuid4())
        accepted = self.decide(run_id, first["id"], 0, "accepted", key=key)
        self.assertEqual((accepted.status_code, accepted.json()["data"]["decision_status"]), (200, "accepted"))
        replay = self.decide(run_id, first["id"], 0, "accepted", key=key)
        self.assertEqual(replay.json()["data"], accepted.json()["data"])
        edited = self.decide(run_id, second["id"], 1, "edited", {
            "title": "作者改写的修订任务",
            "instruction": "作者决定先核对时间线，再手动修改正文。",
            "priority": "low",
        })
        self.assertEqual((edited.status_code, edited.json()["data"]["decision_status"]), (200, "edited"))
        rejected = self.decide(run_id, third["id"], 2, "rejected")
        self.assertEqual((rejected.status_code, rejected.json()["data"]["decision_status"]), (200, "rejected"))

        refreshed = self.view(run_id)
        self.assertFalse(refreshed["is_stale"])
        self.assertEqual([item["decision_status"] for item in refreshed["analysis"]["candidates"]], ["accepted", "edited", "rejected"])
        snapshot = self.client.get(f"/api/projects/{self.project_id}/revision-tasks").json()["data"]
        self.assertEqual((snapshot["task_version"], len(snapshot["tasks"])), (2, 2))
        task = snapshot["tasks"][0]
        conflict = self.client.patch(f"/api/projects/{self.project_id}/revision-tasks/{task['id']}", headers=idem(), json={"base_version": 9, "status": "in_progress"})
        self.assertEqual((conflict.status_code, conflict.json()["error"]["code"]), (409, "revision_task_version_conflict"))
        update_key = str(uuid.uuid4())
        progressed = self.client.patch(f"/api/projects/{self.project_id}/revision-tasks/{task['id']}", headers=idem(update_key), json={"base_version": 1, "status": "in_progress"})
        replay_progress = self.client.patch(f"/api/projects/{self.project_id}/revision-tasks/{task['id']}", headers=idem(update_key), json={"base_version": 1, "status": "in_progress"})
        self.assertEqual(progressed.json()["data"], replay_progress.json()["data"])
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT status FROM v2_issues WHERE id=?", (task["issue_id"],)).fetchone()[0], "open")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_decisions WHERE issue_id=?", (task["issue_id"],)).fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (self.project_id,)).fetchone()[0], memory_before)

    def test_draft_revision_and_source_revision_are_distinct_bindings(self):
        draft = self.draft
        saved = self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}", headers=idem(), json={
            "base_revision": draft["revision"],
            "title": draft["title"],
            "body": f"{draft['body']}\n银钥匙仍由林默保管。",
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        draft = {**draft, **saved.json()["data"]}
        project = self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        self.assertEqual((draft["revision"], project["source_revision"]), (2, 1))
        check = self.client.post(f"/api/projects/{self.project_id}/checks", headers=idem(), json={"draft_id": draft["id"], "draft_revision": draft["revision"]})
        self.assertEqual(check.status_code, 202, check.text)
        check_view = self.client.get(f"/api/projects/{self.project_id}/checks/{check.json()['data']['run_id']}?include=issues,evidence").json()["data"]
        self.assertEqual(check_view["source_revision"], 2)
        current_issue = check_view["issues"][0]["id"]
        planned = self.analysis([current_issue], draft)
        self.assertEqual(planned.status_code, 202, planned.text)
        planned_view = self.view(planned.json()["data"]["run_id"])
        self.assertEqual((planned_view["draft_revision"], planned_view["source_revision"], planned_view["status"]), (2, 1, "completed"))
        old = self.analysis([self.issue_ids[0]], draft)
        self.assertEqual((old.status_code, old.json()["error"]["code"]), (409, "revision_plan_issue_stale"))

    def test_saved_draft_stales_suggestions_but_not_accepted_task_progress(self):
        created = self.analysis([self.issue_ids[0]])
        run_id = created.json()["data"]["run_id"]
        candidate = self.view(run_id)["analysis"]["candidates"][0]
        accepted = self.decide(run_id, candidate["id"], 0, "accepted").json()["data"]
        task = accepted["revision_tasks"]["tasks"][0]
        draft = self.draft
        saved = self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}", headers=idem(), json={"base_revision": draft["revision"], "title": draft["title"], "body": draft["body"] + "\n作者手动完成修订。"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(self.view(run_id)["is_stale"])
        progressed = self.client.patch(f"/api/projects/{self.project_id}/revision-tasks/{task['id']}", headers=idem(), json={"base_version": 1, "status": "completed"})
        self.assertEqual((progressed.status_code, progressed.json()["data"]["item"]["status"]), (200, "completed"))
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/revision-tasks?include_completed=false").json()["data"]["tasks"], [])
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT status FROM v2_issues WHERE id=?", (task["issue_id"],)).fetchone()[0], "open")

    def test_invalid_output_timeout_cross_project_and_stale_candidate_fail_closed(self):
        for mode, code in (("zero", "revision_plan_candidate_count_invalid"), ("invalid_evidence", "evidence_unresolvable"), ("duplicate", "revision_plan_candidate_duplicate"), ("invalid_json", "invalid_json"), ("timeout", "provider_timeout")):
            self.provider.mode = mode
            created = self.analysis(self.issue_ids[:2] if mode == "duplicate" else [self.issue_ids[0]])
            run_id = created.json()["data"]["run_id"]
            view = self.view(run_id)
            self.assertEqual(view["error_code"], code)
            with self.app.state.database.connection() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_revision_plan_candidates WHERE run_id=?", (run_id,)).fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_analysis_results WHERE run_id=?", (run_id,)).fetchone()[0], 0)
        self.provider.mode = "valid"
        created = self.analysis([self.issue_ids[0]])
        run_id = created.json()["data"]["run_id"]
        candidate = self.view(run_id)["analysis"]["candidates"][0]
        outsider = TestClient(self.app)
        foreign = outsider.post("/api/auth/register", headers=idem(), json={"account_name": f"foreign-{uuid.uuid4().hex[:8]}", "display_name": "Other", "password": "safe-password-v130", "recovery_email": f"foreign-{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]["onboarding"]["tutorial"]["project_id"]
        crossed = self.client.post(f"/api/projects/{foreign}/analyses/{run_id}/revision-candidates/{candidate['id']}/decision", headers=idem(), json={"base_task_version": 0, "decision": "rejected"})
        self.assertEqual(crossed.status_code, 404)
        draft = self.draft
        self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}", headers=idem(), json={"base_revision": draft["revision"], "title": draft["title"], "body": draft["body"] + "\n使建议过期。"})
        stale = self.decide(run_id, candidate["id"], 0, "accepted")
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (409, "revision_candidate_stale"))

    def test_completed_task_reopen_enforces_duplicate_and_active_limit_without_audit(self):
        created = self.analysis(self.issue_ids[:2])
        run_id = created.json()["data"]["run_id"]
        first, second = self.view(run_id)["analysis"]["candidates"]
        first_decision = self.decide(run_id, first["id"], 0, "accepted").json()["data"]
        first_task = first_decision["revision_tasks"]["tasks"][0]
        completed = self.client.patch(f"/api/projects/{self.project_id}/revision-tasks/{first_task['id']}", headers=idem(), json={"base_version": 1, "status": "completed"})
        self.assertEqual(completed.status_code, 200, completed.text)
        same_title = self.decide(run_id, second["id"], 2, "edited", {"title": first_task["title"], "instruction": "另一项作者任务。", "priority": "medium"})
        self.assertEqual(same_title.status_code, 200, same_title.text)
        with self.app.state.database.connection() as connection:
            audit_before = connection.execute("SELECT COUNT(*) FROM v2_revision_task_versions WHERE task_id=?", (first_task["id"],)).fetchone()[0]
            version_before = connection.execute("SELECT revision_task_version FROM v2_projects WHERE id=?", (self.project_id,)).fetchone()[0]
        duplicate = self.client.patch(f"/api/projects/{self.project_id}/revision-tasks/{first_task['id']}", headers=idem(), json={"base_version": 2, "status": "todo"})
        self.assertEqual((duplicate.status_code, duplicate.json()["error"]["code"]), (409, "revision_task_duplicate"))
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_revision_task_versions WHERE task_id=?", (first_task["id"],)).fetchone()[0], audit_before)
            self.assertEqual(connection.execute("SELECT revision_task_version FROM v2_projects WHERE id=?", (self.project_id,)).fetchone()[0], version_before)
        with patch("app.v2_database.REVISION_TASK_MAX_RECORDS", 1):
            limited = self.client.patch(f"/api/projects/{self.project_id}/revision-tasks/{first_task['id']}", headers=idem(), json={"base_version": 2, "status": "in_progress"})
        self.assertEqual((limited.status_code, limited.json()["error"]["code"]), (409, "revision_task_limit_reached"))

    def test_cancel_discards_late_result_retry_and_migration_are_safe(self):
        queued: list[tuple] = []
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-revision-cancel-"))
        provider = RevisionPlanProvider()
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=provider, executor=lambda fn, *args: queued.append((fn, args)), settings=Stage13Settings.for_test())
        client = TestClient(app)
        registered = client.post("/api/auth/register", headers=idem(), json={"account_name": f"cancel-{uuid.uuid4().hex[:8]}", "display_name": "Cancel", "password": "safe-password-v130", "recovery_email": f"cancel-{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        project_id = registered["onboarding"]["tutorial"]["project_id"]
        project = client.get(f"/api/projects/{project_id}").json()["data"]
        with app.state.database.connection() as connection:
            issue_id = connection.execute("SELECT id FROM v2_issues WHERE project_id=? AND status='open' ORDER BY id LIMIT 1", (project_id,)).fetchone()[0]
        created = client.post(f"/api/projects/{project_id}/analyses", headers=idem(), json={"analysis_type": "revision_plan", "draft_id": project["current_draft"]["id"], "draft_revision": project["current_draft"]["revision"], "issue_ids": [issue_id]})
        run_id = created.json()["data"]["run_id"]
        cancelled = client.post(f"/api/projects/{project_id}/analyses/{run_id}/cancel", headers=idem(), json={})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        fn, args = queued.pop(0)
        fn(*args)
        view = client.get(f"/api/projects/{project_id}/analyses/{run_id}").json()["data"]
        self.assertEqual(view["status"], "cancelled")
        with app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_revision_plan_candidates WHERE run_id=?", (run_id,)).fetchone()[0], 0)
        retried = client.post(f"/api/projects/{project_id}/analyses/{run_id}/retry", headers=idem(), json={})
        self.assertEqual(retried.status_code, 202, retried.text)
        retry_id = retried.json()["data"]["run"]["run_id"]
        fn, args = queued.pop(0)
        fn(*args)
        self.assertEqual(client.get(f"/api/projects/{project_id}/analyses/{retry_id}").json()["data"]["status"], "completed")
        app.state.database.initialize()
        self.assertTrue(app.state.database.readiness_probe())


if __name__ == "__main__":
    unittest.main()
