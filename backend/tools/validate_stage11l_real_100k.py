"""Validate the redacted, one-shot Stage 11L-B formal result."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_SHA256 = "01b7cb6ca01c86a56e69bd5c897efc0f377b32b8da4b4274c326a9135b437af1"
LEGACY_V1_RESULT_SHA256 = "9694af5e91499ac7cb087438f76fba36605c7bfb675a96997e6eeca0e836a645"
LEGACY_V2_RESULT_SHA256 = "813241394661b85a49391210ac9ab6938f1128e08ec8cc937ea83c7d036ff766"
LEGACY_V3_RESULT_SHA256 = "2b595bed75697807d68f895689067aa43a9209e4df31a4e482f77918798dfef1"
LEGACY_V4_RESULT_SHA256 = "f33f12ade1ba45fd78c15bbf54491e498683cce5dd48ec769b93ae76bc81102a"
LEGACY_V5_RESULT_SHA256 = "e3155bca4fbebdb37250011a5e121ff9c2cca7cc19de138f6c2ac2da9547323c"
OBSERVABILITY_CONTRACT_VERSION = "stage11l-failure-v5"
CURRENT_EVIDENCE_ID = "real-novel-100k-11l-v6"
REQUIRED_PROVIDER_MODEL = "deepseek-v4-pro"
LEGACY_RESULT_HASHES = {"real-novel-100k-11l-v1":LEGACY_V1_RESULT_SHA256,"real-novel-100k-11l-v2":LEGACY_V2_RESULT_SHA256,"real-novel-100k-11l-v3":LEGACY_V3_RESULT_SHA256,"real-novel-100k-11l-v4":LEGACY_V4_RESULT_SHA256,"real-novel-100k-11l-v5":LEGACY_V5_RESULT_SHA256}
ENGINE_FAILURE_CODES = {"input_budget_exceeded","provider_unavailable","provider_timeout","invalid_json","provider_error","provider_model_not_pro","budget_paused","schema_invalid","evidence_unresolvable","top_level_shape_invalid","candidate_collection_invalid","candidate_count_invalid","empty_candidates","candidate_fields_invalid","candidate_value_invalid","memory_type_invalid","required_field_type_invalid","required_field_blank","candidate_length_invalid"}
FAILURE_PHASES = {"provider_preflight","batch_planning","provider_request","post_response_decode","post_response_budget","post_response_validation","post_aggregation","incremental_review"}
FORBIDDEN_RESULT_KEYS = {"source_text","source_path","prompt","raw_provider_body","api_key","secret"}


def contains_forbidden_result_key(value:object)->bool:
    if isinstance(value,dict):
        return any(key in FORBIDDEN_RESULT_KEYS or contains_forbidden_result_key(item) for key,item in value.items())
    if isinstance(value,list):return any(contains_forbidden_result_key(item) for item in value)
    return False


def valid_repair_events(events:object,count:object,*,completed:bool)->bool:
    if not isinstance(count,int) or isinstance(count,bool) or not 0<=count<=5 or not isinstance(events,list) or len(events)!=count:return False
    if [event.get("attempt") for event in events] != list(range(1,count+1)):return False
    by_batch={}
    for event in events:
        if not isinstance(event,dict) or event.get("result") not in {"succeeded","failed","provider_failed"}:return False
        batch=event.get("batch_ordinal"); batch_attempt=event.get("batch_attempt")
        if not isinstance(batch,int) or isinstance(batch,bool) or batch<1 or batch_attempt not in {1,2}:return False
        by_batch.setdefault(batch,[]).append(event)
    for batch_events in by_batch.values():
        if [event["batch_attempt"] for event in batch_events] != list(range(1,len(batch_events)+1)):return False
        if len(batch_events)>2:return False
        if completed and (batch_events[-1]["result"]!="succeeded" or any(event["result"]!="failed" for event in batch_events[:-1])):return False
    return True


def validate_result(data:dict,raw_sha256:str)->bool:
    if contains_forbidden_result_key(data):return False
    passed = (
        data.get("stage") == "11L-B"
        and data.get("status") in {"completed_pending_independent_gate", "gate_failed"}
        and data.get("frozen_sample_hash_contract") == "utf-8-sig decode; text[:100000]; UTF-8 encode"
        and data.get("expected_frozen_sample_sha256") == EXPECTED_SHA256
        and data.get("actual_frozen_sample_sha256") == EXPECTED_SHA256
        and data.get("frozen_sample_characters") == 100000
        and data.get("frozen_sample_utf8_bytes") == 286451
        and isinstance(data.get("provider_http_calls"), int) and not isinstance(data.get("provider_http_calls"),bool)
        and 0 <= data["provider_http_calls"] <= 36
        and data.get("provider_max_retries") == 0
        and data.get("provider_http_call_cap") == 36
        and data.get("provider_retries") == 0
        and data.get("cost") == "unavailable"
        and all(data.get(key) is False for key in ("contains_source_text", "contains_source_path", "contains_secret", "contains_prompt", "contains_raw_provider_body"))
    )
    if not passed:return False
    legacy=LEGACY_RESULT_HASHES.get(data.get("evidence_id")) == raw_sha256
    if not legacy and data.get("evidence_id") != CURRENT_EVIDENCE_ID:return False
    if not legacy and data.get("schema_repair_max_attempts") != 5:return False
    if not legacy and data.get("schema_repair_max_per_batch") != 2:return False
    if not legacy and data.get("required_provider_model") != REQUIRED_PROVIDER_MODEL:return False
    if not legacy and data.get("provider_model_label") != REQUIRED_PROVIDER_MODEL:return False
    if data.get("status") == "completed_pending_independent_gate":
        metrics=data.get("initialization_metrics",{})
        provenance=data.get("initialization_provenance",{})
        return (not legacy
            and
            data.get("source_revisions") == [1, 2, 3]
            and data.get("memory_versions") == [1,2,3]
            and data.get("pending_canon_count") == 0
            and data.get("lineage_unresolved_count") == 0
            and isinstance(data.get("business_table_counts"),dict)
            and all(isinstance(value,int) and not isinstance(value,bool) and value>=0 for value in data["business_table_counts"].values())
            and all(data["business_table_counts"].get(table,0)>=1 for table in ("v2_memory_initializations","v2_memory_candidates","v2_memory_candidate_decisions","v2_runs","v2_memory_delta_batches","v2_memory_delta_candidates","v2_memory_delta_decisions","v2_source_coverage_audits","v2_memory_records"))
            and data.get("controlled_regression_chapters") == 2
            and data.get("model_output_auto_canon") is False
            and data.get("initialization_core_decisions", 0) >= 1
            and len(data.get("incremental_rounds", [])) == 2
            and [row.get("memory_version") for row in data["incremental_rounds"]] == [2,3]
            and all(row.get("run_types") == ["continuity", "memory_delta"] and row.get("core_decisions", 0) >= 1 and row.get("coverage_status")=="covered_with_memory_change" and row.get("retrieval_trace_count",0)>=1 and row.get("retrieval_method_versions")=={"continuity":"bounded-lexical-v4-longform","memory_delta":"bounded-lexical-v4-longform"} for row in data["incremental_rounds"])
            and isinstance(metrics,dict)
            and isinstance(metrics.get("total_batches"),int) and 1 <= metrics["total_batches"] <= 35
            and isinstance(metrics.get("schema_repair_attempts"),int) and not isinstance(metrics.get("schema_repair_attempts"),bool) and 0 <= metrics["schema_repair_attempts"] <= 5
            and metrics.get("validated_batches") == metrics.get("total_batches")
            and isinstance(metrics.get("staged_candidate_count"),int) and metrics["staged_candidate_count"] >= data.get("initialization_core_decisions",0)
            and isinstance(metrics.get("normalization_count"),int) and metrics["normalization_count"] >= 0
            and valid_repair_events(metrics.get("repair_events"),metrics.get("schema_repair_attempts"),completed=True)
            and isinstance(metrics.get("normalization_kinds"),dict)
            and all(isinstance(metrics.get(field),int) and metrics[field]>=0 for field in ("input_tokens","output_tokens","latency_ms"))
            and isinstance(metrics.get("cost_available"),bool)
            and isinstance(provenance,dict)
            and provenance.get("provider_label")=="deepseek"
            and isinstance(provenance.get("model_label"),str) and bool(provenance["model_label"])
            and provenance.get("model_label")==REQUIRED_PROVIDER_MODEL
            and provenance.get("provider_api_format")=="chat-completions-json-object"
            and provenance.get("prompt_version")=="memory-initialization-v8-pro-two-repair"
            and provenance.get("schema_version")=="memory-candidate-v1"
            and provenance.get("chunking_method_version")=="source-chunk-v4-5800"
        )
    if legacy:
        return True
    stop_reason=data.get("stop_reason")
    if data.get("observability_contract_version") != OBSERVABILITY_CONTRACT_VERSION or not isinstance(stop_reason,str) or not stop_reason or stop_reason in {"initialization_failed","unclassified_formal_failure"}:
        return False
    if stop_reason in ENGINE_FAILURE_CODES:
        phase=data.get("failure_phase"); ordinal=data.get("failed_batch_ordinal"); total=data.get("total_batches")
        if phase not in FAILURE_PHASES or not isinstance(total,int) or isinstance(total,bool) or total<0:return False
        if ordinal is not None and (not isinstance(ordinal,int) or isinstance(ordinal,bool) or ordinal<1 or ordinal>total):return False
        for field in ("input_tokens","output_tokens","latency_ms","schema_repair_attempts","validated_batches","staged_candidate_count","normalization_count","invalid_candidate_ordinal"):
            if field in data and (not isinstance(data[field],int) or isinstance(data[field],bool) or data[field]<0):return False
        if data.get("schema_repair_attempts",0)>5:return False
        if "repair_events" in data and not valid_repair_events(data["repair_events"],data.get("schema_repair_attempts",0),completed=False):return False
        if "normalization_kinds" in data and not isinstance(data["normalization_kinds"],dict):return False
        if "cost_available" in data and not isinstance(data["cost_available"],bool):return False
        metrics=data.get("initialization_metrics")
        if metrics is not None and (not isinstance(metrics,dict) or not isinstance(metrics.get("total_batches"),int) or not isinstance(metrics.get("repair_events"),list)):return False
        provenance=data.get("initialization_provenance")
        if provenance is not None and (not isinstance(provenance,dict) or provenance.get("model_label")!=REQUIRED_PROVIDER_MODEL or provenance.get("provider_api_format")!="chat-completions-json-object" or provenance.get("prompt_version")!="memory-initialization-v8-pro-two-repair" or provenance.get("chunking_method_version")!="source-chunk-v4-5800"):return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    raw=args.results.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    passed = validate_result(data,hashlib.sha256(raw).hexdigest())
    print(json.dumps({"validator": f"stage11l-{data.get('evidence_id','unknown')}", "valid": passed}, ensure_ascii=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
