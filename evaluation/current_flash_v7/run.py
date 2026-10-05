"""Fresh 24+10 API runner with pre-dispatch persistence and create-only identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
os.environ.update({"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3219",
                   "BACKEND_ORIGIN": "http://127.0.0.1:8219", "TRUSTED_HOSTS": "testserver,127.0.0.1",
                   "TRUSTED_ORIGINS": "http://testserver,http://127.0.0.1:3219"})

import httpx
from app.config import AppPaths
from app.main import COOKIE, create_app
from app.provider import DeepSeekProvider, ProviderResult
from app.stage13 import Stage13Settings
from evaluation.current_flash_v7.inputs import InputContract
from evaluation.current_flash_v5.journal import DurableProvider, RunJournal, StubProvider, stamp, write_x
from evaluation.v2_fixture_loader import FixtureRuntime, load_fixture

RESULTS = HERE / "runs"
WORKSPACES = HERE / "workspaces"
CORPORA = {p.stem: p for folder in (ROOT / "evaluation/current_contract_compare_v2/corpora", HERE / "corpora") for p in folder.glob("*.json")}
BASE_HEAD = "7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2"
MAX_POST = 136  # 34 continuity x 2 contract evaluations x 2 transport attempts.


class V7StubProvider(StubProvider):
    label = "flash-v7-offline-stub"
    continuity_contract_version = "v6"

    def evaluate(self, request: dict) -> ProviderResult:
        self.journal.begin_evaluation(request)
        if self.input_validator is not None:
            audit = self.input_validator(self.journal.case, request)
            write_x(self.journal.root / "input-audit" / f"{self.journal.current_evaluation:02d}.json", audit)
        payload = {"issues": [], "claim_verdicts": [
            {"claim_span_id": claim["id"], "verdict": "no_issue", "basis": "Offline input-capture stub, not a model decision."}
            for claim in request["claims"]]}
        result = ProviderResult(payload, input_tokens=1, output_tokens=1, latency_ms=1)
        self.journal.finish_evaluation(result)
        return result


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reserve(run_id: str) -> tuple[pathlib.Path, pathlib.Path]:
    if not re.fullmatch(r"(?:prep|flash)-v7-[a-z0-9-]{1,24}", run_id):
        raise ValueError("run_id_invalid")
    run_dir, workspace = RESULTS / run_id, WORKSPACES / run_id
    # Existing identity is rejected before freeze, case, fixture, or Provider access.
    if run_dir.exists() or workspace.exists():
        raise FileExistsError("run_identity_already_exists:" + run_id)
    RESULTS.mkdir(parents=True, exist_ok=True)
    WORKSPACES.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)
    workspace.mkdir(exist_ok=False)
    return run_dir, workspace


def _data(response):
    if response.status_code >= 400:
        raise RuntimeError(f"isolated_api_{response.status_code}:{response.text[:180]}")
    return response.json()["data"]


def _binding_snapshot(app, project_id: str, draft: dict, root: pathlib.Path) -> dict:
    with app.state.database.connection() as connection:
        project = connection.execute("SELECT source_revision,current_memory_version FROM v2_projects WHERE id=?", (project_id,)).fetchone()
        draft_row = connection.execute("SELECT body FROM v2_draft_revisions WHERE draft_id=? AND revision=?",
                                       (draft["id"], draft["revision"])).fetchone()
        rows = connection.execute(
            "SELECT ch.id chapter_id,ch.chapter_number,ch.title chapter_title,ch.body chapter_body,ch.source_revision chapter_revision,"
            "s.id span_id,s.body span_body,s.source_revision span_revision FROM v2_chapters ch JOIN v2_source_spans s "
            "ON s.chapter_id=ch.id AND s.project_id=ch.project_id WHERE ch.project_id=? ORDER BY ch.chapter_number,s.id",
            (project_id,)).fetchall()
        memories = connection.execute(
            "SELECT id,memory_type,subject,predicate,value,source_span_id,version FROM v2_memory_records "
            "WHERE project_id=? AND version=? ORDER BY id",
            (project_id, project["current_memory_version"])).fetchall()
    if draft_row is None:
        raise RuntimeError("isolated_saved_draft_missing")
    snapshot = {"project_id": project_id, "draft_id": draft["id"],
                "draft_revision": draft["revision"], "draft_body": draft_row["body"],
                "draft_body_sha256": hashlib.sha256(draft_row["body"].encode()).hexdigest(),
                "source_revision": project["source_revision"], "memory_version": project["current_memory_version"],
                "chapters": [{"chapter_id": row["chapter_id"], "chapter_number": row["chapter_number"],
                              "chapter_title": row["chapter_title"], "chapter_body": row["chapter_body"],
                              "chapter_revision": row["chapter_revision"], "span_id": row["span_id"],
                              "span_body": row["span_body"], "span_revision": row["span_revision"],
                              "chapter_body_sha256": hashlib.sha256(row["chapter_body"].encode()).hexdigest(),
                              "span_body_sha256": hashlib.sha256(row["span_body"].encode()).hexdigest()}
                             for row in rows],
                "memory": [dict(row) for row in memories]}
    write_x(root / "runtime-binding.json", snapshot)
    return snapshot


def _continuity(case: dict, provider, workspace: pathlib.Path, record_root: pathlib.Path) -> dict:
    app = create_app(AppPaths.from_project_root(workspace, protected_poc_root=workspace / "protected-placeholder"),
                     provider=provider, executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
    identity = load_fixture(app.state.database, case["corpus_key"], corpus_paths=CORPORA)
    from fastapi.testclient import TestClient
    client = TestClient(app)
    client.cookies.set(COOKIE, identity.session_token)
    runtime = FixtureRuntime(workspace, app, client, identity)
    try:
        client, identity = runtime.client, runtime.identity
        with runtime.app.state.database.connection() as connection:
            runtime.app.state.database._insert_empty_author_context_zero(
                connection, identity.project_id, stamp())
        project = _data(client.get(f"/api/projects/{identity.project_id}"))
        saved = _data(client.patch(f"/api/projects/{identity.project_id}/drafts/{identity.draft_id}",
                     headers={"Idempotency-Key": str(uuid.uuid4())},
                     json={"base_revision": project["current_draft"]["revision"], "body": case["saved_draft"]}))
        provider.input_validator.bind_runtime(case["case_id"], _binding_snapshot(runtime.app, identity.project_id, saved, record_root))
        started = _data(client.post(f"/api/projects/{identity.project_id}/checks",
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                        json={"draft_id": saved["id"], "draft_revision": saved["revision"]}))
        return _data(client.get(f"/api/projects/{identity.project_id}/checks/{started['run_id']}?include=issues,evidence,metrics"))
    finally:
        runtime.client.close()


def _models_preflight(run_dir: pathlib.Path, key: str) -> None:
    # One GET only; the key remains in-process and no header/body is persisted.
    write_x(run_dir / "models-start.json", {"endpoint": "/models", "started_at": stamp(), "status": "dispatch_started"})
    metadata = {"endpoint": "/models", "finished_at": stamp(), "http_status": None,
                "model_present": False, "error_type": None, "usage_status": "not_applicable"}
    try:
        with httpx.Client(timeout=DeepSeekProvider.timeout_seconds) as client:
            response = client.get("https://api.deepseek.com/models", headers={"Authorization": "Bearer " + key})
        metadata["http_status"] = response.status_code
        if response.status_code == 200:
            payload = response.json()
            metadata["model_present"] = any(x.get("id") == "deepseek-flash" for x in payload.get("data", []) if isinstance(x, dict))
    except Exception as error:
        metadata["error_type"] = type(error).__name__
    metadata["finished_at"] = stamp()
    write_x(run_dir / "models-finish.json", metadata)
    if metadata["http_status"] != 200 or not metadata["model_present"]:
        raise RuntimeError("models_preflight_failed")


def _attempts(case_root: pathlib.Path) -> list[dict]:
    starts = sorted((case_root / "attempts").glob("*-start.json"))
    rows = []
    for path in starts:
        start = json.loads(path.read_text(encoding="utf-8"))
        finish = path.with_name(path.name.replace("-start.json", "-finish.json"))
        rows.append({"start": start, "finish": json.loads(finish.read_text(encoding="utf-8")) if finish.exists() else None})
    return rows


def usage_ledger(run_dir: pathlib.Path) -> dict:
    attempts = [x for case_root in sorted((run_dir / "cases").glob("[0-9][0-9]")) for x in _attempts(case_root)]
    statuses = [x["finish"]["usage"]["status"] if x["finish"] else "unknown" for x in attempts]
    values = [x["finish"]["usage"]["values"] for x in attempts if x["finish"]]
    prompt = sum(x["prompt_tokens"] for x in values if x.get("prompt_tokens") is not None)
    completion = sum(x["completion_tokens"] for x in values if x.get("completion_tokens") is not None)
    all_complete = bool(attempts) and all(x == "complete" for x in statuses)
    return {"post_attempt_start_records": len(attempts),
            "transport_attempts_finished": sum(x["finish"] is not None for x in attempts),
            "http_responses_received": sum(x["finish"] is not None and isinstance(x["finish"].get("status"), int) for x in attempts),
            "server_receipt_for_unfinished_attempts": "unknown",
            "usage_counts": {name: statuses.count(name)
            for name in ("complete", "missing", "partial", "unknown")},
            "known_prompt_tokens_partial_sum": prompt, "known_completion_tokens_partial_sum": completion,
            "prompt_tokens_total": prompt if all_complete else None,
            "completion_tokens_total": completion if all_complete else None,
            "all_dispatch_usage_complete": all_complete,
            "unfinished_attempt_count": sum(x["finish"] is None for x in attempts),
            "models_get_start_records": int((run_dir / "models-start.json").exists()),
            "models_get_finish_observed": int((run_dir / "models-finish.json").exists()),
            "models_server_receipt_if_unfinished": "unknown"}


def workspace_inventory(work_root: pathlib.Path) -> dict:
    databases = sorted(x for x in work_root.rglob("*.sqlite3") if x.is_file())
    return {"root": str(work_root), "isolated_evaluation_only": True,
            "database_count": len(databases),
            "databases": [{"relative_path": str(path.relative_to(work_root)).replace("\\", "/"),
                           "sha256": sha(path), "bytes": path.stat().st_size} for path in databases]}


def _service_failure(product: dict, attempts: list[dict]) -> bool:
    statuses = [x["finish"]["status"] for x in attempts if x["finish"]]
    return (product.get("error_code") in {"provider_unavailable", "provider_error", "provider_timeout"} or
            any(x["finish"] and x["finish"].get("error_type") not in {None, "response_json_unavailable"} for x in attempts) or
            any(status in {400, 401, 403, 404, 429} or isinstance(status, int) and status >= 500 for status in statuses))


def _auth_or_model_rejection(attempts: list[dict]) -> bool:
    return any(x["finish"] and x["finish"]["status"] in {400, 401, 403, 404} for x in attempts)


def execute(mode: str, run_id: str) -> pathlib.Path:
    if mode not in {"prepare", "live"}:
        raise ValueError("mode_invalid")
    if not run_id.startswith("prep-v7-" if mode == "prepare" else "flash-v7-"):
        raise ValueError("run_mode_identity_mismatch")
    run_dir, work_root = reserve(run_id)
    try:
        if mode == "live":
            from evaluation.current_flash_v7.freeze import verify
            manifest = verify()
        else:
            manifest = None
        cases_doc = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
        from evaluation.current_flash_v7.build_cases import build
        if cases_doc != build():
            raise RuntimeError("case_set_drift")
        contract = InputContract()
        write_x(run_dir / "start.json", {"run_id": run_id, "mode": mode, "started_at": stamp(),
                "git_base": BASE_HEAD, "case_count": len(cases_doc["cases"]),
                "frozen_manifest_sha256": sha(HERE / "frozen-inputs.json") if manifest else None,
                "max_generation_post": MAX_POST, "max_models_get": 1 if mode == "live" else 0,
                "provider": "deepseek-flash" if mode == "live" else "offline-stub"})
        if mode == "live":
            # Only this named existing environment variable is consumed; never print or persist it.
            key = os.environ.get("CONTINUITY_API_KEY")
            if not key:
                raise RuntimeError("CONTINUITY_API_KEY_missing")
            os.environ["CONTINUITY_PROVIDER"] = "deepseek"
            os.environ["CONTINUITY_MODEL"] = "deepseek-flash"
            os.environ["CONTINUITY_BASE_URL"] = "https://api.deepseek.com"
            _models_preflight(run_dir, key)
        journal = RunJournal(run_dir, run_id, MAX_POST)
        consecutive_service_errors = 0
        completed_cases = 0
        for case in cases_doc["cases"]:
            ordinal = case["ordinal"]
            case_journal = journal.case(ordinal, case)
            workspace = work_root / f"{ordinal:02d}"
            workspace.mkdir(exist_ok=False)
            try:
                provider = (V7StubProvider(case_journal, contract) if mode == "prepare" else
                            DurableProvider(case_journal, input_validator=contract))
                product = _continuity(case, provider, workspace, case_journal.root)
                write_x(case_journal.root / "final-product.json", product)
                from evaluation.current_flash_v7.score import score_case
                scored = score_case(case, case_journal.root, product, mode)
                write_x(case_journal.root / "scores.json", scored)
                attempts = _attempts(case_journal.root)
                consecutive_service_errors = consecutive_service_errors + 1 if _service_failure(product, attempts) else 0
                write_x(case_journal.root / "case-finish.json", {"case_id": case["case_id"],
                        "status": product.get("status"), "error_code": product.get("error_code"),
                        "post_attempt_start_records": len(attempts), "evaluation_count": case_journal.evaluation_count,
                        "score_status": scored.get("final", {}).get("result", "pending_manual_review"),
                        "finished_at": stamp()})
                completed_cases += 1
                if _auth_or_model_rejection(attempts) or consecutive_service_errors >= 2:
                    write_x(run_dir / "service-stop.json", {"case_id": case["case_id"],
                            "reason": "authorization_or_model_rejection" if _auth_or_model_rejection(attempts) else "two_consecutive_service_failures",
                            "consecutive_service_failures": consecutive_service_errors, "stopped_at": stamp()})
                    break
            except Exception as error:
                write_x(case_journal.root / "first-failure.json", {"case_id": case["case_id"],
                        "error_type": type(error).__name__, "error": str(error), "failed_at": stamp(),
                        "post_attempt_start_records_so_far": len(_attempts(case_journal.root))})
                parsed_response_exists = any((case_journal.root / "evaluations").glob("*.json"))
                recoverable_quality_error = (parsed_response_exists and not (case_journal.root / "final-product.json").exists()
                                             and isinstance(error, (AttributeError, TypeError, ValueError))
                                             and not str(error).startswith("input_contract:"))
                if not recoverable_quality_error:
                    raise
                # The product API threw after a parseable model answer. Preserve
                # that answer and lack of final product, then continue the fixed
                # matrix once; this is not a model or API retry.
                write_x(case_journal.root / "final-product-unavailable.json", {
                    "status": "unavailable", "reason": "product_api_exception",
                    "error_type": type(error).__name__, "no_persisted_api_product": True})
                from evaluation.current_flash_v7.score import score_case
                scored = score_case(case, case_journal.root, None, mode)
                write_x(case_journal.root / "scores.json", scored)
                attempts = _attempts(case_journal.root)
                quality_marker = {"status": "failed", "error_code": "product_api_exception"}
                consecutive_service_errors = consecutive_service_errors + 1 if _service_failure(quality_marker, attempts) else 0
                write_x(case_journal.root / "case-finish.json", {"case_id": case["case_id"],
                        "status": "product_api_exception", "post_attempt_start_records": len(attempts),
                        "evaluation_count": case_journal.evaluation_count, "finished_at": stamp()})
                completed_cases += 1
                if _auth_or_model_rejection(attempts) or consecutive_service_errors >= 2:
                    write_x(run_dir / "service-stop.json", {"case_id": case["case_id"],
                            "reason": "authorization_or_model_rejection" if _auth_or_model_rejection(attempts) else "two_consecutive_service_failures",
                            "consecutive_service_failures": consecutive_service_errors, "stopped_at": stamp()})
                    break
        write_x(run_dir / "workspace-manifest.json", workspace_inventory(work_root))
        write_x(run_dir / "summary.json", {"run_id": run_id, "mode": mode, "finished_at": stamp(),
                "logical_cases_finished": completed_cases, "logical_cases_planned": len(cases_doc["cases"]),
                "service_stop": (run_dir / "service-stop.json").exists(),
                "semantic_status": "pending_manual_review", **usage_ledger(run_dir)})
    except Exception as error:
        write_x(run_dir / "first-failure.json", {"run_id": run_id, "mode": mode,
                "error_type": type(error).__name__, "error": str(error), "failed_at": stamp(),
                "ledger_at_failure": usage_ledger(run_dir)})
        raise
    return run_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare",))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(execute(args.mode, args.run_id))
