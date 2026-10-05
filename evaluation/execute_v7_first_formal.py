"""One-time V7 formal execution entry with a fake-only default command."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from urllib.parse import urlsplit

# Formal CLI modules are invoked from the repository root.  Make the backend
# package location explicit before importing app; this neither reads .env nor
# depends on the caller's cwd or test-suite import state.
ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_PATH = ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.provider import DeepSeekProvider
from evaluation.generate_v7_post_run_integrity import atomic_write_json, build_integrity
from evaluation.run_eval import EVALUATION_FIXTURE_MODE, EvaluationRunConfig, assert_outputs_safe, build_run_config, execute_formal_run, fixture_work_root
from evaluation.validate_eval_set_v7 import validate_formal_freeze
from evaluation.v7_fixture_preflight import preflight_v7_candidate


PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v7-first-formal-plan.json"
EVALUATION_ID = "scc-web-demo-eval-v7-first-formal"
CASE_SET = "evaluation/case_sets/eval-set-v7.json"
MANIFEST = "evaluation/manifests/eval-set-v7-manifest.json"
RESULT_PREFIX = "eval-v7-first-formal"
WORKSPACE = ROOT / "evaluation" / "fixture-workspaces" / EVALUATION_ID


def _read_plan(path: pathlib.Path = PLAN_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_v7_run_config(*, checkpoint_path: pathlib.Path | None = None) -> EvaluationRunConfig:
    """Assemble only the immutable V7 paths; this function performs no side effect."""
    config = build_run_config(EVALUATION_ID, CASE_SET, MANIFEST, RESULT_PREFIX)
    if checkpoint_path is not None:
        config = EvaluationRunConfig(EVALUATION_ID, config.case_set_path, config.manifest_path, RESULT_PREFIX, checkpoint_path)
    expected_outputs = {ROOT / value for value in _read_plan()["planned_output_paths"].values()}
    actual_outputs = {config.checkpoint_path, *config.artifacts.values(), ROOT / "evaluation" / "results" / "v7-first-formal-post-run-integrity.json"}
    if (config.case_set_path != (ROOT / CASE_SET) or config.manifest_path != (ROOT / MANIFEST)
            or config.result_prefix != RESULT_PREFIX or (checkpoint_path is None and actual_outputs != expected_outputs)):
        raise RuntimeError("v7_formal_config_paths_must_be_fixed")
    protected = {path for version in ("v5", "v6") for path in (ROOT / "evaluation" / "results").glob(f"eval-{version}-first-formal-*")}
    if protected & actual_outputs:
        raise RuntimeError("v7_formal_config_must_not_target_v5_v6_outputs")
    return config


def planned_provider_call_count(manifest: dict | None = None) -> int:
    manifest = manifest or json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    cases = json.loads((ROOT / CASE_SET).read_text(encoding="utf-8"))["cases"]
    stability = manifest.get("stability_protocol", {})
    selected = stability.get("representative_case_ids", [])
    if (len(cases), len(selected), stability.get("independent_runs_per_case"), stability.get("additional_calls_after_formal")) != (24, 3, 3, 6):
        raise RuntimeError("v7_formal_30_call_protocol_invalid")
    return len(cases) + stability["additional_calls_after_formal"]


def validate_environment() -> DeepSeekProvider:
    provider_value = os.environ.get("CONTINUITY_PROVIDER", "")
    model = os.environ.get("CONTINUITY_MODEL", "")
    base_url = os.environ.get("CONTINUITY_BASE_URL", "")
    api_key = os.environ.get("CONTINUITY_API_KEY", "")
    parsed = urlsplit(base_url)
    checks = {
        "provider": provider_value.lower() == "deepseek",
        "model": model == "deepseek-v4-flash",
        "base_url": base_url in {"https://api.deepseek.com", "https://api.deepseek.com/"} and parsed.scheme == "https" and parsed.hostname == "api.deepseek.com" and parsed.path in {"", "/"},
        "api_key": bool(api_key),
    }
    provider = DeepSeekProvider()
    checks["available"] = provider.available
    if not all(checks.values()):
        raise RuntimeError("v7_formal_provider_configuration_invalid:" + ",".join(name for name, passed in checks.items() if not passed))
    return provider


def assert_zero_formal_output_paths(*, output_paths: tuple[pathlib.Path, ...] | None = None, workspace: pathlib.Path = WORKSPACE) -> None:
    output_paths = output_paths or tuple(ROOT / value for value in _read_plan()["planned_output_paths"].values())
    if any(path.exists() for path in output_paths) or workspace.exists():
        raise RuntimeError("v7_first_formal_must_have_zero_prior_outputs")


def assert_real_execution_preconditions(*, plan: dict | None = None, formal_validator=validate_formal_freeze) -> tuple[EvaluationRunConfig, dict]:
    """Validate every authorization and immutable-path gate before Provider or SQLite setup."""
    plan = plan or _read_plan()
    if plan.get("formal_run_executed") is True or plan.get("provider_calls") not in {0, None}:
        raise RuntimeError("v7_first_formal_must_have_zero_prior_outputs")
    required = {
        "controller_candidate_gate_passed": True,
        "formal_inputs_frozen": True,
        "real_provider_authorization_received": True,
        "formal_run_executed": False,
        "provider_calls": 0,
        "status": "approved_for_formal_run",
    }
    if any(plan.get(key) != value for key, value in required.items()):
        raise RuntimeError("v7_real_provider_authorization_required")
    formal = formal_validator(plan_payload=plan)
    if formal["formal_run_executed"] or formal["provider_calls"] or formal["formal_result_count"] or formal["formal_workspace_count"]:
        raise RuntimeError("v7_first_formal_must_have_zero_prior_outputs")
    assert_zero_formal_output_paths()
    config = build_v7_run_config()
    if fixture_work_root(None, EVALUATION_ID) != WORKSPACE:
        raise RuntimeError("v7_formal_workspace_path_must_be_fixed")
    assert_outputs_safe(config)
    if planned_provider_call_count() != 30:
        raise RuntimeError("v7_formal_30_call_protocol_invalid")
    return config, formal


def update_plan(report: dict) -> None:
    plan = _read_plan()
    execution = report["run_metadata"]["provider_execution"]
    plan.update({
        "status": report["status"],
        "formal_run_executed": True,
        "provider_calls": execution["provider_run_records"],
        "real_provider_authorization_received": True,
        "execution_note": "V7 first_valid_formal executed once under explicit authorization; consult the immutable result bundle and post-run integrity record for the retained outcome.",
    })
    stability = plan.get("stability_protocol", {})
    stability["execution_status"] = report["status"]
    plan["stability_protocol"] = stability
    plan["stage_status"] = {"stage_10": "gate_failed_not_passed" if report["status"] == "gate_failed" else "awaiting_controller_gate_review", "stage_11": "not_started", "stage_12": "not_started"}
    atomic_write_json(PLAN_PATH, plan)


def execute_once() -> dict:
    """Run exactly once only after the user authorization flag is recorded."""
    config, _ = assert_real_execution_preconditions()
    provider = validate_environment()
    outcome = execute_formal_run(
        config,
        runtime_mode=EVALUATION_FIXTURE_MODE,
        fixture_work_root_path=WORKSPACE,
        provider=provider,
        formal_run_kind="first_valid_formal",
        abort_after_first_transport_failure=True,
    )
    integrity = build_integrity()
    atomic_write_json(ROOT / "evaluation" / "results" / "v7-first-formal-post-run-integrity.json", integrity)
    update_plan(outcome["report"])
    return outcome


def fake_only_dry_run() -> dict:
    """The default CLI behavior: no remote Provider, no formal path writes."""
    formal = validate_formal_freeze()
    preflight = preflight_v7_candidate()
    if (preflight["real_provider_calls"], preflight["quality_scored"], preflight["case_count"], preflight["retrieval_expected_evidence_hit_at_5"], preflight["source_lineage_resolved"], preflight["account_project_isolated"]) != (0, False, 24, 24, 24, 24):
        raise RuntimeError("v7_fake_only_dry_run_contract_invalid")
    return {"formal_status": formal["status"], "planned_provider_calls": planned_provider_call_count(), "fake_provider_calls": preflight["fake_provider_calls"], "real_provider_calls": 0, "quality_scored": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Requires separately recorded real Provider authorization.")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(fake_only_dry_run(), ensure_ascii=False, indent=2))
        return
    try:
        outcome = execute_once()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
    execution = outcome["report"]["run_metadata"]["provider_execution"]
    print(json.dumps({"status": outcome["report"]["status"], "metrics": outcome["report"]["metrics"], "bad_case_count": len(outcome["bad_cases"]["bad_cases"]), "provider_execution": execution}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
