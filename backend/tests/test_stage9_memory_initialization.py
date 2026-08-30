import json
import pathlib
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult


def idem(value=None):
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class DeterministicInitializationProvider:
    label = "stage9-deterministic-provider"
    model_label = "stage9-test-model"

    def __init__(self):
        self.calls = 0
        self.requests = []

    @property
    def available(self):
        return True

    def evaluate(self, request):
        self.calls += 1
        self.requests.append(request)
        if request.get("task") == "memory_initialization":
            sources = request["sources"]
            facts = [
                ("static_canon", "雾港守则", "rule", "钟声响起后所有船只停泊", sources[0]),
                ("dynamic_state", "银钥匙", "holder", "林默保管", sources[1]),
                ("character_knowledge", "林默", "knowledge", "知道北堤门只在清晨开启", sources[2]),
            ]
            return ProviderResult({"candidates": [{"memory_type":kind, "subject":subject, "predicate":predicate, "value":value, "chapter_id":source["chapter_id"], "source_span_id":source["id"]} for kind, subject, predicate, value, source in facts]})
        claim = request["claims"][0]
        memory = next(item for item in request["memory"] if item["subject"] == "雾港守则")
        evidence = next(item for item in claim["allowed_evidence"] if item["id"] == memory["source_span_id"])
        return ProviderResult({"issues": [{"claim_span_id":claim["id"], "status":"conflict", "category":"object_state", "severity":"medium", "explanation":"草稿中的钥匙状态需要与已确认来源一起由作者核对。", "evidence":[{"chapter_id":evidence["chapter_id"],"span_id":evidence["id"],"relation":"contradicts","sufficiency":"sufficient","related_memory_ids":[memory["id"]]}], "proposed_memory_change":None}]})


class InvalidInitializationProvider(DeterministicInitializationProvider):
    def evaluate(self, request):
        self.calls += 1
        if request.get("task") == "memory_initialization":
            return ProviderResult({"wrong": []})
        return super().evaluate(request)


