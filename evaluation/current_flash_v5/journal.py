"""Create-only per-dispatch journal. Never persists headers, keys, or hidden reasoning."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.provider import DeepSeekProvider, ProviderDispatchDenied, ProviderResult


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def write_x(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())


def usage_info(envelope: Any) -> dict:
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    if not isinstance(envelope, dict):
        return {"status": "unknown", "values": {k: None for k in fields}, "invalid_fields": list(fields)}
    if "usage" not in envelope or envelope["usage"] is None or envelope["usage"] == {}:
        return {"status": "missing", "values": {k: None for k in fields}, "invalid_fields": list(fields)}
    usage = envelope["usage"]
    if not isinstance(usage, dict):
        return {"status": "unknown", "values": {k: None for k in fields}, "invalid_fields": list(fields)}
    values = {k: usage[k] if type(usage.get(k)) is int and usage[k] >= 0 else None for k in fields}
    invalid = [k for k in fields if values[k] is None]
    if not invalid and values["total_tokens"] != values["prompt_tokens"] + values["completion_tokens"]:
        invalid.append("total_tokens_inconsistent")
    status = "complete" if not invalid else "partial" if any(v is not None for v in values.values()) else "unknown"
    return {"status": status, "values": values, "invalid_fields": invalid}


def selected_source_bindings(request: dict) -> list[dict]:
    spans = []
    if request.get("task") == "context_brief":
        written = request.get("layers", {}).get("written", {})
        for source in written.get("draft_claims", []):
            spans.append({"kind": "draft_claim", "id": source.get("id"), "text": source.get("text"),
                          "sha256": digest(source.get("text"))})
        for source in written.get("source_spans", []):
            spans.append({"kind": "source_span", "id": source.get("id"), "chapter_id": source.get("chapter_id"),
                          "chapter_number": source.get("chapter_number"), "source_revision": source.get("source_revision"),
                          "text": source.get("body"), "sha256": digest(source.get("body"))})
        for row in request.get("layers", {}).get("confirmed", {}).get("memory_records", []):
            spans.append({"kind": "memory_record", "id": row.get("id"), "source_span_id": row.get("source_span_id"),
                          "text": row.get("value"), "sha256": digest(row.get("value"))})
    else:
        for claim in request.get("claims", []):
            spans.append({"kind": "target_claim", "id": claim.get("id"), "text": claim.get("text"),
                          "sha256": digest(claim.get("text"))})
            for source in claim.get("allowed_evidence", []):
                spans.append({"kind": "allowed_evidence", "id": source.get("id"), "chapter_id": source.get("chapter_id"),
                              "text": source.get("body"), "prompt_excerpt": source.get("prompt_excerpt"),
                              "sha256": digest(source.get("body"))})
        for row in request.get("memory", []):
            spans.append({"kind": "memory_record", "id": row.get("id"), "source_span_id": row.get("source_span_id"),
                          "text": row.get("value"), "sha256": digest(row.get("value"))})
    return spans


class RunJournal:
    def __init__(self, root: pathlib.Path, run_id: str, max_post: int = 108):
        self.root, self.run_id, self.max_post = root, run_id, max_post
        self.post_count = 0

    def case(self, ordinal: int, case: dict) -> "CaseJournal":
        root = self.root / "cases" / f"{ordinal:02d}"
        root.mkdir(parents=True, exist_ok=False)
        write_x(root / "case-start.json", {"run_id": self.run_id, "ordinal": ordinal,
                "case_id": case["case_id"], "family": case["family"], "started_at": stamp(),
                "case_input_sha256": digest(case), "source_ref": case.get("accepted_gold_ref", case.get("accepted_case_ref"))})
        return CaseJournal(self, root, ordinal, case)


class CaseJournal:
    def __init__(self, run: RunJournal, root: pathlib.Path, ordinal: int, case: dict):
        self.run, self.root, self.ordinal, self.case = run, root, ordinal, case
        self.evaluation_count = 0
        self.dispatch_count = 0
        self.current_evaluation: int | None = None
        self.request_sha: str | None = None
        self.max_dispatches = 4 if case["family"] == "comparison" else 2

    def begin_evaluation(self, request: dict) -> pathlib.Path:
        max_evaluations = 2 if self.case["family"] == "comparison" else 1
        if self.evaluation_count >= max_evaluations:
            raise ProviderDispatchDenied("v5_evaluation_cap")
        self.evaluation_count += 1
        self.current_evaluation = self.evaluation_count
        snapshot = copy.deepcopy(request)
        self.request_sha = digest(snapshot)
        path = self.root / "requests" / f"{self.evaluation_count:02d}.json"
        write_x(path, {"case_id": self.case["case_id"], "evaluation_ordinal": self.evaluation_count,
                       "stage": "repair" if request.get("contract_repair") else "first",
                       "recorded_before_dispatch_at": stamp(), "business_request_sha256": self.request_sha,
                       "bindings": snapshot.get("bindings", {"draft_id": snapshot.get("draft", {}).get("id"),
                                                          "draft_revision": snapshot.get("draft", {}).get("revision")}),
                       "selected_source_bindings": selected_source_bindings(snapshot),
                       "business_request": snapshot})
        return path

    def start_post(self, url: str, body: Any) -> tuple[int, float]:
        if self.current_evaluation is None or self.request_sha is None:
            raise RuntimeError("business_snapshot_missing_before_dispatch")
        if self.dispatch_count >= self.max_dispatches or self.run.post_count >= self.run.max_post:
            raise ProviderDispatchDenied("v5_http_dispatch_cap")
        self.dispatch_count += 1
        self.run.post_count += 1
        number = self.dispatch_count
        # Only fixed endpoint and body digest are retained; headers and prompt are not.
        write_x(self.root / "attempts" / f"{number:02d}-start.json", {
            "case_id": self.case["case_id"], "run_id": self.run.run_id,
            "http_ordinal_in_case": number, "global_http_ordinal": self.run.post_count,
            "evaluation_ordinal": self.current_evaluation, "business_request_sha256": self.request_sha,
            "endpoint": "/chat/completions" if url.endswith("/chat/completions") else "unexpected_endpoint",
            "http_body_sha256": digest(body), "started_at": stamp(), "usage_status": "unknown_until_response"})
        return number, time.perf_counter()

    def finish_post(self, number: int, started: float, response: Any = None, error: Exception | None = None) -> None:
        metadata: dict[str, Any] = {"case_id": self.case["case_id"], "http_ordinal_in_case": number,
                                    "finished_at": stamp(), "latency_ms": int((time.perf_counter() - started) * 1000),
                                    "status": getattr(response, "status_code", None),
                                    "error_type": type(error).__name__ if error else None,
                                    "usage": usage_info(None), "response_model": None,
                                    "system_fingerprint": None, "finish_reason": None,
                                    "message_content": None, "message_content_sha256": None,
                                    "response_body_sha256": None, "response_json_status": "unavailable"}
        if response is not None:
            try:
                envelope = response.json()
                metadata["response_json_status"] = "parsed"
                metadata["usage"] = usage_info(envelope)
                if isinstance(envelope, dict):
                    metadata["response_model"] = envelope.get("model")
                    metadata["system_fingerprint"] = envelope.get("system_fingerprint")
                    choices = envelope.get("choices")
                    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                        choice = choices[0]
                        metadata["finish_reason"] = choice.get("finish_reason")
                        message = choice.get("message")
                        if isinstance(message, dict) and isinstance(message.get("content"), str):
                            content = message["content"]
                            metadata["message_content"] = content
                            metadata["message_content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            except (ValueError, TypeError, AttributeError):
                # An invalid envelope can contain unknown fields. Retain only its digest.
                raw = getattr(response, "content", b"")
                metadata["response_body_sha256"] = hashlib.sha256(raw).hexdigest() if isinstance(raw, bytes) else None
        write_x(self.root / "attempts" / f"{number:02d}-finish.json", metadata)

    def finish_evaluation(self, result: ProviderResult | None, error: Exception | None = None) -> None:
        number = self.current_evaluation
        if number is None:
            raise RuntimeError("evaluation_not_started")
        write_x(self.root / "evaluations" / f"{number:02d}.json", {
            "case_id": self.case["case_id"], "evaluation_ordinal": number,
            "business_request_sha256": self.request_sha, "finished_at": stamp(),
            "outcome": "parsed" if result is not None else "error",
            "error_type": type(error).__name__ if error else None,
            "parsed_business_json": result.payload if result is not None else None,
            "reported_usage": {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                               "observed_response_input_tokens": result.observed_response_input_tokens,
                               "observed_response_output_tokens": result.observed_response_output_tokens}
                              if result is not None else None})


class JournalClient:
    def __init__(self, journal: CaseJournal, client_factory=None):
        self.journal = journal
        self.client = client_factory() if client_factory else httpx.Client(timeout=httpx.Timeout(DeepSeekProvider.timeout_seconds))

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, *args):
        return self.client.__exit__(*args)

    def post(self, url, **kwargs):
        number, started = self.journal.start_post(url, kwargs.get("json"))
        try:
            response = self.client.post(url, **kwargs)
        except Exception as error:
            self.journal.finish_post(number, started, error=error)
            raise
        self.journal.finish_post(number, started, response=response)
        return response


class DurableProvider(DeepSeekProvider):
    def __init__(self, journal: CaseJournal, client_factory=None, input_validator=None):
        self.journal = journal
        self.input_validator = input_validator
        super().__init__(client_factory=lambda: JournalClient(journal, client_factory))
        self.request_cap = journal.max_dispatches

    def evaluate(self, request: dict) -> ProviderResult:
        self.journal.begin_evaluation(request)
        try:
            if self.input_validator is not None:
                audit = self.input_validator(self.journal.case, request)
                write_x(self.journal.root / "input-audit" / f"{self.journal.current_evaluation:02d}.json", audit)
            result = super().evaluate(request)
        except Exception as error:
            self.journal.finish_evaluation(None, error)
            raise
        self.journal.finish_evaluation(result)
        return result


class StubProvider:
    label = "flash-v5-offline-stub"
    model_label = "no-model"
    available = True

    def __init__(self, journal: CaseJournal, input_validator=None):
        self.journal = journal
        self.input_validator = input_validator

    def evaluate(self, request: dict) -> ProviderResult:
        self.journal.begin_evaluation(request)
        if self.input_validator is not None:
            audit = self.input_validator(self.journal.case, request)
            write_x(self.journal.root / "input-audit" / f"{self.journal.current_evaluation:02d}.json", audit)
        if self.journal.case["family"] == "comparison":
            payload = {"issues": []}
        else:
            claim = request["layers"]["written"]["draft_claims"][0]
            citation = {"source_type": "draft_claim", "source_id": claim["id"]}
            payload = {"summary": claim["text"], "summary_sources": [citation],
                       "items": [{"section": "recent_source", "text": claim["text"], "sources": [citation]}]}
        result = ProviderResult(payload, input_tokens=1, output_tokens=1, latency_ms=1)
        self.journal.finish_evaluation(result)
        return result
