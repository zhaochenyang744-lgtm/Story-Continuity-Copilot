"""One-shot, redacted Stage 11M formal 300k incremental regression."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.engine import MemoryInitializationEngine
from app.main import create_app
from app.provider import DeepSeekProvider, request_prompt_and_budget
import run_stage11l_real_100k as stage11l

EXPECTED_SHA256 = "01baefc1039f5efead919c2ea1a78015336726a7e1308beecf65dae782124a48"
EXPECTED_CONTAINER_SHA256 = "ef751050f7843b8bb9f98a5a2347df42c67ee223ffd80bb80dc7596fc97043d1"
EXPECTED_CHARACTERS = 300000
EXPECTED_UTF8_BYTES = 862721
EXPECTED_PARENT_SPANS = 13
EXPECTED_CHUNKS = 82
EXPECTED_BATCHES = 81
EXPECTED_MAX_INPUT = 5800
EXPECTED_MAX_REPAIR_INPUT = 5938
HTTP_CAP = 92
REQUIRED_PROVIDER_MODEL = "deepseek-v4-pro"
DEFAULT_EVIDENCE_ID = "real-novel-300k-11m-v1"
HASH_CONTRACT = "utf-8-sig decode; text[:300000]; UTF-8 encode"


class RunFailure(RuntimeError):
    def __init__(self, code: str, details: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.details = details or {}


class TrackingProvider:
    """Collect only aggregate metering; never retain prompts or provider bodies."""
    def __init__(self, provider: Any):
        self.provider = provider
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_values: list[float] = []

    @property
    def available(self): return self.provider.available
    @property
    def label(self): return self.provider.label
    @property
    def model_label(self): return self.provider.model_label
    @property
    def api_format_label(self): return getattr(self.provider, "api_format_label", "injected-provider")
    @property
    def request_attempts(self): return getattr(self.provider, "request_attempts", 0)
    @property
    def successful_responses(self): return getattr(self.provider, "successful_responses", 0)

    def evaluate(self, request: dict[str, Any]):
        result = self.provider.evaluate(request)
        self.input_tokens += int(result.input_tokens or 0)
        self.output_tokens += int(result.output_tokens or 0)
        if isinstance(result.cost_cny, (int, float)) and not isinstance(result.cost_cny, bool):
            self.cost_values.append(float(result.cost_cny))
        return result


def frozen_sample(path: Path) -> tuple[str, str, int, int, str]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    sample = text[:EXPECTED_CHARACTERS]
    payload = sample.encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), hashlib.sha256(payload).hexdigest(), len(sample), len(payload), sample


def _milliseconds(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _sqlite_bytes(app: Any) -> int:
    path = app.state.database.paths.database_path
    return path.stat().st_size if path.exists() else 0


def _response(response: Any, expected: int, code: str) -> dict[str, Any]:
    if response.status_code != expected:
        safe = code
        try:
            candidate = response.json().get("error", {}).get("code")
            if candidate in stage11l.SAFE_RESPONSE_ERROR_CODES:
                safe = candidate
        except (AttributeError, TypeError, ValueError):
            pass
        raise RunFailure(safe)
    try:
        return response.json()["data"]
    except (KeyError, TypeError, ValueError) as error:
        raise RunFailure(f"{code}_response_invalid") from error


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _append(client: TestClient, project_id: str, base_revision: int, number: int) -> None:
    facts = {
        1: "测试记录员甲将蓝色钥匙锁入东侧柜，并登记为当班保管。",
        2: "测试记录员甲将蓝色钥匙交给测试记录员乙，登记状态改为已移交。",
    }
    content = f"# 受控原创章节 {number:02d}\n{facts[number]}\n受控情节标识：11M-R{number:02d}。"
    preview = _response(client.post(
        f"/api/projects/{project_id}/source-change-sets/preview",
        json={"mode": "append", "input_method": "paste", "base_source_revision": base_revision, "content": content}, headers=_idem(),
    ), 201, "controlled_append_preview_failed")
    change = preview["source_change_set"]
    _response(client.post(
        f"/api/projects/{project_id}/source-change-sets/{change['id']}/commit",
        json={"confirm": True, "content_sha256": change["content_sha256"]}, headers=_idem(),
    ), 200, "controlled_append_commit_failed")


def _decide_core_delta(client: TestClient, project_id: str, delta: dict[str, Any], edited: bool) -> tuple[int, int, str]:
    core = [row for row in delta.get("candidates", []) if row.get("review_priority") == "core"]
    if not core:
        raise RunFailure("no_core_candidates")
    for ordinal, candidate in enumerate(core):
        payload: dict[str, Any] = {"decision": "accepted"}
        if edited and ordinal == 0:
            payload = {"decision": "edited", "after": {
                "memory_type": candidate["memory_type"], "subject": candidate["subject"],
                "predicate": candidate["predicate"], "value": "受控作者修订：已核对移交记录",
            }, "evidence_span_id": candidate["source"]["span_id"]}
        _response(client.post(
            f"/api/projects/{project_id}/memory/deltas/{delta['id']}/candidates/{candidate['id']}/decision",
            json=payload, headers=_idem(),
        ), 200, "core_decision_failed")
    committed = _response(client.post(
        f"/api/projects/{project_id}/memory/deltas/{delta['id']}/commit",
        json={"confirm": True}, headers=_idem(),
    ), 200, "delta_commit_failed")
    return len(core), committed["memory_version"], committed["coverage_audit"]["status"]


def _plan_metrics(app: Any, user_id: str, project_id: str, provider: TrackingProvider) -> dict[str, int]:
    data = app.state.database.memory_initialization_input(user_id, project_id, 1)
    if data is None:
        raise RunFailure("initialization_already_exists")
    planner = MemoryInitializationEngine(provider)
    chunks = planner.chunk_plan(data)
    batches = planner._batches(data)
    normal = max(request_prompt_and_budget(batch)[1] for batch in batches)
    repair_context = {"reason_code": "memory_type_invalid", "attempt": 2, "global_attempt": 5, "field": "memory_type", "candidate_ordinal": 4}
    repair = max(request_prompt_and_budget({**batch, "schema_repair": repair_context})[1] for batch in batches)
    values = {"parent_source_spans": len(data["sources"]), "source_chunks": len(chunks), "initialization_batches": len(batches), "max_normal_input_budget": normal, "max_repair_input_budget": repair}
    expected = {"parent_source_spans": EXPECTED_PARENT_SPANS, "source_chunks": EXPECTED_CHUNKS, "initialization_batches": EXPECTED_BATCHES, "max_normal_input_budget": EXPECTED_MAX_INPUT, "max_repair_input_budget": EXPECTED_MAX_REPAIR_INPUT}
    if values != expected:
        raise RunFailure("frozen_batch_plan_mismatch", values)
    return values


def _business_counts(app: Any, project_id: str) -> tuple[dict[str, int], int]:
    tables = ("v2_memory_initializations", "v2_memory_candidates", "v2_memory_candidate_decisions", "v2_runs", "v2_issues", "v2_evidence", "v2_memory_delta_batches", "v2_memory_delta_candidates", "v2_memory_delta_decisions", "v2_source_coverage_audits", "v2_memory_records")
    with app.state.database.connection() as connection:
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project_id,)).fetchone()[0] for table in tables}
        unresolved = sum(connection.execute(query, (project_id,)).fetchone()[0] for query in (
            "SELECT COUNT(*) FROM v2_memory_candidates c LEFT JOIN v2_source_spans s ON s.id=c.source_span_id AND s.project_id=c.project_id WHERE c.project_id=? AND s.id IS NULL",
            "SELECT COUNT(*) FROM v2_memory_delta_candidates c LEFT JOIN v2_source_spans s ON s.id=c.source_span_id AND s.project_id=c.project_id WHERE c.project_id=? AND s.id IS NULL",
            "SELECT COUNT(*) FROM v2_evidence e LEFT JOIN v2_source_spans s ON s.id=e.span_id AND s.project_id=e.project_id WHERE e.project_id=? AND s.id IS NULL",
        ))
    return counts, unresolved


def _idempotency_metrics(app: Any) -> dict[str, int]:
    with app.state.database.connection() as connection:
        total_rows,total_json_bytes,max_json_bytes=connection.execute("SELECT COUNT(*),COALESCE(SUM(LENGTH(CAST(response_json AS BLOB))),0),COALESCE(MAX(LENGTH(CAST(response_json AS BLOB))),0) FROM v2_idempotency").fetchone()
        decision_rows,decision_total,decision_max=connection.execute("SELECT COUNT(*),COALESCE(SUM(LENGTH(CAST(response_json AS BLOB))),0),COALESCE(MAX(LENGTH(CAST(response_json AS BLOB))),0) FROM v2_idempotency WHERE operation LIKE 'memory_candidate_decision:%'").fetchone()
        initialization_max=connection.execute("SELECT COALESCE(MAX(LENGTH(CAST(response_json AS BLOB))),0) FROM v2_idempotency WHERE operation LIKE 'memory_initialization:%'").fetchone()[0]
        commit_max=connection.execute("SELECT COALESCE(MAX(LENGTH(CAST(response_json AS BLOB))),0) FROM v2_idempotency WHERE operation LIKE 'memory_initialization_commit:%'").fetchone()[0]
        table_bytes=connection.execute("SELECT COALESCE(SUM(pgsize),0) FROM dbstat WHERE name='v2_idempotency'").fetchone()[0]
    return {"row_count":total_rows,"response_json_bytes":total_json_bytes,"max_response_json_bytes":max_json_bytes,"table_bytes":table_bytes,"candidate_decision_rows":decision_rows,"candidate_decision_response_json_bytes":decision_total,"candidate_decision_max_response_json_bytes":decision_max,"initialization_max_response_json_bytes":initialization_max,"initialization_commit_max_response_json_bytes":commit_max}


def formal_run(sample: str, runtime_root: Path, provider: Any) -> dict[str, Any]:
    if runtime_root.exists() and any(runtime_root.iterdir()):
        raise RunFailure("isolated_runtime_not_fresh")
    if not provider.available:
        raise RunFailure("provider_unavailable", {"provider_http_calls": 0})
    if provider.model_label != REQUIRED_PROVIDER_MODEL:
        raise RunFailure("provider_model_not_pro", {"provider_http_calls": 0})
    runtime_root.mkdir(parents=True, exist_ok=True)
    measured = TrackingProvider(provider)
    started = time.perf_counter()
    app = create_app(AppPaths.from_project_root(runtime_root, protected_poc_root=runtime_root / "protected"), provider=measured, executor=lambda fn, *args: fn(*args))
    client = TestClient(app)
    _response(client.post("/api/auth/register", json={"account_name": f"stage11m-{uuid.uuid4().hex[:12]}", "display_name": "Stage 11M author", "password": "stage11m-controlled"}, headers=_idem()), 201, "registration_failed")
    session = _response(client.get("/api/auth/session"), 200, "session_failed")
    user_id = session["user"]["id"]
    sqlite_sizes = {"before_import": _sqlite_bytes(app)}
    import_started = time.perf_counter()
    preview = _response(client.post("/api/imports/preview", files={"file": ("frozen-sample.txt", sample.encode("utf-8"), "text/plain")}, headers=_idem()), 201, "import_preview_failed")
    project = _response(client.post(
        f"/api/imports/{preview['import_id']}/commit",
        json={"confirm": True, "title": "11M 300k Incremental Regression", "chapter_preview_ids": [row["preview_id"] for row in preview["detected"]["chapters"]]}, headers=_idem(),
    ), 201, "import_commit_failed")["project"]
    import_ms = _milliseconds(import_started)
    project_id = project["id"]
    sqlite_sizes["after_import"] = _sqlite_bytes(app)
    planning_started = time.perf_counter()
    plan = _plan_metrics(app, user_id, project_id, measured)
    planning_ms = _milliseconds(planning_started)
    initialization_started = time.perf_counter()
    initialization_data = _response(client.post(f"/api/projects/{project_id}/memory/initializations?view=compact", json={"source_revision": 1}, headers=_idem()), 201, "initialization_failed")
    initialization = _response(client.get(f"/api/projects/{project_id}/memory/initialization"), 200, "initialization_view_failed")
    cores = [row for row in initialization.get("candidates", []) if row.get("review_priority") == "core"]
    if not cores:
        raise RunFailure("no_initialization_core_candidates")
    for candidate in cores:
        _response(client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/candidates/{candidate['id']}/decision?view=compact", json={"decision": "accepted"}, headers=_idem()), 200, "initialization_core_decision_failed")
    initialization_commit = _response(client.post(f"/api/projects/{project_id}/memory/initializations/{initialization['id']}/commit?view=compact", json={"confirm": True}, headers=_idem()), 200, "initialization_commit_failed")
    initialization_ms = _milliseconds(initialization_started)
    sqlite_sizes["after_initialization"] = _sqlite_bytes(app)
    rounds: list[dict[str, Any]] = []
    for number, revision in ((1, 2), (2, 3)):
        _append(client, project_id, revision - 1, number)
        round_started = time.perf_counter()
        started_run = _response(client.post(f"/api/projects/{project_id}/incremental-reviews", json={"source_revision": revision}, headers=_idem()), 202, "incremental_start_failed")
        runs = [_response(client.get(f"/api/projects/{project_id}/checks/{run_id}?include=metrics"), 200, "run_view_failed") for run_id in (started_run["continuity_run_id"], started_run["memory_delta_run_id"])]
        completion_ms = _milliseconds(round_started)
        if any(row.get("status") != "completed" for row in runs):
            raise RunFailure("incremental_run_not_completed", {"incremental_run_errors": [
                {"run_type": row.get("run_type"), "status": row.get("status"), "error_code": row.get("error_code")}
                for row in runs
            ]})
        if {row.get("run_type") for row in runs} != {"continuity", "memory_delta"}:
            raise RunFailure("incremental_run_types_invalid")
        continuity = next(row for row in runs if row["run_type"] == "continuity")
        if len(continuity.get("metrics", {}).get("retrieval", [])) < 1:
            raise RunFailure("incremental_retrieval_invalid")
        delta = _response(client.get(f"/api/projects/{project_id}/memory/delta"), 200, "delta_view_failed")
        if delta.get("status") != "in_review":
            raise RunFailure("delta_not_in_review")
        core_count, memory_version, coverage_status = _decide_core_delta(client, project_id, delta, edited=(number == 2))
        total_ms = _milliseconds(round_started)
        rounds.append({"source_revision": revision, "memory_version": memory_version, "core_decisions": core_count, "coverage_status": coverage_status, "run_types": sorted(row["run_type"] for row in runs), "retrieval_trace_count": len(continuity["metrics"]["retrieval"]), "incremental_run_completion_ms": completion_ms, "incremental_total_ms": total_ms})
    final_project = _response(client.get(f"/api/projects/{project_id}"), 200, "final_project_view_failed")
    coverage = _response(client.get(f"/api/projects/{project_id}/memory/coverage"), 200, "coverage_view_failed")
    counts, unresolved = _business_counts(app, project_id)
    sqlite_sizes["final"] = _sqlite_bytes(app)
    if final_project.get("source_revision") != 3 or final_project.get("current_memory_version") != 3 or coverage.get("counts", {}).get("pending_canon_count") != 0 or unresolved != 0:
        raise RunFailure("final_state_invalid")
    if measured.request_attempts > HTTP_CAP:
        raise RunFailure("provider_http_cap_exceeded")
    cost: float | str = sum(measured.cost_values) if measured.cost_values else "unavailable"
    return {
        "status": "completed_pending_independent_gate", "stop_reason": None,
        "provider_http_calls": measured.request_attempts, "provider_successful_responses": measured.successful_responses, "provider_retries": 0,
        "plan": plan, "source_revisions": [1, 2, 3], "memory_versions": [initialization_commit["memory_version"], *[row["memory_version"] for row in rounds]],
        "pending_canon_count": coverage["counts"]["pending_canon_count"], "lineage_unresolved_count": unresolved, "business_table_counts": counts,
        "initialization_core_decisions": len(cores), "initialization_metrics": initialization_data["initialization_metrics"], "initialization_provenance": initialization_data["initialization_provenance"],
        "incremental_rounds": rounds, "timings_ms": {"import": import_ms, "batch_planning": planning_ms, "initialization": initialization_ms, "incremental_1": rounds[0]["incremental_total_ms"], "incremental_2": rounds[1]["incremental_total_ms"], "total": _milliseconds(started)},
        "sqlite_bytes": sqlite_sizes, "idempotency_metrics": _idempotency_metrics(app), "provider_tokens": {"input": measured.input_tokens, "output": measured.output_tokens}, "schema_repair_attempts": initialization_data["initialization_metrics"].get("schema_repair_attempts", 0), "cost": cost,
        "model_output_auto_canon": False,
    }


def _base(container_hash: str, sample_hash: str, characters: int, utf8_bytes: int, evidence_id: str = DEFAULT_EVIDENCE_ID) -> dict[str, Any]:
    return {"stage": "11M", "evidence_id": evidence_id, "frozen_sample_hash_contract": HASH_CONTRACT, "expected_frozen_sample_sha256": EXPECTED_SHA256, "actual_frozen_sample_sha256": sample_hash, "frozen_sample_characters": characters, "frozen_sample_utf8_bytes": utf8_bytes, "source_container_full_sha256": container_hash, "formal_input_character_limit": EXPECTED_CHARACTERS, "required_provider_model": REQUIRED_PROVIDER_MODEL, "provider_http_call_cap": HTTP_CAP, "provider_max_retries": 0, "contains_source_text": False, "contains_source_path": False, "contains_secret": False, "contains_prompt": False, "contains_raw_provider_body": False}


def _write_once(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        raise RunFailure("formal_result_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--execute-formal", action="store_true")
    args = parser.parse_args()
    if not args.execute_formal:
        print(json.dumps({"status": "formal_execution_flag_required", "provider_http_calls": 0}))
        return 2
    if args.results.exists():
        print(json.dumps({"status": "formal_result_already_exists", "provider_http_calls": 0}))
        return 3
    container_hash, sample_hash, characters, utf8_bytes, sample = frozen_sample(args.sample)
    result = _base(container_hash, sample_hash, characters, utf8_bytes)
    if (container_hash != EXPECTED_CONTAINER_SHA256 or sample_hash != EXPECTED_SHA256 or characters != EXPECTED_CHARACTERS or utf8_bytes != EXPECTED_UTF8_BYTES):
        result.update({"status": "gate_failed", "stop_reason": "frozen_input_contract_mismatch", "provider_http_calls": 0})
        _write_once(args.results, result)
        return 2
    raw = DeepSeekProvider()
    raw.max_retries = 0
    raw.request_cap = HTTP_CAP
    result["provider_model_label"] = raw.model_label
    try:
        result.update(formal_run(sample, args.runtime_root, raw))
    except RunFailure as error:
        result.update({"status": "gate_failed", "stop_reason": error.code, **error.details, "provider_http_calls": getattr(raw, "request_attempts", 0), "provider_successful_responses": getattr(raw, "successful_responses", 0), "provider_retries": 0, "model_output_auto_canon": False})
    except Exception:
        result.update({"status": "gate_failed", "stop_reason": "unclassified_formal_failure", "provider_http_calls": getattr(raw, "request_attempts", 0), "provider_successful_responses": getattr(raw, "successful_responses", 0), "provider_retries": 0, "model_output_auto_canon": False})
    _write_once(args.results, result)
    print(json.dumps({"status": result["status"], "stop_reason": result["stop_reason"], "provider_http_calls": result["provider_http_calls"]}))
    return 0 if result["status"] == "completed_pending_independent_gate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
