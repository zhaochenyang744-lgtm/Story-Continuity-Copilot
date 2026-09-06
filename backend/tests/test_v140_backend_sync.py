import json
import os
import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.engine import ContinuityEngine
from app.main import create_app
from app.provider import ProviderResult


def idem(value=None):
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class TrustworthyProvider:
    available = True
    label = "injected-v140-provider"
    model_label = "injected-v140-model"

    def __init__(self):
        self.calls = 0

    def evaluate(self, request):
        self.calls += 1
        claim = request["claims"][0]
        evidence = claim["allowed_evidence"][0]
        return ProviderResult(payload={"issues": [{
            "claim_span_id": claim["id"], "status": "conflict", "nature": "possible_conflict",
            "category": "object_state", "severity": "medium", "explanation": "存在需要作者复核的状态张力。",
            "reasoning": "引用来源给出较早状态，但没有封闭后续转移的可能，因此只标记为可能冲突。",
            "evidence": [{"chapter_id": evidence["chapter_id"], "span_id": evidence["id"], "relation": "context", "sufficiency": "sufficient", "related_memory_ids": []}],
            "evidence_chain": [{"span_id": evidence["id"], "role": "prior_state"}],
            "suggested_revision": None, "available_actions": ["false_positive"],
        }]}, input_tokens=11, output_tokens=13, latency_ms=2)


