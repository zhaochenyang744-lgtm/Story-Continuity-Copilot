"""Run the once-only formal V1 evaluation through the production 24 API."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from evaluation.metrics import aggregate, prediction_for_target, stability
from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import CORPUS_PATHS, V3_CORPUS_PATHS, V4_CORPUS_PATHS, V5_CORPUS_PATHS, V6_CORPUS_PATHS, V7_CORPUS_PATHS, V8_CORPUS_PATHS, corpus_manifest_payload, fixture_runtime_at


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v1-manifest.json"
RESULTS = ROOT / "evaluation" / "results"
FORMAL = RESULTS / "first-formal-results.json"
STABILITY = RESULTS / "first-formal-stability.json"
REPORT = RESULTS / "first-formal-report.md"
BAD_CASES = RESULTS / "first-formal-bad-cases.json"
RUN_MANIFEST = RESULTS / "first-formal-run-manifest.json"
API_SCAN = RESULTS / "first-formal-api-corpus-scan.json"
SAFETY = RESULTS / "fail-closed-contract.json"
EVALUATION_ROOT = ROOT / "evaluation"
PREFIX_RE = re.compile(r"^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?$")
REMOTE_SEED_MODE = "remote_seed"
EVALUATION_FIXTURE_MODE = "evaluation_fixture"
RUNTIME_MODES = (REMOTE_SEED_MODE, EVALUATION_FIXTURE_MODE)


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvaluationRunConfig:
    """Paths and identity for one formal evaluation; all paths stay in evaluation/."""

    def __init__(self, evaluation_id: str, case_set_path: pathlib.Path, manifest_path: pathlib.Path, result_prefix: str, checkpoint_path: pathlib.Path) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", evaluation_id):
            raise ValueError("evaluation_id_invalid")
        if not PREFIX_RE.fullmatch(result_prefix):
            raise ValueError("result_prefix_invalid")
        self.evaluation_id = evaluation_id
        self.case_set_path = case_set_path
        self.manifest_path = manifest_path
        self.result_prefix = result_prefix
        self.checkpoint_path = checkpoint_path

    @property
    def artifacts(self) -> dict[str, pathlib.Path]:
        return {
            "formal": RESULTS / f"{self.result_prefix}-results.json",
            "stability": RESULTS / f"{self.result_prefix}-stability.json",
            "report": RESULTS / f"{self.result_prefix}-report.md",
            "bad_cases": RESULTS / f"{self.result_prefix}-bad-cases.json",
            "run_manifest": RESULTS / f"{self.result_prefix}-run-manifest.json",
            "api_scan": RESULTS / f"{self.result_prefix}-api-corpus-scan.json",
        }


def evaluation_path(value: str) -> pathlib.Path:
    """Resolve a user argument without allowing an absolute or escaping path."""
    raw = pathlib.PurePath(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("evaluation_path_must_be_relative_and_contained")
    path = (ROOT / raw).resolve()
    evaluation_root = EVALUATION_ROOT.resolve()
    if path != evaluation_root and evaluation_root not in path.parents:
        raise ValueError("evaluation_path_outside_evaluation_directory")
    return path


def build_run_config(evaluation_id: str, case_set: str, manifest: str, result_prefix: str, checkpoint_path: str | None = None) -> EvaluationRunConfig:
    case_set_path = evaluation_path(case_set)
    manifest_path = evaluation_path(manifest)
    checkpoint = evaluation_path(checkpoint_path) if checkpoint_path else RESULTS / f"{result_prefix}-checkpoint.json"
    results_root = RESULTS.resolve()
    if results_root not in checkpoint.resolve().parents:
        raise ValueError("checkpoint_path_must_be_within_evaluation_results")
    return EvaluationRunConfig(evaluation_id, case_set_path, manifest_path, result_prefix, checkpoint)


def assert_outputs_safe(config: EvaluationRunConfig) -> None:
    frozen_v1 = {FORMAL.resolve(), STABILITY.resolve(), REPORT.resolve(), BAD_CASES.resolve(), RUN_MANIFEST.resolve(), API_SCAN.resolve()}
    output_paths = {name: path.resolve() for name, path in config.artifacts.items()}
    if any(path in frozen_v1 for path in output_paths.values()):
        raise RuntimeError("frozen_v1_output_path_refused")
    if config.checkpoint_path.resolve() == (RESULTS / "first-formal-checkpoint.json").resolve():
        raise RuntimeError("frozen_v1_checkpoint_path_refused")
    if any(path.exists() for path in output_paths.values()):
        raise RuntimeError("formal_evaluation_artifacts_already_exist")


def load_case_payload(path: pathlib.Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("schema_version"), str) or not isinstance(payload.get("cases"), list):
        raise ValueError("invalid_case_set_schema")
    return payload


def source_hashes_for_config(config: EvaluationRunConfig, runtime_mode: str = REMOTE_SEED_MODE, corpus_manifest_path: pathlib.Path | None = None) -> dict[str, str]:
    """Keep the V1 provenance set stable; fixture runs add their isolated corpus inputs."""
    paths = (
        ROOT / "backend/app/v2_database.py",
        ROOT / "backend/app/engine.py",
        ROOT / "backend/app/provider.py",
        config.case_set_path,
        ROOT / "evaluation/run_eval.py",
    )
    if runtime_mode == EVALUATION_FIXTURE_MODE:
        if corpus_manifest_path is None:
            raise ValueError("fixture_corpus_manifest_required")
        corpus_paths = fixture_corpus_paths(corpus_manifest_path)
        paths = paths + (
            config.manifest_path,
            corpus_manifest_path,
            *(corpus_paths[key] for key in sorted(corpus_paths)),
            ROOT / "evaluation/v2_fixture_loader.py",
        )
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in paths}


def assert_manifest_approved(manifest: dict) -> None:
    if manifest.get("status") != "approved_for_formal_run":
        raise RuntimeError("evaluation_manifest_not_approved_for_formal_run")


def fixture_corpus_manifest_path(manifest: dict) -> pathlib.Path:
    fixture = manifest.get("fixture_corpus")
    if not isinstance(fixture, dict) or not isinstance(fixture.get("path"), str):
        raise RuntimeError("fixture_corpus_manifest_required")
    return evaluation_path(fixture["path"])


def fixture_corpus_paths(corpus_manifest_path: pathlib.Path) -> dict[str, pathlib.Path]:
    resolved = corpus_manifest_path.resolve()
    if resolved == (ROOT / "evaluation" / "fixtures" / "eval-v2-corpus-manifest.json").resolve():
        return CORPUS_PATHS
    if resolved == (ROOT / "evaluation" / "fixtures" / "eval-v3-corpus-manifest.json").resolve():
        return V3_CORPUS_PATHS
    if resolved == (ROOT / "evaluation" / "fixtures" / "eval-v4-corpus-manifest.json").resolve():
        return V4_CORPUS_PATHS
    if resolved == (ROOT / "evaluation" / "fixtures" / "eval-v5-corpus-manifest.json").resolve():
        return V5_CORPUS_PATHS
    if resolved == (ROOT / "evaluation" / "fixtures" / "eval-v6-corpus-manifest.json").resolve():
        return V6_CORPUS_PATHS
    if resolved == (ROOT / "evaluation" / "fixtures" / "eval-v7-corpus-manifest.json").resolve():
        return V7_CORPUS_PATHS
    if resolved == (ROOT / "evaluation" / "fixtures" / "eval-v8-corpus-manifest.json").resolve():
        return V8_CORPUS_PATHS
    raise RuntimeError("fixture_corpus_manifest_not_formally_recognized")


def verify_fixture_inputs(cases_payload: dict, manifest: dict) -> pathlib.Path:
    """Fail before checkpoint, database, account, or provider side effects."""
    corpus_path = fixture_corpus_manifest_path(manifest)
    if not corpus_path.exists():
        raise RuntimeError("fixture_corpus_manifest_missing")
    stored = json.loads(corpus_path.read_text(encoding="utf-8"))
    expected = corpus_manifest_payload(fixture_corpus_paths(corpus_path))
    fixture = manifest["fixture_corpus"]
    if fixture.get("canonical_sha256") != expected["canonical_sha256"] or stored != expected:
        raise RuntimeError("fixture_corpus_hash_mismatch")
    if not all(fixture.get(field) is expected[field] for field in ("evaluation_only", "production_seed", "protected_asset_source")):
        raise RuntimeError("fixture_corpus_boundary_invalid")
    corpus_keys = {item.get("corpus_key") for item in stored.get("files", [])}
    for case in cases_payload["cases"]:
        if case.get("corpus_key") not in corpus_keys or case.get("seed_key") != case.get("corpus_key"):
            raise RuntimeError("fixture_case_corpus_not_found")
    return corpus_path


def fixture_work_root(value: str | None, evaluation_id: str) -> pathlib.Path:
    """A case workspace is evaluation-owned and can never target demo runtime data."""
    if value is None:
        root = EVALUATION_ROOT / "fixture-workspaces" / evaluation_id
    else:
        root = evaluation_path(value)
    return assert_fixture_work_root(root)


def assert_fixture_work_root(root: pathlib.Path) -> pathlib.Path:
    root = root.resolve()
    demo_db = (ROOT / "runtime" / "data" / "demo.sqlite3").resolve()
    allowed = (EVALUATION_ROOT.resolve(), pathlib.Path(tempfile.gettempdir()).resolve())
    if root == EVALUATION_ROOT.resolve() or root == demo_db or demo_db in root.parents or root == (ROOT / "runtime").resolve():
        raise RuntimeError("fixture_work_root_forbidden")
    if not any(root == parent or parent in root.parents for parent in allowed):
        raise RuntimeError("fixture_work_root_outside_evaluation_or_temp")
    return root


class FixtureRuntimeAdapter:
    """One persistent, isolated production-app runtime per fixture Case."""

    def __init__(self, evaluation_id: str, work_root: pathlib.Path, provider: Any, corpus_paths: dict[str, pathlib.Path]) -> None:
        self.evaluation_id = evaluation_id
        self.work_root = work_root
        self.provider = provider
        self.corpus_paths = corpus_paths
        self.runtimes: dict[str, Any] = {}

    def open_case(self, case: dict) -> Any:
        case_id = case["case_id"]
        if case_id in self.runtimes:
            return self.runtimes[case_id]
        safe = hashlib.sha256(f"{self.evaluation_id}:{case_id}".encode("utf-8")).hexdigest()[:24]
        runtime = fixture_runtime_at(self.work_root / safe, case["corpus_key"], self.provider, corpus_paths=self.corpus_paths)
        self.runtimes[case_id] = runtime
        return runtime

    def close(self) -> None:
        for runtime in self.runtimes.values():
            runtime.client.close()


def headers(key: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": key or str(uuid.uuid4())}


def runner_account_name(case_id: str) -> str:
    return "eval-" + hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:20]


def runner_password(case_id: str) -> str:
    return "local-eval-" + hashlib.sha256(("password:" + case_id).encode("utf-8")).hexdigest()[:24]


def atomic_write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as temporary:
        temporary.write(encoded)
        temporary_path = pathlib.Path(temporary.name)
    os.replace(temporary_path, path)


class FormalCheckpoint:
    """Atomic, resumable Case state; it never contains an auth token or prompt."""

    STATE_ORDER = {"intent": 0, "account_ready": 1, "draft_ready": 2, "check_queued": 3, "run_terminal": 4, "completed": 5}

    def __init__(self, path: pathlib.Path, case_set_sha256: str) -> None:
        self.path = path
        self.case_set_sha256 = case_set_sha256
        self.payload = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": "scc-evaluation-checkpoint-v2", "case_set_sha256": self.case_set_sha256, "cases": {}}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "scc-evaluation-checkpoint-v2" or payload.get("case_set_sha256") != self.case_set_sha256 or not isinstance(payload.get("cases"), dict):
            raise RuntimeError("checkpoint_schema_or_case_set_mismatch")
        return payload

    def case(self, case_id: str) -> dict[str, Any] | None:
        value = self.payload["cases"].get(case_id)
        return value if isinstance(value, dict) else None

    def ensure_intent(self, case: dict[str, Any]) -> dict[str, Any]:
        existing = self.case(case["case_id"])
        intent = {"case_id": case["case_id"], "seed_key": case["seed_key"], "target_draft_sha256": hashlib.sha256(case["target_draft"].encode("utf-8")).hexdigest(), "account_name": runner_account_name(case["case_id"]), "check_idempotency_key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"scc-eval:{self.case_set_sha256}:{case['case_id']}:check")), "client_request_id": "eval:" + hashlib.sha256((self.case_set_sha256 + ":" + case["case_id"]).encode("utf-8")).hexdigest()[:20], "state": "intent"}
        if existing is not None:
            if {key: existing.get(key) for key in intent if key != "state"} != {key: intent[key] for key in intent if key != "state"}:
                raise RuntimeError("checkpoint_case_intent_mismatch")
            return existing
        candidate = json.loads(json.dumps(self.payload, ensure_ascii=False))
        candidate["cases"][case["case_id"]] = intent
        atomic_write_json(self.path, candidate)
        self.payload = candidate
        return intent

    def advance(self, case_id: str, state: str, **fields: Any) -> dict[str, Any]:
        current = self.case(case_id)
        if current is None or state not in self.STATE_ORDER:
            raise RuntimeError("checkpoint_state_invalid")
        if self.STATE_ORDER[state] < self.STATE_ORDER[current["state"]]:
            return current
        if current["state"] == "completed" and state != "completed":
            return current
        for key, value in fields.items():
            if key in current and current[key] != value:
                raise RuntimeError("checkpoint_field_conflict")
        candidate = json.loads(json.dumps(self.payload, ensure_ascii=False))
        candidate_case = candidate["cases"][case_id]
        candidate_case.update(fields)
        candidate_case["state"] = state
        atomic_write_json(self.path, candidate)
        self.payload = candidate
        return candidate_case

    def completed(self, case_id: str) -> dict[str, Any] | None:
        value = self.case(case_id)
        return value if value and value.get("state") == "completed" else None

    def record_completed(self, case_id: str, result: dict[str, Any]) -> dict[str, Any]:
        existing = self.completed(case_id)
        if existing is not None:
            if existing.get("result") != result: raise RuntimeError("checkpoint_completed_result_conflict")
            return existing
        return self.advance(case_id, "completed", result=result)


def safe_error(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", {}).get("code", "http_error"))
    except ValueError:
        return "http_error"


class ApiResponseScanner:
    def __init__(self) -> None:
        self.response_count = 0
        self.categories = {"secret_value": 0, "authorization_value": 0, "prompt_body": 0, "raw_provider_body": 0, "chain_of_thought": 0}

    def scan(self, payload: Any) -> None:
        self.response_count += 1
        def walk(value: Any, key: str = "") -> None:
            lowered = key.casefold()
            if "authorization" in lowered and value: self.categories["authorization_value"] += 1
            if lowered in {"prompt", "prompt_body"} and value: self.categories["prompt_body"] += 1
            if "raw_provider" in lowered or lowered in {"provider_body", "raw_body"}: self.categories["raw_provider_body"] += 1
            if "reasoning_content" in lowered or "chain_of_thought" in lowered: self.categories["chain_of_thought"] += 1
            if isinstance(value, str) and ("-----BEGIN " in value or value.startswith("sk-") or "Bearer " in value): self.categories["secret_value"] += 1
            if isinstance(value, dict):
                for child_key, child_value in value.items(): walk(child_value, str(child_key))
            elif isinstance(value, list):
                for child in value: walk(child, key)
        walk(payload)

    def result(self) -> dict[str, Any]:
        return {"scanned_in_memory": True, "response_count": self.response_count, "categories": self.categories, "unresolved": sum(self.categories.values())}


def request_json(client: httpx.Client, method: str, path: str, scanner: ApiResponseScanner | None = None, **kwargs: Any) -> dict:
    response = client.request(method, path, **kwargs)
    body = response.json()
    if scanner: scanner.scan(body)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed: {response.status_code}:{body.get('error', {}).get('code', 'http_error')}")
    return body["data"]


def project_span_map(client: httpx.Client, project_id: str, scanner: ApiResponseScanner) -> tuple[dict[str, tuple[int, str]], dict[tuple[int, str], str]]:
    chapters = request_json(client, "GET", f"/api/projects/{project_id}/chapters?include=excerpt", scanner)
    by_id, by_semantic = {}, {}
    for chapter in chapters["chapters"]:
        for span in chapter["source_spans"]:
            semantic = (chapter["number"], span["label"])
            by_id[span["span_id"]] = semantic
            by_semantic[semantic] = span["span_id"]
    return by_id, by_semantic


def wait_for_terminal(client: httpx.Client, project_id: str, run_id: str, scanner: ApiResponseScanner) -> dict:
    for _ in range(60):
        run = request_json(client, "GET", f"/api/projects/{project_id}/checks/{run_id}?include=issues,evidence,metrics", scanner)
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(1)
    raise RuntimeError("run_poll_timeout")


def register_or_login_case(client: httpx.Client, intent: dict[str, Any], scanner: ApiResponseScanner) -> None:
    account = intent["account_name"]
    password = runner_password(intent["case_id"])
    registration = client.post("/api/auth/register", json={"account_name": account, "display_name": "Evaluation Runner", "password": password}, headers=headers())
    registration_body = registration.json()
    scanner.scan(registration_body)
    if registration.status_code == 201:
        return
    if registration.status_code == 409 and safe_error(registration) == "account_name_unavailable":
        request_json(client, "POST", "/api/auth/login", scanner, json={"account_name": account, "password": password})
        return
    raise RuntimeError(f"case_account_unavailable:{registration.status_code}:{safe_error(registration)}")


def project_for_seed(client: httpx.Client, seed_key: str, scanner: ApiResponseScanner) -> str:
    projects = request_json(client, "GET", "/api/projects", scanner)["projects"]
    matches = [project["id"] for project in projects if project.get("seed_key") == seed_key]
    if len(matches) != 1: raise RuntimeError("scoped_seed_project_not_unique")
    return matches[0]


def _fault(fault_hook, boundary: str) -> None:
    if fault_hook is not None: fault_hook(boundary)


def build_case_result(client: httpx.Client, case: dict, intent: dict[str, Any], terminal: dict, scanner: ApiResponseScanner) -> dict[str, Any]:
    project_id = intent["project_id"]
    span_by_id, _ = project_span_map(client, project_id, scanner)
    predicted, issue = prediction_for_target(terminal, case["target_claim_ordinal"])
    metrics = terminal.get("metrics", {})
    trace = next((item for item in metrics.get("retrieval", []) if item.get("claim_ordinal") == case["target_claim_ordinal"]), {"returned_span_ids": []})
    expected_semantics = {(item["chapter_number"], item["source_label"]) for item in case["expected_evidence"]}
    retrieval_semantics = {span_by_id[item] for item in trace["returned_span_ids"] if item in span_by_id}
    evidence = issue.get("evidence", []) if issue else []
    evidence_semantics = [span_by_id.get(item["span_id"]) for item in evidence]
    cited_expected_unique = set(item for item in evidence_semantics if item in expected_semantics)
    expected_citable_count = len(expected_semantics) if case["expected_class"] == "conflict" else 0
    return {
        "case_id": case["case_id"], "seed_key": case["seed_key"], "expected_class": case["expected_class"], "predicted_class": predicted,
        "expected_category": case["expected_category"], "predicted_category": issue.get("category") if issue else None,
        "expected_severity": case["expected_severity"], "predicted_severity": issue.get("severity") if issue else None,
        "category_severity": [issue.get("category"), issue.get("severity")] if issue else None,
        "run_id": intent["run_id"], "post_status": 202, "post_state": "queued", "idempotency_replay_same_run": True,
        "terminal_status": terminal["status"], "terminal_error_code": terminal.get("error_code"),
        "schema_valid": terminal["status"] == "completed", "retrieval_hit_at_5": expected_semantics <= retrieval_semantics,
        "retrieval_semantic_set": sorted([list(item) for item in retrieval_semantics]), "cited_evidence_count": len(evidence), "cited_evidence_expected_count": sum(item in expected_semantics for item in evidence_semantics),
        "resolvable_evidence_count": sum(item is not None for item in evidence_semantics), "evidence_ids": sorted(item["id"] for item in evidence),
        "evidence_semantic_set": sorted([list(item) for item in evidence_semantics if item is not None]),
        "challenge_tags": list(case.get("challenge_tags", [])),
        "requires_multiple_direct_evidence": bool(case.get("requires_multiple_direct_evidence")),
        "expected_evidence_count": expected_citable_count,
        "cited_expected_evidence_unique_count": len(cited_expected_unique) if expected_citable_count else 0,
        "expected_evidence_full_set_cited": expected_semantics <= set(evidence_semantics) if expected_citable_count else None,
        "explanation_sha256": hashlib.sha256((issue.get("explanation", "") if issue else "").encode("utf-8")).hexdigest(),
        "latency_ms": metrics.get("latency_ms"), "input_tokens": metrics.get("input_tokens"), "output_tokens": metrics.get("output_tokens"), "cost_cny": metrics.get("cost_cny"), "provenance": metrics.get("provenance"),
    }


def run_case(checkpoint: FormalCheckpoint, client: httpx.Client, case: dict, scanner: ApiResponseScanner, fault_hook=None, preloaded_project_id: str | None = None) -> tuple[dict, dict[str, Any]]:
    intent = checkpoint.ensure_intent(case)
    if intent["state"] == "completed": return intent["result"], intent
    if preloaded_project_id is None:
        register_or_login_case(client, intent, scanner)
    elif intent.get("project_id") not in {None, preloaded_project_id}:
        raise RuntimeError("fixture_checkpoint_project_mismatch")
    _fault(fault_hook, "after_account_created")
    project_id = intent.get("project_id") or preloaded_project_id or project_for_seed(client, case["seed_key"], scanner)
    intent = checkpoint.advance(case["case_id"], "account_ready", project_id=project_id)
    project = request_json(client, "GET", f"/api/projects/{project_id}", scanner)
    draft = project["current_draft"]
    current = request_json(client, "GET", f"/api/projects/{project_id}/drafts/{draft['id']}", scanner)
    if hashlib.sha256(current["body"].encode("utf-8")).hexdigest() == intent["target_draft_sha256"]:
        saved = {"id": draft["id"], "revision": draft["revision"]}
    else:
        saved = request_json(client, "PATCH", f"/api/projects/{project_id}/drafts/{draft['id']}", scanner, json={"base_revision": draft["revision"], "body": case["target_draft"]}, headers=headers())
    _fault(fault_hook, "after_draft_saved")
    intent = checkpoint.advance(case["case_id"], "draft_ready", draft_id=saved["id"], draft_revision=saved["revision"])
    payload = {"draft_id": intent["draft_id"], "draft_revision": intent["draft_revision"], "client_request_id": intent["client_request_id"]}
    first = client.post(f"/api/projects/{project_id}/checks", json=payload, headers=headers(intent["check_idempotency_key"]))
    scanner.scan(first.json())
    if first.status_code != 202:
        raise RuntimeError(f"check_not_queued:{first.status_code}:{safe_error(first)}")
    queued = first.json()["data"]
    _fault(fault_hook, "after_check_posted")
    intent = checkpoint.advance(case["case_id"], "check_queued", run_id=queued["run_id"])
    terminal = wait_for_terminal(client, project_id, intent["run_id"], scanner)
    _fault(fault_hook, "after_run_terminal")
    intent = checkpoint.advance(case["case_id"], "run_terminal", terminal_status=terminal["status"])
    result = build_case_result(client, case, intent, terminal, scanner)
    _fault(fault_hook, "after_terminal_before_completed")
    intent = checkpoint.record_completed(case["case_id"], result)
    return result, intent


def repeat_case(client: httpx.Client, case: dict, context: dict[str, Any], scanner: ApiResponseScanner) -> dict:
    span_by_id, _ = project_span_map(client, context["project_id"], scanner)
    payload = {"draft_id": context["draft_id"], "draft_revision": context["draft_revision"], "client_request_id": f"stability:{case['case_id']}:{uuid.uuid4().hex[:8]}"}
    idem = str(uuid.uuid4())
    response = client.post(f"/api/projects/{context['project_id']}/checks", json=payload, headers=headers(idem))
    scanner.scan(response.json())
    if response.status_code != 202:
        raise RuntimeError(f"stability_check_not_queued:{response.status_code}:{safe_error(response)}")
    replay = client.post(f"/api/projects/{context['project_id']}/checks", json=payload, headers=headers(idem))
    scanner.scan(replay.json())
    if replay.status_code != 202 or replay.json()["data"].get("run_id") != response.json()["data"].get("run_id"):
        raise RuntimeError("stability_idempotency_replay_failed")
    terminal = wait_for_terminal(client, context["project_id"], response.json()["data"]["run_id"], scanner)
    predicted, issue = prediction_for_target(terminal, case["target_claim_ordinal"])
    evidence = issue.get("evidence", []) if issue else []
    metrics = terminal.get("metrics", {})
    return {"case_id": case["case_id"], "run_id": response.json()["data"]["run_id"], "idempotency_replay_same_run": True, "predicted_class": predicted, "category_severity": [issue.get("category"), issue.get("severity")] if issue else None, "evidence_ids": sorted(item["id"] for item in evidence), "explanation_sha256": hashlib.sha256((issue.get("explanation", "") if issue else "").encode("utf-8")).hexdigest(), "terminal_status": terminal["status"], "terminal_error_code": terminal.get("error_code"), "latency_ms": metrics.get("latency_ms"), "input_tokens": metrics.get("input_tokens"), "output_tokens": metrics.get("output_tokens"), "cost_cny": metrics.get("cost_cny")}


def bad_case(result: dict) -> dict | None:
    dimensions: list[str] = []
    if result["terminal_status"] != "completed":
        dimensions.append("terminal_failure")
        cause = "schema"
        rationale = "The fail-closed schema/evidence guard ended the run with a terminal error."
    else:
        cause = "provider_generation"
        rationale = "One or more model-quality dimensions did not match the frozen rubric."
    if not result["retrieval_hit_at_5"]:
        dimensions.append("retrieval_miss")
        cause = "retrieval"
        rationale = "The expected semantic evidence location was absent from the recorded retrieval top five."
    if result["cited_evidence_count"] != result["resolvable_evidence_count"]:
        dimensions.append("evidence_grounding")
        cause = "evidence_grounding"
        rationale = "At least one cited Evidence item could not be resolved against the recorded source span."
    if result["predicted_class"] != result["expected_class"]:
        dimensions.append("classification_mismatch")
    if result.get("expected_category") and result.get("predicted_category") != result["expected_category"]:
        dimensions.append("category_mismatch")
    expected_count = result.get("expected_evidence_count", 0)
    cited_expected = result.get("cited_expected_evidence_unique_count", 0)
    if result.get("expected_class") == "conflict" and cited_expected < expected_count:
        dimensions.append("expected_evidence_recall_incomplete")
    if result.get("requires_multiple_direct_evidence") and result.get("expected_evidence_full_set_cited") is not True:
        dimensions.append("multi_direct_evidence_full_set_miss")
    dimensions = list(dict.fromkeys(dimensions))
    if not dimensions:
        return None
    if "terminal_failure" in dimensions:
        cause = "schema"
        rationale = "The fail-closed schema/evidence guard ended the run with a terminal error."
    elif "retrieval_miss" in dimensions:
        cause = "retrieval"
        rationale = "The expected semantic evidence location was absent from the recorded retrieval top five."
    elif "evidence_grounding" in dimensions:
        cause = "evidence_grounding"
        rationale = "At least one cited Evidence item could not be resolved against the recorded source span."
    return {"case_id": result["case_id"], "expected_class": result["expected_class"], "predicted_class": result["predicted_class"], "category": {"expected": result.get("expected_category"), "predicted": result.get("predicted_category")}, "root_cause": cause, "failure_dimensions": dimensions, "rationale": rationale, "evidence": {"terminal_error_code": result["terminal_error_code"], "retrieval_hit_at_5": result["retrieval_hit_at_5"], "cited_evidence_count": result["cited_evidence_count"], "resolvable_evidence_count": result["resolvable_evidence_count"], "expected_evidence_count": expected_count, "cited_expected_evidence_unique_count": cited_expected, "expected_evidence_full_set_cited": result.get("expected_evidence_full_set_cited")}}


def gate(metrics: dict, safety: dict, thresholds: dict) -> tuple[bool, dict[str, bool]]:
    checks = {"macro_f1": metrics["macro_f1"] >= thresholds["macro_f1_min"], "conflict_recall": metrics["conflict"]["recall"] >= thresholds["conflict_recall_min"], "insufficient_evidence_recall": metrics["insufficient_evidence_recall"] >= thresholds["insufficient_evidence_recall_min"], "no_conflict_false_positive_rate": metrics["no_conflict_false_positive_rate"] <= thresholds["no_conflict_false_positive_rate_max"], "retrieval_expected_evidence_hit_at_5": metrics["retrieval_expected_evidence_hit_at_5"] >= thresholds["retrieval_expected_evidence_hit_at_5_min"], "cited_evidence_precision": metrics["cited_evidence_precision"] == thresholds["cited_evidence_precision"], "schema_validity": metrics["schema_validity"] == thresholds["schema_validity"], "evidence_resolvability_grounding": metrics["evidence_resolvability_grounding"] == thresholds["evidence_resolvability_grounding"], "fail_closed_safety_paths": safety.get("validity") == thresholds["fail_closed_safety_paths"]}
    if "conflict_category_accuracy_min" in thresholds:
        checks["conflict_category_accuracy"] = metrics["conflict_category_accuracy"] >= thresholds["conflict_category_accuracy_min"]
    if "designated_category_mismatch_regression_required_correct" in thresholds:
        regression = metrics["designated_category_mismatch_regression"]
        checks["designated_category_mismatch_regression"] = regression["correct"] == thresholds["designated_category_mismatch_regression_required_correct"] and regression["total"] == thresholds["designated_category_mismatch_regression_required_total"]
    if "expected_evidence_recall_min" in thresholds:
        checks["expected_evidence_recall"] = metrics["expected_evidence_recall"] >= thresholds["expected_evidence_recall_min"]
    if "multi_direct_evidence_full_set_recall_min" in thresholds:
        checks["multi_direct_evidence_full_set_recall"] = metrics["multi_direct_evidence_full_set_recall"] >= thresholds["multi_direct_evidence_full_set_recall_min"]
    return all(checks.values()), checks


def write_json(path: pathlib.Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def execute_formal_run(
    config: EvaluationRunConfig,
    *,
    runtime_mode: str,
    base_url: str | None = None,
    fixture_work_root_path: pathlib.Path | None = None,
    provider: Any = None,
    write_artifacts: bool = True,
    run_stability: bool = True,
    cases_override: list[dict] | None = None,
    fault_hook=None,
    formal_run_kind: str = "formal",
    abort_after_first_transport_failure: bool = False,
) -> dict[str, Any]:
    """The single production-API formal execution chain for remote or fixture inputs."""
    if runtime_mode not in RUNTIME_MODES:
        raise RuntimeError("evaluation_runtime_mode_invalid")
    if runtime_mode == REMOTE_SEED_MODE and not base_url:
        raise RuntimeError("remote_seed_mode_base_url_required")
    if runtime_mode == EVALUATION_FIXTURE_MODE and (base_url or fixture_work_root_path is None):
        raise RuntimeError("fixture_mode_requires_work_root_and_rejects_base_url")
    if not SAFETY.exists():
        raise RuntimeError("fail-closed contract evidence is required before formal scoring")
    safety = json.loads(SAFETY.read_text(encoding="utf-8"))
    cases_payload = load_case_payload(config.case_set_path)
    manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    assert_manifest_approved(manifest)
    if canonical_sha256(cases_payload) != manifest["case_set"]["canonical_sha256"]:
        raise RuntimeError("case_set_hash_mismatch")
    if runtime_mode == EVALUATION_FIXTURE_MODE:
        # Approved fixture runs are permitted only for the controller-frozen
        # data assets. This check has no database, checkpoint, or provider side
        # effects and deliberately rejects an approval-shaped candidate copy.
        v2_case_set = ROOT / "evaluation" / "case_sets" / "eval-set-v2.json"
        v2_manifest = ROOT / "evaluation" / "manifests" / "eval-set-v2-manifest.json"
        v3_case_set = ROOT / "evaluation" / "case_sets" / "eval-set-v3.json"
        v3_manifest = ROOT / "evaluation" / "manifests" / "eval-set-v3-manifest.json"
        v4_case_set = ROOT / "evaluation" / "case_sets" / "eval-set-v4.json"
        v4_manifest = ROOT / "evaluation" / "manifests" / "eval-set-v4-manifest.json"
        v5_case_set = ROOT / "evaluation" / "case_sets" / "eval-set-v5.json"
        v5_manifest = ROOT / "evaluation" / "manifests" / "eval-set-v5-manifest.json"
        v6_case_set = ROOT / "evaluation" / "case_sets" / "eval-set-v6.json"
        v6_manifest = ROOT / "evaluation" / "manifests" / "eval-set-v6-manifest.json"
        v7_case_set = ROOT / "evaluation" / "case_sets" / "eval-set-v7.json"
        v7_manifest = ROOT / "evaluation" / "manifests" / "eval-set-v7-manifest.json"
        if config.case_set_path.resolve() == v2_case_set.resolve() and config.manifest_path.resolve() == v2_manifest.resolve():
            from evaluation.validate_eval_set_v2 import validate_formal_freeze
            validate_formal_freeze(config.case_set_path, config.manifest_path)
        elif config.case_set_path.resolve() == v3_case_set.resolve() and config.manifest_path.resolve() == v3_manifest.resolve():
            from evaluation.validate_eval_set_v3 import validate_formal_freeze
            validate_formal_freeze(config.case_set_path, config.manifest_path)
        elif config.case_set_path.resolve() == v4_case_set.resolve() and config.manifest_path.resolve() == v4_manifest.resolve():
            from evaluation.validate_eval_set_v4 import validate_formal_freeze
            validate_formal_freeze(config.case_set_path, config.manifest_path)
        elif config.case_set_path.resolve() == v5_case_set.resolve() and config.manifest_path.resolve() == v5_manifest.resolve():
            from evaluation.validate_eval_set_v5 import validate_formal_freeze
            validate_formal_freeze(config.case_set_path, config.manifest_path)
        elif config.case_set_path.resolve() == v6_case_set.resolve() and config.manifest_path.resolve() == v6_manifest.resolve():
            from evaluation.validate_eval_set_v6 import validate_formal_freeze
            validate_formal_freeze(config.case_set_path, config.manifest_path)
        elif config.case_set_path.resolve() == v7_case_set.resolve() and config.manifest_path.resolve() == v7_manifest.resolve():
            from evaluation.validate_eval_set_v7 import validate_formal_freeze
            validate_formal_freeze(config.case_set_path, config.manifest_path)
        elif config.case_set_path.resolve() == (ROOT / "evaluation" / "case_sets" / "eval-set-v8.json").resolve() and config.manifest_path.resolve() == (ROOT / "evaluation" / "manifests" / "eval-set-v8-manifest.json").resolve():
            from evaluation.validate_eval_set_v8 import validate_formal_freeze
            validate_formal_freeze()
        else:
            raise RuntimeError("fixture_formal_assets_must_use_frozen_paths")
    corpus_manifest_path = verify_fixture_inputs(cases_payload, manifest) if runtime_mode == EVALUATION_FIXTURE_MODE else None
    if runtime_mode == EVALUATION_FIXTURE_MODE:
        fixture_work_root_path = assert_fixture_work_root(fixture_work_root_path)
    active_cases = cases_override if cases_override is not None else cases_payload["cases"]
    case_ids = {case["case_id"] for case in cases_payload["cases"]}
    if not active_cases or any(case.get("case_id") not in case_ids for case in active_cases):
        raise RuntimeError("formal_run_cases_override_invalid")
    if write_artifacts:
        assert_outputs_safe(config)
        RESULTS.mkdir(parents=True, exist_ok=True)
    checkpoint = FormalCheckpoint(config.checkpoint_path, manifest["case_set"]["canonical_sha256"])
    source_hashes = source_hashes_for_config(config, runtime_mode, corpus_manifest_path)
    contexts: dict[str, dict] = {}
    results: list[dict] = []
    clients: dict[str, Any] = {}
    scanner = ApiResponseScanner()
    fixture_adapter = FixtureRuntimeAdapter(config.evaluation_id, fixture_work_root_path, provider, fixture_corpus_paths(corpus_manifest_path)) if runtime_mode == EVALUATION_FIXTURE_MODE else None
    started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    aborted_transport_error: str | None = None
    try:
        for case_index, case in enumerate(active_cases):
            fixture_runtime = fixture_adapter.open_case(case) if fixture_adapter else None
            client = fixture_runtime.client if fixture_runtime else httpx.Client(base_url=base_url.rstrip("/"), timeout=45)
            clients[case["case_id"]] = client
            intent = checkpoint.ensure_intent(case)
            if intent["state"] == "completed":
                if fixture_runtime is None:
                    register_or_login_case(client, intent, scanner)
                result = intent["result"]
            else:
                result, intent = run_case(checkpoint, client, case, scanner, fault_hook=fault_hook, preloaded_project_id=fixture_runtime.identity.project_id if fixture_runtime else None)
            contexts[case["case_id"]] = intent
            results.append(result)
            if case_index == 0 and abort_after_first_transport_failure and result.get("terminal_error_code") in {"provider_unavailable", "provider_timeout", "provider_error"}:
                aborted_transport_error = result["terminal_error_code"]
                break
        stability_rows = []
        if run_stability and aborted_transport_error is None:
            selected = {case["case_id"]: case for case in active_cases if case["case_id"] in manifest["stability_protocol"]["representative_case_ids"]}
            for case_id, case in selected.items():
                repeats = [next(item for item in results if item["case_id"] == case_id)]
                repeats.extend(repeat_case(clients[case_id], case, contexts[case_id], scanner) for _ in range(2))
                stability_rows.append({"case_id": case_id, "runs": repeats, "stability": stability(repeats)})
    finally:
        if fixture_adapter:
            fixture_adapter.close()
        else:
            for client in clients.values():
                client.close()
    finished_at = datetime.now(timezone.utc)
    elapsed_ms = int((time.perf_counter() - started_clock) * 1000)
    additional_runs = [run for row in stability_rows for run in row["runs"][1:]]
    all_provider_runs = [*results, *additional_runs]
    token_input = sum(item.get("input_tokens") or 0 for item in all_provider_runs)
    token_output = sum(item.get("output_tokens") or 0 for item in all_provider_runs)
    costs = [item.get("cost_cny") for item in all_provider_runs]
    provider_execution = {
        "provider_run_records": len(all_provider_runs),
        "actual_provider_http_attempts": getattr(provider, "request_attempts", len(all_provider_runs)),
        "successful_provider_responses": getattr(provider, "successful_responses", sum(item.get("latency_ms") is not None for item in all_provider_runs)),
        "terminal_status_counts": {status: sum(item.get("terminal_status") == status for item in all_provider_runs) for status in sorted({item.get("terminal_status") for item in all_provider_runs})},
        "input_tokens_returned": token_input,
        "output_tokens_returned": token_output,
        "cost": "unavailable" if not costs or any(value is None for value in costs) else sum(costs),
        "elapsed_ms": elapsed_ms,
    }
    if aborted_transport_error is None:
        metrics = aggregate(results)
        passed, gate_checks = gate(metrics, safety, manifest["required_thresholds"])
        status = "gate_passed" if passed else "gate_failed"
    else:
        metrics = None
        gate_checks = {"quality_gate_evaluated": False}
        status = "aborted_valid_run_attempt"
    report = {"evaluation": config.evaluation_id, "execution_kind": formal_run_kind, "status": status, "abort_reason": aborted_transport_error, "case_set_sha256": manifest["case_set"]["canonical_sha256"], "formal_case_results": results, "metrics": metrics, "gate_checks": gate_checks, "safety_contract": safety, "run_metadata": {"started_at": started_at.isoformat(), "completed_at": finished_at.isoformat(), "runtime_mode": runtime_mode, "base_url_label": "user_started_local_provider_backend" if runtime_mode == REMOTE_SEED_MODE else "isolated_evaluation_fixture", "source_file_hashes": source_hashes, "provider_configuration": "environment_only_not_recorded", "provider_execution": provider_execution}}
    bad = [item for result in results if (item := bad_case(result))]
    outcome = {"report": report, "stability": {"evaluation": config.evaluation_id, "rows": stability_rows}, "bad_cases": {"evaluation": config.evaluation_id, "bad_cases": bad}, "scanner": scanner.result(), "source_hashes": source_hashes}
    if write_artifacts:
        artifacts = config.artifacts
        write_json(artifacts["formal"], report)
        write_json(artifacts["stability"], outcome["stability"])
        write_json(artifacts["bad_cases"], outcome["bad_cases"])
        write_json(artifacts["run_manifest"], {"evaluation": config.evaluation_id, "execution_kind": formal_run_kind, "status": status, "case_set_sha256": manifest["case_set"]["canonical_sha256"], "source_file_hashes": source_hashes, "safety_contract_sha256": sha256_file(SAFETY), "provider_configuration": "environment_only_not_recorded", "provider_execution": provider_execution, "completed_at": finished_at.isoformat()})
        write_json(artifacts["api_scan"], outcome["scanner"])
        artifacts["report"].write_text("# Evaluation formal report\n\nExecution kind: **" + formal_run_kind + "**\n\nStatus: **" + status + "**\n\n```json\n" + json.dumps({"metrics": metrics, "gate_checks": gate_checks, "bad_case_count": len(bad), "provider_execution": provider_execution}, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-mode", choices=RUNTIME_MODES, default=REMOTE_SEED_MODE)
    parser.add_argument("--base-url")
    parser.add_argument("--fixture-work-root")
    parser.add_argument("--evaluation-id", default="scc-web-demo-eval-v1")
    parser.add_argument("--case-set", default="evaluation/case_sets/eval-set-v1.json")
    parser.add_argument("--manifest", default="evaluation/manifests/eval-set-v1-manifest.json")
    parser.add_argument("--result-prefix", default="first-formal")
    parser.add_argument("--checkpoint-path")
    parser.add_argument("--formal-run-kind", default="formal")
    parser.add_argument("--abort-after-first-transport-failure", action="store_true")
    args = parser.parse_args()
    try:
        config = build_run_config(args.evaluation_id, args.case_set, args.manifest, args.result_prefix, args.checkpoint_path)
        work_root = fixture_work_root(args.fixture_work_root, args.evaluation_id) if args.runtime_mode == EVALUATION_FIXTURE_MODE else None
        provider = None
        if args.runtime_mode == EVALUATION_FIXTURE_MODE:
            from app.provider import DeepSeekProvider
            provider = DeepSeekProvider()
        outcome = execute_formal_run(config, runtime_mode=args.runtime_mode, base_url=args.base_url, fixture_work_root_path=work_root, provider=provider, formal_run_kind=args.formal_run_kind, abort_after_first_transport_failure=args.abort_after_first_transport_failure)
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
    print(json.dumps({"status": outcome["report"]["status"], "metrics": outcome["report"]["metrics"], "bad_case_count": len(outcome["bad_cases"]["bad_cases"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
