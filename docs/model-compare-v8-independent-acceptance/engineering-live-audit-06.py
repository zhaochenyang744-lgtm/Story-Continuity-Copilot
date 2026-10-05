"""Read-only V8 live ledger and history audit. Standard library only."""
import ast
import copy
import hashlib
import json
import math
import pathlib
import re
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC = pathlib.Path(__file__).resolve().parent
RUN = ROOT / "evaluation/model_compare_v8/runs/model-compare-v8-20260927-01"
MANIFEST = ROOT / "evaluation/model_compare_v8/frozen-inputs.json"
PIN = "c99e007f026aa95c19fecdb15caf3f96ccd141673bc1c2b2b30d3b140975370a"
OUTPUT = DOC / "engineering-live-review-06.json"
if OUTPUT.exists():
    raise FileExistsError("independent_live_review_identity_already_exists")

def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()

def digest(value):
    return sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())

paths = sorted(p for p in RUN.rglob("*") if p.is_file())
raw_files = {p: p.read_bytes() for p in paths}
before = {p.relative_to(ROOT).as_posix(): sha_bytes(data) for p, data in raw_files.items()}
hash_cache = {p.resolve(): sha_bytes(data) for p, data in raw_files.items()}
parsed = {}

def file_hash(path):
    path = path.resolve()
    if path not in hash_cache:
        hash_cache[path] = sha_bytes(path.read_bytes())
    return hash_cache[path]

def read(path):
    if path not in parsed:
        parsed[path] = json.loads(raw_files[path].decode("utf-8") if path in raw_files else path.read_text(encoding="utf-8"))
    return parsed[path]

findings = []
checks = 0

def check(value, name):
    global checks
    checks += 1
    if not value:
        findings.append(name)

manifest = read(MANIFEST)
check(file_hash(MANIFEST) == PIN, "manifest_pin")
check(len(manifest["source_hashes"]) == 443, "source_count_443")
check(len(manifest["runtime"]["files"]) == 253, "runtime_count_253")

def verify_map(mapping, absolute=False):
    mismatch = []
    for name, expected in mapping.items():
        path = pathlib.Path(name) if absolute else ROOT / name
        if not path.is_file() or file_hash(path) != expected:
            mismatch.append(name)
    return {"files": len(mapping), "matched": len(mapping)-len(mismatch), "mismatches": mismatch}

protection = {
    "v8_sources": verify_map(manifest["source_hashes"]),
    "v8_runtime": verify_map(manifest["runtime"]["files"], True),
}
baseline_path = DOC / "baseline-v7-preservation-01.json"
baseline = read(baseline_path)
check(file_hash(ROOT / baseline["manifest_path"]) == baseline["manifest_sha256"], "v7_manifest_preserved")
protection["v7_product"] = verify_map(baseline["product_hashes"])
protection["v7_frozen_sources"] = verify_map(baseline["frozen_source_hashes"])
protection["v7_run"] = verify_map(baseline["v7_run_file_hashes"])
v7_run_root = ROOT / "evaluation/current_flash_v7/runs/flash-v7-20260927-01"
check({p.relative_to(ROOT).as_posix() for p in v7_run_root.rglob("*") if p.is_file()} == set(baseline["v7_run_file_hashes"]), "v7_run_inventory_375")
for name, result in protection.items():
    check(not result["mismatches"], "preservation:"+name)

plan = read(RUN / "plan.json")
start = read(RUN / "start.json")
summary = read(RUN / "summary.json")
check(start["manifest_sha256"] == PIN, "run_manifest_binding")
check(start["limits"] == manifest["limits"] == plan["limits"], "limits_binding")
check(start["conditions"] == manifest["conditions"] == plan["conditions"], "conditions_binding")
check(plan == read(ROOT / "evaluation/model_compare_v8/runs/prep-v8-01/plan.json"), "plan_equals_frozen_prep")
conditions = {c["id"]: c for c in manifest["conditions"]}
check(set(conditions) == {"flash-off", "flash-high", "pro-high"}, "three_conditions")
check(len(plan["cases"]) == 34 and len(plan["schedule"]) == 102, "matrix_34_102")
expected_schedule = []
arm_order = list(conditions)
for case in plan["cases"]:
    n = case["ordinal"]
    order = arm_order[(n-1)%3:] + arm_order[:(n-1)%3]
    for position, arm in enumerate(order, 1):
        expected_schedule.append({"dispatch_order": len(expected_schedule)+1, "case_ordinal": n,
            "case_id": case["case_id"], "condition_id": arm, "position_in_case": position})
