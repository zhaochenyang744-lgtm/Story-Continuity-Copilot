"""Read frozen assets, validate captured text, run bounded in-memory controls."""
import collections, copy, datetime, hashlib, importlib.util, json, pathlib, re, socket, sqlite3, sys
ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
TARGET = ROOT / 'evaluation/current_contract_compare_v1'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'backend'))
def forbidden(*args, **kwargs): raise RuntimeError('no_network_or_database')
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
manifest_bytes = (TARGET / 'frozen-inputs.json').read_bytes()
manifest = json.loads(manifest_bytes)
before = {p: sha((ROOT / p).read_bytes()) for p in manifest['source_hashes']}
cases = read(TARGET / 'cases.json')['cases']
capture = read(TARGET / 'actual-inputs.json')
requests = {r['case_id']: r['business_request'] for r in capture['rows']}
corpora = {p.stem: read(p) for p in (TARGET / 'corpora').glob('*.json')}
spec = importlib.util.spec_from_file_location('independent_scoring', TARGET / 'score.py')
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)
from app.engine import ContinuityEngine
engine = ContinuityEngine(object())

def payload(case, request):
    if case['expected_class'] == 'no_conflict': return {'issues': []}
    conflict = case['expected_class'] == 'conflict'
    claim = request['claims'][0]
    spans = {x['id']: x for x in claim['allowed_evidence']}
    evidence = []
    for item in case['expected_evidence']:
        sid = f"fixture-span-{case['corpus_key']}-{item['chapter_number']}"
        evidence.append({'chapter_id': spans[sid]['chapter_id'], 'span_id': sid,
                         'relation':'contradicts' if conflict else 'context',
                         'sufficiency':'sufficient' if conflict else 'insufficient',
                         'related_memory_ids':[x['id'] for x in request['memory'] if x['source_span_id']==sid]})
    temporal = {'relation':'unknown','claim_anchor':None,'evidence_anchor':None}
    if conflict:
        if case['temporal_policy']=='timeless_rule': temporal['relation']='timeless_rule'
        else:
            anchor=re.search(r'\d+点',claim['text']).group()
            temporal={'relation':'explicit_overlap','claim_anchor':anchor,'evidence_anchor':anchor}
    return {'issues':[{'claim_span_id':claim['id'],'status':'conflict' if conflict else 'insufficient_evidence',
                      'nature':'confirmed_conflict' if conflict else 'insufficient_evidence',
                      'category':case['decision_category'],'severity':'medium',
                      'explanation':'Review the supplied facts.','reasoning':case['label_reason'],
                      'temporal_basis':temporal,'evidence':evidence,
                      'evidence_chain':[{'span_id':x['span_id'],'role':'prior_state' if conflict else 'missing_link'} for x in evidence],
                      'available_actions':[],'suggested_revision':None,'proposed_memory_change':None}]}

def project(case, validated):
    return {'status':'completed','issues':[{**x,'classification':x['status'],'status':'open',
                                         'claim_text':case['target_draft']} for x in validated]}

rows, controls, validated_products = [], [], {}
for case in cases:
    req=requests[case['case_id']]
    corpus=corpora[case['corpus_key']]
    problems=[]
    if len(req['claims'])!=1 or req['claims'][0]['text']!=case['target_draft'] or req['draft']['body']!=case['target_draft']:
        problems.append('target_binding')
    span_map={f"fixture-span-{case['corpus_key']}-{c['chapter_number']}":c for c in corpus['chapters']}
    for span in req['claims'][0]['allowed_evidence']:
        canonical=span_map.get(span['id'])
        if not canonical or span['body']!=canonical['body'] or span['prompt_excerpt']!=canonical['body']:
            problems.append('selected_body_excerpt')
        elif span['chapter_id']!=f"fixture-chapter-{case['corpus_key']}-{canonical['chapter_number']}": problems.append('chapter_binding')
    allowed={x['id'] for x in req['claims'][0]['allowed_evidence']}
    for required in case['expected_evidence']:
        sid=f"fixture-span-{case['corpus_key']}-{required['chapter_number']}"
        canonical=span_map[sid]
        if sid not in allowed or sha(canonical['body'].encode())!=required['body_sha256']: problems.append('required_body_hash')
    for memory in req['memory']:
        original=corpus['memory'][int(memory['id'].rsplit('-',1)[1])-1]
        if any(memory[k]!=original[k] for k in ('memory_type','subject','predicate','value')): problems.append('memory_content')
        source=original['source']
        sid=f"fixture-span-{case['corpus_key']}-{source['chapter_number']}"
        if memory['source_span_id']!=sid or original['value']!=span_map[sid]['body']: problems.append('memory_source')
    raw=payload(case,req)
    try:
        validated=engine.validate(raw,req)
        final=project(case,validated)
        validated_products[case['case_id']]=final
        verdict='accepted'
        product_score=score.score_one(case,final)
    except ValueError as exc:
        verdict=str(exc); product_score=None
    rows.append({'case_id':case['case_id'],'input_errors':problems,'minimal_contract':verdict,'score':product_score})

def check(name, case, product, expected_not_pass=True):
    outcome=score.score_one(case,product)
    controls.append({'name':name,'case_id':case['case_id'],'expected_not_pass':expected_not_pass,
                     'result':outcome,'control_correct':(outcome['result']!='pass')==expected_not_pass})

