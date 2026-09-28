"""Serial fixed-request comparison; no database or application API is opened."""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import re
import threading
from contextlib import contextmanager

import httpx
import app.engine as engine_module
from app.engine import ContinuityEngine
from evaluation.model_compare_v11.config import *
from evaluation.model_compare_v11.journal import ExperimentStopped, GenerationIncomplete, MatrixLedger, TrialJournal
from evaluation.model_compare_v11.provider import ExperimentProvider, body_for
from evaluation.model_compare_v11.score import engine_final_score, raw_score, safe_score, layers

_budget_lock = threading.Lock()


@contextmanager
def experimental_budget():
    if not _budget_lock.acquire(blocking=False):
        raise RuntimeError("nested_or_concurrent_experimental_engine_forbidden")
    original = engine_module.MAX_RUN_TOKENS
    try:
        if original != ORIGINAL_ENGINE_BUDGET:
            raise RuntimeError("original_engine_budget_drift")
        engine_module.MAX_RUN_TOKENS = EXPERIMENT_ENGINE_BUDGET
        yield
    finally:
        engine_module.MAX_RUN_TOKENS = original
        _budget_lock.release()


class FrozenInputEngine(ContinuityEngine):
    def _batches(self, data):
        # Each input is already a complete one-claim business request (V7 prepared or frozen control).
        # Avoid retrieval, new claim IDs, or schema regeneration. execute keeps
        # its original 6000 input checks, repair loop and validator unchanged.
        return [copy.deepcopy(data)]


def reserve(run_id, mode):
    pattern = r"prep-v11-[a-z0-9-]{1,24}" if mode == "prepare" else r"model-compare-v11-[a-z0-9-]{1,24}"
    if not re.fullmatch(pattern, run_id):
        raise ValueError("invalid_run_identity")
    folder = HERE / "runs" / run_id
    if folder.exists():
        raise FileExistsError("run_identity_already_exists")
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def prepare(run_id="prep-v11-01"):
    folder = reserve(run_id, "prepare")
    current_plan = plan()
    write_x(folder / "plan.json", current_plan)
    all_cases = {x["ordinal"]: x for x in cases()}
    by_condition = {x["id"]: x for x in CONDITIONS}
    for item in current_plan["schedule"]:
        request = request_for(all_cases[item["case_ordinal"]])
        root = folder / "cases" / f"{item['case_ordinal']:02d}" / item["condition_id"]
        body = body_for(request, by_condition[item["condition_id"]])
        write_x(root / "input.json", {"business_request": request, "business_request_sha256": digest(request)})
        write_x(root / "wire.json", {"http_json_body": body, "body_sha256": digest(body)})
    write_x(folder / "summary.json", {"mode": "prepare", "version": VERSION, "cases": LOGICAL_CASES,
        "condition_cases": LOGICAL_CASES * len(CONDITIONS), "provider_calls": 0, "database_connections": 0, "quality_scored": False})
    return folder


def models_preflight(folder, key, factory=None):
    write_x(folder / "models-start.json", {"endpoint": "/models", "started_at": stamp(), "get_ordinal": 1})
    record = {"http_status": None, "models": [], "required_models_available": False, "error_type": None}
    try:
        with (factory() if factory else httpx.Client(timeout=httpx.Timeout(TIMEOUT_SECONDS))) as client:
            response = client.get("https://api.deepseek.com/models", headers={"Authorization": "Bearer " + key})
        record["http_status"] = response.status_code
        data = response.json()
        if response.status_code == 200:
            allowed = {"id", "object", "owned_by", "name", "version", "context_window", "max_output_tokens", "input_modalities", "output_modalities", "effort", "api_capabilities"}
            record["models"] = [{k: v for k, v in item.items() if k in allowed} for item in data.get("data", [])
                                if isinstance(item, dict) and item.get("id") in {c["model"] for c in CONDITIONS}]
            record["required_models_available"] = {c["model"] for c in CONDITIONS} <= {x["id"] for x in record["models"]}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
        record["error_type"] = type(error).__name__
    record["finished_at"] = stamp()
    write_x(folder / "models-finish.json", record)
    if not record["required_models_available"]:
        raise ExperimentStopped("models_preflight_failed")


