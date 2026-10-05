"""Execute only the frozen runner's summary AST against independent synthetic event matrices."""
import ast
import json
import pathlib

HERE=pathlib.Path(__file__).resolve().parent
EVAL=HERE.parent
tree=ast.parse((EVAL/"run.py").read_text(encoding="utf-8"))
run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="run")
nodes=[n for n in run.body if 439<=n.lineno<=452]
code=compile(ast.Module(body=nodes,type_ignores=[]),str(EVAL/"run.py"),"exec")
prior=json.loads((HERE/"accounting-results.json").read_text(encoding="utf-8"))
by_case={p["case"]:p["event"] for p in prior["usage_probes"]}
scenarios=[
    ("complete",["complete"],(0,True,11,7,11,7)),
    ("missing",["absent"],(1,False,0,0,None,None)),
    ("partial_with_known_prior",["complete","input_only"],(1,False,22,7,None,None)),
    ("invalid_negative_with_known_prior",["complete","negative_input"],(1,False,11,14,None,None)),
    ("mismatch_with_known_prior",["complete","inconsistent_total"],(1,False,22,14,None,None)),
    ("zero_valid",["zero_complete"],(0,True,0,0,0,0)),
    ("no_dispatch",[],(0,False,0,0,None,None)),
]
results=[]
keys=("usage_unknown_attempts","complete_total_usage_available","known_prompt_tokens_partial_sum","known_completion_tokens_partial_sum","prompt_tokens_total","completion_tokens_total")
for label,sequence,expected in scenarios:
    captured=[]
    scope={"events":[by_case[k] for k in sequence],"run_id":"offline-only","run_dir":HERE,
           "rows":[],"failures":[],"stamp":lambda:"offline-only","write_new":lambda p,value:captured.append(value)}
    exec(code,scope)
    actual=tuple(captured[0][k] for k in keys)
    results.append({"case":label,"actual":dict(zip(keys,actual)),"expected":dict(zip(keys,expected)),"pass":actual==expected})
result={"scope":"Frozen summary AST only; fake events; no imports, HTTP, credentials or output overwrite","probes":results,"all_pass":all(r["pass"] for r in results)}
with (HERE/"accounting-summary-results.json").open("x",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps({"summary_probes":len(results),"all_pass":result["all_pass"]}))
