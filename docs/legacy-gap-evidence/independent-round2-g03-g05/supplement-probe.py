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

from app.provider import ProviderInvalidJson

class JsonResponse:
    def __init__(self,content):self.content=content
    def raise_for_status(self):pass
    def json(self):return {'choices':[{'message':{'content':self.content,'finish_reason':'stop'}}], 'usage':{'prompt_tokens':11,'completion_tokens':7,'cost_cny':0.2}}

for mode in ('normal-success','timeout-success','timeout-invalid-json'):
    p=deepseek();app,_,uid,_,_=app_for(p,10);posted=[]
    reservation=app.state.stage13.reserve_workflow(uid,None,'independent-observed-response')
    class DirectClient:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            posted.append('post')
            if mode!='normal-success' and len(posted)==1:raise httpx.ReadTimeout('lost first response')
            return JsonResponse('invalid-json' if mode=='timeout-invalid-json' else '{"issues":[]}')
    p._factory=DirectClient
    try:
        with provider_usage(uid,reservation):r=UsageGuardProvider(p,app.state.stage13).evaluate(REQUEST)
        error=None
    except ProviderInvalidJson as e:r=e;error=type(e).__name__
    total=[r.input_tokens,r.output_tokens,r.cost_cny]
    observed=[r.observed_response_input_tokens,r.observed_response_output_tokens,r.observed_response_cost_cny]
    record('direct_observed_'+mode,total==([11,7,0.2] if mode=='normal-success' else [None,None,None]) and observed==[11,7,0.2] and len(posted)==count(app,reservation)==(1 if mode=='normal-success' else 2),{'total':total,'observed_response':observed,'posts':len(posted),'ledger':count(app,reservation),'exception':error})

def legacy_content(kwargs):
    prompt=json.loads(kwargs['json']['messages'][1]['content'])
    claim=prompt['current_claims'][0]
    source=claim['allowed_evidence'][0]
    return json.dumps({'issues':[{'claim_span_id':claim['id'],'status':'conflict','category':'attribute','severity':'low','explanation':'旧格式需要一次契约修复。','evidence':[{'chapter_id':source['chapter_id'],'span_id':source['span_id'],'relation':'contradicts','sufficiency':'sufficient','related_memory_ids':[]}]}]},ensure_ascii=False)

# Normal success, parser errors, contract repair and a failure after earlier known usage.
for mode,limit in [('normal-success',10),('invalid-json',10),('timeout-invalid-json',10),('repair-success',10),('repair-second-timeout-success',10),('repair-timeouts',10),('repair-retry-denied',2)]:
    p=deepseek();app,client,uid,pid,project=app_for(p,limit);posted=[];repair_flags=[]
    class PublicClient:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            posted.append('post')
            prompt=json.loads(kwargs['json']['messages'][1]['content'])
            repair_flags.append('contract_repair' in prompt)
            if mode=='timeout-invalid-json' and len(posted)==1:raise httpx.ReadTimeout('lost before invalid json')
            if mode in ('invalid-json','timeout-invalid-json'):return JsonResponse('invalid-json')
            if mode.startswith('repair') and len(posted)==1:return JsonResponse(legacy_content(kwargs))
            if mode in ('repair-timeouts','repair-retry-denied') or (mode=='repair-second-timeout-success' and len(posted)==2):raise httpx.ReadTimeout('repair response lost')
            return JsonResponse('{"issues":[]}')
    p._factory=PublicClient
    d=project['current_draft']
    created=client.post(f'/api/projects/{pid}/checks',headers=headers(),json={'draft_id':d['id'],'draft_revision':d['revision']})
    assert created.status_code==202,created.text
    rid=created.json()['data']['run_id']
    with app.state.database.connection() as c:
        run=dict(c.execute('SELECT status,error_code,input_tokens,output_tokens,cost_cny FROM v2_runs WHERE id=?',(rid,)).fetchone())
        ledger=c.execute('SELECT COUNT(*) FROM v2_provider_attempts WHERE user_id=?',(uid,)).fetchone()[0]
    report=operations_usage({'database':app.state.database.paths.database_path,'failure_window_hours':24,'stuck_run_minutes':10})
    expected_posts={'normal-success':1,'invalid-json':1,'timeout-invalid-json':2,'repair-success':2,'repair-second-timeout-success':3,'repair-timeouts':3,'repair-retry-denied':2}[mode]
    expected_status='completed' if mode in ('normal-success','repair-success','repair-second-timeout-success') else 'timed_out' if mode=='repair-timeouts' else 'failed'
    expect_unknown=mode in ('timeout-invalid-json','repair-second-timeout-success','repair-timeouts','repair-retry-denied')
    multiplier=2 if mode=='repair-success' else 1
    totals=[run[k] for k in ('input_tokens','output_tokens','cost_cny')]
    metrics=report['run_observed_metrics']
    good=run['status']==expected_status and len(posted)==ledger==expected_posts
    good=good and (totals==[None,None,None] and all(metrics[k]['status']=='unknown' for k in ('input_tokens','output_tokens','cost_cny')) if expect_unknown else totals==[11*multiplier,7*multiplier,0.2*multiplier] and all(metrics[k]['status']=='available' for k in ('input_tokens','output_tokens','cost_cny')))
    record('public_metrics_'+mode,good,{'posts':len(posted),'ledger':ledger,'repair_dispatches':repair_flags,'run':run,'operations_metrics':metrics,'expected_unknown_total':expect_unknown,'expected_posts':expected_posts,'expected_status':expected_status})