check(plan["schedule"] == expected_schedule, "case_major_rotation")
check(len({(x["case_ordinal"], x["condition_id"]) for x in plan["schedule"]}) == 102, "unique_matrix_identities")

models_start = read(RUN / "models-start.json")
models_finish = read(RUN / "models-finish.json")
check(models_start["get_ordinal"] == 1 and models_start["endpoint"] == "/models", "one_models_get_start")
check(models_finish["http_status"] == 200 and models_finish["required_models_available"], "models_get_success")
check({x["id"] for x in models_finish["models"]} == {"deepseek-flash", "deepseek-v4-pro"}, "models_available")
check(models_finish["finished_at"] <= min(read(RUN / "cases" / f"{r['case_ordinal']:02d}" / r["condition_id"] / "trial-start.json")["started_at"] for r in plan["schedule"]), "models_before_trials")

# Read only a literal/f-string instruction from the frozen AST; execute no product code.
tree = ast.parse((ROOT / "backend/app/provider.py").read_text(encoding="utf-8"))
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "continuity_prompt")
instruction_node = next(v for node in ast.walk(function) if isinstance(node, ast.Dict)
                        for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant) and k.value == "instruction")
def literal_text(node):
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.JoinedStr):
        return "".join(literal_text(x) for x in node.values)
    if isinstance(node, ast.FormattedValue) and isinstance(node.value, ast.Name) and node.value.id == "MAX_CLAIM_BASIS_CODEPOINTS":
        return "400"
    raise ValueError("unsupported_literal_instruction")
repair_instruction = literal_text(instruction_node)

