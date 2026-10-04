from __future__ import annotations

import contextvars
import os
import re
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from . import brief_citations
from .internal_ids import strip_internal_ids
from .memory_contract import CONTROLLED_PREDICATES, predicate_label
from .provider import MAX_CLAIM_BASIS_CODEPOINTS, MAX_ISSUE_REASONING_CODEPOINTS
from .provider import ProviderDispatchDenied
from .provider import CONTINUITY_PROMPT_VERSION, InputBudgetExceeded, MAX_INPUT_BUDGET_UNITS, MAX_MEMORY_CANDIDATES_PER_BATCH, MEMORY_BATCH_TARGET_BUDGET_UNITS, ProviderFailure, ProviderInvalidJson, ProviderPort, ProviderTimeout, ProviderUnavailable, request_prompt_and_budget, review_effort_scope
from .provider import CONTINUITY_SCREENED_PROMPT_VERSION, CONTINUITY_SCREEN_PROMPT_VERSION, input_budget_units_for
from . import review_screening as screening
from .review_screening import SCREENED_RETRIEVAL_METHOD_VERSION

ALLOWED_STATUS={"conflict","insufficient_evidence"}
ALLOWED_CATEGORY={"attribute","location_action","timeline","character_knowledge","object_state","relationship","world_rule","event_status"}
ALLOWED_SEVERITY={"low","medium","high"}
ALLOWED_MEMORY_TYPE={"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"}
REVIEW_NATURES={"confirmed_conflict","possible_conflict","state_change","insufficient_evidence"}
REVIEW_ACTIONS={"edit","apply_suggestion","keep_intentional","false_positive"}
EVIDENCE_CHAIN_ROLES={"prior_state","current_context","missing_link"}
MAX_RUN_TOKENS=8000
PROMPT_VERSION=CONTINUITY_PROMPT_VERSION
# The screened pipeline (review_screening.py) is the default. CONTINUITY_REVIEW_PIPELINE=legacy is the
# temporary rollback to per-sentence review; a run keeps the pipeline recorded when it was created.
REVIEW_PIPELINE_ENV="CONTINUITY_REVIEW_PIPELINE"
SCREENED_PROMPT_VERSION=f"{CONTINUITY_SCREENED_PROMPT_VERSION}+{CONTINUITY_SCREEN_PROMPT_VERSION}"
MEMORY_PROMPT_VERSION="memory-initialization-v10-whole-chapter-rules"
RETRIEVAL_METHOD_VERSION="bounded-lexical-v4-longform"
RELATED_MEMORY_LIMIT=15
CONTINUITY_EVIDENCE_LIMIT=3
# Spans with a Memory record are weighted 10x, and Memory holds only a few facts per work, so the
# span that matches the claim's own words best could be crowded out by spans that merely have a
# record. These slots always go to the best direct text matches.
CONTINUITY_DIRECT_TEXT_SLOTS=2
CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS=500
# Input budget alone let a batch grow to 12-13 claims once evidence is shared, but thinking output is
# what fills: one to three claims already produced 0.5k-13.5k output tokens against a 16k cap, and a
# length stop steps the whole run down to medium effort. Small batches also parallelize and keep a
# contract repair small. Held-out drafts are one to three sentences, so eval runs are unaffected.
CONTINUITY_MAX_CLAIMS_PER_BATCH=4
# The per-account dispatch quota refusal (stage13.reserve_provider_attempt). Mid-chapter it leaves the
# rest of the chapter undecided instead of failing the run.
PROVIDER_ATTEMPT_QUOTA_EXCEEDED="provider_attempt_quota_exceeded"
# A single claim whose full evidence and Memory do not fit the input budget (the v21 rules left the
# long-form worst case at 6,324 of 6,000 units) is sent with these tighter bounds instead of failing.
SINGLE_CLAIM_FALLBACK_BOUNDS=((CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS,RELATED_MEMORY_LIMIT),(400,12),(300,10),(200,8))
# The screened equivalent: fewer passages, then fewer Memory rows.
SCREENED_SINGLE_CLAIM_FALLBACK_BOUNDS=((screening.VERIFY_MAX_PASSAGES,RELATED_MEMORY_LIMIT),(4,12),(2,10),(1,8))
MEMORY_DELTA_RELATED_MEMORY_LIMIT=20
# A batch may return MAX_MEMORY_CANDIDATES_PER_BATCH facts, so batches are also capped by source text
# (about one ordinary chapter): packing several chapters into one request let the first crowd out the
# rest (lf1 dev set, 2026-10-04: chapter 2 kept 3 facts after chapter 1 took 5 of the 8).
MEMORY_BATCH_TARGET_SOURCE_CHARS=2600
SOURCE_CHUNK_METHOD_VERSION="source-chunk-v4-5800"
MAX_CHUNK_OVERLAP_CODEPOINTS=200
MEMORY_SCHEMA_REPAIR_MAX_ATTEMPTS=5
MEMORY_SCHEMA_REPAIR_MAX_PER_BATCH=2
MEMORY_CANDIDATE_FIELDS=("memory_type","subject","predicate","value","chapter_id","source_span_id")
MEMORY_DELTA_CANDIDATE_FIELDS=("change_kind","affected_memory_id","memory_type","subject","predicate","value","invalidation_reason","chapter_id","source_span_id")
MEMORY_REPAIRABLE_ERRORS={"top_level_shape_invalid","candidate_collection_invalid","candidate_count_invalid","empty_candidates","candidate_fields_invalid","memory_type_invalid","required_field_type_invalid","required_field_blank","candidate_length_invalid","evidence_unresolvable"}
ANALYSIS_RETRIEVAL_METHOD_VERSION="writing-analysis-lexical-v2-draft-claims"
CONTEXT_BRIEF_RETRIEVAL_METHOD_VERSION="writing-analysis-lexical-v3-brief-540"
CONTEXT_BRIEF_PROMPT_VERSION="context-brief-v5-clause-citations"
PLAN_ALIGNMENT_PROMPT_VERSION="plan-alignment-v4-clause-citations"
CHANGE_IMPACT_PROMPT_VERSION="change-impact-v3-supplied-targets"
STORY_QA_PROMPT_VERSION="story-qa-v3-no-prose-ids"
FORESHADOW_SCAN_PROMPT_VERSION="foreshadow-scan-v7-clause-citations"
REVISION_PLAN_PROMPT_VERSION="revision-plan-v2-clause-citations"
AUTHOR_MATERIAL_COMPARISON_PROMPT_VERSION="author-material-comparison-v3-nature-assessments"
CHANGE_IMPACT_INSUFFICIENT_SUMMARY="当前证据不足以支持影响结论。"
STORY_QA_INSUFFICIENT_ANSWER="当前证据不足以回答这个问题。"
FORESHADOW_INSUFFICIENT_SUMMARY="当前未发现有可采信已写证据的伏笔候选。"
PLAN_ALIGNMENT_STATUSES={"planned_covered","planned_missing","planned_early","planned_changed","insufficient_evidence"}
CONTEXT_BRIEF_SECTIONS={"related_plan","confirmed_fact","character_state","world_rule","open_thread","recent_source"}
STORY_QA_STATUSES={"answered","partial","insufficient","conflicting"}
STORY_QA_LAYERS={"confirmed","written","planned"}
REVISION_TASK_PRIORITIES={"high","medium","low"}


class MemoryCandidateValidationError(ValueError):
    """A redacted validation failure with only allowlisted structural context."""
    def __init__(self, code: str, *, field: str | None = None, candidate_ordinal: int | None = None):
        super().__init__(code)
        self.code=code
        self.field=field if field in MEMORY_CANDIDATE_FIELDS else None
        self.candidate_ordinal=candidate_ordinal if isinstance(candidate_ordinal,int) and candidate_ordinal>=1 else None

    def safe_context(self)->dict[str,Any]:
        context={}
        if self.field is not None:context["invalid_field"]=self.field
        if self.candidate_ordinal is not None:context["invalid_candidate_ordinal"]=self.candidate_ordinal
        return context


class ContinuityContractValidationError(ValueError):
    """A semantic contract failure that permits one bounded provider repair."""

    def __init__(self, code: str, *, diagnostics: list[dict[str, Any]] | None = None):
        super().__init__(code)
        self.diagnostics = diagnostics or []


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _requires_cjk(value: str) -> bool:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    return cjk >= 4 and cjk >= latin


def _clock_values(value: str) -> set[int] | None:
    """Return explicit clock minutes; None means an invalid/unsupported colon clock."""
    pattern = r"(?<![\w:])(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|(?<![A-Za-z0-9_:])(\d{1,2}):(\d{2})(?![A-Za-z0-9_:])(?!\s*(?:am|pm)[A-Za-z0-9_])"
    clocks: set[int] = set()
    matches = list(re.finditer(pattern, value, re.IGNORECASE))
    for token in re.finditer(r"\d+(?::\d+)+", value):
        if not any(match.start() <= token.start() and match.end() >= token.end() for match in matches):
            return None
    for match in matches:
        hour, minute = int(match[1] or match[4]), int(match[2] or match[5] or 0)
        meridiem = (match[3] or "").lower()
        if minute > 59 or hour > (12 if meridiem else 23) or (meridiem and hour < 1):
            return None
        if meridiem:
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        clocks.add(hour * 60 + minute)
    return clocks


