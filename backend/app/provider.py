from __future__ import annotations

import json
import math
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Protocol

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
    usage_unknown = True


class ProviderFailure(Exception):
    usage_unknown = False


class ProviderDispatchDenied(ValueError):
    """The persistent quota rejected an HTTP dispatch before it was sent."""
    usage_unknown = False


_dispatch_guard: ContextVar[Callable[[], None] | None] = ContextVar("provider_dispatch_guard", default=None)


@contextmanager
def provider_dispatch_guard(guard: Callable[[], None]) -> Iterator[None]:
    token = _dispatch_guard.set(guard)
    try:
        yield
    finally:
        _dispatch_guard.reset(token)


# One continuity review run shares this state across its dispatches. Once high-effort thinking has
# run away (hit the output cap) the run's later dispatches, such as its contract repair, start at the
# fallback effort instead of spending another full output cap before falling back again.
_review_effort: ContextVar[dict[str, str] | None] = ContextVar("review_effort", default=None)
_dispatch_timeout: ContextVar[int | None] = ContextVar("dispatch_timeout", default=None)


@contextmanager
def review_effort_scope() -> Iterator[None]:
    token = _review_effort.set({})
    try:
        yield
    finally:
        _review_effort.reset(token)


class ProviderInvalidJson(Exception):
    """A parsed HTTP response whose message content did not meet the JSON contract.

    Deliberately carries only response metadata.  Raw message content must never
    escape the provider boundary or enter persistence/logging.
    """
    def __init__(self, input_tokens: int | None = None, output_tokens: int | None = None,
                 cost_cny: float | None = None, latency_ms: int | None = None,
                 finish_reason: str | None = None,
                 observed_response_input_tokens: int | None = None,
                 observed_response_output_tokens: int | None = None,
                 observed_response_cost_cny: float | None = None):
        super().__init__("provider_invalid_json")
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_cny = cost_cny
        self.latency_ms = latency_ms
        self.finish_reason = finish_reason
        self.cost_available = cost_cny is not None
        self.observed_response_input_tokens = observed_response_input_tokens
        self.observed_response_output_tokens = observed_response_output_tokens
        self.observed_response_cost_cny = observed_response_cost_cny


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
    # A later successful response can be observed after a timed-out dispatch,
    # while the total run usage remains unknown.
    observed_response_input_tokens: int | None = None
    observed_response_output_tokens: int | None = None
    observed_response_cost_cny: float | None = None


MAX_CLAIM_BASIS_CODEPOINTS = 400
MAX_ISSUE_REASONING_CODEPOINTS = 800
CONTINUITY_PROMPT_VERSION = "continuity-review-v24c-explicit-missing-link"
# The screened pipeline (long-text phase 4): a cheap non-thinking screen picks the sentences worth a
# careful look, and only those are reviewed, against passages of earlier chapters instead of whole
# spans. The review keeps every v24c rule and adds SCREENED_REVIEW_RULES.
CONTINUITY_SCREENED_PROMPT_VERSION = "continuity-review-v25f-screened-presupposed-links-bounded-knowledge"
CONTINUITY_SCREEN_PROMPT_VERSION = "continuity-screen-v1"
CONTINUITY_TRIAGE_PROMPT_VERSION = "continuity-triage-v3-presupposed-links"
SCREEN_KINDS = ("conflict", "gap", "check")
SCREEN_MAX_FACTS_PER_FLAG = 3

