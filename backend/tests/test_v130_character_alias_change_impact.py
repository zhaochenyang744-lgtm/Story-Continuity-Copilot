import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderInvalidJson, ProviderResult
from app.stage13 import Stage13Settings


def idem(value=None):
    return {"Idempotency-Key":value or str(uuid.uuid4()),"Origin":"http://testserver","X-CSRF-Token":"test-csrf-token"}


class ImpactProvider:
    label="change-impact-test-provider"
    def __init__(self):self.requests=[];self.mode="valid"
    @property
    def available(self):return True
    def evaluate(self,request):
        self.requests.append(request)
        if request.get("task")!="change_impact":return ProviderResult({"issues":[]},1,1,latency_ms=1)
        if self.mode=="invalid_json":raise ProviderInvalidJson()
        character=request["layers"]["identity"]["characters"][0]
        alias=request["layers"]["identity"]["aliases"][0]
        if self.mode=="zero_evidence":return ProviderResult({"summary":"Provider 自称没有影响，但未提供任何证据。","items":[]},8,4,latency_ms=2)
        evidence=[] if self.mode=="invalid_evidence" else [{"source_type":"character_alias","source_id":alias["id"]}]
        return ProviderResult({"summary":"该修改会影响角色识别与相关章节核对。","items":[{"area":"character","target_id":character["id"],"impact":"需要复核该角色在现有资料中的身份指向。","evidence":evidence}]},8,4,latency_ms=2)


