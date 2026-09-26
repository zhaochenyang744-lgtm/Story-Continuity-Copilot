"""Independent, append-only current-code evaluation. Never imports the V8 executor."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
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
from app.engine import ContinuityEngine, WritingAnalysisEngine, PROMPT_VERSION, CONTEXT_BRIEF_PROMPT_VERSION, CHANGE_IMPACT_PROMPT_VERSION
from app.main import create_app
from app.provider import DeepSeekProvider
from app.stage13 import Stage13Settings
from evaluation.metrics import aggregate, prediction_for_target, stability
from evaluation.run_eval import ApiResponseScanner, FormalCheckpoint, repeat_case, run_case
from evaluation.v2_fixture_loader import V8_CORPUS_PATHS, fixture_runtime_at

V8_CASES = ROOT / "evaluation/case_sets/eval-set-v8.json"
V8_MANIFEST = ROOT / "evaluation/manifests/eval-set-v8-manifest.json"
V8_CORPUS_MANIFEST = ROOT / "evaluation/fixtures/eval-v8-corpus-manifest.json"
MANIFEST = HERE / "frozen-inputs.json"
RESULTS = HERE / "runs"
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
    return [HERE / "cases.json", HERE / "run.py", HERE / "test_offline.py", HERE / "PLAN.md",
            V8_CASES, V8_MANIFEST, V8_CORPUS_MANIFEST,
            *V8_CORPUS_PATHS.values(), ROOT / "backend/app/provider.py", ROOT / "backend/app/engine.py",
            ROOT / "backend/app/v2_database.py", ROOT / "backend/app/main.py",
            ROOT / "backend/app/stage13.py", ROOT / "evaluation/metrics.py",
            ROOT / "evaluation/run_eval.py", ROOT / "evaluation/v2_fixture_loader.py"]


def validate_cases(cases: dict) -> None:
    v8 = json.loads(V8_CASES.read_text(encoding="utf-8"))["cases"]
    protocol = json.loads(V8_MANIFEST.read_text(encoding="utf-8"))["stability_protocol"]
    assert len(v8) == 24 and {c["expected_class"] for c in v8} == {"conflict", "no_conflict", "insufficient_evidence"}
    assert (len(protocol["representative_case_ids"]), protocol["independent_runs_per_case"], protocol["additional_calls_after_formal"]) == (3, 3, 6)
    assert all(x in {c["case_id"] for c in v8} for x in protocol["representative_case_ids"])
    assert tuple(len(cases[k]) for k in ("g01", "g02", "g03")) == (10, 4, 4)
    all_ids = [c.get("id") for group in ("g01", "g02", "g03") for c in cases[group]]
    assert len(all_ids) == len(set(all_ids))
    assert len({case_body(c) for c in cases["g02"]}) == 4


def freeze() -> None:
    if MANIFEST.exists():
        raise RuntimeError("frozen_inputs_already_exist")
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    validate_cases(cases)
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in source_paths()}
    write_new(MANIFEST, {"version": "current-flash-v1", "frozen_at": stamp(), "source_hashes": hashes,
        "model": MODEL, "base_url": BASE_URL, "provider": "deepseek", "thinking": "disabled",
        "temperature": 0, "max_tokens": DeepSeekProvider.max_output_tokens,
        "provider_timeout_seconds": DeepSeekProvider.timeout_seconds,
        "provider_max_retries": DeepSeekProvider.max_retries,
        "prompt_versions": {"continuity": PROMPT_VERSION, "context_brief": CONTEXT_BRIEF_PROMPT_VERSION,
                            "change_impact": CHANGE_IMPACT_PROMPT_VERSION},
        "v8_case_count": 24, "v8_stability_additional": 6, "special_case_count": 18,
        "scoring": "V8 original labels, evaluation.metrics.aggregate and V8 required_thresholds; G01 first semantics against frozen labels; G02/G03 item-level human review pending",
        "adaptations": ["new output identity and current provider/prompt; old V8 result remains historical",
                        "G01 compatible-time labels are no_conflict, separate from final conservative downgrade",
                        "G02 repeated fake-output variants become one real input; duplicate bodies removed",
                        "G03 absent-target may fail closed before dispatch and is counted as a zero-HTTP product case"],
        "boundaries": {"exposed_fixed_regression": True, "unseen_or_blind": False, "safety_fake_not_model_accuracy": True,
                       "historical_12_pack": "not_located_in_this_checkout"}})


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
                 "response_model": None, "system_fingerprint": None, "finish_reason": None,
                 "error_type": None}
        started = time.perf_counter()
        try:
            response = self.client.post(url, **kwargs)
            event["status"] = response.status_code
            try:
                body = response.json()
                if response.status_code < 400 and isinstance(body, dict):
                    event["usage"] = {key: body.get("usage", {}).get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
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

    def evaluate(self, request):
        try:
            result = super().evaluate(request)
            written = request.get("layers", {}).get("written", {})
            input_refs = {"claims": request.get("claims", []),
                          "draft_claims": written.get("draft_claims", []),
                          "source_spans": written.get("source_spans", []),
                          "retrieval": request.get("retrieval"),
                          "proposal": request.get("proposal")}
            self.parsed.append({"case_id": self.case_id, "task": request.get("task", "continuity_review"),
                                "contract_repair": bool(request.get("contract_repair")),
                                "input_refs": input_refs,
                                "business_json": result.payload, "usage": {
                                    "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                                    "observed_response_input_tokens": result.observed_response_input_tokens,
                                    "observed_response_output_tokens": result.observed_response_output_tokens,
                                    "cost_cny": result.cost_cny}, "latency_ms": result.latency_ms})
            return result
        except Exception:
            raise


def begin(provider: ObservedProvider, case_id: str) -> tuple[int, int]:
    provider.case_id = case_id
    return len(provider.parsed), len(provider.http_events)


def observation(provider: ObservedProvider, start: tuple[int, int]) -> dict:
    parsed, http = start
    return {"model_outputs": provider.parsed[parsed:], "http_attempts": provider.http_events[http:],
            "actual_http_dispatches": len(provider.http_events[http:]), "request_model": MODEL}


def raw_prediction(payload) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
        return None, None
    issues = payload["issues"]
    if not issues:
        return "no_conflict", None
    first = issues[0]
    if not isinstance(first, dict):
        return None, None
    nature = first.get("nature")
    status = first.get("status")
    return ("conflict" if nature == "confirmed_conflict" or status == "conflict" else
            "insufficient_evidence" if nature == "insufficient_evidence" or status == "insufficient_evidence" else None,
            first.get("category"))


def prepare_current_fixture(runtime):
    """Bring the old synthetic corpus up to the current empty author snapshot contract."""
    with runtime.app.state.database.connection() as connection:
        runtime.app.state.database._insert_empty_author_context_zero(connection, runtime.identity.project_id, stamp())


def v8_one(case, provider, work_root, checkpoint, scanner):
    start = begin(provider, case["case_id"])
    runtime = fixture_runtime_at(work_root / case["case_id"], case["corpus_key"], provider, V8_CORPUS_PATHS)
    try:
        prepare_current_fixture(runtime)
        row, context = run_case(checkpoint, runtime.client, case, scanner, preloaded_project_id=runtime.identity.project_id)
        terminal = runtime.client.get(f"/api/projects/{context['project_id']}/checks/{context['run_id']}?include=issues,evidence,metrics").json()["data"]
        return {"family": "v8", "case_id": case["case_id"], "input_sha256": hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "expected": {"class": case["expected_class"], "category": case.get("expected_category"), "evidence": case["expected_evidence"]},
                "score_row": row, "product": terminal, **observation(provider, start)}
    finally:
        runtime.client.close()


def g01_one(case, provider):
    start = begin(provider, case["id"])
    data = {"draft": {"id": "synthetic-draft", "revision": 1, "body": case["claim"]},
            "claims": [{"id": "claim-1", "text": case["claim"], "allowed_evidence": [{"id": "span-1", "chapter_id": "chapter-1", "body": case["evidence"], "prompt_excerpt": case["evidence"]}]}], "memory": []}
    product = ContinuityEngine(provider).execute(data)
    observed = observation(provider, start)
    first = raw_prediction(observed["model_outputs"][0]["business_json"]) if observed["model_outputs"] else (None, None)
    final = raw_prediction(observed["model_outputs"][-1]["business_json"]) if observed["model_outputs"] else (None, None)
    product_class = raw_prediction({"issues": product.get("issues", [])})[0] if product.get("status") == "completed" else None
    return {"family": "g01", "case_id": case["id"], "input": {"claim": case["claim"], "evidence": case["evidence"]},
            "expected": case["expected"], "first_model_class": first[0], "first_semantic_correct": first[0] == case["expected"],
            "last_model_class": final[0], "product_class": product_class, "product": product, **observed}


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
    app, client, pid = isolated_app(provider, root)
    try:
        project = client.get(f"/api/projects/{pid}").json()["data"]
        db = app.state.database
        with db.connection() as connection:
            target = dict(connection.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=? AND source_span_id IS NOT NULL LIMIT 1",
                                             (pid, project["current_memory_version"])).fetchone())
            sid = target["source_span_id"]
            span = dict(connection.execute("SELECT * FROM v2_source_spans WHERE id=?", (sid,)).fetchone())
            fact = "星钥始终由乔霁保管。"
            target_body = ("晴日里，绒草覆盖山坡。" * 100 if case["mode"] in {"deep", "other_chapter"} else "")
            target_body += (fact if case["mode"] != "absent" else "山坡上没有关于星钥保管者的记载。")
            target_body += "平静的溪水流过石桥。" * (40 if case["mode"] in {"deep", "other_chapter"} else 1)
            connection.execute("UPDATE v2_memory_records SET subject=?,value=? WHERE id=?", ("星钥", fact, target["id"]))
            connection.execute("UPDATE v2_source_spans SET body=?,label=? WHERE id=?", (target_body, "星钥保管说明", sid))
            if case["mode"] == "other_chapter":
                other = connection.execute("SELECT id FROM v2_chapters WHERE project_id=? AND id<>? LIMIT 1", (pid, span["chapter_id"])).fetchone()
                if other:
                    connection.execute("UPDATE v2_source_spans SET body=? WHERE chapter_id=? AND project_id=?",
                                       ("另一章只记载沈砚经过石桥，没有星钥归属事实。", other["id"], pid))
        draft = project["current_draft"]
        view = analysis(client, pid, draft, "change_impact", {"target_type": "memory", "target_id": target["id"],
                                                               "proposed_change": "改为由沈砚保管星钥。"})
        observed = observation(provider, start)
        return {"family": "g03", "case_id": case["id"], "input": {"mode": case["mode"], "target_source_body": target_body,
                "target_memory_value": fact, "proposal": "改为由沈砚保管星钥。"}, "expected": case["expected"],
                "target_source_span_id": sid, "product": view, "semantic_item_review": "pending_independent_human_review", **observed}
    finally:
        client.close()


def stability_one(case, provider, work_root, ordinal):
    case_id = case["case_id"]
    start = begin(provider, case_id + f":stability:{ordinal}")
    runtime = fixture_runtime_at(work_root / f"{case_id}-stability-{ordinal}", case["corpus_key"], provider, V8_CORPUS_PATHS)
    try:
        prepare_current_fixture(runtime)
        from evaluation.run_eval import ApiResponseScanner, FormalCheckpoint
        checkpoint = FormalCheckpoint(work_root / f"{case_id}-stability-{ordinal}-checkpoint.json", "independent-stability")
        row, _ = run_case(checkpoint, runtime.client, case, ApiResponseScanner(), preloaded_project_id=runtime.identity.project_id)
        return {"family": "v8_stability", "case_id": case_id, "repeat_ordinal": ordinal,
                "score_row": row, **observation(provider, start)}
    finally:
        runtime.client.close()


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


def run(run_id):
    frozen = verify_freeze()
    if not run_id.startswith("flash-v1-") or not all(ch.isalnum() or ch in "-_" for ch in run_id):
        raise RuntimeError("run_id_invalid")
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    write_new(run_dir / "start.json", {"run_id": run_id, "started_at": stamp(), "frozen_manifest_sha256": sha(MANIFEST),
                                       "git_base": "c3bd54ab019447354e8b1387e16b9aca3258b4c9",
                                       "model": MODEL, "provider": "deepseek", "cost": "unavailable_unless_returned"})
    provider = configured_provider()
    preflight_models(provider, run_dir)
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    v8 = json.loads(V8_CASES.read_text(encoding="utf-8"))["cases"]
    v8_manifest = json.loads(V8_MANIFEST.read_text(encoding="utf-8"))
    checkpoint = FormalCheckpoint(run_dir / "v8-checkpoint.json", frozen["source_hashes"]["evaluation/case_sets/eval-set-v8.json"])
    scanner = ApiResponseScanner()
    rows = []
    failures = []
    work_root = pathlib.Path(tempfile.mkdtemp(prefix="scc-flash-v1-"))
    try:
        sequence = [("v8", c) for c in v8] + [(group, c) for group in ("g01", "g02", "g03") for c in cases[group]]
        representatives = {c["case_id"]: c for c in v8 if c["case_id"] in v8_manifest["stability_protocol"]["representative_case_ids"]}
        sequence += [("v8_stability", (c, n)) for c in representatives.values() for n in (2, 3)]
        consecutive_service_errors = 0
        for index, (family, case) in enumerate(sequence, 1):
            case_id = case[0]["case_id"] + f"-repeat-{case[1]}" if family == "v8_stability" else case.get("case_id", case.get("id"))
            try:
                if family == "v8":
                    record = v8_one(case, provider, work_root, checkpoint, scanner)
                elif family == "g01":
                    record = g01_one(case, provider)
                elif family == "g02":
                    record = g02_one(case, provider, work_root / case_id)
                elif family == "g03":
                    record = g03_one(case, provider, work_root / case_id)
                else:
                    record = stability_one(case[0], provider, work_root, case[1])
                original_case = case[0] if family == "v8_stability" else case
                record.setdefault("input_sha256", hashlib.sha256(json.dumps(original_case, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")).encode("utf-8")).hexdigest())
                if isinstance(original_case, dict):
                    record["source_case_ref"] = original_case.get("source", "evaluation/case_sets/eval-set-v8.json")
                terminal = record.get("score_row", record.get("product", {}))
                status = terminal.get("terminal_status", terminal.get("status"))
                if status in {"provider_unavailable", "provider_error", "timed_out", "failed"} or terminal.get("terminal_error_code") in {"provider_unavailable", "provider_error", "provider_timeout"}:
                    consecutive_service_errors += 1
                else:
                    consecutive_service_errors = 0
                rows.append(record)
                write_new(run_dir / "cases" / f"{index:02d}-{case_id}.json", record)
                if consecutive_service_errors >= 2:
                    failures.append({"case_id": case_id, "type": "consecutive_service_errors"})
                    break
            except Exception as error:
                failure = {"family": family, "case_id": case_id, "error_type": type(error).__name__,
                           "http_attempts": [x for x in provider.http_events if x["case_id"] == provider.case_id],
                           "model_outputs": [x for x in provider.parsed if x["case_id"] == provider.case_id]}
                failures.append(failure)
                write_new(run_dir / "failures" / f"{index:02d}-{case_id}.json", failure)
                if failure["http_attempts"] or family == "v8":
                    break
        v8_rows = [r["score_row"] for r in rows if r["family"] == "v8"]
        metrics = aggregate(v8_rows) if len(v8_rows) == 24 else None
        first_v8 = []
        for record in rows:
            if record["family"] != "v8":
                continue
            first = raw_prediction(record["model_outputs"][0]["business_json"]) if record["model_outputs"] else (None, None)
            first_v8.append({"case_id": record["case_id"], "expected": record["expected"]["class"], "first": first[0],
                             "correct": first[0] == record["expected"]["class"]})
        all_http = provider.http_events
        usages = [e["usage"] for e in all_http if e["usage"]]
        write_new(run_dir / "summary.json", {"run_id": run_id, "ended_at": stamp(), "executed_case_records": len(rows),
                  "v8_formal_count": len(v8_rows), "v8_stability_additional": sum(r["family"] == "v8_stability" for r in rows),
                  "special_counts": {g: sum(r["family"] == g for r in rows) for g in ("g01", "g02", "g03")},
                  "v8_product_metrics": metrics, "v8_first_model": first_v8,
                  "g01_first_correct": sum(r.get("first_semantic_correct", False) for r in rows if r["family"] == "g01"),
                  "actual_http_dispatches": len(all_http), "successful_http_responses": sum(e["status"] == 200 for e in all_http),
                  "known_prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in usages),
                  "known_completion_tokens": sum(u.get("completion_tokens") or 0 for u in usages),
                  "usage_unknown_attempts": sum(e["usage"] is None for e in all_http), "cost": "unavailable",
                  "failures": failures, "all_attempt_metadata": all_http,
                  "quality_gate_evaluated": False if len(v8_rows) != 24 else "pending_independent_review"})
    finally:
        # Temporary database/session roots are deliberately outside Git and not retained.
        import shutil
        shutil.rmtree(work_root)


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