_ENGLISH_MONTHS = {name: number for number, names in enumerate(
    (("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
     ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
     ("december", "dec")), 1) for name in names}
_MONTH_NAME = r"(" + "|".join(sorted(_ENGLISH_MONTHS, key=len, reverse=True)) + r")\.?"


def _english_calendar(value: str) -> dict[str, set[str]]:
    """Explicit English or ISO calendar dates as the same 年/月/日 components used for Chinese dates."""
    parsed: dict[str, set[str]] = {}
    def add(year: str | None, month: int | str, day: str) -> None:
        if isinstance(month, str):
            # "may" is also a common verb; only the capitalised month name counts.
            if month.casefold() == "may" and month != "May":
                return
            month = _ENGLISH_MONTHS[month.casefold()]
        if 1 <= month <= 12 and 1 <= int(day) <= 31:
            parsed.setdefault("月", set()).add(str(month)); parsed.setdefault("日", set()).add(str(int(day)))
            if year:
                parsed.setdefault("年", set()).add(str(int(year)))
    for day, month, year in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_NAME + r"(?:,?\s+(\d{4}))?\b", value, re.IGNORECASE):
        add(year, month, day)
    for month, day, year in re.findall(r"\b" + _MONTH_NAME + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", value, re.IGNORECASE):
        add(year, month, day)
    for year, month, day in re.findall(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", value):
        add(year, int(month), day)
    return parsed


def _temporal_anchor_is_explicit(value: str) -> bool:
    clocks = _clock_values(value)
    if clocks is None:
        return False
    if clocks or _english_calendar(value):
        return True
    return bool(re.search(
        r"(?:\d{1,4}\s*(?:年|月|日|号|点|时|分|秒|章)|[一二三四五六七八九十百零两]+\s*(?:年|月|日|号|点|时|分|秒|章)|"
        r"同一(?:天|夜|晚|时刻|时间)|与此同时|同时|当时|此刻|刚落|之后|以前|以前|直到|"
        r"\b(?:same\s+(?:day|night|time|moment)|simultaneously|at\s+that\s+(?:time|moment)|before|after|until)\b)",
        value,
        re.IGNORECASE,
    ))


def _explicit_temporal_overlap(claim_anchor: str, evidence_anchor: str) -> bool:
    if not _temporal_anchor_is_explicit(claim_anchor) or not _temporal_anchor_is_explicit(evidence_anchor):
        return False
    claim_clocks, evidence_clocks = _clock_values(claim_anchor), _clock_values(evidence_anchor)
    if claim_clocks is None or evidence_clocks is None:
        return False
    if (claim_clocks or evidence_clocks) and (len(claim_clocks) != 1 or claim_clocks != evidence_clocks):
        return False
    day_aliases={"前天":"day_minus_2","昨日":"day_minus_1","昨天":"day_minus_1","今日":"day_0","今天":"day_0","明日":"day_plus_1","明天":"day_plus_1","后天":"day_plus_2","day before yesterday":"day_minus_2","yesterday":"day_minus_1","today":"day_0","tomorrow":"day_plus_1"}
    def relative_day(value:str)->str|None:
        match=re.search(r"前天|昨日|昨天|今日|今天|明日|明天|后天|\b(?:day before yesterday|yesterday|today|tomorrow)\b",value,re.IGNORECASE)
        return day_aliases.get(match.group().casefold()) if match else None
    claim_day=relative_day(claim_anchor);evidence_day=relative_day(evidence_anchor)
    if (claim_day or evidence_day) and claim_day!=evidence_day:return False
    component_pattern=r"(\d{1,4}|[一二三四五六七八九十百零两]+)\s*(年|月|日|号|点|时|分|秒|章)"
    unit_group={"号":"日","时":"点"}
    digit_map={"零":"0","一":"1","二":"2","两":"2","三":"3","四":"4","五":"5","六":"6","七":"7","八":"8","九":"9"}
    def normalized_number(raw:str)->str:
        if raw.isdigit():return str(int(raw))
        if "十" in raw and all(char in digit_map or char=="十" for char in raw):
            left,right=raw.split("十",1)
            return str((int(digit_map[left]) if left else 1)*10+(int(digit_map[right]) if right else 0))
        if all(char in digit_map for char in raw):return str(int("".join(digit_map[char] for char in raw)))
        return raw
    def components(value:str)->dict[str,set[str]]:
        parsed:dict[str,set[str]]={}
        for raw,unit in re.findall(component_pattern,value,re.IGNORECASE):
            parsed.setdefault(unit_group.get(unit,unit),set()).add(normalized_number(raw.casefold()))
        for unit,values in _english_calendar(value).items():
            parsed.setdefault(unit,set()).update(values)
        if clocks := _clock_values(value):
            parsed["clock"] = {str(clock) for clock in clocks}
        return parsed
    claim_components=components(claim_anchor);evidence_components=components(evidence_anchor)
    shared_units=set(claim_components)&set(evidence_components)
    if claim_components or evidence_components:
        if any(claim_components[unit].isdisjoint(evidence_components[unit]) for unit in shared_units):return False
        return any(claim_components[unit]&evidence_components[unit] for unit in shared_units)
    relational_pattern=r"(?:同一(?:天|夜|晚|时刻|时间)|与此同时|同时|当时|此刻|\b(?:same\s+(?:day|night|time|moment)|simultaneously|at\s+that\s+(?:time|moment))\b)"
    return bool(re.search(relational_pattern,claim_anchor,re.IGNORECASE) and re.search(relational_pattern,evidence_anchor,re.IGNORECASE))


def _full_temporal_scope_supports_conflict(claim_text: str, evidence_text: str, claim_anchor: str, evidence_anchor: str) -> bool:
    """Qualify model-selected anchors against the bound statements, not just their substrings."""
    if not _explicit_temporal_overlap(claim_anchor,evidence_anchor):return False
    def supporting_sentence(value:str,anchor:str)->str|None:
        sentences=[match.group().strip() for match in re.finditer(r"[^。！？.!?]+[。！？.!?]?",value) if match.group().strip()]
        matches=[sentence for sentence in sentences if anchor in sentence]
        return matches[0] if len(matches)==1 else None
    claim_scope=supporting_sentence(claim_text,claim_anchor)
    evidence_scope=supporting_sentence(evidence_text,evidence_anchor)
    if claim_scope is None or evidence_scope is None:return False
    # A recalled event or attributed utterance has a different assertion scope
    # from a narrator-confirmed state, even when its surface clock matches.
    framed=r"回忆|追忆|想起|闪回|梦见|梦到|谎称|撒谎|说谎|假称|故意骗|声称|宣称|自称|说自己|表示自己|据称|引述|转述|听说|告诉|\b(?:recall|remember|flashback|dream|lied?|said|claimed|reported|told|falsely claimed)\b"
    if re.search(framed,claim_scope,re.IGNORECASE) or re.search(framed,evidence_scope,re.IGNORECASE):return False
    aliases={"前天":"relative:-2","昨日":"relative:-1","昨天":"relative:-1","今日":"relative:0","今天":"relative:0","明日":"relative:1","明天":"relative:1","后天":"relative:2","day before yesterday":"relative:-2","yesterday":"relative:-1","today":"relative:0","tomorrow":"relative:1"}
    def days(value:str)->set[str]:
        found={aliases[match.group().casefold()] for match in re.finditer(r"前天|昨日|昨天|今日|今天|明日|明天|后天|\b(?:day before yesterday|yesterday|today|tomorrow)\b",value,re.IGNORECASE)}
        found.update("ordinal:"+match.group(1).translate(str.maketrans("零一二三四五六七八九", "0123456789")) for match in re.finditer(r"第\s*([零一二三四五六七八九十百两\d]+)\s*天",value))
        return found
    claim_days,evidence_days=days(claim_scope),days(evidence_scope)
    if len(claim_days)>1 or len(evidence_days)>1 or (claim_days or evidence_days) and claim_days!=evidence_days:return False
    if not _explicit_temporal_overlap(claim_scope,evidence_scope):return False
    # 时 followed by 段/间/候/期/刻 is a word ("这一时段", "一时间"), not a clock.
    clock=r"(?:\d{1,2}|[一二三四五六七八九十两]+)\s*(?:点|时(?![段间候期刻]))|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|(?<![\d:])\d{1,2}:\d{2}(?![\d:])"
    def clock_values(value:str)->set[str]:
        return {match.group().replace(" ","").translate(str.maketrans("一二三四五六七八九", "123456789")) for match in re.finditer(clock,value,re.IGNORECASE)}
    claim_clocks=clock_values(claim_scope)
    if len(claim_clocks)>1:return False
    # An evidence sentence may state a span ("十六时……签到了十七时才离开"); it still qualifies when its
    # anchor is the sentence's opening clock and that is the claim's own clock (lf1 dev set, 2026-10-04).
    # A later clock in the sentence ("直到十九点才获知") marks a transition and never qualifies.
    if len(clock_values(evidence_scope))>1:
        first=re.search(clock,evidence_scope,re.IGNORECASE)
        opening=clock_values(first.group()) if first else set()
        if not (claim_clocks and claim_clocks==opening and opening<=clock_values(evidence_anchor)):return False
    calendar=r"(?:\d{1,4}|[一二三四五六七八九十百零两]+)\s*(?:年|月|日|号)"
    shared_scope=r"同一(?:天|夜|晚|时刻|时间)|与此同时|同时|\b(?:same\s+(?:day|night|time|moment)|simultaneously)\b"
    if re.search(clock,claim_anchor,re.IGNORECASE) and re.search(clock,evidence_anchor,re.IGNORECASE) and not claim_days:
        dated=lambda scope:bool(re.search(calendar,scope) or _english_calendar(scope))
        if not (dated(claim_scope) and dated(evidence_scope)) and not (re.search(shared_scope,claim_scope,re.IGNORECASE) and re.search(shared_scope,evidence_scope,re.IGNORECASE)):return False
    return True


def _confirmed_temporal_failure(raw: dict[str, Any], claim_text: str, evidence: list[dict[str, Any]], memory: dict[str, Any]) -> str | None:
    """One qualification rule for both repair diagnostics and persisted Issues."""
    if raw.get("nature") != "confirmed_conflict":
        return None
    temporal = raw.get("temporal_basis")
    if not isinstance(temporal, dict):
        return "temporal_overlap_unproven"
    claim_anchor, evidence_anchor = temporal.get("claim_anchor"), temporal.get("evidence_anchor")
    if temporal.get("relation") == "explicit_overlap":
        if (isinstance(claim_anchor, str) and isinstance(evidence_anchor, str) and
            any(item.get("relation") == "contradicts" and item.get("sufficiency") == "sufficient" and
                evidence_anchor in item["excerpt"] and
                _full_temporal_scope_supports_conflict(claim_text, item["excerpt"], claim_anchor, evidence_anchor)
                for item in evidence)):
            return None
        return "temporal_overlap_unproven"
    if temporal.get("relation") == "timeless_rule":
        related_ids = {memory_id for item in evidence for memory_id in item.get("related_memory_ids", [])
                       if isinstance(memory_id, str) and memory_id in memory}
        # A screened review cites passages; the rule's SourceSpan is the one each passage was cut from.
        cited_ids = {item.get("source_span_id", item["span_id"]) for item in evidence}
        # static_canon is by definition durable canon or a world rule. Authors and legacy seeds use
        # free-form predicates (e.g. entry_rule), so the predicate is not required to be "rule";
        # requiring it sent every such conflict into an unsatisfiable repair.
        if any(memory[memory_id].get("memory_type") == "static_canon" and
               memory[memory_id].get("source_span_id") in cited_ids for memory_id in related_ids):
            return None
        return "timeless_rule_unproven"
    return "temporal_overlap_unproven"


def _contract_diagnostic(data: dict[str, Any], code: str, claim_id: str | None = None, **details: Any) -> dict[str, Any]:
    claim = next((item for item in data["claims"] if item["id"] == claim_id), None)
    return {"claim_span_id": claim["id"] if claim else None, "claim_text": claim["text"] if claim else None,
            "problem_codes": [code], "cited_evidence": [], **details}


def _reasoning_length_diagnostic(data: dict[str, Any], claim_id: str, reasoning: str) -> dict[str, Any]:
    return _contract_diagnostic(data, "reasoning_too_long", claim_id, invalid_field="reasoning", problem="too_long",
                                observed_length=len(reasoning.strip()), limit=MAX_ISSUE_REASONING_CODEPOINTS)


def _continuity_schema() -> dict[str, Any]:
    return {"claim_verdicts":[{"claim_span_id":"every supplied current claim id exactly once","verdict":"reviewed_issue|insufficient_evidence|no_issue","basis":f"non-empty string, at most {MAX_CLAIM_BASIS_CODEPOINTS} Unicode code points; concise decision reason, not a reasoning transcript"}],"issues":[{"claim_span_id":"current claim id","status":"conflict|insufficient_evidence","nature":"confirmed_conflict|possible_conflict|state_change|insufficient_evidence","category":"allowed category","severity":"low|medium|high","explanation":"short backwards-compatible summary","reasoning":f"non-empty string, at most {MAX_ISSUE_REASONING_CODEPOINTS} Unicode code points; why the cited evidence supports this nature, or exactly what evidence is missing","temporal_basis":{"claim_anchor":"exact claim substring or null","evidence_anchor":"exact cited evidence substring or null","relation":"explicit_overlap|timeless_rule|explicit_later_transition|unknown"},"evidence":[{"chapter_id":"allowed chapter id","span_id":"allowed span id","relation":"supports|contradicts|context","sufficiency":"sufficient|insufficient","related_memory_ids":["known memory id"]}],"evidence_chain":[{"span_id":"one cited evidence span id","role":"prior_state|current_context|missing_link"}],"suggested_revision":{"before":"exact text occurring once in the bound draft","after":"specific replacement text"},"available_actions":["edit|apply_suggestion|keep_intentional|false_positive"],"proposed_memory_change":{"operation":"add|replace","memory_type":"allowed memory type","subject":"string","predicate":"string","value":"string","affected_memory_id":"required for replace only"}}]}


def _memory_schema() -> dict[str, Any]:
    return {"candidates":[{"memory_type":"static_canon|dynamic_state|event_timeline|character_knowledge|open_thread","subject":"string","predicate":"identity|relationship|affiliation|location|status|rule|possession|event_occurred|knowledge","value":"string","chapter_id":"source chapter id","source_span_id":"supplied source span id"}]}


def _memory_delta_schema() -> dict[str, Any]:
    return {"candidates":[{"change_kind":"new_fact|changed_fact|invalidated_fact","affected_memory_id":"null for new_fact; supplied confirmed Memory id for changed_fact or invalidated_fact","memory_type":"allowed memory type","subject":"string, at most 80 characters","predicate":"controlled predicate","value":"new/changed fact value, at most 240 characters; exact current value for invalidated_fact","invalidation_reason":"null for new_fact/changed_fact; non-empty reason for invalidated_fact, at most 240 characters","chapter_id":"source chapter id","source_span_id":"supplied current-revision SourceSpan id"}]}


def _source_chars(sources: list[dict[str, Any]]) -> int:
    return sum(len(str(source.get("body",""))) for source in sources)


def _aggregate(results: list[Any]) -> dict[str, Any]:
    def total(field: str):
        values=[getattr(result,field) for result in results]
        return sum(values) if values and all(value is not None for value in values) else None
    return {"input_tokens":total("input_tokens"),"output_tokens":total("output_tokens"),"latency_ms":total("latency_ms"),"cost_cny":total("cost_cny")}


def _aggregate_attempt_failure(results: list[Any], error: Exception) -> dict[str, Any]:
    metrics=_aggregate(results)
    if getattr(error,"usage_unknown",False):
        return {field:None for field in metrics}
    return metrics


def _invalid_json_aggregate(results: list[Any], error: ProviderInvalidJson) -> dict[str, Any]:
    return {**_aggregate(results+[error]), "finish_reason": error.finish_reason, "cost_available": error.cost_available}


def _claim_terms(text: str) -> set[str]:
    characters="".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]",text))
    return {characters[index:index+2] for index in range(max(0,len(characters)-1))}


def _relevance_score(terms:set[str],text:str)->int:
    return len(terms & _claim_terms(text))


def _memory_sort_key(item:dict[str,Any])->tuple[str,...]:
    return tuple(str(item.get(key,"")) for key in ("subject","predicate","value","source_span_id","id"))


def _bounded_excerpt(body:str,hints:list[str],limit:int=CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS)->str:
    if len(body)<=limit:return body
    phrases=[]
    for hint in hints:
        compact="".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]",hint))
        if len(compact)>=2:phrases.append(compact)
        phrases.extend(sorted(_claim_terms(hint)))
    anchor=next((body.find(phrase) for phrase in sorted(set(phrases),key=lambda value:(-len(value),value)) if body.find(phrase)>=0),0)
    start=max(0,anchor-limit//3); end=min(len(body),start+limit); start=max(0,end-limit)
    return body[start:end]


def _share_batch_excerpts(claims:list[dict[str,Any]])->list[dict[str,Any]]:
    """Give every claim in one batch the same excerpt of a span it shares with other claims.

    The prompt shows each span once per batch. A long span's excerpt is a window anchored on the
    claim's own wording, so claims can need different parts of it; the shared excerpt is the union
    of those windows, never longer than the copies it replaces. Every claim's prompt_excerpt is set
    to that text, so validation and stored evidence see exactly what the model saw.
    """
    seen:dict[str,tuple[dict[str,Any],list[str]]]={}
    for claim in claims:
        for span in claim["allowed_evidence"]:
            seen.setdefault(span["id"],(span,[]))[1].append(str(span.get("prompt_excerpt",span.get("body",""))))
    shared={}
    for span_id,(span,excerpts) in seen.items():
        distinct=list(dict.fromkeys(excerpts)); body=str(span.get("body",""))
        windows=[(body.find(text),body.find(text)+len(text)) for text in distinct]
        if len(distinct)==1 or any(start<0 for start,_ in windows):
            shared[span_id]=distinct[0] if len(distinct)==1 else "…".join(distinct); continue
        merged:list[list[int]]=[]
        for start,end in sorted(windows):
            if merged and start<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],end)
            else:merged.append([start,end])
        shared[span_id]="…".join(body[start:end] for start,end in merged)
    return [{**claim,"allowed_evidence":[{**span,"prompt_excerpt":shared[span["id"]]} for span in claim["allowed_evidence"]]} for claim in claims]


