"""Create safe, deterministic fail-closed evidence without a real provider call."""
from __future__ import annotations

import json
import pathlib
import tempfile
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderInvalidJson, ProviderResult, ProviderTimeout


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation" / "results" / "fail-closed-contract.json"


def key() -> dict[str, str]: return {"Idempotency-Key": str(uuid.uuid4())}


def execute_case(name: str, provider, expected_status: str, expected_error: str) -> dict:
    root=pathlib.Path(tempfile.mkdtemp(prefix='scc-eval-safety-')); app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=provider,executor=lambda fn,*args:fn(*args)); client=TestClient(app)
    registered=client.post('/api/auth/register',json={'account_name':'safety'+uuid.uuid4().hex[:10],'display_name':'Safety','password':'safe-password-68'},headers=key()).json()['data']; project=registered['seeded_projects'][0]['id']; draft=client.get(f'/api/projects/{project}').json()['data']['current_draft']
    response=client.post(f'/api/projects/{project}/checks',json={'draft_id':draft['id'],'draft_revision':1},headers=key())
    if name=='unavailable':
        return {'path':name,'post_status':response.status_code,'error_code':response.json()['error']['code'],'valid':response.status_code==503 and response.json()['error']['code']==expected_error}
    run=response.json()['data']['run_id']; terminal=client.get(f'/api/projects/{project}/checks/{run}?include=issues,evidence,metrics').json()['data']
    return {'path':name,'post_status':response.status_code,'terminal_status':terminal['status'],'error_code':terminal['error_code'],'issue_count':len(terminal.get('issues',[])),'valid':response.status_code==202 and terminal['status']==expected_status and terminal['error_code']==expected_error and not terminal.get('issues')}


class Unavailable:
    label='test-unavailable'; model_label='test-model'; available=False
class Timeout:
    label='test-timeout'; model_label='test-model'; available=True
    def evaluate(self,request): raise ProviderTimeout()
class InvalidJson:
    label='test-invalid-json'; model_label='test-model'; available=True
    def evaluate(self,request): raise ProviderInvalidJson()
class InvalidSchema:
    label='test-invalid-schema'; model_label='test-model'; available=True
    def evaluate(self,request): return ProviderResult({'issues':[{}]})
class InvalidEvidence:
    label='test-invalid-evidence'; model_label='test-model'; available=True
    def evaluate(self,request):
        claim=request['claims'][0]
        return ProviderResult({'issues':[{'claim_span_id':claim['id'],'status':'conflict','category':'attribute','severity':'high','explanation':'safe fixture','evidence':[{'chapter_id':'missing','span_id':'missing','relation':'contradicts','sufficiency':'sufficient','related_memory_ids':[]}]}]})


def main() -> None:
    cases=[execute_case('unavailable',Unavailable(),'failed','provider_unavailable'),execute_case('timeout',Timeout(),'timed_out','provider_timeout'),execute_case('invalid_json',InvalidJson(),'failed','invalid_json'),execute_case('schema',InvalidSchema(),'failed','schema_invalid'),execute_case('evidence_grounding',InvalidEvidence(),'failed','evidence_unresolvable')]
    result={'evaluation':'scc-web-demo-eval-v1','type':'deterministic_fail_closed_contract','provider_calls':0,'paths':cases,'validity':sum(item['valid'] for item in cases)/len(cases)}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True); OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
