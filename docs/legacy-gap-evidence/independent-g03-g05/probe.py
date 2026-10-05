"""Independent offline probes. Uses only fresh synthetic SQLite databases and fake transports."""
from __future__ import annotations
import os
os.environ['SCC_DISABLE_DEFAULT_APP']='1'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import sys, pathlib, tempfile, json, threading, socket, smtplib, uuid, ipaddress
sys.dont_write_bytecode=True
ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend'))
OUT=pathlib.Path(__file__).resolve().parent
network_attempts=[]
def deny_network(*args,**kwargs):
    network_attempts.append('blocked'); raise AssertionError('external network is forbidden')
socket.create_connection=deny_network
original_connect=socket.socket.connect
def guarded_connect(sock,address):
    # Windows asyncio constructs its internal socketpair through loopback.
    if isinstance(address,tuple) and ipaddress.ip_address(address[0]).is_loopback:
        return original_connect(sock,address)
    return deny_network(sock,address)
socket.socket.connect=guarded_connect
smtplib.SMTP=deny_network
import httpx
from dataclasses import replace
from fastapi.testclient import TestClient
from app.config import AppPaths
from app.main import create_app
from app.provider import DeepSeekProvider,ProviderResult,ProviderDispatchDenied,ProviderTimeout
from app.stage13 import Stage13Settings,UsageGuardProvider,provider_usage
from app.engine import _aggregate
from app.operations import usage as operations_usage

results=[]
def record(name,ok,details):
    results.append({'name':name,'passed':bool(ok),'details':details})
def headers():return {'Idempotency-Key':str(uuid.uuid4())}
class Capture:
    available=True;label='independent-offline';model_label='independent-offline'
    def __init__(self):self.requests=[]
    def evaluate(self,request):
        self.requests.append(request)
        return ProviderResult({'summary':'独立探针不生成影响项目。','items':[]},1,1,latency_ms=1)
def app_for(provider,attempts=20,executor=None):
    root=pathlib.Path(tempfile.mkdtemp(prefix='synthetic-',dir=OUT))
    settings=replace(Stage13Settings.for_test(),registered_provider_attempts=attempts,registered_workflows=100)
    app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=provider,settings=settings,executor=executor or (lambda fn,*args:fn(*args)))
    client=TestClient(app)
    response=client.post('/api/auth/register',headers=headers(),json={'account_name':'independent-author','display_name':'Independent','password':'test-password-independent','recovery_email':'independent@example.test'})
    assert response.status_code==201,response.text
    user=response.json()['data']['user']['id']
    pid=response.json()['data']['onboarding']['tutorial']['project_id']
    project=client.get(f'/api/projects/{pid}').json()['data']
    return app,client,user,pid,project
def deepseek():
    p=object.__new__(DeepSeekProvider)
    p.enabled=True;p.model='offline-fake';p.base_url='https://unit.invalid';p.api_key='fake-local-key'
    p.request_attempts=0;p.successful_responses=0;p.request_cap=None;p.max_retries=1
    return p
REQUEST={'draft':{'id':'d','revision':1,'body':'A neutral sentence.'},'claims':[],'memory':[],'output_schema':{'issues':[]}}
class Response:
    def raise_for_status(self):pass
    def json(self):return {'choices':[{'message':{'content':'{"issues":[]}'}}],'usage':{'prompt_tokens':11,'completion_tokens':7,'cost_cny':0.2}}
def count(app,reservation):
    with app.state.database.connection() as c:return c.execute('SELECT COUNT(*) FROM v2_provider_attempts WHERE reservation_id=?',(reservation,)).fetchone()[0]

for limit in (1,2):
    p=deepseek();app,_,uid,_,_=app_for(p,limit)
    reservation=app.state.stage13.reserve_workflow(uid,None,'independent-transport')
    posted=[]
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            posted.append('post')
            if len(posted)==1:raise httpx.ReadTimeout('simulated response lost after dispatch')
            return Response()
    p._factory=Client
    try:
        with provider_usage(uid,reservation):r=UsageGuardProvider(p,app.state.stage13).evaluate(REQUEST)
        detail={'posts':len(posted),'ledger':count(app,reservation),'provider_attempts':p.request_attempts,'result_usage':_aggregate([r])}
        record('retry_two_dispatches_reserved',limit==2 and len(posted)==count(app,reservation)==p.request_attempts==2,detail)
        record('retry_success_preserves_unknown_first_attempt_usage',r.cost_cny is None,detail)
    except Exception as e:
        detail={'posts':len(posted),'ledger':count(app,reservation),'provider_attempts':p.request_attempts,'exception':type(e).__name__,'code':str(e)}
        record('quota_denial_retains_specific_semantics',limit==1 and type(e) is ProviderDispatchDenied and str(e)=='provider_attempt_quota_exceeded' and len(posted)==count(app,reservation)==1,detail)

