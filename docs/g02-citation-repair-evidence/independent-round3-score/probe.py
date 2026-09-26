"""Independent in-memory scorer controls. Does not run capture or Provider entrypoints."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import copy
import hashlib
import importlib.util
import json
import pathlib
import socket
import sqlite3
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'evaluation/current_contract_compare_v2'
EXPECTED = '35b8a9559b9d5138f21795cdeb74439d010490dd5a9ee07a37cd48dbd44ca337'
def forbidden(*args, **kwargs):
    raise AssertionError('Network/database access forbidden in independent scorer probe')
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
manifest = json.loads((BASE / 'frozen-inputs.json').read_text(encoding='utf-8'))
paths = list(manifest['source_hashes']) + ['evaluation/current_contract_compare_v2/frozen-inputs.json']
before = {name: sha(ROOT / name) for name in paths}
assert before[paths[-1]] == EXPECTED
assert all(before[name] == digest for name, digest in manifest['source_hashes'].items())
spec = importlib.util.spec_from_file_location('independent_current_score', BASE / 'score.py')
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)
sys.path.insert(0, str(ROOT / 'backend'))
from app.engine import ContinuityEngine
engine = ContinuityEngine(object())
cases = json.loads((BASE / 'cases.json').read_text(encoding='utf-8'))['cases']
by_id = {case['case_id']: case for case in cases}
saved = json.loads((BASE / 'api-score-probe-results-v2.json').read_text(encoding='utf-8'))['rows']
def get(category, outcome, variant='gold'):
    case = next(c for c in cases if c['decision_category'] == category and c['expected_class'] == outcome)
    return case, next(r for r in saved if r['case_id'] == case['case_id'] and r['variant'] == variant)
records = []
def check(name, category, outcome, mutate=None, *, variant='gold', layer='final', expected='fail', validator=False):
    case, row = get(category, outcome, variant)
    request = copy.deepcopy(row['business_request'])
    payload = copy.deepcopy(row['raw_first' if layer == 'raw' else 'final_product'])
    if mutate: mutate(payload, request)
    result = (scorer.score_raw_one if layer == 'raw' else scorer.score_one)(case, payload, request)
    entry = {'name': name, 'case_id': case['case_id'], 'variant': variant, 'layer': layer,
             'expected_machine_result': expected, 'score': result, 'expectation_met': result['machine_result'] == expected}
    if validator:
        try:
            engine.validate(copy.deepcopy(payload), copy.deepcopy(request))
            entry['current_validator'] = 'accepted'
        except Exception as exc:
            entry['current_validator'] = type(exc).__name__ + ': ' + str(exc)
    if not entry['expectation_met']:
        entry.update(payload=payload, captured_request=request)
    records.append(entry)

# Exact saved raw and final layers, with no recomposition of product-shaped fields.
baseline = []
for row in saved:
    case = by_id[row['case_id']]
    raw = scorer.score_raw_one(case, row['raw_first'], row['business_request'])
    final = scorer.score_one(case, row['final_product'], row['business_request'])
    baseline.append({'case_id': case['case_id'], 'variant': row['variant'], 'raw': raw, 'final': final,
                     'repair_absent': row['raw_repair'] is None, 'content_matched_capture': row['actual_business_content_equal_capture']})
    assert raw['machine_result'] == final['machine_result'] == 'pass'
    assert raw['semantic_result'] == final['result'] == 'pending_manual_review'

# Prior V1 false positives and legitimate state-change controls.
for category in ('character_knowledge', 'location_action'):
    check('supported_state_change_' + category, category, 'no_conflict', variant='state_change', expected='pass')
    check('raw_supported_state_change_' + category, category, 'no_conflict', variant='state_change', layer='raw', expected='pass', validator=True)
    check('possible_is_not_state_change_' + category, category, 'no_conflict', lambda p,r:p['issues'][0].update(nature='possible_conflict'), variant='state_change')

def add_source(payload, request, case, optional=False):
    issue = payload['issues'][0]
    used = {e['span_id'] for e in issue['evidence']}
    optional_ids = {scorer.span_id(case,x) for x in case['recommended_context']}
    source = next(s for s in request['claims'][0]['allowed_evidence'] if s['id'] not in used and (not optional or s['id'] in optional_ids))
    ev = copy.deepcopy(issue['evidence'][0])
    number = int(source['id'].rsplit('-',1)[-1])
    ev.update(id='independent-added', span_id=source['id'], chapter_id=source['chapter_id'], chapter_number=number,
              excerpt=source['prompt_excerpt'], excerpt_context=source['body'][:500], related_memory_ids=[])
    issue['evidence'].append(ev)
    issue['evidence_chain'].append({'evidence_id':ev['id'], 'role':'missing_link' if issue['nature']=='insufficient_evidence' else 'prior_state'})

conflict_case, _ = get('world_rule','conflict')
check('extra_unrelated_source_even_with_valid_chain', 'world_rule', 'conflict', lambda p,r:add_source(p,r,conflict_case))
check('wrong_chapter', 'world_rule', 'conflict', lambda p,r:p['issues'][0]['evidence'][0].update(chapter_id='unrelated-chapter'))
check('wrong_excerpt', 'world_rule', 'conflict', lambda p,r:p['issues'][0]['evidence'][0].update(excerpt='unrelated text'))
check('wrong_memory_link', 'world_rule', 'conflict', lambda p,r:p['issues'][0]['evidence'][0].update(related_memory_ids=[r['memory'][-1]['id']]))
check('wrong_final_chain_role', 'object_state', 'insufficient_evidence', lambda p,r:p['issues'][0]['evidence_chain'][0].update(role='prior_state'))
check('missing_final_chain', 'object_state', 'insufficient_evidence', lambda p,r:p['issues'][0].update(evidence_chain=[]))
check('insuff_context_upgraded_to_contradiction', 'object_state', 'insufficient_evidence', lambda p,r:p['issues'][0]['evidence'][0].update(relation='contradicts'))
check('insuff_action_upgrade', 'object_state', 'insufficient_evidence', lambda p,r:p['issues'][0].update(available_actions=['edit']))
check('possible_is_not_confirmed', 'world_rule', 'conflict', lambda p,r:p['issues'][0].update(nature='possible_conflict'))
for status in ('failed','timed_out','running','cancelled'):
    check('empty_issues_' + status, 'timeline', 'no_conflict', lambda p,r,s=status:p.update(status=s,issues=[]), expected='terminal_failure')
for case in cases:
    if case['expected_class']=='insufficient_evidence':
        check('minimum_only_' + case['decision_category'],case['decision_category'],'insufficient_evidence',expected='pass')
        if case['recommended_context']:
            check('minimum_plus_optional_' + case['decision_category'],case['decision_category'],'insufficient_evidence',lambda p,r,c=case:add_source(p,r,c,True),expected='pass')
movement_case, _ = get('location_action','no_conflict','state_change')
check('state_change_with_optional_prior', 'location_action','no_conflict',lambda p,r:add_source(p,r,movement_case,True),variant='state_change',expected='pass')

# Existing rubric boundaries, separately scored at raw layer. These are machine-checkable contracts, not narrative entailment.
check('raw_missing_link_chain_absent','object_state','insufficient_evidence',lambda p,r:p['issues'][0].update(evidence_chain=[]),layer='raw',validator=True)
check('raw_missing_link_wrong_role','object_state','insufficient_evidence',lambda p,r:p['issues'][0]['evidence_chain'][0].update(role='prior_state'),layer='raw',validator=True)
check('raw_insuff_action_upgrade','object_state','insufficient_evidence',lambda p,r:p['issues'][0].update(available_actions=['edit']),layer='raw',validator=True)
check('raw_insuff_memory_change','object_state','insufficient_evidence',lambda p,r:p['issues'][0].update(proposed_memory_change={'operation':'add','memory_type':'dynamic_state','subject':'Mira','predicate':'location','value':'North Glass'}),layer='raw',validator=True)
check('raw_unknown_memory_id','object_state','insufficient_evidence',lambda p,r:p['issues'][0]['evidence'][0].update(related_memory_ids=['independent-missing-memory']),layer='raw',validator=True)
check('raw_wrong_temporal_relation','timeline','conflict',lambda p,r:p['issues'][0]['temporal_basis'].update(relation='unknown'),layer='raw',validator=True)
check('raw_wrong_evidence_relation','timeline','conflict',lambda p,r:p['issues'][0]['evidence'][0].update(relation='context'),layer='raw',validator=True)

# Reviewer-specified plausible category controls on different missing questions.
for original, alternative in [('character_knowledge','attribute'),('relationship','timeline'),('timeline','relationship')]:
    for layer in ('raw','final'):
        check('question_category_' + original + '_to_' + alternative,original,'insufficient_evidence',lambda p,r,c=alternative:p['issues'][0].update(category=c),layer=layer,expected='pass',validator=layer=='raw')

after = {name: sha(ROOT / name) for name in paths}
result = {'scope':'Independent in-memory scorer controls; no Provider/DB; not gold or model accuracy',
          'timestamp_utc':datetime.now(timezone.utc).isoformat(),'manifest_sha256':EXPECTED,
          'hashes_before':before,'hashes_after':after,'changed_files':[x for x in paths if before[x]!=after[x]],
          'baseline_rows':baseline,'controls':records,'control_count':len(records),
          'expectations_met':sum(r['expectation_met'] for r in records),'expectation_mismatches':[r['name'] for r in records if not r['expectation_met']],
          'real_provider_calls':0,'network_calls':0,'database_connections':0}
assert not result['changed_files']
with (HERE/'results.json').open('x',encoding='utf-8') as stream: json.dump(result,stream,ensure_ascii=False,indent=2)
print(json.dumps({k:result[k] for k in ['manifest_sha256','changed_files','control_count','expectations_met','expectation_mismatches','real_provider_calls','database_connections']},ensure_ascii=False,indent=2))