CONTINUITY_REVIEW_RULES = (
    "Write every author-facing explanation, reasoning, and suggested revision in the dominant language of the bound draft. Preserve proper nouns from the source.",
    f"Decide every current claim before emitting output. Return exactly issues and claim_verdicts. Include one claim_verdict for every current claim in this request, with its exact claim_span_id, verdict reviewed_issue|insufficient_evidence|no_issue, and a non-empty basis of at most {MAX_CLAIM_BASIS_CODEPOINTS} Unicode code points (characters, not tokens); give one concise decision reason without restating all the evidence. Every emitted conflict-status issue, including a compatible state_change, needs reviewed_issue verdict; an insufficient_evidence issue needs insufficient_evidence verdict. An omitted issue needs no_issue verdict with a reason. Never emit a no_conflict issue or mix the new and legacy shapes.",
    f"Every emitted issue's reasoning must be non-empty and at most {MAX_ISSUE_REASONING_CODEPOINTS} Unicode code points (characters, not tokens) after trimming surrounding whitespace. State what each cited span contributes and the decisive link or gap concisely; do not restate the full excerpts.",
    "Deciding every claim does not mean emitting an issue for every claim. First decide whether a claim actually needs review, then omit claims the supplied material supports and new events the draft itself narrates; settling a point the material leaves open is insufficient_evidence, not compatible information. If none need review, return an empty issues array and one explained no_issue claim_verdict for each claim. Never encode 'no contradiction', 'same person', 'consistent', or 'supported' as a confirmed_conflict object. The status, nature, explanation, reasoning, evidence relation and actions must express the same decision.",
    "Classify nature as confirmed_conflict only when the current story-fact claim and the complete cited evidence set cannot coexist under the same subject, scope, and time. Cite at least one direct, sufficient fact contradicting the current claim and every necessary identity, rule, or time/scope premise in the same issue. Explain what each cited span contributes to the joint proof. Evidence relation is relative to the current story-fact claim: a premise or relevant background is context, not contradicts; supports means it supports that claim and cannot be relabeled to pass the conflict contract. The sufficiency flag describes whether a cited text is complete for its own stated role; it does not make the whole set sufficient by itself. "
    "A rule that X happens only when C forbids X outside C; it does not require X whenever C holds.",
    "For every trustworthy issue, emit temporal_basis. claim_anchor and evidence_anchor must be exact substrings copied from the supplied claim and cited evidence, or null. relation must be explicit_overlap, timeless_rule, explicit_later_transition, or unknown. confirmed_conflict requires explicit_overlap with real time anchors in both texts, or timeless_rule grounded by a supplied static_canon rule. The words current narrative, current scene, or chapter order are never time anchors.",
    "A claim_anchor belongs only to the exact current_claims[id].text for the issue's claim_span_id. A time phrase in an adjacent sentence, another claim, or the overall draft cannot be copied as this claim's anchor. If the current claim has no literal time anchor, use null and unknown unless an actually supplied timeless rule applies. An evidence_anchor must likewise occur in that issue's cited excerpt. Do not manufacture anchors to justify a label.",
    "Classify nature as state_change when a prior state and a later explicit transition can both be true. Explain the before/after ordering in reasoning; do not mislabel an ordinary transition as a confirmed conflict.",
    "For character knowledge, a bounded statement that someone did not know at an earlier time says nothing by itself about what they could learn later. A later discovery may be a compatible state change. Treat recollections as claims about the recalled time, and reported speech or a character's lie as an attributed claim rather than narrator-confirmed canon. Require cited evidence tying the same person's knowledge to the same story time before declaring a confirmed conflict; otherwise use insufficient_evidence or omit a compatible claim.",
    "Chapter order gives narrative position only; it does not by itself prove story chronology. Determine same time, later time, flashback, or a bounded period only from explicit temporal language in the supplied text. Never invent a same-time link by saying only 'current narrative'. When text explicitly bounds a prior fact through an earlier period, a later changed state can coexist with it: use state_change for an explicit transition, or insufficient_evidence when the required learning, handoff, or transition is absent.",
    "A recollection, flashback, or description of an earlier date does not assert that an earlier state still holds at a later date. Different dates or hours are not overlapping merely because they concern the same object. The current draft itself is supplied written evidence: when it explicitly states the later action that changes a prior mutable state, that action is the transition, not a missing intermediate event. Do not demand a second source proving every compatible new event.",
    "Distinguish a character's utterance or belief from the narrator's asserted world facts. An explicitly identified lie, deliberately false testimony, imagined event, or quotation is not an assertion by the narrator that its content is true. Use the supplied narrative framing and explicit correction; do not report an intentional false utterance as a factual continuity conflict merely because the utterance differs from canon. Do not invent deception when the text does not mark it.",
    "Resolve identity only from supplied explicit alias statements or author-confirmed identity links. When two names are explicitly the same person, compare that person's actual state and action; the different name strings are not a holder or identity conflict. If the source supports the same state for that person, omit the issue. Do not assert that two people are the same without evidence.",
    "Classify nature as possible_conflict when a reviewable tension remains but the supplied material does not establish a direct contradiction. Explain the uncertainty or open-thread boundary and do not claim certainty. "
    "Use it for an undated contradiction that no shared time or static_canon rule proves (null anchors, relation unknown) and for a character contradicting their own earlier unmarked statement. Settle such cases once.",
    "Classify nature and status as insufficient_evidence when a claim depends on a missing handoff, learning event, outcome, authority, identity, source warrant, or other logical link. A draft assertion that a record establishes story fact P is not disproved merely because the record omits the decisive detail: explain that the attribution is unsupported and P remains unknown. Do not infer not-P, invent a timeless rule, or omit this reviewable gap as no_issue. Cite only supplied context with sufficiency insufficient, use evidence_chain role missing_link, explain exactly why judgment stops, set available_actions to [], and omit proposed_memory_change. "
    "When a claim settles an earlier or recorded point that the material leaves open (partial record, stated unknown, or a missing link), report insufficient_evidence and name the missing link: compatible is not established, and silence is not allowed. A direct contradiction, or one proved by combining supplied facts, is a conflict-status issue, not a gap.",
    "Every evidence item must copy a supplied allowed_evidence span and use only known related Memory ids. evidence_chain must contain each cited span exactly once with role prior_state, current_context, or missing_link.",
    "available_actions may contain only edit, apply_suggestion, keep_intentional, and false_positive. If apply_suggestion is present, suggested_revision must have exact before text occurring once in the bound draft and a distinct after text; otherwise suggested_revision must be null.",
    "A suggested revision must remove every contradiction asserted by that issue, including governing actions or rules, not merely change a time label or repeat the conflict. If no grounded complete correction is possible, return null and omit apply_suggestion. Never propose changing Story Memory merely to make an unsupported draft claim true.",
    "Omit proposed_memory_change unless cited sufficient evidence fully grounds it. Add and replace use controlled memory types; replace must bind a supplied Memory id. Author action is still required before canon changes.",
    "Every emitted issue must include a valid category, severity, and non-empty explanation. Assign category only after deciding the status and complete Evidence set, by the decisive fact: the direct contradicting fact, or the missing link. Ignore verbs, time anchors, and context. attribute = an intrinsic property (material, colour, size, measured count), even at a stated time; object_state = a named object's mutable condition, holder, or placement at a time; relationship = who performed, caused, delivered, authorized, or is responsible for an act, or kinship or role; an act recorded without its actor or cause is relationship; character_knowledge = what a character knows, believes, observed, or was told; timeline = order of events, including birth order; event_status = whether an event started, completed, failed, or remains open, its actor undisputed; location_action = where a character was or acted; world_rule = a global constraint only when it alone contradicts the claim; a rule that only defines ready, complete, or permitted is a premise: use the category of the state or outcome it governs.",
    "Before returning, check each object. confirmed_conflict: your cited spans alone must prove the contradiction; if the contradicting fact names the subject by an alias, code, or role, or relies on a definition or rule, cite that premise as context; cite nothing the proof does not use. It needs a proved shared time/scope. insufficient_evidence: only insufficient context showing the gap, missing_link for every evidence_chain entry, no actions, no proposed change. If your explanation finds no issue, remove the object and give the no_issue basis in claim_verdicts; a repair that drops an earlier issue must say why. A no_issue basis saying the sources do not record or confirm the point means insufficient_evidence. Do not include abandoned classifications or deliberation transcripts.",
)

CONTINUITY_DECISION_EXAMPLES = (
    {"situation": "The same object is assigned to two holders at the same stated moment.", "decision": "confirmed_conflict; explain the shared time and object scope and cite sufficient contradicting evidence."},
    {"situation": "An earlier holder is followed by an explicit later placement.", "decision": "state_change; explain the prior and later states and keep both temporally valid."},
    {"situation": "A claimed knowledge transfer has no supplied handoff event.", "decision": "insufficient_evidence; cite the missing-link context as insufficient and expose no author decision actions."},
    {"situation": "A source gives only a combined total; the draft states one part.", "decision": "insufficient_evidence: the breakdown is missing."},
    {"situation": "A source checked only some items; the draft states something about all of them.", "decision": "insufficient_evidence: the unchecked items are unknown."},
    {"situation": "A source records a request or dispatch; the draft states its outcome.", "decision": "insufficient_evidence: the outcome is missing."},
    {"situation": "Supplied facts, alone or combined, cannot hold with the claim; side details are unknown.", "decision": "A conflict-status issue citing every premise, not insufficient_evidence."},
    {"situation": "One span directly supports the full draft claim and other retrieved spans only share names or context.", "decision": "no continuity issue; emit no issue object."},
    {"situation": "A narrator recalls a lamp unlit on an earlier day; a source records it lit on a later day.", "decision": "Different dated states can coexist; omit unless a supplied fact contradicts one of them."},
    {"situation": "A source records a gate closed in the morning; the draft describes opening it that afternoon.", "decision": "The draft's opening is the transition: no conflict and no missing event; omit or report state_change."},
    {"situation": "The narrator marks a witness's testimony as deliberately false, then states the true event consistently with the source.", "decision": "A marked lie is an utterance, not canon: omit the issue."},
    {"situation": "A source says a legal name and a pen name are the same writer; source and draft give that writer the same manuscript under different names.", "decision": "Same identity and compatible possession: emit no issue."},
)

