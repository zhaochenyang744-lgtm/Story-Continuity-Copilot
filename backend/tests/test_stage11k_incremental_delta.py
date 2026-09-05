import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderInvalidJson, ProviderResult, ProviderTimeout


def idem(value=None): return {"Idempotency-Key": value or str(uuid.uuid4())}


class DeltaProvider:
    label="stage11k-test-provider"; model_label="stage11k-test-model"
    fail_mode=None; duplicate=False
    @property
    def available(self): return True
    def evaluate(self, request):
        task=request.get("task")
        if task=="memory_delta" and self.fail_mode=="timeout": raise ProviderTimeout()
        if task=="memory_delta" and self.fail_mode=="invalid_json": raise ProviderInvalidJson()
        self.last_requests=getattr(self,"last_requests",[])+[request]
        if task=="memory_initialization":
            source=request["sources"][0]
            return ProviderResult({"candidates":[
                {"memory_type":"dynamic_state","subject":"林默","predicate":"status","value":"在雾港","chapter_id":source["chapter_id"],"source_span_id":source["id"]},
                {"memory_type":"open_thread","subject":"北堤门","predicate":"status","value":"待确认","chapter_id":source["chapter_id"],"source_span_id":source["id"]},
            ]})
        if task=="memory_delta":
            source=request["sources"][0]
            affected=next(item for item in request["memory"] if item["subject"]=="林默" and item["predicate"]=="status")
            if self.fail_mode=="schema": return ProviderResult({"candidates":[{"bad":"shape"}]})
            if self.fail_mode=="evidence": return ProviderResult({"candidates":[{"change_kind":"changed_fact","affected_memory_id":affected["id"],"memory_type":"dynamic_state","subject":"林默","predicate":"status","value":"已离开雾港","invalidation_reason":None,"chapter_id":"not-current","source_span_id":"not-current"}]})
            candidates=[
                {"change_kind":"changed_fact","affected_memory_id":affected["id"],"memory_type":"dynamic_state","subject":"林默","predicate":"status","value":"已离开雾港","invalidation_reason":None,"chapter_id":source["chapter_id"],"source_span_id":source["id"]},
                {"change_kind":"new_fact","affected_memory_id":None,"memory_type":"open_thread","subject":"北堤门","predicate":"status","value":"是否开启仍待确认","invalidation_reason":None,"chapter_id":source["chapter_id"],"source_span_id":source["id"]},
            ]
            if self.duplicate:
                second=request["sources"][1]
                candidates.insert(1,{"change_kind":"changed_fact","affected_memory_id":affected["id"],"memory_type":"dynamic_state","subject":"林默","predicate":"status","value":"已离开雾港","invalidation_reason":None,"chapter_id":second["chapter_id"],"source_span_id":second["id"]})
            return ProviderResult({"candidates":candidates},input_tokens=12,output_tokens=8,latency_ms=3)
        return ProviderResult({"issues":[]},input_tokens=8,output_tokens=4,latency_ms=2)