class Stage9MemoryInitializationTests(unittest.TestCase):
    text = """# 雾港初章\n钟声响起后，所有船只必须停泊在雾港。\n# 北堤钥匙\n林默一直保管银钥匙，钥匙没有离开过他。\n# 清晨门扉\n林默知道北堤门只在清晨开启。\n"""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="scc-stage9-"))
        self.provider = DeterministicInitializationProvider()
        self.app = create_app(AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected"), provider=self.provider, executor=lambda fn, *args: fn(*args))
        self.client = TestClient(self.app)
        registered = self.client.post("/api/auth/register", json={"account_name":"stage9author","display_name":"Stage 9","password":"safe-password-99"}, headers=idem())
        self.assertEqual(registered.status_code, 201)

    def imported_project(self, title="雾港手稿"):
        preview = self.client.post("/api/imports/preview", files={"file":("mist-harbor.md", self.text.encode("utf-8"), "text/markdown")}, headers=idem())
        self.assertEqual(preview.status_code, 201)
        data = preview.json()["data"]
        committed = self.client.post(f"/api/imports/{data['import_id']}/commit", json={"confirm":True,"title":title,"summary":"原创确定性测试作品","genre":"悬疑","chapter_preview_ids":[item["preview_id"] for item in data["detected"]["chapters"]]}, headers=idem())
        self.assertEqual(committed.status_code, 201)
        return committed.json()["data"]["project"]["id"]

    def start(self, project_id, key=None, revision=1):
        return self.client.post(f"/api/projects/{project_id}/memory/initializations", json={"source_revision":revision}, headers=idem(key))

    def test_import_initialize_decide_commit_v1_then_first_check(self):
        project_id = self.imported_project()
        project = self.client.get(f"/api/projects/{project_id}").json()["data"]
        before_runs = self.app.state.database.counts()["v2_runs"]
        unavailable_context = self.client.post(f"/api/projects/{project_id}/checks", json={"draft_id":project["current_draft"]["id"],"draft_revision":1}, headers=idem())
        self.assertEqual((unavailable_context.status_code, unavailable_context.json()["error"]["code"]), (422,"insufficient_project_context"))
        self.assertEqual((self.provider.calls, self.app.state.database.counts()["v2_runs"]), (0,before_runs))
        start_key = str(uuid.uuid4())
        started = self.start(project_id,start_key)
        replay = self.start(project_id,start_key)
        self.assertEqual((started.status_code,replay.status_code), (201,200))
        initialization = started.json()["data"]["initialization"]
        metrics=started.json()["data"]["initialization_metrics"]
        self.assertEqual((metrics["total_batches"],metrics["schema_repair_attempts"],metrics["cost_available"]),(1,0,False))
        provenance=started.json()["data"]["initialization_provenance"]
        self.assertEqual((provenance["prompt_version"],provenance["chunking_method_version"]),("memory-initialization-v8-pro-two-repair","source-chunk-v4-5800"))
        self.assertEqual((initialization["status"],initialization["source_revision"],len(initialization["candidates"])), ("draft",1,3))
        self.assertEqual(self.provider.calls,1)
        self.assertTrue(all(item["decision_status"]=="pending" and item["source"]["text"] for item in initialization["candidates"]))
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/memory").json()["data"]["records"], [])
        candidates_by_subject = {candidate["subject"]: candidate for candidate in initialization["candidates"]}
        harbor, key_candidate, dawn = candidates_by_subject["雾港守则"], candidates_by_subject["银钥匙"], candidates_by_subject["林默"]
        decisions = [
            ({"decision":"accepted"}, harbor),
            ({"decision":"rejected"}, key_candidate),
            ({"decision":"edited","after":{"memory_type":"character_knowledge","subject":"林默","predicate":"knowledge","value":"确认北堤门只在清晨开启"},"evidence_span_id":dawn["source"]["span_id"]}, dawn),
        ]
        for payload, candidate in decisions:
            response = self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{candidate['id']}/decision", json=payload, headers=idem())
            self.assertEqual(response.status_code,200)
        duplicate = self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{harbor['id']}/decision", json={"decision":"accepted"}, headers=idem())
        self.assertEqual(duplicate.status_code,200)
        commit_key = str(uuid.uuid4())
        committed = self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/commit", json={"confirm":True}, headers=idem(commit_key))
        replay_commit = self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/commit", json={"confirm":True}, headers=idem(commit_key))
        self.assertEqual((committed.status_code,replay_commit.status_code), (200,200))
        self.assertEqual(committed.json()["data"],replay_commit.json()["data"])
        result=committed.json()["data"]
        self.assertEqual((result["memory_version"],result["initialization"]["status"]),(1,"committed"))
        memory=self.client.get(f"/api/projects/{project_id}/memory?version=1").json()["data"]["records"]
        self.assertEqual(len(memory),2)
        self.assertTrue(all(item["review_status"]=="author_confirmed" and item["source"] for item in memory))
        self.assertFalse(any(item["subject"]=="银钥匙" for item in memory))
        with self.app.state.database.connection() as connection:
            audit=connection.execute("SELECT evidence_span_id FROM v2_memory_candidate_decisions WHERE candidate_id=?",(dawn["id"],)).fetchone()
        self.assertEqual(audit["evidence_span_id"],dawn["source"]["span_id"])
        draft=self.client.get(f"/api/projects/{project_id}/drafts/{project['current_draft']['id']}").json()["data"]
        saved=self.client.patch(f"/api/projects/{project_id}/drafts/{draft['id']}",json={"base_revision":1,"title":draft["title"],"body":"钟声响起后，所有船只继续离开雾港。"},headers=idem())
        self.assertEqual(saved.status_code,200)
        run=self.client.post(f"/api/projects/{project_id}/checks",json={"draft_id":draft["id"],"draft_revision":2},headers=idem())
        self.assertEqual(run.status_code,202)
        viewed=self.client.get(f"/api/projects/{project_id}/checks/{run.json()['data']['run_id']}?include=issues,evidence").json()["data"]
        self.assertEqual((viewed["status"],len(viewed["issues"]),len(viewed["issues"][0]["evidence"])),("completed",1,1))

    def test_edited_decision_requires_explicit_current_evidence_without_writes(self):
        project_id=self.imported_project("Evidence 确认")
        initialization=self.start(project_id).json()["data"]["initialization"]
        candidates={candidate["subject"]:candidate for candidate in initialization["candidates"]}
        dawn,harbor=candidates["林默"],candidates["雾港守则"]
        after={"memory_type":"character_knowledge","subject":"林默","predicate":"knowledge","value":"确认北堤门只在清晨开启"}
        endpoint=f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{dawn['id']}/decision"
        other_project=self.imported_project("跨项目 Evidence")
        with self.app.state.database.connection() as connection:
            foreign_span=connection.execute("SELECT id FROM v2_source_spans WHERE project_id=? LIMIT 1",(other_project,)).fetchone()[0]
        for payload in ({"decision":"edited","after":after},{"decision":"edited","after":after,"evidence_span_id":harbor["source"]["span_id"]},{"decision":"edited","after":after,"evidence_span_id":foreign_span},{"decision":"edited","after":after,"evidence_span_id":"span-forged"}):
            response=self.client.post(endpoint,json=payload,headers=idem())
            self.assertEqual((response.status_code,response.json()["error"]["code"]),(422,"evidence_unresolvable"))
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT decision_status FROM v2_memory_candidates WHERE id=?",(dawn["id"],)).fetchone()[0],"pending")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_memory_candidate_decisions WHERE initialization_id=?",(initialization["id"],)).fetchone()[0],0)
            connection.execute("UPDATE v2_source_spans SET body=? WHERE id=?",("陈旧来源",dawn["source"]["span_id"]))
        stale=self.client.post(endpoint,json={"decision":"edited","after":after,"evidence_span_id":dawn["source"]["span_id"]},headers=idem())
        self.assertEqual((stale.status_code,stale.json()["error"]["code"]),(422,"evidence_unresolvable"))
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_memory_candidate_decisions WHERE initialization_id=?",(initialization["id"],)).fetchone()[0],0)

    def test_final_initialization_commit_rolls_back_midway_sqlite_failure(self):
        project_id=self.imported_project("提交回滚")
        initialization=self.start(project_id).json()["data"]["initialization"]
        candidates={candidate["subject"]:candidate for candidate in initialization["candidates"]}
        decisions=[
            ({"decision":"accepted"},candidates["雾港守则"]),
            ({"decision":"rejected"},candidates["银钥匙"]),
            ({"decision":"edited","after":{"memory_type":"character_knowledge","subject":"林默","predicate":"knowledge","value":"确认北堤门只在清晨开启"},"evidence_span_id":candidates["林默"]["source"]["span_id"]},candidates["林默"]),
        ]
        for payload,candidate in decisions:
            response=self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{candidate['id']}/decision",json=payload,headers=idem())
            self.assertEqual(response.status_code,200)
        database=self.app.state.database
        original_new_id=__import__("app.v2_database",fromlist=["new_id"]).new_id
        inserted_memory_records=0
        def fail_after_first_memory_record(kind):
            nonlocal inserted_memory_records
            if kind=="mem":
                inserted_memory_records+=1
                if inserted_memory_records==2: raise sqlite3.OperationalError("stage9 injected final-commit failure")
            return original_new_id(kind)
        with patch("app.v2_database.new_id",side_effect=fail_after_first_memory_record):
            failed=self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/commit",json={"confirm":True},headers=idem())
        self.assertEqual((failed.status_code,failed.json()["error"]["code"]),(503,"memory_initialization_commit_failed"))
        with database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=1",(project_id,)).fetchone()[0],0)
            initialization_state=connection.execute("SELECT status,completed_at FROM v2_memory_initializations WHERE id=?",(initialization["id"],)).fetchone()
            self.assertEqual((initialization_state["status"],initialization_state["completed_at"]),("draft",None))
            statuses=[row[0] for row in connection.execute("SELECT decision_status FROM v2_memory_candidates WHERE initialization_id=? ORDER BY decision_status",(initialization["id"],)).fetchall()]
            self.assertEqual(statuses,["accepted","edited","rejected"])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_memory_candidate_decisions WHERE initialization_id=?",(initialization["id"],)).fetchone()[0],3)

    def test_server_priorities_partial_commit_and_confirmed_only_check_input(self):
        project_id=self.imported_project("11I 部分确认")
        project=self.client.get(f"/api/projects/{project_id}").json()["data"]
        initialization=self.start(project_id).json()["data"]["initialization"]
        candidates={candidate["subject"]:candidate for candidate in initialization["candidates"]}
        harbor,key_candidate,dawn=candidates["雾港守则"],candidates["银钥匙"],candidates["林默"]
        self.assertEqual((harbor["candidate_origin"],harbor["review_priority"],dawn["review_priority"],key_candidate["review_priority"]),("initialization","core","core","supporting"))
        self.assertEqual((initialization["coverage"]["status"],initialization["coverage"]["counts"]["core_pending"],initialization["coverage"]["counts"]["supporting_pending"]),("in_review",2,1))
        forged=self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{harbor['id']}/decision",json={"decision":"accepted","review_priority":"supporting"},headers=idem())
        self.assertEqual((forged.status_code,forged.json()["error"]["code"]),(400,"invalid_request"))
        for payload,candidate in (({"decision":"accepted"},harbor),({"decision":"rejected"},dawn)):
            self.assertEqual(self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{candidate['id']}/decision",json=payload,headers=idem()).status_code,200)
        committed=self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/commit",json={"confirm":True},headers=idem())
        self.assertEqual(committed.status_code,200)
        coverage=committed.json()["data"]["coverage"]
        self.assertEqual((coverage["status"],coverage["counts"]["core_pending"],coverage["counts"]["supporting_pending"],coverage["counts"]["confirmed_core"],coverage["counts"]["pending_canon_count"]),("ready_partial",0,1,1,0))
        memory=self.client.get(f"/api/projects/{project_id}/memory").json()["data"]["records"]
        self.assertEqual([record["subject"] for record in memory],["雾港守则"])
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT decision_status FROM v2_memory_candidates WHERE id=?",(key_candidate["id"],)).fetchone()[0],"pending")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND subject='银钥匙'",(project_id,)).fetchone()[0],0)
        draft=self.client.get(f"/api/projects/{project_id}/drafts/{project['current_draft']['id']}").json()["data"]
        saved=self.client.patch(f"/api/projects/{project_id}/drafts/{draft['id']}",json={"base_revision":draft["revision"],"title":draft["title"],"body":"钟声响起后，所有船只继续离开雾港。"},headers=idem())
        self.assertEqual(saved.status_code,200)
        run=self.client.post(f"/api/projects/{project_id}/checks",json={"draft_id":project["current_draft"]["id"],"draft_revision":2},headers=idem())
        self.assertEqual(run.status_code,202)
        provider_memory=self.provider.requests[-1]["memory"]
        self.assertEqual([item["subject"] for item in provider_memory],["雾港守则"])

    def test_stage11i_migration_backfills_legacy_once_and_preserves_restart_values(self):
        project_id=self.imported_project("11I 迁移一次性")
        initialization=self.start(project_id).json()["data"]["initialization"]
        database=self.app.state.database
        with database.connection() as connection:
            # Simulate a pre-v11 persisted candidate set: no v11 marker, no
            # trusted origin/priority/ordinal values. Rowid is the legacy
            # insertion-order source for the first and only backfill.
            connection.execute("DELETE FROM schema_migrations WHERE version=11")
            connection.execute("UPDATE v2_memory_candidates SET candidate_origin='delta',review_priority='supporting',candidate_ordinal=0 WHERE initialization_id=?",(initialization["id"],))
        database.initialize()
        with database.connection() as connection:
            migrated=connection.execute("SELECT id,candidate_origin,review_priority,candidate_ordinal FROM v2_memory_candidates WHERE initialization_id=? ORDER BY candidate_ordinal",(initialization["id"],)).fetchall()
            marker=connection.execute("SELECT version FROM schema_migrations WHERE version=11").fetchone()
        self.assertEqual(marker["version"],11)
        self.assertEqual([(row["candidate_origin"],row["review_priority"],row["candidate_ordinal"]) for row in migrated],[("initialization","core",1),("initialization","supporting",2),("initialization","core",3)])
        preserved_id=migrated[0]["id"]
        with database.connection() as connection:
            connection.execute("UPDATE v2_memory_candidates SET candidate_origin='delta',review_priority='supporting',candidate_ordinal=73 WHERE id=?",(preserved_id,))
        database.initialize()
        with database.connection() as connection:
            preserved=connection.execute("SELECT candidate_origin,review_priority,candidate_ordinal FROM v2_memory_candidates WHERE id=?",(preserved_id,)).fetchone()
        self.assertEqual(tuple(preserved),("delta","supporting",73))

    def test_all_candidates_final_with_supporting_rejected_is_ready_current(self):
        project_id=self.imported_project("11I 全部处理")
        initialization=self.start(project_id).json()["data"]["initialization"]
        candidates={candidate["subject"]:candidate for candidate in initialization["candidates"]}
        decisions=(("雾港守则","accepted"),("林默","rejected"),("银钥匙","rejected"))
        for subject,decision in decisions:
            self.assertEqual(self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{candidates[subject]['id']}/decision",json={"decision":decision},headers=idem()).status_code,200)
        committed=self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/commit",json={"confirm":True},headers=idem())
        self.assertEqual((committed.status_code,committed.json()["data"]["coverage"]["status"],committed.json()["data"]["coverage"]["counts"]["supporting_pending"]),(200,"ready_current",0))

    def test_all_rejected_stays_in_review_and_reset_preserves_import_sources(self):
        project_id=self.imported_project("全拒绝")
        initial_chapters=self.client.get(f"/api/projects/{project_id}/chapters?include=excerpt").json()["data"]
        initialization=self.start(project_id).json()["data"]["initialization"]
        for candidate in initialization["candidates"]:
            self.assertEqual(self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{candidate['id']}/decision",json={"decision":"rejected"},headers=idem()).status_code,200)
        before_check_calls=self.provider.calls
        committed=self.client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/commit",json={"confirm":True},headers=idem())
        self.assertEqual((committed.status_code,committed.json()["error"]["code"]),(422,"insufficient_project_context"))
        coverage=self.client.get(f"/api/projects/{project_id}/memory/coverage").json()["data"]
        self.assertEqual((coverage["status"],coverage["counts"]["confirmed_core"],coverage["counts"]["pending_canon_count"]),("in_review",0,0))
        project=self.client.get(f"/api/projects/{project_id}").json()["data"]
        self.assertEqual((project["memory_initialization_status"],project["current_memory_version"]),("in_review",1))
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/memory").json()["data"]["records"],[])
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/checks",json={"draft_id":project["current_draft"]["id"],"draft_revision":1},headers=idem()).status_code,422)
        self.assertEqual(self.provider.calls,before_check_calls)
        other=self.imported_project("另一个项目")
        before_other=self.client.get(f"/api/projects/{other}").json()["data"]
        reset=self.client.post(f"/api/projects/{project_id}/reset",json={"confirm":True,"reason":"fresh_start"},headers=idem())
        self.assertEqual(reset.status_code,200)
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/chapters?include=excerpt").json()["data"],initial_chapters)
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/memory/initialization").json()["data"]["status"],"required")
        self.assertEqual(self.client.get(f"/api/projects/{other}").json()["data"],before_other)

    def test_fail_closed_for_stale_cross_account_and_invalid_provider(self):
        project_id=self.imported_project()
        before=self.app.state.database.counts().copy()
        stale=self.start(project_id,revision=2)
        self.assertEqual((stale.status_code,stale.json()["error"]["code"]),(409,"source_revision_not_current"))
        self.assertEqual(self.app.state.database.counts(),before)
        outsider=TestClient(self.app)
        outsider.post("/api/auth/register",json={"account_name":"stage9other","display_name":"Other","password":"safe-password-98"},headers=idem())
        self.assertEqual(outsider.get(f"/api/projects/{project_id}/memory/initialization").status_code,404)
        bad_root=pathlib.Path(tempfile.mkdtemp(prefix="scc-stage9-invalid-"))
        invalid=create_app(AppPaths.from_project_root(bad_root,protected_poc_root=bad_root / "protected"),provider=InvalidInitializationProvider(),executor=lambda fn,*args:fn(*args))
        client=TestClient(invalid)
        client.post("/api/auth/register",json={"account_name":"badstage9","display_name":"Bad","password":"safe-password-97"},headers=idem())
        preview=client.post("/api/imports/preview",files={"file":("bad.md",self.text.encode(),"text/markdown")},headers=idem()).json()["data"]
        imported=client.post(f"/api/imports/{preview['import_id']}/commit",json={"confirm":True,"title":"坏返回","summary":"x","chapter_preview_ids":[x["preview_id"] for x in preview["detected"]["chapters"]]},headers=idem()).json()["data"]["project"]["id"]
        failure=client.post(f"/api/projects/{imported}/memory/initializations",json={"source_revision":1},headers=idem())
        self.assertEqual((failure.status_code,failure.json()["error"]["code"]),(503,"top_level_shape_invalid"))
        error=failure.json()["error"]
        self.assertTrue(error["retryable"])
        self.assertEqual(error["details"],{"failure_phase":"post_response_validation","failed_batch_ordinal":1,"total_batches":1,"schema_repair_attempts":2,"validated_batches":0,"staged_candidate_count":0,"normalization_count":0,"repair_events":[{"batch_ordinal":1,"attempt":1,"reason_code":"top_level_shape_invalid","result":"failed","batch_attempt":1,"final_reason_code":"top_level_shape_invalid"},{"batch_ordinal":1,"attempt":2,"reason_code":"top_level_shape_invalid","result":"failed","batch_attempt":2,"final_reason_code":"top_level_shape_invalid"}],"normalization_kinds":{},"cost_available":False})
        serialized=json.dumps(error,ensure_ascii=False)
        self.assertNotIn("wrong",serialized)
        self.assertNotIn(self.text,serialized)
        with invalid.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_memory_initializations WHERE project_id=?",(imported,)).fetchone()[0],0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_memory_candidates WHERE project_id=?",(imported,)).fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