p=deepseek();app,_,uid,_,_=app_for(p,1)
reservation=app.state.stage13.reserve_workflow(uid,None,'concurrent-full-evaluate')
posts=[];lock=threading.Lock();barrier=threading.Barrier(4);outcomes=[]
class ConcurrentClient:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def post(self,*args,**kwargs):
        with lock:posts.append('post')
        return Response()
p._factory=ConcurrentClient
def worker():
    barrier.wait()
    try:
        with provider_usage(uid,reservation):UsageGuardProvider(p,app.state.stage13).evaluate(REQUEST)
        value='success'
    except Exception as e:value=type(e).__name__+':'+str(e)
    with lock:outcomes.append(value)
threads=[threading.Thread(target=worker) for _ in range(4)]
for t in threads:t.start()
for t in threads:t.join()
record('concurrent_full_transport_limit',len(posts)==count(app,reservation)==1 and outcomes.count('success')==1,{'posts':len(posts),'ledger':count(app,reservation),'outcomes':sorted(outcomes)})

# Traverse the public request -> engine -> persisted run -> operational metrics path.
for mode,attempt_limit in [('retry-success',10),('quota-denied',1),('both-timeout',10),('connection-error',10)]:
    p=deepseek();app,client,uid,pid,project=app_for(p,attempt_limit);posted=[]
    class PublicClient:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            posted.append('post')
            if mode=='connection-error':raise httpx.ConnectError('simulated connection failure')
            if mode in ('quota-denied','both-timeout') or len(posted)==1:raise httpx.ReadTimeout('simulated response loss')
            return Response()
    p._factory=PublicClient
    d=project['current_draft']
    created=client.post(f'/api/projects/{pid}/checks',headers=headers(),json={'draft_id':d['id'],'draft_revision':d['revision']})
    assert created.status_code==202,created.text
    rid=created.json()['data']['run_id']
    state=client.get(f'/api/projects/{pid}/checks/{rid}?include=issues,evidence,metrics').json()['data']
    with app.state.database.connection() as c:
        run=dict(c.execute('SELECT status,error_code,input_tokens,output_tokens,cost_cny FROM v2_runs WHERE id=?',(rid,)).fetchone())
        ledger=c.execute('SELECT COUNT(*) FROM v2_provider_attempts WHERE user_id=?',(uid,)).fetchone()[0]
        issue_count=c.execute('SELECT COUNT(*) FROM v2_issues WHERE run_id=?',(rid,)).fetchone()[0]
    if mode=='retry-success':
        report=operations_usage({'database':app.state.database.paths.database_path,'failure_window_hours':24,'stuck_run_minutes':10})
        detail={'mode':mode,'posts':len(posted),'ledger':ledger,'run':run,'operations_metrics':report['run_observed_metrics'],'billing_status':report['billed_cost_status']}
        record('persisted_retry_usage_marks_unknown',run['cost_cny'] is None and report['run_observed_metrics']['cost_cny']['status']=='unknown',detail)
    else:
        expected={'quota-denied':('failed','provider_attempt_quota_exceeded',1),'both-timeout':('timed_out','provider_timeout',2),'connection-error':('failed','provider_error',1)}[mode]
        detail={'mode':mode,'posts':len(posted),'ledger':ledger,'run':run,'issues':issue_count}
        record('public_failure_'+mode,(run['status'],run['error_code'],len(posted))==expected and ledger==len(posted) and run['cost_cny'] is None and run['input_tokens'] is None and issue_count==0,detail)