class V140BackendSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update({
            "PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3080",
            "BACKEND_ORIGIN": "http://127.0.0.1:8080", "TRUSTED_HOSTS": "127.0.0.1:8080,testserver",
            "TRUSTED_ORIGINS": "http://127.0.0.1:3080,http://testserver",
        })

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v140-"))
        self.provider = TrustworthyProvider()
        self.app = create_app(AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected"), provider=self.provider, executor=lambda fn, *args: fn(*args))
        self.client = TestClient(self.app)
        registered = self.client.post("/api/auth/register", json={"account_name": "v140author", "display_name": "V140", "password": "safe-password-140"}, headers=idem())
        self.assertEqual(registered.status_code, 201)
        self.project_id = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]

    def project(self):
        return self.client.get(f"/api/projects/{self.project_id}").json()["data"]

    def view_run(self, run_id):
        return self.client.get(f"/api/projects/{self.project_id}/checks/{run_id}?include=issues,evidence,metrics")

    def test_new_seed_exposes_four_auditable_natures_and_no_provider_effect(self):
        run = self.view_run(self.project()["latest_run"]["run_id"]).json()["data"]
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual({issue["nature"] for issue in run["issues"]}, {"confirmed_conflict", "state_change", "possible_conflict", "insufficient_evidence"})
        for issue in run["issues"]:
            self.assertEqual(issue["review_contract_version"], "trustworthy_review_v1")
            self.assertTrue(issue["reasoning"])
            self.assertEqual({item["evidence_id"] for item in issue["evidence_chain"]}, {item["id"] for item in issue["evidence"]})
        insufficient = next(issue for issue in run["issues"] if issue["nature"] == "insufficient_evidence")
        self.assertEqual(insufficient["available_actions"], [])
        denied = self.client.post(f"/api/projects/{self.project_id}/issues/{insufficient['id']}/decision", json={"run_id": run["run_id"], "source_revision": 1, "decision": "false_positive"}, headers=idem())
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (409, "issue_decision_unavailable"))

    def test_validated_provider_result_persists_and_server_gates_actions(self):
        project = self.project(); draft = self.client.get(f"/api/projects/{self.project_id}/drafts/{project['current_draft']['id']}").json()["data"]
        created = self.client.post(f"/api/projects/{self.project_id}/checks", json={"draft_id": draft["id"], "draft_revision": draft["revision"]}, headers=idem())
        self.assertEqual(created.status_code, 202)
        run = self.view_run(created.json()["data"]["run_id"]).json()["data"]
        issue = run["issues"][0]
        self.assertEqual((self.provider.calls, issue["review_contract_version"], issue["nature"]), (1, "trustworthy_review_v1", "possible_conflict"))
        self.assertEqual(issue["evidence_chain"][0]["evidence_id"], issue["evidence"][0]["id"])
        denied = self.client.post(f"/api/projects/{self.project_id}/issues/{issue['id']}/decision", json={"run_id": run["run_id"], "source_revision": 1, "decision": "keep_intentional"}, headers=idem())
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (409, "issue_action_unavailable"))
        allowed = self.client.post(f"/api/projects/{self.project_id}/issues/{issue['id']}/decision", json={"run_id": run["run_id"], "source_revision": 1, "decision": "false_positive"}, headers=idem())
        self.assertEqual(allowed.status_code, 200)

    def test_legacy_rows_are_not_semantically_reinterpreted(self):
        run_id = self.project()["latest_run"]["run_id"]
        with self.app.state.database.connection() as c:
            issue_id = c.execute("SELECT id FROM v2_issues WHERE run_id=? ORDER BY id LIMIT 1", (run_id,)).fetchone()[0]
            c.execute("UPDATE v2_issues SET review_contract_version=NULL,nature=NULL,reasoning=NULL,evidence_chain_json=NULL,suggested_revision_json=NULL,available_actions_json=NULL WHERE id=?", (issue_id,))
            before = tuple(c.execute("SELECT classification,category,severity,evidence_status,explanation FROM v2_issues WHERE id=?", (issue_id,)).fetchone())
        self.app.state.database.initialize()
        viewed = next(item for item in self.view_run(run_id).json()["data"]["issues"] if item["id"] == issue_id)
        self.assertEqual(viewed["review_contract_version"], "legacy_v3")
        self.assertNotIn("nature", viewed)
        with self.app.state.database.connection() as c:
            after = tuple(c.execute("SELECT classification,category,severity,evidence_status,explanation FROM v2_issues WHERE id=?", (issue_id,)).fetchone())
            columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_issues)")}
        self.assertEqual(before, after)
        self.assertTrue({"nature", "reasoning", "evidence_chain_json", "suggested_revision_json", "available_actions_json"} <= columns)

    def test_suggested_revision_requires_complete_contract_and_unique_bound_text(self):
        data = {"draft": {"id": "d", "revision": 1, "body": "重复。重复。"}, "memory": [], "claims": [{"id": "c", "text": "重复。", "allowed_evidence": [{"id": "s", "chapter_id": "ch", "body": "旧状态。", "prompt_excerpt": "旧状态。"}]}]}
        issue = {"claim_span_id": "c", "status": "conflict", "nature": "confirmed_conflict", "category": "object_state", "severity": "high", "explanation": "x", "reasoning": "同一对象与时间范围直接冲突。", "evidence": [{"chapter_id": "ch", "span_id": "s", "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []}], "evidence_chain": [{"span_id": "s", "role": "prior_state"}], "suggested_revision": {"before": "重复。", "after": "唯一。"}, "available_actions": ["apply_suggestion"]}
        with self.assertRaisesRegex(ValueError, "suggested_revision_unresolvable"):
            ContinuityEngine(self.provider).validate({"issues": [issue]}, data)
        partial = dict(issue); partial.pop("reasoning")
        with self.assertRaisesRegex(ValueError, "schema_invalid"):
            ContinuityEngine(self.provider).validate({"issues": [partial]}, data)

    def _project_snapshot(self):
        tables = ("v2_chapters", "v2_source_spans", "v2_drafts", "v2_memory_versions", "v2_memory_records", "v2_runs", "v2_issues", "v2_evidence", "v2_decisions", "v2_author_story_plans", "v2_author_character_plans", "v2_author_world_plans", "v2_author_context_versions")
        with self.app.state.database.connection() as c:
            result = {}
            for table in tables:
                columns = {row["name"] for row in c.execute(f"PRAGMA table_info({table})")}
                if "project_id" in columns:
                    rows = c.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY 1", (self.project_id,)).fetchall()
                elif table == "v2_evidence":
                    rows = c.execute("SELECT e.* FROM v2_evidence e JOIN v2_issues i ON i.id=e.issue_id WHERE i.project_id=? ORDER BY e.id", (self.project_id,)).fetchall()
                else:
                    rows = []
                result[table] = [tuple(row) for row in rows]
            draft_ids = [row[0] for row in c.execute("SELECT id FROM v2_drafts WHERE project_id=?", (self.project_id,)).fetchall()]
            result["v2_draft_revisions"] = [tuple(row) for row in c.execute("SELECT * FROM v2_draft_revisions WHERE draft_id IN (%s) ORDER BY draft_id,revision" % ",".join("?" for _ in draft_ids), draft_ids).fetchall()]
            user = c.execute("SELECT display_name,avatar_preset,profile_revision FROM v2_users WHERE onboarding_tutorial_project_id=?", (self.project_id,)).fetchone()
            result["profile"] = tuple(user)
            return result

    def test_progress_restart_is_idempotent_progress_only_and_owner_scoped(self):
        onboarding = self.client.get("/api/onboarding").json()["data"]
        before = self._project_snapshot(); key = str(uuid.uuid4())
        payload = {"tutorial_version": "1.2.0", "project_id": self.project_id, "base_revision": onboarding["progress"]["revision"], "confirm": True}
        first = self.client.post("/api/onboarding/progress/restart", json=payload, headers=idem(key))
        replay = self.client.post("/api/onboarding/progress/restart", json=payload, headers=idem(key))
        self.assertEqual((first.status_code, first.json()["data"]), (200, replay.json()["data"]))
        self.assertEqual((first.json()["data"]["progress"]["current_step"], first.json()["data"]["progress"]["completed_events"]), (1, []))
        self.assertEqual(before, self._project_snapshot())
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_tutorial_progress_restarts WHERE user_id=(SELECT id FROM v2_users WHERE onboarding_tutorial_project_id=?)", (self.project_id,)).fetchone()[0], 1)
        conflict = self.client.post("/api/onboarding/progress/restart", json={**payload, "base_revision": payload["base_revision"] + 1}, headers=idem(key))
        self.assertEqual((conflict.status_code, conflict.json()["error"]["code"]), (409, "idempotency_conflict"))
        outsider = TestClient(self.app)
        outsider.post("/api/auth/register", json={"account_name": "v140other", "display_name": "Other", "password": "safe-password-141"}, headers=idem())
        denied = outsider.post("/api/onboarding/progress/restart", json={**payload, "base_revision": None}, headers=idem())
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (409, "tutorial_progress_target_invalid"))

    def _tutorial_event(self, event, **extra):
        return self.client.post(
            "/api/onboarding/progress",
            json={"tutorial_version": "1.2.0", "project_id": self.project_id, "event": event, **extra},
            headers=idem(),
        )

    def test_completed_decisions_can_be_reviewed_after_progress_restart_without_mutation(self):
        run_id = self.project()["latest_run"]["run_id"]
        run = self.view_run(run_id).json()["data"]
        actionable = [issue for issue in run["issues"] if "false_positive" in issue["available_actions"]]
        for issue in actionable:
            decided = self.client.post(
                f"/api/projects/{self.project_id}/issues/{issue['id']}/decision",
                json={"run_id": run_id, "source_revision": run["source_revision"], "decision": "false_positive"},
                headers=idem(),
            )
            self.assertEqual(decided.status_code, 200, decided.text)
        for event in ("memory_source_opened", "continuity_issue_located", "evidence_opened", "author_decision_recorded"):
            self.assertEqual(self._tutorial_event(event).status_code, 200)
        self.assertEqual(self.client.post("/api/onboarding/complete", json={"confirm": True}, headers=idem()).status_code, 200)
        before = self._project_snapshot()
        restarted = self.client.post(
            "/api/onboarding/progress/restart",
            json={"tutorial_version": "1.2.0", "project_id": self.project_id, "base_revision": None, "confirm": True},
            headers=idem(),
        )
        self.assertEqual(restarted.status_code, 200, restarted.text)
        for event in ("memory_source_opened", "continuity_issue_located", "evidence_opened"):
            self.assertEqual(self._tutorial_event(event).status_code, 200)
        reviewed = self._tutorial_event(
            "author_decision_reviewed", run_id=run_id, issue_id=actionable[0]["id"]
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["data"]["current_step"], 5)
        self.assertIn("author_decision_reviewed", reviewed.json()["data"]["completed_events"])
        self.assertEqual(self.client.post("/api/onboarding/complete", json={"confirm": True}, headers=idem()).status_code, 200)
        self.assertEqual(before, self._project_snapshot())
        self.assertEqual(self.provider.calls, 0)

    def test_review_path_supports_partial_and_stale_runs_but_requires_evidence_and_existing_decision(self):
        project = self.project()
        run_id = project["latest_run"]["run_id"]
        run = self.view_run(run_id).json()["data"]
        actionable = [issue for issue in run["issues"] if issue["available_actions"]]
        decided_issue, undecided_issue = actionable[:2]
        decided = self.client.post(
            f"/api/projects/{self.project_id}/issues/{decided_issue['id']}/decision",
            json={"run_id": run_id, "source_revision": run["source_revision"], "decision": "false_positive"},
            headers=idem(),
        )
        self.assertEqual(decided.status_code, 200, decided.text)
        denied_early = self._tutorial_event(
            "author_decision_reviewed", run_id=run_id, issue_id=decided_issue["id"]
        )
        self.assertEqual((denied_early.status_code, denied_early.json()["error"]["code"]), (409, "tutorial_decision_review_unavailable"))
        for event in ("memory_source_opened", "continuity_issue_located", "evidence_opened"):
            self.assertEqual(self._tutorial_event(event).status_code, 200)
        denied_undecided = self._tutorial_event(
            "author_decision_reviewed", run_id=run_id, issue_id=undecided_issue["id"]
        )
        self.assertEqual((denied_undecided.status_code, denied_undecided.json()["error"]["code"]), (409, "tutorial_decision_review_unavailable"))
        draft = self.client.get(f"/api/projects/{self.project_id}/drafts/{project['current_draft']['id']}").json()["data"]
        saved = self.client.patch(
            f"/api/projects/{self.project_id}/drafts/{draft['id']}",
            json={"base_revision": draft["revision"], "body": draft["body"] + "\n旧检查之后的新段落。"},
            headers=idem(),
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(self.view_run(run_id).json()["data"]["is_stale"])
        before = self._project_snapshot()
        reviewed = self._tutorial_event(
            "author_decision_reviewed", run_id=run_id, issue_id=decided_issue["id"]
        )
        self.assertEqual((reviewed.status_code, reviewed.json()["data"]["current_step"]), (200, 5))
        self.assertEqual(before, self._project_snapshot())


if __name__ == "__main__":
    unittest.main()
