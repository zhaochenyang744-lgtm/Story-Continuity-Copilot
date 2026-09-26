"""Independent capture integrity and six fresh scripted API probes; no real Provider."""
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
import traceback
import uuid
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASSETS = ROOT / 'evaluation/current_contract_compare_v2'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['SCC_DISABLE_DEFAULT_APP'] = '1'
sys.dont_write_bytecode = True
_connect = socket.socket.connect
def denied(*args, **kwargs): raise AssertionError('external_network_forbidden')
def guarded_connect(sock, address):
    if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'} and any(f.function == '_fallback_socketpair' for f in inspect.stack()):
        return _connect(sock, address)
    return denied()
socket.create_connection = denied
socket.socket.connect = guarded_connect

def read(name): return json.loads((ASSETS / name).read_text(encoding='utf-8'))
def sha(value): return hashlib.sha256(value.encode('utf-8')).hexdigest()
def dump(name, value):
    with (HERE / name).open('x', encoding='utf-8') as handle: json.dump(value, handle, ensure_ascii=False, indent=2)
errors = []
def check(where, condition):
    if not condition: errors.append(where)

cases = {c['case_id']: c for c in read('cases.json')['cases']}
captures = read('actual-inputs.json')
api = read('api-score-probe-results-v2.json')
capture_by_id = {r['case_id']: r for r in captures['rows']}
corpora = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in (ASSETS / 'corpora').glob('*.json')}

def expected_maps(key):
    corpus = corpora[key]
    sources = {f'fixture-span-{key}-{s["chapter_number"]}': s for s in corpus['chapters']}
    memory = {f'fixture-memory-{key}-{i}': {k: row[k] for k in ('memory_type','subject','predicate','value')} | {
        'id': f'fixture-memory-{key}-{i}', 'source_span_id': f'fixture-span-{key}-{row["source"]["chapter_number"]}'}
        for i, row in enumerate(corpus['memory'], 1)}
    return sources, memory

def signature(q):
    result = copy.deepcopy(q)
    for claim in result['claims']: claim['id'] = '<ephemeral-claim-id>'
    return result

def audit_request(case, q, where):
    start = len(errors)
    key = case['corpus_key']; sources, memory = expected_maps(key)
    check(where + ':full-draft', q['draft']['body'] == case['target_draft'])
    check(where + ':draft-id-revision', q['draft']['id'] == 'fixture-draft-' + key.replace('_','-') and q['draft']['revision'] == 2)
    check(where + ':single-exact-claim', len(q['claims']) == 1 and q['claims'][0]['text'] == case['target_draft'])
    supplied = {s['id']: s for claim in q['claims'] for s in claim['allowed_evidence']}
    check(where + ':unique-selected-spans', len(supplied) == len(q['claims'][0]['allowed_evidence']))
    for span_id, s in supplied.items():
        original = sources.get(span_id)
        check(where + ':known-span:' + span_id, original is not None)
        if original is None: continue
        check(where + ':source-body-excerpt:' + span_id, s['body'] == original['body'] == s['prompt_excerpt'])
        check(where + ':chapter-label:' + span_id, s['chapter_id'] == f'fixture-chapter-{key}-{original["chapter_number"]}' and s['label'] == original['source_label'])
    all_declared = case['expected_evidence'] + case['recommended_context'] + [item for group in case['minimum_sufficient_evidence_sets'] for item in group]
    for spec in all_declared:
        sid = f'fixture-span-{key}-{spec["chapter_number"]}'
        check(where + ':declared-body-hash:' + sid, sha(sources[sid]['body']) == spec['body_sha256'] and sources[sid]['source_label'] == spec['source_label'])
    required = {f'fixture-span-{key}-{spec["chapter_number"]}' for spec in case['expected_evidence']}
    check(where + ':required-source-complete', required <= set(supplied))
    check(where + ':all-memory-fields-and-bindings', {m['id']: m for m in q['memory']} == memory)
    return {'case_id':case['case_id'], 'selected_span_count':len(supplied), 'memory_count':len(q['memory']),
            'full_draft_sha256':sha(q['draft']['body']), 'required_ids':sorted(required), 'errors':errors[start:]}

