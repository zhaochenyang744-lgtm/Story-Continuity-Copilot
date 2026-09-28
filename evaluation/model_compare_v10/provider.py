"""Experiment-only HTTP adapter; real usage is passed through unchanged."""
from __future__ import annotations

import copy
import json
import time

import httpx
from app.provider import (CONTINUITY_PROMPT_VERSION, ProviderFailure, ProviderInvalidJson,
                          ProviderResult, continuity_prompt, parse_json_content)
from evaluation.model_compare_v10.config import MAX_OUTPUT, PROMPT_VERSION, TIMEOUT_SECONDS, TRANSPORT_RETRIES, digest, write_x
from evaluation.model_compare_v10.journal import ExperimentStopped, GenerationIncomplete


def body_for(request, condition):
    if CONTINUITY_PROMPT_VERSION != PROMPT_VERSION:
        raise RuntimeError("prompt_version_drift")
    body = {"model": condition["model"], "messages": [{"role": "user", "content": continuity_prompt(request)}],
            "response_format": {"type": "json_object"}, "thinking": {"type": condition["thinking"]},
            "max_tokens": MAX_OUTPUT}
    if condition["reasoning_effort"] is not None:
        body["reasoning_effort"] = condition["reasoning_effort"]
    if condition["temperature"] is not None:
        body["temperature"] = condition["temperature"]
    return body


class ExperimentProvider:
    label = "model-compare-v10-experiment"
    continuity_contract_version = "v6"
    available = True

    def __init__(self, journal, condition, base_request, key, client_factory=None):
        self.journal, self.condition = journal, condition
        self.base_request = copy.deepcopy(base_request)
        self.model_label = condition["model"]
        self.key = key
        self.factory = client_factory or (lambda: httpx.Client(timeout=httpx.Timeout(TIMEOUT_SECONDS)))

    def evaluate(self, request):
        check = copy.deepcopy(request)
        check.pop("contract_repair", None)
        if check != self.base_request:
            raise RuntimeError("fixed_v7_business_request_drift")
        body = body_for(request, self.condition)
        self.journal.begin_evaluation(copy.deepcopy(request), body)
        started_evaluation = time.perf_counter()
        # The one-retry transport ceiling is retained, but unknown dispatched
        # usage has higher priority and forbids the usual timeout retry.
        for transport_attempt in range(TRANSPORT_RETRIES + 1):
            # Admission runs for EVERY dispatch, including a known-usage retry.
            number = self.journal.begin_post(body)
            started = time.perf_counter()
            try:
                with self.factory() as client:
                    response = client.post("https://api.deepseek.com/chat/completions",
                        headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"}, json=body)
                status = response.status_code
                try:
                    envelope = response.json()
                except (ValueError, TypeError):
                    envelope = None
                receipt = self.journal.finish_post(number, envelope=envelope, status=status,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error_type=None if envelope is not None else "response_json_unavailable")
            except (httpx.HTTPError, OSError) as error:
                receipt = self.journal.finish_post(number, error_type=type(error).__name__,
                    latency_ms=int((time.perf_counter() - started) * 1000))
                write_x(self.journal.root / "evaluations" / f"{self.journal.evaluation_count:02d}.json", {
                    "evaluation": self.journal.evaluation_count, "business_request_sha256": digest(request),
                    "outcome": "transport_unknown", "parsed_business_json": None, "error_type": type(error).__name__,
                    "finish_reason": None, "usage": receipt["usage"], "usage_isolation_or_substitution": False})
                raise ExperimentStopped(self.journal.matrix.stop_reason or "unknown_dispatch_usage") from None
            if (status == 429 or status >= 500) and transport_attempt < TRANSPORT_RETRIES and not self.journal.matrix.stop_reason:
                continue
            break
        parsed = None
        parse_error = None
        try:
            if not isinstance(receipt["visible_content"], str):
                raise TypeError("visible_content_missing")
            parsed = parse_json_content(receipt["visible_content"])
        except (ValueError, TypeError) as error:
            parse_error = type(error).__name__
        evaluation = {"evaluation": self.journal.evaluation_count, "business_request_sha256": digest(request),
                      "outcome": "parsed" if parse_error is None else "not_parsed",
                      "parsed_business_json": parsed, "error_type": parse_error,
                      "finish_reason": receipt["finish_reason"], "usage": receipt["usage"],
                      "engine_budget": 40000, "usage_isolation_or_substitution": False}
        write_x(self.journal.root / "evaluations" / f"{self.journal.evaluation_count:02d}.json", evaluation)
        if self.journal.matrix.stop_reason and (receipt["usage"]["status"] != "complete" or status != 200):
            raise ExperimentStopped(self.journal.matrix.stop_reason)
        if status != 200:
            raise ProviderFailure()
        if receipt["finish_reason"] != "stop":
            raise GenerationIncomplete("finish_reason:" + str(receipt["finish_reason"]))
        usage = receipt["usage"]
        attempts = [r for r in self.journal.raw_records if r["evaluation"] == self.journal.evaluation_count]
        total_input = sum(r["usage"]["prompt_tokens"] for r in attempts)
        total_output = sum(r["usage"]["completion_tokens"] for r in attempts)
        reported_costs = [r["usage"]["cost_cny_reported"] for r in attempts]
        total_cost = sum(reported_costs) if all(type(c) in (int, float) for c in reported_costs) else None
        total_latency = int((time.perf_counter() - started_evaluation) * 1000)
        cost = usage["cost_cny_reported"]
        cost = cost if type(cost) in (int, float) else None
        if parse_error:
            raise ProviderInvalidJson(total_input, total_output, total_cost,
                total_latency, receipt["finish_reason"], usage["prompt_tokens"], usage["completion_tokens"], cost)
        return ProviderResult(parsed, total_input, total_output, total_cost,
            total_latency, receipt["finish_reason"], usage["prompt_tokens"], usage["completion_tokens"], cost)