class Stage11KTests(unittest.TestCase):
    def setUp(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-11k-")); self.provider=DeltaProvider()
        self.app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/"protected"),provider=self.provider,executor=lambda fn,*args:fn(*args)); self.client=TestClient(self.app)
        self.client.post("/api/auth/register",json={"account_name":"delta-author","display_name":"Delta","password":"safe-password-123"},headers=idem())
        preview=self.client.post("/api/imports/preview",files={"file":("base.md","# 第一章\n林默在雾港。".encode(),"text/markdown")},headers=idem()).json()["data"]
        self.project=self.client.post(f"/api/imports/{preview['import_id']}/commit",json={"confirm":True,"title":"Delta","chapter_preview_ids":[x["preview_id"] for x in preview["detected"]["chapters"]]},headers=idem()).json()["data"]["project"]["id"]
        initialization=self.client.post(f"/api/projects/{self.project}/memory/initializations",json={"source_revision":1},headers=idem()).json()["data"]["initialization"]
        core=next(x for x in initialization["candidates"] if x["review_priority"]=="core")
        self.client.post(f"/api/projects/{self.project}/memory/initializations/{initialization['id']}/candidates/{core['id']}/decision",json={"decision":"accepted"},headers=idem())
        self.client.post(f"/api/projects/{self.project}/memory/initializations/{initialization['id']}/commit",json={"confirm":True},headers=idem())
        change=self.client.post(f"/api/projects/{self.project}/source-change-sets/preview",json={"mode":"append","input_method":"paste","base_source_revision":1,"content":"# 第二章\n林默已离开雾港。\n# 第三章\n林默已离开雾港。"},headers=idem()).json()["data"]["source_change_set"]
        self.client.post(f"/api/projects/{self.project}/source-change-sets/{change['id']}/commit",json={"confirm":True,"content_sha256":change["content_sha256"]},headers=idem())

    def start(self,key=None,payload=None):
        response=self.client.post(f"/api/projects/{self.project}/incremental-reviews",json=payload or {"source_revision":2},headers=idem(key))
        return response,self.client.get(f"/api/projects/{self.project}/memory/delta").json()["data"]

    def counts(self):
        tables=("v2_issues","v2_memory_delta_candidates","v2_memory_delta_decisions","v2_memory_versions","v2_source_coverage_audits")
        with self.app.state.database.connection() as c:
            return {table:c.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?",(self.project,)).fetchone()[0] for table in tables}

    def decide(self,delta,candidate,decision,**extra):
        return self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/candidates/{candidate['id']}/decision",json={"decision":decision,**extra},headers=idem())

    def test_incremental_runs_are_current_and_carry_full_lineage_and_provenance(self):
        response,delta=self.start(); self.assertEqual(response.status_code,202); self.assertEqual((delta["status"],delta["coverage"]["status"]),("in_review","update_pending"))
        continuity=self.client.get(f"/api/projects/{self.project}/checks/{delta['continuity_run_id']}?include=issues,evidence,metrics").json()["data"]
        memory_run=self.client.get(f"/api/projects/{self.project}/checks/{delta['memory_delta_run_id']}?include=metrics").json()["data"]
        author_context=self.client.get(f"/api/projects/{self.project}/author-intent?version=0").json()["data"]
        self.assertEqual((continuity["run_type"],memory_run["run_type"]),("continuity","memory_delta"))
        for run in (continuity,memory_run):
            self.assertEqual((run["source_revision"],run["lineage_status"],run["is_stale"],run["superseded"]),(2,"incremental_source_revision",False,False))
            self.assertTrue(run["source_change_set_id"]); self.assertEqual(len(run["source_span_ids"]),2)
            self.assertEqual(run["metrics"]["provenance"]["source_span_ids"],run["source_span_ids"])
            self.assertEqual(run["metrics"]["provenance"]["source_memory_version"],1)
            self.assertTrue(run["metrics"]["provenance"]["prompt_version"]); self.assertIsNotNone(run["metrics"]["latency_ms"])
            self.assertEqual((run["author_context_version"],run["author_context_snapshot_digest"],run["author_context_resolvable"]),(0,author_context["snapshot_digest"],True))
        self.assertEqual(continuity["metrics"]["retrieval"][0]["method_version"],"bounded-lexical-v4-longform")
        self.assertTrue(all(len(trace["returned_span_ids"])<=3 and len(trace["returned_span_ids"])==len(set(trace["returned_span_ids"])) for trace in continuity["metrics"]["retrieval"]))
        continuity_request=next(request for request in self.provider.last_requests if request.get("task") is None)
        expected=[[span["id"] for span in claim["allowed_evidence"]] for claim in continuity_request["claims"]]
        self.assertEqual([trace["returned_span_ids"] for trace in continuity["metrics"]["retrieval"]],expected)

    def test_duplicate_affected_fact_fails_closed_without_candidate_drift(self):
        self.provider.duplicate=True; before=self.counts(); _,delta=self.start()
        self.assertEqual((delta["status"],delta["error_code"],delta["candidates"]),("failed","duplicate_candidate",[]))
        self.assertEqual(self.counts(),before); self.app.state.database.initialize()
        after=self.client.get(f"/api/projects/{self.project}/memory/delta").json()["data"]
        self.assertEqual((after["status"],after["candidates"]),("failed",[]))

    def test_edited_core_with_current_evidence_creates_v2_and_readable_audit(self):
        _,delta=self.start(); core=next(x for x in delta["candidates"] if x["review_priority"]=="core")
        edited={"memory_type":core["memory_type"],"subject":core["subject"],"predicate":core["predicate"],"value":"编辑后离开雾港"}
        self.assertEqual(self.decide(delta,core,"edited",after=edited,evidence_span_id=core["source"]["span_id"]).status_code,200)
        committed=self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit",json={"confirm":True},headers=idem()).json()["data"]
        audit=committed["coverage_audit"]; self.assertEqual((committed["memory_version"],audit["status"]),(2,"covered_with_memory_change")); self.assertTrue(audit["actor_user_id"])
        self.assertEqual(audit["details"]["decisions"][0]["after"]["value"],"编辑后离开雾港")
        read=self.client.get(f"/api/projects/{self.project}/source-coverage-audits/{audit['id']}")
        self.assertEqual(read.status_code,200); self.assertEqual(read.json()["data"]["audit"]["details"]["candidate_ids"],audit["details"]["candidate_ids"])
        memory=self.client.get(f"/api/projects/{self.project}/memory").json()["data"]["records"]; self.assertIn("编辑后离开雾港",[row["value"] for row in memory])

    def test_invalid_or_cross_revision_edit_evidence_is_422_and_has_no_writes(self):
        _,delta=self.start(); core=next(x for x in delta["candidates"] if x["review_priority"]=="core"); before=self.counts()
        bad=self.decide(delta,core,"edited",after={"memory_type":core["memory_type"],"subject":core["subject"],"predicate":core["predicate"],"value":"变化"},evidence_span_id="span-from-r1")
        self.assertEqual(bad.status_code,422); self.assertEqual(self.counts(),before)

    def test_all_rejected_writes_auditable_coverage_without_memory_growth(self):
        _,delta=self.start(); core=next(x for x in delta["candidates"] if x["review_priority"]=="core"); self.decide(delta,core,"rejected")
        result=self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit",json={"confirm":True},headers=idem()).json()["data"]; audit=result["coverage_audit"]
        self.assertEqual((result["status"],result["memory_version"],audit["status"]),("covered_without_memory_change",1,"covered_without_memory_change"))
        self.assertEqual(audit["details"]["decisions"][0]["decision"],"rejected"); self.assertTrue(audit["details"]["decisions"][0]["evidence_span_id"])

    def test_provider_failures_leave_terminal_runs_and_no_partial_result_rows(self):
        for mode,code,status in (("timeout","provider_timeout","timed_out"),("invalid_json","invalid_json","failed"),("schema","candidate_fields_invalid","failed"),("evidence","evidence_unresolvable","failed")):
            with self.subTest(mode=mode):
                self.setUp(); self.provider.fail_mode=mode; before=self.counts(); _,failed=self.start()
                self.assertEqual((failed["status"],failed["error_code"]),("failed",code)); self.assertEqual(self.counts(),before)
                run=self.client.get(f"/api/projects/{self.project}/checks/{failed['memory_delta_run_id']}").json()["data"]
                self.assertEqual((run["status"],run["error_code"]),(status,code))

    def test_idempotency_retry_and_pending_canon_invariant(self):
        key=str(uuid.uuid4()); first,delta=self.start(key); replay,_=self.start(key); conflict,_=self.start(key,{"source_revision":999})
        self.assertEqual((first.status_code,replay.status_code,conflict.status_code),(202,202,409)); self.assertEqual(conflict.json()["error"]["code"],"idempotency_conflict")
        core=next(x for x in delta["candidates"] if x["review_priority"]=="core"); self.decide(delta,core,"accepted")
        result=self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit",json={"confirm":True},headers=idem()).json()["data"]
        self.assertEqual(result["delta"]["coverage"]["counts"]["pending_canon_count"],0)
        with self.app.state.database.connection() as c: self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND value LIKE '%待确认%'",(self.project,)).fetchone()[0],0)
        request=next(x for x in self.provider.last_requests if x.get("task")=="memory_delta"); self.assertFalse(any("待确认" in row["value"] for row in request["memory"]))

    def test_cross_account_and_project_cannot_read_or_mutate_incremental_resources(self):
        _,delta=self.start(); other=TestClient(self.app)
        other.post("/api/auth/register",json={"account_name":"other-delta","display_name":"Other","password":"safe-password-123"},headers=idem())
        core=next(x for x in delta["candidates"] if x["review_priority"]=="core"); self.decide(delta,core,"rejected")
        audit=self.client.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit",json={"confirm":True},headers=idem()).json()["data"]["coverage_audit"]; before=self.counts()
        cases=[("get",f"/api/projects/{self.project}/memory/delta",None),("post",f"/api/projects/{self.project}/incremental-reviews",{"source_revision":2}),("post",f"/api/projects/{self.project}/memory/deltas/{delta['id']}/candidates/{core['id']}/decision",{"decision":"accepted"}),("post",f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit",{"confirm":True}),("get",f"/api/projects/{self.project}/source-coverage-audits/{audit['id']}",None)]
        for method,url,payload in cases:
            response=getattr(other,method)(url,json=payload,headers=idem()) if payload else getattr(other,method)(url); self.assertEqual(response.status_code,404)
        self.assertEqual(self.counts(),before)

    def test_failed_batch_new_key_creates_new_runs_without_partial_rows(self):
        self.provider.fail_mode="timeout"; _,failed=self.start(); self.assertEqual(failed["status"],"failed")
        self.provider.fail_mode=None; _,retry=self.start(); self.assertEqual(retry["status"],"in_review")
        self.assertNotEqual((failed["continuity_run_id"],failed["memory_delta_run_id"]),(retry["continuity_run_id"],retry["memory_delta_run_id"]))


if __name__ == "__main__": unittest.main()