def audit_product(case, row, where):
    start = len(errors)
    q = row['business_request']; raw = row['raw_first']; product = row['final_product']
    sources, memory = expected_maps(case['corpus_key'])
    check(where + ':terminal-completed', product['status'] == row['status'] == 'completed')
    check(where + ':repair-absent-explicit', 'raw_repair' in row and row['raw_repair'] is None)
    check(where + ':raw-final-count', len(raw['issues']) == len(product['issues']))
    check(where + ':memory-version', product['source_memory_version'] == 1)
    check(where + ':normalization-zero', product['metrics']['contract_normalization_count'] == 0)
    for first, issue in zip(raw['issues'], product['issues']):
        check(where + ':current-run-claim', first['claim_span_id'] == issue['claim_span_id'] == q['claims'][0]['id'])
        check(where + ':claim-text', issue['claim_text'] == q['claims'][0]['text'])
        check(where + ':same-nature-category', (first['nature'],first['category']) == (issue['nature'],issue['category']))
        check(where + ':raw-temporal-retained', 'temporal_basis' in first)
        check(where + ':evidence-id-set', {s['span_id'] for s in first['evidence']} == {s['span_id'] for s in issue['evidence']})
        for ev in issue['evidence']:
            orig = sources[ev['span_id']]
            check(where + ':persisted-evidence-body:' + ev['span_id'], ev['excerpt'] == ev['excerpt_context'] == orig['body'])
            check(where + ':persisted-evidence-chapter:' + ev['span_id'], ev['chapter_id'] == f'fixture-chapter-{case["corpus_key"]}-{orig["chapter_number"]}' and ev['chapter_number'] == orig['chapter_number'] and ev['chapter_title'] == orig['title'])
            check(where + ':evidence-run-revision:' + ev['span_id'], ev['source_revision'] == product['source_revision'])
            check(where + ':memory-links:' + ev['span_id'], all(mid in memory and memory[mid]['source_span_id'] == ev['span_id'] for mid in ev['related_memory_ids']))
            raw_ev = next(s for s in first['evidence'] if s['span_id'] == ev['span_id'])
            check(where + ':persisted-relation:' + ev['span_id'], all(raw_ev[k] == ev[k] for k in ('relation','sufficiency','related_memory_ids')))
        check(where + ':chain-resolves', {e['evidence_id'] for e in issue['evidence_chain']} <= {e['id'] for e in issue['evidence']})
    return {'identity':[row['case_id'],row['variant']], 'status':product['status'], 'issue_count':len(product['issues']),
            'raw_natures':[i['nature'] for i in raw['issues']], 'final_natures':[i['nature'] for i in product['issues']], 'errors':errors[start:]}

