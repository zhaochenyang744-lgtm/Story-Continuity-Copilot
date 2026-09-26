"""Read-only V3 lineage comparison. Stdlib only; no product/scorer/API/DB imports."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V2 = ROOT / 'evaluation/current_contract_compare_v2'
V3 = ROOT / 'evaluation/current_contract_compare_v3'
errors = []

def read(path): return json.loads(path.read_text(encoding='utf-8'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(name, value):
    with (HERE/name).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
def check(label, passed):
    if not passed: errors.append(label)
def normalized(request):
    result = copy.deepcopy(request)
    for claim in result['claims']: claim['id'] = '<ephemeral>'
    return result

prior = read(HERE.parent/'independent-round3-capture/hashes-after.json')
manifest = read(V3/'frozen-inputs.json')
protected = set(x['path'] for x in prior) | set(manifest['source_hashes']) | {
    'evaluation/current_contract_compare_v3/frozen-inputs.json',
    'evaluation/current_contract_compare_v3/HANDOFF.md'}
before = {p:digest(ROOT/p) for p in sorted(protected)}
dump('hashes-before.json', before)
for row in prior: check('v2-prior-hash:'+row['path'], before[row['path']]==row['sha256'])
for path, sha in manifest['source_hashes'].items(): check('v3-bound-hash:'+path, before[path]==sha)
check('v3-manifest-identity', digest(V3/'frozen-inputs.json')=='0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf')

v2cases = {x['case_id']:x for x in read(V2/'cases.json')['cases']}
v3doc = read(V3/'cases.json')
v3cases = {x['lineage']['v2_case_id']:x for x in v3doc['cases']}
capture = {x['case_id']:x['business_request'] for x in read(V2/'actual-inputs.json')['rows']}
saved_list = read(V2/'api-score-probe-results-v2.json')['rows']
saved = {(x['case_id'], x['variant']):x for x in saved_list}
rescored_list = read(V3/'runs/final-offline-rescore/rows.json')['rows']
rescored = {(x['v2_record_id'], x['variant']):x for x in rescored_list}
summary = read(V3/'runs/final-offline-rescore/summary.json')
expected_hashes = {'v2_cases_sha256':digest(V2/'cases.json'), 'v2_capture_sha256':digest(V2/'actual-inputs.json'),
                   'v2_saved_api_sha256':digest(V2/'api-score-probe-results-v2.json')}
check('exact-source-hashes', all(v3doc[k]==v for k,v in expected_hashes.items()) and summary['v2_input_hashes']==expected_hashes)
check('case-identities-24',len(v2cases)==len(v3cases)==len(capture)==24 and set(v2cases)==set(v3cases)==set(capture))
check('saved-identities-26',len(saved_list)==len(saved)==len(rescored_list)==len(rescored)==26 and set(saved)==set(rescored))
for cid, case in v3cases.items():
    old = v2cases[cid]
    for field in ('target_draft','corpus_key','target_claim_ordinal','expected_class'):
        check('unchanged-input:'+cid+':'+field,case[field]==old[field])

category_rows=[]
for identity, old in saved.items():
    row=rescored[identity]; case=v3cases[identity[0]]
    check('capture-equality:'+str(identity), normalized(old['business_request'])==normalized(capture[identity[0]]))
    check('lineage:'+str(identity),row['v3_case_id']==case['case_id'])
    check('three-layers:'+str(identity),all(k in row for k in ('raw_first','raw_repair','final_product')))
    check('no-repair:'+str(identity),old['raw_repair'] is None and row['raw_repair'] is None)
    check('raw-layer-label:'+str(identity),row['raw_first']['score_layer']=='raw_first_or_repair')
    check('final-layer-label:'+str(identity),row['final_product']['score_layer']=='final_product')
    check('no-new-api-origin:'+str(identity),'no_new_api' in row['input_origin'])
    firstfail=row['raw_first']['machine_result']=='fail'; finalfail=row['final_product']['machine_result']=='fail'
    check('same-fail-membership:'+str(identity),firstfail==finalfail)
    if finalfail:
        raw_category=old['raw_first']['issues'][0]['category']
        final_category=old['final_product']['issues'][0]['category']
        check('failure-only-old-category:'+str(identity),
              row['raw_first']['errors']==['raw_target_or_category_mismatch'] and
              row['final_product']['errors']==['category_mismatch'] and
              raw_category==final_category and final_category not in case['category_candidates'] and
              case['expected_class']=='insufficient_evidence')
        category_rows.append({'v2_record_id':identity[0], 'variant':identity[1], 'v3_case_id':case['case_id'],
                              'preserved_raw_category':raw_category, 'preserved_final_category':final_category,
                              'v3_declared_candidates':case['category_candidates']})
raw_pass=sum(x['raw_first']['machine_result']=='pass' for x in rescored_list)
final_pass=sum(x['final_product']['machine_result']=='pass' for x in rescored_list)
check('19-pass-7-fail',raw_pass==final_pass==19 and len(category_rows)==7)
check('summary-counts',summary['raw_first_machine_pass']==raw_pass and summary['final_machine_pass']==final_pass and
      summary['raw_repair_present']==0 and set(summary['category_delta_rows'])=={x['v3_case_id'] for x in category_rows})
check('zero-new-calls-summary',summary['new_api_runs']==summary['real_provider_calls']==0)

controls01=read(V3/'runs/targeted-controls-01/controls.json')
controls02=read(V3/'runs/targeted-controls-02/controls.json')
by01={x['control']:x for x in controls01['rows']}; by02={x['control']:x for x in controls02['rows']}
check('both-20-controls',len(by01)==len(by02)==20 and set(by01)==set(by02))
mutations={'raw_missing_chain':'raw_evidence_chain_mismatch',
           'raw_wrong_missing_link_role':'raw_missing_link_role_invalid',
           'raw_insufficient_edit_action':'raw_insufficient_actions_invalid',
           'raw_insufficient_memory_change':'raw_insufficient_memory_change_invalid',
           'raw_unknown_memory_id':'raw_memory_link_mismatch'}
control_rows=[]
for name, intended in mutations.items():
    first=by01[name]; second=by02[name]
    check('first-confound-preserved:'+name,'raw_target_or_category_mismatch' in first['raw_errors'] and intended in first['raw_errors'])
    check('second-isolated-target:'+name,second['actual_raw']=='fail' and intended in second['raw_errors'] and
          'raw_target_or_category_mismatch' not in second['raw_errors'] and second['required_error']==intended and
          second['raw_full_validator']=='rejected')
    control_rows.append({'control':name, 'first_errors':first['raw_errors'], 'second_errors':second['raw_errors'],
                         'second_full_validator':second['raw_full_validator']})
for name, value in [('controls01',controls01),('controls02',controls02)]:
    check(name+':in-memory-zero-new-calls',value['new_api_runs']==value['real_provider_calls']==0 and
          value['source']=='in_memory_mutations_of_saved_synthetic_v2_records')

after={p:digest(ROOT/p) for p in sorted(protected)}
check('all-protected-unchanged',after==before)
dump('hashes-after.json',after)
result={'scope':'stdlib read-only lineage comparison; no scorer/product/API/DB import or execution',
        'prior_round_protected_files_verified':len(prior), 'v3_manifest_bound_files_verified':len(manifest['source_hashes']),
        'protected_files_before_after':len(protected),'v3_manifest_sha256':digest(V3/'frozen-inputs.json'),
        'exact_v2_hashes':expected_hashes,'capture_cases':len(capture),'saved_records':len(saved),
        'raw_first_pass':raw_pass,'final_pass':final_pass,'category_failure_rows':category_rows,
        'retained_control_corrections':control_rows,'new_api_runs':0,'real_provider_calls':0,'errors':errors}
dump('lineage-results.json',result)
print(json.dumps({'capture_cases':len(capture),'saved_records':len(saved),'raw_pass':raw_pass,'final_pass':final_pass,
                  'category_failures':len(category_rows),'protected_files':len(protected),'errors':errors}))
if errors: raise SystemExit(1)