rows = []
all_attempts = []
statuses = Counter()
usage_classes = Counter()
finish_reasons = Counter()
reasoning_detail = Counter()
repair_reason = Counter()
score_errors = 0
cross_case = {}
for item in plan["schedule"]:
    n, arm = item["case_ordinal"], item["condition_id"]
    tag = f"{n:02d}/{arm}"
    folder = RUN / "cases" / f"{n:02d}" / arm
    try:
        begun = read(folder / "trial-start.json")
        done = read(folder / "trial-finish.json")
        final = read(folder / "engine-final.json")
        scores = read(folder / "scores.json")
        check(all(begun[k] == v for k, v in item.items()), tag+":identity")
        check(begun["condition"] == conditions[arm], tag+":condition")
        check(done["budget_restored_to"] == 8000 and final["original_engine_budget"] == 8000 and final["effective_engine_budget"] == 40000, tag+":budget_restore")
        check(final["experiment_only"] is True and final["usage_substituted"] is False and final["output_layer"] == "engine_not_api_or_database", tag+":experiment_disclosure")
        check(done["status"] == final["status"] and done["error_code"] == final.get("error_code"), tag+":final_status_binding")
        statuses[final["status"]] += 1
        requests = [read(p) for p in sorted((folder / "requests").glob("*.json"))]
        wires = [read(p) for p in sorted((folder / "wire").glob("*.json"))]
        evaluations = [read(p) for p in sorted((folder / "evaluations").glob("*.json"))]
        attempts_start = [read(p) for p in sorted((folder / "attempts").glob("*-start.json"))]
        attempts_finish = [read(p) for p in sorted((folder / "attempts").glob("*-finish.json"))]
        check(len(requests) == len(wires) == len(evaluations) == done["evaluation_count"] <= 2, tag+":evaluation_count")
        check(len(attempts_start) == len(attempts_finish) == done["post_count"] <= 4, tag+":attempt_pairs")
        check(len(attempts_start) == len(evaluations), tag+":no_transport_retry_observed")
        prepared = read(ROOT / "evaluation/current_flash_v7/runs/prep-v7-01/cases" / f"{n:02d}" / "requests/01.json")
        first = requests[0]["business_request"]
        check(first == prepared["business_request"] and digest(first) == plan["input_hashes"][str(n)], tag+":first_exact_input")
        first_payload = json.loads(wires[0]["http_json_body"]["messages"][0]["content"])
        prior = cross_case.setdefault(n, (first, wires[0]["http_json_body"]["messages"]))
        check(prior == (first, wires[0]["http_json_body"]["messages"]), tag+":cross_arm_business_and_prompt")
        for index, (request, wire, evaluation) in enumerate(zip(requests, wires, evaluations), 1):
            req = request["business_request"]
            body = wire["http_json_body"]
            condition = conditions[arm]
            check(body["model"] == condition["model"] and body["thinking"] == {"type": condition["thinking"]}, tag+":wire_model_thinking")
            check(body.get("reasoning_effort") == condition["reasoning_effort"] and ("reasoning_effort" in body) == (arm != "flash-off"), tag+":wire_effort")
            check(body.get("temperature") == condition["temperature"] and ("temperature" in body) == (arm == "flash-off"), tag+":wire_temperature")
            check(body["max_tokens"] == 32768 and "top_p" not in body and body["response_format"] == {"type": "json_object"}, tag+":wire_limits")
            check(len(body["messages"]) == 1 and body["messages"][0]["role"] == "user", tag+":one_user_message")
            check(wire["request_body_sha256"] == digest(body), tag+":wire_hash")
            check(request["business_request_sha256"] == evaluation["business_request_sha256"] == digest(req), tag+":business_hash")
            prompt = body["messages"][0]["content"]
            ascii_count = sum(ord(char) < 128 for char in prompt)
            estimate = math.ceil(ascii_count/4) + math.ceil((len(prompt)-ascii_count)*1.25) + 256
            check(estimate <= 6000, tag+":complete_input_estimate")
            payload = json.loads(prompt)
            if index == 1:
                frozen_wire = read(ROOT / "evaluation/model_compare_v8/runs/prep-v8-01/cases" / f"{n:02d}" / arm / "wire.json")
                check(body == frozen_wire["http_json_body"], tag+":wire_equals_frozen_prep")
            else:
                repair = req["contract_repair"]
                repair_reason[repair["reason_code"]] += 1
                stripped = {k:v for k,v in req.items() if k != "contract_repair"}
                check(stripped == first, tag+":repair_business_fixed")
                raw_first = evaluations[index-2]["parsed_business_json"]
                check(repair["rejected_issues"] == raw_first.get("issues",[]) and repair["rejected_claim_verdicts"] == raw_first.get("claim_verdicts",[]), tag+":full_rejected_fields")
                check(repair["attempt"] == index and isinstance(repair["diagnostics"],list) and bool(repair["diagnostics"]), tag+":repair_diagnostics")
                expected_payload = copy.deepcopy(first_payload)
                expected_payload["contract_repair"] = {**repair, "instruction": repair_instruction}
                check(payload == expected_payload, tag+":full_repair_wire")
            own = [x for x in attempts_finish if x["evaluation"] == index]
            check(len(own) == 1, tag+":one_response_per_evaluation")
            actual = own[-1]
            content = actual["visible_content"]
            check(evaluation["outcome"] == "parsed" and json.loads(content) == evaluation["parsed_business_json"], tag+":raw_equals_parsed")
            check(actual["usage"] == evaluation["usage"] and actual["finish_reason"] == evaluation["finish_reason"], tag+":evaluation_receipt")
        for a, b in zip(attempts_start, attempts_finish):
            check(a["evaluation"] == b["evaluation"] and a["trial_post_ordinal"] == b["trial_post_ordinal"], tag+":attempt_identity")
            check(a["request_body_sha256"] == wires[a["evaluation"]-1]["request_body_sha256"], tag+":attempt_wire_hash")
            check(wires[a["evaluation"]-1]["created_at"] <= a["started_at"] <= b["finished_at"] <= done["finished_at"], tag+":durability_order")
            check(a["condition"] == conditions[arm], tag+":attempt_condition")
            check(b["http_status"] == 200 and b["error_type"] is None, tag+":http_success")
            check(b["response_model"] == conditions[arm]["model"], tag+":response_model")
            finish_reasons[str(b["finish_reason"])] += 1
            content = b["visible_content"]
            check(sha_bytes(content.encode()) == b["visible_content_sha256"], tag+":content_hash")
            usage = b["usage"]; values = usage["raw_usage"]
            usage_classes[usage["status"]] += 1
            check(usage["status"] == "complete", tag+":usage_complete")
            check(all(type(values.get(k)) is int and values[k] >= 0 for k in ("prompt_tokens","completion_tokens","total_tokens")), tag+":usage_integer")
            check(values["prompt_tokens"] + values["completion_tokens"] == values["total_tokens"], tag+":usage_sum")
            check(all(usage[k] == values[k] for k in ("prompt_tokens","completion_tokens","total_tokens")), tag+":usage_projection")
            detail = usage["reasoning_tokens"]
            reasoning_detail[usage["reasoning_tokens_status"]] += 1
            check(detail is None or type(detail) is int and 0 <= detail <= usage["completion_tokens"], tag+":reasoning_subcount")
            check(usage["original_8000_compatible"] == (values["total_tokens"] <= 8000) and usage["experimental_40000_compatible"] == (values["total_tokens"] <= 40000), tag+":compatibility")
            check(b["reasoning_body_persisted"] is False and "reasoning_content" not in b, tag+":reasoning_not_persisted")
            check(b["reasoning"]["present"] == (arm != "flash-off"), tag+":thinking_metadata")
            if b["reasoning"]["present"]:
                check(b["reasoning"]["codepoints"] > 0 and b["reasoning"]["utf8_bytes"] >= b["reasoning"]["codepoints"] and len(b["reasoning"]["sha256"]) == 64, tag+":reasoning_metadata_shape")
            all_attempts.append({"tag":tag,"start":a,"finish":b})
        total_input = sum(r["usage"]["prompt_tokens"] for r in attempts_finish)
        total_output = sum(r["usage"]["completion_tokens"] for r in attempts_finish)
        check(final.get("input_tokens") == total_input and final.get("output_tokens") == total_output, tag+":engine_usage")
        check(scores["first"] is not None and len(scores["repair"]) == len(evaluations)-1, tag+":separate_scores")
        score_errors += sum(r.get("machine_result") == "score_error" for r in [scores["first"], *scores["repair"], scores["final"]])
        rows.append({"case_ordinal":n,"condition_id":arm,"status":final["status"],"error_code":final.get("error_code"),
            "evaluations":len(evaluations),"posts":len(attempts_finish),"input_tokens":total_input,"completion_tokens":total_output,
            "total_tokens":total_input+total_output,"normalizations":final.get("contract_normalization_count",0),
            "original_8000_exceeded_responses":sum(not r["usage"]["original_8000_compatible"] for r in attempts_finish)})
    except Exception as error:
        findings.append(tag+":audit_read_or_shape_error:"+type(error).__name__)

