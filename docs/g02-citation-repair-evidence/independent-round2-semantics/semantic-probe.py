"""Independent offline replay and isolated in-process API semantic probe."""
from __future__ import annotations
import copy
import hashlib
import inspect
import json
import os
import pathlib
import socket
import sys
import tempfile
import uuid

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
os.environ['SCC_DISABLE_DEFAULT_APP'] = '1'
sys.path.insert(0, str(ROOT / 'backend'))
sys.stdout.reconfigure(encoding='utf-8')

def reject_network(*_args, **_kwargs):
    raise AssertionError('External socket connection prohibited in this probe')
socket.create_connection = reject_network
_original_connect = socket.socket.connect
def guard_connect(sock, address):
    # Windows asyncio implements its local self-pipe through socketpair fallback.
    if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'} and any(
            frame.function == '_fallback_socketpair' for frame in inspect.stack()):
        return _original_connect(sock, address)
    return reject_network()
socket.socket.connect = guard_connect

from fastapi.testclient import TestClient
from app.engine import WritingAnalysisEngine
from app.brief_citations import split_draft_claims
from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult
from app.stage13 import Stage13Settings

V4 = ROOT / 'evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases'
checks = []
def check(name, condition):
    checks.append({'name': name, 'passed': bool(condition)})

def check_sources(prefix, result, request):
    maps = WritingAnalysisEngine._source_maps(request)
    for location, sources in [('summary', result['summary_sources'])] + [
        (f'item-{i+1}', item['sources']) for i, item in enumerate(result['items'])]:
        for source in sources:
            source_id, kind = source['source_id'], source['source_type']
            source_record = maps[kind].get(source_id)
            check(f'{prefix}:{location}:{kind}:{source_id}:resolves', source_record is not None)
            expected = source_record.get('text', source_record.get('body', source_record.get('value', source_record.get('summary', ''))))
            check(f'{prefix}:{location}:{source_id}:excerpt', source['excerpt'] == expected)

