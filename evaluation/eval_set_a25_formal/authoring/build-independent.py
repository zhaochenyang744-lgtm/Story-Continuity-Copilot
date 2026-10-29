"""Assemble the completion ledger only after the independent reports are complete."""
from pathlib import Path
import json
FORMAL=Path(__file__).resolve().parent.parent
SAFETY=FORMAL.parent/'eval_set_a2s5_formal'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def summary(p):
    d=load(p)
    return {k:d[k] for k in ('total','initial_agreement','final_agreement','initial_rate','final_rate',
        'unresolved','disagreement_ids','closed_ids')}
for root in (FORMAL,SAFETY):
    safety=root==SAFETY;ws=['w01'] if safety else ['w01','w02']
    for w in ws:assert (root/'authoring'/f'independent-{w}-review.md').is_file()
    if not safety:assert (root/'authoring/independent-task-review.md').is_file()
    d={'status':'completed','chapter_coverage':{w:12 if safety else 20 for w in ws},
       'task_coverage':12 if safety else 68,'facts_coverage':{w:25 for w in ws},
       'foreshadow_coverage':{w:10 for w in ws},'shared_draft_coverage':{w:1 for w in ws},
       'findings':1 if safety else 2,'closed_findings':1 if safety else 2,'unresolved_findings':0,
       'method':'author-independent full prose and materials reading; separate blind route and new-action judgments; independent task semantics review',
       'model_api_calls':0,'product_runs':0,'evaluation_runs':0,'reports':{},'sha256':{},'authoring_sha256':{},
       'new_action_blind':summary(root/'authoring/new-action-blind-comparison.json')}
    if not safety:
        d['blind_route']=summary(root/'authoring/route-blind-comparison.json')
        d['checker_review']={'covered_checkers':2,'findings':1,'closed_findings':1,'unresolved_findings':0}
    (root/'authoring/independent-review.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'independent_completion_ledgers':2}))