class ContinuityEngine:
    def __init__(self,provider:ProviderPort): self.provider=provider
    @staticmethod
    def pipeline()->str:
        return "legacy" if os.environ.get(REVIEW_PIPELINE_ENV,"").strip().lower()=="legacy" else "screened"
    def provenance(self)->dict[str,str]:
        screened=self.pipeline()=="screened"
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":SCREENED_PROMPT_VERSION if screened else PROMPT_VERSION,"schema_version":"continuity-issue-v7-repair-diagnostics","retrieval_method_version":SCREENED_RETRIEVAL_METHOD_VERSION if screened else RETRIEVAL_METHOD_VERSION}

    def _selected_evidence(self,claim:dict[str,Any],memory:list[dict[str,Any]],excerpt_limit:int=CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS)->list[dict[str,Any]]:
        unique={span["id"]:span for span in claim["allowed_evidence"]}
        by_source:dict[str,list[dict[str,Any]]]={}
        for item in memory:by_source.setdefault(str(item.get("source_span_id","")),[]).append(item)
        terms=_claim_terms(claim["text"]); ranked=[]
        for span in unique.values():
            related=by_source.get(span["id"],[])
            memory_text=" ".join(str(item.get(key,"")) for item in related for key in ("subject","predicate","value"))
            text_score=_relevance_score(terms,str(span.get("body","")))
            score=10*_relevance_score(terms,memory_text)+min(20,text_score)
            ranked.append((score,str(span.get("chapter_id","")),span["id"],span,related,text_score))
        order=lambda row:(-row[0],row[1],row[2])
        direct=sorted((row for row in ranked if row[5]>0),key=lambda row:(-row[5],row[1],row[2]))[:CONTINUITY_DIRECT_TEXT_SLOTS]
        kept={row[2] for row in direct}
        picks=(direct+[row for row in sorted(ranked,key=order) if row[2] not in kept])[:CONTINUITY_EVIDENCE_LIMIT]
        selected=[]
        for _,_,_,span,related,_ in sorted(picks,key=order):
            hints=[claim["text"]]+[str(item.get(key,"")) for item in sorted(related,key=_memory_sort_key) for key in ("subject","value")]
            selected.append({**span,"prompt_excerpt":_bounded_excerpt(str(span.get("body","")),hints,excerpt_limit)})
        return selected

    def _related_memory(self, claim: dict[str, Any], memory: list[dict[str, Any]], limit: int = RELATED_MEMORY_LIMIT) -> list[dict[str, Any]]:
        terms=_claim_terms(claim["text"]); evidence_ids={span.get("source_span_id",span["id"]) for span in claim["allowed_evidence"]}; ranked=[]
        cited=claim.get("screen_facts") or []
        for item in memory:
            text=" ".join(str(item.get(key,"")) for key in ("subject","predicate","value"))
            # Facts the screen tied to this claim come first.
            score=100*int(item["id"] in cited)+10*int(item.get("source_span_id") in evidence_ids)+_relevance_score(terms,text)
            if score:ranked.append((score,item))
        return [item for _,item in sorted(ranked,key=lambda row:(-row[0],_memory_sort_key(row[1])))[:limit]]

    def _request(self, claims: list[dict[str, Any]], data: dict[str, Any],
                 bounds: tuple[int, int] | None = None) -> dict[str, Any]:
        if data.get("pipeline")=="screened":return self._screened_request(claims,data,bounds or SCREENED_SINGLE_CLAIM_FALLBACK_BOUNDS[0])
        memory,draft=data["memory"],data["draft"]
        excerpt_limit,memory_limit=bounds or (CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS, RELATED_MEMORY_LIMIT)
        selected_claims=_share_batch_excerpts([{**claim,"allowed_evidence":self._selected_evidence(claim,memory,excerpt_limit)} for claim in claims])
        used={item["id"]:item for claim in selected_claims for item in self._related_memory(claim,memory,memory_limit)}
        return {"draft":{"id":draft["id"],"revision":draft["revision"],"body":"\n".join(claim["text"] for claim in selected_claims)},"claims":selected_claims,"memory":[used[key] for key in sorted(used)],"output_schema":_continuity_schema()}

    def _screened_request(self, claims: list[dict[str, Any]], data: dict[str, Any], bounds: tuple[int, int]) -> dict[str, Any]:
        """Flagged claims of one context with their passages; the context itself is the draft text shown."""
        passage_limit,memory_limit=bounds
        before=min(screening.before_chapter(claim) for claim in claims)
        chapters=data["memory_chapters"]
        # Facts from the checked chapter or later never reach the review.
        memory=[item for item in data["memory"] if chapters.get(item["id"],0)<before]
        selected=[{**claim,"allowed_evidence":claim["allowed_evidence"][:passage_limit]} for claim in claims]
        used={item["id"]:item for claim in selected for item in self._related_memory(claim,memory,memory_limit)}
        full=data["contexts"][claims[0]["context"]]
        body=screening.context_window(full,[claim["text"] for claim in claims])
        return {"pipeline":"screened",**({"review_mode":"quick"} if data.get("review_mode")=="quick" else {}),"draft":{"id":data["draft"]["id"],"revision":data["draft"]["revision"],"body":body},"claims":selected,
                "memory":[{**used[key],"chapter_number":chapters.get(key)} for key in sorted(used,key=lambda key:_memory_sort_key(used[key]))],"output_schema":_continuity_schema(),"full_draft_body":full}

    def _fits(self,request:dict[str,Any])->bool:
        return request_prompt_and_budget(request)[1] <= input_budget_units_for(request)

    def _single_claim_batch(self,claim:dict[str,Any],data:dict[str,Any])->dict[str,Any]:
        """One claim alone, with tighter excerpts and fewer Memory rows only when the full bounds do not fit."""
        for bounds in (SCREENED_SINGLE_CLAIM_FALLBACK_BOUNDS if data.get("pipeline")=="screened" else SINGLE_CLAIM_FALLBACK_BOUNDS):
            request=self._request([claim],data,bounds)
            if self._fits(request):return request
        raise InputBudgetExceeded()

    def _batches(self,data:dict[str,Any])->list[dict[str,Any]]:
        batches=[]; current=[]
        for claim in data["claims"]:
            # A screened batch shows one context, so claims of different chapters never share one.
            if current and current[-1].get("context")!=claim.get("context"):
                batches.append(self._request(current,data)); current=[]
            candidate=current+[claim]; request=self._request(candidate,data)
            if len(candidate)<=(data.get("max_claims_per_batch") or CONTINUITY_MAX_CLAIMS_PER_BATCH) and self._fits(request):
                current=candidate; continue
            if current:
                batches.append(self._request(current,data)); current=[claim]
                if self._fits(self._request(current,data)):continue
            batches.append(self._single_claim_batch(claim,data)); current=[]
        if current:batches.append(self._request(current,data))
        return batches

    def _repair_diagnostics(self,payload:Any,data:dict[str,Any])->list[dict[str,Any]]:
        """Collect all independently detectable semantic contract failures for one repair call."""
        diagnostics=[]
        if getattr(self.provider,"continuity_contract_version",None)=="v6":
            try:self._v6_issues(payload,data)
            except ContinuityContractValidationError as error:diagnostics.extend(error.diagnostics)
        if not isinstance(payload,dict) or not isinstance(payload.get("issues"),list):return diagnostics
        claims={item["id"]:item for item in data["claims"]};mem={item["id"]:item for item in data["memory"]}
        for raw in payload["issues"]:
            if not isinstance(raw,dict) or not isinstance(raw.get("claim_span_id"),str) or raw["claim_span_id"] not in claims:continue
            review_keys={"nature","reasoning","temporal_basis","evidence_chain","suggested_revision","available_actions"}
            if not review_keys<=set(raw):continue
            reasoning=raw.get("reasoning")
            if isinstance(reasoning,str) and len(reasoning.strip())>MAX_ISSUE_REASONING_CODEPOINTS:
                diagnostics.append(_reasoning_length_diagnostic(data,raw["claim_span_id"],reasoning))
            claim=claims[raw["claim_span_id"]];allowed={item["id"]:item for item in claim["allowed_evidence"]};codes=[]
            raw_evidence=raw.get("evidence") if isinstance(raw.get("evidence"),list) else []
            if _requires_cjk(data["draft"]["body"]):
                author_texts=[raw.get("explanation"),raw.get("reasoning")]
                if any(not isinstance(text,str) or not _contains_cjk(text) for text in author_texts):codes.append("author_language_mismatch")
            bound_evidence=[]
            for item in raw_evidence:
                if isinstance(item,dict) and isinstance(item.get("span_id"),str) and item["span_id"] in allowed:
                    span=allowed[item["span_id"]]
                    bound_evidence.append({**item,"excerpt":span.get("prompt_excerpt",span["body"]),"source_span_id":span.get("source_span_id",span["id"]),
                                           "related_memory_ids":item.get("related_memory_ids") if isinstance(item.get("related_memory_ids"),list) else []})
            temporal_failure=_confirmed_temporal_failure(raw,claim["text"],bound_evidence,mem)
            # Missing/unresolvable evidence is a binding failure, not a proved time mismatch. The screened
            # pipeline settles an unproved time or rule locally (see validate), never by a repair.
            if temporal_failure and bound_evidence and data.get("pipeline")!="screened":codes.append(temporal_failure)
            if codes:
                evidence_excerpts=[]
                for evidence in raw_evidence:
                    if isinstance(evidence,dict) and isinstance(evidence.get("span_id"),str) and evidence["span_id"] in allowed:
                        span=allowed[evidence["span_id"]]
                        evidence_excerpts.append({"span_id":span["id"],"excerpt":span.get("prompt_excerpt",span["body"])})
                diagnostics.append({"claim_span_id":claim["id"],"claim_text":claim["text"],"problem_codes":list(dict.fromkeys(codes)),"cited_evidence":evidence_excerpts})
        return diagnostics

    def execute(self,data:dict[str,Any])->dict[str,Any]:
        # Every dispatch of this review run, including repairs, shares one stepped-down thinking effort.
        with review_effort_scope():
            return self._execute_screened(data) if data.get("pipeline")=="screened" else self._execute(data)

    def _execute_screened(self,data:dict[str,Any])->dict[str,Any]:
        """Screen the claims, then review only the flagged ones against passages of earlier chapters."""
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        claims=data["claims"]; index=screening.build_index(data["sources"],data["memory"])
        chapters=screening.memory_chapters(data["sources"],data["memory"])
        summary={"claims":len(claims),"screened":len(claims)>screening.SCREEN_MIN_CLAIMS,"parts":0,"fallback_parts":0,"flagged":0,"reviewed":0}
        screen_results:list[Any]=[]
        if summary["screened"]:
            flags=self._screen(claims,index,data["memory"],chapters,screen_results,summary)
            if "error" in flags:return self._failure(flags["error"],screen_results)
            added=screening.attribute_contacts([claim for claim in claims if claim["id"] not in flags],data["memory"],chapters)
            flags.update({claim_id:{"kind":"check","facts":[]} for claim_id in added})
            summary["safety_net"]=len(added)
        else:
            # A short draft is reviewed whole, every sentence with thinking.
            flags={claim["id"]:{"kind":"unscreened","facts":[]} for claim in claims}
        summary["flagged"]=len(flags)
        evidence={claim["id"]:screening.claim_evidence(claim,index,flags[claim["id"]]["facts"]) for claim in claims if claim["id"] in flags}
        # A flagged sentence with no earlier passage at all has nothing to be reviewed against.
        reviewed=[{**claim,"allowed_evidence":evidence[claim["id"]],"screen_facts":flags[claim["id"]]["facts"]} for claim in claims if evidence.get(claim["id"])]
        summary["reviewed"]=len(reviewed)
        base={**data,"memory_chapters":chapters}
        quick=[claim for claim in reviewed if flags[claim["id"]]["kind"]=="check"]
        results=list(screen_results); escalated:set[str]=set()
        summary.update(quick_reviewed=len(quick),escalated=0,deep_reviewed=0)
        if quick:
            # What the quick review reports, or cannot decide, gets a thinking review; the rest is settled.
            outcome=self._execute({**base,"claims":quick,"review_mode":"quick","max_claims_per_batch":screening.QUICK_MAX_CLAIMS,"settled_by_screen":True},prior_results=results,keep_results=True)
            if outcome["status"]!="completed":return {key:value for key,value in outcome.items() if key!="_results"}
            results=outcome["_results"]
            escalated={issue["claim_span_id"] for issue in outcome["issues"]}|{row["claim_span_id"] for row in outcome["undecided_claims"]}
            summary["escalated"]=len(escalated)
        deep=[claim for claim in reviewed if flags[claim["id"]]["kind"]!="check" or claim["id"] in escalated]
        summary["deep_reviewed"]=len(deep)
        # A short draft keeps the per-sentence batching (and the quota preflight's arithmetic) of before.
        limit=screening.DEEP_MAX_CLAIMS if summary["screened"] else CONTINUITY_MAX_CLAIMS_PER_BATCH
        result=self._execute({**base,"claims":deep,"max_claims_per_batch":limit,"settled_by_screen":summary["screened"]},prior_results=results)
        paths={claim["id"]:("escalated" if claim["id"] in escalated else "deep") for claim in deep}
        paths.update({claim["id"]:"quick" for claim in quick if claim["id"] not in escalated})
        result={**result,"retrieval_traces":screening.retrieval_traces(claims,{claim["id"]:claim["allowed_evidence"] for claim in reviewed},flags,summary["screened"],paths),
                "retrieval_method_version":SCREENED_RETRIEVAL_METHOD_VERSION,"screening":summary}
        return result

    def _screen(self,claims:list[dict[str,Any]],index:Any,memory:list[dict[str,Any]],chapters:dict[str,int],
                results:list[Any],summary:dict[str,Any])->dict[str,Any]:
        """Flagged claim id -> {kind, facts}; {"error": exception} when a dispatch fails.

        A screen answer the validator rejects is retried once as a repair. A part that still fails is
        reviewed whole: costlier, never a silent miss.
        """
        flags:dict[str,Any]={}
        for part in screening.screen_parts(claims):
            summary["parts"]+=1
            request,sentence_ids,fact_ids=screening.screen_request(part,index,memory,chapters)
            parsed=None
            try:
                for attempt in range(2):
                    sent=request if attempt==0 else {**request,"screen_repair":{"reason_code":code}}
                    try:
                        result=self.provider.evaluate(sent)
                    except ProviderInvalidJson as error:
                        results.append(error); code="screen_invalid_json"; continue
                    results.append(result)
                    try:
                        parsed=screening.parse_screen(result.payload,sentence_ids,fact_ids); break
                    except screening.ScreenContractError as error:
                        code=str(error)
            except (ProviderDispatchDenied,InputBudgetExceeded,ProviderUnavailable,ProviderTimeout,ProviderFailure) as error:
                return {"error":error}
            if parsed is None:
                summary["fallback_parts"]+=1
                parsed={claim["id"]:{"kind":"check","facts":[]} for claim in part}
            flags.update(parsed)
        return flags

    def _failure(self,error:Exception,results:list[Any])->dict[str,Any]:
        """The terminal result of a run stopped by `error`, keeping the usage already spent."""
        if isinstance(error,ProviderDispatchDenied):return {"status":"failed","error_code":str(error),"retryable":True,**_aggregate_attempt_failure(results,error)}
        if isinstance(error,InputBudgetExceeded):return {"status":"failed","error_code":"input_budget_exceeded","retryable":True,**_aggregate(results)}
        if isinstance(error,ProviderUnavailable):return {"status":"failed","error_code":"provider_unavailable","retryable":True,**_aggregate(results)}
        if isinstance(error,ProviderTimeout):return {"status":"timed_out","error_code":"provider_timeout","retryable":True,**_aggregate_attempt_failure(results,error)}
        if isinstance(error,ProviderInvalidJson):
            # A length stop cut the answer off; name it instead of calling it a JSON contract failure.
            code="output_truncated" if error.finish_reason=="length" else "invalid_json"
            return {"status":"failed","error_code":code,"retryable":True,**_invalid_json_aggregate(results,error)}
        if isinstance(error,ProviderFailure):return {"status":"failed","error_code":"provider_error","retryable":True,**_aggregate_attempt_failure(results,error)}
        return {"status":"failed","error_code":str(error),"retryable":True,**_aggregate_attempt_failure(results,error)}

    def _execute(self,data:dict[str,Any],prior_results:list[Any]|None=None,keep_results:bool=False)->dict[str,Any]:
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        prior_results=list(prior_results or [])
        try:batches=self._batches(data)
        except InputBudgetExceeded:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True,**(_aggregate(prior_results) if prior_results else {})}
        retrieval_traces=[{"claim_id":claim["id"],"returned_span_ids":[span["id"] for span in claim["allowed_evidence"]]} for batch in batches for claim in batch["claims"]]
        # A thinking-review provider declares its own larger budget; everything else keeps MAX_RUN_TOKENS.
        run_budget=getattr(self.provider,"continuity_run_token_budget",None) or MAX_RUN_TOKENS
        if data.get("pipeline")=="screened":run_budget=max(run_budget,screening.SCREENED_RUN_TOKEN_BUDGET)
        # Batches are independent, so a provider that declares a concurrency above one gets that many
        # in flight; the rest keep the old sequential order. An 816-character chapter is 36 claims
        # and ran its batches one after another for four minutes.
        concurrency=getattr(self.provider,"continuity_batch_concurrency",None)
        concurrency=concurrency if isinstance(concurrency,int) and not isinstance(concurrency,bool) and concurrency>1 else 1
        order={claim["id"]:index for index,claim in enumerate(data["claims"])}
        pending=list(batches); outcomes=[]; stop=None; exhausted=False
        pool=ThreadPoolExecutor(max_workers=concurrency,thread_name_prefix="continuity-batch") if concurrency>1 else None
        def submit(batch:dict[str,Any])->Future:
            if pool is None:
                future=Future(); future.set_result(self._review_batch(batch,data,run_budget)); return future
            # Each dispatch carries the caller's context: the usage reservation, the dispatch guard
            # and the run's shared thinking-effort state all live in context variables.
            return pool.submit(contextvars.copy_context().run,self._review_batch,batch,data,run_budget)
        try:
            running=set()
            while running or (pending and stop is None and not exhausted):
                while pending and stop is None and not exhausted and len(running)<concurrency:running.add(submit(pending.pop(0)))
                done,running=wait(running,return_when=FIRST_COMPLETED)
                for future in done:
                    outcome=future.result(); outcomes.append(outcome)
                    if outcome.get("quota_exhausted"):
                        # The author's provider quota ran out mid-chapter. Keep every finished batch and
                        # stop dispatching; what was never judged is reported as undecided, not discarded.
                        exhausted=True
                    elif outcome.get("error") is not None or outcome.get("budget_paused"):
                        # Stop dispatching, but let what is already in flight finish: its tokens are spent
                        # either way and belong in the run's totals.
                        stop=stop or outcome
                    elif outcome.get("split"):
                        # Split, so one claim's self-contradicting answer or oversized repair cannot cost the others.
                        pending[:0]=[self._request(group,data) for group in outcome["split"]]
        finally:
            if pool is not None:pool.shutdown(wait=True)
        if exhausted and stop is None:
            outcomes.extend({"first_claim_id":batch["claims"][0]["id"],"results":[],"undecided":[{"claim_span_id":claim["id"],"error_code":PROVIDER_ATTEMPT_QUOTA_EXCEEDED} for claim in batch["claims"]]} for batch in pending)
        results=prior_results+[result for outcome in outcomes for result in outcome["results"]]
        if stop is not None:
            if stop.get("budget_paused"):return {"status":"budget_paused","error_code":"budget_paused","retryable":True,**_aggregate(results)}
            return self._failure(stop["error"],results)
        # Completion order varies with concurrency; everything reported follows claim order instead.
        outcomes.sort(key=lambda outcome:order[outcome["first_claim_id"]])
        issues=[issue for outcome in outcomes for issue in outcome.get("issues",[])]
        contract_normalizations=[item for outcome in outcomes for item in outcome.get("normalizations",[])]
        undecided=sorted((row for outcome in outcomes for row in outcome.get("undecided",[])),key=lambda row:order[row["claim_span_id"]])
        totals=_aggregate(results)
        if any(outcome.get("usage_unknown") for outcome in outcomes):totals={field:None for field in totals}
        if len({issue["claim_span_id"] for issue in issues}) != len(issues): return {"status":"failed","error_code":"schema_invalid","retryable":True,**totals}
        # Nothing survived, so there is no partial result worth showing: keep the old failure.
        # After a screen most sentences are already settled, so undecided ones are reported, never the run's failure.
        if undecided and len(undecided)==len(data["claims"]) and not data.get("settled_by_screen"): return {"status":"failed","error_code":undecided[0]["error_code"],"retryable":True,**totals}
        return {"status":"completed","issues":sorted(issues,key=lambda item:order[item["claim_span_id"]]),"retrieval_traces":retrieval_traces,"retrieval_method_version":RETRIEVAL_METHOD_VERSION,"contract_normalization_count":len(contract_normalizations),"contract_normalizations":contract_normalizations,"undecided_claim_count":len(undecided),"undecided_claims":undecided,**totals,**({"_results":results} if keep_results else {})}

    def _review_batch(self,batch:dict[str,Any],data:dict[str,Any],run_budget:int)->dict[str,Any]:
        """One batch through its first answer and at most one contract repair.

        A batch that fails its contract twice used to raise, discarding every other batch's finished
        work. On a real chapter that is 36 claims lost to one of them, so a multi-claim batch comes
        back as a split, to be retried one claim at a time (or in halves when only its repair request
        is too large), and a single claim that still fails is set aside as undecided. A provider
        failure is returned, not raised, so the usage already spent on this batch still reaches the
        run's totals.
        """
        results=[]; normalizations=[]
        outcome={"first_claim_id":batch["claims"][0]["id"],"results":results,"normalizations":normalizations}
        try:
            for contract_attempt in range(2):
                request=batch if contract_attempt==0 else {**batch,"contract_repair":{"attempt":contract_attempt+1,"reason_code":repair_code,"diagnostics":repair_diagnostics,"rejected_issues":rejected_issues,"rejected_claim_verdicts":rejected_claim_verdicts}}
                # Check the complete feedback as sent; never truncate rejected output to fit.
                input_limit=input_budget_units_for(request,getattr(self.provider,"continuity_repair_input_budget_units",None))
                if request_prompt_and_budget(request)[1]>input_limit:
                    if not contract_attempt:raise InputBudgetExceeded()
                    # A repair carries every rejected issue: a packed 21-claim batch is about 7,200 units
                    # before any and roughly 190 more per issue, so past about ten it cannot fit even the
                    # 9,000 thinking allowance. That used to fail the whole run. Halve the batch instead,
                    # so each half's own repair is smaller; a lone claim that still cannot fit is undecided.
                    claims=batch["claims"]
                    if len(claims)>1:return {**outcome,"split":[claims[:len(claims)//2],claims[len(claims)//2:]]}
                    return {**outcome,"undecided":[{"claim_span_id":claims[0]["id"],"error_code":"input_budget_exceeded"}]}
                result=self.provider.evaluate(request)
                results.append(result)
                if (result.input_tokens or 0)+(result.output_tokens or 0)>run_budget:return {**outcome,"budget_paused":True}
                rejected_issues=result.payload.get("issues",[]) if isinstance(result.payload,dict) else []
                rejected_claim_verdicts=result.payload.get("claim_verdicts",[]) if isinstance(result.payload,dict) else []
                repair_diagnostics=self._repair_diagnostics(result.payload,batch)
                if contract_attempt==0 and repair_diagnostics:
                    repair_code=repair_diagnostics[0]["problem_codes"][0]
                    continue
                try:
                    validated=self.validate(result.payload,batch,allow_conservative_temporal_normalization=contract_attempt==1,normalization_sink=normalizations)
                except ValueError as error:
                    # In the screened pipeline every contract failure is repairable and, failing that,
                    # costs only its own claims; the legacy pipeline keeps failing the run on a plain one.
                    if not isinstance(error,ContinuityContractValidationError) and batch.get("pipeline")!="screened":raise
                    if contract_attempt==0:
                        repair_code=str(error)
                        claim_id=batch["claims"][0]["id"] if len(batch["claims"])==1 else None
                        repair_diagnostics=getattr(error,"diagnostics",None) or [_contract_diagnostic(batch,repair_code,claim_id)]
                        continue
                    if len(batch["claims"])>1:return {**outcome,"split":[[claim] for claim in batch["claims"]]}
                    return {**outcome,"undecided":[{"claim_span_id":batch["claims"][0]["id"],"error_code":str(error)}]}
                if batch.get("pipeline")=="screened":validated=screening.bind_passage_evidence(validated,batch["claims"])
                return {**outcome,"issues":validated}
        except ProviderDispatchDenied as error:
            if str(error)!=PROVIDER_ATTEMPT_QUOTA_EXCEEDED:return {**outcome,"error":error}
            # A refusal after a timed-out dispatch leaves that dispatch's billing unknown.
            return {**outcome,"quota_exhausted":True,"usage_unknown":bool(getattr(error,"usage_unknown",False)),"undecided":[{"claim_span_id":claim["id"],"error_code":PROVIDER_ATTEMPT_QUOTA_EXCEEDED} for claim in batch["claims"]]}
        except ProviderInvalidJson as error:
            if error.finish_reason!="length":return {**outcome,"error":error}
            # Every effort ran out of output, down to the non-thinking answer and its 2,000 tokens. On a
            # multi-claim batch that last answer is what overflows: four verdicts plus one reported gap
            # (explanation, reasoning, evidence chain) do not fit. Retry the claims one at a time; the run
            # has already stepped down, so those answers are short. A lone claim that still overflows is
            # undecided rather than the whole check's failure. Its spent usage stays in the totals.
            results.append(error)
            claims=batch["claims"]
            if len(claims)>1:return {**outcome,"split":[[claim] for claim in claims]}
            return {**outcome,"undecided":[{"claim_span_id":claims[0]["id"],"error_code":"output_truncated"}]}
        except (InputBudgetExceeded,ProviderUnavailable,ProviderTimeout,ProviderFailure,ValueError) as error:
            return {**outcome,"error":error}
        raise AssertionError("unreachable: the second contract attempt always returns")

    def _v6_issues(self,payload:Any,data:dict[str,Any])->dict[str,Any]:
        """Validate the compatible V6 ledger shape, retaining every detectable fault."""
        if not isinstance(payload,dict) or set(payload)!={"issues","claim_verdicts"} or not isinstance(payload.get("issues"),list) or not isinstance(payload.get("claim_verdicts"),list):
            code="claim_verdicts_required"
            raise ContinuityContractValidationError(code,diagnostics=[_contract_diagnostic(data,code,invalid_field="claim_verdicts",requirement="Return exactly issues and claim_verdicts arrays.")])
        claim_ids={item["id"] for item in data["claims"]}
        verdicts={};diagnostics=[]
        def fault(code,claim_id=None,**details):
            diagnostics.append(_contract_diagnostic(data,code,claim_id,**details))
        for index,item in enumerate(payload["claim_verdicts"]):
            if not isinstance(item,dict):
                fault("claim_verdicts_invalid",invalid_field="claim_verdicts",row_index=index,problem="row_type")
                continue
            claim_id=item.get("claim_span_id")
            if not isinstance(claim_id,str) or claim_id not in claim_ids:
                fault("claim_verdicts_invalid",invalid_field="claim_span_id",row_index=index,problem="unknown_claim")
                continue
            if claim_id in verdicts:
                fault("claim_verdicts_invalid",claim_id,invalid_field="claim_span_id",row_index=index,problem="duplicate_claim")
                continue
            verdicts[claim_id]=item.get("verdict")
            if set(item)!={"claim_span_id","verdict","basis"}:
                fault("claim_verdicts_invalid",claim_id,invalid_field="claim_verdicts",row_index=index,problem="row_fields",required_fields=["claim_span_id","verdict","basis"])
            verdict=item.get("verdict")
            if not isinstance(verdict,str) or verdict not in {"reviewed_issue","insufficient_evidence","no_issue"}:
                fault("claim_verdicts_invalid",claim_id,invalid_field="verdict",row_index=index,problem="invalid_enum",allowed_values=["reviewed_issue","insufficient_evidence","no_issue"])
            basis=item.get("basis")
            if not isinstance(basis,str) or not basis.strip() or len(basis)>MAX_CLAIM_BASIS_CODEPOINTS:
                fault("claim_verdicts_invalid",claim_id,invalid_field="basis",row_index=index,
                      problem="invalid_type" if not isinstance(basis,str) else "blank" if not basis.strip() else "too_long",
                      observed_length=len(basis) if isinstance(basis,str) else None,limit=MAX_CLAIM_BASIS_CODEPOINTS)
        for claim_id in sorted(claim_ids-set(verdicts)):
            fault("claim_verdicts_incomplete",claim_id,invalid_field="claim_verdicts",problem="missing_claim")
        issue_status={}
        for index,item in enumerate(payload["issues"]):
            claim_id=item.get("claim_span_id") if isinstance(item,dict) else None
            if not isinstance(claim_id,str) or claim_id not in claim_ids or claim_id in issue_status:
                fault("claim_verdicts_issue_mismatch",claim_id if isinstance(claim_id,str) else None,invalid_field="issues",row_index=index,problem="invalid_or_duplicate_claim")
                continue
            issue_status[claim_id]=item.get("status")
        for claim_id,verdict in verdicts.items():
            if not isinstance(verdict,str) or verdict not in {"reviewed_issue","insufficient_evidence","no_issue"}:
                continue
            expected=("insufficient_evidence" if issue_status.get(claim_id)=="insufficient_evidence" else
                      "reviewed_issue" if claim_id in issue_status else "no_issue")
            if verdict!=expected:
                fault("claim_verdicts_issue_mismatch",claim_id,invalid_field="verdict",actual_verdict=verdict,
                      expected_verdict_for_returned_issues=expected,issue_present=claim_id in issue_status,
                      required_issue_status_for_verdict="insufficient_evidence" if verdict=="insufficient_evidence" else "conflict" if verdict=="reviewed_issue" else None,
                      requirement="Keep the evidence-based decision. An insufficient_evidence decision needs a cited missing_link Issue with no actions. Change a verdict only when the original evidence justifies that change.")
        if diagnostics:
            raise ContinuityContractValidationError(diagnostics[0]["problem_codes"][0],diagnostics=diagnostics)
        return {"issues":payload["issues"]}

    def validate(self,payload:Any,data:dict[str,Any],allow_conservative_temporal_normalization:bool=False,normalization_sink:list[dict[str,Any]]|None=None):
        if getattr(self.provider,"continuity_contract_version",None)=="v6":
            payload=self._v6_issues(payload,data)
        if not isinstance(payload,dict) or set(payload)!={"issues"} or not isinstance(payload.get("issues"),list):raise ValueError("schema_invalid")
        claims={x["id"]:x for x in data["claims"]}; mem={x["id"]:x for x in data["memory"]}; output=[]
        for raw in payload["issues"]:
            if not isinstance(raw,dict):raise ValueError("schema_invalid")
            if raw.get("status")=="no_conflict":raise ValueError("no_conflict_issue_forbidden")
            explanation=raw.get("explanation") if isinstance(raw,dict) else None
            if not isinstance(raw.get("claim_span_id"),str) or raw["claim_span_id"] not in claims or raw.get("status") not in ALLOWED_STATUS or raw.get("category") not in ALLOWED_CATEGORY or raw.get("severity") not in ALLOWED_SEVERITY or not isinstance(explanation,str) or not explanation.strip():raise ValueError("schema_invalid")
            review_keys={"nature","reasoning","temporal_basis","evidence_chain","suggested_revision","available_actions"}
            present=review_keys & set(raw)
            if not present and not getattr(self.provider,"allows_legacy_continuity_contract",False):raise ContinuityContractValidationError("trustworthy_review_required")
            if present==review_keys-{"temporal_basis"}:raise ContinuityContractValidationError("temporal_basis_missing")
            if present and present!=review_keys:raise ValueError("schema_invalid")
            trustworthy=present==review_keys
            evs=raw.get("evidence",[]); allowed={x["id"]:x for x in claims[raw["claim_span_id"]]["allowed_evidence"]}
            if raw["status"]=="conflict" and not evs:raise ValueError("conflict_without_evidence")
            if raw["status"]=="insufficient_evidence" and evs and not trustworthy:raise ValueError("insufficient_evidence_upgraded")
            if raw["status"]=="insufficient_evidence" and raw.get("proposed_memory_change") is not None:raise ValueError("insufficient_evidence_memory_change")
            cleaned=[]
            for ev in evs:
                if not isinstance(ev,dict) or not isinstance(ev.get("span_id"),str) or ev["span_id"] not in allowed:raise ValueError("evidence_unresolvable")
                s=allowed[ev["span_id"]]
                related_ids=ev.get("related_memory_ids")
                if (ev.get("chapter_id")!=s["chapter_id"] or ev.get("relation") not in {"supports","contradicts","context"} or
                    ev.get("sufficiency") not in {"sufficient","insufficient"} or not isinstance(related_ids,list) or
                    any(not isinstance(memory_id,str) or memory_id not in mem for memory_id in related_ids)):
                    raise ValueError("evidence_unresolvable")
                if raw["status"]=="conflict" and not trustworthy and (ev.get("relation")!="contradicts" or ev.get("sufficiency")!="sufficient"):raise ValueError("conflict_evidence_not_direct")
                if raw["status"]=="insufficient_evidence" and ev.get("sufficiency")!="insufficient":
                    # A reviewed insufficient_evidence issue that marks a citation sufficient is a
                    # self-contradicting answer (V10 diagnostic rerun, 1 in 5): allow the bounded repair.
                    code="insufficient_evidence_upgraded"
                    if not trustworthy:raise ValueError(code)
                    raise ContinuityContractValidationError(code,diagnostics=[_contract_diagnostic(data,code,raw["claim_span_id"],invalid_field="evidence.sufficiency",
                        requirement="An insufficient_evidence issue cites only context marked sufficiency insufficient; otherwise reclassify the issue.")])
                cleaned.append({"chapter_id":s["chapter_id"],"span_id":s["id"],"excerpt":s.get("prompt_excerpt",s["body"]),"relation":ev["relation"],"sufficiency":ev["sufficiency"],"related_memory_ids":ev.get("related_memory_ids",[]),
                                **({"source_span_id":s["source_span_id"]} if "source_span_id" in s else {})})
            change=raw.get("proposed_memory_change")
            if change is not None:
                required={"memory_type","subject","predicate","value","operation"}
                if (not isinstance(change,dict) or not required<=set(change) or change["memory_type"] not in ALLOWED_MEMORY_TYPE or change["operation"] not in {"add","replace"} or any(not isinstance(change[key],str) or not change[key].strip() for key in ("subject","predicate","value")) or (change["operation"]=="add" and change.get("affected_memory_id") is not None) or (change["operation"]=="replace" and change.get("affected_memory_id") not in mem) or raw["status"]!="conflict"):raise ValueError("schema_invalid")
            review={"review_contract_version":"legacy_v3","nature":None,"reasoning":None,"evidence_chain":None,"suggested_revision":None,"available_actions":None}
            if trustworthy:
                nature=raw.get("nature");reasoning=raw.get("reasoning");temporal=raw.get("temporal_basis");chain=raw.get("evidence_chain");suggestion=raw.get("suggested_revision");actions=raw.get("available_actions")
                if nature not in REVIEW_NATURES or not isinstance(reasoning,str) or not reasoning.strip():raise ValueError("schema_invalid")
                if len(reasoning.strip())>MAX_ISSUE_REASONING_CODEPOINTS:
                    raise ContinuityContractValidationError("reasoning_too_long",diagnostics=[_reasoning_length_diagnostic(data,raw["claim_span_id"],reasoning)])
                if not isinstance(temporal,dict) or set(temporal)!={"claim_anchor","evidence_anchor","relation"} or temporal.get("relation") not in {"explicit_overlap","timeless_rule","explicit_later_transition","unknown"}:raise ValueError("schema_invalid")
                claim_text=claims[raw["claim_span_id"]]["text"]
                claim_anchor=temporal.get("claim_anchor");evidence_anchor=temporal.get("evidence_anchor")
                if claim_anchor is not None and (not isinstance(claim_anchor,str) or not claim_anchor.strip() or claim_anchor not in claim_text):raise ContinuityContractValidationError("temporal_anchor_unresolvable")
                if evidence_anchor is not None and (not isinstance(evidence_anchor,str) or not evidence_anchor.strip() or not any(evidence_anchor in item["excerpt"] for item in cleaned)):raise ContinuityContractValidationError("temporal_anchor_unresolvable")
                if _requires_cjk(data["draft"]["body"]):
                    author_texts=[explanation,reasoning]
                    if any(not _contains_cjk(text) for text in author_texts):raise ContinuityContractValidationError("author_language_mismatch")
                if raw["status"]=="insufficient_evidence" and nature!="insufficient_evidence":raise ValueError("schema_invalid")
                if raw["status"]=="conflict" and nature=="insufficient_evidence":raise ValueError("schema_invalid")
                if nature=="confirmed_conflict" and (not any(ev["relation"]=="contradicts" and ev["sufficiency"]=="sufficient" for ev in cleaned) or any(ev["relation"]=="supports" or ev["sufficiency"]!="sufficient" for ev in cleaned)):
                    raise ContinuityContractValidationError("conflict_evidence_not_direct")
                temporal_failure=_confirmed_temporal_failure(raw,claim_text,cleaned,mem)
                if temporal_failure and data.get("pipeline")=="screened":
                    # A contradiction whose shared time or governing rule is not proved is, by the review
                    # rules themselves, a possible_conflict. Settled here instead of by a repair that thinks
                    # the whole batch through again (lf1 dev set: 12k-29k reasoning tokens per such repair).
                    if normalization_sink is not None:normalization_sink.append({"claim_span_id":raw["claim_span_id"],"reason_code":temporal_failure,"outcome":"possible_conflict","provider_attempt":2 if allow_conservative_temporal_normalization else 1})
                    nature="possible_conflict"; temporal_failure=None
                if temporal_failure and not allow_conservative_temporal_normalization:
                    raise ContinuityContractValidationError(temporal_failure)
                if nature in {"possible_conflict","state_change"} and any(ev["sufficiency"]!="sufficient" for ev in cleaned):
                    # v22 tells the model to settle an undecidable tension as possible_conflict, and an unsure
                    # model then marks its own citation insufficient. That self-contradiction is repairable
                    # (imported-project diagnostic, 3 of 4 runs failed the whole check on it).
                    code="conflict_evidence_insufficient"
                    raise ContinuityContractValidationError(code,diagnostics=[_contract_diagnostic(data,code,raw["claim_span_id"],invalid_field="evidence.sufficiency",
                        requirement="A possible_conflict or state_change issue cites only spans sufficient for their stated role; mark them sufficient, or reclassify the issue as insufficient_evidence.")])
                if nature=="insufficient_evidence" and (not cleaned or any(ev["sufficiency"]!="insufficient" for ev in cleaned)):raise ValueError("evidence_unresolvable")
                if not isinstance(chain,list) or len(chain)!=len(cleaned) or any(not isinstance(item,dict) or set(item)!={"span_id","role"} or item.get("role") not in EVIDENCE_CHAIN_ROLES for item in chain):raise ValueError("evidence_unresolvable")
                chain_spans=[item["span_id"] for item in chain]
                if len(chain_spans)!=len(set(chain_spans)) or set(chain_spans)!={item["span_id"] for item in cleaned}:raise ValueError("evidence_unresolvable")
                if nature=="insufficient_evidence" and any(item["role"]!="missing_link" for item in chain):raise ValueError("evidence_unresolvable")
                if not isinstance(actions,list) or len(actions)!=len(set(actions)) or not set(actions)<=REVIEW_ACTIONS:raise ValueError("schema_invalid")
                if nature=="insufficient_evidence" and actions:raise ValueError("schema_invalid")
                if suggestion is not None:
                    if not isinstance(suggestion,dict) or set(suggestion)!={"before","after"} or any(not isinstance(suggestion.get(field),str) or not suggestion[field].strip() for field in ("before","after")) or suggestion["before"]==suggestion["after"]:raise ValueError("schema_invalid")
                    if data.get("full_draft_body",data["draft"]["body"]).count(suggestion["before"])!=1 or "apply_suggestion" not in actions:raise ValueError("suggested_revision_unresolvable")
                elif "apply_suggestion" in actions:raise ValueError("suggested_revision_unresolvable")
                if temporal_failure and allow_conservative_temporal_normalization:
                    chinese=_requires_cjk(data["draft"]["body"])
                    safe_explanation=("现有材料不足以证明当前主张与引用事实在同一故事时间和范围内相互矛盾，暂不能判定为确定冲突。" if chinese else "The supplied material does not establish that the current claim and cited fact conflict in the same story time and scope, so a confirmed conflict cannot be established.")
                    safe_reasoning=("需要补充明确的时间锚点、适用范围或连接事件，才能判断两项陈述是否不能同时成立。" if chinese else "An explicit time anchor, applicable scope, or connecting event is required before deciding that the two statements cannot coexist.")
                    insufficient=[{**item,"relation":"context","sufficiency":"insufficient"} for item in cleaned]
                    if normalization_sink is not None:normalization_sink.append({"claim_span_id":raw["claim_span_id"],"reason_code":temporal_failure,"outcome":"insufficient_evidence","provider_attempt":2})
                    output.append({"claim_span_id":raw["claim_span_id"],"status":"insufficient_evidence","category":raw["category"],"severity":"medium","evidence_status":"insufficient","explanation":safe_explanation,"evidence":insufficient,"proposed_memory_change":None,"review_contract_version":"trustworthy_review_v1","nature":"insufficient_evidence","reasoning":safe_reasoning,"evidence_chain":[{"span_id":item["span_id"],"role":"missing_link"} for item in insufficient],"suggested_revision":None,"available_actions":[]})
                    continue
                if nature=="confirmed_conflict" and temporal["relation"]=="timeless_rule" and suggestion is not None:
                    suggestion=None;actions=[action for action in actions if action!="apply_suggestion"]
                review={"review_contract_version":"trustworthy_review_v1","nature":nature,"reasoning":reasoning.strip(),"evidence_chain":chain,"suggested_revision":suggestion,"available_actions":actions}
            output.append({"claim_span_id":raw["claim_span_id"],"status":raw["status"],"category":raw["category"],"severity":raw["severity"],"evidence_status":"sufficient" if cleaned and all(item["sufficiency"]=="sufficient" for item in cleaned) else "insufficient","explanation":explanation.strip()[:500],"evidence":cleaned,"proposed_memory_change":change,**review})
        return output


class WritingAnalysisEngine:
    """Strict, bounded analysis over one immutable database-prepared input."""
    def __init__(self,provider:ProviderPort):self.provider=provider

    def provenance(self,analysis_type:str)->dict[str,str]:
        prompt_version=CONTEXT_BRIEF_PROMPT_VERSION if analysis_type=="context_brief" else PLAN_ALIGNMENT_PROMPT_VERSION if analysis_type=="plan_alignment" else CHANGE_IMPACT_PROMPT_VERSION if analysis_type=="change_impact" else STORY_QA_PROMPT_VERSION if analysis_type=="story_qa" else FORESHADOW_SCAN_PROMPT_VERSION if analysis_type=="foreshadow_scan" else AUTHOR_MATERIAL_COMPARISON_PROMPT_VERSION if analysis_type=="author_material_comparison" else REVISION_PLAN_PROMPT_VERSION
        schema_version="writing-analysis-v2-foreshadow-evidence-kind" if analysis_type=="foreshadow_scan" else "writing-analysis-v1"
        retrieval_version=CONTEXT_BRIEF_RETRIEVAL_METHOD_VERSION if analysis_type=="context_brief" else ANALYSIS_RETRIEVAL_METHOD_VERSION
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":prompt_version,"schema_version":schema_version,"retrieval_method_version":retrieval_version}

    @staticmethod
    def _schema(task:str)->dict[str,Any]:
        if task=="author_material_comparison":
            return {"assessment":"aligned|possible_tension|insufficient_evidence; plan_deviation only when comparison.material.nature is plan","explanation":"1-600 chars","evidence":[{"source_type":"author_material|source_span","source_id":"supplied id"}]}
        if task=="context_brief":
            return {"summary":"1-400 chars","summary_sources":[{"source_type":"author_context|memory_record|source_span|draft_claim","source_id":"supplied id"}],"items":[{"section":"related_plan|confirmed_fact|character_state|world_rule|open_thread|recent_source","text":"1-600 chars","sources":[{"source_type":"author_context|memory_record|source_span|draft_claim","source_id":"supplied id"}]}]}
        if task=="change_impact":
            return {"summary":"1-400 chars","items":[{"area":"chapter|character|world|memory|plan","target_id":"supplied target id","impact":"1-600 chars; analysis only, never replacement prose","evidence":[{"source_type":"author_context|memory_record|source_span|draft_claim|character_record|character_alias|world_record","source_id":"supplied id"}]}]}
        if task=="story_qa":
            return {"answer_status":"answered|partial|insufficient|conflicting","answer":"1-800 chars","findings":[{"layer":"confirmed|written|planned","stance":"supports|contradicts|context","text":"1-600 chars","evidence":[{"source_type":"memory_record|source_span|draft_claim|author_context","source_id":"supplied id"}]}]}
        if task=="foreshadow_scan":
            return {"summary":"1-400 chars","candidates":[{"title":"1-120 chars","description":"1-1200 chars","suggested_status":"planted|developing|resolved","evidence":[{"source_type":"source_span|draft_claim","source_id":"supplied id","relation":"planted|developing|resolved","evidence_kind":"current_clue|specific_prior_unresolved_clue|background_only|explicit_payoff"}]}]}
        if task=="revision_plan":
            return {"summary":"1-400 chars","candidates":[{"issue_id":"one supplied selected issue id","title":"1-120 chars","instruction":"1-1200 chars; an editing action, never replacement prose","priority":"high|medium|low","evidence":[{"source_type":"issue_evidence","source_id":"evidence id supplied for that issue"}]}]}
        return {"summary":"1-400 chars","items":[{"story_plan_id":"supplied story plan id","status":"planned_covered|planned_missing|planned_early|planned_changed|insufficient_evidence","explanation":"1-600 chars","evidence":[{"source_type":"draft_claim|source_span","source_id":"supplied id"}]}]}

    def _request(self,data:dict[str,Any])->dict[str,Any]:
        return {**data,"output_schema":self._schema(data["task"])}

    @staticmethod
    def _text(value:Any,limit:int)->str:
        if not isinstance(value,str) or not value.strip() or len(value.strip())>limit:raise ValueError("schema_invalid")
        # Model prose is author-facing: drop record ids it copied from the evidence keys.
        cleaned=strip_internal_ids(value.strip())
        if not cleaned:raise ValueError("schema_invalid")
        return cleaned

    @staticmethod
    def _source_maps(data:dict[str,Any])->dict[str,dict[str,dict[str,Any]]]:
        planned=data["layers"]["planned"]
        author={}
        for group_name,group in planned.items():
            route="outline" if group_name=="story_plans" else "characters" if group_name=="character_plans" else "world"
            for item in group:author[item["id"]]={**item,"_source_route":route}
        memory={item["id"]:item for item in data["layers"]["confirmed"]["memory_records"]}
        written=data["layers"]["written"]
        identity=data["layers"].get("identity",{});reference=data["layers"].get("reference",{})
        issue_evidence={item["id"]:item for issue in data.get("selected_issues",[]) for item in issue.get("evidence",[])}
        return {"author_context":author,"author_material":author,"memory_record":memory,"source_span":{item["id"]:item for item in written["source_spans"]},"draft_claim":{item["id"]:item for item in written["draft_claims"]},"character_record":{item["id"]:item for item in identity.get("characters",[])},"character_alias":{item["id"]:item for item in identity.get("aliases",[])},"world_record":{item["id"]:item for item in reference.get("world_entries",[])},"issue_evidence":issue_evidence}

    @classmethod
    def _clean_source(cls,raw:Any,maps:dict[str,dict[str,dict[str,Any]]],allowed:set[str],project_id:str)->dict[str,Any]:
        if not isinstance(raw,dict) or set(raw)!={"source_type","source_id"} or raw.get("source_type") not in allowed:raise ValueError("evidence_unresolvable")
        source_type=raw["source_type"];source_id=raw.get("source_id")
        if not isinstance(source_id,str) or source_id not in maps[source_type]:raise ValueError("evidence_unresolvable")
        item=maps[source_type][source_id]
        if source_type in {"author_context","author_material"}:label=item.get("title") or item.get("name") or "作者规划";excerpt=item.get("content") or item.get("summary") or item.get("goal") or item.get("planned_state") or item.get("description") or ""
        elif source_type=="memory_record":label=f"{item['subject']} · {predicate_label(item['predicate'])}";excerpt=item["value"]
        elif source_type=="draft_claim":label=f"当前草稿 · 句 {item['ordinal']}";excerpt=item["text"]
        elif source_type=="character_record":label=item["name"];excerpt=" · ".join(filter(None,(item.get("identity"),item.get("current_state"),item.get("knowledge_boundary"))))
        elif source_type=="character_alias":label=f"{item['primary_name']} · 别名";excerpt=item["alias"]
        elif source_type=="world_record":label=item["name"];excerpt=item["summary"]
        elif source_type=="issue_evidence":label=f"第 {item['chapter_number']} 章 · {item['chapter_title']}";excerpt=item["excerpt"]
        else:label=f"第 {item['chapter_number']} 章 · {item['label']}";excerpt=item["body"]
        if source_type in {"author_context","author_material"}:source_path=f"/projects/{project_id}/{item['_source_route']}#plan-{source_id}"
        elif source_type=="memory_record":source_path=f"/projects/{project_id}/memory#memory-{source_id}"
        elif source_type=="draft_claim":source_path=f"/projects/{project_id}/workspace#draft-source"
        elif source_type=="character_record":source_path=f"/projects/{project_id}/characters?character={source_id}#character-{source_id}"
        elif source_type=="character_alias":source_path=f"/projects/{project_id}/characters?character={item['character_id']}#alias-{source_id}"
        elif source_type=="world_record":source_path=f"/projects/{project_id}/world?world={source_id}#world-{source_id}"
        elif source_type=="issue_evidence":source_path=item["source_path"]
        else:source_path=f"/projects/{project_id}/sources#span-{source_id}"
        return {"source_type":source_type,"source_id":source_id,"label":str(label)[:160],"excerpt":str(excerpt)[:900],"source_path":source_path}

    def validate(self,payload:Any,data:dict[str,Any])->dict[str,Any]:
        maps=self._source_maps(data);task=data["task"];project_id=data["bindings"]["project_id"]
        if task=="author_material_comparison":
            if not isinstance(payload,dict) or set(payload)!={"assessment","explanation","evidence"} or payload.get("assessment") not in {"aligned","possible_tension","plan_deviation","insufficient_evidence"} or not isinstance(payload.get("evidence"),list):raise ValueError("schema_invalid")
            material=data["comparison"]["material"]
            # The prompt states that a contradicted setting is possible_tension; Flash still labels it
            # plan_deviation about one time in three, so apply the stated rule instead of failing.
            assessment="possible_tension" if payload["assessment"]=="plan_deviation" and material["nature"]!="plan" else payload["assessment"]
            if assessment=="insufficient_evidence":
                if len(payload["evidence"])>2:raise ValueError("evidence_unresolvable")
            elif len(payload["evidence"])!=2:raise ValueError("evidence_unresolvable")
            evidence=[self._clean_source(item,maps,{"author_material","source_span"},project_id) for item in payload["evidence"]]
            if assessment!="insufficient_evidence" and {(item["source_type"],item["source_id"]) for item in evidence}!={("author_material",material["id"]),("source_span",data["comparison"]["passage"]["id"])}:raise ValueError("evidence_unresolvable")
            return {"assessment":assessment,"explanation":self._text(payload["explanation"],600),"evidence":evidence,"comparison_id":data["bindings"]["comparison_id"],"decision_revision":data["bindings"]["decision_revision"]}
        if task=="context_brief":
            if not isinstance(payload,dict) or set(payload)!={"summary","summary_sources","items"} or not isinstance(payload["summary_sources"],list) or not isinstance(payload["items"],list) or not 1<=len(payload["summary_sources"])<=3 or not 1<=len(payload["items"])<=12:raise ValueError("schema_invalid")
            summary_sources=[self._clean_source(item,maps,{"author_context","memory_record","source_span","draft_claim"},project_id) for item in payload["summary_sources"]]
            rendered_items=[]
            draft_claims=data["layers"]["written"]["draft_claims"]
            discarded_citation_mismatches=[]
            citation_added=0;citation_omitted=0
            def clean_brief_source(ref:dict[str,str])->dict[str,Any]:
                return self._clean_source(ref,maps,{"author_context","memory_record","source_span","draft_claim"},project_id)
            for index,raw in enumerate(payload["items"]):
                if not isinstance(raw,dict) or set(raw)!={"section","text","sources"} or raw.get("section") not in CONTEXT_BRIEF_SECTIONS or not isinstance(raw.get("sources"),list) or not 1<=len(raw["sources"])<=4:raise ValueError("schema_invalid")
                sources=[clean_brief_source(item) for item in raw["sources"]]
                item_text=self._text(raw["text"],600)
                located,added,omitted=brief_citations.locate_sources(item_text,sources,maps,clean_brief_source)
                citation_added+=added;citation_omitted+=omitted
                if not located:
                    discarded_citation_mismatches.append(index)
                    continue
                groups=[located] if len(brief_citations.render_sources(located,maps,100000))<=600 else [[source] for source in located]
                for group in groups:
                    rendered=brief_citations.render_sources(group,maps)
                    rendered_items.append({"section":brief_citations.section_for_sources(group,maps,raw["section"]),
                                  "text":rendered,"sources":group})
            draft_text=str(data["layers"]["written"]["draft"].get("excerpt", ""))
            model_cited_draft={source["source_id"] for item in rendered_items for source in item["sources"] if source["source_type"]=="draft_claim"}
            fallback_draft_ids=[]
            if draft_text.strip():
                for claim in draft_claims:
                    if claim["id"] in model_cited_draft:continue
                    source=clean_brief_source({"source_type":"draft_claim","source_id":claim["id"]})
                    rendered_items.append({"section":"recent_source","text":brief_citations.render_sources([source],maps),"sources":[source]})
                    fallback_draft_ids.append(claim["id"])
            unique_rendered=[]
            for item in rendered_items:
                if item not in unique_rendered:unique_rendered.append(item)
            duplicate_omitted=len(rendered_items)-len(unique_rendered)
            # Reserve a place for every selected saved-draft claim before optional background cards.
            # A multi-source model item may otherwise consume all twelve visible slots.
            items=[]
            for claim in draft_claims:
                candidate=next((item for item in unique_rendered if item not in items and any(
                    source["source_type"]=="draft_claim" and source["source_id"]==claim["id"] for source in item["sources"])),None)
                if candidate is not None:items.append(candidate)
            for item in unique_rendered:
                if len(items)>=12:break
                if item not in items:items.append(item)
            cited_draft={source["source_id"] for item in items for source in item["sources"] if source["source_type"]=="draft_claim"}
            overflow_omitted=max(0,len(unique_rendered)-len(items))
            if not items:
                for kind in ("memory_record","source_span","author_context"):
                    for source_id in list(maps[kind])[:3-len(items)]:
                        source=clean_brief_source({"source_type":kind,"source_id":source_id})
                        items.append({"section":brief_citations.section_for_sources([source],maps,"confirmed_fact"),
                                      "text":brief_citations.render_sources([source],maps),"sources":[source]})
                    if len(items)>=3:break
            retrieval=data.get("retrieval",{})
            truncated=retrieval.get("truncated",{})
            scope=retrieval.get("draft_claim_scope",{})
            selected_scopes=scope.get("selected",[{"id":item["id"],"truncated":False} for item in draft_claims])
            selected_ids={item["id"] for item in selected_scopes}
            draft_reasons=[]
            if discarded_citation_mismatches:draft_reasons.append("draft_item_citation_mismatch")
            if draft_text.strip() and not cited_draft:draft_reasons.append("draft_citation_missing")
            if selected_ids-cited_draft:draft_reasons.append("draft_claim_uncovered")
            if scope.get("available",len(selected_scopes))>len(selected_scopes):draft_reasons.append("draft_claim_unselected")
            if any(item.get("truncated") for item in selected_scopes):draft_reasons.append("draft_claim_truncated")
            if truncated.get("draft_body"):draft_reasons.append("draft_body_truncated")
            if not items:draft_reasons.append("evidence_insufficient")
            deterministic_summary=[];deterministic_sources=[];source_keys=set()
            section_order={name:index for index,name in enumerate(("recent_source","related_plan","confirmed_fact","character_state","world_rule","open_thread"))}
            for item in sorted(items,key=lambda value:section_order[value["section"]]):
                candidate_keys={(source["source_type"],source["source_id"]) for source in item["sources"]}
                if len(source_keys|candidate_keys)>3:continue
                candidate_text=" ".join([*deterministic_summary,item["text"]])
                if len(candidate_text)>400:continue
                deterministic_summary.append(item["text"]);source_keys.update(candidate_keys)
                for source in item["sources"]:
                    key=(source["source_type"],source["source_id"])
                    if key not in {(value["source_type"],value["source_id"]) for value in deterministic_sources}:deterministic_sources.append(source)
            if not deterministic_summary:
                fallback_sources=items[0]["sources"][:3]
                draft_excerpt=str(data["layers"]["written"]["draft"].get("excerpt", ""))
                fallback_summary="已根据所列来源整理当前写作上下文，具体事实与引用见分项。" if _requires_cjk(draft_excerpt) else "Writing context was organized from the listed sources; see item-level citations for factual details."
                deterministic_summary=[fallback_summary];deterministic_sources=fallback_sources
            return {"summary":" ".join(deterministic_summary),"summary_sources":deterministic_sources,"items":items,"evidence_status":"partial" if draft_reasons else "supported","citation_transform":{"version":"source-rendered-v2","model_summary_used":False,"model_item_count":len(payload["items"]),"source_rendered_item_count":len(items),"added_source_count":citation_added,"omitted_unmatched_clause_count":citation_omitted,"discarded_model_item_indices":discarded_citation_mismatches,"fallback_draft_claim_ids":fallback_draft_ids,"duplicate_omitted_item_count":duplicate_omitted,"overflow_omitted_item_count":overflow_omitted},"draft_coverage":{"status":"partial" if draft_reasons else "covered" if draft_text.strip() else "empty","source_ids":sorted(cited_draft),"cited_ranges":[item for item in selected_scopes if item["id"] in cited_draft],"uncovered_source_ids":sorted(selected_ids-cited_draft),"unselected_count":max(0,scope.get("available",len(selected_scopes))-len(selected_scopes)),"discarded_item_indices":discarded_citation_mismatches,"reasons":draft_reasons}}
        if task=="change_impact":
            target_source=data.get("retrieval",{}).get("target_source")
            if target_source and target_source.get("status")!="selected":
                return {"summary":CHANGE_IMPACT_INSUFFICIENT_SUMMARY,"evidence_status":"insufficient","items":[],"proposal":data["proposal"]}
            if not isinstance(payload,dict) or set(payload)!={"summary","items"} or not isinstance(payload["items"],list) or len(payload["items"])>20:raise ValueError("schema_invalid")
            layers=data["layers"]
            targets={"chapter":{item["id"]:f"第 {item['chapter_number']} 章 · {item['title']}" for item in layers["reference"]["chapters"]},"character":{item["id"]:item["name"] for item in layers["identity"]["characters"]},"world":{item["id"]:item["name"] for item in layers["reference"]["world_entries"]},"memory":{item["id"]:f"{item['subject']} · {item['predicate']}" for item in layers["confirmed"]["memory_records"]},"plan":{item["id"]:(item.get("title") or item.get("name") or "创作计划") for group in layers["planned"].values() for item in group}}
            allowed={"author_context","memory_record","source_span","draft_claim","character_record","character_alias","world_record"};items=[];seen=set()
            for raw in payload["items"]:
                if not isinstance(raw,dict) or set(raw)!={"area","target_id","impact","evidence"} or raw.get("area") not in targets or not isinstance(raw.get("target_id"),str) or (raw["area"],raw["target_id"]) in seen or not isinstance(raw.get("evidence"),list) or not 1<=len(raw["evidence"])<=5:raise ValueError("evidence_unresolvable")
                # An item aimed at an unsupplied target (e.g. the current draft's id) is dropped, like a
                # chapter item without evidence from that chapter; the remaining items stand on their own.
                if raw.get("target_id") not in targets[raw["area"]]:continue
                evidence=[self._clean_source(item,maps,allowed,project_id) for item in raw["evidence"]]
                if raw["area"]=="chapter" and not any(item["source_type"]=="source_span" and maps["source_span"][item["source_id"]]["chapter_id"]==raw["target_id"] for item in evidence):continue
                seen.add((raw["area"],raw["target_id"]));items.append({"area":raw["area"],"target_id":raw["target_id"],"label":targets[raw["area"]][raw["target_id"]],"impact":self._text(raw["impact"],600),"evidence":evidence})
            if not items:return {"summary":CHANGE_IMPACT_INSUFFICIENT_SUMMARY,"evidence_status":"insufficient","items":[],"proposal":data["proposal"]}
            return {"summary":self._text(payload["summary"],400),"evidence_status":"supported","items":items,"proposal":data["proposal"]}
        if task=="story_qa":
            if not isinstance(payload,dict) or set(payload)!={"answer_status","answer","findings"} or payload.get("answer_status") not in STORY_QA_STATUSES or not isinstance(payload.get("findings"),list) or len(payload["findings"])>12:raise ValueError("schema_invalid")
            if payload["answer_status"]=="insufficient":
                if payload["findings"]:raise ValueError("evidence_unresolvable")
                return {"summary":STORY_QA_INSUFFICIENT_ANSWER,"items":[],"answer_status":"insufficient","answer":STORY_QA_INSUFFICIENT_ANSWER,"evidence_status":"insufficient","findings":[],"question":data["question"],"scope":data["scope"]}
            if not payload["findings"]:raise ValueError("evidence_unresolvable")
            layer_sources={"confirmed":{"memory_record"},"written":{"source_span","draft_claim"},"planned":{"author_context"}}
            findings=[];stances=set();source_keys=set()
            for raw in payload["findings"]:
                if not isinstance(raw,dict) or set(raw)!={"layer","stance","text","evidence"} or raw.get("layer") not in STORY_QA_LAYERS or raw["layer"] not in data["scope"] or raw.get("stance") not in {"supports","contradicts","context"} or not isinstance(raw.get("evidence"),list) or not 1<=len(raw["evidence"])<=4:raise ValueError("evidence_unresolvable")
                evidence=[self._clean_source(item,maps,layer_sources[raw["layer"]],project_id) for item in raw["evidence"]]
                stances.add(raw["stance"]);source_keys.update((item["source_type"],item["source_id"]) for item in evidence)
                findings.append({"layer":raw["layer"],"stance":raw["stance"],"text":self._text(raw["text"],600),"evidence":evidence})
            if payload["answer_status"]=="conflicting" and (not {"supports","contradicts"}<=stances or len(source_keys)<2):raise ValueError("evidence_unresolvable")
            answer=self._text(payload["answer"],800)
            return {"summary":answer,"items":[],"answer_status":payload["answer_status"],"answer":answer,"evidence_status":"supported","findings":findings,"question":data["question"],"scope":data["scope"]}
        if task=="foreshadow_scan":
            if not isinstance(payload,dict) or set(payload)!={"summary","candidates"} or not isinstance(payload.get("candidates"),list) or len(payload["candidates"])>20:raise ValueError("schema_invalid")
            if not payload["candidates"]:return {"summary":FORESHADOW_INSUFFICIENT_SUMMARY,"items":[],"evidence_status":"insufficient","candidates":[]}
            existing={re.sub(r"\s+","",str(item["title"])).casefold() for item in data["author_records"]["foreshadows"]};seen=set();candidates=[];normalized_background=False
            written=data["layers"]["written"];span_map={item["id"]:item for item in written["source_spans"]}
            for raw in payload["candidates"]:
                if not isinstance(raw,dict) or set(raw)!={"title","description","suggested_status","evidence"} or raw.get("suggested_status") not in {"planted","developing","resolved"} or not isinstance(raw.get("evidence"),list) or not 1<=len(raw["evidence"])<=5:raise ValueError("evidence_unresolvable")
                title=self._text(raw["title"],120);normalized=re.sub(r"\s+","",title).casefold()
                description=self._text(raw["description"],1200)
                if normalized in existing or normalized in seen:raise ValueError("foreshadow_candidate_duplicate")
                seen.add(normalized);evidence=[];planted=None;resolved=None
                for source in raw["evidence"]:
                    if not isinstance(source,dict) or set(source) not in ({"source_type","source_id","relation"},{"source_type","source_id","relation","evidence_kind"}) or source.get("relation") not in {"planted","developing","resolved"}:raise ValueError("evidence_unresolvable")
                    evidence_kind=source.get("evidence_kind")
                    if evidence_kind is not None and evidence_kind not in {"current_clue","specific_prior_unresolved_clue","background_only","explicit_payoff"}:raise ValueError("evidence_unresolvable")
                    cleaned=self._clean_source({"source_type":source.get("source_type"),"source_id":source.get("source_id")},maps,{"source_span","draft_claim"},project_id);cleaned["relation"]=source["relation"]
                    if evidence_kind is not None:cleaned["evidence_kind"]=evidence_kind
                    evidence.append(cleaned)
                    span=span_map.get(source.get("source_id"))
                    locatable=evidence_kind not in {"background_only","current_clue"}
                    if span and locatable and source["relation"] in {"planted","developing"} and planted is None:planted={"chapter_id":span["chapter_id"],"source_span_id":span["id"]}
                    if span and locatable and source["relation"]=="resolved" and resolved is None:resolved={"chapter_id":span["chapter_id"],"source_span_id":span["id"]}
                suggested_status=raw["suggested_status"]
                typed_count=sum("evidence_kind" in source for source in evidence)
                if typed_count not in {0,len(evidence)}:raise ValueError("evidence_unresolvable")
                if typed_count==0 and not getattr(self.provider,"allows_legacy_foreshadow_evidence_contract",False):raise ValueError("evidence_kind_required")
                typed_evidence=typed_count==len(evidence)
                has_specific_prior=any(source["source_type"]=="source_span" and source.get("evidence_kind")=="specific_prior_unresolved_clue" for source in evidence)
                if suggested_status=="developing" and typed_evidence and not has_specific_prior:
                    evidence=[{**source,"relation":"planted"} for source in evidence if source["source_type"]=="draft_claim" and source.get("evidence_kind")=="current_clue"]
                    if not evidence:raise ValueError("evidence_unresolvable")
                    description=("当前草稿中的候选线索：" if _requires_cjk(written["draft"].get("excerpt","")) else "Candidate clue in the current draft: ")+evidence[0]["excerpt"]
                    description=self._text(description[:1200],1200)
                    suggested_status="planted";planted=None;normalized_background=True
                if suggested_status not in {source["relation"] for source in evidence}:raise ValueError("evidence_unresolvable")
                candidates.append({"title":title,"description":description,"suggested_status":suggested_status,"planted_chapter_id":planted["chapter_id"] if planted else None,"planted_source_span_id":planted["source_span_id"] if planted else None,"resolved_chapter_id":resolved["chapter_id"] if resolved else None,"resolved_source_span_id":resolved["source_span_id"] if resolved else None,"evidence":evidence})
            summary=("发现可供作者复核的伏笔候选：" if _requires_cjk(written["draft"].get("excerpt","")) else "Foreshadow candidates for author review: ")+"、".join(item["title"] for item in candidates) if normalized_background else self._text(payload["summary"],400)
            return {"summary":self._text(summary[:400],400),"items":[],"evidence_status":"supported","candidates":candidates}
        if task=="revision_plan":
            selected={item["id"]:item for item in data["selected_issues"]}
            if not isinstance(payload,dict) or set(payload)!={"summary","candidates"} or not isinstance(payload.get("candidates"),list) or len(payload["candidates"])!=len(selected):raise ValueError("revision_plan_candidate_count_invalid")
            candidates=[];seen_issues=set();seen_titles=set()
            for raw in payload["candidates"]:
                if not isinstance(raw,dict) or set(raw)!={"issue_id","title","instruction","priority","evidence"} or raw.get("issue_id") not in selected or raw["issue_id"] in seen_issues or raw.get("priority") not in REVISION_TASK_PRIORITIES or not isinstance(raw.get("evidence"),list) or not 1<=len(raw["evidence"])<=5:raise ValueError("revision_plan_candidate_invalid")
                title=self._text(raw["title"],120);normalized=re.sub(r"\s+","",title).casefold()
                if normalized in seen_titles:raise ValueError("revision_plan_candidate_duplicate")
                issue=selected[raw["issue_id"]];allowed_ids={item["id"] for item in issue["evidence"]}
                evidence=[]
                for source in raw["evidence"]:
                    if not isinstance(source,dict) or set(source)!={"source_type","source_id"} or source.get("source_type")!="issue_evidence" or source.get("source_id") not in allowed_ids:raise ValueError("evidence_unresolvable")
                    evidence.append(self._clean_source(source,maps,{"issue_evidence"},project_id))
                seen_issues.add(raw["issue_id"]);seen_titles.add(normalized);candidates.append({"issue_id":raw["issue_id"],"title":title,"instruction":self._text(raw["instruction"],1200),"priority":raw["priority"],"evidence":evidence})
            if seen_issues!=set(selected):raise ValueError("revision_plan_candidate_count_invalid")
            return {"summary":self._text(payload["summary"],400),"items":[],"evidence_status":"supported","candidates":candidates,"source_run_id":data["source_run_id"],"selected_issue_ids":list(selected)}
        if not isinstance(payload,dict) or set(payload)!={"summary","items"} or not isinstance(payload["items"],list):raise ValueError("schema_invalid")
        plans={item["id"]:item for item in data["layers"]["planned"]["story_plans"]}
        if len(payload["items"])!=len(plans):raise ValueError("schema_invalid")
        seen=set();items=[]
        for raw in payload["items"]:
            if not isinstance(raw,dict) or set(raw)!={"story_plan_id","status","explanation","evidence"} or raw.get("story_plan_id") not in plans or raw["story_plan_id"] in seen or raw.get("status") not in PLAN_ALIGNMENT_STATUSES or not isinstance(raw.get("evidence"),list) or len(raw["evidence"])>5:raise ValueError("schema_invalid")
            evidence=[self._clean_source(item,maps,{"draft_claim","source_span"},project_id) for item in raw["evidence"]]
            if raw["status"] in {"planned_covered","planned_early","planned_changed"} and not evidence:raise ValueError("evidence_unresolvable")
            seen.add(raw["story_plan_id"]);plan=plans[raw["story_plan_id"]]
            items.append({"story_plan_id":raw["story_plan_id"],"story_plan_title":plan["title"],"status":raw["status"],"explanation":self._text(raw["explanation"],600),"plan_source":self._clean_source({"source_type":"author_context","source_id":plan["id"]},maps,{"author_context"},project_id),"evidence":evidence})
        return {"summary":self._text(payload["summary"],400),"items":items}

    def execute(self,data:dict[str,Any])->dict[str,Any]:
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        request=self._request(data)
        response=None
        try:
            if request_prompt_and_budget(request)[1]>MAX_INPUT_BUDGET_UNITS:raise InputBudgetExceeded()
            response=self.provider.evaluate(request)
            if (response.input_tokens or 0)+(response.output_tokens or 0)>MAX_RUN_TOKENS:return {"status":"budget_paused","error_code":"budget_paused","retryable":True,**_aggregate([response])}
            analysis=self.validate(response.payload,data)
            return {"status":"completed","analysis":analysis,**_aggregate([response])}
        except InputBudgetExceeded:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True}
        except ProviderUnavailable:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        except ProviderTimeout:return {"status":"timed_out","error_code":"provider_timeout","retryable":True}
        except ProviderInvalidJson as error:return {"status":"failed","error_code":"invalid_json","retryable":True,**_invalid_json_aggregate([],error)}
        except ProviderFailure:return {"status":"failed","error_code":"provider_error","retryable":True}
        except ValueError as error:return {"status":"failed","error_code":str(error),"retryable":True,**(_aggregate([response]) if response is not None else {})}


class MemoryInitializationEngine:
    """Validates every bounded batch in memory before one atomic persistence operation."""
    def __init__(self, provider: ProviderPort): self.provider=provider
    def provenance(self)->dict[str,str]:
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"provider_api_format":getattr(self.provider,"api_format_label","injected-provider"),"prompt_version":MEMORY_PROMPT_VERSION,"schema_version":"memory-candidate-v1","chunking_method_version":SOURCE_CHUNK_METHOD_VERSION}
    def _request(self,sources:list[dict[str,Any]],source_revision:int)->dict[str,Any]:
        return {"task":"memory_initialization","source_revision":source_revision,"sources":sources,"controlled_predicates":list(CONTROLLED_PREDICATES),"output_schema":_memory_schema()}
    def chunking_method_version(self)->str:
        return SOURCE_CHUNK_METHOD_VERSION
    def _chunk(self,source:dict[str,Any],source_revision:int,ordinal:int,start:int,end:int)->dict[str,Any]:
        return {**source,"chunk_id":f"{source['id']}:r{source_revision}:chunk:{ordinal}","chunk_ordinal":ordinal,"chunk_start":start,"chunk_end":end,"body":source["body"][start:end]}
    def _maximum_chunk_end(self,source:dict[str,Any],source_revision:int,ordinal:int,start:int)->int:
        body=source["body"]; low=start+1; high=len(body); best=None
        while low<=high:
            end=(low+high)//2
            if request_prompt_and_budget(self._request([self._chunk(source,source_revision,ordinal,start,end)],source_revision))[1]<=MEMORY_BATCH_TARGET_BUDGET_UNITS:
                best=end; low=end+1
            else: high=end-1
        if best is None: raise InputBudgetExceeded()
        return best
    def _preferred_end(self,body:str,start:int,maximum:int,previous_end:int|None)->int:
        endings=[start+match.end() for match in re.finditer(r"(?:\r?\n)+|[。！？!?；;]",body[start:maximum])]
        eligible=[end for end in endings if previous_end is None or end>previous_end]
        return eligible[-1] if eligible else maximum
    def _source_chunks(self,source:dict[str,Any],source_revision:int)->list[dict[str,Any]]:
        if request_prompt_and_budget(self._request([source],source_revision))[1]<=MEMORY_BATCH_TARGET_BUDGET_UNITS:return [source]
        chunks=[]; body=source["body"]; start=0; ordinal=1; previous_end=None
        while start<len(body):
            maximum=self._maximum_chunk_end(source,source_revision,ordinal,start)
            end=self._preferred_end(body,start,maximum,previous_end)
            if end<=start or (previous_end is not None and end<=previous_end): raise InputBudgetExceeded()
            chunks.append(self._chunk(source,source_revision,ordinal,start,end))
            if end==len(body): break
            overlap=min(MAX_CHUNK_OVERLAP_CODEPOINTS,end-start-1)
            previous_end=end; start=end-overlap; ordinal+=1
        return chunks
    def chunk_plan(self,data:dict[str,Any])->list[dict[str,Any]]:
        ordered=sorted(data["sources"],key=lambda source:(source["chapter_number"],source["id"]))
        return [chunk for source in ordered for chunk in self._source_chunks(source,data["source_revision"])]
    def _batches(self,data:dict[str,Any])->list[dict[str,Any]]:
        batches=[]; current=[]
        for source in self.chunk_plan(data):
            candidate=current+[source]; request=self._request(candidate,data["source_revision"])
            if request_prompt_and_budget(request)[1] <= MEMORY_BATCH_TARGET_BUDGET_UNITS and (not current or _source_chars(candidate)<=MEMORY_BATCH_TARGET_SOURCE_CHARS):
                current=candidate; continue
            if not current: raise InputBudgetExceeded()
            batches.append(self._request(current,data["source_revision"])); current=[source]
            if request_prompt_and_budget(self._request(current,data["source_revision"]))[1] > MEMORY_BATCH_TARGET_BUDGET_UNITS: raise InputBudgetExceeded()
        if current:batches.append(self._request(current,data["source_revision"]))
        return batches
    def execute(self,data:dict[str,Any])->dict[str,Any]:
        repair_attempts=0
        repair_events=[]
        normalization_counts={"trimmed_string":0,"memory_type_format":0,"extra_fields_removed":0}
        validated_batches=0
        candidates=[]
        def failure(error_code:str,failure_phase:str,failed_batch_ordinal:int|None,total_batches:int,metrics:dict[str,Any]|None=None,**extra:Any)->dict[str,Any]:
            return {"status":"failed","error_code":error_code,"retryable":True,"failure_phase":failure_phase,"failed_batch_ordinal":failed_batch_ordinal,"total_batches":total_batches,"schema_repair_attempts":repair_attempts,"repair_events":repair_events,"validated_batches":validated_batches,"staged_candidate_count":len(candidates),"normalization_count":sum(normalization_counts.values()),"normalization_kinds":{key:value for key,value in normalization_counts.items() if value},**(metrics or {}),**extra}
        if not self.provider.available:return failure("provider_unavailable","provider_preflight",None,0)
        try:batches=self._batches(data)
        except InputBudgetExceeded:return failure("input_budget_exceeded","batch_planning",None,0)
        results=[]
        total_batches=len(batches)
        for batch_ordinal,batch in enumerate(batches,start=1):
            request=batch
            active_repair_event=None
            batch_repair_attempts=0
            while True:
                try:
                    result=self.provider.evaluate(request)
                    if (result.input_tokens or 0)+(result.output_tokens or 0)>MAX_RUN_TOKENS:
                        if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                        return failure("budget_paused","post_response_budget",batch_ordinal,total_batches,_aggregate(results+[result]))
                    results.append(result)
                except InputBudgetExceeded:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("input_budget_exceeded","provider_request",batch_ordinal,total_batches,_aggregate(results))
                except ProviderUnavailable:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("provider_unavailable","provider_request",batch_ordinal,total_batches,_aggregate(results))
                except ProviderTimeout:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("provider_timeout","provider_request",batch_ordinal,total_batches,_aggregate(results))
                except ProviderInvalidJson as error:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("invalid_json","post_response_decode",batch_ordinal,total_batches,_invalid_json_aggregate(results,error))
                except ProviderFailure:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("provider_error","provider_request",batch_ordinal,total_batches,_aggregate(results))
                try:
                    validated,normalizations=self._validate_with_normalization(result.payload,batch)
                except MemoryCandidateValidationError as error:
                    error_code=error.code
                    if active_repair_event is not None:
                        active_repair_event["result"]="failed"
                        active_repair_event["final_reason_code"]=error_code
                        active_repair_event=None
                    if error_code in MEMORY_REPAIRABLE_ERRORS and repair_attempts<MEMORY_SCHEMA_REPAIR_MAX_ATTEMPTS and batch_repair_attempts<MEMORY_SCHEMA_REPAIR_MAX_PER_BATCH:
                        repair_attempts+=1
                        batch_repair_attempts+=1
                        active_repair_event={"batch_ordinal":batch_ordinal,"attempt":repair_attempts,"batch_attempt":batch_repair_attempts,"reason_code":error_code,"result":"pending",**({"field":error.field} if error.field else {}),**({"candidate_ordinal":error.candidate_ordinal} if error.candidate_ordinal else {})}
                        repair_events.append(active_repair_event)
                        request={**batch,"schema_repair":{"reason_code":error_code,"attempt":batch_repair_attempts,"global_attempt":repair_attempts,**({"field":error.field} if error.field else {}),**({"candidate_ordinal":error.candidate_ordinal} if error.candidate_ordinal else {})}}
                        continue
                    return failure(error_code,"post_response_validation",batch_ordinal,total_batches,_aggregate(results),**error.safe_context())
                if active_repair_event is not None:active_repair_event["result"]="succeeded"
                for kind,count in normalizations.items():normalization_counts[kind]+=count
                candidates.extend(validated)
                validated_batches+=1
                break
        deduped=[]; seen=set()
        for item in candidates:
            identity=(item["memory_type"],item["subject"],item["predicate"],item["value"],item["source_span_id"])
            if identity not in seen: seen.add(identity); deduped.append(item)
        if not deduped:return failure("schema_invalid","post_aggregation",None,total_batches,_aggregate(results))
        return {"status":"completed","candidates":deduped,"total_batches":total_batches,"schema_repair_attempts":repair_attempts,"repair_events":repair_events,"validated_batches":validated_batches,"staged_candidate_count":len(candidates),"normalization_count":sum(normalization_counts.values()),"normalization_kinds":{key:value for key,value in normalization_counts.items() if value},**_aggregate(results)}
    def validate(self,payload:Any,data:dict[str,Any])->list[dict[str,Any]]:
        return self._validate_with_normalization(payload,data)[0]
    def _validate_with_normalization(self,payload:Any,data:dict[str,Any])->tuple[list[dict[str,Any]],dict[str,int]]:
        if not isinstance(payload,dict) or set(payload)!={"candidates"}:raise MemoryCandidateValidationError("top_level_shape_invalid")
        if not isinstance(payload["candidates"],list):raise MemoryCandidateValidationError("candidate_collection_invalid")
        if len(payload["candidates"])>MAX_MEMORY_CANDIDATES_PER_BATCH:raise MemoryCandidateValidationError("candidate_count_invalid")
        if not payload["candidates"]:raise MemoryCandidateValidationError("empty_candidates")
        sources={item["id"]:item for item in data["sources"]}; candidates=[]; seen=set()
        normalizations={"trimmed_string":0,"memory_type_format":0,"extra_fields_removed":0}
        required=set(MEMORY_CANDIDATE_FIELDS)
        for candidate_ordinal,item in enumerate(payload["candidates"],start=1):
            if not isinstance(item,dict):raise MemoryCandidateValidationError("candidate_fields_invalid",candidate_ordinal=candidate_ordinal)
            missing=required-set(item)
            if missing:raise MemoryCandidateValidationError("candidate_fields_invalid",field=sorted(missing)[0],candidate_ordinal=candidate_ordinal)
            extra=set(item)-required
            if extra:normalizations["extra_fields_removed"]+=len(extra)
            values={key:item[key] for key in MEMORY_CANDIDATE_FIELDS}
            for field,value in values.items():
                if not isinstance(value,str):raise MemoryCandidateValidationError("required_field_type_invalid",field=field,candidate_ordinal=candidate_ordinal)
                stripped=value.strip()
                if not stripped:raise MemoryCandidateValidationError("required_field_blank",field=field,candidate_ordinal=candidate_ordinal)
                if stripped!=value:normalizations["trimmed_string"]+=1
                values[field]=stripped
            memory_type=values["memory_type"].lower().replace("-","_")
            if memory_type not in ALLOWED_MEMORY_TYPE:raise MemoryCandidateValidationError("memory_type_invalid",field="memory_type",candidate_ordinal=candidate_ordinal)
            if memory_type!=values["memory_type"]:normalizations["memory_type_format"]+=1
            values["memory_type"]=memory_type
            if len(values["subject"])>80:raise MemoryCandidateValidationError("candidate_length_invalid",field="subject",candidate_ordinal=candidate_ordinal)
            if len(values["predicate"])>80:raise MemoryCandidateValidationError("candidate_length_invalid",field="predicate",candidate_ordinal=candidate_ordinal)
            if len(values["value"])>240:raise MemoryCandidateValidationError("candidate_length_invalid",field="value",candidate_ordinal=candidate_ordinal)
            source=sources.get(values["source_span_id"])
            if not source or source["chapter_id"]!=values["chapter_id"]:raise MemoryCandidateValidationError("evidence_unresolvable",field="source_span_id",candidate_ordinal=candidate_ordinal)
            identity=(values["memory_type"],values["subject"],values["predicate"],values["value"],values["source_span_id"])
            if identity in seen:continue
            seen.add(identity); candidates.append(values)
        return candidates,normalizations


class MemoryDeltaEngine(MemoryInitializationEngine):
    """A separate provider contract for one append-only source revision."""
    def provenance(self)->dict[str,str]:
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":"memory-delta-v5-whole-chapter","schema_version":"memory-delta-candidate-v2","retrieval_method_version":RETRIEVAL_METHOD_VERSION}

    def _related_memory(self,data:dict[str,Any])->list[dict[str,Any]]:
        terms=_claim_terms("\n".join(str(source.get("body","")) for source in data["sources"])); ranked=[]
        for item in data["memory"]:
            text=" ".join(str(item.get(key,"")) for key in ("subject","predicate","value"))
            ranked.append((_relevance_score(terms,text),item))
        return [item for _,item in sorted(ranked,key=lambda row:(-row[0],_memory_sort_key(row[1])))[:MEMORY_DELTA_RELATED_MEMORY_LIMIT]]

    def _request(self, data:dict[str,Any])->dict[str,Any]:
        """One request for exactly the given sources; _batches decides which sources go together."""
        sources=list(data["sources"])
        return {"task":"memory_delta","source_revision":data["source_revision"],"sources":sources,"memory":self._related_memory({**data,"sources":sources}),"controlled_predicates":list(CONTROLLED_PREDICATES),"output_schema":_memory_delta_schema()}

    def _fits(self,data:dict[str,Any],sources:list[dict[str,Any]])->bool:
        return request_prompt_and_budget(self._request({**data,"sources":sources}))[1]<=MAX_INPUT_BUDGET_UNITS

    def _source_pieces(self,data:dict[str,Any],source:dict[str,Any])->list[dict[str,Any]]:
        """The whole chapter, split at sentence ends into overlapping pieces only when it does not fit.

        Each piece keeps the original SourceSpan id, so a candidate from any piece cites the chapter.
        """
        body=str(source.get("body",""))
        if self._fits(data,[source]):return [source]
        pieces=[]; start=0; previous_end=None
        while start<len(body):
            low,high,best=start+1,len(body),None
            while low<=high:
                middle=(low+high)//2
                if self._fits(data,[{**source,"body":body[start:middle]}]):best=middle; low=middle+1
                else:high=middle-1
            if best is None:raise InputBudgetExceeded()
            end=self._preferred_end(body,start,best,previous_end)
            if end<=start or (previous_end is not None and end<=previous_end):raise InputBudgetExceeded()
            pieces.append({**source,"body":body[start:end]})
            if end==len(body):break
            overlap=min(MAX_CHUNK_OVERLAP_CODEPOINTS,end-start-1)
            previous_end=end; start=end-overlap
        return pieces

    def _batches(self,data:dict[str,Any])->list[dict[str,Any]]:
        """Every source in chapter order, whole, packed into as few requests as the input budget allows."""
        ordered=sorted(data["sources"],key=lambda source:(int(source.get("chapter_number",0)),str(source.get("id",""))))
        batches=[]; current=[]
        for source in ordered:
            for piece in self._source_pieces(data,source):
                if current and _source_chars(current+[piece])<=MEMORY_BATCH_TARGET_SOURCE_CHARS and self._fits(data,current+[piece]):current.append(piece); continue
                if current:batches.append(self._request({**data,"sources":current}))
                current=[piece]
        if current:batches.append(self._request({**data,"sources":current}))
        return batches

    def validate(self,payload:Any,data:dict[str,Any])->list[dict[str,Any]]:
        if not isinstance(payload,dict) or set(payload)!={"candidates"} or not isinstance(payload["candidates"],list):raise ValueError("schema_invalid")
        if len(payload["candidates"])>MAX_MEMORY_CANDIDATES_PER_BATCH:raise ValueError("candidate_count_invalid")
        sources={item["id"]:item for item in data["sources"]}; memory={item["id"]:item for item in data["memory"]}
        required=set(MEMORY_DELTA_CANDIDATE_FIELDS); candidates=[]; affected_seen=set(); identities=set()
        active_keys={
            (str(item["memory_type"]),str(item["subject"]).strip(),str(item["predicate"]).strip()):item["id"]
            for item in data["memory"]
        }
        for item in payload["candidates"]:
            if not isinstance(item,dict) or set(item)!=required:raise ValueError("candidate_fields_invalid")
            change_kind=item["change_kind"]
            if change_kind not in {"new_fact","changed_fact","invalidated_fact"}:raise ValueError("change_kind_invalid")
            values={}
            for field in ("memory_type","subject","predicate","value","chapter_id","source_span_id"):
                value=item[field]
                if not isinstance(value,str) or not value.strip():raise ValueError("candidate_fields_invalid")
                values[field]=value.strip()
            if values["memory_type"] not in ALLOWED_MEMORY_TYPE:raise ValueError("memory_type_invalid")
            if values["predicate"] not in CONTROLLED_PREDICATES:raise ValueError("predicate_invalid")
            if len(values["subject"])>80 or len(values["predicate"])>80 or len(values["value"])>240:raise ValueError("candidate_length_invalid")
            source=sources.get(values["source_span_id"])
            if not source or source["chapter_id"]!=values["chapter_id"]:raise ValueError("evidence_unresolvable")
            affected=item["affected_memory_id"]
            reason=item["invalidation_reason"]
            if change_kind=="new_fact":
                if affected is not None:raise ValueError("affected_memory_invalid")
                if reason is not None:raise ValueError("invalidation_reason_invalid")
                if (values["memory_type"],values["subject"],values["predicate"]) in active_keys:raise ValueError("candidate_conflict")
            else:
                if not isinstance(affected,str) or not affected.strip() or affected.strip() not in memory:raise ValueError("affected_memory_unresolvable")
                affected=affected.strip()
                if affected in affected_seen:raise ValueError("duplicate_candidate")
                affected_seen.add(affected); before=memory[affected]
                before_fact={field:str(before[field]).strip() for field in ("memory_type","subject","predicate","value")}
                if change_kind=="changed_fact":
                    if reason is not None:raise ValueError("invalidation_reason_invalid")
                    if all(values[field]==before_fact[field] for field in before_fact):raise ValueError("candidate_conflict")
                    target_key=(values["memory_type"],values["subject"],values["predicate"])
                    if target_key in active_keys and active_keys[target_key]!=affected:raise ValueError("candidate_conflict")
                else:
                    if not isinstance(reason,str) or not reason.strip() or len(reason.strip())>240:raise ValueError("invalidation_reason_invalid")
                    reason=reason.strip()
                    if any(values[field]!=before_fact[field] for field in before_fact):raise ValueError("candidate_conflict")
            identity=(change_kind,affected,values["memory_type"],values["subject"],values["predicate"],values["value"],values["source_span_id"])
            if identity in identities:raise ValueError("duplicate_candidate")
            identities.add(identity)
            candidates.append({"change_kind":change_kind,"affected_memory_id":affected,**values,"invalidation_reason":reason})
        return candidates

    def execute(self,data:dict[str,Any])->dict[str,Any]:
        """Read every new source in full, one request per batch, and merge the candidates.

        Before 2026-10 this sent at most 12 spans cut to their first 1,600 characters and kept at most
        4 candidates, so the second half of a long chapter never reached the fact library.
        """
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        try:batches=self._batches(data) or [self._request(data)]
        except InputBudgetExceeded:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True}
        if any(request_prompt_and_budget(batch)[1]>MAX_INPUT_BUDGET_UNITS for batch in batches):return {"status":"failed","error_code":"input_budget_exceeded","retryable":True}
        results=[]; candidates=[]; affected_seen=set(); new_keys=set(); identities=set()
        usage=lambda:(_aggregate(results) if results else {})
        try:
            for batch in batches:
                result=self.provider.evaluate(batch)
                results.append(result)
                if (result.input_tokens or 0)+(result.output_tokens or 0)>MAX_RUN_TOKENS:return {"status":"failed","error_code":"budget_paused","retryable":True,**usage()}
                for item in self.validate(result.payload,{"sources":batch["sources"],"memory":batch["memory"]}):
                    # Overlapping pieces of one chapter can surface the same fact twice; keep the first.
                    if item["affected_memory_id"] is not None:
                        if item["affected_memory_id"] in affected_seen:continue
                        affected_seen.add(item["affected_memory_id"])
                    else:
                        key=(item["memory_type"],item["subject"],item["predicate"])
                        if key in new_keys:continue
                        new_keys.add(key)
                    identity=(item["change_kind"],item["affected_memory_id"],item["memory_type"],item["subject"],item["predicate"],item["value"],item["source_span_id"])
                    if identity in identities:continue
                    identities.add(identity); candidates.append(item)
        except ProviderUnavailable:return {"status":"failed","error_code":"provider_unavailable","retryable":True,**usage()}
        except ProviderTimeout:return {"status":"timed_out","error_code":"provider_timeout","retryable":True,**usage()}
        except ProviderInvalidJson as error:return {"status":"failed","error_code":"invalid_json","retryable":True,**_invalid_json_aggregate(results,error)}
        except ProviderFailure:return {"status":"failed","error_code":"provider_error","retryable":True,**usage()}
        except ValueError as error:return {"status":"failed","error_code":str(error),"retryable":True,**usage()}
        source_ids=list(dict.fromkeys(item["id"] for batch in batches for item in batch["sources"]))
        memory_ids=list(dict.fromkeys(item["id"] for batch in batches for item in batch["memory"]))
        retrieval={"method_version":RETRIEVAL_METHOD_VERSION,"selected_source_span_ids":source_ids,"selected_memory_ids":memory_ids,"batches":len(batches),"counts":{"source_spans":{"available":len(data["sources"]),"selected":len(source_ids)},"confirmed_memory":{"available":len(data["memory"]),"selected":len(memory_ids)}},"truncated":{"source_spans":len(source_ids)<len(data["sources"]),"confirmed_memory":len(memory_ids)<len(data["memory"])}}
        return {"status":"completed","candidates":candidates,"retrieved_memory_count":len(memory_ids),"retrieval_method_version":RETRIEVAL_METHOD_VERSION,"retrieval":retrieval,**_aggregate(results)}