replays = []
for name in ('05-g02-time-bound.json', '02-g02-long-sentence.json', '01-g02-three-sentences.json', '04-g02-identical-text.json'):
    path = V4 / name
    saved = json.loads(path.read_text(encoding='utf-8'))
    request = copy.deepcopy(saved['business_requests'][0]['business_request'])
    raw = copy.deepcopy(saved['model_outputs'][0]['business_json'])
    result = WritingAnalysisEngine(object()).validate(raw, request)
    claims = request['layers']['written']['draft_claims']
    for claim in claims:
        check(name + ':own-draft:' + str(claim['ordinal']), any(claim['text'] in item['text'] and any(
            source['source_id'] == claim['id'] and source['excerpt'] == claim['text'] for source in item['sources']) for item in result['items']))
    check(name + ':covered', result['draft_coverage']['status'] == 'covered')
    check(name + ':item-limit', len(result['items']) <= 12)
    check(name + ':summary-limit', len(result['summary']) <= 400)
    if 'time-bound' in name:
        check(name + ':both-times-in-summary', all(claim['text'] in result['summary'] for claim in claims))
        check(name + ':both-summary-own-ids', {claim['id'] for claim in claims} <= {source['source_id'] for source in result['summary_sources']})
    if 'long-sentence' in name:
        check(name + ':tail-summary', '最后把银钥匙交给陈澈并得知弟弟还活着。' in result['summary'])
    check_sources(name, result, request)
    replays.append({'case': name, 'classification': 'unchanged saved V4 actual business input and first model JSON replayed through later validator; not a new model run',
                    'source_case_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'analysis': result})

old_dialogue = json.loads((V4 / '06-g02-dialogue-attribution.json').read_text(encoding='utf-8'))
body = old_dialogue['input']['saved_draft']
expected_claims = ['陈澈说：‘温岚已经把潮汐表交给林默。’', '温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。’']
check('dialogue:independent-split', split_draft_claims(body) == expected_claims)

class ScriptedProvider:
    available = True
    label = 'independent-scripted-local'
    model_label = 'not-a-real-model'
    def __init__(self):
        self.requests = []
        self.responses = []
    def evaluate(self, request):
        self.requests.append(copy.deepcopy(request))
        assert request['task'] == 'context_brief'
        claims = request['layers']['written']['draft_claims']
        memory = next(row for row in request['layers']['confirmed']['memory_records'] if row['predicate'] == 'does_not_know')
        plan = request['layers']['planned']['story_plans'][0]
        items = []
        for i, claim in enumerate(claims):
            items.append({'section': 'confirmed_fact', 'text': old_dialogue['model_outputs'][0]['business_json']['items'][i]['text'],
                          'sources': [{'source_type': 'draft_claim', 'source_id': claim['id']}]})
        items += [
            {'section': 'confirmed_fact', 'text': '温岚已经知道廊桥钥匙的含义。', 'sources': [{'source_type': 'memory_record', 'source_id': memory['id']}]},
            {'section': 'confirmed_fact', 'text': '林默已经把星钥交给沈砚。', 'sources': [{'source_type': 'author_context', 'source_id': plan['id']}]},
        ]
        payload = {'summary': '这是固定脚本，不是本轮真实模型答复。', 'summary_sources': [item['sources'][0] for item in items[:2]], 'items': items}
        self.responses.append(copy.deepcopy(payload))
        return ProviderResult(payload, input_tokens=0, output_tokens=0, latency_ms=0)

fixture = pathlib.Path(tempfile.mkdtemp(prefix='synthetic-api-', dir=HERE))
provider = ScriptedProvider()
app = create_app(AppPaths.from_project_root(fixture, protected_poc_root=fixture / 'protected'), provider=provider,
                 executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
def idem(): return {'Idempotency-Key': str(uuid.uuid4())}
with TestClient(app) as client:
    response = client.post('/api/auth/register', headers=idem(), json={'account_name': 'synthetic-semantic-owner', 'display_name': 'Synthetic', 'password': 'synthetic-local-only-pass', 'recovery_email': 'semantic@example.test'})
    assert response.status_code == 201, response.status_code
    project_id = response.json()['data']['onboarding']['tutorial']['project_id']
    project = client.get(f'/api/projects/{project_id}').json()['data']
    draft = project['current_draft']
    response = client.post(f'/api/projects/{project_id}/author-intent/story-plans', headers=idem(), json={
        'base_author_context_version': 0, 'title': '未来交接安排', 'summary': '计划在下一章让林默把星钥交给沈砚。',
        'goal': '尚未写入正文的未来交接。', 'status': 'planned', 'target_chapter_number': draft['chapter_number']})
    assert response.status_code == 201, response.status_code
    response = client.patch(f'/api/projects/{project_id}/drafts/{draft["id"]}', headers=idem(), json={'base_revision': draft['revision'], 'body': body})
    assert response.status_code == 200, response.status_code
    draft = client.get(f'/api/projects/{project_id}').json()['data']['current_draft']
    response = client.post(f'/api/projects/{project_id}/analyses', headers=idem(), json={'analysis_type': 'context_brief', 'draft_id': draft['id'], 'draft_revision': draft['revision']})
    assert response.status_code == 202, response.status_code
    run_id = response.json()['data']['run_id']
    first_read = client.get(f'/api/projects/{project_id}/analyses/{run_id}').json()['data']
    second_read = client.get(f'/api/projects/{project_id}/analyses/{run_id}').json()['data']
    check('api:completed', first_read['status'] == 'completed')
    check('api:persisted-reread-identical', first_read['analysis'] == second_read['analysis'])
    request = provider.requests[0]
    claims = request['layers']['written']['draft_claims']
    result = second_read['analysis']
    check('api:exact-two-closed-claims', [claim['text'] for claim in claims] == expected_claims)
    check('api:body-lossless', ''.join(claim['text'] for claim in claims) == body)
    check('api:no-punctuation-claim', len(claims) == 2 and all(len(claim['text']) > 1 for claim in claims))
    check('api:covered-no-false-partial', result['draft_coverage']['status'] == 'covered' and not result['draft_coverage']['reasons'])
    for claim in claims:
        check('api:closed-dialogue-own-item:' + str(claim['ordinal']), any(item['section'] == 'recent_source' and claim['text'] in item['text'] and any(source['source_id'] == claim['id'] and source['excerpt'] == claim['text'] for source in item['sources']) for item in result['items']))
        check('api:dialogue-in-summary:' + str(claim['ordinal']), claim['text'] in result['summary'])
    memory_items = [item for item in result['items'] if any(source['source_type'] == 'memory_record' for source in item['sources'])]
    plan_items = [item for item in result['items'] if any(source['source_type'] == 'author_context' for source in item['sources'])]
    check('api:not-knows-predicate-preserved', bool(memory_items) and all('不知道' in item['text'] and '已经知道' not in item['text'] for item in memory_items))
    check('api:plan-not-established-fact', bool(plan_items) and all(item['section'] == 'related_plan' and '作者计划记录' in item['text'] and '计划在下一章' in item['text'] and '已经把星钥交给' not in item['text'] for item in plan_items))
    check_sources('api-persisted', result, request)

output = {'classification': 'independent offline product behavior only; no new real model outcome', 'external_provider_calls': 0,
          'source_replays': replays, 'fresh_dialogue_api': {'classification': 'fresh input IDs and complete quoted claims; fixed scripted response uses V4 dialogue paraphrases plus deliberate false knowledge/plan assertions; not a new model run',
          'fixture_root': str(fixture), 'scripted_call_count': len(provider.requests), 'business_request': request, 'scripted_response': provider.responses[0], 'persisted_analysis': result, 'run_status': second_read['status']},
          'checks': checks, 'failed_checks': [item for item in checks if not item['passed']]}
with (HERE / 'semantic-probe-results.json').open('x', encoding='utf-8') as handle:
    json.dump(output, handle, ensure_ascii=False, indent=2)
print(json.dumps({'checks': len(checks), 'failed': output['failed_checks'], 'external_provider_calls': 0}, ensure_ascii=False))
if output['failed_checks']: raise SystemExit(1)
