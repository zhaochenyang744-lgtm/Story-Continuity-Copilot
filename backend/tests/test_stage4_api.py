from __future__ import annotations

import pathlib
import sqlite3
import socket
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
import uvicorn

from app.config import AppPaths
from app.engine import ContinuityEngine
from app.main import create_app
from app.provider import DeepSeekProvider, ProviderFailure, ProviderInvalidJson, ProviderResult, ProviderTimeout
from app.v2_database import V2Database


def key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def grounded_issue(request, index: int = 0, operation: str = 'add'):
    claim=request['claims'][index]; evidence=claim['allowed_evidence'][0]; memory=next(item for item in request['memory'] if item['source_span_id']==evidence['id'])
    proposal={'operation':operation,'memory_type':'open_thread','subject':f'作者确认项{index}','predicate':'status','value':'待后续章节推进','affected_memory_id':None}
    if operation=='replace': proposal.update({'memory_type':memory['memory_type'],'subject':memory['subject'],'predicate':memory['predicate'],'value':'作者确认的新状态','affected_memory_id':memory['id']})
    return {'claim_span_id':claim['id'],'status':'conflict','category':'object_state','severity':'high','explanation':'可验证连续性差异。','evidence':[{'chapter_id':evidence['chapter_id'],'span_id':evidence['id'],'relation':'contradicts','sufficiency':'sufficient','related_memory_ids':[memory['id']]}],'proposed_memory_change':proposal}


class DeepSeekProviderRegressionTests(unittest.TestCase):
    def test_json_fence_is_unwrapped_before_schema_validation(self):
        class Response:
            def raise_for_status(self): return None
            def json(self): return {"choices":[{"message":{"content":"```json\n{\"issues\":[]}\n```"}}],"usage":{"prompt_tokens":7,"completion_tokens":3}}
        class Client:
            body=None
            def __enter__(self): return self
            def __exit__(self,*_): return False
            def post(self,*_,**kwargs): self.body=kwargs["json"]; return Response()
        client=Client()
        settings={"CONTINUITY_PROVIDER":"deepseek","CONTINUITY_MODEL":"unit-model","CONTINUITY_BASE_URL":"https://unit.invalid","CONTINUITY_API_KEY":"unit-test"}
        with patch.dict("os.environ",settings,clear=False):
            result=DeepSeekProvider(client_factory=lambda:client).evaluate({"draft":{},"claims":[],"memory":[],"output_schema":{}})
        self.assertEqual((result.payload,result.input_tokens,result.output_tokens),({"issues":[]},7,3))
        self.assertEqual(client.body["thinking"],{"type":"disabled"})
        prompt=client.body["messages"][0]["content"]
        self.assertIn("Decide every current claim before emitting output",prompt)
        self.assertIn("exactly one top-level key, issues",prompt)
        self.assertIn("never emit a no_conflict issue",prompt)
        self.assertIn("Emit insufficient_evidence when the retrieved material neither supports nor contradicts the target claim",prompt)
        self.assertIn("Category boundaries: attribute is an intrinsic or durable property",prompt)
        self.assertIn("minimal necessary set of one or more direct Evidence",prompt)
        self.assertNotIn("If no grounded conflict can be returned under these rules",prompt)


class ContinuityDecisionContractTests(unittest.TestCase):
    def setUp(self):
        self.data={'draft':{'id':'draft-1','revision':1,'body':'当前草稿。'},'claims':[{'id':'claim-1','text':'目标主张。','allowed_evidence':[{'id':'span-1','chapter_id':'chapter-1','body':'直接事实。'},{'id':'span-2','chapter_id':'chapter-2','body':'背景事实。'}]}],'memory':[{'id':'memory-1'}]}

    def execute(self,payload):
        class Provider:
            label='fake-contract'; model_label='fake-contract-v2'; available=True
            def evaluate(_,request): return ProviderResult(payload,input_tokens=2,output_tokens=1,latency_ms=1)
        return ContinuityEngine(Provider()).execute(self.data)

    def issue(self,status,category='attribute',evidence=None):
        return {'claim_span_id':'claim-1','status':status,'category':category,'severity':'medium','explanation':'可审阅的测试结论。','evidence':evidence if evidence is not None else [],'proposed_memory_change':None}

    def evidence(self,span_id='span-1',relation='contradicts'):
        chapter='chapter-1' if span_id=='span-1' else 'chapter-2'
        return {'chapter_id':chapter,'span_id':span_id,'relation':relation,'sufficiency':'sufficient','related_memory_ids':[]}

    def test_conflict_insufficient_and_no_conflict_contracts(self):
        conflict=self.execute({'issues':[self.issue('conflict','attribute',[self.evidence()])]})
        two_fact_conflict=self.execute({'issues':[self.issue('conflict','timeline',[self.evidence('span-1'),self.evidence('span-2')])]})
        insufficient=self.execute({'issues':[self.issue('insufficient_evidence','object_state',[])]})
        no_conflict=self.execute({'issues':[]})
        self.assertEqual((conflict['status'],conflict['issues'][0]['status'],len(conflict['issues'][0]['evidence'])),('completed','conflict',1))
        self.assertEqual((two_fact_conflict['status'],two_fact_conflict['issues'][0]['category'],len(two_fact_conflict['issues'][0]['evidence'])),('completed','timeline',2))
        self.assertIsNone(conflict['issues'][0]['proposed_memory_change'])
        self.assertEqual((insufficient['status'],insufficient['issues'][0]['status'],insufficient['issues'][0]['evidence']),('completed','insufficient_evidence',[]))
        self.assertIsNone(insufficient['issues'][0]['proposed_memory_change'])
        self.assertEqual((no_conflict['status'],no_conflict['issues']),('completed',[]))
        malformed=self.execute({'issues':{'claim_span_id':'claim-1'}})
        self.assertEqual((malformed['status'],malformed['error_code']),('failed','schema_invalid'))

    def test_category_values_are_preserved_and_boundaries_are_not_rewritten(self):
        for category in ('attribute','object_state','relationship','character_knowledge'):
            result=self.execute({'issues':[self.issue('conflict',category,[self.evidence()])]})
            self.assertEqual((result['status'],result['issues'][0]['category']),('completed',category))

    def test_invalid_evidence_and_nonempty_no_conflict_fail_closed(self):
        self.assertEqual(self.execute({'issues':[self.issue('conflict','attribute',[self.evidence(relation='context')])]} )['error_code'],'conflict_evidence_not_direct')
        self.assertEqual(self.execute({'issues':[self.issue('conflict','attribute',[])]} )['error_code'],'conflict_without_evidence')
        self.assertEqual(self.execute({'issues':[self.issue('conflict','attribute',[{'chapter_id':'chapter-1','span_id':'missing','relation':'contradicts','sufficiency':'sufficient','related_memory_ids':[]}])]} )['error_code'],'evidence_unresolvable')
        self.assertEqual(self.execute({'issues':[self.issue('insufficient_evidence','attribute',[self.evidence()])]} )['error_code'],'insufficient_evidence_upgraded')
        self.assertEqual(self.execute({'issues':[self.issue('no_conflict','attribute',[self.evidence()])]} )['error_code'],'no_conflict_issue_forbidden')
        self.assertEqual(self.execute({'issues':[self.issue('no_conflict','attribute',[])]})['error_code'],'no_conflict_issue_forbidden')


