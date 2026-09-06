from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .memory_contract import CONTROLLED_PREDICATES

try:
    import httpx
except ModuleNotFoundError:  # Offline unit tests can still exercise pure planning and injected clients.
    httpx = None

HTTP_ERRORS = (httpx.HTTPError,) if httpx else ()
TIMEOUT_ERRORS = (httpx.TimeoutException,) if httpx else ()


class ProviderUnavailable(Exception):
    pass


class ProviderTimeout(Exception):
    pass


class ProviderFailure(Exception):
    pass


class ProviderInvalidJson(Exception):
    """A parsed HTTP response whose message content did not meet the JSON contract.

    Deliberately carries only response metadata.  Raw message content must never
    escape the provider boundary or enter persistence/logging.
    """
    def __init__(self, input_tokens: int | None = None, output_tokens: int | None = None,
                 cost_cny: float | None = None, latency_ms: int | None = None,
                 finish_reason: str | None = None):
        super().__init__("provider_invalid_json")
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_cny = cost_cny
        self.latency_ms = latency_ms
        self.finish_reason = finish_reason
        self.cost_available = cost_cny is not None


class InputBudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class ProviderResult:
    payload: Any
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_cny: float | None = None
    latency_ms: int | None = None
    finish_reason: str | None = None


CONTINUITY_REVIEW_RULES = (
    "Decide every current claim before emitting output. Return the complete output schema for every emitted issue, including nature, reasoning, evidence_chain, suggested_revision, and available_actions. Never emit a no_conflict issue and never mix the new and legacy shapes.",
    "Classify nature as confirmed_conflict only when claim and cited facts cannot coexist under the same subject, scope, and time; say those scope and time links explicitly in reasoning. Use status conflict and only direct, sufficient contradicting evidence.",
    "Classify nature as state_change when a prior state and a later explicit transition can both be true. Explain the before/after ordering in reasoning; do not mislabel an ordinary transition as a confirmed conflict.",
    "Classify nature as possible_conflict when a reviewable tension remains but the supplied material does not establish a direct contradiction. Explain the uncertainty or open-thread boundary and do not claim certainty.",
    "Classify nature and status as insufficient_evidence when a required handoff, learning event, outcome, authority, or other logical link is absent. Cite only supplied context with sufficiency insufficient, use evidence_chain role missing_link, explain exactly why judgment stops, set available_actions to [], and omit proposed_memory_change.",
    "Every evidence item must copy a supplied allowed_evidence span and use only known related Memory ids. evidence_chain must contain each cited span exactly once with role prior_state, current_context, or missing_link.",
    "available_actions may contain only edit, apply_suggestion, keep_intentional, and false_positive. If apply_suggestion is present, suggested_revision must have exact before text occurring once in the bound draft and a distinct after text; otherwise suggested_revision must be null.",
    "Omit proposed_memory_change unless cited sufficient evidence fully grounds it. Add and replace use controlled memory types; replace must bind a supplied Memory id. Author action is still required before canon changes.",
    "Every emitted issue must include a valid category, severity, and non-empty explanation. Assign category only after deciding the status and complete Evidence set. Apply category by the core decision, not surface words or background context: attribute = an intrinsic, durable, or measured property, including a current measured count; object_state = a named object's state or location at a specific time, especially an operational state rather than a measured property; relationship = a named person or role holder's authorization, responsibility, duty, obligation, kinship, or role relation, even when the context contains a policy, emergency rule, or exception; character_knowledge = what a character knows, believes, has observed, or was told; world_rule = an abstract or global behavior constraint, mechanism, or exception whose subject is not a particular named role holder's authority or responsibility; timeline = event ordering; event_status = whether an event completed, failed, remains open, or has an unknown result; location_action = where a character acted or which action occurred at a location.",
)

CONTINUITY_DECISION_EXAMPLES = (
    {"situation": "The same object is assigned to two holders at the same stated moment.", "decision": "confirmed_conflict; explain the shared time and object scope and cite sufficient contradicting evidence."},
    {"situation": "An earlier holder is followed by an explicit later placement.", "decision": "state_change; explain the prior and later states and keep both temporally valid."},
    {"situation": "A claimed knowledge transfer has no supplied handoff event.", "decision": "insufficient_evidence; cite the missing-link context as insufficient and expose no author decision actions."},
    {"situation": "One span directly supports the full draft claim and other retrieved spans only share names or context.", "decision": "no continuity issue; emit no issue object."},
)