def _run_trial(matrix, item, case, condition, key, client_factory=None):
    folder = matrix.root / "cases" / f"{case['ordinal']:02d}" / condition["id"]
    write_x(folder / "trial-start.json", {**item, "condition": condition, "started_at": stamp(),
        "original_budget": ORIGINAL_ENGINE_BUDGET, "effective_engine_budget": EXPERIMENT_ENGINE_BUDGET,
        "experiment_only": True, "source_request": source_of(case)})
    request = request_for(case)
    journal = TrialJournal(matrix, folder, item, condition)
    provider = ExperimentProvider(journal, condition, request, key, client_factory)
    try:
        with experimental_budget():
            output = FrozenInputEngine(provider).execute(copy.deepcopy(request))
    except (ExperimentStopped, GenerationIncomplete) as error:
        output = {"status": "stopped" if isinstance(error, ExperimentStopped) else "generation_incomplete",
                  "error_code": str(error), "issues": None}
    except Exception as error:
        # No response/error repr is persisted; it can contain hidden reasoning.
        output = {"status": "harness_error", "error_code": type(error).__name__, "issues": None}
        matrix.stop_reason = "harness_error"
    output.update({"experiment_only": True, "output_layer": "engine_not_api_or_database",
                   "effective_engine_budget": EXPERIMENT_ENGINE_BUDGET,
                   "original_engine_budget": ORIGINAL_ENGINE_BUDGET, "usage_substituted": False})
    write_x(folder / "engine-final.json", output)
    scored = []
    evaluations = []
    for path in sorted((folder / "evaluations").glob("*.json")):
        evaluation = read(path)
        evaluations.append(evaluation)
        own_request = read(folder / "requests" / path.name)["business_request"]
        if evaluation["outcome"] == "parsed":
            score = safe_score(raw_score, case, evaluation["parsed_business_json"], own_request, evaluation["finish_reason"])
        else:
            errors = [evaluation["error_type"]]
            if evaluation.get("finish_reason") != "stop":
                errors.append("generation:finish_reason_" + str(evaluation.get("finish_reason")))
            score = {"machine_result": "unavailable", "errors": errors, "layers": layers(errors),
                     "complete_answer": False, "semantic_result": "not_available"}
        scored.append(score)
    accepted = evaluations[-1] if evaluations else {}
    final_score = safe_score(engine_final_score, case, output, request, accepted.get("parsed_business_json"), accepted.get("finish_reason"))
    write_x(folder / "scores.json", {"first": scored[0] if scored else None, "repair": scored[1:], "final": final_score,
        "manual_semantic_review": "pending", "historical_v7_not_rescored_as_new_result": True})
    write_x(folder / "trial-finish.json", {"status": output["status"], "error_code": output.get("error_code"),
        "evaluation_count": journal.evaluation_count, "post_count": journal.post_count,
        "budget_restored_to": engine_module.MAX_RUN_TOKENS, "finished_at": stamp()})
    return journal, output


def execute(run_id, key, client_factory=None, models_factory=None):
    folder = reserve(run_id, "live")
    current_plan = plan()
    write_x(folder / "plan.json", current_plan)
    write_x(folder / "start.json", {"run_id": run_id, "version": VERSION, "started_at": stamp(),
        "manifest_sha256": sha(HERE / "frozen-inputs.json"), "limits": limits(), "conditions": list(CONDITIONS)})
    matrix = MatrixLedger(folder)
    finished = []
    service_streak = 0
    try:
        models_preflight(folder, key, models_factory)
        by_case = {x["ordinal"]: x for x in cases()}
        by_condition = {x["id"]: x for x in CONDITIONS}
        for item in current_plan["schedule"]:
            if matrix.stop_reason:
                break
            journal, output = _run_trial(matrix, item, by_case[item["case_ordinal"]], by_condition[item["condition_id"]], key, client_factory)
            finished.append(item)
            service_failure = any(r["error_type"] or isinstance(r["http_status"], int) and r["http_status"] >= 400 for r in journal.raw_records)
            service_streak = service_streak + 1 if service_failure else 0
            if service_streak >= 2:
                matrix.stop_reason = matrix.stop_reason or "two_consecutive_condition_case_service_failures"
    except ExperimentStopped as error:
        matrix.stop_reason = matrix.stop_reason or str(error)
    finally:
        not_run = current_plan["schedule"][len(finished):]
        write_x(folder / "not-run.json", {"reason": matrix.stop_reason, "condition_cases": not_run})
        coverage = {c["id"]: [x["case_ordinal"] for x in finished if x["condition_id"] == c["id"]] for c in CONDITIONS}
        common = sorted(set.intersection(*(set(x) for x in coverage.values())))
        write_x(folder / "summary.json", {"run_id": run_id, "finished_at": stamp(), **matrix.summary(),
            "condition_cases_finished": len(finished), "condition_cases_not_run": len(not_run), "coverage": coverage,
            "common_finished_cases": common, "models_get_count": 1, "semantic_review": "pending",
            "engine_budget_restored_to": engine_module.MAX_RUN_TOKENS})
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare",))
    parser.add_argument("--run-id", default="prep-v11-01")
    args = parser.parse_args()
    print(prepare(args.run_id))
