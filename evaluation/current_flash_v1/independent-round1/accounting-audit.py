"""Independent local-only audit. Does not import the runner or access credentials/network/DB."""
import ast
import collections
import hashlib
import json
import pathlib
import re
import time
import types

HERE = pathlib.Path(__file__).resolve().parent
EVAL = HERE.parent
ROOT = EVAL.parents[1]
RUN = EVAL / "runs/flash-v1-20260926-01"

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def walk(value, location=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield location + "/" + key, key, child
            yield from walk(child, location + "/" + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, location + "/" + str(index))

files = sorted((RUN / "cases").glob("*.json"))
records = [read(p) for p in files]
summary = read(RUN / "summary.json")
events = [e for record in records for e in record["http_attempts"]]
outputs = [o for record in records for o in record["model_outputs"]]
frozen = read(EVAL / "frozen-inputs.json")
checks = []

def check(name, actual, expected):
    checks.append({"name": name, "actual": actual, "expected": expected, "pass": actual == expected})

check("saved_records", len(records), 48)
check("logical_run_identity_unique", len({(r["family"], r["case_id"], r.get("repeat_ordinal")) for r in records}), 48)
check("families", dict(collections.Counter(r["family"] for r in records)), {"v8": 24, "v8_stability": 6, "g01": 10, "g02": 4, "g03": 4})
check("summary_records", summary["executed_case_records"], len(records))
check("saved_http_events", len(events), 49)
check("exact_summary_event_sequence", events == summary["all_attempt_metadata"], True)
check("global_ordinals", [e["ordinal"] for e in events], list(range(1, 50)))
check("all_http_200", sum(e["status"] == 200 for e in events), 49)
check("all_complete_nonnegative_integer_usage", sum(isinstance(e.get("usage"), dict) and all(type(e["usage"].get(k)) is int and e["usage"][k] >= 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens")) for e in events), 49)
check("tokens_add_up", sum(e["usage"]["total_tokens"] == e["usage"]["prompt_tokens"] + e["usage"]["completion_tokens"] for e in events), 49)
check("prompt_tokens_recomputed", sum(e["usage"]["prompt_tokens"] for e in events), 144300)
check("completion_tokens_recomputed", sum(e["usage"]["completion_tokens"] for e in events), 8508)
check("summary_prompt_tokens", summary["known_prompt_tokens"], 144300)
check("summary_completion_tokens", summary["known_completion_tokens"], 8508)
check("current_actual_unknown_usage", sum(not isinstance(e.get("usage"), dict) or any(e["usage"].get(k) is None for k in ("prompt_tokens", "completion_tokens")) for e in events), 0)
check("summary_unknown_usage", summary["usage_unknown_attempts"], 0)
check("all_parsed_outputs_preserved", len(outputs), 49)
check("parsed_vs_http_usage_by_case", all(len(r["model_outputs"]) == len(r["http_attempts"]) and all(o["usage"]["observed_response_input_tokens"] == e["usage"]["prompt_tokens"] and o["usage"]["observed_response_output_tokens"] == e["usage"]["completion_tokens"] for o,e in zip(r["model_outputs"],r["http_attempts"])) for r in records), True)
check("model_metadata_all_flash", {e["response_model"] for e in events} == {"deepseek-flash"}, True)
check("nonempty_fingerprints", sum(bool(e["system_fingerprint"]) for e in events), 49)
check("http_errors", [e["ordinal"] for e in events if e["error_type"]], [])
check("preflight_separate", read(RUN / "models-preflight.json"), {"request": "GET /models", "status": 200, "latency_ms": 590, "model_present": True, "error_type": None})
check("freeze_file_hash_at_start", digest(EVAL / "frozen-inputs.json"), read(RUN / "start.json")["frozen_manifest_sha256"])
check("frozen_source_hashes", [name for name, expected in frozen["source_hashes"].items() if digest(ROOT / name) != expected], [])
check("only_one_repair", [(r["case_id"], [o["contract_repair"] for o in r["model_outputs"]]) for r in records if len(r["model_outputs"]) > 1], [("v8-opal-nursery-conflict-timeline", [False, True])])
check("harness_exceptions", summary["failures"], [])
check("product_failure_kept", [r["case_id"] for r in records if r.get("product",{}).get("status") == "failed"], ["g03-short-target", "g03-other-chapter"])
check("no_bill_invented", summary["cost"], "unavailable")

# Extract only the local observer class; never import runner/environment/configuration.
source = (EVAL / "run.py").read_text(encoding="utf-8")
tree = ast.parse(source)
observer = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ObservedClient")
probe_body = {}
class FakeResponse:
    status_code = 200
    def json(self): return probe_body
class FakeClient:
    def __init__(self, **kwargs): pass
    def post(self, *args, **kwargs): return FakeResponse()
scope = {"httpx": types.SimpleNamespace(Client=FakeClient, Timeout=lambda value:value),
         "DeepSeekProvider": types.SimpleNamespace(timeout_seconds=30), "time":time, "stamp":lambda:"offline-only"}
exec(compile(ast.Module(body=[observer], type_ignores=[]), str(EVAL / "run.py"), "exec"), scope)
probes = []
for label, body in [("usage_absent", {}), ("usage_empty", {"usage":{}}),
                    ("completion_missing", {"usage":{"prompt_tokens":11}}),
                    ("usage_null", {"usage":None}),
                    ("complete_control", {"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}})]:
    probe_body = body
    owner = types.SimpleNamespace(case_id=label, http_events=[])
    scope["ObservedClient"](owner).post("offline://no-network")
    e = owner.http_events[0]
    current_unknown = int(e["usage"] is None) # exact summary predicate at run.py:460
    expected_unknown = int(not isinstance(e["usage"],dict) or any(e["usage"].get(k) is None for k in ("prompt_tokens","completion_tokens")))
    probes.append({"case":label,"observed_usage":e["usage"],"error_type":e["error_type"],
                   "runner_unknown_attempts":current_unknown,"expected_unknown_attempts":expected_unknown,
                   "pass":current_unknown==expected_unknown})

forbidden_keys = {"authorization", "api_key", "password", "session_token", "refresh_token", "access_token", "raw_response", "raw_http_body", "reasoning_content"}
suspicious = []
for path in sorted(RUN.rglob("*.json")):
    value = read(path)
    for location, key, child in walk(value):
        if key.lower() in forbidden_keys and child:
            suspicious.append({"file":str(path.relative_to(EVAL)),"json_path":location,"kind":"sensitive_key"})
        if isinstance(child,str) and (re.search(r"\bsk-[A-Za-z0-9_-]{16,}\b",child) or re.search(r"Bearer\s+\S{12,}",child)):
            suspicious.append({"file":str(path.relative_to(EVAL)),"json_path":location,"kind":"credential_pattern"})
check("saved_json_sensitive_field_or_pattern_scan", suspicious, [])
check("no_runtime_database_in_eval", [str(p.relative_to(EVAL)) for p in EVAL.rglob("*") if p.is_file() and p.suffix.lower() in {".db",".sqlite",".sqlite3"}], [])

snapshot = [{"case_id":r["case_id"],"family":r["family"],"product_present":"product" in r,
             "first_input_keys":sorted(r["model_outputs"][0]["input_refs"]) if r["model_outputs"] else [],
             "product_keys":sorted(r.get("product",{})),"product_source_keys":sorted(r.get("product",{}).get("source_catalog",{})) if isinstance(r.get("product",{}).get("source_catalog"),dict) else None}
            for r in records if r["family"] in {"g02","g03","v8_stability"}]
result = {"scope":"Independent file/accounting audit plus isolated fake observer probes; no Provider/network/credential/DB access",
          "checks":checks,"all_current_run_checks_pass":all(c["pass"] for c in checks),
          "missing_usage_observer_probes":probes,"snapshot_inventory":snapshot,
          "observed_source_hashes":{str(p.relative_to(EVAL)):digest(p) for p in [EVAL/"run.py",EVAL/"frozen-inputs.json",*sorted(RUN.rglob("*.json"))]}}
with (HERE / "accounting-results.json").open("x",encoding="utf-8") as f:
    json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps({"current_run_checks":len(checks),"current_run_pass":result["all_current_run_checks_pass"],
                  "failed_current_checks":[c["name"] for c in checks if not c["pass"]],
                  "missing_usage_probe_failures":[p["case"] for p in probes if not p["pass"]],
                  "total_http":len(events),"total_logical_records":len(records)},ensure_ascii=False))