class V130AliasImpactTests(unittest.TestCase):
    def setUp(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-alias-impact-"))
        self.provider=ImpactProvider()
        self.app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/"protected"),provider=self.provider,executor=lambda fn,*args:fn(*args),settings=Stage13Settings.for_test())
        self.client=TestClient(self.app)
        registered=self.client.post("/api/auth/register",headers=idem(),json={"account_name":"alias-owner","display_name":"Author","password":"safe-password-v130","recovery_email":"alias-owner@example.test"})
        self.assertEqual(registered.status_code,201,registered.text)
        self.project_id=registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        self.project=self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        self.character_id=self.client.get(f"/api/projects/{self.project_id}/characters").json()["data"]["characters"][0]["id"]

    def _create_alias(self,value="小岚",base=0,key=None):
        return self.client.post(f"/api/projects/{self.project_id}/characters/{self.character_id}/aliases",headers=idem(key),json={"base_version":base,"alias":value})

    def _impact(self,proposal="将小岚的公开身份改为港务调查员",key=None):
        draft=self.project["current_draft"]
        return self.client.post(f"/api/projects/{self.project_id}/analyses",headers=idem(key),json={"analysis_type":"change_impact","draft_id":draft["id"],"draft_revision":draft["revision"],"proposal":{"target_type":"character","target_id":self.character_id,"proposed_change":proposal}})

    def test_alias_crud_cas_normalization_idempotency_and_isolation(self):
        before={}
        with self.app.state.database.connection() as c:
            for table in ("v2_author_context_versions","v2_memory_records","v2_chapters","v2_source_change_sets"):before[table]=c.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?",(self.project_id,)).fetchone()[0]
        key=str(uuid.uuid4());created=self._create_alias("  小岚  ",0,key)
        self.assertEqual(created.status_code,201,created.text)
        self.assertEqual(created.json()["data"]["aliases"][0]["alias"],"小岚")
        replay=self._create_alias("  小岚  ",0,key)
        self.assertEqual(replay.json()["data"],created.json()["data"])
        duplicate=self._create_alias("小岚",1)
        self.assertEqual((duplicate.status_code,duplicate.json()["error"]["code"]),(409,"character_alias_duplicate"))
        conflict=self._create_alias("阿岚",0)
        self.assertEqual((conflict.status_code,conflict.json()["error"]["code"]),(409,"character_alias_version_conflict"))
        alias_id=created.json()["data"]["changed_alias_id"]
        edited=self.client.patch(f"/api/projects/{self.project_id}/characters/{self.character_id}/aliases/{alias_id}",headers=idem(),json={"base_version":1,"alias":"档案员岚"})
        self.assertEqual((edited.status_code,edited.json()["data"]["version"]),(200,2))
        archived=self.client.post(f"/api/projects/{self.project_id}/characters/{self.character_id}/aliases/{alias_id}/archive",headers=idem(),json={"base_version":2})
        self.assertEqual((archived.status_code,archived.json()["data"]["aliases"][0]["status"]),(200,"archived"))
        visible=self.client.get(f"/api/projects/{self.project_id}/characters/{self.character_id}/aliases").json()["data"]
        self.assertEqual(visible["aliases"],[])
        outsider=TestClient(self.app);outsider.post("/api/auth/register",headers=idem(),json={"account_name":"alias-outsider","display_name":"Other","password":"safe-password-v130","recovery_email":"alias-outsider@example.test"})
        self.assertEqual(outsider.get(f"/api/projects/{self.project_id}/characters/{self.character_id}/aliases").status_code,404)
        with self.app.state.database.connection() as c:
            for table,count in before.items():self.assertEqual(c.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?",(self.project_id,)).fetchone()[0],count)

    def test_alias_active_limit_is_twenty(self):
        for index in range(20):
            response=self._create_alias(f"别名{index+1}",index)
            self.assertEqual(response.status_code,201,response.text)
        limited=self._create_alias("第二十一个",20)
        self.assertEqual((limited.status_code,limited.json()["error"]["code"]),(409,"character_alias_limit_reached"))

    def test_change_impact_bindings_traceability_list_stale_and_no_auto_write(self):
        alias=self._create_alias().json()["data"]
        with self.app.state.database.connection() as c:
            before={table:c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("v2_draft_revisions","v2_memory_records","v2_author_context_versions","v2_character_aliases")}
        response=self._impact();self.assertEqual(response.status_code,202,response.text)
        run_id=response.json()["data"]["run_id"]
        viewed=self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertEqual((viewed["status"],viewed["analysis_type"],viewed["is_stale"]),("completed","change_impact",False))
        evidence=viewed["analysis"]["items"][0]["evidence"][0]
        self.assertEqual(evidence["source_type"],"character_alias")
        self.assertEqual(evidence["source_path"],f"/projects/{self.project_id}/characters?character={self.character_id}#alias-{evidence['source_id']}")
        self.assertEqual(viewed["proposal"],viewed["analysis"]["proposal"])
        self.assertEqual((viewed["draft_revision"],viewed["source_revision"],viewed["source_memory_version"],viewed["author_context_version"],viewed["alias_version"]),(self.project["current_draft"]["revision"],self.project["source_revision"],self.project["current_memory_version"],self.project["author_context_version"],1))
        request=self.provider.requests[-1]
        self.assertEqual(request["bindings"]["alias_version"],1)
        self.assertEqual(request["proposal"]["proposed_change"],"将小岚的公开身份改为港务调查员")
        self.assertTrue(request["layers"]["identity"]["aliases"])
        listed=self.client.get(f"/api/projects/{self.project_id}/analyses?analysis_type=change_impact").json()["data"]
        self.assertEqual((listed["run"]["run_id"],listed["runs"][0]["run_id"]),(run_id,run_id))
        with self.app.state.database.connection() as c:
            for table,count in before.items():self.assertEqual(c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],count)
        alias_id=alias["changed_alias_id"]
        self.client.patch(f"/api/projects/{self.project_id}/characters/{self.character_id}/aliases/{alias_id}",headers=idem(),json={"base_version":1,"alias":"新小岚"})
        stale=self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertTrue(stale["is_stale"])

    def test_change_impact_invalid_json_fails_closed(self):
        self._create_alias();self.provider.mode="invalid_json"
        run_id=self._impact().json()["data"]["run_id"]
        viewed=self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertEqual((viewed["status"],viewed["error_code"]),("failed","invalid_json"))
        with self.app.state.database.connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_analysis_results WHERE run_id=?",(run_id,)).fetchone()[0],0)

    def test_change_impact_invalid_evidence_fails_closed(self):
        self._create_alias();self.provider.mode="invalid_evidence"
        run_id=self._impact().json()["data"]["run_id"]
        viewed=self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertEqual((viewed["status"],viewed["error_code"]),("failed","evidence_unresolvable"))
        with self.app.state.database.connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_analysis_results WHERE run_id=?",(run_id,)).fetchone()[0],0)

    def test_change_impact_zero_evidence_discards_provider_conclusion(self):
        self._create_alias();self.provider.mode="zero_evidence"
        run_id=self._impact().json()["data"]["run_id"]
        viewed=self.client.get(f"/api/projects/{self.project_id}/analyses/{run_id}").json()["data"]
        self.assertEqual(viewed["status"],"completed")
        self.assertEqual(viewed["analysis"],{"summary":"当前证据不足以支持影响结论。","evidence_status":"insufficient","items":[],"proposal":viewed["proposal"]})
        self.assertNotIn("Provider 自称",viewed["analysis"]["summary"])

    def test_change_impact_cancel_and_retry_use_analysis_lifecycle(self):
        queued=[]
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-v130-alias-cancel-"))
        app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/"protected"),provider=ImpactProvider(),executor=lambda fn,*args:queued.append((fn,args)),settings=Stage13Settings.for_test())
        client=TestClient(app);registered=client.post("/api/auth/register",headers=idem(),json={"account_name":"cancel-owner","display_name":"Author","password":"safe-password-v130","recovery_email":"cancel-owner@example.test"}).json()["data"]
        project_id=registered["onboarding"]["tutorial"]["project_id"];project=client.get(f"/api/projects/{project_id}").json()["data"];character_id=client.get(f"/api/projects/{project_id}/characters").json()["data"]["characters"][0]["id"]
        client.post(f"/api/projects/{project_id}/characters/{character_id}/aliases",headers=idem(),json={"base_version":0,"alias":"小岚"})
        draft=project["current_draft"]
        created=client.post(f"/api/projects/{project_id}/analyses",headers=idem(),json={"analysis_type":"change_impact","draft_id":draft["id"],"draft_revision":draft["revision"],"proposal":{"target_type":"character","target_id":character_id,"proposed_change":"修改身份"}}).json()["data"]
        cancelled=client.post(f"/api/projects/{project_id}/analyses/{created['run_id']}/cancel",headers=idem(),json={"client_request_id":str(uuid.uuid4())})
        self.assertEqual(cancelled.status_code,200,cancelled.text)
        retried=client.post(f"/api/projects/{project_id}/analyses/{created['run_id']}/retry",headers=idem(),json={"client_request_id":str(uuid.uuid4())})
        self.assertEqual((retried.status_code,retried.json()["data"]["run"]["run_type"]),(202,"change_impact"))

    def test_migration_is_repeatable(self):
        self.app.state.database.initialize()
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=134").fetchone()[0],1)
            self.assertIn("alias_version",{row["name"] for row in c.execute("PRAGMA table_info(v2_projects)")})


if __name__=="__main__":unittest.main()
