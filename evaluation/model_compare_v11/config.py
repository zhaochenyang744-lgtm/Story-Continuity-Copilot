"""Frozen V11 configuration: v20 decisive-fact category contract.

Ordinals 1-34 are the prepared V7 inputs with the current engine schema, exactly
as in V9. Ordinals 35-54 are the new category-controls-v1 requests, written and
frozen before any v20 run. Neither set is an independent unseen benchmark.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
from datetime import datetime, timezone

from app.engine import _continuity_schema
from evaluation.category_controls_v1 import build as controls_v1

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREPARED = ROOT / "evaluation/current_flash_v7/runs/prep-v7-01"
V7_CASES = ROOT / "evaluation/current_flash_v7/cases.json"
CONTROLS = controls_v1.CASES
VERSION = "model-compare-v11"
PROMPT_VERSION = "continuity-review-v20-decisive-fact-category"
CONTROL_KIND = "category_control_v1"
LOGICAL_CASES = 54
MAX_OUTPUT = 32768
TIMEOUT_SECONDS = 120
CONTRACT_EVALUATIONS = 2
TRANSPORT_RETRIES = 1
# 54 cases x 2 conditions x 2 contract evaluations x 2 transport attempts.
MAX_POST = 432
MAX_GET = 1
# V9 used 414,716 total tokens for 34 cases on these two arms; the cap is a stop threshold.
KNOWN_TOKEN_CAP = 1_500_000
ORIGINAL_ENGINE_BUDGET = 8000
EXPERIMENT_ENGINE_BUDGET = 40000
IMMEDIATE_HTTP_STOP = {400, 401, 402, 403, 404, 422}
CONDITIONS = (
    {"id": "flash-high", "model": "deepseek-flash", "thinking": "enabled", "reasoning_effort": "high", "temperature": None},
    {"id": "pro-high", "model": "deepseek-v4-pro", "thinking": "enabled", "reasoning_effort": "high", "temperature": None},
)
V17_REASONING_SCHEMA = "why the cited evidence supports this nature, or exactly what evidence is missing"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_x(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def cases():
    seen = read(V7_CASES)["cases"]
    if len(seen) != 34 or [x["ordinal"] for x in seen] != list(range(1, 35)):
        raise RuntimeError("fixed_34_case_matrix_drift")
    fresh = [{"ordinal": 35 + index, "case_id": control["id"], "evaluation_kind": CONTROL_KIND, "control": control}
             for index, control in enumerate(controls_v1.controls())]
    return seen + fresh


def is_control(case):
    return case["evaluation_kind"] == CONTROL_KIND


def current_schema():
    schema = _continuity_schema()
    reasoning = schema["issues"][0]["reasoning"]
    if not reasoning.endswith(V17_REASONING_SCHEMA) or "800" not in reasoning:
        raise RuntimeError("v18_reasoning_schema_missing")
    return schema


def request_for(case):
    if is_control(case):
        request = controls_v1.request_for(case["control"])
        if request["output_schema"] != current_schema():
            raise RuntimeError("control_schema_drift")
        return request
    path = PREPARED / "cases" / f"{case['ordinal']:02d}" / "requests/01.json"
    captured = read(path)
    request = captured["business_request"]
    if (captured["case_id"] != case["case_id"] or digest(request) != captured["business_request_sha256"] or
            request["draft"]["body"] != case["saved_draft"] or "contract_repair" in request):
        raise RuntimeError("v7_prepared_input_binding_invalid")
    schema = current_schema()
    previous = copy.deepcopy(schema)
    previous["issues"][0]["reasoning"] = V17_REASONING_SCHEMA
    if request["output_schema"] != previous:
        raise RuntimeError("v7_prepared_schema_differs_beyond_reasoning_limit")
    return copy.deepcopy({**request, "output_schema": schema})


def source_of(case):
    if is_control(case):
        return CONTROLS.relative_to(ROOT).as_posix() + "#" + case["case_id"]
    return (PREPARED / "cases" / f"{case['ordinal']:02d}" / "requests/01.json").relative_to(ROOT).as_posix()


def schedule():
    rows = []
    for case in cases():
        offset = (case["ordinal"] - 1) % len(CONDITIONS)
        rotated = CONDITIONS[offset:] + CONDITIONS[:offset]
        for position, condition in enumerate(rotated, 1):
            rows.append({"dispatch_order": len(rows) + 1, "case_ordinal": case["ordinal"],
                         "case_id": case["case_id"], "condition_id": condition["id"], "position_in_case": position})
    return rows


def limits():
    return {"max_tokens": MAX_OUTPUT, "timeout_seconds": TIMEOUT_SECONDS,
            "timeout_semantics": "HTTPX connect/read/write/pool phase timeout, not a hard wall-clock deadline",
            "contract_evaluations": CONTRACT_EVALUATIONS, "transport_retries": TRANSPORT_RETRIES,
            "generation_post_cap": MAX_POST, "models_get_cap": MAX_GET,
            "known_total_token_cap": KNOWN_TOKEN_CAP, "original_engine_budget": ORIGINAL_ENGINE_BUDGET,
            "experimental_engine_budget": EXPERIMENT_ENGINE_BUDGET,
            "input_budget_units": 6000, "unknown_dispatch_usage_stops_matrix": True}


def plan():
    return {"version": VERSION, "conditions": list(CONDITIONS), "limits": limits(),
            "cases": cases(), "schedule": schedule(), "logical_cases": LOGICAL_CASES,
            "condition_cases": LOGICAL_CASES * len(CONDITIONS),
            "v7_cases_sha256": sha(V7_CASES), "controls_sha256": sha(CONTROLS),
            "input_hashes": {str(c["ordinal"]): digest(request_for(c)) for c in cases()},
            "groups": {"seen_v7": list(range(1, 35)), "new_category_controls_v1": list(range(35, 55))},
            "scoring_policy": "unchanged V7/V6 gold for 1-34; controls scored by the same rule shape from their frozen expected fields",
            "classification": "seen_development_plus_new_development_controls", "engine_output_is_not_api_persistence": True}