all_attempts.sort(key=lambda x:x["start"]["global_post_ordinal"])
known = 0
for index, row in enumerate(all_attempts,1):
    a,b = row["start"],row["finish"]
    admission = a["admission"]
    check(a["global_post_ordinal"] == index and admission["post_count_before"] == index-1, "global_dispatch_sequence")
    check(admission["known_tokens_before"] == known and admission["unknown_dispatch_count_before"] == 0, "pre_dispatch_known_ledger")
    check(admission["remaining_known_token_allowance"] == 1500000-known and known < 1500000 and index <= 408, "cap_before_dispatch")
    if index > 1:
        check(all_attempts[index-2]["finish"]["finished_at"] <= a["started_at"], "serial_dispatch")
    known += b["usage"]["total_tokens"]

check(len(all_attempts) == 113 == summary["post_attempts"], "113_posts")
check(known == 561855 == summary["known_total_tokens"] == summary["tokens_total"], "known_tokens_561855")
check(len(rows) == 102 == summary["condition_cases_finished"], "102_trial_finishes")
check(summary["unknown_dispatches"] == 0 and summary["stop_reason"] is None, "no_unknown_or_service_stop")
check(summary["condition_cases_not_run"] == 0 and read(RUN / "not-run.json")["condition_cases"] == [], "not_run_zero")
check(summary["common_finished_cases"] == list(range(1,35)) and all(v == list(range(1,35)) for v in summary["coverage"].values()), "full_paired_coverage")
check(summary["models_get_count"] == 1 and summary["engine_budget_restored_to"] == 8000, "summary_get_restore")
check(sum(r["evaluations"]-1 for r in rows) == 11, "11_repairs")
check(score_errors == 0, "no_score_error")
check(finish_reasons == {"stop":113}, "all_finish_stop")

