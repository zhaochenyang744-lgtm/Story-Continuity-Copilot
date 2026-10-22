from __future__ import annotations

import contextvars
import os
import re
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from .internal_ids import strip_internal_ids
from .memory_contract import CONTROLLED_PREDICATES, normalized_predicate, predicate_label
from .provider import MAX_CLAIM_BASIS_CODEPOINTS, MAX_ISSUE_REASONING_CODEPOINTS
from .provider import ProviderDispatchDenied
from .provider import CONTINUITY_PROMPT_VERSION, InputBudgetExceeded, MAX_INPUT_BUDGET_UNITS, MAX_MEMORY_CANDIDATES_PER_BATCH, MEMORY_BATCH_TARGET_BUDGET_UNITS, ProviderFailure, ProviderInvalidJson, ProviderPort, ProviderTimeout, ProviderUnavailable, WRITING_ANALYSIS_INPUT_BUDGET_UNITS, request_prompt_and_budget, review_effort_scope
from .provider import CONTINUITY_SCREENED_PROMPT_VERSION, CONTINUITY_SCREEN_PROMPT_VERSION, CONTINUITY_TRIAGE_PROMPT_VERSION, input_budget_units_for
from . import review_screening as screening
from .review_screening import SCREENED_RETRIEVAL_METHOD_VERSION

ALLOWED_STATUS={"conflict","insufficient_evidence"}
ALLOWED_CATEGORY={"attribute","location_action","timeline","character_knowledge","object_state","relationship","world_rule","event_status"}
ALLOWED_SEVERITY={"low","medium","high"}
ALLOWED_MEMORY_TYPE={"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"}
REVIEW_NATURES={"confirmed_conflict","possible_conflict","state_change","insufficient_evidence"}
REVIEW_ACTIONS={"edit","apply_suggestion","keep_intentional","false_positive"}
EVIDENCE_CHAIN_ROLES={"prior_state","current_context","missing_link"}
# Citation faults that, once the one repair is spent, still leave a decided conflict as a possible one
# (ContinuityEngine._keep_as_possible) instead of an undecided claim.
KEEPABLE_CONTRACT_ERRORS=frozenset({"conflict_evidence_not_direct","temporal_anchor_unresolvable","evidence_unresolvable"})
MAX_RUN_TOKENS=8000
MAX_WRITING_ANALYSIS_RUN_TOKENS=16000
PROMPT_VERSION=CONTINUITY_PROMPT_VERSION
# The screened pipeline (review_screening.py) is the default. CONTINUITY_REVIEW_PIPELINE=legacy is the
# temporary rollback to per-sentence review; a run keeps the pipeline recorded when it was created.
REVIEW_PIPELINE_ENV="CONTINUITY_REVIEW_PIPELINE"
SCREENED_PROMPT_VERSION=f"{CONTINUITY_SCREENED_PROMPT_VERSION}+{CONTINUITY_SCREEN_PROMPT_VERSION}+{CONTINUITY_TRIAGE_PROMPT_VERSION}"
MEMORY_PROMPT_VERSION="memory-initialization-v11-epithet-subjects"
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
NON_CONTRACT_UNDECIDED=frozenset({PROVIDER_ATTEMPT_QUOTA_EXCEEDED,"input_budget_exceeded","invalid_json","output_truncated"})
# A single claim whose full evidence and Memory do not fit the input budget (the v21 rules left the
# long-form worst case at 6,324 of 6,000 units) is sent with these tighter bounds instead of failing.
SINGLE_CLAIM_FALLBACK_BOUNDS=((CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS,RELATED_MEMORY_LIMIT),(400,12),(300,10),(200,8))
# The screened equivalent: fewer passages, then fewer Memory rows.
# A screened review sees passages of the source text itself, so it carries fewer Memory rows.
SCREENED_RELATED_MEMORY_LIMIT=10
# Passages added to one claim beyond its own: the sources of its reserved state facts.
SOURCE_PASSAGES_PER_CLAIM=2
SCREENED_SINGLE_CLAIM_FALLBACK_BOUNDS=((screening.VERIFY_MAX_PASSAGES,SCREENED_RELATED_MEMORY_LIMIT),(4,8),(2,6),(1,5))
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
PLAN_ALIGNMENT_PROMPT_VERSION="plan-alignment-v4-clause-citations"
CHANGE_IMPACT_PROMPT_VERSION="change-impact-v3-supplied-targets"
FORESHADOW_SCAN_PROMPT_VERSION="foreshadow-scan-v7-clause-citations"
CHANGE_IMPACT_INSUFFICIENT_SUMMARY="当前证据不足以支持影响结论。"
FORESHADOW_INSUFFICIENT_SUMMARY="当前未发现有可采信已写证据的伏笔候选。"
PLAN_ALIGNMENT_STATUSES={"planned_covered","planned_missing","planned_early","planned_changed","insufficient_evidence"}
# Predicates (and Memory types) that record where a person stands at a point in the story. The review
# keeps the latest of each for every person a sentence names (ContinuityEngine._latest_states).
STATE_PREDICATES=frozenset({"knowledge","status","possession","location","relationship","affiliation"})
STATE_MEMORY_TYPES=frozenset({"dynamic_state","character_knowledge"})


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


# 初六 stands alone; 十二, 廿三 and 卅 count as days only right after a month word (霜月十二), so 十二个 or 十二点 do not.
_TRADITIONAL_DAY = r"(?:(?<![一二三四五六七八九十廿卅])(初[一二三四五六七八九十])|(?<=[月季])(十[一二三四五六七八九]|廿[一二三四五六七八九]?|卅))(?![一二三四五六七八九十]|[年月日号章天点时分秒个岁人次])"
_TRADITIONAL_HOUR = r"([子丑寅卯辰巳午未申酉戌亥])(?:时|正|初(?![一二三四五六七八九十]))"
_TRADITIONAL_WATCH = r"([一二三四五])更(?!加|多|是|新|改|换)"
# One character before 月 or 季 (霜月, 芦季, 腊月), never the word before it: "在四月初九" is 四月 (lf4-formal a-i07, where
# "在四月" against "四月" made the same day look different). Numbered months (四月, 十一月) are left to the 年月日 parse.
_NAMED_MONTH = r"(?<![一二三四五六七八九十])([^\W\d一二三四五六七八九十][月季])(?=初[一二三四五六七八九十]|十[一二三四五六七八九]|廿|卅)"


def _traditional_calendar(value: str) -> dict[str, set[str]]:
    """Day and hour words of an invented or traditional calendar: 霜月初六, 廿三, 午时, 三更 (lf3-formal a-i08)."""
    days = {"初" + "一二三四五六七八九十"[i]: str(i + 1) for i in range(10)}
    days.update({"十" + "一二三四五六七八九"[i]: str(i + 11) for i in range(9)})
    days.update({"廿": "20", "卅": "30"})
    days.update({"廿" + "一二三四五六七八九"[i]: str(i + 21) for i in range(9)})
    parsed: dict[str, set[str]] = {}
    for match in re.finditer(_TRADITIONAL_DAY, value):
        parsed.setdefault("日", set()).add(days[match.group(1) or match.group(2)])
    for match in re.finditer(_TRADITIONAL_HOUR, value):
        parsed.setdefault("shichen", set()).add(match.group(1))
    for match in re.finditer(_TRADITIONAL_WATCH, value):
        parsed.setdefault("watch", set()).add(match.group(1))
    for match in re.finditer(_NAMED_MONTH, value):
        parsed.setdefault("month_name", set()).add(match.group(1))
    return parsed


def _temporal_anchor_is_explicit(value: str) -> bool:
    clocks = _clock_values(value)
    if clocks is None:
        return False
    if clocks or _english_calendar(value) or _traditional_calendar(value):
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
        for unit,values in _traditional_calendar(value).items():
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


def _aggregate_or_unknown(spent: list[Any], failed: dict[str, Any]) -> dict[str, Any]:
    """Usage of a check whose stage failed: everything spent, unknown if the failed stage's usage was."""
    totals = _aggregate(spent)
    if failed.get("_results") and any(failed.get(field) is None for field in ("input_tokens", "output_tokens")):
        return {field: None for field in totals}
    return totals


