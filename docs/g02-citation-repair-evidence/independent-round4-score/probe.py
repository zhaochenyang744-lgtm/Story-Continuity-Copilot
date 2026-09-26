"""V3 independent replay of prior scorer failures and bounded controls; no IO services."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import copy
import hashlib
import json
import pathlib
import socket
import sqlite3
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'evaluation/current_contract_compare_v3'
EXPECTED = '0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf'
def forbidden(*args, **kwargs): raise AssertionError('No network or database allowed')
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
manifest = read(BASE / 'frozen-inputs.json')
protected = dict(manifest['source_hashes'])
protected['evaluation/current_contract_compare_v3/frozen-inputs.json'] = EXPECTED
# Preserve previous independent failure evidence as well as all declared frozen inputs.
for name in ('probe.py','results.json','review.md'):
    path = 'docs/g02-citation-repair-evidence/independent-round3-score/' + name
    protected[path] = sha(ROOT/path)
before = {name:sha(ROOT/name) for name in protected}
assert before == protected
sys.path.insert(0,str(ROOT))
from evaluation.current_contract_compare_v3 import score
from app.engine import ContinuityEngine
cases = read(BASE/'cases.json')['cases']
by_old = {c['lineage']['v2_case_id']:c for c in cases}
saved = read(ROOT/'evaluation/current_contract_compare_v2/api-score-probe-results-v2.json')['rows']
by_row = {(r['case_id'],r['variant']):r for r in saved}
prior = read(ROOT/'docs/g02-citation-repair-evidence/independent-round3-score/results.json')
controls, history = [], []
def record(name, case, row, layer='raw', edit=None, expected='pass', error=None, category_correct=True):
    request=copy.deepcopy(row['business_request'])
    payload=copy.deepcopy(row['raw_first' if layer=='raw' else 'final_product'])
    if category_correct and payload['issues']:
        payload['issues'][0]['category']=case['decision_category']
    if edit: edit(payload,request)
    result=(score.score_raw_one if layer=='raw' else score.score_one)(case,payload,request)
    ok=result['machine_result']==expected and (not error or error in result['errors'])
    if expected=='pass':
        ok=ok and result['semantic_result']=='pending_manual_review'
        if layer=='raw':ok=ok and result['full_validator_result']=='accepted'
    entry={'name':name,'case_id':case['case_id'],'layer':layer,'expected':expected,'required_error':error,
           'score':result,'passed':ok,'payload':payload}
    controls.append(entry)
    return entry
def selected(axis, klass, variant='gold'):
    c=next(c for c in cases if c['category_axis']==axis and c['expected_class']==klass)
    return c,by_row[(c['lineage']['v2_case_id'],variant)]

for row in saved:
    c=by_old[row['case_id']]
    raw=score.score_raw_one(c,row['raw_first'],row['business_request'])
    final=score.score_one(c,row['final_product'],row['business_request'])
    history.append({'case_id':c['case_id'],'variant':row['variant'],'raw_score':raw,'final_score':final,'raw_repair_absent':row['raw_repair'] is None})
assert sum(r['raw_score']['machine_result']=='pass' for r in history)==19
assert sum(r['final_score']['machine_result']=='pass' for r in history)==19
assert all(r['raw_score']['full_validator_result']=='accepted' for r in history)

# Every revised insufficiency category has an unmutated positive control before negative replay.
for c in cases:
    if c['expected_class']=='insufficient_evidence':
        row=by_row[(c['lineage']['v2_case_id'],'gold')]
        for layer in ('raw','final'):
            record('corrected_category_'+c['category_axis'],c,row,layer)
c,row=selected('location_action','insufficient_evidence')
for layer in ('raw','final'):
    item=record('companion_declared_relationship',c,row,layer,lambda p,q:p['issues'][0].update(category='relationship'))
    assert item['score']['category_status']=='pending_manual_adjudication'

# Replay identical R3 bad payloads, changing only the category to eliminate the acknowledged confound.
intended={'raw_missing_link_chain_absent':'raw_evidence_chain_mismatch',
          'raw_missing_link_wrong_role':'raw_missing_link_role_invalid',
          'raw_insuff_action_upgrade':'raw_insufficient_actions_invalid',
          'raw_insuff_memory_change':'raw_insufficient_memory_change_invalid',
          'raw_unknown_memory_id':'raw_memory_link_mismatch'}
for old in prior['controls']:
    if old['name'] not in intended:continue
    c=by_old[old['case_id']]
    row={'raw_first':old['payload'],'business_request':old['captured_request']}
    item=record('replay_'+old['name'],c,row,expected='fail',error=intended[old['name']])
    assert item['score']['full_validator_result']=='rejected'
    assert 'raw_target_or_category_mismatch' not in item['score']['errors']

c,row=selected('world_rule','conflict')
def only_rule(p,q):
    issue=p['issues'][0]
    issue['evidence']=[e for e in issue['evidence'] if e['span_id'].endswith('-1')]
    ev=issue['evidence'][0]
    field='evidence_id' if 'classification' in issue else 'span_id'
    key=ev['id'] if field=='evidence_id' else ev['span_id']
    issue['evidence_chain']=[link for link in issue['evidence_chain'] if link[field]==key]
for layer in ('raw','final'):
    record('single_rule_sufficient',c,row,layer,only_rule)
    record('rule_and_optional_roster',c,row,layer)
for axis in ('character_knowledge','location_action'):
    c,row=selected(axis,'no_conflict','state_change')
    for layer in ('raw','final'):
        record('supported_state_change_'+axis,c,row,layer)
        record('reject_possible_'+axis,c,row,layer,lambda p,q:p['issues'][0].update(nature='possible_conflict'),expected='fail')

c,row=selected('world_rule','conflict')
def extra(p,q):
    issue=p['issues'][0]
    used={e['span_id'] for e in issue['evidence']}
    s=next(s for s in q['claims'][0]['allowed_evidence'] if s['id'] not in used)
    ev=copy.deepcopy(issue['evidence'][0])
    ev.update(id='independent-extra',span_id=s['id'],chapter_id=s['chapter_id'],chapter_number=int(s['id'].rsplit('-',1)[-1]),
              excerpt=s['prompt_excerpt'],excerpt_context=s['body'][:500],related_memory_ids=[])
    issue['evidence'].append(ev)
    issue['evidence_chain'].append({'evidence_id':ev['id'],'role':'prior_state'})
record('extra_unrelated_final',c,row,'final',extra,expected='fail',error='undeclared_extra_evidence')
record('wrong_excerpt_final',c,row,'final',lambda p,q:p['issues'][0]['evidence'][0].update(excerpt='wrong'),expected='fail',error='source_content_mismatch')
record('wrong_chapter_final',c,row,'final',lambda p,q:p['issues'][0]['evidence'][0].update(chapter_id='wrong'),expected='fail',error='source_content_mismatch')
c,row=selected('object_state','insufficient_evidence')
for layer in ('raw','final'):
    record('insuff_wrong_relation',c,row,layer,lambda p,q:p['issues'][0]['evidence'][0].update(relation='contradicts'),expected='fail')
c,row=selected('timeline','no_conflict')
for status in ('failed','timed_out','running','cancelled'):
    record('empty_issues_'+status,c,row,'final',lambda p,q,s=status:p.update(status=s,issues=[]),expected='terminal_failure')

# Strict raw validation must not silently use the product's optional safety normalization path.
c,row=selected('timeline','conflict')
raw=copy.deepcopy(row['raw_first'])
raw['issues'][0]['temporal_basis']['relation']='unknown'
strict=score.score_raw_one(c,copy.deepcopy(raw),copy.deepcopy(row['business_request']))
normalized=ContinuityEngine(object()).validate(copy.deepcopy(raw),copy.deepcopy(row['business_request']),allow_conservative_temporal_normalization=True)
normalization_control={'name':'strict_raw_rejects_normalizable_temporal_conflict','raw_score':strict,
 'explicit_safety_normalization_output':normalized,'passed':strict['machine_result']=='fail' and strict['full_validator_result']=='rejected' and normalized[0]['nature']=='insufficient_evidence'}
assert normalization_control['passed']
after={name:sha(ROOT/name) for name in protected}
assert before==after
out={'scope':'V3 scoped independent scorer recheck; saved V2 data and in-memory controls only',
     'time_utc':datetime.now(timezone.utc).isoformat(),'manifest_sha256':EXPECTED,'hashes_before':before,'hashes_after':after,
     'changed_files':[],'historical_rows':history,'historical_raw_pass':19,'historical_final_pass':19,
     'controls':controls,'normalization_control':normalization_control,'control_count':len(controls)+1,
     'passed_count':sum(x['passed'] for x in controls)+int(normalization_control['passed']),
     'new_api_runs':0,'provider_calls':0,'network_calls':0,'database_connections':0}
with (HERE/'results.json').open('x',encoding='utf-8') as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps({k:out[k] for k in ('manifest_sha256','historical_raw_pass','historical_final_pass','control_count','passed_count','changed_files','new_api_runs','provider_calls','database_connections')},indent=2))
assert out['passed_count']==out['control_count']