MEMORY_INITIALIZATION_RULES = (
    "Candidates are suggestions for an author, never canon. Do not claim facts that are not directly stated in the supplied source spans.",
    "Every candidate must contain memory_type, subject, predicate, value, chapter_id, and source_span_id. memory_type must be static_canon, dynamic_state, event_timeline, character_knowledge, or open_thread.",
    "Use exactly one supplied SourceSpan for each candidate. Do not invent chapter IDs or SourceSpan IDs. Keep subject concise and value directly grounded in its SourceSpan.",
    "predicate must be exactly one value from controlled_predicates and chosen by semantic meaning: identity, relationship, affiliation, location, status, rule, possession, event_occurred, or knowledge. For open_thread, still select the closest controlled predicate; open_thread remains an author-review supporting suggestion, not a core candidate.",
    "Emit at most 4 candidates in this batch. Keep subject, predicate, and value within target lengths of 80, 80, and 240 Unicode characters respectively.",
    "Chunk metadata is prompt-only provenance. Never emit chunk_id; source_span_id must always be the supplied original SourceSpan ID.",
    "Prefer a small, non-duplicative set of durable facts. Omit uncertain inferences.",
)

MEMORY_DELTA_RULES = (
    "Keep the layers separate: source_spans are current manuscript evidence, confirmed_memory is the immutable base Story Memory, and candidates are AI suggestions for author review. Candidates are never canon.",
    "Every candidate must contain exactly change_kind, affected_memory_id, memory_type, subject, predicate, value, invalidation_reason, chapter_id, and source_span_id. change_kind must be new_fact, changed_fact, or invalidated_fact. source_span_id must be one supplied current-revision SourceSpan.",
    "For new_fact, affected_memory_id and invalidation_reason must be null, and the fact must not duplicate an existing confirmed identity.",
    "For changed_fact, affected_memory_id must be exactly one supplied confirmed_memory id, invalidation_reason must be null, and the proposed fact must materially differ from that affected fact.",
    "For invalidated_fact, affected_memory_id must be exactly one supplied confirmed_memory id; memory_type, subject, predicate, and value must repeat that affected fact exactly; invalidation_reason must explain what current manuscript evidence makes it no longer valid. Do not invent an opposite fact.",
    "predicate must be exactly one value from controlled_predicates. Choose the closest semantic value; open_thread is still supporting and never a core candidate.",
    "Do not emit unsupported inferences, previous-source IDs, Author Context, author plans, alignment analysis, or a priority. Do not emit duplicate candidates or multiple candidates for one affected Memory record. The service decides core versus supporting.",
)

ANALYSIS_LAYER_RULES = (
    "Keep the four layers separate: planned is Author Context, confirmed is Story Memory, written is draft or SourceSpan text, and analysis is your conclusion. Never present planned content as written or confirmed evidence.",
    "Use only supplied IDs. Every citation must resolve to a supplied item, and every conclusion must stay within the supplied bounded retrieval set.",
    "Return exactly the requested JSON shape, enums, and keys. Do not use Markdown, tools, external search, or facts outside the request.",
)

MAX_TOTAL_BUDGET_UNITS = 8000
MAX_INPUT_BUDGET_UNITS = 6000
MAX_OUTPUT_BUDGET_UNITS = 2000
MEMORY_BATCH_TARGET_BUDGET_UNITS = 5800
MAX_MEMORY_CANDIDATES_PER_BATCH = 4
INPUT_BUDGET_ALGORITHM = "mixed-char-estimator-v1"


def estimate_prompt_budget_units(prompt: str) -> int:
    """Conservative pre-call budget units; this is not provider-reported usage."""
    ascii_count = sum(ord(char) < 128 for char in prompt)
    non_ascii_count = len(prompt) - ascii_count
    return math.ceil(ascii_count / 4) + math.ceil(non_ascii_count * 1.25) + 256


