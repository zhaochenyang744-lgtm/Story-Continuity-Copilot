"""Independent v2 file accounting and isolated AST probes. No runner import/network/credentials/SQL."""
import ast
import collections
import copy
import hashlib
import json
import pathlib
import re
import subprocess
import time
import types

HERE = pathlib.Path(__file__).resolve().parent
EVAL = HERE.parent
ROOT = EVAL.parents[1]
RUN = EVAL / "runs/flash-v2-20260926-01"
V1 = EVAL.parent / "current_flash_v1"

def read(path): return json.loads(path.read_text(encoding="utf-8"))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
checks=[]
def check(name,actual,expected): checks.append({"name":name,"actual":actual,"expected":expected,"pass":actual==expected})

files=sorted((RUN/"cases").glob("*.json"))
records=[read(path) for path in files]
summary=read(RUN/"summary.json")
events=[e for r in records for e in r["http_attempts"]]
inputs=[q for r in records for q in r["business_requests"]]
outputs=[o for r in records for o in r["model_outputs"]]
frozen=read(EVAL/"frozen-inputs.json")
start=read(RUN/"start.json")
cases=read(EVAL/"cases.json")
case_map={c["id"]:c for group in ("g02","g03") for c in cases[group]}
check("logical_count",len(records),8)
check("case_ids_unique",len({r["case_id"] for r in records}),8)
check("family_counts",dict(collections.Counter(r["family"] for r in records)),{"g02":4,"g03":4})
check("exact_sequence_summary_http",events,summary["all_attempt_metadata"])
check("http_and_input_and_output_counts",[len(events),len(inputs),len(outputs)],[8,8,8])
check("http_ordinals",[e["ordinal"] for e in events],list(range(1,9)))
check("business_request_ordinals",[q["request_ordinal"] for q in inputs],list(range(1,9)))
check("all_complete_valid_usage",sum(e["usage_status"]=="complete" and not e["usage_invalid_fields"] and all(type(e["usage"][k]) is int and e["usage"][k]>=0 for k in ("prompt_tokens","completion_tokens","total_tokens")) and e["usage"]["total_tokens"]==e["usage"]["prompt_tokens"]+e["usage"]["completion_tokens"] for e in events),8)
check("recomputed_prompt_tokens",sum(e["usage"]["prompt_tokens"] for e in events),20844)
check("recomputed_completion_tokens",sum(e["usage"]["completion_tokens"] for e in events),5734)
check("summary_usage",[summary["prompt_tokens_total"],summary["completion_tokens_total"],summary["usage_unknown_attempts"],summary["complete_total_usage_available"]],[20844,5734,0,True])
check("http_200_no_error",sum(e["status"]==200 and e["error_type"] is None for e in events),8)
check("model_all_flash",sum(e["response_model"]=="deepseek-flash" for e in events),8)
check("actual_no_repair",sum(o["contract_repair"] for o in outputs),0)
check("exact_hash_bound_requests",sum(q["business_request_sha256"]==canonical(q["business_request"]) for q in inputs),8)
check("output_schema_hashes",sum(q["output_schema_sha256"]==canonical(q["business_request"]["output_schema"]) for q in inputs),8)
check("first_output_linked_request",sum(o["business_request_sha256"]==q["business_request_sha256"] and o["case_id"]==q["case_id"]==r["case_id"] for r in records for q,o in zip(r["business_requests"],r["model_outputs"])),8)
check("observed_output_usage_and_product_usage",sum(o["usage"]["observed_response_input_tokens"]==e["usage"]["prompt_tokens"]==r["product"]["provider_metrics"]["input_tokens"] and o["usage"]["observed_response_output_tokens"]==e["usage"]["completion_tokens"]==r["product"]["provider_metrics"]["output_tokens"] for r in records for o,e in zip(r["model_outputs"],r["http_attempts"])),8)
check("case_definition_hashes",sum(r["input_sha256"]==canonical(case_map[r["case_id"]]) for r in records),8)
check("required_request_snapshot_sections",sum(all(k in q["business_request"] for k in ("bindings","layers","retrieval","task","output_schema")) and all(k in q["business_request"]["layers"] for k in ("planned","confirmed","written")) and "draft" in q["business_request"]["layers"]["written"] and "memory_records" in q["business_request"]["layers"]["confirmed"] for q in inputs),8)
check("bound_product_identity",sum(q["business_request"]["bindings"]["project_id"]==r["product"]["project_id"] and q["business_request"]["bindings"]["draft_revision"]==r["product"]["draft_revision"] and q["business_request"]["bindings"]["memory_version"]==r["product"]["source_memory_version"] for r in records for q in r["business_requests"]),8)
check("frozen_manifest_start_binding",sha(EVAL/"frozen-inputs.json"),start["frozen_manifest_sha256"])
check("source_hashes_match",[name for name,digest in frozen["source_hashes"].items() if sha(ROOT/name)!=digest],[])
check("seed_dependency_frozen","backend/app/seed_data.py" in frozen["source_hashes"],True)
check("v1_independent_baseline_hashes",[name for name,digest in read(V1/"independent-round1/accounting-results.json")["observed_source_hashes"].items() if sha(V1/name)!=digest],[])
check("v1_all_frozen_inputs",[name for name,digest in read(V1/"frozen-inputs.json")["source_hashes"].items() if sha(ROOT/name)!=digest],[])
check("cost_unavailable",summary["cost"],"unavailable")
check("harness_exceptions",summary["failures"],[])
preflight=read(RUN/"models-preflight.json")
check("separate_models_preflight",[preflight["request"],preflight["status"],preflight["model_present"],preflight["error_type"]],["GET /models",200,True,None])