class Stage4ContractTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-stage4-"))
        self.client = TestClient(create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected")))
        result = self.client.post("/api/auth/register", json={"account_name":"authora","display_name":"Author A","password":"safe-password-42"}, headers=key())
        self.assertEqual(result.status_code, 201)
        self.seed = result.json()["data"]["seeded_projects"]
        self.grey = self.seed[0]["id"]

    def test_auth_and_all_read_contracts_are_account_scoped(self):
        self.assertEqual(self.client.get("/api/auth/session").status_code, 200)
        home = self.client.get("/api/home")
        self.assertEqual(home.status_code, 200)
        home_data = home.json()["data"]
        self.assertEqual(home_data["continue_work"]["project_title"], "灰港回声")
        self.assertEqual([item["title"] for item in home_data["recent_projects"]], ["灰港回声", "纸月档案", "零点花园"])
        projects = self.client.get("/api/projects").json()["data"]["projects"]
        self.assertEqual(len(projects), 3)
        project = self.client.get(f"/api/projects/{self.grey}").json()["data"]
        self.assertEqual(project["chapter_count"], 10)
        for suffix in ("outline", "characters", "world", "chapters?include=excerpt", "memory"):
            self.assertEqual(self.client.get(f"/api/projects/{self.grey}/{suffix}").status_code, 200)
        draft = project["current_draft"]
        self.assertEqual(self.client.get(f"/api/projects/{self.grey}/drafts/{draft['id']}").status_code, 200)
        other = TestClient(self.client.app)
        denied = other.get(f"/api/projects/{self.grey}")
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (401,"authentication_required"))

    def test_writes_require_uuid_idempotency_and_preserve_replay(self):
        missing = self.client.post("/api/projects", json={"title":"新作品"})
        self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (400,"missing_idempotency_key"))
        idem = str(uuid.uuid4()); payload={"title":"新作品","genre":"悬疑","summary":"独立创建"}
        first=self.client.post("/api/projects",json=payload,headers={"Idempotency-Key":idem})
        second=self.client.post("/api/projects",json=payload,headers={"Idempotency-Key":idem})
        self.assertEqual((first.status_code,second.status_code),(201,201))
        self.assertEqual(first.json()["data"],second.json()["data"])
        conflict=self.client.post("/api/projects",json={**payload,"title":"另一部"},headers={"Idempotency-Key":idem})
        self.assertEqual((conflict.status_code,conflict.json()["error"]["code"]),(409,"idempotency_conflict"))
        created=first.json()["data"]["project"]
        archived=self.client.patch(f"/api/projects/{created['id']}",json={"base_metadata_revision":1,"status":"archived","confirm_archive":True},headers=key())
        self.assertEqual(archived.status_code,200)
        blocked=self.client.post(f"/api/projects/{created['id']}/reset",json={"confirm":True,"reason":"fresh_start"},headers=key())
        self.assertEqual((blocked.status_code,blocked.json()["error"]["code"]),(409,"project_archived"))
        restored=self.client.patch(f"/api/projects/{created['id']}",json={"base_metadata_revision":2,"status":"active"},headers=key())
        self.assertEqual(restored.status_code,200)

    def test_draft_cas_provider_fail_closed_and_reset_is_project_local(self):
        project=self.client.get(f"/api/projects/{self.grey}").json()["data"]; draft=project["current_draft"]
        saved=self.client.patch(f"/api/projects/{self.grey}/drafts/{draft['id']}",json={"base_revision":1,"body":"温岚仍握着罗盘。"},headers=key())
        self.assertEqual(saved.status_code,200)
        stale=self.client.patch(f"/api/projects/{self.grey}/drafts/{draft['id']}",json={"base_revision":1,"body":"过期保存。"},headers=key())
        self.assertEqual((stale.status_code,stale.json()["error"]["code"]),(409,"revision_conflict"))
        unavailable=self.client.post(f"/api/projects/{self.grey}/checks",json={"draft_id":draft['id'],"draft_revision":2},headers=key())
        self.assertEqual((unavailable.status_code,unavailable.json()["error"]["code"]),(503,"provider_unavailable"))
        other=self.seed[1]["id"]; before=self.client.get(f"/api/projects/{other}").json()["data"]
        reset=self.client.post(f"/api/projects/{self.grey}/reset",json={"confirm":True,"reason":"demo_recovery"},headers=key())
        self.assertEqual((reset.status_code,reset.json()["data"]["current_memory_version"]),(200,4))
        after=self.client.get(f"/api/projects/{other}").json()["data"]
        self.assertEqual(before["updated_at"],after["updated_at"])

    def test_import_preview_commit_and_cross_user_fail_closed(self):
        preview=self.client.post("/api/imports/preview",files={"file":("novel.md","# 第一章 晨雾\n港口安静。\n# 第二章 夜潮\n钟声响起。".encode("utf-8"),"text/markdown")},headers=key())
        self.assertEqual(preview.status_code,201)
        data=preview.json()["data"]
        commit=self.client.post(f"/api/imports/{data['import_id']}/commit",json={"confirm":True,"title":"导入作品","chapter_preview_ids":[item['preview_id'] for item in data['detected']['chapters']]},headers=key())
        self.assertEqual((commit.status_code,commit.json()["data"]["project"]["data_origin"]),(201,"user_import"))
        duplicate=self.client.post(f"/api/imports/{data['import_id']}/commit",json={"confirm":True,"title":"导入作品","chapter_preview_ids":[item['preview_id'] for item in data['detected']['chapters']]},headers=key())
        self.assertEqual((duplicate.status_code,duplicate.json()["error"]["code"]),(409,"already_committed"))
        outsider=TestClient(self.client.app)
        registration=outsider.post("/api/auth/register",json={"account_name":"authorb","display_name":"Author B","password":"safe-password-43"},headers=key())
        self.assertEqual(registration.status_code,201)
        denied=outsider.get(f"/api/projects/{self.grey}")
        self.assertEqual((denied.status_code,denied.json()["error"]["code"]),(404,"resource_not_found"))

    def test_check_decision_changeset_commit_real_project_scope(self):
        class ScriptedProvider:
            label="test-only"
            available=True
            def evaluate(self, request):
                claim=next(item for item in request["claims"] if item["allowed_evidence"])
                evidence=claim["allowed_evidence"][0]
                return ProviderResult({"issues":[{"claim_span_id":claim["id"],"status":"conflict","category":"object_state","severity":"high","explanation":"测试中的可审阅冲突。","evidence":[{"chapter_id":evidence["chapter_id"],"span_id":evidence["id"],"relation":"contradicts","sufficiency":"sufficient","related_memory_ids":[]}],"proposed_memory_change":{"operation":"add","memory_type":"open_thread","subject":"测试线索","predicate":"status","value":"作者确认","affected_memory_id":None}}]})
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-stage4-flow-")); app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/"protected"),provider=ScriptedProvider(),executor=lambda fn,*args:fn(*args)); client=TestClient(app)
        registration=client.post("/api/auth/register",json={"account_name":"flowuser","display_name":"Flow","password":"safe-password-45"},headers=key())
        project_id=registration.json()["data"]["seeded_projects"][0]["id"]
        project=client.get(f"/api/projects/{project_id}").json()["data"]; draft=project["current_draft"]
        created=client.post(f"/api/projects/{project_id}/checks",json={"draft_id":draft["id"],"draft_revision":1},headers=key())
        self.assertEqual(created.status_code,202)
        run_id=created.json()["data"]["run_id"]
        reviewed=client.get(f"/api/projects/{project_id}/checks/{run_id}?include=issues,evidence,metrics")
        self.assertEqual((reviewed.status_code,reviewed.json()["data"]["status"]),(200,"completed"))
        issue=reviewed.json()["data"]["issues"][0]
        decided=client.post(f"/api/projects/{project_id}/issues/{issue['id']}/decision",json={"run_id":run_id,"source_revision":1,"decision":"keep_intentional"},headers=key())
        self.assertEqual(decided.status_code,200)
        change=client.post(f"/api/projects/{project_id}/memory/change-sets",json={"run_id":run_id,"source_run_revision":1,"resolved_revision":1},headers=key())
        self.assertEqual(change.status_code,201)
        change_data=change.json()["data"]["change_set"]; item=change_data["items"][0]["id"]
        committed=client.post(f"/api/projects/{project_id}/memory/change-sets/{change_data['id']}/commit",json={"confirm":True,"accepted_item_ids":[item],"rejected_item_ids":[]},headers=key())
        self.assertEqual((committed.status_code,committed.json()["data"]["memory_version"]["current"]),(200,5))

    def test_run_provenance_is_migrated_scoped_and_reset_with_the_run(self):
        class Provider:
            available=True; label='contract-provider'; model_label='contract-model-v1'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request)]},input_tokens=12,output_tokens=6,latency_ms=35)
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-provenance-'))
        app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=Provider(),executor=lambda fn,*args:fn(*args)); client=TestClient(app)
        registered=client.post('/api/auth/register',json={'account_name':'provenance','display_name':'Provenance','password':'safe-password-67'},headers=key()).json()['data']
        grey=registered['seeded_projects'][0]['id']; other=registered['seeded_projects'][1]['id']; draft=client.get(f'/api/projects/{grey}').json()['data']['current_draft']
        legacy,_,_=app.state.database.create_run(registered['user']['id'],grey,{'draft_id':draft['id'],'draft_revision':1},str(uuid.uuid4()),{'provider_label':'contract-provider','model_label':'contract-model-v1','prompt_version':'continuity-review-v1','schema_version':'continuity-issue-v1','retrieval_method_version':'demo-retrieval-v2'})
        app.state.database.finish_run(grey,legacy['run_id'],{'status':'failed','error_code':'provider_error','retryable':True})
        legacy_view=app.state.database.run_view(registered['user']['id'],grey,legacy['run_id'],{'metrics'})
        self.assertEqual(legacy_view['metrics']['provenance']['prompt_version'],'continuity-review-v1')
        queued=client.post(f'/api/projects/{grey}/checks',json={'draft_id':draft['id'],'draft_revision':1},headers=key()).json()['data']
        reviewed=client.get(f"/api/projects/{grey}/checks/{queued['run_id']}?include=issues,evidence,metrics")
        self.assertEqual(reviewed.status_code,200)
        metrics=reviewed.json()['data']['metrics']; provenance=metrics['provenance']
        self.assertEqual(provenance,{'provider_label':'contract-provider','model_label':'contract-model-v1','prompt_version':'continuity-review-v4','schema_version':'continuity-issue-v3','retrieval_method_version':'demo-retrieval-v2','source_memory_version':4})
        self.assertTrue(metrics['retrieval'])
        self.assertEqual(client.get(f"/api/projects/{other}/checks/{queued['run_id']}?include=metrics").status_code,404)
        self.assertEqual(client.post(f'/api/projects/{grey}/reset',json={'confirm':True,'reason':'demo_recovery'},headers=key()).status_code,200)
        self.assertEqual(client.get(f"/api/projects/{grey}/checks/{queued['run_id']}?include=metrics").status_code,404)

    def test_old_v2_run_schema_migrates_idempotently_to_provenance_v6(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-provenance-migration-')); paths=AppPaths.from_project_root(root,protected_poc_root=root/'protected'); paths.prepare_runtime()
        with sqlite3.connect(paths.database_path) as connection:
            connection.execute('CREATE TABLE v2_runs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,draft_id TEXT NOT NULL,source_revision INTEGER NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,provider_label TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,latency_ms INTEGER,cost_cny REAL,error_code TEXT,retryable INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,completed_at TEXT)')
            connection.execute('CREATE TABLE v2_issues(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,run_id TEXT NOT NULL,claim_span_id TEXT NOT NULL,status TEXT NOT NULL,category TEXT NOT NULL,severity TEXT NOT NULL,evidence_status TEXT NOT NULL,explanation TEXT NOT NULL,proposed_change_json TEXT)')
        database=V2Database(paths); database.initialize(); database.initialize()
        with database.connection() as connection:
            run_columns={row['name'] for row in connection.execute('PRAGMA table_info(v2_runs)')}; issue_columns={row['name'] for row in connection.execute('PRAGMA table_info(v2_issues)')}
            self.assertTrue({'model_label','prompt_version','schema_version','retrieval_method_version','source_memory_version'} <= run_columns)
            self.assertIn('classification',issue_columns)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM schema_migrations WHERE version=6').fetchone()[0],1)

    def test_real_uvicorn_returns_queued_before_slow_provider_completes(self):
        class SlowProvider:
            label='slow-test-provider'; available=True
            def evaluate(_,request):
                time.sleep(2.5)
                claim=next(item for item in request['claims'] if item['allowed_evidence']); evidence=claim['allowed_evidence'][0]
                return ProviderResult({'issues':[{'claim_span_id':claim['id'],'status':'conflict','category':'object_state','severity':'medium','explanation':'慢测试可审阅结果。','evidence':[{'chapter_id':evidence['chapter_id'],'span_id':evidence['id'],'relation':'contradicts','sufficiency':'sufficient','related_memory_ids':[]}]}]},input_tokens=21,output_tokens=8,latency_ms=2500)
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-uvicorn-slow-')); app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=SlowProvider())
        probe=socket.socket(); probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]; probe.close(); server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False)); thread=threading.Thread(target=server.run,daemon=True); thread.start()
        base=f'http://127.0.0.1:{port}'
        try:
            for _ in range(50):
                try:
                    if httpx.get(base+'/health',timeout=.2).status_code==200: break
                except httpx.HTTPError: time.sleep(.05)
            else: self.fail('uvicorn did not become ready')
            with httpx.Client(base_url=base,timeout=5) as client:
                registration=client.post('/api/auth/register',json={'account_name':'slowuser','display_name':'Slow','password':'safe-password-47'},headers=key()); self.assertEqual(registration.status_code,201)
                project=registration.json()['data']['seeded_projects'][0]['id']; draft=client.get(f'/api/projects/{project}').json()['data']['current_draft']; started=time.monotonic(); queued=client.post(f'/api/projects/{project}/checks',json={'draft_id':draft['id'],'draft_revision':1},headers=key()); elapsed=time.monotonic()-started
                self.assertEqual((queued.status_code,queued.json()['data']['status']),(202,'queued')); self.assertLess(elapsed,1.0); run_id=queued.json()['data']['run_id']
                for _ in range(40):
                    state=client.get(f'/api/projects/{project}/checks/{run_id}').json()['data']
                    if state['status']=='completed': break
                    time.sleep(.1)
                self.assertEqual(state['status'],'completed')
                with app.state.database.connection() as connection: stages=[row['stage'] for row in connection.execute('SELECT stage FROM v2_run_stages WHERE run_id=? ORDER BY created_at',(run_id,)).fetchall()]
                self.assertEqual(stages,['queued','preparing_draft','retrieving_confirmed_facts','comparing_evidence','assembling_reviewable_results','completed'])
        finally:
            server.should_exit=True; thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_all_24_business_endpoints_have_a_repeatable_contract_path(self):
        class Provider:
            available=True; label='twenty-four-contract'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request)]})
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-24-contract-')); client=TestClient(create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=Provider(),executor=lambda fn,*args:fn(*args))); seen={}
        registration=client.post('/api/auth/register',json={'account_name':'twentyfour','display_name':'Twenty Four','password':'safe-password-48'},headers=key()); seen['register']=registration.status_code; project=registration.json()['data']['seeded_projects'][0]['id']
        seen['session']=client.get('/api/auth/session').status_code; seen['login']=client.post('/api/auth/login',json={'account_name':'twentyfour','password':'safe-password-48'}).status_code; seen['home']=client.get('/api/home').status_code; seen['projects']=client.get('/api/projects').status_code
        created=client.post('/api/projects',json={'title':'接口作品'},headers=key()); seen['create_project']=created.status_code; created_id=created.json()['data']['project']['id']; project_read=client.get(f'/api/projects/{created_id}'); seen['project']=project_read.status_code; self.assertEqual(project_read.json()['data']['metadata_revision'],1); self.assertEqual(client.get('/api/projects').json()['data']['projects'][-1]['metadata_revision'],1); seen['project_patch']=client.patch(f'/api/projects/{created_id}',json={'base_metadata_revision':1,'summary':'已更新'},headers=key()).status_code
        seen['outline']=client.get(f'/api/projects/{project}/outline?volume=1').status_code; seen['characters']=client.get(f'/api/projects/{project}/characters?role_type=ally').status_code; seen['world']=client.get(f'/api/projects/{project}/world?entry_type=location').status_code; seen['chapters']=client.get(f'/api/projects/{project}/chapters?include=excerpt').status_code; seen['memory']=client.get(f'/api/projects/{project}/memory?memory_type=static_canon').status_code
        draft=client.get(f'/api/projects/{project}').json()['data']['current_draft']; seen['draft_get']=client.get(f'/api/projects/{project}/drafts/{draft["id"]}').status_code; saved=client.patch(f'/api/projects/{project}/drafts/{draft["id"]}',json={'base_revision':1,'body':'温岚带着罗盘走向雾钟。'},headers=key()); seen['draft_patch']=saved.status_code
        created_run=client.post(f'/api/projects/{project}/checks',json={'draft_id':draft['id'],'draft_revision':2},headers=key()); seen['checks_post']=created_run.status_code; run=created_run.json()['data']['run_id']; checked=client.get(f'/api/projects/{project}/checks/{run}?include=issues,evidence,metrics'); seen['checks_get']=checked.status_code; issue=checked.json()['data']['issues'][0]
        decided=client.post(f'/api/projects/{project}/issues/{issue["id"]}/decision',json={'run_id':run,'source_revision':2,'decision':'keep_intentional'},headers=key()); seen['decision']=decided.status_code; changes=client.post(f'/api/projects/{project}/memory/change-sets',json={'run_id':run,'source_run_revision':2,'resolved_revision':2},headers=key()); seen['changeset']=changes.status_code; change=changes.json()['data']['change_set']; seen['commit']=client.post(f'/api/projects/{project}/memory/change-sets/{change["id"]}/commit',json={'confirm':True,'accepted_item_ids':[change['items'][0]['id']],'rejected_item_ids':[]},headers=key()).status_code
        seen['reset']=client.post(f'/api/projects/{project}/reset',json={'confirm':True,'reason':'demo_recovery'},headers=key()).status_code; preview=client.post('/api/imports/preview',files={'file':('chapter.md','# 第一章\n导入内容。'.encode(),'text/markdown')},headers=key()); seen['import_preview']=preview.status_code; import_id=preview.json()['data']['import_id']; previews=[item['preview_id'] for item in preview.json()['data']['detected']['chapters']]; seen['import_commit']=client.post(f'/api/imports/{import_id}/commit',json={'confirm':True,'title':'导入接口作品','chapter_preview_ids':previews},headers=key()).status_code; seen['logout']=client.post('/api/auth/logout').status_code
        self.assertEqual(seen,{'register':201,'session':200,'login':200,'home':200,'projects':200,'create_project':201,'project':200,'project_patch':200,'outline':200,'characters':200,'world':200,'chapters':200,'memory':200,'draft_get':200,'draft_patch':200,'checks_post':202,'checks_get':200,'decision':200,'changeset':201,'commit':200,'reset':200,'import_preview':201,'import_commit':201,'logout':204})

    def test_real_uvicorn_24_endpoint_smoke(self):
        class Provider:
            available=True; label='uvicorn-contract'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request)]})
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-uvicorn-24-')); app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=Provider())
        probe=socket.socket(); probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]; probe.close(); server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False)); thread=threading.Thread(target=server.run,daemon=True); thread.start(); base=f'http://127.0.0.1:{port}'
        try:
            for _ in range(50):
                try:
                    if httpx.get(base+'/health',timeout=.2).status_code==200: break
                except httpx.HTTPError: time.sleep(.05)
            else: self.fail('uvicorn did not become ready')
            with httpx.Client(base_url=base,timeout=5) as client:
                seen={}; registration=client.post('/api/auth/register',json={'account_name':'uvicorn24','display_name':'Uvicorn','password':'safe-password-49'},headers=key()); seen['register']=registration.status_code; project=registration.json()['data']['seeded_projects'][0]['id']
                seen['session']=client.get('/api/auth/session').status_code; seen['login']=client.post('/api/auth/login',json={'account_name':'uvicorn24','password':'safe-password-49'}).status_code; seen['home']=client.get('/api/home').status_code; seen['projects']=client.get('/api/projects').status_code
                created=client.post('/api/projects',json={'title':'服务烟测'},headers=key()); seen['create_project']=created.status_code; created_id=created.json()['data']['project']['id']; seen['project']=client.get(f'/api/projects/{created_id}').status_code; seen['project_patch']=client.patch(f'/api/projects/{created_id}',json={'base_metadata_revision':1,'summary':'烟测'},headers=key()).status_code
                seen['outline']=client.get(f'/api/projects/{project}/outline?volume=1').status_code; seen['characters']=client.get(f'/api/projects/{project}/characters?role_type=ally').status_code; seen['world']=client.get(f'/api/projects/{project}/world?entry_type=location').status_code; seen['chapters']=client.get(f'/api/projects/{project}/chapters?include=excerpt').status_code; seen['memory']=client.get(f'/api/projects/{project}/memory?memory_type=static_canon').status_code
                draft=client.get(f'/api/projects/{project}').json()['data']['current_draft']; seen['draft_get']=client.get(f'/api/projects/{project}/drafts/{draft["id"]}').status_code; seen['draft_patch']=client.patch(f'/api/projects/{project}/drafts/{draft["id"]}',json={'base_revision':1,'body':'温岚带着罗盘走向雾钟。'},headers=key()).status_code
                queued=client.post(f'/api/projects/{project}/checks',json={'draft_id':draft['id'],'draft_revision':2},headers=key()); seen['checks_post']=queued.status_code; run=queued.json()['data']['run_id']
                for _ in range(30):
                    checked=client.get(f'/api/projects/{project}/checks/{run}?include=issues,evidence,metrics')
                    if checked.json()['data']['status']=='completed': break
                    time.sleep(.05)
                seen['checks_get']=checked.status_code; issue=checked.json()['data']['issues'][0]; seen['decision']=client.post(f'/api/projects/{project}/issues/{issue["id"]}/decision',json={'run_id':run,'source_revision':2,'decision':'keep_intentional'},headers=key()).status_code; changes=client.post(f'/api/projects/{project}/memory/change-sets',json={'run_id':run,'source_run_revision':2,'resolved_revision':2},headers=key()); seen['changeset']=changes.status_code; change=changes.json()['data']['change_set']; seen['commit']=client.post(f'/api/projects/{project}/memory/change-sets/{change["id"]}/commit',json={'confirm':True,'accepted_item_ids':[change['items'][0]['id']],'rejected_item_ids':[]},headers=key()).status_code
                seen['reset']=client.post(f'/api/projects/{project}/reset',json={'confirm':True,'reason':'demo_recovery'},headers=key()).status_code; preview=client.post('/api/imports/preview',files={'file':('chapter.md','# 第一章\n服务导入。'.encode(),'text/markdown')},headers=key()); seen['import_preview']=preview.status_code; previews=[item['preview_id'] for item in preview.json()['data']['detected']['chapters']]; seen['import_commit']=client.post(f"/api/imports/{preview.json()['data']['import_id']}/commit",json={'confirm':True,'title':'服务导入','chapter_preview_ids':previews},headers=key()).status_code; seen['logout']=client.post('/api/auth/logout').status_code
            self.assertEqual(seen,{'register':201,'session':200,'login':200,'home':200,'projects':200,'create_project':201,'project':200,'project_patch':200,'outline':200,'characters':200,'world':200,'chapters':200,'memory':200,'draft_get':200,'draft_patch':200,'checks_post':202,'checks_get':200,'decision':200,'changeset':201,'commit':200,'reset':200,'import_preview':201,'import_commit':201,'logout':204})
        finally:
            server.should_exit=True; thread.join(timeout=5); self.assertFalse(thread.is_alive())