def _invalid_json_aggregate(results: list[Any], error: ProviderInvalidJson) -> dict[str, Any]:
    return {**_aggregate(results+[error]), "finish_reason": error.finish_reason, "cost_available": error.cost_available}


def _claim_terms(text: str) -> set[str]:
    characters="".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]",text))
    return {characters[index:index+2] for index in range(max(0,len(characters)-1))}


def _relevance_score(terms:set[str],text:str)->int:
    return len(terms & _claim_terms(text))


def _memory_sort_key(item:dict[str,Any])->tuple[str,...]:
    return tuple(str(item.get(key,"")) for key in ("subject","predicate","value","source_span_id","id"))


def _resolve_id(value:Any,known:Any)->tuple[str|None,bool]:
    """(the known id `value` stands for, whether it had to be corrected).

    An id the model copied wrongly by exactly one character still names the one known id of the same
    length that differs from it in that single place. Zero or several such ids correct nothing.
    """
    if not isinstance(value,str):return None,False
    if value in known:return value,False
    near=[item for item in known if isinstance(item,str) and len(item)==len(value) and sum(a!=b for a,b in zip(item,value))==1]
    return (near[0],True) if len(near)==1 else (None,False)


def _normalization(raw:dict[str,Any],reason_code:str,outcome:str,attempt:int)->dict[str,Any]:
    return {"claim_span_id":raw["claim_span_id"],"reason_code":reason_code,"outcome":outcome,"provider_attempt":attempt}


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

    def _related_memory(self, claim: dict[str, Any], memory: list[dict[str, Any]], limit: int = RELATED_MEMORY_LIMIT,
                        chapters: dict[str, int] | None = None, aliases: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        reserved,rest=self._related_parts(claim,memory,limit,chapters,aliases)
        return reserved+rest

    def _related_parts(self, claim: dict[str, Any], memory: list[dict[str, Any]], limit: int,
                       chapters: dict[str, int] | None, aliases: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The facts a claim is reviewed against: scored by relevance, plus (screened review) each named person's latest states.

        Scoring prefers facts whose source is among the claim's passages, and a person's older states
        can fill every slot with them, so the newest one never arrives (a sentence saying someone still
        cannot read, against the later fact that they now can). With `chapters` (a Memory id -> chapter
        number map) up to half the slots go first to the named people's state facts (see `_reserved_states`).
        """
        terms=_claim_terms(claim["text"]); evidence_ids={span.get("source_span_id",span["id"]) for span in claim["allowed_evidence"]}; ranked=[]
        cited=claim.get("screen_facts") or []
        for item in memory:
            text=" ".join(str(item.get(key,"")) for key in ("subject","predicate","value"))
            # Facts the screen tied to this claim come first.
            score=100*int(item["id"] in cited)+10*int(item.get("source_span_id") in evidence_ids)+_relevance_score(terms,text)
            if score:ranked.append((score,item))
        scores={item["id"]:score for score,item in ranked}
        latest=self._latest_states(claim,memory,chapters,aliases) if chapters is not None else []
        # Ranked by the words shared with the claim only: the passage-source bonus in `scores` favours the older states.
        # Names do not count: a person's name is in every fact about them, and a place the claim names made a
        # later fact about an unrelated route mark tie with the fact that she can now read (first A1c fix-02).
        names={str(item.get("subject","")).strip() for item in memory}|set(self._person_of(aliases))
        plain={term for term in terms if not any(term in name for name in names if len(name)>=2)}
        reserved=self._reserved_states(latest,plain,chapters,aliases,limit//2) if latest else []
        taken={item["id"] for item in reserved}
        rest=[item for _,item in sorted(ranked,key=lambda row:(-row[0],_memory_sort_key(row[1]))) if item["id"] not in taken]
        return reserved,rest[:limit-len(reserved)]

    @staticmethod
    def _person_of(aliases:list[dict[str,Any]]|None)->dict[str,str]:
        person_of:dict[str,str]={}
        for row in aliases or []:
            primary=str(row.get("primary_name","")).strip()
            for name in (primary,str(row.get("alias","")).strip()):
                if name and primary:person_of.setdefault(name,primary)
        return person_of

    @staticmethod
    def _latest_states(claim:dict[str,Any],memory:list[dict[str,Any]],chapters:dict[str,int],aliases:list[dict[str,Any]]|None)->list[dict[str,Any]]:
        """Every state fact, before the claim's chapter, about a person the claim names (by name or a known alias).

        All of them, not only the latest of each predicate: a person has many knowledge facts, and the
        latest one is often about something else (a1cf-f1-fix-02: the fact that she now reads the script
        lies chapters before an unrelated later knowledge fact). `_reserved_states` chooses among them."""
        before=screening.before_chapter(claim); text=claim["text"]
        person_of=ContinuityEngine._person_of(aliases)
        named={person_of[name] for name in person_of if len(name)>=2 and name in text}
        found:list[dict[str,Any]]=[]
        for item in memory:
            subject=str(item.get("subject","")).strip(); person=person_of.get(subject,subject)
            predicate=normalized_predicate(str(item.get("predicate","")))
            chapter=chapters.get(item["id"])
            if chapter is None or chapter>=before or not subject or (predicate not in STATE_PREDICATES and item.get("memory_type") not in STATE_MEMORY_TYPES):continue
            if person not in named and not (len(subject)>=2 and subject in text):continue
            found.append(item)
        return found

    @staticmethod
    def _reserved_states(states:list[dict[str,Any]],terms:Any,chapters:dict[str,int],aliases:list[dict[str,Any]]|None,slots:int)->list[dict[str,Any]]:
        """The state facts that take the reserved slots, in this order: each person's two facts sharing the most words with the
        claim, then the latest fact of each person and predicate, then the rest by shared words. Later chapter first among equals."""
        person_of=ContinuityEngine._person_of(aliases)
        def text(item):return " ".join(str(item.get(key,"")) for key in ("subject","predicate","value"))
        rank=lambda item:(-_relevance_score(terms,text(item)),-chapters.get(item["id"],0),_memory_sort_key(item))
        by_relevance=sorted(states,key=rank)
        def person(item):
            subject=str(item.get("subject","")).strip();return person_of.get(subject,subject)
        # Each person's two closest facts: one predicate (knowledge) holds facts about unrelated things.
        best:dict[str,list[dict[str,Any]]]={}
        for item in by_relevance:
            picked=best.setdefault(person(item),[])
            if len(picked)<2 and _relevance_score(terms,text(item))>0:picked.append(item)
        latest:dict[tuple[str,str],dict[str,Any]]={}
        for item in states:
            key=(person(item),normalized_predicate(str(item.get("predicate",""))))
            if key not in latest or (chapters.get(item["id"],0),str(item["id"]))>(chapters.get(latest[key]["id"],0),str(latest[key]["id"])):latest[key]=item
        ordered=sorted((item for picked in best.values() for item in picked),key=rank)+sorted(latest.values(),key=rank)+by_relevance
        chosen:list[dict[str,Any]]=[];seen=set()
        for item in ordered:
            if item["id"] in seen:continue
            seen.add(item["id"]);chosen.append(item)
            if len(chosen)==slots:break
        return chosen

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
        used:dict[str,dict[str,Any]]={}; extras:list[tuple[int,dict[str,Any]]]=[]
        for position,claim in enumerate(selected):
            reserved,rest=self._related_parts(claim,memory,memory_limit,chapters,data.get("aliases"))
            used.update({item["id"]:item for item in reserved+rest})
            extras.extend((position,passage) for passage in self._source_passages(claim,reserved,data.get("passage_index")))
        full=data["contexts"][claims[0]["context"]]
        body=screening.context_window(full,[claim["text"] for claim in claims])
        def build(added:list[tuple[int,dict[str,Any]]])->dict[str,Any]:
            shown=[{**claim,"allowed_evidence":claim["allowed_evidence"]+[passage for place,passage in added if place==position]} for position,claim in enumerate(selected)]
            return {"pipeline":"screened",**({"second_review":True} if data.get("second_review") else {}),"draft":{"id":data["draft"]["id"],"revision":data["draft"]["revision"],"body":body},"claims":shown,
                    "memory":[{**used[key],"chapter_number":chapters.get(key)} for key in sorted(used,key=lambda key:_memory_sort_key(used[key]))],"output_schema":_continuity_schema(),"full_draft_body":full}
        request=build([])
        # The sources of the reserved facts are added only while the request stays within its input budget: the last one added goes first.
        if extras and self._fits(request):
            for count in range(len(extras),0,-1):
                fuller=build(extras[:count])
                if self._fits(fuller):return fuller
        return request

    @staticmethod
    def _source_passages(claim:dict[str,Any],reserved:list[dict[str,Any]],index:Any)->list[dict[str,Any]]:
        """The passage each reserved state fact comes from, when the claim's passages lack it (at most SOURCE_PASSAGES_PER_CLAIM).

        A fact the review can only cite as a fact cannot make a confirmed conflict: that needs the text it
        stands on. Passages of the checked chapter or later are never added, as the facts themselves are not.
        The slots go to the reserved facts that share the most words with the claim, in reserved order among equals:
        the reserved order is about covering each person and predicate, and could leave the fact that matters last."""
        if index is None:return []
        have={span["id"] for span in claim["allowed_evidence"]}; before=screening.before_chapter(claim); added:list[dict[str,Any]]=[]
        terms=_claim_terms(claim["text"])
        def score(item:dict[str,Any])->int:return _relevance_score(terms," ".join(str(item.get(key,"")) for key in ("subject","predicate","value")))
        for item in sorted(reserved,key=lambda item:-score(item)):
            passage=screening.fact_evidence(index,item["id"])
            if passage is None or passage["id"] in have or passage["chapter_number"]>=before:continue
            if len(added)>=SOURCE_PASSAGES_PER_CLAIM:break
            have.add(passage["id"]); added.append(passage)
        return added

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
                # Ids are read as validate reads them: one mistyped character still names the cited span or fact.
                span_id=_resolve_id(item.get("span_id"),allowed)[0] if isinstance(item,dict) else None
                if span_id is not None:
                    span=allowed[span_id]; cited=item.get("related_memory_ids") if isinstance(item.get("related_memory_ids"),list) else []
                    bound_evidence.append({**item,"span_id":span_id,"excerpt":span.get("prompt_excerpt",span["body"]),"source_span_id":span.get("source_span_id",span["id"]),
                                           "related_memory_ids":[found for found in (_resolve_id(memory_id,mem)[0] for memory_id in cited) if found is not None]})
            temporal_failure=_confirmed_temporal_failure(raw,claim["text"],bound_evidence,mem)
            # Missing/unresolvable evidence is a binding failure, not a proved time mismatch. The screened
            # pipeline settles an unproved time or rule locally (see validate), never by a repair.
            if temporal_failure and bound_evidence and data.get("pipeline")!="screened":codes.append(temporal_failure)
            if codes:
                evidence_excerpts=[]
                for evidence in raw_evidence:
                    span_id=_resolve_id(evidence.get("span_id"),allowed)[0] if isinstance(evidence,dict) else None
                    if span_id is not None:
                        span=allowed[span_id]
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
            capped=screening.capped_key_claims(claims,{claim_id:flag["kind"] for claim_id,flag in flags.items()})
            flags.update({claim_id:{**flags[claim_id],"kind":"check"} for claim_id in capped})
            summary["key_capped"]=len(capped)
        else:
            # A short draft is reviewed whole, every sentence with thinking.
            flags={claim["id"]:{"kind":"unscreened","facts":[]} for claim in claims}
        summary["flagged"]=len(flags)
        evidence={claim["id"]:screening.claim_evidence(claim,index,flags[claim["id"]]["facts"]) for claim in claims if claim["id"] in flags}
        # A flagged sentence with no earlier passage at all has nothing to be reviewed against.
        reviewed=[{**claim,"allowed_evidence":evidence[claim["id"]],"screen_facts":flags[claim["id"]]["facts"]} for claim in claims if evidence.get(claim["id"])]
        summary["reviewed"]=len(reviewed)
        base={**data,"memory_chapters":chapters,"passage_index":index}
        triaged=[claim for claim in reviewed if flags[claim["id"]]["kind"]=="check"]
        results=list(screen_results); escalated:set[str]=set()
        summary.update(triaged=len(triaged),triage_fallback_batches=0,escalated=0,deep_reviewed=0)
        if summary["screened"] and not screening.DOUBLE_REVIEW:
            result,escalated=self._review_overlapped(reviewed,triaged,flags,base,results,summary)
            deep=[claim for claim in reviewed if flags[claim["id"]]["kind"]!="check" or claim["id"] in escalated]
            paths={claim["id"]:("escalated" if claim["id"] in escalated else "deep") for claim in deep}
            paths.update({claim["id"]:"triage" for claim in triaged if claim["id"] not in escalated})
            return {**result,"retrieval_traces":screening.retrieval_traces(claims,{claim["id"]:claim["allowed_evidence"] for claim in reviewed},flags,True,paths,
                                                                         summary.pop("triage_detail",None)),
                    "retrieval_method_version":SCREENED_RETRIEVAL_METHOD_VERSION,"screening":summary}
        if triaged:
            # What the triage flags gets a thinking review; what it passes is settled.
            escalated=self._triage(triaged,data["contexts"],results,summary)
            if isinstance(escalated,dict):return self._failure(escalated["error"],results)
            summary["escalated"]=len(escalated)
        deep=[claim for claim in reviewed if flags[claim["id"]]["kind"]!="check" or claim["id"] in escalated]
        summary["deep_reviewed"]=len(deep)
        # A short draft keeps the per-sentence batching (and the quota preflight's arithmetic) of before.
        limit=screening.DEEP_MAX_CLAIMS if summary["screened"] else CONTINUITY_MAX_CLAIMS_PER_BATCH
        # Key sentences (a conflict or gap at the screen) are reviewed twice, in the same parallel run.
        passes=[{**claim,"id":claim["id"]+screening.SECOND_PASS_SUFFIX} for claim in deep if flags[claim["id"]]["kind"] in screening.DEEP_KINDS] if summary["screened"] and screening.DOUBLE_REVIEW else []
        summary["double_reviewed"]=len(passes)
        result=self._execute({**base,"claims":deep+passes,"max_claims_per_batch":limit,"settled_by_screen":summary["screened"]},prior_results=results,keep_results=True)
        if passes and result["status"]=="completed":
            result=self._merge_passes(result,{claim["id"] for claim in deep if claim["id"]+screening.SECOND_PASS_SUFFIX in {p["id"] for p in passes}},
                                      {claim["id"]:index for index,claim in enumerate(claims)},summary)
        if screening.SECOND_LOOK and not passes and summary["screened"] and result["status"]=="completed":
            result=self._second_look(result,deep,flags,base,summary)
        result={key:value for key,value in result.items() if key!="_results"}
        paths={claim["id"]:("escalated" if claim["id"] in escalated else "deep") for claim in deep}
        paths.update({claim["id"]:"triage" for claim in triaged if claim["id"] not in escalated})
        result={**result,"retrieval_traces":screening.retrieval_traces(claims,{claim["id"]:claim["allowed_evidence"] for claim in reviewed},flags,summary["screened"],paths,
                                                                       summary.pop("triage_detail",None)),
                "retrieval_method_version":SCREENED_RETRIEVAL_METHOD_VERSION,"screening":summary}
        return result

    def _review_overlapped(self,reviewed:list[dict[str,Any]],triaged:list[dict[str,Any]],flags:dict[str,Any],base:dict[str,Any],
                           results:list[Any],summary:dict[str,Any])->tuple[dict[str,Any],set[str]]:
        """Key sentences' reviews (and second reviews) run while the triage runs, in one shared pool.

        Waiting for the triage before any thinking review, and for every first review before any second
        review, put two or three slow stages end to end on the slowest chapters (lf1 dev set, 2026-10-05:
        p90 up to 115 s). The key-sentence stage runs in its own thread; the triage and then the
        escalated sentences' reviews run here; every dispatch goes through the same pool, so a check
        never has more requests in flight than its concurrency.
        """
        key=[claim for claim in reviewed if flags[claim["id"]]["kind"]!="check"]
        concurrency=getattr(self.provider,"continuity_batch_concurrency",None)
        concurrency=concurrency if isinstance(concurrency,int) and not isinstance(concurrency,bool) and concurrency>1 else 1
        pool=ThreadPoolExecutor(max_workers=concurrency,thread_name_prefix="continuity-review") if concurrency>1 else None
        stage:dict[str,Any]={}
        def key_stage()->None:
            outcome=self._execute({**base,"claims":key,"max_claims_per_batch":screening.DEEP_MAX_CLAIMS,"settled_by_screen":True},keep_results=True,pool=pool)
            if screening.SECOND_LOOK and outcome["status"]=="completed":
                outcome=self._second_look(outcome,key,flags,base,summary,pool=pool)
            stage["key"]=outcome
        escalated:set[str]=set(); triage_error=None
        try:
            worker=threading.Thread(target=contextvars.copy_context().run,args=(key_stage,),name="continuity-key-stage")
            worker.start()
            try:
                sweep_ids:list[str]=[]
                if triaged:
                    found=self._triage(triaged,base["contexts"],results,summary,pool=pool,sweep_ids=sweep_ids)
                    if isinstance(found,dict):triage_error=found["error"]
                    else:escalated=found; summary["escalated"]=len(escalated)
                if triage_error is None and escalated:
                    stage["escalated"]=self._execute({**base,"claims":[claim for claim in triaged if claim["id"] in escalated],"max_claims_per_batch":screening.DEEP_MAX_CLAIMS,"settled_by_screen":True},keep_results=True,pool=pool)
                if triage_error is None and sweep_ids:
                    summary["sweep"]=len(sweep_ids)
                    # The gap sweep: what the triage scored 2 or 3 but could not escalate, a few to a request.
                    stage["sweep"]=self._execute({**base,"claims":[claim for claim in triaged if claim["id"] in sweep_ids],"max_claims_per_batch":screening.TRIAGE_SWEEP_BATCH,
                                                  "settled_by_screen":True,"second_review":True},keep_results=True,pool=pool)
            finally:
                worker.join()
        finally:
            if pool is not None:pool.shutdown(wait=True)
        summary.update(deep_reviewed=len(key)+len(escalated),double_reviewed=0)
        outcomes=[stage[name] for name in ("key","escalated") if name in stage]
        sweep=stage.get("sweep")
        spent=results+[item for outcome in outcomes+([sweep] if sweep else []) for item in outcome.get("_results",[])]
        if triage_error is not None:return self._failure(triage_error,spent),escalated
        failed=next((outcome for outcome in outcomes if outcome["status"]!="completed"),None)
        if failed is not None:
            # Usage of the other stages is added to the failed stage's own (which never includes the screen).
            return {**{key:value for key,value in failed.items() if key!="_results"},**_aggregate_or_unknown(spent,failed)},escalated
        order={claim["id"]:index for index,claim in enumerate(base["claims"])}
        merged=lambda field:sorted((row for outcome in outcomes for row in outcome[field]),key=lambda row:order[row["claim_span_id"]])
        normalizations=[row for outcome in outcomes for row in outcome["contract_normalizations"]]
        totals=_aggregate(spent)
        # A stage that dispatched but reports no usage had a timed-out dispatch: the check's usage is unknown.
        if any(outcome.get("_results") and outcome.get(field) is None for outcome in outcomes for field in ("input_tokens","output_tokens")):
            totals={field:None for field in totals}
        undecided=merged("undecided_claims")
        issues=merged("issues")
        if sweep is not None and sweep["status"]=="completed":
            # Only what the sweep finds counts; a sentence it could not decide keeps the triage's verdict.
            found=[issue for issue in sweep["issues"] if issue.get("nature") in {"confirmed_conflict","possible_conflict","insufficient_evidence"}]
            ids={issue["claim_span_id"] for issue in found}
            issues=sorted(issues+found,key=lambda row:order[row["claim_span_id"]])
            normalizations+=[row for row in sweep["contract_normalizations"] if row["claim_span_id"] in ids]
            summary["sweep_found"]=len(found)
            if any(sweep.get("_results") and sweep.get(field) is None for field in ("input_tokens","output_tokens")):
                totals={field:None for field in totals}
        return {"status":"completed","issues":issues,"contract_normalization_count":len(normalizations),"contract_normalizations":normalizations,
                "undecided_claim_count":len(undecided),"undecided_claims":undecided,**totals},escalated

    def _merge_passes(self,result:dict[str,Any],doubled:set[str],order:dict[str,int],summary:dict[str,Any])->dict[str,Any]:
        """Fold the second reviews back onto their sentences: a finding from either review counts.

        A conflict outranks a missing link, a confirmed conflict a possible one, and both outrank a
        state_change, which is never a card. A sentence reviewed twice is undecided only if both were.
        """
        suffix=screening.SECOND_PASS_SUFFIX
        base_id=lambda claim_id:claim_id[:-len(suffix)] if claim_id.endswith(suffix) else claim_id
        rank=lambda issue:{"confirmed_conflict":3,"possible_conflict":2,"insufficient_evidence":1}.get(issue.get("nature"),0)
        chosen:dict[str,dict[str,Any]]={}; found_first=set()
        for issue in result["issues"]:
            claim_id=base_id(issue["claim_span_id"])
            if claim_id==issue["claim_span_id"]:found_first.add(claim_id)
            issue={**issue,"claim_span_id":claim_id}
            if claim_id not in chosen or rank(issue)>rank(chosen[claim_id]):chosen[claim_id]=issue
        summary["double_found"]=sum(1 for claim_id in chosen if claim_id in doubled and claim_id not in found_first)
        rows:dict[str,list[dict[str,Any]]]={}
        for row in result["undecided_claims"]:rows.setdefault(base_id(row["claim_span_id"]),[]).append(row)
        kept=[{**found[0],"claim_span_id":claim_id} for claim_id,found in rows.items() if claim_id not in chosen and (claim_id not in doubled or len(found)==2)]
        normalizations=list({(base_id(row["claim_span_id"]),row["reason_code"]):{**row,"claim_span_id":base_id(row["claim_span_id"])}
                             for row in result["contract_normalizations"] if base_id(row["claim_span_id"]) in chosen}.values())
        issues=sorted(chosen.values(),key=lambda issue:order[issue["claim_span_id"]])
        return {**result,"issues":issues,"undecided_claims":sorted(kept,key=lambda row:order[row["claim_span_id"]]),"undecided_claim_count":len(kept),
                "contract_normalizations":normalizations,"contract_normalization_count":len(normalizations)}

    def _second_look(self,result:dict[str,Any],deep:list[dict[str,Any]],flags:dict[str,Any],base:dict[str,Any],summary:dict[str,Any],pool:ThreadPoolExecutor|None=None)->dict[str,Any]:
        """A second, independent thinking review of key sentences the first review passed.

        Key sentences are those the screen saw a conflict or gap in. The verdict on a borderline one
        varied from run to run (lf1 dev set, 2026-10-05), and reviewing every key sentence twice cost
        too much, so only those passed by the first review are reviewed again, as shadow claims with
        SECOND_PASS_SUFFIX on their id. A conflict or missing link it finds counts; a failed or
        undecided second review leaves the first outcome as it was, with the usage of both counted.
        """
        suffix=screening.SECOND_PASS_SUFFIX
        decided={issue["claim_span_id"] for issue in result["issues"]}|{row["claim_span_id"] for row in result["undecided_claims"]}
        passed=[claim for claim in deep if claim["id"] not in decided]
        again=[{**claim,"id":claim["id"]+suffix} for claim in screening.second_look_claims(passed,{claim["id"]:flags[claim["id"]]["kind"] for claim in passed})]
        summary.update(second_look=len(again),second_look_found=0)
        if not again:return result
        second=self._execute({**base,"claims":again,"max_claims_per_batch":1,"settled_by_screen":True,"second_review":True},prior_results=result["_results"],keep_results=True,pool=pool)
        totals={key:second.get(key) for key in ("input_tokens","output_tokens","latency_ms","cost_cny")}
        if second["status"]!="completed":return {**result,**totals,"_results":second.get("_results",result["_results"])}
        strip=lambda row:{**row,"claim_span_id":row["claim_span_id"][:-len(suffix)]}
        found=[strip(issue) for issue in second["issues"] if issue.get("nature") in {"confirmed_conflict","possible_conflict","insufficient_evidence"}]
        found_ids={issue["claim_span_id"] for issue in found}
        normalizations=[strip(row) for row in second["contract_normalizations"] if row["claim_span_id"][:-len(suffix)] in found_ids]
        order={claim["id"]:index for index,claim in enumerate(base["claims"])}
        summary["second_look_found"]=len(found)
        return {**result,**totals,"_results":second["_results"],"issues":sorted(result["issues"]+found,key=lambda item:order[item["claim_span_id"]]),
                "contract_normalizations":result["contract_normalizations"]+normalizations,"contract_normalization_count":result["contract_normalization_count"]+len(normalizations)}

    def _triage(self,claims:list[dict[str,Any]],contexts:dict[str,str],results:list[Any],summary:dict[str,Any],pool:ThreadPoolExecutor|None=None,
                sweep_ids:list[str]|None=None)->set[str]|dict[str,Any]:
        """Claim ids to escalate by triage score; {"error": exception} when a dispatch fails.

        Batches run in parallel like review batches. An answer the validator rejects is retried once as
        a repair; a batch that still fails scores all its claims 2, so they compete for escalation.
        """
        batches=screening.triage_batches(claims,contexts); batch_kinds:dict[int,dict[str,str]]={}
        sweep_ids=sweep_ids if sweep_ids is not None else []
        def one(batch:tuple[dict[str,Any],dict[str,str]])->tuple[dict[str,int]|None,list[Any],Exception|None]:
            request,sentence_ids=batch; spent=[]; code="triage_invalid"; kinds=batch_kinds.setdefault(id(batch),{})
            try:
                for attempt in range(2):
                    sent=request if attempt==0 else {**request,"triage_repair":{"reason_code":code}}
                    try:result=self.provider.evaluate(sent)
                    except ProviderInvalidJson as error:
                        spent.append(error); code="triage_invalid_json"; continue
                    spent.append(result)
                    try:return screening.parse_triage(result.payload,sentence_ids,kinds),spent,None
                    except screening.ScreenContractError as error:code=str(error)
            except (ProviderDispatchDenied,InputBudgetExceeded,ProviderUnavailable,ProviderTimeout,ProviderFailure) as error:
                return None,spent,error
            return None,spent,None
        concurrency=getattr(self.provider,"continuity_batch_concurrency",None)
        concurrency=concurrency if isinstance(concurrency,int) and not isinstance(concurrency,bool) and concurrency>1 else 1
        if (pool is not None or concurrency>1) and len(batches)>1:
            # Each dispatch carries the caller's context (usage reservation, dispatch guard), copied here
            # in the calling thread, as review batches do.
            copies=[contextvars.copy_context() for _ in batches]
            if pool is not None:
                outcomes=list(pool.map(lambda pair:pair[0].run(one,pair[1]),zip(copies,batches)))
            else:
                with ThreadPoolExecutor(max_workers=concurrency,thread_name_prefix="continuity-triage") as own:
                    outcomes=list(own.map(lambda pair:pair[0].run(one,pair[1]),zip(copies,batches)))
        else:
            outcomes=[one(batch) for batch in batches]
        scores:dict[str,int]={}; failure=None
        for (request,sentence_ids),(found,spent,error) in zip(batches,outcomes):
            results.extend(spent)
            if error is not None:
                failure=failure or error; continue
            if found is None:
                summary["triage_fallback_batches"]+=1; found={claim_id:screening.TRIAGE_ESCALATION_MIN_SCORE for claim_id in sentence_ids.values()}
            scores.update(found)
        if failure is not None:return {"error":failure}
        summary["triage_scores"]={str(score):sum(1 for value in scores.values() if value==score) for score in range(4)}
        kinds={claim_id:kind for found in batch_kinds.values() for claim_id,kind in found.items()}
        summary["triage_marker_raised"]=screening.raise_link_markers(claims,scores,kinds)
        escalated=screening.triage_escalations(claims,scores,kinds)
        summary["triage_gap_escalated"]=len(escalated-screening.triage_escalations(claims,scores))
        sweep_ids[:]=[claim["id"] for claim in screening.triage_sweep(claims,scores,escalated)]
        # Per sentence: score, kind and what became of it, for the review trace (read by the long-form harness).
        summary["triage_detail"]={claim["id"]:{"score":scores.get(claim["id"],0),"kind":kinds.get(claim["id"],"none"),
                                              "outcome":"escalated" if claim["id"] in escalated else "swept" if claim["id"] in sweep_ids else "passed"}
                                  for claim in claims}
        return escalated

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

    def _execute(self,data:dict[str,Any],prior_results:list[Any]|None=None,keep_results:bool=False,pool:ThreadPoolExecutor|None=None)->dict[str,Any]:
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
        # A shared pool (screened chapters) bounds the whole check's requests in flight; it is not ours to shut down.
        shared=pool is not None
        if shared:concurrency=max(concurrency,pool._max_workers)
        pool=pool if shared else ThreadPoolExecutor(max_workers=concurrency,thread_name_prefix="continuity-batch") if concurrency>1 else None
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
            if pool is not None and not shared:pool.shutdown(wait=True)
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
        # In the screened pipeline a claim's own contract fault is never the run's failure: a short draft whose every
        # claim is undecided for that reason completes with them reported. Provider-side stops (quota, budget, a cut or malformed answer) still fail.
        contract_only=data.get("pipeline")=="screened" and all(row["error_code"] not in NON_CONTRACT_UNDECIDED for row in undecided)
        if undecided and len(undecided)==len(data["claims"]) and not data.get("settled_by_screen") and not contract_only: return {"status":"failed","error_code":undecided[0]["error_code"],"retryable":True,**totals}
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
        results=[]; normalizations=[]; first_payload=None
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
                    kept=self._keep_first_answer(first_payload,batch)
                    if kept is not None:
                        normalizations.extend(kept[1]); return {**outcome,"issues":screening.bind_passage_evidence(kept[0],batch["claims"])}
                    return {**outcome,"undecided":[{"claim_span_id":claims[0]["id"],"error_code":"input_budget_exceeded"}]}
                result=self.provider.evaluate(request)
                results.append(result)
                if contract_attempt==0:first_payload=result.payload
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
                    # The repair did not help: a conflict the first answer reached and cited well enough is kept, not lost with the repair.
                    kept=self._keep_first_answer(first_payload,batch)
                    if kept is not None:
                        normalizations.extend(kept[1]); return {**outcome,"issues":screening.bind_passage_evidence(kept[0],batch["claims"])}
                    return {**outcome,"undecided":[{"claim_span_id":batch["claims"][0]["id"],"error_code":str(error)}]}
                if batch.get("pipeline")=="screened":validated=screening.bind_passage_evidence(validated,batch["claims"])
                return {**outcome,"issues":validated}
        except ProviderDispatchDenied as error:
            if str(error)!=PROVIDER_ATTEMPT_QUOTA_EXCEEDED:return {**outcome,"error":error}
            # A refusal after a timed-out dispatch leaves that dispatch's billing unknown.
            return {**outcome,"quota_exhausted":True,"usage_unknown":bool(getattr(error,"usage_unknown",False)),"undecided":[{"claim_span_id":claim["id"],"error_code":PROVIDER_ATTEMPT_QUOTA_EXCEEDED} for claim in batch["claims"]]}
        except ProviderInvalidJson as error:
            if error.finish_reason!="length" and batch.get("pipeline")=="screened":
                # One malformed answer costs only its own claims: they are sent again one at a time, and a
                # lone claim that comes back malformed is undecided (lf1 dev set: one bad JSON failed a chapter).
                results.append(error)
                claims=batch["claims"]
                if len(claims)>1:return {**outcome,"split":[[claim] for claim in claims]}
                return {**outcome,"undecided":[{"claim_span_id":claims[0]["id"],"error_code":"invalid_json"}]}
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

    def _keep_first_answer(self,payload:Any,data:dict[str,Any])->tuple[list[dict[str,Any]],list[dict[str,Any]]]|None:
        """The first answer of a one-claim batch kept as a possible conflict once its repair has failed, or None.

        A repair answer that is itself unusable (its verdict contradicts its issues, say) must not cost
        a conflict the first answer already reached. The first answer qualifies exactly as in
        `_keep_as_possible`: its ledger is consistent, the claim's issue is a reviewed conflict, it failed
        only a citation rule in KEEPABLE_CONTRACT_ERRORS and at least one citation resolves.
        """
        if data.get("pipeline")!="screened" or len(data["claims"])!=1 or not isinstance(payload,dict) or not isinstance(payload.get("issues"),list):return None
        verdicts:dict[str,Any]={}
        if getattr(self.provider,"continuity_contract_version",None)=="v6":
            try:self._v6_issues(payload,data)
            except ValueError:return None
            verdicts={item["claim_span_id"]:item.get("verdict") for item in payload["claim_verdicts"] if isinstance(item,dict)}
        claims={item["id"]:item for item in data["claims"]}; mem={item["id"]:item for item in data["memory"]}
        if len(payload["issues"])!=1:return None
        raw=payload["issues"][0]; scratch:list[dict[str,Any]]=[]
        try:self._validate_issue(raw,data,claims,mem,False,1,scratch)
        except ValueError as error:
            kept=self._keep_as_possible(raw,error,data,claims,mem,verdicts,1)
            return ([kept[0]],kept[1]) if kept is not None else None
        return None

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
        verdicts:dict[str,Any]={}
        if getattr(self.provider,"continuity_contract_version",None)=="v6":
            original=payload; payload=self._v6_issues(payload,data)
            verdicts={item["claim_span_id"]:item.get("verdict") for item in original["claim_verdicts"] if isinstance(item,dict)}
        if not isinstance(payload,dict) or set(payload)!={"issues"} or not isinstance(payload.get("issues"),list):raise ValueError("schema_invalid")
        claims={x["id"]:x for x in data["claims"]}; mem={x["id"]:x for x in data["memory"]}; output=[]; notes=[]
        # Two issues for one claim: in the screened pipeline that is this claim's repairable fault, not the run's (see _execute).
        if data.get("pipeline")=="screened":
            ids=[row.get("claim_span_id") for row in payload["issues"] if isinstance(row,dict)]
            if len(ids)!=len(set(ids)):raise ValueError("schema_invalid")
        attempt=2 if allow_conservative_temporal_normalization else 1
        for raw in payload["issues"]:
            mark=len(notes)
            try:output.append(self._validate_issue(raw,data,claims,mem,allow_conservative_temporal_normalization,attempt,notes))
            except ValueError as error:
                del notes[mark:]
                # Only once the one repair is spent (the second attempt) may a conflict that is still not compliant be kept as a possible one.
                kept=self._keep_as_possible(raw,error,data,claims,mem,verdicts,attempt) if allow_conservative_temporal_normalization else None
                if kept is None:raise
                output.append(kept[0]); notes.extend(kept[1])
        if normalization_sink is not None:normalization_sink.extend(notes)
        return output

    def _validate_issue(self,raw:Any,data:dict[str,Any],claims:dict[str,Any],mem:dict[str,Any],allow_conservative_temporal_normalization:bool,attempt:int,notes:list[dict[str,Any]])->dict[str,Any]:
        """One issue through the review contract; its contract normalizations are appended to `notes`."""
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
            if not isinstance(ev,dict):raise ValueError("evidence_unresolvable")
            # One mistyped character of an id is not a different citation: take the single allowed id it
            # can only mean. The span fixes the chapter, so the model's own chapter_id is not checked.
            span_id,fixed=_resolve_id(ev.get("span_id"),allowed)
            if span_id is None:raise ValueError("evidence_unresolvable")
            if fixed:notes.append(_normalization(raw,"id_corrected","corrected",attempt))
            s=allowed[span_id]
            if ev.get("chapter_id")!=s["chapter_id"]:notes.append(_normalization(raw,"chapter_id_replaced","corrected",attempt))
            related_ids=ev.get("related_memory_ids")
            if (ev.get("relation") not in {"supports","contradicts","context"} or ev.get("sufficiency") not in {"sufficient","insufficient"} or
                not isinstance(related_ids,list) or any(not isinstance(memory_id,str) for memory_id in related_ids)):
                raise ValueError("evidence_unresolvable")
            # Memory ids only accompany a citation: one that resolves to nothing is dropped, not fatal.
            kept_ids=[]
            for memory_id in related_ids:
                found,fixed=_resolve_id(memory_id,mem)
                if found is None:
                    notes.append(_normalization(raw,"id_dropped","dropped",attempt));continue
                if fixed:notes.append(_normalization(raw,"id_corrected","corrected",attempt))
                if found not in kept_ids:kept_ids.append(found)
            if raw["status"]=="conflict" and not trustworthy and (ev.get("relation")!="contradicts" or ev.get("sufficiency")!="sufficient"):raise ValueError("conflict_evidence_not_direct")
            if raw["status"]=="insufficient_evidence" and ev.get("sufficiency")!="insufficient":
                # A reviewed insufficient_evidence issue that marks a citation sufficient is a
                # self-contradicting answer (V10 diagnostic rerun, 1 in 5): allow the bounded repair.
                code="insufficient_evidence_upgraded"
                if not trustworthy:raise ValueError(code)
                raise ContinuityContractValidationError(code,diagnostics=[_contract_diagnostic(data,code,raw["claim_span_id"],invalid_field="evidence.sufficiency",
                    requirement="An insufficient_evidence issue cites only context marked sufficiency insufficient; otherwise reclassify the issue.")])
            cleaned.append({"chapter_id":s["chapter_id"],"span_id":s["id"],"excerpt":s.get("prompt_excerpt",s["body"]),"relation":ev["relation"],"sufficiency":ev["sufficiency"],"related_memory_ids":kept_ids,
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
                notes.append(_normalization(raw,temporal_failure,"possible_conflict",attempt))
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
            fixed_chain=[]
            for item in chain:
                chain_id,fixed=_resolve_id(item["span_id"],allowed)
                if chain_id is None:raise ValueError("evidence_unresolvable")
                if fixed:notes.append(_normalization(raw,"id_corrected","corrected",attempt))
                fixed_chain.append({**item,"span_id":chain_id})
            chain=fixed_chain
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
                notes.append(_normalization(raw,temporal_failure,"insufficient_evidence",attempt))
                return {"claim_span_id":raw["claim_span_id"],"status":"insufficient_evidence","category":raw["category"],"severity":"medium","evidence_status":"insufficient","explanation":safe_explanation,"evidence":insufficient,"proposed_memory_change":None,"review_contract_version":"trustworthy_review_v1","nature":"insufficient_evidence","reasoning":safe_reasoning,"evidence_chain":[{"span_id":item["span_id"],"role":"missing_link"} for item in insufficient],"suggested_revision":None,"available_actions":[]}
            if nature=="confirmed_conflict" and temporal["relation"]=="timeless_rule" and suggestion is not None:
                suggestion=None;actions=[action for action in actions if action!="apply_suggestion"]
            review={"review_contract_version":"trustworthy_review_v1","nature":nature,"reasoning":reasoning.strip(),"evidence_chain":chain,"suggested_revision":suggestion,"available_actions":actions}
        return {"claim_span_id":raw["claim_span_id"],"status":raw["status"],"category":raw["category"],"severity":raw["severity"],"evidence_status":"sufficient" if cleaned and all(item["sufficiency"]=="sufficient" for item in cleaned) else "insufficient","explanation":explanation.strip()[:500],"evidence":cleaned,"proposed_memory_change":change,**review}

    def _keep_as_possible(self,raw:Any,error:ValueError,data:dict[str,Any],claims:dict[str,Any],mem:dict[str,Any],verdicts:dict[str,Any],attempt:int)->tuple[dict[str,Any],list[dict[str,Any]]]|None:
        """A conflict the model decided on but could not cite compliantly even after its repair, kept as a possible conflict.

        Only the citation faults in KEEPABLE_CONTRACT_ERRORS qualify, only for an issue the model reached
        as reviewed_issue / conflict, and only when at least one citation resolves (an allowed passage, or
        an existing Memory fact that comes from one). The kept issue cites just the resolvable part, has
        no time basis (unknown) and keeps its suggested revision only when that is compliant. None means
        something else is wrong: the caller raises the original error.
        """
        review_keys={"nature","reasoning","temporal_basis","evidence_chain","suggested_revision","available_actions"}
        if str(error) not in KEEPABLE_CONTRACT_ERRORS or not isinstance(raw,dict) or not isinstance(raw.get("claim_span_id"),str) or raw["claim_span_id"] not in claims:return None
        claim=claims[raw["claim_span_id"]]
        if raw.get("status")!="conflict" or verdicts.get(claim["id"])!="reviewed_issue" or raw.get("nature") not in {"confirmed_conflict","possible_conflict"} or not review_keys<=set(raw):return None
        allowed={item["id"]:item for item in claim["allowed_evidence"]}
        kept=[]; seen=set(); notes:list[dict[str,Any]]=[]
        for ev in raw.get("evidence") if isinstance(raw.get("evidence"),list) else []:
            if not isinstance(ev,dict):continue
            span_id,fixed=_resolve_id(ev.get("span_id"),allowed)
            if fixed:notes.append(_normalization(raw,"id_corrected","corrected",attempt))
            if span_id is not None and ev.get("chapter_id")!=allowed[span_id]["chapter_id"]:notes.append(_normalization(raw,"chapter_id_replaced","corrected",attempt))
            cited=ev.get("related_memory_ids") if isinstance(ev.get("related_memory_ids"),list) else []
            memory_ids=[]
            for memory_id in cited:
                found,fixed=_resolve_id(memory_id,mem)
                if found is None:notes.append(_normalization(raw,"id_dropped","dropped",attempt))
                elif found not in memory_ids:
                    memory_ids.append(found)
                    if fixed:notes.append(_normalization(raw,"id_corrected","corrected",attempt))
            if span_id is None:
                # An existing Memory fact still locates the passage it came from.
                span_id=next((item["id"] for memory_id in memory_ids for item in allowed.values() if mem[memory_id].get("source_span_id")==item.get("source_span_id",item["id"])),None)
            if span_id is None or span_id in seen:continue
            seen.add(span_id)
            kept.append({"chapter_id":allowed[span_id]["chapter_id"],"span_id":span_id,"relation":ev["relation"] if ev.get("relation") in {"supports","contradicts","context"} else "context","sufficiency":"sufficient","related_memory_ids":memory_ids})
        if not kept:return None
        excerpts=[allowed[item["span_id"]].get("prompt_excerpt",allowed[item["span_id"]]["body"]) for item in kept]
        temporal=raw["temporal_basis"] if isinstance(raw["temporal_basis"],dict) else {}
        claim_anchor,evidence_anchor=temporal.get("claim_anchor"),temporal.get("evidence_anchor")
        claim_anchor=claim_anchor if isinstance(claim_anchor,str) and claim_anchor.strip() and claim_anchor in claim["text"] else None
        evidence_anchor=evidence_anchor if isinstance(evidence_anchor,str) and evidence_anchor.strip() and any(evidence_anchor in text for text in excerpts) else None
        roles={}
        for item in raw["evidence_chain"] if isinstance(raw["evidence_chain"],list) else []:
            if isinstance(item,dict):
                chain_id=_resolve_id(item.get("span_id"),allowed)[0]
                if chain_id is not None and item.get("role") in EVIDENCE_CHAIN_ROLES and item["role"]!="missing_link":roles.setdefault(chain_id,item["role"])
        actions=raw["available_actions"]
        if not isinstance(actions,list) or any(not isinstance(action,str) for action in actions):return None
        actions=[action for action in dict.fromkeys(actions) if action in REVIEW_ACTIONS]
        suggestion=raw["suggested_revision"]
        if not (isinstance(suggestion,dict) and set(suggestion)=={"before","after"} and all(isinstance(suggestion[field],str) and suggestion[field].strip() for field in ("before","after")) and
                suggestion["before"]!=suggestion["after"] and data.get("full_draft_body",data["draft"]["body"]).count(suggestion["before"])==1 and "apply_suggestion" in actions):
            suggestion=None; actions=[action for action in actions if action!="apply_suggestion"]
        repaired={**raw,"nature":"possible_conflict","evidence":kept,"evidence_chain":[{"span_id":item["span_id"],"role":roles.get(item["span_id"],"prior_state")} for item in kept],
                  "temporal_basis":{"claim_anchor":claim_anchor,"evidence_anchor":evidence_anchor,"relation":"unknown"},"suggested_revision":suggestion,"available_actions":actions,"proposed_memory_change":None}
        try:issue=self._validate_issue(repaired,data,claims,mem,True,attempt,notes)
        except ValueError:return None
        notes.append(_normalization(raw,"kept_as_possible_after_repair","possible_conflict",attempt))
        return issue,notes


class WritingAnalysisEngine:
    """Strict, bounded analysis over one immutable database-prepared input."""
    def __init__(self,provider:ProviderPort):self.provider=provider

    def provenance(self,analysis_type:str)->dict[str,str]:
        prompt_version=PLAN_ALIGNMENT_PROMPT_VERSION if analysis_type=="plan_alignment" else CHANGE_IMPACT_PROMPT_VERSION if analysis_type=="change_impact" else FORESHADOW_SCAN_PROMPT_VERSION
        schema_version="writing-analysis-v2-foreshadow-evidence-kind" if analysis_type=="foreshadow_scan" else "writing-analysis-v1"
        retrieval_version=ANALYSIS_RETRIEVAL_METHOD_VERSION
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":prompt_version,"schema_version":schema_version,"retrieval_method_version":retrieval_version}

    @staticmethod
    def _schema(task:str)->dict[str,Any]:
        if task=="change_impact":
            return {"summary":"1-400 chars","items":[{"area":"chapter|character|world|memory|plan","target_id":"supplied target id","impact":"1-600 chars; analysis only, never replacement prose","evidence":[{"source_type":"author_context|memory_record|source_span|draft_claim|character_record|character_alias|world_record","source_id":"supplied id"}]}]}
        if task=="foreshadow_scan":
            return {"summary":"1-400 chars","candidates":[{"title":"1-120 chars","description":"1-1200 chars","suggested_status":"planted|developing|resolved","evidence":[{"source_type":"source_span|draft_claim","source_id":"supplied id","relation":"planted|developing|resolved","evidence_kind":"current_clue|specific_prior_unresolved_clue|background_only|explicit_payoff"}]}]}
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
        return {"author_context":author,"memory_record":memory,"source_span":{item["id"]:item for item in written["source_spans"]},"draft_claim":{item["id"]:item for item in written["draft_claims"]},"character_record":{item["id"]:item for item in identity.get("characters",[])},"character_alias":{item["id"]:item for item in identity.get("aliases",[])},"world_record":{item["id"]:item for item in reference.get("world_entries",[])}}

    @classmethod
    def _clean_source(cls,raw:Any,maps:dict[str,dict[str,dict[str,Any]]],allowed:set[str],project_id:str)->dict[str,Any]:
        if not isinstance(raw,dict) or set(raw)!={"source_type","source_id"} or raw.get("source_type") not in allowed:raise ValueError("evidence_unresolvable")
        source_type=raw["source_type"]
        # An id copied wrongly by one character still names the one supplied id it differs from.
        source_id=_resolve_id(raw.get("source_id"),maps[source_type])[0]
        if source_id is None:raise ValueError("evidence_unresolvable")
        item=maps[source_type][source_id]
        if source_type=="author_context":label=item.get("title") or item.get("name") or "作者规划";excerpt=item.get("content") or item.get("summary") or item.get("goal") or item.get("planned_state") or item.get("description") or ""
        elif source_type=="memory_record":label=f"{item['subject']} · {predicate_label(item['predicate'])}";excerpt=item["value"]
        elif source_type=="draft_claim":label=f"当前草稿 · 句 {item['ordinal']}";excerpt=item["text"]
        elif source_type=="character_record":label=item["name"];excerpt=" · ".join(filter(None,(item.get("identity"),item.get("current_state"),item.get("knowledge_boundary"))))
        elif source_type=="character_alias":label=f"{item['primary_name']} · 别名";excerpt=item["alias"]
        elif source_type=="world_record":label=item["name"];excerpt=item["summary"]
        else:label=f"第 {item['chapter_number']} 章 · {item['label']}";excerpt=item["body"]
        if source_type=="author_context":source_path=f"/projects/{project_id}/{item['_source_route']}#plan-{source_id}"
        elif source_type=="memory_record":source_path=f"/projects/{project_id}/memory#memory-{source_id}"
        elif source_type=="draft_claim":source_path=f"/projects/{project_id}/workspace#draft-source"
        elif source_type=="character_record":source_path=f"/projects/{project_id}/characters?character={source_id}#character-{source_id}"
        elif source_type=="character_alias":source_path=f"/projects/{project_id}/characters?character={item['character_id']}#alias-{source_id}"
        elif source_type=="world_record":source_path=f"/projects/{project_id}/world?world={source_id}#world-{source_id}"
        else:source_path=f"/projects/{project_id}/sources#span-{source_id}"
        return {"source_type":source_type,"source_id":source_id,"label":str(label)[:160],"excerpt":str(excerpt)[:900],"source_path":source_path}

    def validate(self,payload:Any,data:dict[str,Any])->dict[str,Any]:
        maps=self._source_maps(data);task=data["task"];project_id=data["bindings"]["project_id"]
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
                    span=span_map.get(cleaned["source_id"])
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
            if request_prompt_and_budget(request)[1]>WRITING_ANALYSIS_INPUT_BUDGET_UNITS:raise InputBudgetExceeded()
            response=self.provider.evaluate(request)
            if (response.input_tokens or 0)+(response.output_tokens or 0)>MAX_WRITING_ANALYSIS_RUN_TOKENS:return {"status":"budget_paused","error_code":"budget_paused","retryable":True,**_aggregate([response])}
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
                    # The repairs are spent. Faults of single candidates cost those candidates, not the import (third A1c
                    # formal, 2026-10-18: one invalid memory_type in batch 16 of 30 failed the whole initialization).
                    kept=None
                    if error.candidate_ordinal:
                        try:kept=self._validate_with_normalization(result.payload,batch,drop_invalid=True)
                        except MemoryCandidateValidationError:kept=None
                    if not kept or not kept[0]:
                        return failure(error_code,"post_response_validation",batch_ordinal,total_batches,_aggregate(results),**error.safe_context())
                    validated,normalizations=kept
                    repair_events.append({"batch_ordinal":batch_ordinal,"attempt":repair_attempts,"batch_attempt":batch_repair_attempts,"reason_code":error_code,"result":"invalid_candidates_dropped",
                                          "dropped":normalizations.get("invalid_candidates_dropped",0)})
                    for kind,count in normalizations.items():normalization_counts[kind]=normalization_counts.get(kind,0)+count
                    candidates.extend(validated)
                    validated_batches+=1
                    break
                if active_repair_event is not None:active_repair_event["result"]="succeeded"
                for kind,count in normalizations.items():normalization_counts[kind]=normalization_counts.get(kind,0)+count
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
    def _validate_with_normalization(self,payload:Any,data:dict[str,Any],drop_invalid:bool=False)->tuple[list[dict[str,Any]],dict[str,int]]:
        """Validated candidates and the normalizations made. With `drop_invalid`, a candidate with a fault of its own is
        left out (counted as invalid_candidates_dropped) instead of failing the batch; faults of the whole answer still raise."""
        if not drop_invalid:
            return self._validate_strict(payload,data)
        if not isinstance(payload,dict) or not isinstance(payload.get("candidates"),list):
            return self._validate_strict(payload,data)
        kept:list[dict[str,Any]]=[]; normalizations:dict[str,int]={"trimmed_string":0,"memory_type_format":0,"extra_fields_removed":0}; dropped=0
        for item in payload["candidates"][:MAX_MEMORY_CANDIDATES_PER_BATCH]:
            try:
                found,counts=self._validate_strict({"candidates":[item]},data)
            except MemoryCandidateValidationError:
                dropped+=1; continue
            for kind,count in counts.items():normalizations[kind]=normalizations.get(kind,0)+count
            identities={(row["memory_type"],row["subject"],row["predicate"],row["value"],row["source_span_id"]) for row in kept}
            kept.extend(row for row in found if (row["memory_type"],row["subject"],row["predicate"],row["value"],row["source_span_id"]) not in identities)
        normalizations["invalid_candidates_dropped"]=dropped+max(0,len(payload["candidates"])-MAX_MEMORY_CANDIDATES_PER_BATCH)
        return kept,normalizations
    def _validate_strict(self,payload:Any,data:dict[str,Any])->tuple[list[dict[str,Any]],dict[str,int]]:
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
            # An id copied wrongly by one character still names the one supplied span and its chapter; anything further off does not.
            source_span_id,fixed_span=_resolve_id(values["source_span_id"],sources)
            if source_span_id is None:raise MemoryCandidateValidationError("evidence_unresolvable",field="source_span_id",candidate_ordinal=candidate_ordinal)
            source=sources[source_span_id]
            chapter_id,fixed_chapter=_resolve_id(values["chapter_id"],{source["chapter_id"]})
            if chapter_id is None:raise MemoryCandidateValidationError("evidence_unresolvable",field="chapter_id",candidate_ordinal=candidate_ordinal)
            if fixed_span or fixed_chapter:normalizations["id_corrected"]=normalizations.get("id_corrected",0)+int(fixed_span)+int(fixed_chapter)
            values["source_span_id"]=source_span_id; values["chapter_id"]=chapter_id
            identity=(values["memory_type"],values["subject"],values["predicate"],values["value"],values["source_span_id"])
            if identity in seen:continue
            seen.add(identity); candidates.append(values)
        return candidates,normalizations


class MemoryDeltaEngine(MemoryInitializationEngine):
    """A separate provider contract for one append-only source revision."""
    def provenance(self)->dict[str,str]:
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":"memory-delta-v6-epithet-subjects","schema_version":"memory-delta-candidate-v2","retrieval_method_version":RETRIEVAL_METHOD_VERSION}

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
            source_span_id=_resolve_id(values["source_span_id"],sources)[0]
            chapter_id=_resolve_id(values["chapter_id"],{sources[source_span_id]["chapter_id"]})[0] if source_span_id is not None else None
            if chapter_id is None:raise ValueError("evidence_unresolvable")
            values["source_span_id"]=source_span_id; values["chapter_id"]=chapter_id
            affected=item["affected_memory_id"]
            reason=item["invalidation_reason"]
            if change_kind=="new_fact":
                if affected is not None:raise ValueError("affected_memory_invalid")
                if reason is not None:raise ValueError("invalidation_reason_invalid")
                if (values["memory_type"],values["subject"],values["predicate"]) in active_keys:raise ValueError("candidate_conflict")
            else:
                affected=_resolve_id(affected.strip(),memory)[0] if isinstance(affected,str) else None
                if affected is None:raise ValueError("affected_memory_unresolvable")
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
