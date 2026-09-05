from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult, request_prompt_and_budget
from app.stage13 import Stage13Settings


def idem(value: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class LayeredProvider:
    available=True
    label="analysis-stub"
    model_label="analysis-stub-model"

    def __init__(self):
        self.requests=[]
        self.invalid=False

    def evaluate(self,request):
        self.requests.append(request)
        if request.get("task")=="context_brief":
            if self.invalid:return ProviderResult({"summary":"bad","items":[]})
            planned=request["layers"]["planned"]["story_plans"]
            memory=request["layers"]["confirmed"]["memory_records"]
            spans=request["layers"]["written"]["source_spans"]
            if planned:source={"source_type":"author_context","source_id":planned[0]["id"]};section="related_plan"
            elif memory:source={"source_type":"memory_record","source_id":memory[0]["id"]};section="confirmed_fact"
            else:source={"source_type":"source_span","source_id":spans[0]["id"]};section="recent_source"
            return ProviderResult({"summary":"写作前先守住既有约束。","summary_sources":[source],"items":[{"section":section,"text":"本章需要延续已绑定的上下文。","sources":[source]}]},input_tokens=12,output_tokens=6,latency_ms=2)
        if request.get("task")=="plan_alignment":
            claims=request["layers"]["written"]["draft_claims"]
            return ProviderResult({"summary":"草稿覆盖了当前计划。","items":[{"story_plan_id":plan["id"],"status":"planned_covered","explanation":"草稿已直接写到计划动作。","evidence":[{"source_type":"draft_claim","source_id":claims[0]["id"]}]} for plan in request["layers"]["planned"]["story_plans"]]},input_tokens=13,output_tokens=7,latency_ms=2)
        return ProviderResult({"issues":[]},input_tokens=3,output_tokens=1,latency_ms=1)


class V130WritingAnalysisTests(unittest.TestCase):
    def setUp(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-writing-analysis-"))
        self.provider=LayeredProvider()
        self.app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/"protected"),provider=self.provider,executor=lambda fn,*args:fn(*args),settings=Stage13Settings.for_test())
        self.client=TestClient(self.app)
        registered=self.client.post("/api/auth/register",headers=idem(),json={"account_name":"analysis-owner","display_name":"Author","password":"safe-password-v130","recovery_email":"analysis-owner@example.test"})
        self.assertEqual(registered.status_code,201,registered.text)
        self.project_id=registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        self.project=self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        plan=self.client.post(f"/api/projects/{self.project_id}/author-intent/story-plans",headers=idem(),json={"base_author_context_version":0,"title":"让林默带着潮汐表返回雾港","summary":"本章完成返航。","goal":"让返航动作落到正文。","status":"planned","target_chapter_number":self.project["current_draft"]["chapter_number"]})
        self.assertEqual(plan.status_code,201,plan.text)
        self.plan_id=plan.json()["data"]["item"]["id"]

    def _save(self,body="林默带着潮汐表返回雾港。她听见北门的雾钟。"):
        draft=self.project["current_draft"]
        saved=self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}",headers=idem(),json={"base_revision":draft["revision"],"body":body})
        self.assertEqual(saved.status_code,200,saved.text)
        self.project=self.client.get(f"/api/projects/{self.project_id}").json()["data"]

    def _run(self,kind,key=None):
        draft=self.project["current_draft"]
        return self.client.post(f"/api/projects/{self.project_id}/analyses",headers=idem(key),json={"analysis_type":kind,"draft_id":draft["id"],"draft_revision":draft["revision"]})

    def test_context_brief_and_alignment_are_layered_bound_and_resolvable(self):
        self._save()
        brief=self._run("context_brief")
        self.assertEqual(brief.status_code,202,brief.text)
        brief_view=self.client.get(f"/api/projects/{self.project_id}/analyses/{brief.json()['data']['run_id']}").json()["data"]
        self.assertEqual((brief_view["status"],brief_view["analysis_type"],brief_view["is_stale"]),("completed","context_brief",False))
        self.assertEqual(brief_view["analysis"]["items"][0]["sources"][0]["source_type"],"author_context")
        self.assertEqual(brief_view["retrieval"]["method_version"],"writing-analysis-lexical-v1")
        self.assertTrue(brief_view["retrieval"]["selected_ids"]["memory_record"])
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/checks/{brief.json()['data']['run_id']}").status_code,404)
        align=self._run("plan_alignment")
        self.assertEqual(align.status_code,202,align.text)
        aligned=self.client.get(f"/api/projects/{self.project_id}/analyses/{align.json()['data']['run_id']}").json()["data"]
        item=aligned["analysis"]["items"][0]
        self.assertEqual((item["story_plan_id"],item["status"]),(self.plan_id,"planned_covered"))
        self.assertEqual(item["evidence"][0]["source_type"],"draft_claim")
        self.assertTrue(item["evidence"][0]["source_path"].endswith("/workspace#draft-source"))
        request=self.provider.requests[-1]
        self.assertEqual(set(request["layers"]),{"planned","confirmed","written"})
        self.assertEqual(request["bindings"]["author_context_version"],1)

    def test_existing_continuity_provider_input_stays_free_of_author_context(self):
        self._save()
        draft=self.project["current_draft"]
        response=self.client.post(f"/api/projects/{self.project_id}/checks",headers=idem(),json={"draft_id":draft["id"],"draft_revision":draft["revision"]})
        self.assertEqual(response.status_code,202,response.text)
        request=self.provider.requests[-1]
        self.assertNotIn("task",request)
        self.assertNotIn("layers",request)
        self.assertNotIn("author_context",str(request).casefold())

    def test_invalid_schema_fails_closed_without_partial_result(self):
        self.provider.invalid=True
        response=self._run("context_brief")
        self.assertEqual(response.status_code,202,response.text)
        run_id=response.json()["data"]["run_id"]
        viewed=self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertEqual((viewed["status"],viewed["error_code"]),("failed","schema_invalid"))
        self.assertNotIn("analysis",viewed)
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_analysis_results WHERE run_id=?",(run_id,)).fetchone()[0],0)

    def test_no_plan_empty_draft_idempotency_isolation_and_staleness(self):
        created=self.client.post("/api/projects",headers=idem(),json={"title":"No plan"}).json()["data"]["project"]
        no_plan=self.client.post(f"/api/projects/{created['id']}/analyses",headers=idem(),json={"analysis_type":"plan_alignment","draft_id":created["current_draft"]["id"],"draft_revision":1})
        self.assertEqual((no_plan.status_code,no_plan.json()["error"]["code"]),(422,"analysis_draft_empty"))
        saved=self.client.patch(f"/api/projects/{created['id']}/drafts/{created['current_draft']['id']}",headers=idem(),json={"base_revision":1,"body":"只有正文，没有计划。"})
        self.assertEqual(saved.status_code,200,saved.text)
        no_plan_after_save=self.client.post(f"/api/projects/{created['id']}/analyses",headers=idem(),json={"analysis_type":"plan_alignment","draft_id":created["current_draft"]["id"],"draft_revision":2})
        self.assertEqual((no_plan_after_save.status_code,no_plan_after_save.json()["error"]["code"]),(422,"analysis_plan_unavailable"))
        no_evidence=self.client.post(f"/api/projects/{created['id']}/analyses",headers=idem(),json={"analysis_type":"context_brief","draft_id":created["current_draft"]["id"],"draft_revision":2})
        self.assertEqual((no_evidence.status_code,no_evidence.json()["error"]["code"]),(422,"analysis_evidence_unavailable"))
        self._save()
        key=str(uuid.uuid4());first=self._run("context_brief",key);replay=self._run("context_brief",key)
        self.assertEqual(first.json()["data"],replay.json()["data"])
        run_id=first.json()["data"]["run_id"]
        draft=self.project["current_draft"]
        changed=self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}",headers=idem(),json={"base_revision":draft["revision"],"body":"改写后的正文。"})
        self.assertEqual(changed.status_code,200,changed.text)
        stale=self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertEqual((stale["is_stale"],stale["lineage_status"]),(True,"bound_state_changed"))
        outsider=TestClient(self.app)
        outsider.post("/api/auth/register",headers=idem(),json={"account_name":"analysis-outsider","display_name":"Other","password":"safe-password-v130","recovery_email":"analysis-outsider@example.test"})
        self.assertEqual(outsider.get(f"/api/projects/{self.project_id}/analyses/{run_id}").status_code,404)

    def test_prompt_router_preserves_explicit_task_and_budget(self):
        self._save()
        self._run("context_brief")
        prompt,budget=request_prompt_and_budget(self.provider.requests[-1])
        self.assertIn('"task":"Create a compact pre-writing chapter context brief.',prompt)
        self.assertIn("Keep the four layers separate",prompt)
        self.assertNotIn("external_search",prompt)
        self.assertGreater(budget,0)

    def test_schema_migration_and_latest_analysis_do_not_replace_latest_continuity(self):
        self._save()
        draft=self.project["current_draft"]
        continuity=self.client.post(f"/api/projects/{self.project_id}/checks",headers=idem(),json={"draft_id":draft["id"],"draft_revision":draft["revision"]})
        self.assertEqual(continuity.status_code,202,continuity.text)
        brief=self._run("context_brief")
        project=self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        self.assertEqual(project["latest_run"]["run_id"],continuity.json()["data"]["run_id"])
        latest=self.client.get(f"/api/projects/{self.project_id}/analyses?analysis_type=context_brief").json()["data"]
        self.assertEqual(latest["run"]["run_id"],brief.json()["data"]["run_id"])
        self.app.state.database.initialize()
        with self.app.state.database.connection() as c:
            columns={row["name"] for row in c.execute("PRAGMA table_info(v2_runs)")}
            tables={row["name"] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("draft_revision",columns)
            self.assertTrue({"v2_analysis_inputs","v2_analysis_results"}<=tables)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=133").fetchone()[0],1)


if __name__=="__main__":unittest.main()