# Test actual input assembly, with a low lexical-rank target beyond the default top-k.
stub=Capture();app,client,uid,pid,project=app_for(stub,100)
db=app.state.database
with db.connection() as c:
    selected=c.execute('SELECT * FROM v2_memory_records WHERE project_id=? AND version=? AND source_span_id IS NOT NULL LIMIT 1',(pid,project['current_memory_version'])).fetchone()
    target=dict(selected);sid=target['source_span_id']
    span=dict(c.execute('SELECT * FROM v2_source_spans WHERE id=?',(sid,)).fetchone())
    chapter=dict(c.execute('SELECT * FROM v2_chapters WHERE id=?',(span['chapter_id'],)).fetchone())
    c.execute('UPDATE v2_memory_records SET subject=?,value=? WHERE id=?',('星钥','星钥始终由乔霁保管。',target['id']))
    for i in range(12):
        values=dict(target);values.update(id='independent-memory-'+str(i),subject='雾钟 灰港 林默 温岚',value='雾钟 灰港 林默 温岚 '+str(i))
        c.execute('INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',tuple(values[k] for k in ('id','project_id','version','memory_type','subject','predicate','value','source_span_id','review_status','valid_from','valid_to','source_claim_id')))
    for i in range(6):
        ch='independent-chapter-'+str(i);sp='independent-span-'+str(i)
        c.execute('INSERT INTO v2_chapters VALUES(?,?,?,?,?,?,?)',(ch,pid,100+i,'雾钟 灰港 林默 温岚 '+str(i),'','雾钟 灰港 林默 温岚 '*10,1))
        c.execute('INSERT INTO v2_source_spans VALUES(?,?,?,?,?,?)',(sp,pid,ch,'雾钟 灰港','雾钟 灰港 林默 温岚 '*10,1))
    target_body='晴日里，绒草覆盖山坡。'*100+'星钥始终由乔霁保管。'+'平静的溪水流过石桥。'*40
    c.execute('UPDATE v2_source_spans SET body=?,label=? WHERE id=?',(target_body,'星钥保管说明',sid))
draft=project['current_draft']
def impact():
    res=client.post(f'/api/projects/{pid}/analyses',headers=headers(),json={'analysis_type':'change_impact','draft_id':draft['id'],'draft_revision':draft['revision'],'proposal':{'target_type':'memory','target_id':target['id'],'proposed_change':'改为由沈砚保管星钥。'}})
    assert res.status_code==202,res.text
    return client.get(f"/api/projects/{pid}/analyses/{res.json()['data']['run_id']}").json()['data']
view=impact();request=stub.requests[-1];retrieval=view['retrieval']
record('low_rank_target_pinned_inside_original_slots',retrieval['selected_ids']['memory_record'][0]==target['id'] and retrieval['selected_ids']['source_span'][0]==sid and len(retrieval['selected_ids']['memory_record'])==8 and len(retrieval['selected_ids']['source_span'])==4,{'target_source':retrieval['target_source'],'counts':retrieval['counts'],'selected_first_memory':retrieval['selected_ids']['memory_record'][0],'selected_first_source':retrieval['selected_ids']['source_span'][0]})
actual_source=next(s for s in request['layers']['written']['source_spans'] if s['id']==sid)
record('pinned_source_contains_target_fact_passage','星钥始终由乔霁保管。' in actual_source['body'],{'target_source':retrieval['target_source'],'supplied_excerpt':actual_source['body'],'target_passage_in_excerpt':'星钥始终由乔霁保管。' in actual_source['body'],'original_length':len(target_body),'supplied_length':len(actual_source['body']),'source_span_truncated':retrieval['truncated']['source_span']})
# Current chapter version mismatch must suppress the old direct source.
with db.connection() as c:c.execute('UPDATE v2_chapters SET source_revision=2 WHERE id=?',(chapter['id'],))
view=impact()
record('stale_chapter_source_is_missing_and_no_determinate_items',view['retrieval']['target_source']['status']=='missing' and sid not in view['retrieval']['selected_ids']['source_span'] and view['analysis']['evidence_status']=='insufficient' and view['analysis']['items']==[],{'target_source':view['retrieval']['target_source'],'analysis':view['analysis']})
# A span newer than project.source_revision cannot pass even if its chapter matches it.
with db.connection() as c:c.execute('UPDATE v2_source_spans SET source_revision=2 WHERE id=?',(sid,))
view=impact()
record('future_source_version_not_in_current_project',view['retrieval']['target_source']['status']=='missing' and sid not in view['retrieval']['selected_ids']['source_span'],{'target_source':view['retrieval']['target_source'],'project_source_revision':view['source_revision']})
record('external_network_disabled',network_attempts==[],{'attempted_external_connections':len(network_attempts),'actual_external_requests':0,'smtp_requests':0})
(OUT/'probe-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'probes':len(results),'passed':sum(r['passed'] for r in results),'findings':[r for r in results if not r['passed']]},ensure_ascii=False,indent=2))
