"""Read-only V6 live ledger audit. Standard library, no product/DB/Provider imports."""
from __future__ import annotations

import ast
from collections import Counter
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUN_ID = "flash-v6-20260927-01"
RUN = ROOT / "evaluation/current_flash_v6/runs" / RUN_ID
EXPECTED = "f0e2cb3d5c44a1a92000f703423a0d26ea1fab5aef750b7a3393102ea98ed696"
SUPPLEMENT = "c8da7a578bfc82ddfadbe2bd9cad488a2f3c12b7e817c6a323d0cc6997b5eeec"


def lp(path):
    return Path("\\\\?\\" + str(path)) if sys.platform == "win32" and not str(path).startswith("\\\\?\\") else path


def read(path):
    return json.loads(lp(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(lp(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run_hashes():
    return {p.relative_to(RUN).as_posix(): sha(p) for p in sorted(RUN.rglob("*")) if p.is_file()}


def write(name, value):
    with lp(HERE / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)


def main():
    if not (RUN / "summary.json").exists():
        raise RuntimeError("wait_for_completed_summary")
    before = run_hashes()
    issues = []

    def check(condition, code, case_id=None):
        if not condition:
            issues.append({"code": code, "case_id": case_id})

    manifest_path = ROOT / "evaluation/current_flash_v6/frozen-inputs.json"
    supplement_path = ROOT / "docs/flash-v6-independent-acceptance-evidence/PRELAUNCH-SUPPLEMENT.json"
    manifest, supplement = read(manifest_path), read(supplement_path)
    protected = {**manifest["source_hashes"], **supplement["additional_source_hashes"]}
    protected_before = {name: sha(ROOT / name) for name in protected}
    check(sha(manifest_path) == EXPECTED and sha(supplement_path) == SUPPLEMENT, "manifest_or_supplement_digest")
    check(protected_before == protected, "frozen_or_supplement_source_drift")
    start, summary = read(RUN / "start.json"), read(RUN / "summary.json")
    prelaunch_path = ROOT / "docs/flash-v6-independent-acceptance-evidence/PRELAUNCH-RECEIPT.json"
    prelaunch = read(prelaunch_path)
    check(prelaunch["run_id"] == RUN_ID and prelaunch["manifest_sha256"] == EXPECTED and
          prelaunch["supplement_sha256"] == SUPPLEMENT and
          prelaunch["initializer_sha256"] == protected["evaluation/__init__.py"] and
          prelaunch["check_before_python_module_import"] is True and prelaunch["identity_unoccupied"] is True and
          time(prelaunch["checked_at_utc"]) < time(start["started_at"]), "prelaunch_receipt_binding")
    cases = read(ROOT / "evaluation/current_flash_v6/cases-v2.json")["cases"]
    check(start["run_id"] == RUN_ID and start["mode"] == "live" and start["case_count"] == len(cases) == 34 and
          start["frozen_manifest_sha256"] == EXPECTED and start["max_generation_post"] == 136 and start["max_models_get"] == 1,
          "run_identity_matrix_or_limits")

    # Only two pure JSON/text functions are compiled from already hashed source.
    # No product module import, Provider construction, configuration or credentials.
    tree = ast.parse(lp(ROOT / "backend/app/provider.py").read_text(encoding="utf-8"))
    pure = {"json": json, "Any": object}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {
                "CONTINUITY_PROMPT_VERSION", "CONTINUITY_REVIEW_RULES", "CONTINUITY_DECISION_EXAMPLES"}:
            pure[node.targets[0].id] = ast.literal_eval(node.value)
    for name in ("continuity_prompt", "parse_json_content"):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), "pure_audit_" + name, "exec"), pure)

    rows, all_attempts, all_evaluations = [], [], []
    finished_ordinals, product_statuses, errors, usage_counts = [], Counter(), Counter(), Counter()
    prompt_sum = completion_sum = total_sum = 0
    repairs = []
    sensitive_flags = []
    banned = {"authorization", "api_key", "access_token", "session_token", "password", "headers",
              "reasoning_content", "reasoning_details", "chain_of_thought"}

    def scan(value, path, pointer=""):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in banned:
                    sensitive_flags.append({"file": path, "field": pointer + "/" + key})
                scan(item, path, pointer + "/" + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                scan(item, path, pointer + "/" + str(index))
        elif isinstance(value, str) and (re.search(r"\bsk-[A-Za-z0-9_-]{16,}", value) or re.search(r"\bBearer\s+[A-Za-z0-9_.-]{16,}", value)):
            sensitive_flags.append({"file": path, "field": pointer, "kind": "credential_like_pattern_value_omitted"})

    for relative in before:
        if relative.endswith(".json"):
            scan(read(RUN / relative), relative)
    for case in cases:
        cid, ordinal = case["case_id"], case["ordinal"]
        folder = RUN / "cases" / f"{ordinal:02d}"
        if not folder.exists():
            rows.append({"case_id": cid, "ordinal": ordinal, "status": "not_run"})
            continue
        case_start = read(folder / "case-start.json")
        check(case_start["case_id"] == cid and case_start["run_id"] == RUN_ID and
              case_start["ordinal"] == ordinal and case_start["case_input_sha256"] == digest(case), "case_identity", cid)
        binding = read(folder / "runtime-binding.json")
        check(binding["draft_body"] == case["saved_draft"] and binding["draft_body_sha256"] == text_sha(binding["draft_body"]), "runtime_draft_digest", cid)
        sources = {s["span_id"]: s for s in binding["chapters"]}
        memories = {m["id"]: m for m in binding["memory"]}
        check(all(s["chapter_body_sha256"] == text_sha(s["chapter_body"]) and s["span_body_sha256"] == text_sha(s["span_body"]) for s in sources.values()), "runtime_source_digest", cid)
        requests = {int(p.stem): read(p) for p in sorted((folder / "requests").glob("*.json"))}
        evaluations = {int(p.stem): read(p) for p in sorted((folder / "evaluations").glob("*.json"))}
        check(set(requests) == set(evaluations) and list(requests) == list(range(1, len(requests) + 1)) and 1 <= len(requests) <= 2, "evaluation_pairing_or_bound", cid)
        prep_request = read(ROOT / "evaluation/current_flash_v6/runs/prep-v6-02/cases" / f"{ordinal:02d}" / "requests/01.json")["business_request"]
        for index, request_record in requests.items():
            request = request_record["business_request"]
            h = digest(request)
            audit = read(folder / "input-audit" / f"{index:02d}.json")
            evaluation = evaluations[index]
            check(request_record["business_request_sha256"] == h == audit["same_run_request_sha256"] == evaluation["business_request_sha256"], "request_audit_evaluation_digest", cid)
            check(audit["database_binding"] == "matched_persisted_isolated_database", "input_audit_database", cid)
            check(request["draft"]["id"] == binding["draft_id"] and request["draft"]["revision"] == binding["draft_revision"] and
                  request["draft"]["body"] == binding["draft_body"] and len(request["claims"]) == 1, "same_run_draft_identity", cid)
            for claim in request["claims"]:
                check(claim["text"] == case["saved_draft"], "full_claim", cid)
                for selected in claim["allowed_evidence"]:
                    source = sources.get(selected["id"])
                    check(source is not None and selected["chapter_id"] == source["chapter_id"] and selected["body"] == source["span_body"] and
                          source["span_revision"] == source["chapter_revision"] == binding["source_revision"], "selected_source_runtime_binding", cid)
            for selected in request["memory"]:
                memory = memories.get(selected["id"])
                check(memory is not None and all(selected.get(k) == memory[k] for k in ("memory_type", "subject", "predicate", "value", "source_span_id")) and
                      memory["source_span_id"] in sources and memory["version"] == binding["memory_version"], "selected_memory_runtime_binding", cid)
            comparable = copy.deepcopy(request)
            comparable.pop("contract_repair", None)
            for actual_claim, old_claim in zip(comparable["claims"], prep_request["claims"]):
                actual_claim["id"] = old_claim["id"]
            check(comparable == prep_request, "live_prep_business_input_drift", cid)
            if index == 1:
                check("contract_repair" not in request and request_record["stage"] == "first", "first_request_stage", cid)
            else:
                repair = request.get("contract_repair", {})
                previous = evaluations[index - 1]["parsed_business_json"]
                check(repair.get("attempt") == 2 and repair.get("rejected_issues") == (previous.get("issues", []) if isinstance(previous, dict) else []) and request_record["stage"] == "repair", "repair_first_failure_lineage", cid)
                repairs.append({"case_id": cid, "reason_code": repair.get("reason_code")})
            all_evaluations.append(evaluation)
        attempts = []
        for path in sorted((folder / "attempts").glob("*-start.json")):
            post = read(path)
            finish_path = path.with_name(path.name.replace("-start.json", "-finish.json"))
            finish = read(finish_path) if finish_path.exists() else None
            entry = {"case_id": cid, "start": post, "finish": finish}
            attempts.append(entry); all_attempts.append(entry)
            number, eval_number = post["http_ordinal_in_case"], post["evaluation_ordinal"]
            check(post["run_id"] == RUN_ID and post["case_id"] == cid and number == len(attempts) and eval_number in requests, "post_identity", cid)
            request = requests[eval_number]
            check(post["business_request_sha256"] == request["business_request_sha256"] and post["endpoint"] == "/chat/completions" and
                  time(request["recorded_before_dispatch_at"]) <= time(post["started_at"]), "pre_dispatch_snapshot", cid)
            body = {"model": "deepseek-flash", "messages": [{"role": "user", "content": pure["continuity_prompt"](request["business_request"])}],
                    "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": manifest["max_tokens"]}
            check(post["http_body_sha256"] == digest(body), "actual_http_body_digest", cid)
            if finish is None:
                usage_counts["unknown"] += 1
                continue
            check(finish["case_id"] == cid and finish["http_ordinal_in_case"] == number and time(post["started_at"]) <= time(finish["finished_at"]), "post_finish_pair", cid)
            content = finish["message_content"]
            check((content is None and finish["message_content_sha256"] is None) or isinstance(content, str) and text_sha(content) == finish["message_content_sha256"], "visible_content_digest", cid)
            usage = finish["usage"]; status = usage["status"]; values = usage["values"]
            check(status in {"complete", "missing", "partial", "unknown"}, "usage_class", cid)
            usage_counts[status] += 1
            if status == "complete":
                check(all(type(values.get(k)) is int and values[k] >= 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens")) and
                      values["prompt_tokens"] + values["completion_tokens"] == values["total_tokens"], "complete_usage_invalid", cid)
            prompt_sum += values.get("prompt_tokens") or 0
            completion_sum += values.get("completion_tokens") or 0
            total_sum += values.get("total_tokens") or 0
        check(len(attempts) <= 4 and all(sum(a["start"]["evaluation_ordinal"] == e for a in attempts) <= 2 for e in requests), "per_case_transport_bound", cid)
        for index, evaluation in evaluations.items():
            if evaluation["outcome"] != "parsed":
                continue
            parsed = []
            for attempt in attempts:
                if attempt["start"]["evaluation_ordinal"] == index and attempt["finish"] and isinstance(attempt["finish"].get("message_content"), str):
                    try:
                        parsed.append(pure["parse_json_content"](attempt["finish"]["message_content"]))
                    except (ValueError, TypeError):
                        pass
            check(bool(parsed) and parsed[-1] == evaluation["parsed_business_json"], "visible_content_to_business_parse", cid)
        finish_file = folder / "case-finish.json"
        case_finish = read(finish_file) if finish_file.exists() else None
        if case_finish:
            finished_ordinals.append(ordinal)
            check(case_finish["case_id"] == cid and case_finish["post_attempt_start_records"] == len(attempts) and case_finish["evaluation_count"] == len(evaluations), "case_finish_counts", cid)
        product_path = folder / "final-product.json"
        product = read(product_path) if product_path.exists() else None
        score = read(folder / "scores.json")
        if product:
            product_statuses[product["status"]] += 1
            if product.get("error_code"):
                errors[product["error_code"]] += 1
            check(product["draft_revision"] == binding["draft_revision"] and product["source_revision"] == binding["source_revision"] and product["source_memory_version"] == binding["memory_version"], "final_runtime_versions", cid)
            provenance = product.get("provenance") or {}
            check(provenance.get("schema_version") == "continuity-issue-v6-joint-evidence-coverage" and provenance.get("prompt_version") == "continuity-review-v16-joint-evidence-coverage", "current_v6_provenance", cid)
            if product["status"] != "completed":
                check(score["final"]["machine_result"] == "terminal_failure", "failed_product_scored_as_completed", cid)
        else:
            product_statuses["unavailable"] += 1
            check((folder / "final-product-unavailable.json").exists() and (folder / "first-failure.json").exists() and score["final"]["machine_result"] == "unscorable", "missing_final_unmarked", cid)
        service = (product or {}).get("error_code") in {"provider_unavailable", "provider_error", "provider_timeout"} or any(
            a["finish"] and (a["finish"].get("error_type") not in {None, "response_json_unavailable"} or
            a["finish"]["status"] in {400, 401, 403, 404, 429} or isinstance(a["finish"]["status"], int) and a["finish"]["status"] >= 500) for a in attempts)
        rows.append({"ordinal": ordinal, "case_id": cid, "evaluations": len(evaluations), "post_starts": len(attempts),
                     "transport_finishes": sum(a["finish"] is not None for a in attempts), "http_responses": sum(a["finish"] is not None and type(a["finish"].get("status")) is int for a in attempts),
                     "product_status": product["status"] if product else "unavailable", "product_error": product.get("error_code") if product else "product_api_exception",
                     "service_failure": service, "case_finished": case_finish is not None, "first_failure_retained": (folder / "first-failure.json").exists()})

    unfinished = sum(a["finish"] is None for a in all_attempts)
    http_responses = sum(a["finish"] is not None and type(a["finish"].get("status")) is int for a in all_attempts)
    global_numbers = [a["start"]["global_http_ordinal"] for a in all_attempts]
    check(global_numbers == list(range(1, len(all_attempts) + 1)) and len(all_attempts) <= 136, "global_dispatch_sequence_or_cap")
    models_start = read(RUN / "models-start.json") if (RUN / "models-start.json").exists() else None
    models_finish = read(RUN / "models-finish.json") if (RUN / "models-finish.json").exists() else None
    check(models_start is not None and models_finish is not None and models_finish["http_status"] == 200 and models_finish["model_present"] is True and
          time(models_start["started_at"]) <= time(models_finish["finished_at"]) < time(all_attempts[0]["start"]["started_at"]), "models_preflight_pair")
    all_complete = bool(all_attempts) and usage_counts["complete"] == len(all_attempts)
    expected_counts = {key: usage_counts[key] for key in ("complete", "missing", "partial", "unknown")}
    check(summary["run_id"] == RUN_ID and summary["logical_cases_planned"] == 34 and summary["logical_cases_finished"] == len(finished_ordinals) and
          summary["post_attempt_start_records"] == len(all_attempts) and summary["transport_attempts_finished"] == len(all_attempts) - unfinished and
          summary["http_responses_received"] == http_responses and summary["unfinished_attempt_count"] == unfinished and summary["usage_counts"] == expected_counts and
          summary["known_prompt_tokens_partial_sum"] == prompt_sum and summary["known_completion_tokens_partial_sum"] == completion_sum and
          summary["prompt_tokens_total"] == (prompt_sum if all_complete else None) and summary["completion_tokens_total"] == (completion_sum if all_complete else None), "summary_reconciliation")
    stop = (RUN / "service-stop.json").exists()
    check(summary["service_stop"] == stop, "summary_stop_marker")
    service_count = sum(row.get("service_failure", False) for row in rows)
    if not stop:
        check(len(finished_ordinals) == 34 and not any(a["finish"] and a["finish"]["status"] in {400, 401, 403, 404} for a in all_attempts) and
              not any(rows[i].get("service_failure") and rows[i+1].get("service_failure") for i in range(len(rows)-1)), "missing_required_stop_or_cases")
    after = run_hashes()
    protected_after = {name: sha(ROOT / name) for name in protected}
    check(before == after, "run_files_changed_during_read")
    check(protected_before == protected_after == protected and sha(manifest_path) == EXPECTED and sha(supplement_path) == SUPPLEMENT, "frozen_files_changed_during_read")
    check(not sensitive_flags, "sensitive_or_hidden_reasoning_flags")
    result = {"status": "independent_live_engineering_pass" if not issues else "independent_live_engineering_findings",
              "run_id": RUN_ID, "findings": issues, "logical_cases_planned": 34, "logical_cases_finished": len(finished_ordinals),
              "not_run": [c["case_id"] for c in rows if c.get("status") == "not_run"],
              "post_attempt_start_records": len(all_attempts), "transport_attempts_finished": len(all_attempts) - unfinished,
              "http_responses_received": http_responses, "http_status_counts": dict(Counter(str(a["finish"]["status"]) for a in all_attempts if a["finish"])),
              "unfinished_post_starts": unfinished, "generation_evaluations": len(all_evaluations), "contract_repairs": repairs,
              "transport_retries": len(all_attempts) - len(all_evaluations), "models_get_start_records": int(models_start is not None),
              "models_get_finish_records": int(models_finish is not None), "models_get_http_status": models_finish.get("http_status") if models_finish else None,
              "models_unfinished": models_start is not None and models_finish is None, "usage_counts": expected_counts,
              "known_prompt_tokens_partial_sum": prompt_sum, "known_completion_tokens_partial_sum": completion_sum, "known_total_tokens_partial_sum": total_sum,
              "all_dispatch_usage_complete": all_complete, "prompt_tokens_total": prompt_sum if all_complete else None,
              "completion_tokens_total": completion_sum if all_complete else None, "total_tokens": total_sum if all_complete else None,
              "cost": "unavailable_not_inferred", "service_stop": stop, "logical_service_failures": service_count,
              "product_statuses": dict(product_statuses), "product_errors": dict(errors), "case_results": rows,
              "prelaunch_receipt": {"path": str(prelaunch_path.relative_to(ROOT)), "sha256": sha(prelaunch_path), "before_run_start": True},
              "frozen_manifest_sha256": EXPECTED, "prelaunch_supplement_sha256": SUPPLEMENT,
              "protected_file_count": len(protected), "all_protected_hashes_match_before_after": protected_before == protected_after == protected,
              "run_file_count": len(before), "run_hashes_before": before, "run_hashes_after": after,
              "run_stable_during_read": before == after, "sensitive_flags": sensitive_flags,
              "audit_provider_calls": 0, "audit_database_connections": 0, "audit_network_calls": 0,
              "limits": ["Technical ledger acceptance only; semantic/model quality judged separately.",
                         "Usage independently reconciled from retained observer metadata; no cost inferred.",
                         "No product module import; pure text functions only reconstruct prompt and JSON parsing."]}
    write("live-01-engineering-review.json", result)
    with lp(HERE / "live-01-engineering-review.md").open("x", encoding="utf-8") as stream:
        stream.write("# V6 真实账本独立工程验收\n\n")
        stream.write("结论：" + ("工程账本通过。" if not issues else "存在待核发现。") + "此结论不替代语义、用户或发布验收。\n\n")
        stream.write(f"固定 {RUN_ID}：{len(finished_ordinals)}/34 逻辑案例完成；{len(all_attempts)} POST start、{len(all_attempts)-unfinished} transport finish、{http_responses} HTTP 响应；未完成 POST start {unfinished}。models GET start/finish 为 {int(models_start is not None)}/{int(models_finish is not None)}。合同修复 {len(repairs)}，transport retry {len(all_attempts)-len(all_evaluations)}。\n\n")
        stream.write(f"usage 分类 {json.dumps(expected_counts, ensure_ascii=False)}；已知 prompt {prompt_sum}、completion {completion_sum}、total {total_sum}。完整总量可用：{all_complete}；费用未推断。service-stop={stop}，逻辑服务失败={service_count}。产品状态 {json.dumps(dict(product_statuses), ensure_ascii=False)}，产品错误 {json.dumps(dict(errors), ensure_ascii=False)}，失败不计无冲突。\n\n")
        stream.write(f"逐项核对同次输入/DB 快照、请求/HTTP body/content/解析摘要、首答/repair 血缘、当前 V6 provenance、评分终态与 summary。补充 pin receipt 早于 run start。原 manifest 加 initializer 共 {len(protected)} 文件与本次 {len(before)} run 文件读取前后摘要稳定；敏感字段/隐式推理标记 {len(sensitive_flags)}。本验收 Provider、网络、DB 连接均 0。完整逐案记录与发现见同名 JSON。\n\n")
        if issues:
            stream.write("发现：" + json.dumps(issues, ensure_ascii=False) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "findings", "logical_cases_finished", "post_attempt_start_records", "unfinished_post_starts", "generation_evaluations", "transport_retries", "usage_counts", "prompt_tokens_total", "completion_tokens_total", "total_tokens", "product_statuses", "product_errors", "run_file_count", "protected_file_count")}, ensure_ascii=False))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
