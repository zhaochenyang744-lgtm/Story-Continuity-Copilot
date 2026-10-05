"""Create-only dispatch/usage receipts; reasoning text never crosses persistence."""
from __future__ import annotations

import hashlib

from evaluation.model_compare_v8.config import (
    CONTRACT_EVALUATIONS, EXPERIMENT_ENGINE_BUDGET, IMMEDIATE_HTTP_STOP, KNOWN_TOKEN_CAP,
    MAX_POST, ORIGINAL_ENGINE_BUDGET, digest, stamp, write_x,
)


class ExperimentStopped(RuntimeError):
    pass


class GenerationIncomplete(RuntimeError):
    pass


def count(value):
    return value if type(value) is int and value >= 0 else None


def usage_receipt(raw):
    usage = raw if isinstance(raw, dict) else None
    p, c, total = (count((usage or {}).get(k)) for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
    complete = p is not None and c is not None and total is not None and p + c == total
    details = (usage or {}).get("completion_tokens_details")
    reported = isinstance(details, dict) and "reasoning_tokens" in details
    reasoning = count(details.get("reasoning_tokens")) if reported else None
    detail_error = ("not_nonnegative_integer" if reported and reasoning is None else
                    "exceeds_completion_tokens" if reasoning is not None and c is not None and reasoning > c else None)
    if detail_error:
        reasoning = None
    return {"raw_usage": usage, "status": "complete" if complete else "unknown_or_partial",
            "prompt_tokens": p, "completion_tokens": c, "total_tokens": total,
            "reasoning_tokens": reasoning, "reasoning_tokens_status": "invalid" if detail_error else "reported" if reported else "not_reported",
            "reasoning_tokens_invalid_reason": detail_error,
            "completion_includes_reasoning_do_not_add_again": True,
            "original_8000_compatible": p + c <= ORIGINAL_ENGINE_BUDGET if complete else None,
            "experimental_40000_compatible": p + c <= EXPERIMENT_ENGINE_BUDGET if complete else None,
            "cost_cny_reported": (usage or {}).get("cost_cny"), "cost_status": "unknown_unless_explicitly_reported"}


def reasoning_receipt(message):
    value = message.get("reasoning_content") if isinstance(message, dict) else None
    if not isinstance(value, str):
        return {"present": value is not None, "codepoints": None, "utf8_bytes": None, "sha256": None}
    encoded = value.encode("utf-8")
    return {"present": True, "codepoints": len(value), "utf8_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest()}


class MatrixLedger:
    def __init__(self, root):
        self.root = root
        self.post_count = 0
        self.known_total_tokens = 0
        self.unknown_dispatches = 0
        self.stop_reason = None
        self.receipts = []

    def admit(self, trial):
        if self.stop_reason:
            raise ExperimentStopped(self.stop_reason)
        if self.post_count >= MAX_POST:
            self.stop_reason = "post_cap_reached"
        elif self.known_total_tokens >= KNOWN_TOKEN_CAP:
            self.stop_reason = "known_token_cap_reached"
        elif trial.post_count >= 4:
            self.stop_reason = "condition_case_post_cap_reached"
        if self.stop_reason:
            raise ExperimentStopped(self.stop_reason)
        return {"post_count_before": self.post_count, "post_cap": MAX_POST,
                "known_tokens_before": self.known_total_tokens, "known_token_cap": KNOWN_TOKEN_CAP,
                "unknown_dispatch_count_before": self.unknown_dispatches,
                "remaining_known_token_allowance": KNOWN_TOKEN_CAP - self.known_total_tokens,
                "one_request_may_exceed_remaining_allowance": True}

    def observe(self, receipt):
        self.receipts.append(receipt)
        usage = receipt["usage"]
        if usage["status"] == "complete":
            self.known_total_tokens += usage["total_tokens"]
        else:
            self.unknown_dispatches += 1
            self.stop_reason = self.stop_reason or "unknown_dispatch_usage"
        if receipt.get("http_status") in IMMEDIATE_HTTP_STOP:
            self.stop_reason = "immediate_http_stop_" + str(receipt["http_status"])
        if self.known_total_tokens >= KNOWN_TOKEN_CAP:
            self.stop_reason = self.stop_reason or "known_token_cap_reached"

    def summary(self):
        return {"post_attempts": self.post_count, "known_total_tokens": self.known_total_tokens,
                "unknown_dispatches": self.unknown_dispatches, "stop_reason": self.stop_reason,
                "tokens_total": self.known_total_tokens if not self.unknown_dispatches else None,
                "cost": None, "cost_status": "unknown", "unknown_is_not_zero": True}


class TrialJournal:
    def __init__(self, matrix, folder, item, condition):
        self.matrix, self.root, self.item, self.condition = matrix, folder, item, condition
        self.evaluation_count = self.post_count = 0
        self.raw_records = []
        self.requests = []

    def begin_evaluation(self, request, body):
        if self.matrix.stop_reason:
            raise ExperimentStopped(self.matrix.stop_reason)
        if self.evaluation_count >= CONTRACT_EVALUATIONS:
            raise ExperimentStopped("contract_evaluation_cap_reached")
        self.evaluation_count += 1
        number = self.evaluation_count
        self.requests.append(request)
        write_x(self.root / "requests" / f"{number:02d}.json", {
            "evaluation": number, "stage": "first" if number == 1 else "repair",
            "business_request_sha256": digest(request), "business_request": request})
        write_x(self.root / "wire" / f"{number:02d}.json", {
            "request_body_sha256": digest(body), "http_json_body": body,
            "headers_saved": False, "created_at": stamp()})

    def begin_post(self, body):
        admission = self.matrix.admit(self)
        self.post_count += 1
        self.matrix.post_count += 1
        number = self.post_count
        write_x(self.root / "attempts" / f"{number:02d}-start.json", {
            "global_post_ordinal": self.matrix.post_count, "trial_post_ordinal": number,
            "evaluation": self.evaluation_count, "condition": self.condition,
            "request_body_sha256": digest(body), "admission": admission, "started_at": stamp()})
        return number

    def finish_post(self, number, *, envelope=None, status=None, error_type=None, latency_ms=None):
        data = envelope if isinstance(envelope, dict) else {}
        choices = data.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = message.get("content")
        record = {"evaluation": self.evaluation_count, "trial_post_ordinal": number,
                  "http_status": status, "error_type": error_type, "latency_ms": latency_ms,
                  "finish_reason": choice.get("finish_reason"), "response_model": data.get("model"),
                  "response_id": data.get("id"), "system_fingerprint": data.get("system_fingerprint"),
                  "visible_content": content if isinstance(content, str) else None,
                  "visible_content_sha256": hashlib.sha256(content.encode()).hexdigest() if isinstance(content, str) else None,
                  "reasoning": reasoning_receipt(message), "reasoning_body_persisted": False,
                  "usage": usage_receipt(data.get("usage")), "finished_at": stamp()}
        write_x(self.root / "attempts" / f"{number:02d}-finish.json", record)
        self.raw_records.append(record)
        self.matrix.observe(record)
        return record
