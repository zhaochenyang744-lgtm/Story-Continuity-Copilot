"""One-time V8 formal execution entry; the default command remains fake-only."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_PATH = ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.provider import DeepSeekProvider
from app import engine as continuity_engine
from evaluation.generate_v8_post_run_integrity import atomic_write_json, build_integrity
from evaluation.run_eval import EVALUATION_FIXTURE_MODE, EvaluationRunConfig, assert_outputs_safe, build_run_config, execute_formal_run, fixture_work_root
from evaluation.validate_eval_set_v8 import validate_formal_freeze
from evaluation.v8_fixture_preflight import preflight_v8_candidate

PLAN_PATH = ROOT / "evaluation/manifests/eval-v8-first-formal-plan.json"
EVALUATION_ID = "scc-web-demo-eval-v8-first-formal"
CASE_SET = "evaluation/case_sets/eval-set-v8.json"
MANIFEST = "evaluation/manifests/eval-set-v8-manifest.json"
RESULT_PREFIX = "eval-v8-first-formal"
WORKSPACE = ROOT / "evaluation/fixture-workspaces" / EVALUATION_ID
RUNTIME_CONTRACT = {"model_label": "deepseek-v4-pro", "prompt_version": "continuity-review-v6"}


def _read_plan(path: pathlib.Path = PLAN_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_v8_run_config(*, checkpoint_path: pathlib.Path | None = None) -> EvaluationRunConfig:
    """Construct only immutable V8 paths; no SQLite, file, or Provider side effect."""
    config = build_run_config(EVALUATION_ID, CASE_SET, MANIFEST, RESULT_PREFIX)
    if checkpoint_path is not None:
        config = EvaluationRunConfig(EVALUATION_ID, config.case_set_path, config.manifest_path, RESULT_PREFIX, checkpoint_path)
    plan = _read_plan(); expected = {ROOT / value for value in plan["planned_output_paths"].values()}
    actual = {config.checkpoint_path, *config.artifacts.values(), ROOT / "evaluation/results/v8-first-formal-post-run-integrity.json"}
    if (config.case_set_path != ROOT / CASE_SET or config.manifest_path != ROOT / MANIFEST or config.result_prefix != RESULT_PREFIX or (checkpoint_path is None and actual != expected)):
        raise RuntimeError("v8_formal_config_paths_must_be_fixed")
    protected = {path for version in ("v5", "v6", "v7") for path in (ROOT / "evaluation/results").glob(f"eval-{version}-first-formal-*")}
    if protected & actual:
        raise RuntimeError("v8_formal_config_must_not_target_prior_outputs")
    return config


def planned_provider_call_count(manifest: dict | None = None) -> int:
    manifest = manifest or json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    cases = json.loads((ROOT / CASE_SET).read_text(encoding="utf-8"))["cases"]
    stability = manifest.get("stability_protocol", {})
    if (len(cases), len(stability.get("representative_case_ids", [])), stability.get("independent_runs_per_case"), stability.get("additional_calls_after_formal")) != (24, 3, 3, 6):
        raise RuntimeError("v8_formal_30_call_protocol_invalid")
    return len(cases) + stability["additional_calls_after_formal"]


def assert_zero_formal_output_paths() -> None:
    plan = _read_plan()
    if any((ROOT / value).exists() for value in plan["planned_output_paths"].values()) or WORKSPACE.exists():
        raise RuntimeError("v8_first_formal_must_have_zero_prior_outputs")


def assert_prompt_contract() -> None:
    """Bind a future run to the actual production engine prompt contract."""
    if continuity_engine.PROMPT_VERSION != RUNTIME_CONTRACT["prompt_version"]:
        raise RuntimeError("v8_formal_prompt_version_mismatch")


def assert_real_execution_preconditions(*, plan: dict | None = None, formal_validator=validate_formal_freeze) -> tuple[EvaluationRunConfig, dict]:
    """Run every authorization, freeze, and path gate before Provider or SQLite setup."""
    plan = plan or _read_plan()
    # A retained first-valid run is never eligible for another execution.  The
    # fixed output check runs before authorization, Provider construction, or
    # fixture/SQLite initialization so a post-run CLI invocation is inert.
    if plan.get("formal_run_executed") is True or plan.get("provider_calls") not in {0, None}:
        assert_zero_formal_output_paths()
        raise RuntimeError("v8_first_formal_must_have_zero_prior_outputs")
    required = {"controller_candidate_gate_passed": True, "formal_inputs_frozen": True, "real_provider_authorization_received": True, "formal_run_executed": False, "provider_calls": 0, "status": "approved_for_formal_run", "runtime_contract": RUNTIME_CONTRACT}
    if any(plan.get(key) != value for key, value in required.items()):
        raise RuntimeError("v8_real_provider_authorization_required")
    # This reads the imported engine constant only. It happens before formal
    # validation, Provider construction, fixture runtime, or SQLite setup.
    assert_prompt_contract()
    formal = formal_validator(plan_payload=plan)
    if formal["formal_result_count"] or formal["formal_workspace_count"]:
        raise RuntimeError("v8_first_formal_must_have_zero_prior_outputs")
    assert_zero_formal_output_paths(); config = build_v8_run_config()
    if fixture_work_root(None, EVALUATION_ID) != WORKSPACE:
        raise RuntimeError("v8_formal_workspace_path_must_be_fixed")
    assert_outputs_safe(config)
    if planned_provider_call_count() != 30:
        raise RuntimeError("v8_formal_30_call_protocol_invalid")
    return config, formal


def validate_environment() -> DeepSeekProvider:
    provider_value, model = os.environ.get("CONTINUITY_PROVIDER", ""), os.environ.get("CONTINUITY_MODEL", "")
    base_url, api_key = os.environ.get("CONTINUITY_BASE_URL", ""), os.environ.get("CONTINUITY_API_KEY", "")
    parsed = urlsplit(base_url); provider = DeepSeekProvider()
    checks = {"provider": provider_value.lower() == "deepseek", "model": model == RUNTIME_CONTRACT["model_label"], "base_url": base_url in {"https://api.deepseek.com", "https://api.deepseek.com/"} and parsed.scheme == "https" and parsed.hostname == "api.deepseek.com" and parsed.path in {"", "/"}, "api_key": bool(api_key), "available": provider.available}
    if not all(checks.values()):
        raise RuntimeError("v8_formal_provider_configuration_invalid:" + ",".join(key for key, ok in checks.items() if not ok))
    return provider


def update_plan(report: dict) -> None:
    plan = _read_plan(); execution = report["run_metadata"]["provider_execution"]
    plan.update({"status": report["status"], "formal_run_executed": True, "provider_calls": execution["provider_run_records"], "real_provider_authorization_received": True})
    plan["stability_protocol"] = {**plan["stability_protocol"], "execution_status": report["status"]}
    atomic_write_json(PLAN_PATH, plan)


def execute_once() -> dict:
    config, _ = assert_real_execution_preconditions(); provider = validate_environment()
    outcome = execute_formal_run(config, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=WORKSPACE, provider=provider, formal_run_kind="first_valid_formal", abort_after_first_transport_failure=True)
    atomic_write_json(ROOT / "evaluation/results/v8-first-formal-post-run-integrity.json", build_integrity()); update_plan(outcome["report"])
    return outcome


def fake_only_dry_run() -> dict:
    formal = validate_formal_freeze(); preflight = preflight_v8_candidate()
    if (preflight["real_provider_calls"], preflight["quality_scored"], preflight["case_count"], preflight["retrieval_expected_evidence_hit_at_5"], preflight["source_lineage_resolved"], preflight["account_project_isolated"]) != (0, False, 24, 24, 24, 24):
        raise RuntimeError("v8_fake_only_dry_run_contract_invalid")
    return {"formal_status": formal["status"], "planned_provider_calls": 30, "fake_provider_calls": preflight["fake_provider_calls"], "real_provider_calls": 0, "quality_scored": False}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    if not args.execute:
        print(json.dumps(fake_only_dry_run(), ensure_ascii=False, indent=2)); return
    try:
        outcome = execute_once()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
    print(json.dumps({"status": outcome["report"]["status"], "metrics": outcome["report"]["metrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