# Only the explicitly named synthetic artifact root is inspected. Read bytes for hashes, never SQL.
manifest=read(RUN/"workspace-manifest.json")
expected_root=(ROOT/"artifacts/current_flash_v2/flash-v2-20260926-01").resolve()
dbroot=pathlib.Path(manifest["root"]).resolve()
if dbroot != expected_root: raise RuntimeError("unexpected_synthetic_database_root")
check("workspace_start_binding",str(dbroot),start["local_evidence_root"])
db_results=[]
for entry in manifest["database_files"]:
    path=(dbroot/entry["path"]).resolve()
    if not path.is_relative_to(dbroot): raise RuntimeError("database_manifest_escape")
    ignored=subprocess.run(["git","check-ignore","-q","--",str(path)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    db_results.append({"path":entry["path"],"exists":path.is_file(),"bytes_match":path.stat().st_size==entry["bytes"],"sha256_match":sha(path)==entry["sha256"],"git_ignored":ignored})
check("synthetic_database_count",len(db_results),8)
check("database_hash_size_ignore",all(all(r[k] for k in ("exists","bytes_match","sha256_match","git_ignored")) for r in db_results),True)
check("database_file_inventory",sorted(str(p.relative_to(dbroot)).replace("\\","/") for p in dbroot.rglob("*.sqlite3")),sorted(e["path"] for e in manifest["database_files"]))

tree=ast.parse((EVAL/"run.py").read_text(encoding="utf-8"))
selected=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in {"usage_metadata","ObservedClient","ObservedProvider","service_failure","auth_or_model_rejection"}]
fake_response={}
fake_status=200
fake_error=None
class FakeResponse:
    @property
    def status_code(self): return fake_status
    def json(self): return fake_response
class FakeClient:
    def __init__(self,**kw): pass
    def post(self,*a,**kw):
        if fake_error: raise fake_error
        return FakeResponse()
class FakeBase:
    timeout_seconds=30
    should_raise=False
    call_observations=[]
    def __init__(self,**kw): pass
    def evaluate(self,request):
        self.call_observations.append({"snapshot_present_at_base_entry":len(self.business_requests)==1,"hash_valid_at_base_entry":self.business_requests[0]["business_request_sha256"]==canonical(request)})
        request["layers"]["confirmed"]["memory_records"][0]["value"]="mutated only in fake base"
        if self.should_raise: raise ValueError("synthetic parse failure")
        return types.SimpleNamespace(payload={"items":[]},input_tokens=11,output_tokens=7,observed_response_input_tokens=11,observed_response_output_tokens=7,cost_cny=None,latency_ms=1)
scope={"httpx":types.SimpleNamespace(Client=FakeClient,Timeout=lambda x:x),"DeepSeekProvider":FakeBase,
       "time":time,"stamp":lambda:"offline-only","copy":copy,"json":json,"hashlib":hashlib,
       "assert_business_input":lambda c,r:None}
exec(compile(ast.Module(body=selected,type_ignores=[]),str(EVAL/"run.py"),"exec"),scope)
usage_probes=[]
variants=[("absent",{},"unknown"),("null",{"usage":None},"unknown"),("empty",{"usage":{}},"unknown"),
          ("input_only",{"usage":{"prompt_tokens":11}},"partial"),
          ("missing_total",{"usage":{"prompt_tokens":11,"completion_tokens":7}},"partial"),
          ("string_input",{"usage":{"prompt_tokens":"11","completion_tokens":7,"total_tokens":18}},"partial"),
          ("negative_input",{"usage":{"prompt_tokens":-1,"completion_tokens":7,"total_tokens":6}},"partial"),
          ("boolean_input",{"usage":{"prompt_tokens":True,"completion_tokens":7,"total_tokens":8}},"partial"),
          ("float_input",{"usage":{"prompt_tokens":11.0,"completion_tokens":7,"total_tokens":18}},"partial"),
          ("inconsistent_total",{"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":19}},"partial"),
          ("complete",{"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}},"complete"),
          ("zero_complete",{"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}},"complete")]
for label,body,expected_status in variants:
    fake_response=body
    owner=types.SimpleNamespace(case_id=label,http_events=[])
    scope["ObservedClient"](owner).post("offline://no-network")
    event=owner.http_events[0]
    usage_probes.append({"case":label,"expected":expected_status,"event":event,"pass":event["usage_status"]==expected_status and (event["usage_status"]!="complete" or event["usage_invalid_fields"]==[])})
check("usage_edge_probes",sum(p["pass"] for p in usage_probes),12)

service_probes=[]
for label,status,error_code,error_type,service,auth in [
    ("evidence_quality",200,"evidence_unresolvable",None,False,False),
    ("schema_quality",200,"schema_invalid",None,False,False),
    ("http_503",503,"provider_error",None,True,False),
    ("http_429",429,"provider_error",None,True,False),
    ("auth_401",401,"provider_error",None,True,True),
    ("model_404",404,"provider_error",None,True,True),
    ("timeout",None,"provider_timeout","ReadTimeout",True,False),
    ("completed",200,None,None,False,False)]:
    record={"product":{"status":"failed" if error_code else "completed","error_code":error_code},"http_attempts":[{"status":status,"error_type":error_type}]}
    actual=scope["service_failure"](record)
    actual_auth=scope["auth_or_model_rejection"](record)
    service_probes.append({"case":label,"service":actual,"auth_or_model_stop":actual_auth,"pass":actual==service and actual_auth==auth})
counter=0
business={"product":{"status":"failed","error_code":"evidence_unresolvable"},"http_attempts":[{"status":200,"error_type":None}]}
counter_values=[]
for r in (business,business):
    counter=counter+1 if scope["service_failure"](r) else 0
    counter_values.append(counter)
check("stop_classifier_controls",sum(p["pass"] for p in service_probes),8)
check("two_business_failures_no_stop",counter_values,[0,0])

snapshot_probes=[]
for should_raise in (False,True):
    provider=scope["ObservedProvider"]()
    provider.should_raise=should_raise
    provider.call_observations=[]
    provider.case_id="offline-failure" if should_raise else "offline-success"
    original={"task":"context_brief","layers":{"confirmed":{"memory_records":[{"id":"m","value":"original synthetic fact"}]}},"output_schema":{"items":[]}}
    initial=copy.deepcopy(original)
    error=None
    try: provider.evaluate(original)
    except ValueError: error="synthetic parse failure"
    result={"raised":should_raise,"snapshot_was_present_pre_base_call":all(x["snapshot_present_at_base_entry"] and x["hash_valid_at_base_entry"] for x in provider.call_observations),
            "deep_copy_unmutated":provider.business_requests[0]["business_request"]==initial,
            "retained_request_count":len(provider.business_requests),"parsed_output_count":len(provider.parsed),"expected_exception":bool(error)==should_raise}
    result["pass"]=result["snapshot_was_present_pre_base_call"] and result["deep_copy_unmutated"] and result["retained_request_count"]==1 and result["parsed_output_count"]==(0 if should_raise else 1) and result["expected_exception"]
    snapshot_probes.append(result)
check("precall_deepcopy_success_failure_controls",sum(p["pass"] for p in snapshot_probes),2)

def walk(value,location=""):
    if isinstance(value,dict):
        for key,child in value.items():
            yield location+"/"+key,key,child
            yield from walk(child,location+"/"+key)
    elif isinstance(value,list):
        for i,child in enumerate(value): yield from walk(child,location+"/"+str(i))
sensitive=[]
for path in sorted(RUN.rglob("*.json")):
    for location,key,child in walk(read(path)):
        if key.lower() in {"authorization","api_key","password","access_token","refresh_token","session_token","raw_http_body","reasoning_content"} and child:
            sensitive.append({"file":str(path.relative_to(EVAL)),"location":location,"kind":"sensitive_field"})
        if isinstance(child,str) and (re.search(r"\bsk-[A-Za-z0-9_-]{16,}\b",child) or re.search(r"Bearer\s+\S{12,}",child)):
            sensitive.append({"file":str(path.relative_to(EVAL)),"location":location,"kind":"credential_pattern"})
check("saved_json_sensitive_scan",sensitive,[])
result={"scope":"No network, credentials, runner import, database SQL, product changes or implementation evidence changes; synthetic DB bytes only hashed within verified root",
        "checks":checks,"all_checks_pass":all(c["pass"] for c in checks),"usage_probes":usage_probes,
        "service_probes":service_probes,"precall_snapshot_probes":snapshot_probes,"database_verification":db_results,
        "observed_file_hashes":{str(p.relative_to(EVAL)):sha(p) for p in [EVAL/"run.py",EVAL/"frozen-inputs.json",*sorted(RUN.rglob("*.json"))]},
        "limitation":"Snapshot is copied into memory before the base Provider call; case/failure disk persistence is after return or caught exception, not a crash-safe pre-dispatch journal."}
with (HERE/"accounting-results.json").open("x",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps({"checks":len(checks),"all_pass":result["all_checks_pass"],"failed":[c["name"] for c in checks if not c["pass"]],"tokens":[20844,5734],"actual_http":len(events),"synthetic_databases":len(db_results)},ensure_ascii=False))