class TargetImpact:
    available=True;label='independent-offline';model_label='independent-offline'
    def __init__(self):self.requests=[]
    def evaluate(self,request):
        self.requests.append(request)
        source=request['layers']['written']['source_spans'][0]
        return ProviderResult({'summary':'目标原文应复核。','items':[{'area':'chapter','target_id':source['chapter_id'],'impact':'星钥的保管安排需要复核。','evidence':[{'source_type':'source_span','source_id':source['id']}]}]},1,1,latency_ms=1)

stub=TargetImpact();app,client,uid,pid,project=app_for(stub,100);db=app.state.database
with db.connection() as c:
    target=dict(c.execute('SELECT id,source_span_id FROM v2_memory_records WHERE project_id=? AND version=? AND source_span_id IS NOT NULL LIMIT 1',(pid,project['current_memory_version'])).fetchone())
    c.execute('UPDATE v2_memory_records SET subject=?,predicate=?,value=? WHERE id=?',('星钥','holder','星钥始终由乔霁保管。',target['id']))
d=project['current_draft'];fact='星钥始终由乔霁保管。'
for mode,body in [('short-full',fact),('late-bounded','晴日里，绒草覆盖山坡。'*100+fact+'平静的溪水流过石桥。'*40),('unlocated','晴日里，绒草覆盖山坡。'*100)]:
    with db.connection() as c:c.execute('UPDATE v2_source_spans SET body=? WHERE id=?',(body,target['source_span_id']))
    res=client.post(f'/api/projects/{pid}/analyses',headers=headers(),json={'analysis_type':'change_impact','draft_id':d['id'],'draft_revision':d['revision'],'proposal':{'target_type':'memory','target_id':target['id'],'proposed_change':'改为沈砚保管星钥。'}})
    assert res.status_code==202,res.text
    view=client.get(f"/api/projects/{pid}/analyses/{res.json()['data']['run_id']}").json()['data']
    meta=view['retrieval']['target_source'];source=next(s for s in stub.requests[-1]['layers']['written']['source_spans'] if s['id']==target['source_span_id'])
    actual=view['analysis'];missing=mode=='unlocated'
    good=meta['status']==('unlocated' if missing else 'selected') and meta['original_chars']==len(body) and meta['excerpt_chars']==len(source['body']) and meta['excerpt_truncated']==(len(body)>500)
    good=good and ((actual['evidence_status']=='insufficient' and actual['items']==[]) if missing else actual['evidence_status']=='supported' and len(actual['items'])==1 and fact in source['body'] and len(source['body'])<=502)
    if mode=='short-full':good=good and source['body']==body and not meta['excerpt_truncated']
    record('target_fact_'+mode,good,{'target_source':meta,'provided_excerpt':source['body'],'analysis':actual})

record('external_network_disabled',network_attempts==[],{'attempted_external_connections':len(network_attempts),'actual_external_requests':0,'smtp_requests':0})
with (OUT/'supplement-results.json').open('x',encoding='utf-8') as f:json.dump(results,f,ensure_ascii=False,indent=2)
print(json.dumps({'probes':len(results),'passed':sum(r['passed'] for r in results),'findings':[r for r in results if not r['passed']]},ensure_ascii=False,indent=2))
