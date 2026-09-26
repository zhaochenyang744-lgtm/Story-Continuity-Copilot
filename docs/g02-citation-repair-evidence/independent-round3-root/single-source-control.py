import copy,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from evaluation.current_contract_compare_v2.score import score_one,score_raw_one
HERE=pathlib.Path(__file__).resolve().parent
case=next(x for x in json.loads((ROOT/'evaluation/current_contract_compare_v2/cases.json').read_text(encoding='utf-8'))['cases'] if x['decision_category']=='world_rule' and x['expected_class']=='conflict')
row=next(x for x in json.loads((ROOT/'evaluation/current_contract_compare_v2/api-score-probe-results-v2.json').read_text(encoding='utf-8'))['rows'] if x['case_id']==case['case_id'])
source=next(x for x in row['business_request']['claims'][0]['allowed_evidence'] if x['label']=='badge_rule')
product=copy.deepcopy(row['product']);raw=copy.deepcopy(row['raw_first'])
for response in (product,raw):
    issue=response['issues'][0]
    issue['evidence']=[e for e in issue['evidence'] if e['span_id']==source['id']]
    ids={e.get('id',e['span_id']) for e in issue['evidence']}
    issue['evidence_chain']=[e for e in issue['evidence_chain'] if e.get('evidence_id',e.get('span_id')) in ids]
out={'case_id':case['case_id'],'draft':case['target_draft'],'single_source':source['prompt_excerpt'],'rationale_in_case':case['label_reason'],'raw_score':score_raw_one(case,raw,row['business_request']),'final_score':score_one(case,product,row['business_request']),'human_root_judgment':'Draft itself specifies red-only; badge_rule forbids red-only opening. The roster is corroborating context, not required to refute this draft. The conflict gold remains sound, but the mandatory minimum is unnecessarily strict.','provider_calls':0}
with (HERE/'single-source-control.json').open('x',encoding='utf-8') as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False))

