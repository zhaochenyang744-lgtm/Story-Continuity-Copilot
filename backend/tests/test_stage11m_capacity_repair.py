"""Offline capacity and API-contract tests for the Stage 11M V2 repair."""
from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult


def idem(value: str | None = None) -> dict[str,str]:
    return {"Idempotency-Key":value or str(uuid.uuid4())}


class ThreeCandidateProvider:
    label="capacity-test"
    model_label="capacity-test-model"
    available=True

    def evaluate(self,request):
        source=request["sources"][0]
        return ProviderResult({"candidates":[
            {"memory_type":"dynamic_state","subject":f"人物{i}","predicate":"status","value":f"状态{i}","chapter_id":source["chapter_id"],"source_span_id":source["id"]}
            for i in range(3)
        ]})


class Stage11MCapacityRepairTests(unittest.TestCase):
    def setUp(self):
        self.root=pathlib.Path(tempfile.mkdtemp(prefix="scc-11m-capacity-"))
        self.app=create_app(AppPaths.from_project_root(self.root,protected_poc_root=self.root/"protected"),provider=ThreeCandidateProvider(),executor=lambda fn,*args:fn(*args))
        self.client=TestClient(self.app)
        registered=self.client.post("/api/auth/register",json={"account_name":f"capacity-{uuid.uuid4().hex[:8]}","display_name":"Capacity","password":"safe-password-123"},headers=idem())
        self.assertEqual(registered.status_code,201)

    def imported(self,text: str,title: str="Capacity") -> str:
        preview=self.client.post("/api/imports/preview",files={"file":("capacity.md",text.encode("utf-8"),"text/markdown")},headers=idem())
        self.assertEqual(preview.status_code,201)
        data=preview.json()["data"]
        committed=self.client.post(f"/api/imports/{data['import_id']}/commit",json={"confirm":True,"title":title,"chapter_preview_ids":[row["preview_id"] for row in data["detected"]["chapters"]]},headers=idem())
        self.assertEqual(committed.status_code,201)
        return committed.json()["data"]["project"]["id"]

    def test_compact_writes_replay_exactly_while_full_get_keeps_evidence(self):
        project=self.imported("# 第一章\n受控来源正文。")
        start_key=str(uuid.uuid4())
        started=self.client.post(f"/api/projects/{project}/memory/initializations?view=compact",json={"source_revision":1},headers=idem(start_key))
        self.assertEqual(started.status_code,201)
        self.assertNotIn("candidates",started.json()["data"]["initialization"])
        full=self.client.get(f"/api/projects/{project}/memory/initialization").json()["data"]
        self.assertEqual(len(full["candidates"]),3)
        self.assertTrue(all(row["source"]["text"] and row["source"]["span_id"] for row in full["candidates"]))
        candidate=full["candidates"][0]
        decision_key=str(uuid.uuid4())
        endpoint=f"/api/projects/{project}/memory/initializations/{full['id']}/candidates/{candidate['id']}/decision?view=compact"
        first=self.client.post(endpoint,json={"decision":"accepted"},headers=idem(decision_key))
        replay=self.client.post(endpoint,json={"decision":"accepted"},headers=idem(decision_key))
        conflict=self.client.post(endpoint,json={"decision":"rejected"},headers=idem(decision_key))
        self.assertEqual((first.status_code,replay.status_code,conflict.status_code),(200,200,409))
        self.assertEqual(first.json()["data"],replay.json()["data"])
        self.assertEqual(set(first.json()["data"]),{"candidate_id","decision_status"})
        default_full=self.client.post(f"/api/projects/{project}/memory/initializations/{full['id']}/candidates/{candidate['id']}/decision",json={"decision":"accepted"},headers=idem())
        self.assertIn("initialization",default_full.json()["data"])
        with self.app.state.database.connection() as connection:
            stored=connection.execute("SELECT response_json FROM v2_idempotency WHERE operation LIKE 'memory_candidate_decision:%' ORDER BY created_at LIMIT 1").fetchone()[0]
        self.assertLessEqual(len(stored.encode("utf-8")),2048)
        self.assertNotIn("initialization",stored)

    def test_300k_and_181_decisions_remain_under_capacity_gate(self):
        project=self.imported("# 第一章\n"+("受控长篇来源。"*42856),"Scaled Capacity")
        session=self.client.get("/api/auth/session").json()["data"]
        user_id=session["user"]["id"]
        database=self.app.state.database
        input_data=database.memory_initialization_input(user_id,project,1)
        source=input_data["sources"][0]
        candidates=[{"memory_type":"dynamic_state","subject":f"人物{i:03d}","predicate":"status","value":f"受控状态{i:03d}","chapter_id":source["chapter_id"],"source_span_id":source["id"]} for i in range(181)]
        created,status=database.complete_memory_initialization(user_id,project,input_data,{"candidates":candidates},{"provider_label":"offline","model_label":"offline","prompt_version":"offline","schema_version":"memory-candidate-v1"},str(uuid.uuid4()))
        self.assertEqual(status,201)
        initialization_id=created["initialization"]["id"]
        with database.connection() as connection:
            rows=connection.execute("SELECT id FROM v2_memory_candidates WHERE initialization_id=? ORDER BY candidate_ordinal",(initialization_id,)).fetchall()
        for row in rows:
            response=self.client.post(f"/api/projects/{project}/memory/initializations/{initialization_id}/candidates/{row['id']}/decision?view=compact",json={"decision":"accepted"},headers=idem())
            self.assertEqual(response.status_code,200)
        committed=self.client.post(f"/api/projects/{project}/memory/initializations/{initialization_id}/commit?view=compact",json={"confirm":True},headers=idem())
        self.assertEqual(committed.status_code,200)
        with database.connection() as connection:
            decision_count,decision_max=connection.execute("SELECT COUNT(*),MAX(LENGTH(CAST(response_json AS BLOB))) FROM v2_idempotency WHERE operation LIKE 'memory_candidate_decision:%'").fetchone()
            start_max=connection.execute("SELECT MAX(LENGTH(CAST(response_json AS BLOB))) FROM v2_idempotency WHERE operation LIKE 'memory_initialization:%'").fetchone()[0]
            commit_max=connection.execute("SELECT MAX(LENGTH(CAST(response_json AS BLOB))) FROM v2_idempotency WHERE operation LIKE 'memory_initialization_commit:%'").fetchone()[0]
        self.assertEqual(decision_count,181)
        self.assertLessEqual(decision_max,2048)
        self.assertLessEqual(start_max,16384)
        self.assertLessEqual(commit_max,16384)
        self.assertLessEqual(database.paths.database_path.stat().st_size,50*1024*1024)


if __name__ == "__main__":
    unittest.main()
