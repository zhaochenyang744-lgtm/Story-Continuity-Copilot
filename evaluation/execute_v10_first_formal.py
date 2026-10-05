"""One-time V10 held-out formal execution entry; the default command is fake-only.

The product itself runs the check: fixture databases, bounded retrieval, the
original 8,000-token run budget, DeepSeekProvider with deepseek-flash and
CONTINUITY_REVIEW_THINKING=high, and prompt v21. Citation precision uses the pre-registered >= 0.95 threshold;
the report also records the V5-V8 exact-1 gate.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import uuid
from typing import Any
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_PATH = ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app import engine as continuity_engine
from app.provider import DeepSeekProvider, ProviderResult
from evaluation.build_v10_formal_assets import CASE_SET, HISTORICAL_THRESHOLDS, MANIFEST, OUTPUTS, PLAN, RUNTIME_CONTRACT
from evaluation.generate_v8_post_run_integrity import atomic_write_json
from evaluation.run_eval import (EVALUATION_FIXTURE_MODE, EvaluationRunConfig, assert_outputs_safe, build_run_config,
                                 execute_formal_run, fixture_work_root)
from evaluation.v2_fixture_loader import V10_CORPUS_PATHS, fixture_runtime
from evaluation.validate_eval_set_v10 import WORKSPACE, validate_formal_freeze, validate_inputs

EVALUATION_ID = "scc-web-demo-eval-v10-first-formal"
RESULT_PREFIX = "eval-v10-first-formal"
POST_RUN = ROOT / "evaluation/results/v10-first-formal-post-run-integrity.json"


def read(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_v10_run_config() -> EvaluationRunConfig:
    config = build_run_config(EVALUATION_ID, "evaluation/case_sets/eval-set-v10.json", "evaluation/manifests/eval-set-v10-manifest.json", RESULT_PREFIX)
    expected = {ROOT / value for value in OUTPUTS.values()}
    actual = {config.checkpoint_path, *config.artifacts.values()}
    if config.case_set_path != CASE_SET or config.manifest_path != MANIFEST or actual != expected:
        raise RuntimeError("v10_formal_config_paths_must_be_fixed")
    return config


def assert_prompt_contract() -> None:
    if continuity_engine.PROMPT_VERSION != RUNTIME_CONTRACT["prompt_version"]:
        raise RuntimeError("v10_formal_prompt_version_mismatch")


def assert_real_execution_preconditions() -> EvaluationRunConfig:
    plan = read(PLAN)
    if plan.get("formal_run_executed") is True or plan.get("provider_calls") not in {0, None}:
        raise RuntimeError("v10_first_formal_must_have_zero_prior_outputs")
    required = {"controller_candidate_gate_passed": True, "formal_inputs_frozen": True, "real_provider_authorization_received": True,
                "formal_run_executed": False, "provider_calls": 0, "status": "approved_for_formal_run", "runtime_contract": RUNTIME_CONTRACT}
    if any(plan.get(key) != value for key, value in required.items()):
        raise RuntimeError("v10_real_provider_authorization_required")
    assert_prompt_contract()
    formal = validate_formal_freeze()
    if formal["formal_result_count"] or formal["formal_workspace_count"]:
        raise RuntimeError("v10_first_formal_must_have_zero_prior_outputs")
    config = build_v10_run_config()
    if fixture_work_root(None, EVALUATION_ID) != WORKSPACE:
        raise RuntimeError("v10_formal_workspace_path_must_be_fixed")
    assert_outputs_safe(config)
    if plan["provider_execution"]["planned_provider_calls"] != 42:
        raise RuntimeError("v10_formal_42_call_protocol_invalid")
    return config


def validate_environment() -> DeepSeekProvider:
    base_url = os.environ.get("CONTINUITY_BASE_URL", "")
    parsed = urlsplit(base_url)
    provider = DeepSeekProvider()
    checks = {"provider": os.environ.get("CONTINUITY_PROVIDER", "").lower() == "deepseek",
              "model": os.environ.get("CONTINUITY_MODEL") == RUNTIME_CONTRACT["model_label"],
              "review_thinking": os.environ.get("CONTINUITY_REVIEW_THINKING") == RUNTIME_CONTRACT["review_thinking"],
              "base_url": parsed.scheme == "https" and parsed.hostname == "api.deepseek.com" and parsed.path in {"", "/"},
              "api_key": bool(os.environ.get("CONTINUITY_API_KEY")), "available": provider.available}
    if not all(checks.values()):
        raise RuntimeError("v10_formal_provider_configuration_invalid:" + ",".join(k for k, ok in checks.items() if not ok))
    return provider


class NoIssueFakeProvider:
    label = "evaluation-v10-fake"; model_label = "evaluation-v10-fake"; available = True

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, _: dict[str, Any]) -> ProviderResult:
        self.calls += 1
        return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1, latency_ms=1)


def fake_only_dry_run() -> dict:
    """Product chain with a fake Provider: loads, isolation, retrieval Hit@5. No quality is scored."""
    validate_inputs()
    cases = read(CASE_SET)["cases"]
    provider, misses = NoIssueFakeProvider(), []
    for case in cases:
        with fixture_runtime(case["corpus_key"], provider, V10_CORPUS_PATHS) as runtime:
            client, identity = runtime.client, runtime.identity
            data = lambda response: response.json()["data"]
            project = data(client.get(f"/api/projects/{identity.project_id}"))
            headers = {"Idempotency-Key": str(uuid.uuid4())}
            saved = data(client.patch(f"/api/projects/{identity.project_id}/drafts/{identity.draft_id}",
                                      json={"base_revision": project["current_draft"]["revision"], "body": case["target_draft"]}, headers=headers))
            queued = client.post(f"/api/projects/{identity.project_id}/checks", headers=headers,
                                 json={"draft_id": saved["id"], "draft_revision": saved["revision"], "client_request_id": f"v10-dry:{case['case_id']}"})
            if queued.status_code != 202:
                raise RuntimeError(f"v10_dry_check_not_queued:{case['case_id']}:{queued.status_code}:{queued.json().get('error', {}).get('code') if isinstance(queued.json().get('error'), dict) else queued.json().get('error')}")
            run = data(client.get(f"/api/projects/{identity.project_id}/checks/{queued.json()['data']['run_id']}?include=metrics"))
            if run["status"] != "completed":
                raise RuntimeError(f"v10_dry_run_not_completed:{case['case_id']}:{run.get('error_code')}")
            trace = next(item for item in run["metrics"]["retrieval"] if item["claim_ordinal"] == 1)
            expected = {(item["chapter_number"], item["source_label"]) for item in case["expected_evidence"]}
            returned = {semantic for semantic, span in identity.semantic_spans.items() if span in trace["returned_span_ids"]}
            if not expected <= returned:
                misses.append(case["case_id"])
    return {"fake_provider_calls": provider.calls, "real_provider_calls": 0, "quality_scored": False, "cases": len(cases),
            "retrieval_expected_evidence_hit_at_5": round((len(cases) - len(misses)) / len(cases), 4), "retrieval_misses": misses}


def update_plan(report: dict) -> None:
    plan = read(PLAN)
    execution = report["run_metadata"]["provider_execution"]
    plan.update({"status": report["status"], "formal_run_executed": True, "provider_calls": execution["provider_run_records"]})
    plan["stability_protocol"] = {**plan["stability_protocol"], "execution_status": report["status"]}
    atomic_write_json(PLAN, plan)


def execute_once() -> dict:
    config = assert_real_execution_preconditions()
    provider = validate_environment()
    outcome = execute_formal_run(config, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=WORKSPACE, provider=provider,
                                 formal_run_kind="first_valid_formal", abort_after_first_transport_failure=True)
    frozen = read(ROOT / "evaluation/manifests/eval-set-v10-freeze-integrity.json")
    atomic_write_json(POST_RUN, {"schema_version": "scc-eval-v10-post-run-integrity-v1", "status": outcome["report"]["status"],
                                 "freeze_integrity_files": len(frozen["files"]), "case_set_sha256": outcome["report"]["case_set_sha256"]})
    from evaluation.run_eval import gate
    report = outcome["report"]
    if report["metrics"] is not None:
        passed, checks = gate(report["metrics"], report["safety_contract"], HISTORICAL_THRESHOLDS)
        atomic_write_json(ROOT / "evaluation/results/eval-v10-first-formal-historical-gate.json",
                          {"historical_thresholds": "V5-V8", "status": "gate_passed" if passed else "gate_failed", "gate_checks": checks})
    update_plan(report)
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    if not parser.parse_args().execute:
        print(json.dumps(fake_only_dry_run(), ensure_ascii=False, indent=2))
        return
    try:
        outcome = execute_once()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
    report = outcome["report"]
    print(json.dumps({"status": report["status"], "gate_checks": report["gate_checks"], "metrics": report["metrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