SCREENED_REVIEW_RULES = (
    "draft.body is the current chapter, or the part of it around the current claims. Judge only current_claims. The other draft sentences are context: they may narrate a transition, or tell who a pronoun or role refers to, and are never reported themselves.",
    "Each evidence span is one passage of an earlier chapter, not the whole chapter. A passage that does not mention a point neither supports nor contradicts it. When a claim treats such a point as already established earlier (an outcome, a handoff, what someone learned, what a record says), and the supplied passages leave it open, that missing link is insufficient_evidence, not no_issue.",
    "A claim also asserts what it presupposes. A modifier or attribution such as 'the box that A entrusted to her', 'the official procedure', 'the change caused by X', or 'concluded that the crop survived' asserts that handoff, source, cause or outcome; check it against the passages like a direct statement. When the passages give a different route (a request made to someone else, a second-hand or informal report, a state recorded before the deciding event, two things merely observed together) and nothing supplies the presupposed link, report insufficient_evidence naming it.",
    "A bounded ignorance and a claim about the same moment overlap. When a passage says someone did not yet know something at a stated time (their first day, a named meal or visit), and the claim says they already knew it at that same time or earlier (the same occasion, 'before arriving', 'from the start'), report a conflict-status issue; a later learning event cannot reconcile them. Likewise a lifelong or innate condition (born without a sense, never, always) holds at every later time: a claim that contradicts it is a conflict-status issue, not a missing learning event.",
)

# The triage is a second, evidence-backed screen for sentences the first screen only marked worth a
# check. It scores each sentence instead of applying the full review contract. On the lf1 dev set
# (2026-10-04) a non-thinking model given the whole contract escalated 1 sentence in 12 chapters and
# passed 3 of 12 conflicts, while a yes/no "flag when unsure" triage flagged nine in ten. The engine
# sends the highest scores, a bounded number per chapter, on to a thinking review.
CONTINUITY_TRIAGE_RULES = (
    "You compare draft sentences with passages of earlier chapters, before a careful continuity review that can only look at a few of them. Score every listed sentence once.",
    "3: a supplied passage states something that cannot be true together with the sentence (a different attribute, name, age, origin, holder, condition, place at the same time, count, date, relationship, knowledge or outcome, or an action a stated rule forbids), or the sentence asserts as settled something a passage states is unknown, unfinished or only planned.",
    "2: a passage seems to disagree with the sentence but the match is not certain, or the sentence states a specific fact about something the passages describe without supporting that fact, or relies on a handoff, learning, record, authority, cause, outcome or source they do not provide, including one built into a phrase (whose object it is, who gave it, where a method came from, what caused a change, how something turned out).",
    "1: passages describe the same people or things and agree with the sentence. 0: the passages do not bear on the sentence, or the sentence only narrates new action, speech or feeling in the current scene.",
    "A change the current chapter itself narrates before the sentence is not a disagreement; the chapter text is context for that. Judge only the listed sentences.",
    "Return exactly one JSON object with exactly one key, scores: one entry per listed sentence id with an integer score 0-3. Do not use Markdown.",
)

# A second review is an independent re-review of a key sentence the first review passed. Missing links
# were the pipeline's weakest point (lf1 dev set, 2026-10-05: insufficient-evidence recall 0.63-0.75),
# so it is asked to watch for them in particular; conflicts it finds count as well.
SECOND_REVIEW_RULES = (
    "Pay particular attention to missing links: does the claim treat as already established an outcome, a handoff, what someone learned or witnessed, an exact measurement, an identity, an authority, or what a record says, that the supplied passages leave open, only estimate, only report second-hand, or describe as planned, requested or attempted? Report that as insufficient_evidence, naming the missing link. Report a conflict when the evidence contradicts the claim. Return no issue only when the passages support the claim or it only narrates something new in the current scene.",
)

CONTINUITY_SCREEN_RULES = (
    "You screen a draft chapter before a careful continuity review. The reviewer checks only the sentences you flag, against the full text of earlier chapters; an unflagged sentence is never checked. Missing a problem is far worse than flagging a sentence that turns out fine.",
    "Flag a sentence when it states or presupposes something about the story world that earlier chapters could already have settled: a character's identity, name, age, appearance, origin or other attribute; kinship, role, rank or relationship; who holds, owns or keeps an object and its condition; where someone is or was at a stated time; what a character knows, learned, saw or was told, and from whom; whether, when, by whom and with what outcome an earlier event happened; counts, dates, durations, distances, prices or ranks; what a record, letter or report says; an action that a world rule permits, forbids or conditions.",
    "kind conflict: a supplied fact contradicts the sentence, or seems to. kind gap: the sentence settles a point that the facts leave open, unknown, partial or only planned, requested or attempted, or it asserts a handoff, learning or authority that no fact provides. kind check: a specific assertion about an earlier-established person, object, place, event, number or rule that no supplied fact covers. The facts are a partial summary of earlier chapters, not their full text, so such a sentence may still contradict earlier text: flag it.",
    "Do not flag a sentence that only narrates new action, dialogue, feeling, thought or scenery in the current scene without asserting an earlier-settled fact, a change this chapter itself narrates in an earlier sentence, or a generic remark.",
    f"In facts list the ids of the supplied facts the sentence relates to, at most {SCREEN_MAX_FACTS_PER_FLAG}, most relevant first; use [] when none applies.",
    "Return exactly one JSON object with exactly one key, flags. Flag each sentence at most once and use only supplied sentence ids. Return an empty flags array when nothing needs a careful look. Do not use Markdown.",
)

