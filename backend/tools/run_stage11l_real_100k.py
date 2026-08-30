"""One-shot, redacted Stage 11L-B formal 100k incremental regression."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import DeepSeekProvider

EXPECTED_SHA256 = "01b7cb6ca01c86a56e69bd5c897efc0f377b32b8da4b4274c326a9135b437af1"
HTTP_CAP = 36
HASH_CONTRACT = "utf-8-sig decode; text[:100000]; UTF-8 encode"
OBSERVABILITY_CONTRACT_VERSION = "stage11l-failure-v5"
DEFAULT_EVIDENCE_ID = "real-novel-100k-11l-v6"
REQUIRED_PROVIDER_MODEL = "deepseek-v4-pro"
SAFE_RESPONSE_ERROR_CODES = {
    "input_budget_exceeded", "provider_unavailable", "provider_timeout", "invalid_json",
    "provider_error", "budget_paused", "schema_invalid", "evidence_unresolvable",
    "top_level_shape_invalid", "candidate_collection_invalid", "candidate_count_invalid",
    "empty_candidates", "candidate_fields_invalid", "candidate_value_invalid", "memory_type_invalid",
    "required_field_type_invalid", "required_field_blank", "candidate_length_invalid",
    "source_revision_not_current", "insufficient_project_context", "rate_limited",
    "provider_model_not_pro",
}
SAFE_FAILURE_PHASES = {
    "provider_preflight", "batch_planning", "provider_request", "post_response_decode",
    "post_response_budget", "post_response_validation", "post_aggregation",
}
SAFE_FIELDS={"memory_type","subject","predicate","value","chapter_id","source_span_id"}
SAFE_REPAIR_RESULTS={"pending","succeeded","failed","provider_failed"}
SAFE_NORMALIZATION_KINDS={"trimmed_string","memory_type_format","extra_fields_removed"}


def safe_repair_events(value: object) -> list[dict[str, Any]]:
    if not isinstance(value,list):return []
    cleaned=[]
    for event in value:
        if not isinstance(event,dict):continue
        batch=event.get("batch_ordinal"); attempt=event.get("attempt"); reason=event.get("reason_code"); result=event.get("result")
        if not (isinstance(batch,int) and not isinstance(batch,bool) and batch>=1 and isinstance(attempt,int) and not isinstance(attempt,bool) and attempt>=1 and reason in SAFE_RESPONSE_ERROR_CODES and result in SAFE_REPAIR_RESULTS):continue
        item={"batch_ordinal":batch,"attempt":attempt,"reason_code":reason,"result":result}
        batch_attempt=event.get("batch_attempt")
        if isinstance(batch_attempt,int) and not isinstance(batch_attempt,bool) and 1<=batch_attempt<=2:item["batch_attempt"]=batch_attempt
        if event.get("field") in SAFE_FIELDS:item["field"]=event["field"]
        ordinal=event.get("candidate_ordinal")
        if isinstance(ordinal,int) and not isinstance(ordinal,bool) and ordinal>=1:item["candidate_ordinal"]=ordinal
        if event.get("final_reason_code") in SAFE_RESPONSE_ERROR_CODES:item["final_reason_code"]=event["final_reason_code"]
        cleaned.append(item)
    return cleaned


class RunFailure(RuntimeError):
    """A short redacted reason that is safe to preserve in results."""
    def __init__(self, code: str, *, http_status: int | None = None, details: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.details = details or {}

    def result_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"stop_reason": self.code}
        if self.http_status is not None:
            fields["failure_http_status"] = self.http_status
        fields.update(self.details)
        return fields


def frozen_sample(path: Path) -> tuple[str, str, int, int, str]:
    """Return source identities and the Gate-defined sample; never print it."""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    sample = text[:100_000]
    payload = sample.encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), hashlib.sha256(payload).hexdigest(), len(sample), len(payload), sample


def redacted_base(container_hash: str, frozen_hash: str, characters: int, utf8_bytes: int, evidence_id: str = DEFAULT_EVIDENCE_ID) -> dict[str, Any]:
    return {
        "stage": "11L-B", "evidence_id": evidence_id,
        "frozen_sample_hash_contract": HASH_CONTRACT,
        "expected_frozen_sample_sha256": EXPECTED_SHA256,
        "actual_frozen_sample_sha256": frozen_hash,
        "frozen_sample_characters": characters, "frozen_sample_utf8_bytes": utf8_bytes,
        "source_container_full_sha256": container_hash, "formal_input_character_limit": 100000,
        "provider_max_retries": 0, "provider_http_call_cap": HTTP_CAP, "provider_retries": 0,
        "schema_repair_max_attempts": 5, "schema_repair_max_per_batch": 2,
        "required_provider_model": REQUIRED_PROVIDER_MODEL,
        "cost": "unavailable", "contains_source_text": False, "contains_source_path": False,
        "contains_secret": False, "contains_prompt": False, "contains_raw_provider_body": False,
        "observability_contract_version": OBSERVABILITY_CONTRACT_VERSION,
    }


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def response_data(response: Any, expected: int, code: str) -> dict[str, Any]:
    if response.status_code != expected:
        actual_code=code; safe_details={}
        try:
            error=response.json().get("error",{})
            if error.get("code") in SAFE_RESPONSE_ERROR_CODES:actual_code=error["code"]
            details=error.get("details",{})
            if details.get("failure_phase") in SAFE_FAILURE_PHASES:safe_details["failure_phase"]=details["failure_phase"]
            ordinal=details.get("failed_batch_ordinal")
            if "failed_batch_ordinal" in details and (ordinal is None or (isinstance(ordinal,int) and not isinstance(ordinal,bool) and ordinal>=1)):safe_details["failed_batch_ordinal"]=ordinal
            total=details.get("total_batches")
            if isinstance(total,int) and not isinstance(total,bool) and total>=0:safe_details["total_batches"]=total
            for field in ("input_tokens","output_tokens","latency_ms","schema_repair_attempts","validated_batches","staged_candidate_count","normalization_count","invalid_candidate_ordinal"):
                value=details.get(field)
                if isinstance(value,int) and not isinstance(value,bool) and value>=0:safe_details[field]=value
            if details.get("invalid_field") in SAFE_FIELDS:safe_details["invalid_field"]=details["invalid_field"]
            repair_events=details.get("repair_events")
            if isinstance(repair_events,list):safe_details["repair_events"]=safe_repair_events(repair_events)
            normalization_kinds=details.get("normalization_kinds")
            if isinstance(normalization_kinds,dict):safe_details["normalization_kinds"]={key:value for key,value in normalization_kinds.items() if key in SAFE_NORMALIZATION_KINDS and isinstance(value,int) and not isinstance(value,bool) and value>=1}
            if isinstance(details.get("cost_available"),bool):safe_details["cost_available"]=details["cost_available"]
        except (AttributeError,TypeError,ValueError):
            pass
        raise RunFailure(actual_code,http_status=response.status_code,details=safe_details)
    try:
        return response.json()["data"]
    except (KeyError, TypeError, ValueError) as error:
        raise RunFailure(f"{code}_response_invalid") from error


def decide_cores(client: TestClient, project_id: str, delta: dict[str, Any], *, edited: bool) -> tuple[int,int,str]:
    cores = [candidate for candidate in delta.get("candidates", []) if candidate.get("review_priority") == "core"]
    if not cores:
        raise RunFailure("no_core_candidates")
    for index, candidate in enumerate(cores):
        payload: dict[str, Any] = {"decision": "accepted"}
        if edited and index == 0:
            payload = {
                "decision": "edited",
                "after": {"memory_type": candidate["memory_type"], "subject": candidate["subject"], "predicate": candidate["predicate"], "value": "受控回归作者修订"},
                "evidence_span_id": candidate["source"]["span_id"],
            }
        response_data(client.post(f"/api/projects/{project_id}/memory/deltas/{delta['id']}/candidates/{candidate['id']}/decision", json=payload, headers=idem()), 200, "core_decision_failed")
    committed=response_data(client.post(f"/api/projects/{project_id}/memory/deltas/{delta['id']}/commit", json={"confirm": True}, headers=idem()), 200, "delta_commit_failed")
    return len(cores),committed["memory_version"],committed["coverage_audit"]["status"]


def append_controlled_chapter(client: TestClient, project_id: str, base_revision: int, number: int) -> None:
    fact=("测试记录员甲将银色书签放入北侧档案柜。" if number==1 else "测试记录员甲从北侧档案柜取出银色书签，并交给测试记录员乙。")
    content = f"# 受控回归章节 {number:02d}\n{fact}\n受控情节标识：11L-R{number:02d}。"
    preview = response_data(client.post(
        f"/api/projects/{project_id}/source-change-sets/preview",
        json={"mode": "append", "input_method": "paste", "base_source_revision": base_revision, "content": content}, headers=idem(),
    ), 201, "controlled_append_preview_failed")
    change = preview["source_change_set"]
    response_data(client.post(
        f"/api/projects/{project_id}/source-change-sets/{change['id']}/commit",
        json={"confirm": True, "content_sha256": change["content_sha256"]}, headers=idem(),
    ), 200, "controlled_append_commit_failed")


def formal_run(sample: str, runtime_root: Path, provider: DeepSeekProvider) -> dict[str, Any]:
    if runtime_root.exists() and any(runtime_root.iterdir()):
        raise RunFailure("isolated_runtime_not_fresh")
    runtime_root.mkdir(parents=True, exist_ok=True)
    provider.max_retries = 0
    provider.request_cap = HTTP_CAP
    if not provider.available:
        raise RunFailure("provider_unavailable",details={"failure_phase":"provider_preflight","failed_batch_ordinal":None,"total_batches":0,"cost_available":False})
    if provider.model_label != REQUIRED_PROVIDER_MODEL:
        raise RunFailure("provider_model_not_pro",details={"failure_phase":"provider_preflight","failed_batch_ordinal":None,"total_batches":0,"cost_available":False})
    app = create_app(AppPaths.from_project_root(runtime_root, protected_poc_root=runtime_root / "protected"), provider=provider, executor=lambda function, *args: function(*args))
    client = TestClient(app)
    account = f"stage11l-real-{uuid.uuid4().hex[:12]}"
    password = "stage11l-real-password"
    response_data(client.post("/api/auth/register", json={"account_name": account, "display_name": "Stage 11L author", "password": password}, headers=idem()), 201, "registration_failed")
    preview = response_data(client.post("/api/imports/preview", files={"file": ("frozen-sample.txt", sample.encode("utf-8"), "text/plain")}, headers=idem()), 201, "import_preview_failed")
    project = response_data(client.post(
        f"/api/imports/{preview['import_id']}/commit",
        json={"confirm": True, "title": "11L 100k Incremental Regression", "chapter_preview_ids": [chapter["preview_id"] for chapter in preview["detected"]["chapters"]]}, headers=idem(),
    ), 201, "import_commit_failed")["project"]
    project_id = project["id"]
    initialization_data = response_data(client.post(f"/api/projects/{project_id}/memory/initializations", json={"source_revision": 1}, headers=idem()), 201, "initialization_failed")
    initialization = initialization_data["initialization"]
    initialization_metrics = initialization_data.get("initialization_metrics", {})
    initialization_provenance = initialization_data.get("initialization_provenance", {})
    init_cores = [candidate for candidate in initialization.get("candidates", []) if candidate.get("review_priority") == "core"]
    if not init_cores:
        raise RunFailure("no_initialization_core_candidates")
    for candidate in init_cores:
        response_data(client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{candidate['id']}/decision", json={"decision": "accepted"}, headers=idem()), 200, "initialization_core_decision_failed")
    initialization_commit=response_data(client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/commit", json={"confirm": True}, headers=idem()), 200, "initialization_commit_failed")
    summaries: list[dict[str, Any]] = []
    try:
        for number, revision in ((1, 2), (2, 3)):
            append_controlled_chapter(client, project_id, revision - 1, number)
            started = response_data(client.post(f"/api/projects/{project_id}/incremental-reviews", json={"source_revision": revision}, headers=idem()), 202, "incremental_start_failed")
            delta = response_data(client.get(f"/api/projects/{project_id}/memory/delta"), 200, "delta_view_failed")
            if delta.get("status") != "in_review":
                raise RunFailure(delta.get("error_code") if delta.get("error_code") in SAFE_RESPONSE_ERROR_CODES else "delta_not_in_review")
            core_count,memory_version,coverage_status = decide_cores(client, project_id, delta, edited=(number == 2))
            run_types: list[str] = []; retrieval_versions={}; retrieval_trace_count=0
            for run_id in (started["continuity_run_id"], started["memory_delta_run_id"]):
                run = response_data(client.get(f"/api/projects/{project_id}/checks/{run_id}?include=metrics"), 200, "run_view_failed")
                if run.get("status") != "completed":
                    raise RunFailure(run.get("error_code") if run.get("error_code") in SAFE_RESPONSE_ERROR_CODES else "incremental_run_not_completed")
                run_type=run.get("run_type", "unknown"); run_types.append(run_type)
                provenance=run.get("metrics",{}).get("provenance",{}); retrieval_versions[run_type]=provenance.get("retrieval_method_version")
                if run_type=="continuity":retrieval_trace_count=len(run.get("metrics",{}).get("retrieval",[]))
            if sorted(run_types) != ["continuity", "memory_delta"] or set(retrieval_versions.values())!={"bounded-lexical-v4-longform"} or retrieval_trace_count<1:
                raise RunFailure("incremental_retrieval_invalid")
            summaries.append({"source_revision": revision, "memory_version":memory_version,"coverage_status":coverage_status,"core_decisions": core_count, "run_types": sorted(run_types),"retrieval_method_versions":retrieval_versions,"retrieval_trace_count":retrieval_trace_count})
    except RunFailure as error:
        error.details.setdefault("failure_phase","incremental_review")
        error.details.setdefault("failed_batch_ordinal",revision-1)
        error.details.setdefault("total_batches",2)
        error.details.setdefault("initialization_metrics",initialization_metrics)
        error.details.setdefault("initialization_provenance",initialization_provenance)
        raise
    final_project=response_data(client.get(f"/api/projects/{project_id}"),200,"final_project_view_failed")
    final_coverage=response_data(client.get(f"/api/projects/{project_id}/memory/coverage"),200,"final_coverage_view_failed")
    memory_versions=[initialization_commit["memory_version"]]+[row["memory_version"] for row in summaries]
    pending_canon_count=final_coverage.get("counts",{}).get("pending_canon_count")
    if final_project.get("source_revision")!=3 or final_project.get("current_memory_version")!=3 or memory_versions!=[1,2,3] or pending_canon_count!=0:
        raise RunFailure("final_state_invalid")
    with app.state.database.connection() as connection:
        business_counts={table:connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?",(project_id,)).fetchone()[0] for table in ("v2_memory_initializations","v2_memory_candidates","v2_memory_candidate_decisions","v2_runs","v2_issues","v2_evidence","v2_memory_delta_batches","v2_memory_delta_candidates","v2_memory_delta_decisions","v2_source_coverage_audits","v2_memory_records")}
        lineage_unresolved_count=sum((
            connection.execute("SELECT COUNT(*) FROM v2_memory_candidates c LEFT JOIN v2_source_spans s ON s.id=c.source_span_id AND s.project_id=c.project_id WHERE c.project_id=? AND s.id IS NULL",(project_id,)).fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM v2_memory_delta_candidates c LEFT JOIN v2_source_spans s ON s.id=c.source_span_id AND s.project_id=c.project_id WHERE c.project_id=? AND s.id IS NULL",(project_id,)).fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM v2_evidence e LEFT JOIN v2_source_spans s ON s.id=e.span_id AND s.project_id=e.project_id WHERE e.project_id=? AND s.id IS NULL",(project_id,)).fetchone()[0],
        ))
    if lineage_unresolved_count!=0:raise RunFailure("lineage_invalid")
    if provider.request_attempts > HTTP_CAP:
        raise RunFailure("provider_http_cap_exceeded")
    return {
        "status": "completed_pending_independent_gate", "stop_reason": None,
        "provider_http_calls": provider.request_attempts, "provider_successful_responses": provider.successful_responses,
        "source_revisions": [1, 2, 3], "controlled_regression_chapters": 2,
        "memory_versions":memory_versions,"pending_canon_count":pending_canon_count,
        "lineage_unresolved_count":lineage_unresolved_count,"business_table_counts":business_counts,
        "initialization_core_decisions": len(init_cores), "incremental_rounds": summaries,
        "initialization_metrics": initialization_metrics,
        "initialization_provenance": initialization_provenance,
        "model_output_auto_canon": False,
    }


def write_result(path: Path, result: dict[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("status") != "preflight_ready_not_executed":
            raise RunFailure("formal_result_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--evidence-id", default=DEFAULT_EVIDENCE_ID, choices=[DEFAULT_EVIDENCE_ID])
    parser.add_argument("--execute-formal", action="store_true")
    args = parser.parse_args()
    if args.execute_formal and args.results.exists():
        existing = json.loads(args.results.read_text(encoding="utf-8"))
        if existing.get("status") != "preflight_ready_not_executed":
            print(json.dumps({"status": "formal_result_already_exists"}, ensure_ascii=True))
            return 3
    container_hash, frozen_hash, characters, utf8_bytes, sample = frozen_sample(args.sample)
    base = redacted_base(container_hash, frozen_hash, characters, utf8_bytes,args.evidence_id)
    if frozen_hash != EXPECTED_SHA256 or characters != 100000 or utf8_bytes != 286451:
        base.update({"status": "gate_failed", "stop_reason": "frozen_input_contract_mismatch", "provider_http_calls": 0})
        write_result(args.results, base)
        return 2
    if not args.execute_formal:
        base.update({"status": "preflight_ready_not_executed", "stop_reason": "formal_run_not_started", "provider_http_calls": 0})
        write_result(args.results, base)
        print(json.dumps({"status": base["status"], "provider_http_calls": 0}, ensure_ascii=True))
        return 0
    provider = DeepSeekProvider()
    base["provider_model_label"] = provider.model_label
    try:
        base.update(formal_run(sample, args.runtime_root, provider))
    except RunFailure as error:
        base.update({"status": "gate_failed", **error.result_fields(), "provider_http_calls": provider.request_attempts, "provider_successful_responses": provider.successful_responses, "model_output_auto_canon": False})
    except Exception:
        base.update({"status": "gate_failed", "stop_reason": "unclassified_formal_failure", "provider_http_calls": provider.request_attempts, "provider_successful_responses": provider.successful_responses, "model_output_auto_canon": False})
    write_result(args.results, base)
    print(json.dumps({"status": base["status"], "stop_reason": base["stop_reason"], "provider_http_calls": base["provider_http_calls"]}, ensure_ascii=True))
    return 0 if base["status"] == "completed_pending_independent_gate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
