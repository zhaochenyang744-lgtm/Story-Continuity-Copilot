"""Execute the one-time V6 first-valid formal Provider evaluation."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
from urllib.parse import urlsplit

from app.provider import DeepSeekProvider
from evaluation.generate_v6_post_run_integrity import atomic_write_json, build_integrity
from evaluation.run_eval import EVALUATION_FIXTURE_MODE, build_run_config, execute_formal_run, fixture_work_root
from evaluation.validate_eval_set_v6 import validate_formal_freeze


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v6-first-formal-plan.json"


def validate_environment() -> DeepSeekProvider:
    provider_value = os.environ.get("CONTINUITY_PROVIDER", "")
    model = os.environ.get("CONTINUITY_MODEL", "")
    base_url = os.environ.get("CONTINUITY_BASE_URL", "")
    api_key = os.environ.get("CONTINUITY_API_KEY", "")
    parsed = urlsplit(base_url)
    exact_url = base_url in {"https://api.deepseek.com", "https://api.deepseek.com/"}
    checks = {
        "provider": provider_value.lower() == "deepseek",
        "model": model == "deepseek-v4-flash",
        "base_url": exact_url and parsed.scheme == "https" and parsed.hostname == "api.deepseek.com" and parsed.path in {"", "/"},
        "api_key": bool(api_key),
    }
    provider = DeepSeekProvider()
    checks["available"] = provider.available
    if not all(checks.values()):
        failures = ",".join(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"v6_formal_provider_configuration_invalid:{failures}")
    return provider


def update_plan(report: dict) -> None:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    execution = report["run_metadata"]["provider_execution"]
    plan.update({
        "status": report["status"],
        "formal_run_executed": True,
        "provider_calls": execution["provider_run_records"],
        "real_provider_authorization_received": True,
        "execution_note": "V6 first_valid_formal executed once under explicit authorization; consult the immutable result bundle and post-run integrity record for the retained outcome.",
    })
    stability = plan.get("stability_protocol", {})
    stability["execution_status"] = report["status"]
    plan["stability_protocol"] = stability
    atomic_write_json(PLAN_PATH, plan)


def main() -> None:
    # This validator precedes fixture creation, checkpoint writes, and Provider calls.
    validate_formal_freeze()
    provider = validate_environment()
    config = build_run_config(
        "scc-web-demo-eval-v6-first-formal",
        "evaluation/case_sets/eval-set-v6.json",
        "evaluation/manifests/eval-set-v6-manifest.json",
        "eval-v6-first-formal",
    )
    outcome = execute_formal_run(
        config,
        runtime_mode=EVALUATION_FIXTURE_MODE,
        fixture_work_root_path=fixture_work_root(None, config.evaluation_id),
        provider=provider,
        formal_run_kind="first_valid_formal",
        abort_after_first_transport_failure=True,
    )
    payload = build_integrity()
    atomic_write_json(ROOT / "evaluation" / "results" / "v6-first-formal-post-run-integrity.json", payload)
    update_plan(outcome["report"])
    execution = outcome["report"]["run_metadata"]["provider_execution"]
    print(json.dumps({"status": outcome["report"]["status"], "metrics": outcome["report"]["metrics"], "bad_case_count": len(outcome["bad_cases"]["bad_cases"]), "provider_execution": execution}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