MEMORY_INITIALIZATION_RULES = (
    "Candidates are suggestions for an author, never canon. Do not claim facts that are not directly stated in the supplied source spans.",
    "Every candidate must contain memory_type, subject, predicate, value, chapter_id, and source_span_id. Copy memory_type exactly from this closed enum: static_canon, dynamic_state, event_timeline, character_knowledge, open_thread. Never put a predicate such as possession, rule, status, relationship, location, identity, affiliation, event_occurred, or knowledge into memory_type.",
    "Use exactly one supplied SourceSpan for each candidate. Do not invent chapter IDs or SourceSpan IDs. Keep subject concise and value directly grounded in its SourceSpan.",
    "predicate is a separate field from memory_type. Copy predicate exactly from controlled_predicates: identity, relationship, affiliation, location, status, rule, possession, event_occurred, or knowledge. For open_thread, still select the closest controlled predicate; open_thread remains an author-review supporting suggestion, not a core candidate.",
    "Use this general mapping: durable canon or world rule -> memory_type static_canon; current possession/location/status -> dynamic_state; an event that occurred -> event_timeline; what a character knows -> character_knowledge; unresolved setup -> open_thread. The corresponding predicate still goes in predicate, never in memory_type.",
    "Emit at most 8 candidates in this batch. Keep subject, predicate, and value within target lengths of 80, 80, and 240 Unicode characters respectively.",
    "Chunk metadata is prompt-only provenance. Never emit chunk_id; source_span_id must always be the supplied original SourceSpan ID.",
    "Prefer a small, non-duplicative set of durable facts that a later chapter could contradict: identities, relationships, physical attributes, who holds or keeps an object, where someone was at a stated time, events and their dates or outcomes, and what a character does or does not know. Skip mood, scenery, and one-off actions. Omit uncertain inferences.",
    "Every explicitly stated world rule, law, prohibition, or standing policy (\"anyone\", \"never\", \"must\", \"under no circumstances\") is a static_canon candidate with predicate rule; extract it before lower-priority facts, quoting its condition and any stated exception in value.",
    "Read the whole of every supplied span, including its last paragraphs; a fact near the end counts as much as one near the start.",
)

MEMORY_DELTA_RULES = (
    "Keep the layers separate: source_spans are current manuscript evidence, confirmed_memory is the immutable base Story Memory, and candidates are AI suggestions for author review. Candidates are never canon.",
    "Every candidate must contain exactly change_kind, affected_memory_id, memory_type, subject, predicate, value, invalidation_reason, chapter_id, and source_span_id. change_kind must be new_fact, changed_fact, or invalidated_fact. source_span_id must be one supplied current-revision SourceSpan.",
    "For new_fact, affected_memory_id and invalidation_reason must be null, and the fact must not duplicate an existing confirmed identity.",
    "For changed_fact, affected_memory_id must be exactly one supplied confirmed_memory id, invalidation_reason must be null, and the proposed fact must materially differ from that affected fact.",
    "For invalidated_fact, affected_memory_id must be exactly one supplied confirmed_memory id; memory_type, subject, predicate, and value must repeat that affected fact exactly; invalidation_reason must explain what current manuscript evidence makes it no longer valid. Do not invent an opposite fact.",
    "predicate must be exactly one value from controlled_predicates. Choose the closest semantic value; open_thread is still supporting and never a core candidate.",
    "Do not emit unsupported inferences, previous-source IDs, Author Context, author plans, alignment analysis, or a priority. Do not emit duplicate candidates or multiple candidates for one affected Memory record. The service decides core versus supporting.",
    "Emit at most 8 candidates. Prefer facts a later chapter could contradict (identities, relationships, attributes, possession, location at a stated time, events and outcomes, knowledge) and every explicitly stated world rule or prohibition as static_canon with predicate rule. Read every supplied span to its end; a span may be one part of a longer chapter.",
)

ANALYSIS_LAYER_RULES = (
    "Write every author-facing summary, explanation, answer, finding, title, and description in the dominant language of the supplied current draft. Preserve proper nouns from the source.",
    "Keep the four layers separate: planned is Author Context, confirmed is Story Memory, written is draft or SourceSpan text, and analysis is your conclusion. Never present planned content as written or confirmed evidence.",
    "Use only supplied IDs. Every citation must resolve to a supplied item, and every conclusion must stay within the supplied bounded retrieval set.",
    "Absence from the selected retrieval set is not absence from the full manuscript or project. When material was not found in the supplied selection, say only that it was not found in this selected evidence, and preserve any stated truncation or coverage limit. Never expand this into 'the source text never mentions it', 'the whole story has none', or a claim that all affected chapters were checked.",
    "Every factual clause inside an item or finding must be supported by that same item's or finding's actual citations. A Memory citation supports only its confirmed fact; it cannot also prove what the current draft says. Cite a supplied draft_claim for claims about the current draft, a SourceSpan for that prior written passage, or omit the unsupported clause. Do not inherit citations from another item, a general retrieval list, or an uncited summary.",
    "When summary_sources exists, every factual clause in summary must be supported by those summary_sources themselves. If the citation limit prevents covering a fact, omit that fact from summary and leave it in a properly cited item. A proposed change is conditional author intent, never proof that the current manuscript or confirmed Memory has already changed.",
    "Return exactly the requested JSON shape, enums, and keys. Do not use Markdown, tools, external search, or facts outside the request.",
)

