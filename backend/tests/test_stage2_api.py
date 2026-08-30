"""V2-scoped continuity regression tests replacing the retired public V1 routes."""
from __future__ import annotations

import json, pathlib, sqlite3, tempfile, unittest, uuid
from fastapi.testclient import TestClient
from app.config import AppPaths
from app.database import DemoDatabase
from app.main import create_app
from app.provider import ProviderResult
from app.v2_database import V2Database

def h(): return {"Idempotency-Key":str(uuid.uuid4())}

class ScopedRegressionTests(unittest.TestCase):
    def setUp(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-regression-")); self.c=TestClient(create_app(AppPaths.from_project_root(root,protected_poc_root=root/"protected")))
        r=self.c.post('/api/auth/register',json={"account_name":"regression","display_name":"Regression","password":"valid-password-99"},headers=h()); self.assertEqual(r.status_code,201); self.p=r.json()['data']['seeded_projects'][0]['id']
        self.d=self.c.get(f'/api/projects/{self.p}').json()['data']['current_draft']
    def test_missing_session_is_401(self):
        anonymous=TestClient(self.c.app)
        self.assertEqual(anonymous.get('/api/home').status_code,401)
        self.assertEqual(anonymous.get('/api/auth/session').status_code,401)
        optional=anonymous.get('/api/auth/session?optional=true')
        self.assertEqual(optional.status_code,200)
        self.assertEqual(optional.json()['data'],{'user':None,'session':None})
    def test_draft_read_is_project_scoped(self): self.assertEqual(self.c.get(f'/api/projects/{self.p}/drafts/{self.d["id"]}').status_code,200)
    def test_draft_cas_conflict_is_safe(self):
        self.assertEqual(self.c.patch(f'/api/projects/{self.p}/drafts/{self.d["id"]}',json={"base_revision":9,"body":"x"},headers=h()).status_code,409)
    def test_invalid_include_is_400(self): self.assertEqual(self.c.get(f'/api/projects/{self.p}/checks/no-run?include=evidence').status_code,400)
    def test_unknown_chapter_is_404(self): self.assertEqual(self.c.get(f'/api/projects/{self.p}/chapters?chapter_id=other').status_code,404)
    def test_invalid_world_filter_is_400(self): self.assertEqual(self.c.get(f'/api/projects/{self.p}/world?entry_type=invalid').status_code,400)
    def test_invalid_character_filter_is_400(self): self.assertEqual((self.c.get(f'/api/projects/{self.p}/characters?role_type=invalid').status_code,self.c.get(f'/api/projects/{self.p}/characters?role_type=invalid').json()['error']['code']),(400,'invalid_filter'))
    def test_new_project_has_empty_context(self):
        class CountingProvider:
            label='counting'; available=True
            def __init__(self): self.calls=0
            def evaluate(self, request): self.calls+=1; return ProviderResult({'issues':[]})
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-empty-context-')); provider=CountingProvider(); app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=provider,executor=lambda fn,*args:fn(*args)); client=TestClient(app)
        client.post('/api/auth/register',json={'account_name':'emptyuser','display_name':'Empty','password':'valid-password-99'},headers=h()); project=client.post('/api/projects',json={'title':'空项目'},headers=h()).json()['data']['project']; before=app.state.database.counts()['v2_runs']
        response=client.post(f'/api/projects/{project["id"]}/checks',json={'draft_id':project['current_draft']['id'],'draft_revision':1},headers=h())
        self.assertEqual((response.status_code,response.json()['error']['code']),(422,'insufficient_project_context')); self.assertEqual(provider.calls,0); self.assertEqual(app.state.database.counts()['v2_runs'],before)
        unavailable=TestClient(create_app(AppPaths.from_project_root(pathlib.Path(tempfile.mkdtemp(prefix='scc-empty-unavailable-')),protected_poc_root=pathlib.Path(tempfile.mkdtemp(prefix='scc-empty-protected-')))))
        registration=unavailable.post('/api/auth/register',json={'account_name':'emptyoff','display_name':'Empty Off','password':'valid-password-99'},headers=h()).json()['data']; blank=unavailable.post('/api/projects',json={'title':'另一个空项目'},headers=h()).json()['data']['project']; response=unavailable.post(f'/api/projects/{blank["id"]}/checks',json={'draft_id':blank['current_draft']['id'],'draft_revision':1},headers=h())
        self.assertEqual((response.status_code,response.json()['error']['code']),(422,'insufficient_project_context'))
    def test_reset_replay_is_idempotent(self):
        headers=h(); body={"confirm":True,"reason":"demo_recovery"}; first=self.c.post(f'/api/projects/{self.p}/reset',json=body,headers=headers); second=self.c.post(f'/api/projects/{self.p}/reset',json=body,headers=headers); self.assertEqual(first.json()['data'],second.json()['data'])
    def test_import_rejects_wrong_extension(self): self.assertEqual(self.c.post('/api/imports/preview',files={'file':('x.pdf',b'x','application/pdf')},headers=h()).status_code,415)
    def test_expired_import_clears_temporary_source_without_creating_project(self):
        preview=self.c.post('/api/imports/preview',files={'file':('expired.md','# 第一章\n临时原文'.encode(),'text/markdown')},headers=h()).json()['data']; db=self.c.app.state.database
        with db.connection() as connection: connection.execute("UPDATE v2_import_drafts SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(preview['import_id'],)); before=connection.execute('SELECT COUNT(*) FROM v2_projects').fetchone()[0]
        response=self.c.post(f'/api/imports/{preview["import_id"]}/commit',json={'confirm':True,'title':'不会导入','chapter_preview_ids':[item['preview_id'] for item in preview['detected']['chapters']]},headers=h())
        self.assertEqual((response.status_code,response.json()['error']['code']),(409,'import_expired'))
        with db.connection() as connection: self.assertIsNone(connection.execute('SELECT source_text FROM v2_import_drafts WHERE id=?',(preview['import_id'],)).fetchone()[0]); self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_projects').fetchone()[0],before)
    def test_metadata_requires_archive_confirmation(self): self.assertEqual(self.c.patch(f'/api/projects/{self.p}',json={"base_metadata_revision":1,"status":"archived"},headers=h()).status_code,400)
    def test_cross_account_project_is_not_found(self):
        outsider=TestClient(self.c.app); outsider.post('/api/auth/register',json={"account_name":"secondu","display_name":"Second","password":"valid-password-98"},headers=h()); self.assertEqual(outsider.get(f'/api/projects/{self.p}').status_code,404)
    def test_cross_account_attack_matrix_is_404_and_has_no_database_write(self):
        outsider=TestClient(self.c.app); self.assertEqual(outsider.post('/api/auth/register',json={'account_name':'attackuser','display_name':'Attack','password':'valid-password-98'},headers=h()).status_code,201); db=self.c.app.state.database
        with db.connection() as connection: before='\n'.join(connection.iterdump())
        routes=[
            ('get',f'/api/projects/{self.p}',None),('get',f'/api/projects/{self.p}/outline',None),('get',f'/api/projects/{self.p}/characters',None),('get',f'/api/projects/{self.p}/world',None),('get',f'/api/projects/{self.p}/chapters',None),('get',f'/api/projects/{self.p}/memory',None),('get',f'/api/projects/{self.p}/drafts/{self.d["id"]}',None),('get',f'/api/projects/{self.p}/checks/missing-run',None),
            ('patch',f'/api/projects/{self.p}',{'base_metadata_revision':1,'title':'攻击'}),('patch',f'/api/projects/{self.p}/drafts/{self.d["id"]}',{'base_revision':1,'body':'攻击'}),('post',f'/api/projects/{self.p}/checks',{'draft_id':self.d['id'],'draft_revision':1}),('post',f'/api/projects/{self.p}/issues/missing-issue/decision',{'run_id':'missing-run','source_revision':1,'decision':'false_positive'}),('post',f'/api/projects/{self.p}/memory/change-sets',{'run_id':'missing-run','source_run_revision':1,'resolved_revision':1}),('post',f'/api/projects/{self.p}/memory/change-sets/missing/commit',{'confirm':True,'accepted_item_ids':[],'rejected_item_ids':[]}),('post',f'/api/projects/{self.p}/reset',{'confirm':True,'reason':'demo_recovery'})]
        for method,url,payload in routes:
            response=getattr(outsider,method)(url,json=payload,headers=h()) if payload is not None else getattr(outsider,method)(url)
            self.assertEqual((response.status_code,response.json()['error']['code']),(404,'resource_not_found'))
        with db.connection() as connection: self.assertEqual('\n'.join(connection.iterdump()),before)
    def test_metrics_are_opt_in(self):
        class Provider:
            available=True; label='metrics-test'
            def evaluate(_,request):
                claim=next(item for item in request['claims'] if item['allowed_evidence']); evidence=claim['allowed_evidence'][0]
                return ProviderResult({'issues':[{'claim_span_id':claim['id'],'status':'conflict','category':'object_state','severity':'high','explanation':'可验证。','evidence':[{'chapter_id':evidence['chapter_id'],'span_id':evidence['id'],'relation':'contradicts','sufficiency':'sufficient','related_memory_ids':[]}]}]},input_tokens=33,output_tokens=12,latency_ms=7)
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-metrics-')); client=TestClient(create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=Provider(),executor=lambda fn,*args:fn(*args)))
        registration=client.post('/api/auth/register',json={'account_name':'metricuser','display_name':'Metric','password':'valid-password-99'},headers=h()).json()['data']; project=registration['seeded_projects'][0]['id']; draft=client.get(f'/api/projects/{project}').json()['data']['current_draft']
        run=client.post(f'/api/projects/{project}/checks',json={'draft_id':draft['id'],'draft_revision':1},headers=h()).json()['data']['run_id']
        minimal=client.get(f'/api/projects/{project}/checks/{run}').json()['data']; detailed=client.get(f'/api/projects/{project}/checks/{run}?include=metrics').json()['data']
        self.assertNotIn('metrics',minimal); self.assertEqual({key:detailed['metrics'][key] for key in ('latency_ms','input_tokens','output_tokens','cost_cny')},{'latency_ms':7,'input_tokens':33,'output_tokens':12,'cost_cny':None}); self.assertEqual(detailed['metrics']['provenance'],{'provider_label':'metrics-test','model_label':'metrics-test','prompt_version':'continuity-review-v8-bounded-evidence','schema_version':'continuity-issue-v3','retrieval_method_version':'bounded-lexical-v4-longform','source_memory_version':4}); self.assertTrue(detailed['metrics']['retrieval'])

    def test_login_rate_limit_only_counts_failed_attempts(self):
        account={'account_name':'regression','password':'valid-password-99'}
        for _ in range(9): self.assertEqual(self.c.post('/api/auth/login',json=account).status_code,200)
        bad={'account_name':'regression','password':'wrong-password-00'}
        for _ in range(8): self.assertEqual(self.c.post('/api/auth/login',json=bad).status_code,401)
        limited=self.c.post('/api/auth/login',json=bad)
        self.assertEqual((limited.status_code,limited.json()['error']['code']),(429,'authentication_rate_limited'))

    def test_register_replay_creates_a_fresh_cookie_without_exposing_token(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-register-replay-')); app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected')); key_id=str(uuid.uuid4()); payload={'account_name':'repeatuser','display_name':'Repeat','password':'valid-password-99'}
        first=TestClient(app); created=first.post('/api/auth/register',json=payload,headers={'Idempotency-Key':key_id}); second=TestClient(app); replay=second.post('/api/auth/register',json=payload,headers={'Idempotency-Key':key_id})
        self.assertEqual((created.status_code,replay.status_code),(201,201)); self.assertIn('scc_local_session=',replay.headers.get('set-cookie','')); self.assertEqual(second.get('/api/auth/session').status_code,200); self.assertNotIn('token',json.dumps(replay.json()['data']).casefold())

    def test_reset_invalidates_old_project_write_replay(self):
        patch_key=h(); body={'base_revision':1,'body':'第一次保存。'}
        saved=self.c.patch(f'/api/projects/{self.p}/drafts/{self.d["id"]}',json=body,headers=patch_key); self.assertEqual(saved.status_code,200)
        self.assertEqual(self.c.post(f'/api/projects/{self.p}/reset',json={'confirm':True,'reason':'demo_recovery'},headers=h()).status_code,200)
        replay=self.c.patch(f'/api/projects/{self.p}/drafts/{self.d["id"]}',json=body,headers=patch_key)
        self.assertEqual((replay.status_code,replay.json()['error']['code']),(404,'resource_not_found'))

    def test_csrf_and_query_lineage_fail_closed(self):
        rejected=self.c.post('/api/auth/logout',headers={'Origin':'http://localhost.evil.example','Host':'attacker.example'})
        self.assertEqual((rejected.status_code,rejected.json()['error']['code']),(403,'cross_site_request_rejected'))
        paper=self.c.get('/api/projects').json()['data']['projects'][1]['id']; foreign_chapter=self.c.get(f'/api/projects/{paper}/chapters').json()['data']['chapters'][0]['id']
        self.assertEqual(self.c.get(f'/api/projects/{self.p}/chapters?chapter_id={foreign_chapter}').status_code,404)
        self.assertEqual(self.c.get(f'/api/projects/{self.p}/outline?volume=two').status_code,400)

    def test_character_and_world_broken_provenance_is_422(self):
        db=self.c.app.state.database
        with db.connection() as connection:
            connection.execute("UPDATE v2_characters SET source_ids_json='[\"missing-span\"]' WHERE project_id=?",(self.p,))
        self.assertEqual((self.c.get(f'/api/projects/{self.p}/characters').status_code,self.c.get(f'/api/projects/{self.p}/characters').json()['error']['code']),(422,'source_unavailable'))
        with db.connection() as connection:
            connection.execute("UPDATE v2_characters SET source_ids_json='[]' WHERE project_id=?",(self.p,)); connection.execute("UPDATE v2_world_entries SET related_character_ids_json='[\"missing-character\"]' WHERE project_id=?",(self.p,))
        world=self.c.get(f'/api/projects/{self.p}/world'); self.assertEqual((world.status_code,world.json()['error']['code']),(422,'source_unavailable'))

    def test_home_aggregates_own_severity_and_failed_run(self):
        db=self.c.app.state.database
        with db.connection() as connection:
            draft=connection.execute('SELECT id FROM v2_drafts WHERE project_id=?',(self.p,)).fetchone(); stamp='2026-01-01T00:00:00+00:00'
            connection.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,input_tokens,output_tokens,latency_ms,cost_cny,error_code,retryable,created_at,completed_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('failed-run',self.p,draft['id'],1,'failed','failed','test',None,None,1,None,'provider_error',1,stamp,stamp,'test-model','test-prompt','test-schema','test-retrieval',4))
            connection.execute("INSERT INTO v2_issues(id,project_id,run_id,claim_span_id,status,classification,category,severity,evidence_status,explanation,proposed_change_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('high-issue',self.p,'failed-run','claim-x','open','conflict','object_state','high','sufficient','安全错误',None))
        home=self.c.get('/api/home').json()['data']; pending=next(item for item in home['pending_continuity'] if item['project_id']==self.p)
        self.assertEqual((pending['open_count'],pending['high'],pending['medium'],pending['low']),(5,2,2,1)); self.assertEqual(home['latest_failed_run']['run_id'],'failed-run')

    def test_operational_error_maps_to_operation_specific_safe_envelope(self):
        db=self.c.app.state.database
        with db.connection() as connection: before=connection.execute('SELECT COUNT(*) FROM v2_projects').fetchone()[0]
        original=db._create_project
        def broken(connection,*args,**kwargs):
            connection.execute('INSERT INTO definitely_missing_table VALUES(1)')
        db._create_project=broken
        try:
            response=self.c.post('/api/projects',json={'title':'不会创建'},headers=h())
        finally:
            db._create_project=original
        self.assertEqual((response.status_code,response.json()['error']['code'],response.json()['error']['retryable']),(503,'create_failed',True)); self.assertIn('request_id',response.json())
        with db.connection() as connection: self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_projects').fetchone()[0],before)

    def test_raw_sqlite_failures_roll_back_register_create_import_and_reset(self):
        def missing(connection,*args,**kwargs): connection.execute('INSERT INTO definitely_missing_table VALUES(1)')
        # Registration has inserted an account before seed creation; the raw
        # database failure must roll that account back and retain a safe code.
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-raw-registration-')); app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected')); db=app.state.database; original=db._create_project; db._create_project=missing
        try: registration=TestClient(app).post('/api/auth/register',json={'account_name':'brokenuser','display_name':'Broken','password':'valid-password-99'},headers=h())
        finally: db._create_project=original
        self.assertEqual((registration.status_code,registration.json()['error']['code']),(503,'registration_failed'))
        with db.connection() as connection: self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_users').fetchone()[0],0)
        db=self.c.app.state.database; original=db._create_project
        with db.connection() as connection: project_count=connection.execute('SELECT COUNT(*) FROM v2_projects').fetchone()[0]
        db._create_project=missing
        try: created=self.c.post('/api/projects',json={'title':'回滚项目'},headers=h())
        finally: db._create_project=original
        self.assertEqual((created.status_code,created.json()['error']['code']),(503,'create_failed'))
        with db.connection() as connection: self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_projects').fetchone()[0],project_count)
        preview=self.c.post('/api/imports/preview',files={'file':('rollback.md','# 第一章\n内容'.encode(),'text/markdown')},headers=h()).json()['data']; db._create_project=missing
        try: imported=self.c.post(f'/api/imports/{preview["import_id"]}/commit',json={'confirm':True,'title':'回滚导入','chapter_preview_ids':[item['preview_id'] for item in preview['detected']['chapters']]},headers=h())
        finally: db._create_project=original
        self.assertEqual((imported.status_code,imported.json()['error']['code']),(503,'import_failed'))
        with db.connection() as connection: self.assertIsNone(connection.execute('SELECT committed_at FROM v2_import_drafts WHERE id=?',(preview['import_id'],)).fetchone()[0])
        original_seed=db._seed_grey_harbor; db._seed_grey_harbor=missing; before=self.c.get(f'/api/projects/{self.p}').json()['data']['current_draft']['id']
        try: reset=self.c.post(f'/api/projects/{self.p}/reset',json={'confirm':True,'reason':'demo_recovery'},headers=h())
        finally: db._seed_grey_harbor=original_seed
        self.assertEqual((reset.status_code,reset.json()['error']['code']),(503,'reset_failed')); self.assertEqual(self.c.get(f'/api/projects/{self.p}').json()['data']['current_draft']['id'],before)

    def test_legacy_migration_preserves_continuity_lineage(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix='scc-legacy-migration-')); paths=AppPaths.from_project_root(root,protected_poc_root=root/'protected'); legacy=DemoDatabase(paths); legacy.initialize()
        with legacy.connection() as connection:
            project=connection.execute('SELECT * FROM projects').fetchone(); draft=connection.execute('SELECT * FROM drafts').fetchone(); chapter=connection.execute('SELECT * FROM chapters').fetchone(); span=connection.execute('SELECT * FROM source_spans').fetchone(); memory=connection.execute('SELECT * FROM memory_records').fetchone(); legacy_memory_count=connection.execute('SELECT COUNT(*) FROM memory_records').fetchone()[0]; stamp='2026-01-01T00:00:00+00:00'
            connection.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('legacy-run',project['id'],draft['id'],1,'completed','completed','legacy',12,3,4,None,None,0,stamp,stamp))
            connection.execute("INSERT INTO run_stages VALUES(?,?,?)",('legacy-run','completed',stamp)); connection.execute("INSERT INTO run_claims VALUES(?,?,?,?)",('legacy-claim','legacy-run',0,'旧草稿主张')); connection.execute("INSERT INTO retrieval_traces VALUES(?,?,?,?,?)",('legacy-run','legacy-claim','旧',json.dumps([span['id']]),'v1'))
            connection.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?,?)",('legacy-issue','legacy-run','legacy-claim','decided','object_state','high','sufficient','旧冲突',None))
            connection.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?)",('legacy-evidence','legacy-issue',chapter['id'],span['id'],'摘录','contradicts','sufficient',json.dumps([memory['id']])))
            connection.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?)",('legacy-decision','legacy-issue','legacy-run','keep_intentional',None,1,1,'current',stamp))
            connection.execute("INSERT INTO change_sets VALUES(?,?,?,?,?,?,?,?,?,?,?)",('legacy-cs',project['id'],'legacy-run',1,1,'current',4,5,'committed',stamp,stamp))
            connection.execute("INSERT INTO change_set_items(id,change_set_id,operation,before_json,after_json,source_ids,decision_ids,review_status) VALUES(?,?,?,?,?,?,?,?)",('legacy-item','legacy-cs','add',None,json.dumps({'operation':'add'}),json.dumps(['legacy-issue','legacy-claim']),json.dumps(['legacy-decision']),'accepted'))
            connection.execute("INSERT INTO commit_audits VALUES(?,?,?,?,?,?,?)",('legacy-audit','legacy-cs','committed','[\"legacy-item\"]','[]',None,stamp))
        app=create_app(paths); db:V2Database=app.state.database
        with db.connection() as connection:
            migrated=connection.execute("SELECT id FROM v2_projects WHERE data_origin='v1_migrated'").fetchone(); self.assertIsNotNone(migrated); counts=[connection.execute(f'SELECT COUNT(*) FROM {table} WHERE project_id=?',(migrated['id'],)).fetchone()[0] for table in ('v2_memory_records','v2_drafts','v2_runs','v2_issues','v2_evidence','v2_decisions','v2_change_sets','v2_change_set_items','v2_commit_audits')]
            self.assertEqual(counts,[legacy_memory_count,1,1,1,1,1,1,1,1]); evidence=connection.execute('SELECT e.span_id,s.project_id FROM v2_evidence e JOIN v2_source_spans s ON s.id=e.span_id').fetchone(); self.assertEqual(evidence['project_id'],migrated['id']); migration_user=connection.execute("SELECT id FROM v2_users WHERE account_name='v1-migration'").fetchone(); token,_=db._new_session(connection,migration_user['id'])
        migrated_client=TestClient(app); migrated_client.cookies.set('scc_local_session',token); listing=migrated_client.get('/api/projects'); self.assertEqual(listing.status_code,200); migrated_project=listing.json()['data']['projects'][0]['id']; run_id=migrated_client.get(f'/api/projects/{migrated_project}').json()['data']['latest_run']['run_id']; lineage=migrated_client.get(f'/api/projects/{migrated_project}/checks/{run_id}?include=issues,evidence'); self.assertEqual((lineage.status_code,len(lineage.json()['data']['issues']),len(lineage.json()['data']['issues'][0]['evidence'])),(200,1,1))
        db.initialize()
        with db.connection() as connection: self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_runs').fetchone()[0],1)
