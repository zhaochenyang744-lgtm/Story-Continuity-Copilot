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

def legacy_content(kwargs):
    prompt=json.loads(kwargs['json']['messages'][0]['content'])
    claim=prompt['current_claims'][0]
    source=claim['allowed_evidence'][0]
    return json.dumps({'issues':[{'claim_span_id':claim['id'],'status':'conflict','category':'attribute','severity':'low','explanation':'旧格式需要一次契约修复。','evidence':[{'chapter_id':source['chapter_id'],'span_id':source['id'],'relation':'contradicts','sufficiency':'sufficient','related_memory_ids':[]}]}]},ensure_ascii=False)

for mode,limit in [('repair-denied-before-dispatch',1),('repair-invalid-json',10),('repair-timeout-invalid-json',10)]:
    p=deepseek();app,client,uid,pid,project=app_for(p,limit);posted=[]
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            posted.append('post')
            if len(posted)==1:return JsonResponse(legacy_content(kwargs))
            if mode=='repair-timeout-invalid-json' and len(posted)==2:raise httpx.ReadTimeout('repair response lost')
            return JsonResponse('invalid-json')
    p._factory=Client
    d=project['current_draft']
    created=client.post(f'/api/projects/{pid}/checks',headers=headers(),json={'draft_id':d['id'],'draft_revision':d['revision']})
    assert created.status_code==202,created.text
    rid=created.json()['data']['run_id']
    with app.state.database.connection() as c:
        run=dict(c.execute('SELECT status,error_code,input_tokens,output_tokens,cost_cny FROM v2_runs WHERE id=?',(rid,)).fetchone())
        ledger=c.execute('SELECT COUNT(*) FROM v2_provider_attempts WHERE user_id=?',(uid,)).fetchone()[0]
    metrics=operations_usage({'database':app.state.database.paths.database_path,'failure_window_hours':24,'stuck_run_minutes':10})['run_observed_metrics']
    expected_posts={'repair-denied-before-dispatch':1,'repair-invalid-json':2,'repair-timeout-invalid-json':3}[mode]
    expected_totals={'repair-denied-before-dispatch':[11,7,0.2],'repair-invalid-json':[22,14,0.4],'repair-timeout-invalid-json':[None,None,None]}[mode]
    expected_error='provider_attempt_quota_exceeded' if mode=='repair-denied-before-dispatch' else 'invalid_json'
    expected_metric_status='unknown' if mode=='repair-timeout-invalid-json' else 'available'
    record(mode,len(posted)==ledger==expected_posts and run['status']=='failed' and run['error_code']==expected_error and [run[k] for k in ('input_tokens','output_tokens','cost_cny')]==expected_totals and all(metrics[k]['status']==expected_metric_status for k in ('input_tokens','output_tokens','cost_cny')),{'posts':len(posted),'ledger':ledger,'run':run,'operations_metrics':metrics,'expected_totals':expected_totals})
record('external_network_disabled',network_attempts==[],{'attempted_external_connections':len(network_attempts),'actual_external_requests':0,'smtp_requests':0})
with (OUT/'failure-boundary-control-results.json').open('x',encoding='utf-8') as f:json.dump(results,f,ensure_ascii=False,indent=2)
print(json.dumps({'probes':len(results),'passed':sum(r['passed'] for r in results),'findings':[r for r in results if not r['passed']]},ensure_ascii=False,indent=2))