def main():
    manifest = read('frozen-inputs.json')
    check('manifest:expected-identity', hashlib.sha256((ASSETS/'frozen-inputs.json').read_bytes()).hexdigest() == '35b8a9559b9d5138f21795cdeb74439d010490dd5a9ee07a37cd48dbd44ca337')
    for rel, expected in manifest['source_hashes'].items(): check('manifest:' + rel, hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() == expected)
    check('capture:24-identities', len(captures['rows']) == len(capture_by_id) == len(cases) == 24 and set(capture_by_id) == set(cases))
    capture_rows=[]
    for cid, row in capture_by_id.items():
        capture_rows.append(audit_request(cases[cid], row['business_request'], 'capture:'+cid))
        required = {(x['chapter_number'],x['source_label']) for x in cases[cid]['expected_evidence']}
        check('capture:retrieval-returned:'+cid, required <= {tuple(x) for x in row['retrieval_returned']})
        actual = {(int(s['id'].rsplit('-',1)[1]), s['label']) for s in row['business_request']['claims'][0]['allowed_evidence']}
        check('capture:selected-metadata:'+cid, actual == {tuple(x) for x in row['business_selected']})
    identities = [(r['case_id'],r['variant']) for r in api['rows']]
    expected = {(cid,'gold') for cid in cases} | {(cid,'state_change') for cid,c in cases.items() if 'state_change' in c['allowed_outcomes']}
    check('api:26-exact-identities', len(identities) == len(set(identities)) == 26 and set(identities) == expected)
    api_rows=[]
    for row in api['rows']:
        case=cases[row['case_id']]; where='saved-api:'+row['case_id']+':'+row['variant']
        audit_request(case,row['business_request'],where)
        check(where+':exact-content-except-claim-id', signature(row['business_request']) == signature(capture_by_id[row['case_id']]['business_request']))
        check(where+':product-alias-same', row['product'] == row['final_product'])
        check(where+':scripted-provenance', row['product']['provenance']['provider_label'] == 'compare-v2-scripted-offline' and row['product']['provenance']['model_label'] == 'compare-v2-no-model')
        api_rows.append(audit_product(case,row,where))
    dump('saved-record-audit.json',{'manifest_hash':hashlib.sha256((ASSETS/'frozen-inputs.json').read_bytes()).hexdigest(),'bound_file_count':len(manifest['source_hashes']),'capture_rows':capture_rows,'api_rows':api_rows,'errors':errors.copy(),'independent_real_provider_calls':0})
    if errors: raise AssertionError('saved_record_integrity_checks_failed')

    from fastapi.testclient import TestClient
    from app.config import AppPaths
    from app.main import create_app, COOKIE
    from app.provider import ProviderResult
    from app.stage13 import Stage13Settings
    from evaluation.v2_fixture_loader import load_fixture
    corpus_paths={key:ASSETS/'corpora'/f'{key}.json' for key in corpora}
    selected=[('ccv2-north_glass-world_rule-conflict','gold'),('ccv2-north_glass-object_state-conflict','gold'),
              ('ccv2-orchard_restoration-event_status-conflict','gold'),('ccv2-harbor_signal-character_knowledge-no_conflict','state_change'),
              ('ccv2-basalt_observatory-location_action-no_conflict','state_change'),('ccv2-north_glass-world_rule-insufficient_evidence','gold')]
    fresh=[]
    class FixedProvider:
        available=True; label='independent-compare-v2-scripted'; model_label='not-a-real-model'
        def __init__(self, template): self.template=template;self.requests=[];self.raw=[]
        def evaluate(self, request):
            self.requests.append(copy.deepcopy(request)); payload=copy.deepcopy(self.template)
            for issue in payload['issues']: issue['claim_span_id']=request['claims'][0]['id']
            self.raw.append(copy.deepcopy(payload))
            return ProviderResult(payload,input_tokens=0,output_tokens=0,latency_ms=0)
    for n,(cid,variant) in enumerate(selected,1):
        case=cases[cid]; original=next(r for r in api['rows'] if (r['case_id'],r['variant'])==(cid,variant))
        provider=FixedProvider(original['raw_first'])
        root=pathlib.Path(tempfile.mkdtemp(prefix=f'synthetic-{n:02d}-',dir=HERE))
        app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/'protected'),provider=provider,executor=lambda fn,*args:fn(*args),settings=Stage13Settings.for_test())
        ident=load_fixture(app.state.database,case['corpus_key'],corpus_paths=corpus_paths)
        with app.state.database.connection() as conn:
            app.state.database._insert_empty_author_context_zero(conn,ident.project_id,datetime.now(timezone.utc).isoformat())
            stored=[dict(r) for r in conn.execute('SELECT c.chapter_number,c.title,c.body AS chapter_body,s.id AS span_id,s.label,s.body AS span_body FROM v2_chapters c JOIN v2_source_spans s ON s.chapter_id=c.id WHERE c.project_id=? ORDER BY c.chapter_number',(ident.project_id,))]
        originals=corpora[case['corpus_key']]['chapters']
        check(cid+':fresh-storage-full-body',len(stored)==len(originals) and all((x['chapter_number'],x['title'],x['chapter_body'],x['span_body'],x['label'])==(y['chapter_number'],y['title'],y['body'],y['body'],y['source_label']) for x,y in zip(stored,originals)))
        def data(response):
            assert response.status_code<400, f'API status {response.status_code}'
            return response.json()['data']
        with TestClient(app) as client:
            client.cookies.set(COOKIE,ident.session_token)
            draft=data(client.get(f'/api/projects/{ident.project_id}'))['current_draft']
            saved=data(client.patch(f'/api/projects/{ident.project_id}/drafts/{ident.draft_id}',headers={'Idempotency-Key':str(uuid.uuid4())},json={'base_revision':draft['revision'],'body':case['target_draft']}))
            started=data(client.post(f'/api/projects/{ident.project_id}/checks',headers={'Idempotency-Key':str(uuid.uuid4())},json={'draft_id':saved['id'],'draft_revision':saved['revision']}))
            url=f'/api/projects/{ident.project_id}/checks/{started["run_id"]}?include=issues,evidence,metrics'
            product=data(client.get(url)); reread=data(client.get(url))
        check(cid+':one-scripted-call',len(provider.requests)==len(provider.raw)==1)
        check(cid+':persistent-issues-repeat',product['issues']==reread['issues'])
        actual=provider.requests[0]
        audit_request(case,actual,'fresh:'+cid+':'+variant)
        check(cid+':fresh-capture-content-equal',signature(actual)==signature(capture_by_id[cid]['business_request']))
        row={'case_id':cid,'variant':variant,'status':product['status'],'business_request':actual,'raw_first':provider.raw[0],'raw_repair':None,'final_product':product}
        outcome=audit_product(case,row,'fresh:'+cid+':'+variant)
        row.update({'classification':'fresh synthetic product API with fixed saved scripted payload remapped to current claim IDs; not a model evaluation','fixture_root':str(root),'storage_body_check':True,'own_audit':outcome})
        fresh.append(row)
        dump(f'fresh-{n:02d}.json',row)
    dump('fresh-api-summary.json',{'independent_case_count':len(fresh),'fixed_provider_calls':sum(1 for _ in fresh),'real_provider_calls':0,'rows':[r['own_audit'] for r in fresh],'errors':errors})
    print(json.dumps({'captured_cases_audited':24,'saved_api_identities_audited':26,'fresh_synthetic_api_runs':len(fresh),'errors':errors,'real_provider_calls':0},ensure_ascii=False))
    if errors:raise AssertionError('fresh_probe_integrity_checks_failed')

if __name__=='__main__':
    try:main()
    except Exception:
        failure=traceback.format_exc()
        dump('first-failure-'+uuid.uuid4().hex[:8]+'.json',{'type':'independent_probe_failure','traceback':failure,'errors_so_far':errors})
        raise