c=next(c for c in cases if c['expected_class']=='conflict')
p=validated_products[c['case_id']]
for nature in ['possible_conflict','state_change','insufficient_evidence']:
    changed=copy.deepcopy(p);changed['issues'][0]['nature']=nature
    check('wrong_nature_'+nature,c,changed)
changed=copy.deepcopy(p);changed['issues'][0]['evidence']=[];check('missing_all_evidence',c,changed)
changed=copy.deepcopy(p);changed['issues'].append(copy.deepcopy(changed['issues'][0]));check('extra_issue',c,changed)
changed=copy.deepcopy(p);changed['issues'][0]['claim_text']='Different claim';check('wrong_claim',c,changed)
raw=payload(c,requests[c['case_id']]);check('raw_shape_not_product',c,{'status':'completed','issues':raw['issues']})
for status in ['failed','timed_out','running','cancelled']:
    nc=next(c for c in cases if c['expected_class']=='no_conflict')
    check('nonterminal_empty_'+status,nc,{'status':status,'issues':[]})

# An unrelated selected source is structurally valid, but falsely citing it as
# direct contradicting evidence must not pass a strict semantic evidence score.
req=requests[c['case_id']];raw=payload(c,req)
used={x['span_id'] for x in raw['issues'][0]['evidence']}
extra=next(x for x in req['claims'][0]['allowed_evidence'] if x['id'] not in used)
raw['issues'][0]['evidence'].append({'span_id':extra['id'],'chapter_id':extra['chapter_id'],
    'relation':'contradicts','sufficiency':'sufficient','related_memory_ids':[]})
raw['issues'][0]['evidence_chain'].append({'span_id':extra['id'],'role':'prior_state'})
extra_final=project(c,engine.validate(raw,req))
check('extra_unrelated_contradicting_source',c,extra_final)
controls[-1]['extra_source_body']=extra['body']

for field,newvalue in [('chapter_id','wrong-chapter'),('excerpt','The opposite of the source is true.')]:
    changed=copy.deepcopy(p);changed['issues'][0]['evidence'][0][field]=newvalue
    check('tampered_'+field,c,changed)

ins=next(c for c in cases if c['expected_class']=='insufficient_evidence')
req=requests[ins['case_id']];raw=payload(ins,req)
for item in raw['issues'][0]['evidence']: item['relation']='contradicts'
try:
    changed=project(ins,engine.validate(raw,req))
    check('insufficient_wrong_relation',ins,changed)
    controls[-1]['engine_validator']='accepted'
except ValueError as exc: controls.append({'name':'insufficient_wrong_relation','engine_validator':str(exc)})

# The prompt explicitly permits state_change for these later transitions.
for axis in ['character_knowledge','location_action']:
    nc=next(c for c in cases if c['decision_category']==axis and c['expected_class']=='no_conflict')
    req=requests[nc['case_id']]
    selected=req['claims'][0]['allowed_evidence']
    ev=[{'span_id':s['id'],'chapter_id':s['chapter_id'],'relation':'supports','sufficiency':'sufficient','related_memory_ids':[]}
        for s in selected if s['id'] in score.expected_span_ids(nc)]
    raw={'issues':[{'claim_span_id':req['claims'][0]['id'],'status':'conflict','nature':'state_change',
        'category':axis,'severity':'low','explanation':'The later transition is compatible with the earlier state.',
        'reasoning':'The draft explicitly states the later learning or movement; both earlier and later facts can hold.',
        'temporal_basis':{'relation':'explicit_later_transition','claim_anchor':None,'evidence_anchor':None},
        'evidence':ev,'evidence_chain':[{'span_id':e['span_id'],'role':'prior_state'} for e in ev],
        'available_actions':[],'suggested_revision':None,'proposed_memory_change':None}]}
    valid=engine.validate(raw,req)
    check('legitimate_state_change_'+axis,nc,project(nc,valid),False)
    controls[-1]['engine_validator']='accepted'

result={'scope':'Frozen candidate independent round 2; no model results',
        'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'manifest_sha256':sha(manifest_bytes),'observed_hashes':before,
        'manifest_hash_mismatches':[p for p,h in before.items() if h!=manifest['source_hashes'][p]],
        'changed_after_probe':[p for p,h in before.items() if sha((ROOT/p).read_bytes())!=h],
        'manifest_changed_after_probe':(TARGET/'frozen-inputs.json').read_bytes()!=manifest_bytes,
        'case_count':len(cases),'classes':dict(collections.Counter(c['expected_class'] for c in cases)),
        'triplets':len({(c['corpus_key'],c['axis_index']) for c in cases}),
        'corpora':len(corpora),'http_calls':0,'provider_calls':0,'database_connections':0,
        'rows':rows,'controls':controls}
with (HERE/'results.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps({'hash_mismatches':result['manifest_hash_mismatches'],'changes':result['changed_after_probe'],
    'input_pass':sum(not r['input_errors'] for r in rows),'contract_pass':sum(r['minimal_contract']=='accepted' for r in rows),
    'product_shape_pass':sum(r['score'] and r['score']['result']=='pass' for r in rows),
    'failed_controls':[x['name'] for x in controls if x.get('control_correct') is False]},ensure_ascii=True))
