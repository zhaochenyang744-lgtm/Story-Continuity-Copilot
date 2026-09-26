"""Frozen V2 gold-material inventory; no product, API, DB or Provider imports."""
import collections, datetime, hashlib, json, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[3]
HERE=pathlib.Path(__file__).resolve().parent
TARGET=ROOT/'evaluation/current_contract_compare_v2'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
names=['HANDOFF.md','RUBRIC.md','build.py','cases.json','v1-lineage.json','frozen-inputs.json',
       'corpora/north_glass.json','corpora/harbor_signal.json',
       'corpora/orchard_restoration.json','corpora/basalt_observatory.json']
raw={name:(TARGET/name).read_bytes() for name in names}
doc={name:json.loads(value.decode('utf-8')) for name,value in raw.items() if name.endswith('.json')}
cases=doc['cases.json']['cases']; manifest=doc['frozen-inputs.json']
corpora={name.split('/')[-1][:-5]:data for name,data in doc.items() if name.startswith('corpora/')}
rows=[]; memory_errors=[]
for key,corpus in corpora.items():
    spans={(x['chapter_number'],x['source_label']):x for x in corpus['chapters']}
    for memory in corpus['memory']:
        loc=(memory['source']['chapter_number'],memory['source']['source_label'])
        if loc not in spans or memory['value']!=spans[loc]['body']:memory_errors.append([key,loc])
for case in cases:
    corpus=corpora[case['corpus_key']]
    spans={(x['chapter_number'],x['source_label']):x for x in corpus['chapters']}
    errors=[]
    for e in case['expected_evidence']+case['recommended_context']+sum(case['minimum_sufficient_evidence_sets'],[]):
        c=spans[(e['chapter_number'],e['source_label'])]
        if sha(c['body'].encode())!=e['body_sha256']:errors.append(e['source_label'])
    rows.append({'case_id':case['case_id'],'class':case['expected_class'],'category':case['decision_category'],
                 'draft':case['target_draft'],'label_reason':case['label_reason'],'time_scope':case['time_scope'],
                 'allowed_outcomes':case['allowed_outcomes'],
                 'minimum_labels':[[x['source_label'] for x in es] for es in case['minimum_sufficient_evidence_sets']],
                 'optional_labels':[x['source_label'] for x in case['recommended_context']],
                 'evidence_hash_errors':errors})
result={'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':'V2 gold materials only; no capture or scorer acceptance',
        'manifest_sha256':sha(raw['frozen-inputs.json']),
        'file_hashes':{name:sha(value) for name,value in raw.items()},
        'manifest_mismatches':[name for name,value in raw.items() if name not in ['HANDOFF.md','frozen-inputs.json'] and
          manifest['source_hashes'].get('evaluation/current_contract_compare_v2/'+name)!=sha(value)],
        'changed_during_inventory':[name for name,value in raw.items() if (TARGET/name).read_bytes()!=value],
        'class_counts':dict(collections.Counter(c['expected_class'] for c in cases)),
        'triplet_count':len({(c['corpus_key'],c['axis_index']) for c in cases}),
        'corpus_count':len(corpora),'memory_source_errors':memory_errors,
        'establish_by_class':{k:sum('establish' in c['target_draft'].lower() for c in cases if c['expected_class']==k)
                              for k in ['conflict','no_conflict','insufficient_evidence']},
        'http_calls':0,'provider_calls':0,'database_connections':0,'rows':rows}
with (HERE/'material-audit-results.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps(result,ensure_ascii=False,indent=2))