def memory_initialization_prompt(request: dict[str, Any]) -> str:
    payload = {
            "task": "Extract candidate Story Memory facts from the imported source only. Return exactly one JSON object with exactly one top-level key, candidates. Do not use Markdown.",
            "rules": list(MEMORY_INITIALIZATION_RULES),
            "controlled_predicates": request.get("controlled_predicates", list(CONTROLLED_PREDICATES)),
            "output_limits": {"max_candidates": MAX_MEMORY_CANDIDATES_PER_BATCH, "subject_max_chars": 80, "predicate_max_chars": 80, "value_max_chars": 240},
            "source_revision": request["source_revision"],
            "source_spans": [
                {"chapter_id": source["chapter_id"], "chapter_number": source["chapter_number"], "chapter_title": source["chapter_title"],
                 "source_span_id": source["id"], "label": source["label"], "text": source["body"],
                 **({key:source[key] for key in ("chunk_id","chunk_ordinal","chunk_start","chunk_end")} if "chunk_id" in source else {})}
                for source in request["sources"]
            ],
            "output_schema": request["output_schema"],
        }
    repair=request.get("schema_repair")
    if isinstance(repair,dict):
        repair_payload={"attempt":repair.get("attempt"),"global_attempt":repair.get("global_attempt"),"reason_code":repair.get("reason_code"),"instruction":"The previous response was rejected by the local schema validator. Re-extract from the same supplied spans and obey every output key, enum, count, type, and length constraint exactly. memory_type must be exactly one of static_canon, dynamic_state, event_timeline, character_knowledge, or open_thread. predicate must be exactly one supplied controlled_predicates value. Do not mention the previous response."}
        if repair.get("field") in {"memory_type","subject","predicate","value","chapter_id","source_span_id"}:
            repair_payload["field"]=repair["field"]
        if isinstance(repair.get("candidate_ordinal"),int) and not isinstance(repair.get("candidate_ordinal"),bool) and repair["candidate_ordinal"]>=1:
            repair_payload["candidate_ordinal"]=repair["candidate_ordinal"]
        payload["schema_repair"]=repair_payload
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def continuity_prompt(request: dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "Review continuity only. Return exactly one JSON object with exactly one top-level key, issues. Do not use Markdown or include any other top-level key.",
            "rules": list(CONTINUITY_REVIEW_RULES), "decision_examples": list(CONTINUITY_DECISION_EXAMPLES), "draft": request["draft"],
            "current_claims": [
                {"id": claim["id"], "text": claim["text"], "allowed_evidence": [
                    {"id": span["id"], "chapter_id": span["chapter_id"], "excerpt": span.get("prompt_excerpt", span["body"])}
                    for span in claim["allowed_evidence"]
                ]} for claim in request["claims"]
            ],
            "memory": request["memory"], "output_schema": request["output_schema"],
        }, ensure_ascii=False, separators=(",", ":"),
    )


def memory_delta_prompt(request: dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "Extract author-reviewable Story Memory changes from this new source revision only. Return exactly one JSON object with exactly one top-level key, candidates. Do not use Markdown.",
            "rules": list(MEMORY_DELTA_RULES),
            "controlled_predicates": request.get("controlled_predicates", list(CONTROLLED_PREDICATES)),
            "source_revision": request["source_revision"],
            "confirmed_memory": request["memory"],
            "source_spans": [
                {"chapter_id": source["chapter_id"], "chapter_number": source["chapter_number"], "chapter_title": source["chapter_title"],
                 "source_span_id": source["id"], "label": source["label"], "text": source["body"]}
                for source in request["sources"]
            ],
            "output_schema": request["output_schema"],
        }, ensure_ascii=False, separators=(",", ":"),
    )


def context_brief_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Create a compact pre-writing chapter context brief. Return exactly summary, summary_sources, and items.","rules":[*ANALYSIS_LAYER_RULES,"Cover relevant plans, confirmed facts, character state, world rules, unresolved threads, and recent written sources when supported. Every item needs at least one citation."],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def plan_alignment_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Compare the saved draft with each supplied story plan. Return exactly summary and items.","rules":[*ANALYSIS_LAYER_RULES,"Return exactly one item for every supplied story_plan_id.","Status must be planned_covered, planned_missing, planned_early, planned_changed, or insufficient_evidence.","planned_covered, planned_early, and planned_changed require direct current-draft claim or SourceSpan evidence. planned_missing may cite no written evidence only when the planned point is absent from the bounded draft. Never use Author Context itself as proof that something was written."],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def change_impact_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Analyze the likely impact of the author's explicit proposed change. Return exactly summary and items.","rules":[*ANALYSIS_LAYER_RULES,"Report only affected supplied chapters, characters, world records, Story Memory records, or plans.","Every impact item requires at least one directly relevant supplied evidence citation. If there is no evidence, emit no conclusion for that target.","Do not write replacement prose, auto-save the proposal, or mutate draft, source, Story Memory, Author Context, or aliases."],"proposal":request["proposal"],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def story_qa_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Answer one author question only from the supplied bounded project evidence. Return exactly answer_status, answer, and findings.","rules":[*ANALYSIS_LAYER_RULES,"Respect the requested scope exactly.","A confirmed finding may cite only Story Memory; a written finding may cite only current draft claims or SourceSpan text; a planned finding may cite only Author Context.","Every non-insufficient finding needs direct evidence. If evidence is absent, return insufficient with no findings. If supplied evidence disagrees, return conflicting and include both supports and contradicts findings.","Do not turn inference into fact and do not mutate any author or manuscript data."],"question":request["question"],"scope":request["scope"],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def foreshadow_scan_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Find reviewable foreshadow candidates in supplied written evidence. Return exactly summary and candidates.","rules":[*ANALYSIS_LAYER_RULES,"Candidates are suggestions only; never create or modify an author foreshadow record.","Every candidate needs direct current draft claim or SourceSpan evidence and must label each citation as planted, developing, or resolved.","Do not duplicate an existing author record or another candidate. If there is no written evidence, return an empty candidate list.","Do not cite Story Memory or Author Context as written proof."],"author_records":request["author_records"],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def revision_plan_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Create one bounded revision-task suggestion for every selected continuity issue. Return exactly summary and candidates.","rules":[*ANALYSIS_LAYER_RULES,"Each candidate must reference exactly one supplied issue_id and at least one evidence id supplied for that same issue.","Write a concise editing action, not replacement fiction prose. Suggestions never edit the manuscript, resolve an Issue, change canon, or create a task without author acceptance.","Return each selected issue exactly once. Do not merge issues, invent references, duplicate titles, or add unselected work."],"source_run_id":request["source_run_id"],"selected_issues":request["selected_issues"],"bindings":request["bindings"],"layers":request["layers"],"author_records":request["author_records"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def request_prompt_and_budget(request: dict[str, Any]) -> tuple[str, int]:
    task=request.get("task")
    prompt = memory_initialization_prompt(request) if task == "memory_initialization" else memory_delta_prompt(request) if task == "memory_delta" else context_brief_prompt(request) if task == "context_brief" else plan_alignment_prompt(request) if task == "plan_alignment" else change_impact_prompt(request) if task == "change_impact" else story_qa_prompt(request) if task == "story_qa" else foreshadow_scan_prompt(request) if task == "foreshadow_scan" else revision_plan_prompt(request) if task == "revision_plan" else continuity_prompt(request)
    return prompt, estimate_prompt_budget_units(prompt)