class ContinuityRegressionTests(unittest.TestCase):
    def flow(self, provider):
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-continuity-v2-')); app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=provider,executor=lambda fn,*args:fn(*args)); client=TestClient(app)
        registered=client.post('/api/auth/register',json={'account_name':'continuity','display_name':'Continuity','password':'safe-password-55'},headers=key()).json()['data']; project=registered['seeded_projects'][0]['id']; draft=client.get(f'/api/projects/{project}').json()['data']['current_draft']; run=client.post(f'/api/projects/{project}/checks',json={'draft_id':draft['id'],'draft_revision':1},headers=key()).json()['data']['run_id']; checked=client.get(f'/api/projects/{project}/checks/{run}?include=issues,evidence').json()['data']
        return app,client,project,draft,run,checked

    def test_controlled_edit_lineage_and_false_positive_no_memory_change(self):
        class Provider:
            available=True; label='lineage'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request)]})
        _,client,project,draft,run,checked=self.flow(Provider()); issue=checked['issues'][0]
        original=client.get(f'/api/projects/{project}/drafts/{draft["id"]}').json()['data']['body']
        edited=client.patch(f'/api/projects/{project}/drafts/{draft["id"]}',json={'base_revision':1,'body':original+' 受控编辑。','edit_context':{'source_run_id':run,'source_revision':1,'issue_id':issue['id']}},headers=key())
        self.assertEqual(edited.json()['data']['revision'],2)
        accepted=client.post(f'/api/projects/{project}/issues/{issue["id"]}/decision',json={'run_id':run,'source_revision':1,'decision':'accept_and_edit','resulting_revision':2},headers=key())
        self.assertEqual((accepted.status_code,accepted.json()['data']['lineage_status']),(200,'validated_direct_successor'))
        changes=client.post(f'/api/projects/{project}/memory/change-sets',json={'run_id':run,'source_run_revision':1,'resolved_revision':2},headers=key())
        self.assertEqual((changes.status_code,changes.json()['error']['code']),(422,'no_reviewable_changes'))
        # A separate current run marked false positive is equally prevented from
        # creating a canon change.
        _,other,other_project,_,other_run,other_checked=self.flow(Provider()); other_issue=other_checked['issues'][0]
        self.assertEqual(other.post(f'/api/projects/{other_project}/issues/{other_issue["id"]}/decision',json={'run_id':other_run,'source_revision':1,'decision':'false_positive'},headers=key()).status_code,200)
        rejected=other.post(f'/api/projects/{other_project}/memory/change-sets',json={'run_id':other_run,'source_run_revision':1,'resolved_revision':1},headers=key())
        self.assertEqual((rejected.status_code,rejected.json()['error']['code']),(422,'no_reviewable_changes'))

    def test_rejected_partial_and_accepted_commits_preserve_baseline(self):
        class One:
            available=True; label='one'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request)]})
        app,client,project,_,run,checked=self.flow(One()); issue=checked['issues'][0]
        client.post(f'/api/projects/{project}/issues/{issue["id"]}/decision',json={'run_id':run,'source_revision':1,'decision':'keep_intentional'},headers=key())
        changes=client.post(f'/api/projects/{project}/memory/change-sets',json={'run_id':run,'source_run_revision':1,'resolved_revision':1},headers=key()).json()['data']['change_set']; item=changes['items'][0]['id']
        all_rejected=client.post(f'/api/projects/{project}/memory/change-sets/{changes["id"]}/commit',json={'confirm':True,'accepted_item_ids':[],'rejected_item_ids':[item]},headers=key())
        self.assertEqual((all_rejected.json()['data']['status'],all_rejected.json()['data']['memory_version']['current']),('rejected',4))
        with app.state.database.connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_memory_versions WHERE project_id=? AND version=5',(project,)).fetchone()[0],0); self.assertEqual(connection.execute('SELECT review_status FROM v2_change_set_items WHERE id=?',(item,)).fetchone()[0],'rejected')
        class Two:
            available=True; label='two'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request,0,'add'),grounded_issue(request,1,'replace')]})
        app,client,project,_,run,checked=self.flow(Two())
        for issue in checked['issues']: self.assertEqual(client.post(f'/api/projects/{project}/issues/{issue["id"]}/decision',json={'run_id':run,'source_revision':1,'decision':'keep_intentional'},headers=key()).status_code,200)
        changes=client.post(f'/api/projects/{project}/memory/change-sets',json={'run_id':run,'source_run_revision':1,'resolved_revision':1},headers=key()).json()['data']['change_set']; accepted=next(item for item in changes['items'] if item['operation']=='add'); rejected=next(item for item in changes['items'] if item['operation']=='replace')
        result=client.post(f'/api/projects/{project}/memory/change-sets/{changes["id"]}/commit',json={'confirm':True,'accepted_item_ids':[accepted['id']],'rejected_item_ids':[rejected['id']]},headers=key())
        self.assertEqual(result.json()['data']['memory_version']['current'],5)
        with app.state.database.connection() as connection:
            baseline=connection.execute('SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=4',(project,)).fetchone()[0]; derived=connection.execute('SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=5',(project,)).fetchone()[0]; states=dict(connection.execute('SELECT id,review_status FROM v2_change_set_items WHERE change_set_id=?',(changes['id'],)))
            self.assertEqual(derived,baseline+1); self.assertEqual((states[accepted['id']],states[rejected['id']]),('accepted','rejected'))

    def test_provider_failures_and_schema_fail_closed_are_observable(self):
        failures=((ProviderTimeout(),'timed_out','provider_timeout'),(ProviderFailure(),'failed','provider_error'),(ProviderInvalidJson(),'failed','invalid_json'))
        for failure,status,code in failures:
            class Failing:
                available=True; label='failure'
                def evaluate(_,request,error=failure): raise error
            _,client,project,_,run,_=self.flow(Failing()); response=client.get(f'/api/projects/{project}/checks/{run}?include=metrics').json()['data']; self.assertEqual((response['status'],response['error_code'],response['retryable']),(status,code,True))
        class Invalid:
            available=True; label='invalid'
            def evaluate(_,request):
                issue=grounded_issue(request); issue['evidence']=[]
                return ProviderResult({'issues':[issue]})
        _,client,project,_,run,_=self.flow(Invalid()); response=client.get(f'/api/projects/{project}/checks/{run}').json()['data']; self.assertEqual((response['status'],response['error_code'],response['retryable']),('failed','conflict_without_evidence',True))
        class Empty:
            available=True; label='empty'
            def evaluate(_,request): return ProviderResult({'issues':[]})
        _,client,project,_,run,checked=self.flow(Empty()); self.assertEqual((checked['status'],checked['issues']),('completed',[]))
        class Grounded:
            available=True; label='grounded'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request)]})
        _,client,project,_,run,checked=self.flow(Grounded()); self.assertEqual((checked['status'],checked['issues'][0]['classification']),('completed','conflict'))
        class Insufficient:
            available=True; label='insufficient'
            def evaluate(_,request): return ProviderResult({'issues':[{'claim_span_id':request['claims'][0]['id'],'status':'insufficient_evidence','category':'attribute','severity':'low','explanation':'材料没有说明具体标识。','evidence':[]}]})
        _,client,project,_,run,checked=self.flow(Insufficient()); self.assertEqual((checked['status'],checked['issues'][0]['classification'],checked['issues'][0]['evidence']),('completed','insufficient_evidence',[]))
        class InsufficientWithChange:
            available=True; label='insufficient-with-change'
            def evaluate(_,request): return ProviderResult({'issues':[{'claim_span_id':request['claims'][0]['id'],'status':'insufficient_evidence','category':'attribute','severity':'low','explanation':'材料没有说明具体标识。','evidence':[],'proposed_memory_change':{}}]})
        _,client,project,_,run,_=self.flow(InsufficientWithChange()); checked=client.get(f'/api/projects/{project}/checks/{run}').json()['data']; self.assertEqual((checked['status'],checked['error_code']),('failed','insufficient_evidence_memory_change'))
        class OutsideEvidence:
            available=True; label='outside-evidence'
            def evaluate(_,request):
                issue=grounded_issue(request); issue['evidence'][0]['span_id']='outside-current-claim'; return ProviderResult({'issues':[issue]})
        _,client,project,_,run,_=self.flow(OutsideEvidence()); checked=client.get(f'/api/projects/{project}/checks/{run}').json()['data']; self.assertEqual((checked['status'],checked['error_code']),('failed','evidence_unresolvable'))
        invalid_payloads=[
            ({'issues':[],'extra':True},'schema_invalid'),
            ({'issues':[{'claim_span_id':'unknown','status':'conflict','category':'invalid','severity':'high','explanation':'x','evidence':[]}]},'schema_invalid'),
            ({'issues':[{'claim_span_id':'unknown','status':'conflict','category':'attribute','severity':'high','evidence':[]}]},'schema_invalid'),
            ({'issues':[{'claim_span_id':'unknown','status':'no_conflict','category':'attribute','severity':'low','explanation':'x','evidence':[]}]},'no_conflict_issue_forbidden'),
            ({'issues':[{'claim_span_id':'unknown','status':'insufficient_evidence','category':'attribute','severity':'low','explanation':'x','evidence':[],'proposed_memory_change':{}}]},'schema_invalid'),
        ]
        for payload,code in invalid_payloads:
            class InvalidPayload:
                available=True; label='invalid-payload'
                def evaluate(_,request,payload=payload): return ProviderResult(payload)
            _,client,project,_,run,_=self.flow(InvalidPayload()); checked=client.get(f'/api/projects/{project}/checks/{run}').json()['data']; self.assertEqual((checked['status'],checked['error_code']),('failed',code))

    def test_all_accepted_replace_inherits_and_updates_v5_identity(self):
        class Replace:
            available=True; label='replace'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request,0,'replace')]})
        app,client,project,_,run,checked=self.flow(Replace()); issue=checked['issues'][0]
        self.assertEqual(client.post(f'/api/projects/{project}/issues/{issue["id"]}/decision',json={'run_id':run,'source_revision':1,'decision':'keep_intentional'},headers=key()).status_code,200)
        changes=client.post(f'/api/projects/{project}/memory/change-sets',json={'run_id':run,'source_run_revision':1,'resolved_revision':1},headers=key()).json()['data']['change_set']; item=changes['items'][0]
        result=client.post(f'/api/projects/{project}/memory/change-sets/{changes["id"]}/commit',json={'confirm':True,'accepted_item_ids':[item['id']],'rejected_item_ids':[]},headers=key())
        self.assertEqual((result.json()['data']['status'],result.json()['data']['memory_version']['current']),('committed',5))
        with app.state.database.connection() as connection:
            v4=connection.execute('SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=4',(project,)).fetchone()[0]; v5=connection.execute('SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=5',(project,)).fetchone()[0]; changed=connection.execute('SELECT value FROM v2_memory_records WHERE id=?',(item['before']['id']+'-v5',)).fetchone()[0]
            self.assertEqual(v4,v5); self.assertEqual(changed,item['after']['value'])

    def test_commit_guard_errors_leave_database_snapshot_unchanged(self):
        class One:
            available=True; label='guard'
            def evaluate(_,request): return ProviderResult({'issues':[grounded_issue(request)]})
        app,client,project,_,run,checked=self.flow(One()); issue=checked['issues'][0]
        client.post(f'/api/projects/{project}/issues/{issue["id"]}/decision',json={'run_id':run,'source_revision':1,'decision':'keep_intentional'},headers=key())
        changes=client.post(f'/api/projects/{project}/memory/change-sets',json={'run_id':run,'source_run_revision':1,'resolved_revision':1},headers=key()).json()['data']['change_set']; item=changes['items'][0]['id']; url=f'/api/projects/{project}/memory/change-sets/{changes["id"]}/commit'
        with app.state.database.connection() as connection: before='\n'.join(connection.iterdump())
        for payload,code in (({'confirm':False,'accepted_item_ids':[item],'rejected_item_ids':[]},'confirmation_required'),({'confirm':True,'accepted_item_ids':[item],'rejected_item_ids':[item]},'invalid_item_selection'),({'confirm':True,'accepted_item_ids':['unknown'],'rejected_item_ids':[item]},'invalid_item_selection')):
            response=client.post(url,json=payload,headers=key()); self.assertEqual((response.status_code,response.json()['error']['code']),(400 if code=='confirmation_required' else 422,code))
            with app.state.database.connection() as connection: self.assertEqual('\n'.join(connection.iterdump()),before)

if __name__ == "__main__":
    unittest.main()
