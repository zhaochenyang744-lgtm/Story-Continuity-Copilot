"""Limited V3 gold identity audit. Standard library only; immutable inputs."""
import datetime, hashlib, json, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[3]
HERE=pathlib.Path(__file__).resolve().parent
V3=ROOT/'evaluation/current_contract_compare_v3'
V2=ROOT/'evaluation/current_contract_compare_v2'
sha=lambda b:hashlib.sha256(b).hexdigest()
names=['evaluation/current_contract_compare_v3/'+n for n in
       ['HANDOFF.md','RUBRIC.md','HISTORY_GAP.md','build.py','cases.json','frozen-inputs.json']]
names+=['evaluation/current_contract_compare_v2/'+n for n in
        ['cases.json','actual-inputs.json','api-score-probe-results-v2.json','frozen-inputs.json',
         'corpora/north_glass.json','corpora/harbor_signal.json',
         'corpora/orchard_restoration.json','corpora/basalt_observatory.json']]
raw={n:(ROOT/n).read_bytes() for n in names}
doc={n:json.loads(b.decode('utf-8')) for n,b in raw.items() if n.endswith('.json')}
v3=doc['evaluation/current_contract_compare_v3/cases.json']
v2=doc['evaluation/current_contract_compare_v2/cases.json']
m3=doc['evaluation/current_contract_compare_v3/frozen-inputs.json']
m2=doc['evaluation/current_contract_compare_v2/frozen-inputs.json']
old={c['case_id']:c for c in v2['cases']}
fields=['corpus_key','target_draft','target_claim_ordinal','expected_class','expected_category',
        'expected_nature','allowed_outcomes','temporal_policy','forbidden_inference','axis_index']
changes=[];categories=[];scope_mismatches=[]
for c in v3['cases']:
    prior=old[c['lineage']['v2_case_id']]
    changed=[f for f in fields if c[f]!=prior[f]]
    if changed:changes.append({'case_id':c['case_id'],'fields':changed})
    corpus=doc['evaluation/current_contract_compare_v2/corpora/'+c['corpus_key']+'.json']
    by_chapter={x['chapter_number']:x['body'] for x in corpus['chapters']}
    minimum_texts=[by_chapter[e['chapter_number']] for e in c['minimum_sufficient_evidence_sets'][0]]
    if minimum_texts!=c['case_time_scope']['minimum_source_texts']:
        scope_mismatches.append(c['case_id'])
    if c['expected_class']=='insufficient_evidence':
        categories.append({k:c[k] for k in ['case_id','target_draft','category_axis','decision_category',
                                           'category_reason','category_policy','category_candidates']})
badge=next(c for c in v3['cases'] if c['case_id']=='ccv3-north_glass-world_rule-conflict')
result={'scope':'Incremental gold only; retains previous manual V2 semantic review',
        'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'v3_manifest_sha256':sha(raw['evaluation/current_contract_compare_v3/frozen-inputs.json']),
        'file_hashes':{n:sha(b) for n,b in raw.items()},
        'frozen_hash_mismatches':[n for n,b in raw.items() if n in m3['source_hashes'] and sha(b)!=m3['source_hashes'][n]],
        'v2_corpus_mismatches':[n for n,b in raw.items() if '/corpora/' in n and sha(b)!=m2['source_hashes'][n]],
        'case_count':len(v3['cases']),
        'all_v2_ids_once':sorted(c['lineage']['v2_case_id'] for c in v3['cases'])==sorted(old),
        'changed_business_or_classification_fields':changes,
        'conflict_categories_unchanged':all(c['decision_category']==old[c['lineage']['v2_case_id']]['decision_category']
                                          for c in v3['cases'] if c['expected_class']=='conflict'),
        'exact_frozen_v2_capture_reused':v3['v2_capture_sha256']==sha(raw['evaluation/current_contract_compare_v2/actual-inputs.json']),
        'capture_case_count':len(doc['evaluation/current_contract_compare_v2/actual-inputs.json']['rows']),
        'badge_minimum_labels':[[e['source_label'] for e in es] for es in badge['minimum_sufficient_evidence_sets']],
        'badge_expected_labels':[e['source_label'] for e in badge['expected_evidence']],
        'badge_optional_labels':[e['source_label'] for e in badge['recommended_context']],
        'badge_requires_all':badge['requires_all_expected_evidence'],
        'time_scope_minimum_text_label_mismatches':scope_mismatches,
        'insufficient_categories':categories,
        'changed_during_audit':[n for n,b in raw.items() if (ROOT/n).read_bytes()!=b],
        'provider_calls':0,'http_calls':0,'database_connections':0}
with (HERE/'incremental-results.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps(result,ensure_ascii=False,indent=2))