MAX_TOTAL_BUDGET_UNITS = 8000
MAX_INPUT_BUDGET_UNITS = 6000
MAX_OUTPUT_BUDGET_UNITS = 2000
MEMORY_BATCH_TARGET_BUDGET_UNITS = 5800
MAX_MEMORY_CANDIDATES_PER_BATCH = 8
INPUT_BUDGET_ALGORITHM = "mixed-char-estimator-v1"
# A screen carries a whole chapter part plus its related facts, and a screened review carries the
# chapter as context plus passages for each claim. Input is cheap next to thinking output, so these
# requests get a larger estimate allowance than the original 6,000 units.
SCREEN_INPUT_BUDGET_UNITS = 16000
SCREEN_MAX_OUTPUT_TOKENS = 4000
SCREENED_REVIEW_INPUT_BUDGET_UNITS = 20000
SCREENED_REVIEW_REPAIR_INPUT_BUDGET_UNITS = 24000
TRIAGE_INPUT_BUDGET_UNITS = 20000


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
            "field_contract": {
                "memory_type": {"meaning": "fact lifecycle/evidence category", "allowed_values": ["static_canon", "dynamic_state", "event_timeline", "character_knowledge", "open_thread"]},
                "predicate": {"meaning": "semantic relationship stated by the fact", "allowed_values": request.get("controlled_predicates", list(CONTROLLED_PREDICATES))},
                "examples": [
                    {"source_meaning": "an object is currently held by someone", "memory_type": "dynamic_state", "predicate": "possession"},
                    {"source_meaning": "a world rule applies", "memory_type": "static_canon", "predicate": "rule"},
                    {"source_meaning": "a character knows or does not know something", "memory_type": "character_knowledge", "predicate": "knowledge"},
                    {"source_meaning": "an event happened", "memory_type": "event_timeline", "predicate": "event_occurred"},
                ],
            },
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
        repair_payload={"attempt":repair.get("attempt"),"global_attempt":repair.get("global_attempt"),"reason_code":repair.get("reason_code"),"instruction":"The previous response was rejected by the local schema validator. Rebuild the complete candidates array from the same supplied spans. For every candidate, copy memory_type from field_contract.memory_type.allowed_values and copy predicate separately from field_contract.predicate.allowed_values. Values such as possession and rule are predicates and are forbidden as memory_type. Obey every output key, enum, count, type, and length constraint exactly. Do not mention the previous response."}
        if repair.get("field") in {"memory_type","subject","predicate","value","chapter_id","source_span_id"}:
            repair_payload["field"]=repair["field"]
        if isinstance(repair.get("candidate_ordinal"),int) and not isinstance(repair.get("candidate_ordinal"),bool) and repair["candidate_ordinal"]>=1:
            repair_payload["candidate_ordinal"]=repair["candidate_ordinal"]
        payload["schema_repair"]=repair_payload
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def continuity_screen_prompt(request: dict[str, Any]) -> str:
    return json.dumps({
        "task": "Screen the draft sentences for a careful continuity review. Return exactly one JSON object with exactly one top-level key, flags.",
        "prompt_version": CONTINUITY_SCREEN_PROMPT_VERSION,
        "rules": list(CONTINUITY_SCREEN_RULES),
        "facts": request["facts"],
        "sentences": request["sentences"],
        "output_schema": {"flags": [{"id": "supplied sentence id", "kind": "|".join(SCREEN_KINDS), "facts": ["supplied fact id"]}]},
        **({"screen_repair": {"reason_code": request["screen_repair"].get("reason_code"),
                              "instruction": "The previous response was rejected by the local validator. Screen the same sentences again and return flags exactly in output_schema, using only supplied sentence and fact ids."}}
           if isinstance(request.get("screen_repair"), dict) else {}),
    }, ensure_ascii=False, separators=(",", ":"))


def continuity_triage_prompt(request: dict[str, Any]) -> str:
    return json.dumps({
        "task": "Score the draft sentences against the passages. Return exactly one JSON object with exactly one top-level key, scores.",
        "prompt_version": CONTINUITY_TRIAGE_PROMPT_VERSION,
        "rules": list(CONTINUITY_TRIAGE_RULES),
        "chapter": request["chapter"],
        "passages": request["passages"],
        "sentences": request["sentences"],
        "output_schema": {"scores": [{"id": "supplied sentence id", "score": "integer 0-3"}]},
        **({"triage_repair": {"reason_code": request["triage_repair"].get("reason_code"),
                              "instruction": "The previous response was rejected by the local validator. Score the same sentences again, one integer 0-3 for every supplied sentence id, exactly in output_schema."}}
           if isinstance(request.get("triage_repair"), dict) else {}),
    }, ensure_ascii=False, separators=(",", ":"))