def parse_json_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    candidate = content.strip()
    lines = candidate.splitlines()
    if len(lines) >= 2 and lines[0].strip().lower() in {"```", "```json"} and lines[-1].strip() == "```":
        candidate = "\n".join(lines[1:-1]).strip()
    return json.loads(candidate)


class ProviderPort(Protocol):
    label: str

    @property
    def available(self) -> bool: ...

    def evaluate(self, request: dict[str, Any]) -> ProviderResult: ...


class DeepSeekProvider:
    label = "deepseek"
    api_format_label = "chat-completions-json-object"
    max_output_tokens = MAX_OUTPUT_BUDGET_UNITS
    timeout_seconds = 30
    max_retries = 1

    def __init__(self, client_factory=None):
        self.model = os.getenv("CONTINUITY_MODEL", "")
        self.base_url = os.getenv("CONTINUITY_BASE_URL", "")
        self.api_key = os.getenv("CONTINUITY_API_KEY", "")
        self.enabled = os.getenv("CONTINUITY_PROVIDER", "").lower() == "deepseek"
        self._factory = client_factory or (lambda: httpx.Client(timeout=httpx.Timeout(self.timeout_seconds)))
        self.request_attempts = 0
        self.successful_responses = 0
        self.request_cap: int | None = None

    @property
    def model_label(self):
        return self.model or "unconfigured"

    @property
    def available(self):
        return bool(self.enabled and self.model and self.base_url and self.api_key)

    def _memory_initialization_prompt(self, request: dict[str, Any]) -> str:
        return memory_initialization_prompt(request)

    def _continuity_prompt(self, request: dict[str, Any]) -> str:
        return continuity_prompt(request)

    def evaluate(self, request: dict[str, Any]) -> ProviderResult:
        if not self.available:
            raise ProviderUnavailable()
        prompt, input_budget_units = request_prompt_and_budget(request)
        if input_budget_units > MAX_INPUT_BUDGET_UNITS:
            raise InputBudgetExceeded()
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
        }
        started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                request_cap=getattr(self,"request_cap",None)
                if request_cap is not None and self.request_attempts >= request_cap:
                    raise ProviderFailure()
                self.request_attempts += 1
                with self._factory() as client:
                    response = client.post(
                        self.base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json=body,
                    )
                    response.raise_for_status()
                    raw = response.json()
                    usage = raw.get("usage", {})
                    choice = raw["choices"][0]
                    finish_reason = choice.get("finish_reason")
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    try:
                        parsed = parse_json_content(choice["message"]["content"])
                    except json.JSONDecodeError as error:
                        raise ProviderInvalidJson(
                            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("cost_cny"),
                            latency_ms, finish_reason,
                        ) from error
                    self.successful_responses += 1
                    return ProviderResult(
                        parsed,
                        usage.get("prompt_tokens"),
                        usage.get("completion_tokens"),
                        usage.get("cost_cny"),
                        latency_ms,
                        finish_reason,
                    )
            except TIMEOUT_ERRORS as error:
                if attempt == self.max_retries:
                    raise ProviderTimeout() from error
            except HTTP_ERRORS + (AttributeError, ValueError, KeyError, TypeError) as error:
                raise ProviderFailure() from error
