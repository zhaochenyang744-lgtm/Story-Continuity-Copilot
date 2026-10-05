"""Independent, append-only current-code evaluation. Never imports the V8 executor."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
# The legacy fixture loader constructs local Stage13 settings from process env.
# Keep that app isolated regardless of the machine's deployment settings.
os.environ.update({"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3219",
                   "BACKEND_ORIGIN": "http://127.0.0.1:8219", "TRUSTED_HOSTS": "testserver,127.0.0.1",
                   "TRUSTED_ORIGINS": "http://testserver,http://127.0.0.1:3219"})

import httpx
from app.config import AppPaths
from app.engine import CONTEXT_BRIEF_PROMPT_VERSION, CHANGE_IMPACT_PROMPT_VERSION
from app.main import create_app
from app.provider import DeepSeekProvider
from app.stage13 import Stage13Settings
from evaluation.v2_fixture_loader import fixture_runtime_at

G03_CORPUS = HERE / "g03-corpus.json"
MANIFEST = HERE / "frozen-inputs.json"
RESULTS = HERE / "runs"
LOCAL_EVIDENCE = ROOT / "artifacts/current_flash_v2"
MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_new(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(obj, output, ensure_ascii=False, indent=2)


def case_body(case: dict) -> str:
    return case.get("body", case.get("body_repeat", "") * case.get("repeat_count", 0) + case.get("body_tail", ""))


def source_paths() -> list[pathlib.Path]:
    return [HERE / "cases.json", HERE / "g03-corpus.json", HERE / "run.py", HERE / "test_offline.py", HERE / "PLAN.md",
            ROOT / "evaluation/current_flash_v1/cases.json", ROOT / "backend/app/provider.py",
            ROOT / "backend/app/engine.py", ROOT / "backend/app/v2_database.py", ROOT / "backend/app/main.py",
            ROOT / "backend/app/seed_data.py", ROOT / "backend/app/config.py", ROOT / "backend/app/database.py",
            ROOT / "backend/app/stage13.py", ROOT / "evaluation/v2_fixture_loader.py"]


def validate_cases(cases: dict) -> None:
    assert cases["schema_version"] == "current-flash-v2-cases"
    assert tuple(len(cases[k]) for k in ("g02", "g03")) == (4, 4)
    all_ids = [c["id"] for group in ("g02", "g03") for c in cases[group]]
    assert len(all_ids) == len(set(all_ids)) == 8
    assert len({case_body(c) for c in cases["g02"]}) == 4
    v1 = json.loads((ROOT / "evaluation/current_flash_v1/cases.json").read_text(encoding="utf-8"))
    assert [case_body(c) for c in cases["g02"]] == [case_body(c) for c in v1["g02"]]
    corpus = json.loads(G03_CORPUS.read_text(encoding="utf-8"))
    assert corpus["corpus_key"] == "flash_v2_target" and [c["chapter_number"] for c in corpus["chapters"]] == [1, 2]
    assert corpus["memory"][0]["subject"] == "星钥" and corpus["memory"][0]["predicate"] == "holder"


def freeze() -> None:
    if MANIFEST.exists():
        raise RuntimeError("frozen_inputs_already_exist")
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    validate_cases(cases)
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in source_paths()}
    write_new(MANIFEST, {"version": "current-flash-v2", "frozen_at": stamp(), "source_hashes": hashes,
        "model": MODEL, "base_url": BASE_URL, "provider": "deepseek", "thinking": "disabled",
        "temperature": 0, "max_tokens": DeepSeekProvider.max_output_tokens,
        "provider_timeout_seconds": DeepSeekProvider.timeout_seconds,
        "provider_max_retries": DeepSeekProvider.max_retries,
        "prompt_versions": {"context_brief": CONTEXT_BRIEF_PROMPT_VERSION,
                            "change_impact": CHANGE_IMPACT_PROMPT_VERSION},
        "logical_run_count": 8, "families": {"g02": 4, "g03": 4},
        "scoring": "Per-item semantic and own-citation review; first parsed output and final product separately. No aggregate accuracy claim for open-ended items.",
        "adaptations": ["G02 four saved-draft bodies byte-identical to v1; full actual business request now retained",
                        "G03 uses deterministic standalone two-chapter fixture with holder predicate; not the same background input as v1",
                        "G03 other-chapter interference is explicitly selected before Provider dispatch",
                        "v1 run and V8/G01 historical outputs are never modified or rerun"],
        "boundaries": {"exposed_development_regression": True, "unseen_or_blind": False,
                       "v1_run_retained": "flash-v1-20260926-01", "product_logic_unchanged": True}})


def verify_freeze() -> dict:
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if current_head != "c3bd54ab019447354e8b1387e16b9aca3258b4c9":
        raise RuntimeError("git_base_changed")
    for name, expected in frozen["source_hashes"].items():
        path = ROOT / name
        if not path.exists() or sha(path) != expected:
            raise RuntimeError("frozen_hash_mismatch:" + name)
    if frozen["model"] != MODEL or frozen["base_url"] != BASE_URL:
        raise RuntimeError("provider_contract_mismatch")
    validate_cases(json.loads((HERE / "cases.json").read_text(encoding="utf-8")))
    return frozen


def usage_metadata(value) -> tuple[dict | None, str, list[str]]:
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if not isinstance(value, dict):
        return None, "unknown", list(keys)
    clean = {key: value.get(key) if type(value.get(key)) is int and value[key] >= 0 else None for key in keys}
    invalid = [key for key in keys if clean[key] is None]
    if not invalid and clean["total_tokens"] != clean["prompt_tokens"] + clean["completion_tokens"]:
        invalid = ["total_tokens_inconsistent"]
    status = "complete" if not invalid else "partial" if any(v is not None for v in clean.values()) else "unknown"
    return clean, status, invalid


class ObservedClient:
    """Records only response metadata; raw response and request never leave memory."""
    def __init__(self, owner):
        self.owner = owner
        self.client = httpx.Client(timeout=httpx.Timeout(DeepSeekProvider.timeout_seconds))

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, *args):
        return self.client.__exit__(*args)

    def post(self, url, **kwargs):
        event = {"case_id": self.owner.case_id, "ordinal": len(self.owner.http_events) + 1,
                 "sent_at": stamp(), "status": None, "latency_ms": None, "usage": None,
                 "usage_status": "unknown", "usage_invalid_fields": ["prompt_tokens", "completion_tokens", "total_tokens"],
                 "response_model": None, "system_fingerprint": None, "finish_reason": None,
                 "error_type": None}
        started = time.perf_counter()
        try:
            response = self.client.post(url, **kwargs)
            event["status"] = response.status_code
            try:
                body = response.json()
                if response.status_code < 400 and isinstance(body, dict):
                    event["usage"], event["usage_status"], event["usage_invalid_fields"] = usage_metadata(body.get("usage"))
                    event["response_model"] = body.get("model")
                    event["system_fingerprint"] = body.get("system_fingerprint")
                    choices = body.get("choices") or []
                    event["finish_reason"] = choices[0].get("finish_reason") if choices else None
            except (ValueError, TypeError, AttributeError, KeyError, IndexError):
                event["error_type"] = "response_json_unavailable"
            return response
        except Exception as error:
            event["error_type"] = type(error).__name__
            raise
        finally:
            event["latency_ms"] = int((time.perf_counter() - started) * 1000)
            self.owner.http_events.append(event)


class ObservedProvider(DeepSeekProvider):
    def __init__(self):
        super().__init__(client_factory=lambda: ObservedClient(self))
        self.case_id = "preflight"
        self.parsed = []
        self.http_events = []
        self.business_requests = []
        self.expected_case = None

    def evaluate(self, request):
        if self.expected_case is not None:
            assert_business_input(self.expected_case, request)
        snapshot = copy.deepcopy(request)
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request_record = {"case_id": self.case_id, "request_ordinal": len(self.business_requests) + 1,
                          "business_request_sha256": hashlib.sha256(encoded).hexdigest(),
                          "output_schema_sha256": hashlib.sha256(json.dumps(snapshot.get("output_schema"), ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
                          "business_request": snapshot}
        self.business_requests.append(request_record)
        try:
            result = super().evaluate(request)
            self.parsed.append({"case_id": self.case_id, "task": request.get("task", "continuity_review"),
                                "contract_repair": bool(request.get("contract_repair")),
                                "business_request_sha256": request_record["business_request_sha256"],
                                "business_json": result.payload, "usage": {
                                    "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                                    "observed_response_input_tokens": result.observed_response_input_tokens,
                                    "observed_response_output_tokens": result.observed_response_output_tokens,
                                    "cost_cny": result.cost_cny}, "latency_ms": result.latency_ms})
            return result
        except Exception:
            raise


def begin(provider: ObservedProvider, case_id: str) -> tuple[int, int, int]:
    provider.case_id = case_id
    return len(provider.parsed), len(provider.http_events), len(provider.business_requests)


def observation(provider: ObservedProvider, start: tuple[int, int, int]) -> dict:
    parsed, http, business = start
    return {"model_outputs": provider.parsed[parsed:], "business_requests": provider.business_requests[business:],
            "http_attempts": provider.http_events[http:],
            "actual_http_dispatches": len(provider.http_events[http:]), "request_model": MODEL}


def g03_body(case: dict) -> str:
    if "target_body" in case:
        return case["target_body"]
    return (case["target_prefix_repeat"] * case["repeat_count"] + case["target_fact"] +
            case["target_suffix_repeat"] * case["suffix_count"])


def assert_business_input(case: dict, request: dict) -> None:
    """G03 case contract is checked before the actual Provider HTTP dispatch."""
    if request.get("task") != "change_impact":
        raise RuntimeError("g03_task_mismatch")
    memory_id = "fixture-memory-flash_v2_target-1"
    target_id = "fixture-span-flash_v2_target-1"
    other_id = "fixture-span-flash_v2_target-2"
    chapter_a = "fixture-chapter-flash_v2_target-1"
    chapter_b = "fixture-chapter-flash_v2_target-2"
    memory = {item["id"]: item for item in request["layers"]["confirmed"]["memory_records"]}
    spans = {item["id"]: item for item in request["layers"]["written"]["source_spans"]}
    chapters = {item["id"] for item in request["layers"]["reference"]["chapters"]}
    if memory_id not in memory or memory[memory_id].get("subject") != "星钥" or memory[memory_id].get("predicate") != "holder" or memory[memory_id].get("value") != "星钥始终由乔霁保管。" or memory[memory_id].get("source_span_id") != target_id:
        raise RuntimeError("g03_target_memory_contract_mismatch")
    if request.get("proposal", {}).get("target_id") != memory_id or target_id not in spans or other_id not in spans:
        raise RuntimeError("g03_target_or_other_source_not_selected")
    if spans[target_id].get("chapter_id") != chapter_a or spans[other_id].get("chapter_id") != chapter_b or {chapter_a, chapter_b} - chapters:
        raise RuntimeError("g03_source_chapter_binding_mismatch")
    if case["mode"] == "absent":
        if request["retrieval"]["target_source"]["status"] != "unlocated" or "星钥始终由乔霁保管。" in spans[target_id]["body"]:
            raise RuntimeError("g03_absent_source_contract_mismatch")
    elif (request["retrieval"]["target_source"]["status"] != "selected" or
          "星钥始终由乔霁保管。" not in spans[target_id]["body"]):
        raise RuntimeError("g03_target_fact_not_in_actual_request")
    if case["mode"] == "other_chapter" and case["other_body"] not in spans[other_id]["body"]:
        raise RuntimeError("g03_interfering_chapter_not_in_actual_request")


def isolated_app(provider, root):
    app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected-placeholder"),
                     provider=provider, executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
    from fastapi.testclient import TestClient
    client = TestClient(app)
    response = client.post("/api/auth/register", headers={"Idempotency-Key": str(uuid.uuid4())},
                           json={"account_name": "synthetic-evaluator", "display_name": "Synthetic Evaluator",
                                 "password": "local-synthetic-passphrase-26", "recovery_email": "synthetic@example.test"})
    if response.status_code != 201:
        raise RuntimeError("isolated_registration_failed:" + str(response.status_code))
    project_id = response.json()["data"]["onboarding"]["tutorial"]["project_id"]
    return app, client, project_id


def analysis(client, project_id, draft, analysis_type, proposal=None):
    body = {"analysis_type": analysis_type, "draft_id": draft["id"], "draft_revision": draft["revision"]}
    if proposal is not None:
        body["proposal"] = proposal
    response = client.post(f"/api/projects/{project_id}/analyses", headers={"Idempotency-Key": str(uuid.uuid4())}, json=body)
    if response.status_code != 202:
        raise RuntimeError("analysis_post_failed:" + str(response.status_code))
    run_id = response.json()["data"]["run_id"]
    view = client.get(f"/api/projects/{project_id}/analyses/{run_id}").json()["data"]
    return view


def g02_one(case, provider, root):
    start = begin(provider, case["id"])
    _, client, pid = isolated_app(provider, root)
    try:
        project = client.get(f"/api/projects/{pid}").json()["data"]
        draft = project["current_draft"]
        body = case_body(case)
        response = client.patch(f"/api/projects/{pid}/drafts/{draft['id']}", headers={"Idempotency-Key": str(uuid.uuid4())},
                                json={"base_revision": draft["revision"], "body": body})
        if response.status_code != 200:
            raise RuntimeError("draft_save_failed:" + str(response.status_code))
        draft = client.get(f"/api/projects/{pid}").json()["data"]["current_draft"]
        view = analysis(client, pid, draft, "context_brief")
        return {"family": "g02", "case_id": case["id"], "input": {"saved_draft": body}, "expected": case["expected"],
                "product": view, "semantic_item_review": "pending_independent_human_review", **observation(provider, start)}
    finally:
        client.close()


def g03_one(case, provider, root):
    start = begin(provider, case["id"])
    runtime = fixture_runtime_at(root, "flash_v2_target", provider, {"flash_v2_target": G03_CORPUS})
    app, client, pid = runtime.app, runtime.client, runtime.identity.project_id
    try:
        with app.state.database.connection() as connection:
            app.state.database._insert_empty_author_context_zero(connection, pid, stamp())
        project = client.get(f"/api/projects/{pid}").json()["data"]
        db = app.state.database
        memory_id = "fixture-memory-flash_v2_target-1"
        target_id = "fixture-span-flash_v2_target-1"
        other_id = "fixture-span-flash_v2_target-2"
        fact = "星钥始终由乔霁保管。"
        target_body = g03_body(case)
        with db.connection() as connection:
            target = connection.execute("SELECT * FROM v2_memory_records WHERE id=? AND project_id=? AND version=?",
                                        (memory_id, pid, project["current_memory_version"])).fetchone()
            if target is None or target["source_span_id"] != target_id:
                raise RuntimeError("g03_deterministic_target_missing")
            connection.execute("UPDATE v2_memory_records SET memory_type=?,subject=?,predicate=?,value=? WHERE id=?",
                               ("dynamic_state", "星钥", "holder", fact, memory_id))
            connection.execute("UPDATE v2_source_spans SET body=? WHERE id=? AND project_id=?", (target_body, target_id, pid))
            connection.execute("UPDATE v2_source_spans SET body=? WHERE id=? AND project_id=?", (case["other_body"], other_id, pid))
        draft = project["current_draft"]
        provider.expected_case = case
        view = analysis(client, pid, draft, "change_impact", {"target_type": "memory", "target_id": memory_id,
                                                               "proposed_change": "改为由沈砚保管星钥。"})
        observed = observation(provider, start)
        return {"family": "g03", "case_id": case["id"], "input": {"mode": case["mode"], "target_source_body": target_body,
                "other_source_body": case["other_body"], "target_memory_value": fact, "target_memory_predicate": "holder",
                "proposal": "改为由沈砚保管星钥。"}, "expected": case["expected"],
                "fixture_lineage": {"target_memory_id": memory_id, "target_source_span_id": target_id,
                                    "target_chapter_id": "fixture-chapter-flash_v2_target-1", "other_source_span_id": other_id,
                                    "other_chapter_id": "fixture-chapter-flash_v2_target-2"},
                "product": view, "semantic_item_review": "pending_independent_human_review", **observed}
    finally:
        provider.expected_case = None
        client.close()


def configured_provider() -> ObservedProvider:
    os.environ["CONTINUITY_PROVIDER"] = "deepseek"
    os.environ["CONTINUITY_MODEL"] = MODEL
    os.environ["CONTINUITY_BASE_URL"] = BASE_URL
    if not os.environ.get("CONTINUITY_API_KEY"):
        raise RuntimeError("CONTINUITY_API_KEY_missing")
    provider = ObservedProvider()
    if not provider.available:
        raise RuntimeError("provider_configuration_missing")
    return provider


def preflight_models(provider, run_dir):
    started = time.perf_counter()
    event = {"request": "GET /models", "status": None, "latency_ms": None, "model_present": False, "error_type": None}
    try:
        with httpx.Client(timeout=DeepSeekProvider.timeout_seconds) as client:
            response = client.get(BASE_URL + "/models", headers={"Authorization": "Bearer " + provider.api_key})
        event["status"] = response.status_code
        if response.status_code == 200:
            ids = [item.get("id") for item in response.json().get("data", []) if isinstance(item, dict)]
            event["model_present"] = MODEL in ids
        if response.status_code in (401, 403, 404) or not event["model_present"]:
            event["error_type"] = "authorization_or_model_unavailable"
    except Exception as error:
        event["error_type"] = type(error).__name__
    finally:
        event["latency_ms"] = int((time.perf_counter() - started) * 1000)
        write_new(run_dir / "models-preflight.json", event)
    if event["error_type"] or event["status"] != 200:
        raise RuntimeError("models_preflight_failed")


def service_failure(record: dict) -> bool:
    """Business schema/evidence failures do not count as service failures."""
    events = record.get("http_attempts", [])
    if any(e.get("error_type") not in {None, "response_json_unavailable"} or
           e.get("status") in {400, 401, 403, 404, 429} or
           (isinstance(e.get("status"), int) and e["status"] >= 500) for e in events):
        return True
    return record.get("product", {}).get("error_code") in {"provider_unavailable", "provider_error", "provider_timeout"}


def auth_or_model_rejection(record: dict) -> bool:
    return any(e.get("status") in {400, 401, 403, 404} for e in record.get("http_attempts", []))


def workspace_manifest(root: pathlib.Path) -> dict:
    databases = sorted(p for p in root.rglob("*.sqlite3") if p.is_file())
    return {"root": str(root), "git_ignored": True, "retained_for_controller_review": True,
            "database_files": [{"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": sha(p), "bytes": p.stat().st_size}
                               for p in databases]}


def run(run_id):
    verify_freeze()
    if not run_id.startswith("flash-v2-") or not all(ch.isalnum() or ch in "-_" for ch in run_id):
        raise RuntimeError("run_id_invalid")
    run_dir = RESULTS / run_id
    work_root = LOCAL_EVIDENCE / run_id
    if run_dir.exists() or work_root.exists():
        raise RuntimeError("run_id_or_workspace_already_exists")
    run_dir.mkdir(parents=True, exist_ok=False)
    work_root.mkdir(parents=True, exist_ok=False)
    write_new(run_dir / "start.json", {"run_id": run_id, "started_at": stamp(), "frozen_manifest_sha256": sha(MANIFEST),
                                       "git_base": "c3bd54ab019447354e8b1387e16b9aca3258b4c9",
                                       "model": MODEL, "provider": "deepseek", "local_evidence_root": str(work_root),
                                       "cost": "unavailable_unless_returned"})
    provider = configured_provider()
    preflight_models(provider, run_dir)
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    rows, failures = [], []
    consecutive_service_errors = 0
    sequence = [(group, case) for group in ("g02", "g03") for case in cases[group]]
    for index, (family, case) in enumerate(sequence, 1):
        case_id = case["id"]
        try:
            record = g02_one(case, provider, work_root / case_id) if family == "g02" else g03_one(case, provider, work_root / case_id)
            record["input_sha256"] = hashlib.sha256(json.dumps(case, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode("utf-8")).hexdigest()
            record["source_case_ref"] = "evaluation/current_flash_v2/cases.json"
            record["business_input_count"] = len(record["business_requests"])
            consecutive_service_errors = consecutive_service_errors + 1 if service_failure(record) else 0
            rows.append(record)
            write_new(run_dir / "cases" / f"{index:02d}-{case_id}.json", record)
            if auth_or_model_rejection(record) or consecutive_service_errors >= 2:
                failures.append({"case_id": case_id, "type": "service_stop", "consecutive_service_errors": consecutive_service_errors})
                break
        except Exception as error:
            failure = {"family": family, "case_id": case_id, "error_type": type(error).__name__,
                       "http_attempts": [x for x in provider.http_events if x["case_id"] == provider.case_id],
                       "business_requests": [x for x in provider.business_requests if x["case_id"] == provider.case_id],
                       "model_outputs": [x for x in provider.parsed if x["case_id"] == provider.case_id]}
            failures.append(failure)
            write_new(run_dir / "failures" / f"{index:02d}-{case_id}.json", failure)
            break
    events = provider.http_events
    write_new(run_dir / "workspace-manifest.json", workspace_manifest(work_root))
    prompt_known = [e["usage"]["prompt_tokens"] for e in events if e.get("usage") and e["usage"]["prompt_tokens"] is not None]
    completion_known = [e["usage"]["completion_tokens"] for e in events if e.get("usage") and e["usage"]["completion_tokens"] is not None]
    usage_complete = bool(events) and all(e["usage_status"] == "complete" for e in events)
    write_new(run_dir / "summary.json", {"run_id": run_id, "ended_at": stamp(), "executed_case_records": len(rows),
              "family_counts": {g: sum(r["family"] == g for r in rows) for g in ("g02", "g03")},
              "actual_http_dispatches": len(events), "successful_http_responses": sum(e["status"] == 200 for e in events),
              "complete_usage_attempts": sum(e["usage_status"] == "complete" for e in events),
              "usage_unknown_attempts": sum(e["usage_status"] != "complete" for e in events),
              "known_prompt_tokens_partial_sum": sum(prompt_known), "known_completion_tokens_partial_sum": sum(completion_known),
              "complete_total_usage_available": usage_complete,
              "prompt_tokens_total": sum(prompt_known) if usage_complete else None,
              "completion_tokens_total": sum(completion_known) if usage_complete else None,
              "cost": "unavailable", "failures": failures, "all_attempt_metadata": events,
              "open_ended_semantic_review": "pending_controller_independent_review"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify", "run"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "verify":
        verify_freeze()
    else:
        if not args.run_id:
            raise SystemExit("--run-id required")
        run(args.run_id)
    print(json.dumps({"command": args.command, "ok": True, "run_id": args.run_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