def continuity_prompt(request: dict[str, Any]) -> str:
    screened = request.get("pipeline") == "screened"
    payload = {
            "task": "Review continuity only. Return exactly one JSON object with exactly two top-level keys, issues and claim_verdicts. Do not use Markdown or include any other top-level key.",
            "prompt_version": CONTINUITY_SCREENED_PROMPT_VERSION if screened else CONTINUITY_PROMPT_VERSION,
            "rules": list(CONTINUITY_REVIEW_RULES) + (list(SCREENED_REVIEW_RULES) if screened else []) + (list(SECOND_REVIEW_RULES) if request.get("second_review") else []),
            "decision_examples": list(CONTINUITY_DECISION_EXAMPLES), "draft": request["draft"],
            # Each span appears once per request; a claim lists the ids it may cite. Repeating the
            # excerpt under every claim put 10 distinct spans into 113 slots on one real chapter.
            "evidence_spans": list({
                span["id"]: {"id": span["id"], "chapter_id": span["chapter_id"], "excerpt": span.get("prompt_excerpt", span["body"])}
                for claim in request["claims"] for span in claim["allowed_evidence"]
            }.values()),
            "current_claims": [
                {"id": claim["id"], "text": claim["text"], "allowed_evidence": [span["id"] for span in claim["allowed_evidence"]]}
                for claim in request["claims"]
            ],
            "memory": request["memory"], "output_schema": request["output_schema"],
        }
    repair = request.get("contract_repair")
    if isinstance(repair, dict):
        payload["contract_repair"] = {
            "attempt": repair.get("attempt"),
            "reason_code": repair.get("reason_code"),
            "diagnostics": repair.get("diagnostics", []),
            "rejected_issues": repair.get("rejected_issues", []),
            "rejected_claim_verdicts": repair.get("rejected_claim_verdicts", []),
            "instruction": f"rejected_issues and rejected_claim_verdicts are the complete respective fields from the previous output. Rebuild both arrays under all original rules; correct every problem_code, not only reason_code. Every basis must be non-empty and at most {MAX_CLAIM_BASIS_CODEPOINTS} Unicode code points. Every issue reasoning must be non-empty and at most {MAX_ISSUE_REASONING_CODEPOINTS} Unicode code points. For a length error, shorten only the named basis or reasoning while preserving its evidence-based decision, nature, category, and cited evidence. An insufficient_evidence verdict requires an actual cited insufficient_evidence Issue with missing_link evidence_chain, no actions and no proposed change; basis alone is not the Issue. expected_verdict_for_returned_issues describes the mismatch, not an instruction to change a correct decision. Do not remove a source-warrant gap just because a record is silent. Remove an issue only if the supplied evidence establishes no reviewable problem, and explain why in no_issue basis. Never invent temporal or identity links; copy exact anchors or use null. Keep author text in the draft language. Suggested revisions must resolve every asserted contradiction; otherwise use null without apply_suggestion. Do not change Story Memory to make the draft true or mention the rejected response to the author.",
        }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


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
    return json.dumps({"task":"Create a compact pre-writing chapter context brief. Return exactly summary, summary_sources, and items.","rules":[*ANALYSIS_LAYER_RULES,"Return 1-3 summary_sources, 1-12 items, and 1-4 sources per item.","Cover relevant plans, confirmed facts, character state, world rules, unresolved threads, and recent written sources only when directly supported.","summary_sources must directly support every factual clause in summary. Item citations are not inherited by summary. Because summary_sources has a maximum of 3, omit lower-priority facts from summary instead of mentioning a fourth unsupported fact; detailed items may still cover it with their own citations.","Every item needs at least one citation that supports the full item text. A statement about the current saved draft must cite a supplied draft_claim; never label a SourceSpan as current draft evidence. A SourceSpan may support a recent_source item about that supplied prior chapter, but supports only its own text and chapter."],"output_limits":{"summary_sources":{"min":1,"max":3},"items":{"min":1,"max":12},"sources_per_item":{"min":1,"max":4}},"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def plan_alignment_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Compare the saved draft with each supplied story plan at the event/state-change level. Return exactly summary and items.","rules":[*ANALYSIS_LAYER_RULES,"Return exactly one item for every supplied story_plan_id.","Status must be planned_covered, planned_missing, planned_early, planned_changed, or insufficient_evidence.","Judge the planned event, transition, or outcome itself, not shared names, objects, locations, themes, prerequisites, or background setup.","Use planned_early only when written evidence explicitly shows the planned event/transition/outcome has already occurred before its planned point. Entity overlap or continued pre-event state is never planned_early.","Use planned_missing when the planned event is absent, including when the draft explicitly remains before its trigger or timing; explain that it is not yet due rather than calling it a deviation.","Use planned_covered only when written evidence explicitly completes or realizes the plan. Use planned_changed only when written evidence explicitly realizes a materially different event or outcome.","planned_covered, planned_early, and planned_changed require direct current-draft claim or SourceSpan evidence. planned_missing may cite no written evidence only when the planned point is absent from the bounded draft. Never use Author Context itself as proof that something was written."],"decision_examples":[{"plan":"暴风夜发生一次未来交接","written":"暴风雨尚未来临，当前持有人仍持有物品","status":"planned_missing","reason":"交接尚未发生且尚未到时机；共享人物和物品只是铺垫。"},{"plan":"暴风夜发生一次未来交接","written":"暴风雨尚未来临，当前持有人已经明确把物品交给接收人","status":"planned_early","reason":"同一交接事件已在计划触发条件前明确发生。"}],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def change_impact_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Analyze the likely impact of the author's explicit proposed change. Return exactly summary and items.","rules":[*ANALYSIS_LAYER_RULES,"Report only affected supplied chapters, characters, world records, Story Memory records, or plans.","target_id must be the id of one supplied chapter, character, world record, Story Memory record, or plan for that area. The current draft is not a target: cite its draft_claim ids as evidence under an affected target instead.","Every impact item requires at least one directly relevant supplied evidence citation. If there is no evidence, emit no conclusion for that target.","A target Memory record may establish that the proposed rule changes, but does not establish that source chapters are unaffected or that the current draft is compatible. Make those additional claims only with their own directly relevant citations; otherwise limit the conclusion to the identified target and the bounded review scope.","Do not write replacement prose, auto-save the proposal, or mutate draft, source, Story Memory, Author Context, or aliases."],"proposal":request["proposal"],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def story_qa_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Answer one author question only from the supplied bounded project evidence. Return exactly answer_status, answer, and findings.","rules":[*ANALYSIS_LAYER_RULES,"Respect the requested scope exactly.","A confirmed finding may cite only Story Memory; a written finding may cite only current draft claims or SourceSpan text; a planned finding may cite only Author Context.","Every non-insufficient finding needs direct evidence. If evidence is absent, return insufficient with no findings. If supplied evidence disagrees, return conflicting and include both supports and contradicts findings.","Do not turn inference into fact and do not mutate any author or manuscript data.","Write answer and finding text for the author: refer to sources by chapter, character, or fact names. Never write supplied IDs (such as mem-..., span-..., draft-claim-...) in answer or text; IDs belong only in evidence."],"question":request["question"],"scope":request["scope"],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def foreshadow_scan_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Find reviewable foreshadow candidates in supplied written evidence. Return exactly summary and candidates.","rules":[*ANALYSIS_LAYER_RULES,"Candidates are suggestions only; never create or modify an author foreshadow record.","Every candidate needs direct current draft claim or SourceSpan evidence and must label each citation with relation and evidence_kind. Use current_clue for the present draft clue, specific_prior_unresolved_clue only for a concrete earlier unresolved setup, background_only for an ordinary rule or backdrop, and explicit_payoff only for a written answer or payoff.","Use planted when the candidate is newly introduced, or when its identity as the same earlier clue is only possible.","Use developing only when written evidence explicitly establishes that the same unresolved clue, mystery, question, or deliberate setup has materially recurred, evolved, or accumulated. A developing candidate must cite at least one earlier SourceSpan as specific_prior_unresolved_clue. An ordinary world rule, background fact, shared object, or thematic resemblance is background_only and is not an earlier planted clue. Future meaning may remain uncertain after a clue is clearly developing; uncertainty about eventual payoff alone does not force planted.","Use resolved only for an explicit payoff or answer in written evidence.","Do not duplicate an existing author record or another candidate. If there is no written evidence, return an empty candidate list.","Do not cite Story Memory or Author Context as written proof."],"decision_examples":[{"earlier_written":"港规写明雾钟每晚九点响起，所有船只随后停泊","current_written":"海面第一次传来三次无人回应的钟声","earlier_evidence_kind":"background_only","current_evidence_kind":"current_clue","status":"planted","reason":"即使没有 Story Memory，普通规则仍只是背景，不能把共享意象当成已经埋设并发展的线索。"},{"earlier_written":"港规写明雾钟每晚九点响起；钟后还留下来源不明的三短一长回声","current_written":"同样的三短一长回声再次出现，并新增半枚徽记","earlier_evidence_kind":"specific_prior_unresolved_clue","current_evidence_kind":"current_clue","status":"developing","reason":"同一段虽包含规则，但被引用的是其中具体且未解的回声线索；它明确复现并增加了信息。"}],"author_records":request["author_records"],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def revision_plan_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Create one bounded revision-task suggestion for every selected continuity issue. Return exactly summary and candidates.","rules":[*ANALYSIS_LAYER_RULES,"Each candidate must reference exactly one supplied issue_id and at least one evidence id supplied for that same issue.","Write a concise editing action, not replacement fiction prose. Suggestions never edit the manuscript, resolve an Issue, change canon, or create a task without author acceptance.","Return each selected issue exactly once. Do not merge issues, invent references, duplicate titles, or add unselected work."],"source_run_id":request["source_run_id"],"selected_issues":request["selected_issues"],"bindings":request["bindings"],"layers":request["layers"],"author_records":request["author_records"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))

def author_material_comparison_prompt(request: dict[str, Any]) -> str:
    return json.dumps({"task":"Compare one author-authored material snapshot with one real manuscript SourceSpan. Return exactly assessment, explanation, and evidence.","rules":[*ANALYSIS_LAYER_RULES,"assessment must be aligned, possible_tension, plan_deviation, or insufficient_evidence.","plan_deviation applies only when the material nature is plan; a setting that the passage contradicts is possible_tension.","A plan deviation is not a factual contradiction. idea materials are not authoritative and are never supplied. hidden means not disclosed to readers; character knowledge is governed only by the separate knowledge field.","For every supported conclusion cite exactly the supplied author_material and source_span. Do not invent prose, edit records, or treat the conclusion as an author decision."],"comparison":request["comparison"],"bindings":request["bindings"],"layers":request["layers"],"retrieval":request["retrieval"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))


def request_prompt_and_budget(request: dict[str, Any]) -> tuple[str, int]:
    task=request.get("task")
    prompt = continuity_screen_prompt(request) if task == "continuity_screen" else continuity_triage_prompt(request) if task == "continuity_triage" else memory_initialization_prompt(request) if task == "memory_initialization" else memory_delta_prompt(request) if task == "memory_delta" else context_brief_prompt(request) if task == "context_brief" else plan_alignment_prompt(request) if task == "plan_alignment" else change_impact_prompt(request) if task == "change_impact" else story_qa_prompt(request) if task == "story_qa" else foreshadow_scan_prompt(request) if task == "foreshadow_scan" else revision_plan_prompt(request) if task == "revision_plan" else author_material_comparison_prompt(request) if task == "author_material_comparison" else continuity_prompt(request)
    return prompt, estimate_prompt_budget_units(prompt)


def input_budget_units_for(request: dict[str, Any], repair_budget_units: int | None = None) -> int:
    """The estimate allowance of one request: screens and screened reviews get larger ones."""
    if request.get("task") == "continuity_screen":
        return SCREEN_INPUT_BUDGET_UNITS
    if request.get("task") == "continuity_triage":
        return TRIAGE_INPUT_BUDGET_UNITS
    if request.get("task") is None and request.get("pipeline") == "screened":
        return SCREENED_REVIEW_REPAIR_INPUT_BUDGET_UNITS if "contract_repair" in request else SCREENED_REVIEW_INPUT_BUDGET_UNITS
    if request.get("task") is None and "contract_repair" in request and repair_budget_units:
        return repair_budget_units
    return MAX_INPUT_BUDGET_UNITS


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


CONTINUITY_REVIEW_THINKING_VALUES = ("disabled", "high")
# Thinking tokens count inside completion. Evidence for these limits (V9 held-out set):
# - formal run: 4/36 answers truncated at 6,000 output tokens, 3/36 paused over an 8,000 run budget;
# - diagnostic reruns: one answer filled 12,000 and later 16,000 tokens with thinking, and one repair
#   request exceeded the 6,000-unit input estimate because it carries the full rejected answer.
# A length stop is retried once at medium effort. The engine compares an evaluation's combined
# input plus output with the run budget, so 40,000 (the V8-V11 experimental budget) covers the
# truncated dispatch and its fallback. First requests keep the 6,000-unit input limit and long-form
# batching is unchanged; every non-thinking path keeps the original limits.
#
# Live smoke (2026-09-29): on some short drafts both high and medium filled the 16,000 cap (about
# 145 s) and the check failed as output_truncated. A last non-thinking dispatch, the pre-thinking
# request shape, now answers instead; it only runs where the check would otherwise have failed.
# The run budget grows to 50,000 so that three-dispatch evaluation still fits.
REVIEW_THINKING_MAX_OUTPUT_TOKENS = 16000
REVIEW_THINKING_REPAIR_INPUT_BUDGET_UNITS = 9000
REVIEW_THINKING_TRUNCATION_FALLBACK_EFFORT = "medium"
REVIEW_THINKING_EFFORTS = ("high", REVIEW_THINKING_TRUNCATION_FALLBACK_EFFORT, "disabled")
REVIEW_THINKING_RUN_TOKEN_BUDGET = 50000
# A screened (long-text) thinking review carries one sentence. On the lf1 dev set (2026-10-04) most
# single-sentence answers that finished thought for under 8,000 tokens, a runaway at high effort usually
# ran away again at medium, and runaways were about a third of the check's cost. So it is capped lower,
# falls back straight to a non-thinking answer, and does not lower the effort of the run's other reviews.
SCREENED_REVIEW_MAX_OUTPUT_TOKENS = 8000
SCREENED_REVIEW_EFFORTS = ("high", "disabled")
REVIEW_THINKING_TIMEOUT_SECONDS = 90
# Review batches of one check may be dispatched in parallel. Off (1) unless the deployment sets it, so
# dev and eval harnesses keep their sequential, reproducible dispatch order.
REVIEW_CONCURRENCY_ENV = "CONTINUITY_REVIEW_CONCURRENCY"
REVIEW_CONCURRENCY_MAX = 8


def _combined_usage(*dispatches: Any) -> tuple[int | None, int | None, float | None, int | None]:
    """Totals across truncated dispatches and their fallback; unknown stays unknown, never zero."""
    def total(field: str):
        values = [getattr(dispatch, field) for dispatch in dispatches]
        return sum(values) if all(value is not None for value in values) else None
    return total("input_tokens"), total("output_tokens"), total("cost_cny"), total("latency_ms")


class DeepSeekProvider:
    label = "deepseek"
    continuity_contract_version = "v6"
    api_format_label = "chat-completions-json-object"
    max_output_tokens = MAX_OUTPUT_BUDGET_UNITS
    timeout_seconds = 30
    max_retries = 1
    # Class defaults keep instances built without __init__ on the original behavior.
    review_thinking = "disabled"
    _request_timeout = timeout_seconds
    # Parallel review batches share one instance; the attempt counters must not lose increments.
    _counter_lock = threading.Lock()

    def __init__(self, client_factory=None):
        self.model = os.getenv("CONTINUITY_MODEL", "")
        self.base_url = os.getenv("CONTINUITY_BASE_URL", "")
        self.api_key = os.getenv("CONTINUITY_API_KEY", "")
        self.enabled = os.getenv("CONTINUITY_PROVIDER", "").lower() == "deepseek"
        # Only continuity review was evaluated with thinking; every other task keeps thinking disabled.
        self.review_thinking = os.getenv("CONTINUITY_REVIEW_THINKING", "disabled").strip().lower()
        self._request_timeout = self.timeout_seconds
        # The timeout travels with the dispatch (a context variable), not the shared instance, so a
        # concurrent non-thinking request cannot shorten a thinking dispatch's timeout.
        self._factory = client_factory or (lambda: httpx.Client(timeout=httpx.Timeout(_dispatch_timeout.get() or self.timeout_seconds)))
        self.request_attempts = 0
        self.successful_responses = 0
        self.request_cap: int | None = None

    @property
    def model_label(self):
        return self.model or "unconfigured"

    @property
    def available(self):
        return bool(self.enabled and self.model and self.base_url and self.api_key and
                    self.review_thinking in CONTINUITY_REVIEW_THINKING_VALUES)

    @property
    def continuity_run_token_budget(self) -> int | None:
        """Per-check token budget override for thinking review; None keeps the engine default."""
        return REVIEW_THINKING_RUN_TOKEN_BUDGET if self.review_thinking == "high" else None

    @property
    def continuity_batch_concurrency(self) -> int:
        """How many review batches of one check may be in flight; anything unparseable means one."""
        try:
            value = int(os.getenv(REVIEW_CONCURRENCY_ENV, "1"))
        except ValueError:
            return 1
        return min(max(value, 1), REVIEW_CONCURRENCY_MAX)

    @property
    def continuity_repair_input_budget_units(self) -> int | None:
        """Input-estimate allowance for a thinking review's single contract-repair request."""
        return REVIEW_THINKING_REPAIR_INPUT_BUDGET_UNITS if self.review_thinking == "high" else None

    def input_budget_for(self, request: dict[str, Any]) -> int:
        return input_budget_units_for(request, self.continuity_repair_input_budget_units)

    def request_body(self, request: dict[str, Any], prompt: str) -> dict[str, Any]:
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}}
        if request.get("task") is None and self.review_thinking == "high":
            cap = SCREENED_REVIEW_MAX_OUTPUT_TOKENS if request.get("pipeline") == "screened" else REVIEW_THINKING_MAX_OUTPUT_TOKENS
            return {**body, "thinking": {"type": "enabled"}, "reasoning_effort": "high", "max_tokens": cap}
        max_tokens = SCREEN_MAX_OUTPUT_TOKENS if request.get("task") in ("continuity_screen", "continuity_triage") else self.max_output_tokens
        return {**body, "thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": max_tokens}

    def _memory_initialization_prompt(self, request: dict[str, Any]) -> str:
        return memory_initialization_prompt(request)

    def _continuity_prompt(self, request: dict[str, Any]) -> str:
        return continuity_prompt(request)

    def evaluate(self, request: dict[str, Any]) -> ProviderResult:
        if not self.available:
            raise ProviderUnavailable()
        prompt, input_budget_units = request_prompt_and_budget(request)
        if input_budget_units > self.input_budget_for(request):
            raise InputBudgetExceeded()
        body = self.request_body(request, prompt)
        self._request_timeout = self._timeout_for(body)
        if body.get("reasoning_effort") != "high":
            return self._send(body)
        # Runaway thinking can fill the whole output cap. Step down one effort per length stop, down to
        # a non-thinking answer, and report the combined usage of every dispatch. Within one review run
        # the stepped-down effort sticks (see review_effort_scope).
        screened = request.get("pipeline") == "screened"
        efforts = SCREENED_REVIEW_EFFORTS if screened else REVIEW_THINKING_EFFORTS
        run_effort = None if screened else _review_effort.get()
        effort = (run_effort or {}).get("effort", "high")
        truncated: list[ProviderInvalidJson] = []
        while True:
            try:
                result = self._send(self._review_body(body, effort))
            except ProviderInvalidJson as error:
                if error.finish_reason == "length" and effort != efforts[-1]:
                    truncated.append(error)
                    effort = efforts[efforts.index(effort) + 1]
                    if run_effort is not None:
                        run_effort["effort"] = effort
                    continue
                if not truncated:
                    raise
                raise ProviderInvalidJson(*_combined_usage(*truncated, error), error.finish_reason,
                                          error.observed_response_input_tokens, error.observed_response_output_tokens,
                                          error.observed_response_cost_cny) from error
            if not truncated:
                return result
            return ProviderResult(result.payload, *_combined_usage(*truncated, result), result.finish_reason,
                                  result.observed_response_input_tokens, result.observed_response_output_tokens,
                                  result.observed_response_cost_cny)

    def _review_body(self, body: dict[str, Any], effort: str) -> dict[str, Any]:
        if effort != "disabled":
            return {**body, "reasoning_effort": effort}
        plain = {key: value for key, value in body.items() if key not in ("thinking", "reasoning_effort", "max_tokens")}
        return {**plain, "thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": self.max_output_tokens}

    def _timeout_for(self, body: dict[str, Any]) -> int:
        return REVIEW_THINKING_TIMEOUT_SECONDS if body["thinking"]["type"] == "enabled" else self.timeout_seconds

    def _send(self, body: dict[str, Any]) -> ProviderResult:
        started = time.perf_counter()
        prior_dispatch_usage_unknown = False
        for attempt in range(self.max_retries + 1):
            post_started = False
            try:
                request_cap=getattr(self,"request_cap",None)
                if request_cap is not None and self.request_attempts >= request_cap:
                    raise ProviderFailure()
                timeout = _dispatch_timeout.set(self._timeout_for(body))
                try:
                    client_context = self._factory()
                finally:
                    _dispatch_timeout.reset(timeout)
                with client_context as client:
                    guard = _dispatch_guard.get()
                    if guard is not None:
                        guard()
                    with self._counter_lock:
                        self.request_attempts += 1
                    post_started = True
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
                            None if prior_dispatch_usage_unknown else usage.get("prompt_tokens"),
                            None if prior_dispatch_usage_unknown else usage.get("completion_tokens"),
                            None if prior_dispatch_usage_unknown else usage.get("cost_cny"),
                            latency_ms, finish_reason,
                            usage.get("prompt_tokens"),usage.get("completion_tokens"),usage.get("cost_cny"),
                        ) from error
                    with self._counter_lock:
                        self.successful_responses += 1
                    return ProviderResult(
                        parsed,
                        None if prior_dispatch_usage_unknown else usage.get("prompt_tokens"),
                        None if prior_dispatch_usage_unknown else usage.get("completion_tokens"),
                        None if prior_dispatch_usage_unknown else usage.get("cost_cny"),
                        latency_ms,
                        finish_reason,
                        usage.get("prompt_tokens"),
                        usage.get("completion_tokens"),
                        usage.get("cost_cny"),
                    )
            except TIMEOUT_ERRORS as error:
                prior_dispatch_usage_unknown = True
                if attempt == self.max_retries:
                    raise ProviderTimeout() from error
            except ProviderDispatchDenied as error:
                error.usage_unknown = prior_dispatch_usage_unknown
                raise
            except HTTP_ERRORS + (AttributeError, ValueError, KeyError, TypeError) as error:
                failure = ProviderFailure()
                failure.usage_unknown = prior_dispatch_usage_unknown or post_started
                raise failure from error
