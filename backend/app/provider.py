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
    "Decide every current claim before emitting output. For each claim, reason in this fixed order: inspect every allowed_evidence span; apply the unresolved-evidence guard; check for direct support; test the smallest relevant combinations of spans; decide conflict, insufficient_evidence, or no continuity issue; select the complete direct Evidence lineage; then assign category and severity. Perform this sequence internally and return only the required JSON.",
    "The unresolved-evidence guard has priority over conflict reasoning. Emit insufficient_evidence, never conflict, when the supplied material explicitly leaves the asserted fact unknown, unregistered, unconfirmed, not recorded, pending, or blank; presents competing possible values without an explicit authority or priority rule; records prerequisites, preparation, inspection, departure, or an attempt without recording the claimed result; or otherwise permits more than one value for the asserted fact. A pending or absent result is not the opposite result.",
    "If one supplied SourceSpan directly supports the whole target claim and no supplied SourceSpan directly contradicts it, omit that claim from issues. Ignore spans that merely mention the same person, object, place, or workflow but do not bear on the target fact. Direct contradiction means conflict; material that neither supports nor refutes the target claim means insufficient_evidence. Emit insufficient_evidence when the retrieved material neither supports nor contradicts the target claim. Material that supports the claim or reveals no continuity risk means omit that claim from issues.",
    "Only after the unresolved-evidence and direct-support guards, a contradiction may be established by a jointly sufficient set of two or more supplied SourceSpans even when no single span states the whole contradiction. Combine explicit premises such as rule plus scope membership, authorization condition plus named holder, sole communication channel plus delivery record, or state-defining rule plus measured result. Do not downgrade a jointly established contradiction to insufficient_evidence merely because each span is incomplete alone.",
    "Every emitted issue must use one claim_span_id from current_claims. Use only conflict or insufficient_evidence for emitted issues; never emit a no_conflict issue.",
    "Emit conflict only when the target claim and the supplied direct facts cannot both be true under the same subject, scope, and time. Every logical link must be explicit in the supplied text. Never turn uncertainty, a missing outcome, an unsigned disagreement, an unranked alternative, a prerequisite, or ordinary absence into the opposite fact. A closed or exhaustive rule may support a contradiction only when the supplied text explicitly says it is closed or exhaustive.",
    "An insufficient_evidence issue must contain evidence: [], must omit the proposed_memory_change key entirely, and must have a short reviewable explanation. Unsupported specific names, numbers, places, sources, causes, or outcomes require insufficient_evidence when the retrieved material does not establish or refute them. Never attach even relevant-looking Evidence to insufficient_evidence.",
    "A conflict must cite the complete direct Evidence lineage needed to review the continuity change. When the decision involves old plus new sources, regular rule plus exception, before plus after state, planned plus actual sequence, earlier plus revised knowledge, assignment plus observed action, departure plus later completion status, or baseline plus measured result, cite every direct SourceSpan in that chain even if the later span alone states the final contradiction. The baseline and transition are both part of the reviewable continuity decision. Apply the same complete-set rule to rule plus scope membership and sole communication channel plus delivery record. Do not cite only the final member of a multi-source lineage and do not add a same-entity span that is not part of the decision chain.",
    "Every Evidence object must be copied from that claim's allowed_evidence. Conflict Evidence must use relation contradicts and sufficiency sufficient. For a multi-source conflict, these values mean that each cited span is a necessary member of the jointly sufficient contradiction set; they do not mean that the span proves the conflict alone. Never cite an ID outside current claim allowed_evidence.",
    "Before returning JSON, perform a structural self-check on every issue. For insufficient_evidence, evidence must equal [] and proposed_memory_change must be absent, not null and not an empty object. For conflict, every cited span must belong to the complete direct lineage, and proposed_memory_change must still be omitted unless fully grounded. For no continuity issue, emit no issue object.",
    "Every emitted issue must include a valid category, severity, and non-empty explanation. Assign category only after deciding the status and complete Evidence set. Apply category by the core decision, not surface words or background context: attribute = an intrinsic, durable, or measured property, including a current measured count; object_state = a named object's state or location at a specific time, especially an operational state rather than a measured property; relationship = a named person or role holder's authorization, responsibility, duty, obligation, kinship, or role relation, even when the context contains a policy, emergency rule, or exception; character_knowledge = what a character knows, believes, has observed, or was told; world_rule = an abstract or global behavior constraint, mechanism, or exception whose subject is not a particular named role holder's authority or responsibility; timeline = event ordering; event_status = whether an event completed, failed, remains open, or has an unknown result; location_action = where a character acted or which action occurred at a location.",
    "Omit proposed_memory_change unless the conflict and its complete direct Evidence set fully ground it: operation is add or replace, memory_type is static_canon, dynamic_state, event_timeline, character_knowledge, or open_thread, subject/predicate/value are non-empty strings, and replace uses a known affected_memory_id.",
)

CONTINUITY_DECISION_EXAMPLES = (
    {"situation": "A draft says a test passed, while the source says the result is pending or the result field is blank.", "decision": "insufficient_evidence; evidence is []; omit proposed_memory_change."},
    {"situation": "Two unranked or unsigned records give different values and no authority or priority rule selects one.", "decision": "insufficient_evidence; do not choose either value and do not call either one a conflict."},
    {"situation": "A baseline, plan, assignment, or earlier state is followed by an explicit later execution, replacement, transfer, or result that contradicts the draft.", "decision": "conflict; cite both the direct baseline span and the direct later transition span."},
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