privacy_flags = []
for path, content in raw_files.items():
    if path.suffix != ".json":
        continue
    value = read(path)
    def inspect(obj):
        if isinstance(obj,dict):
            for key,item in obj.items():
                if key.lower() in {"authorization","api_key","reasoning_content","deepseek_api_key","continuity_api_key"}:
                    privacy_flags.append({"file":path.relative_to(ROOT).as_posix(),"flag":"prohibited_key"})
                inspect(item)
        elif isinstance(obj,list):
            for item in obj:inspect(item)
        elif isinstance(obj,str) and re.search(r"(?:Bearer\s+[A-Za-z0-9_-]{16,}|\bsk-[A-Za-z0-9_-]{20,})",obj):
            privacy_flags.append({"file":path.relative_to(ROOT).as_posix(),"flag":"credential_pattern"})
    inspect(value)
check(not privacy_flags, "no_sensitive_logging_markers")
after = {p.relative_to(ROOT).as_posix():sha_bytes(p.read_bytes()) for p in paths}
check(before == after, "run_read_hashes_stable")
check({p.relative_to(ROOT).as_posix() for p in RUN.rglob("*") if p.is_file()} == set(before), "run_inventory_stable")
check(sha_bytes(MANIFEST.read_bytes()) == PIN, "manifest_after")

report = {
    "review":"engineering-live-review-06", "created_at":datetime.now(timezone.utc).isoformat(),
    "decision":"technical_pass" if not findings else "technical_findings", "findings":findings, "checks":checks,
    "manifest_sha256":PIN, "baseline_sha256":file_hash(baseline_path), "protection":protection,
    "totals":{"condition_cases":len(rows),"trial_statuses":dict(statuses),"post_starts":len(all_attempts),"post_finishes":len(all_attempts),
        "unfinished":sum(len(list((RUN/'cases'/f"{x['case_ordinal']:02d}"/x['condition_id']/'attempts').glob('*-start.json')))-len(list((RUN/'cases'/f"{x['case_ordinal']:02d}"/x['condition_id']/'attempts').glob('*-finish.json'))) for x in plan['schedule']),
        "models_get":1,"input_tokens":sum(r['input_tokens'] for r in rows),"completion_tokens":sum(r['completion_tokens'] for r in rows),
        "total_tokens":known,"repairs":sum(r['evaluations']-1 for r in rows),"repair_reasons":dict(repair_reason),
        "usage_classes":dict(usage_classes),"finish_reasons":dict(finish_reasons),"reasoning_token_detail":dict(reasoning_detail),
        "score_errors":score_errors,"not_run":summary['condition_cases_not_run'],"stop_reason":summary['stop_reason'],
        "known_token_cap_overshoot":max(0,known-1500000),"original_8000_exceeded_responses":sum(r['original_8000_exceeded_responses'] for r in rows),
        "normalizations":sum(r['normalizations'] for r in rows),"cost":summary['cost'],"cost_status":summary['cost_status']},
    "trials":rows,"privacy_flags":privacy_flags,"run_files":len(before),"run_file_hashes":before,
    "run_inventory_sha256_before":digest(before),"run_inventory_sha256_after":digest(after),"run_read_hashes_stable":before==after,
    "semantic_reviews_locked_before_engineering_audit":True,"real_provider_calls":0,"database_connections":0,
    "product_or_scorer_execution":False,"script_sha256":sha_bytes(pathlib.Path(__file__).read_bytes()),
    "limits":["Technical audit is not semantic, user or release acceptance.","Original 8000 compatibility is per-response, not production E2E.","HTTPX 120 seconds is a phase timeout, not a hard wall-clock deadline.","Privacy scan checks prohibited structured fields and credential patterns; no secrets or hidden reasoning are emitted."]}
with OUTPUT.open("x",encoding="utf-8",newline="\n") as handle:
    json.dump(report,handle,ensure_ascii=False,indent=2)
    handle.write("\n")
print(json.dumps({"decision":report['decision'],"findings":findings,"checks":checks,"totals":report['totals'],"run_files":len(before),"protected":{k:v['matched'] for k,v in protection.items()},"report_sha256":sha_bytes(OUTPUT.read_bytes())},ensure_ascii=False))
raise SystemExit(0 if not findings else 1)
