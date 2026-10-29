"""Program-only comparison; never output sealed input strings or identifiers."""
from pathlib import Path
from difflib import SequenceMatcher
import hashlib
import json
import unicodedata

ROOT=Path(__file__).resolve().parents[1];EVAL=ROOT.parent
EXCLUDED=['eval_set_a1_reserve','eval_set_a1b_reserve','eval_set_v13_authoring','eval_set_a26_formal','eval_set_a2s6_formal','eval_set_a2n7_formal']
def norm(s):return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))
def values(v):
    out=[]
    if isinstance(v,dict):
        for k,x in v.items():
            if k in {'input','question','request'} and isinstance(x,str):out.append(norm(x))
            elif isinstance(x,(list,dict)):out.extend(values(x))
    elif isinstance(v,list):
        for x in v:out.extend(values(x))
    return out
data=json.loads((ROOT/'tasks.json').read_text(encoding='utf-8'))
new=[norm(t['request']) for t in data['tasks']]
counts=[];total=failures=comparisons=0;all_prior=set()
for name in EXCLUDED:
    directory=EVAL/name;files=sorted(directory.rglob('tasks.json')) if directory.exists() else []
    old=[]
    for p in files:old.extend(values(json.loads(p.read_text(encoding='utf-8-sig'))))
    old=sorted(set(old));bad=0
    for s in new:
        for prior in old:
            comparisons+=1
            bad+=int(s==prior or SequenceMatcher(None,s,prior,autojunk=False).ratio()>=.8)
    total+=len(old);all_prior.update(old)
    counts.append(dict(directory=name,exists=int(directory.exists()),task_files=len(files),distinct_inputs=len(old),failure_count=bad))
comparisons=len(new)*len(all_prior)
failures=sum(s==prior or SequenceMatcher(None,s,prior,autojunk=False).ratio()>=.8 for s in new for prior in all_prior)
result=dict(status='PASS' if failures==0 else 'FAIL',program_only=True,new_tasks=len(new),sealed_distinct_inputs=len(all_prior),summed_directory_distinct_inputs=total,comparisons=comparisons,failure_count=failures,directories=counts,plaintext_outputs=0,tasks_sha256=hashlib.sha256((ROOT/'tasks.json').read_bytes()).hexdigest())
(ROOT/'authoring/sealed-input-novelty-counts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({k:v for k,v in result.items() if k not in {'directories','tasks_sha256'}},ensure_ascii=False))
raise SystemExit(failures!=0)
