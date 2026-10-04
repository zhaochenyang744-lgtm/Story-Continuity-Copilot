"""Screened continuity review: the pure parts (long-text phase 4).

Reviewing every sentence of a ~2,500-character chapter with thinking cost about 1.4 CNY and 3.5
minutes (2026-09-30 production measurement). The screened pipeline instead:

1. screens the chapter in one cheap non-thinking request: the sentences plus the Story Memory facts
   that best match each of them; the screen flags sentences worth a careful look and names the facts
   they relate to;
2. reviews only the flagged sentences with the existing trustworthy-review contract, each against the
   passages of earlier chapters that best match it (backend/app/passages.py) plus the passages the
   cited facts were taken from, with the current chapter as context. Sentences the screen saw a
   conflict or gap in get a thinking review at once; sentences it only marked worth a check go
   through a triage first, a second non-thinking screen that sees their passages and scores how
   likely a careful review would find a problem; the highest scores, at most TRIAGE_ESCALATION_CAP
   per chapter, get a thinking review.
   Thinking reviews carry one sentence each: on the lf1 dev set (2026-10-04) batches of three or
   four sentences filled the 16,000-token output cap with thinking again and again, and even in pairs
   a sentence's verdict depended on its batch-mate (one conflict judged correctly alone was missed in
   every paired run).

Drafts of at most SCREEN_MIN_CLAIMS sentences skip the screen and are reviewed whole: a screen saves
nothing there and could only miss. Evidence for a sentence of chapter N comes only from chapters
before N, facts included. This module holds no database or provider code; ContinuityEngine
(engine.py) runs the requests.
"""
from __future__ import annotations

from typing import Any

from .passages import ATTRIBUTE_CLASSES, PASSAGE_METHOD_VERSION, FactKey, Passage, PassageIndex, split_passages, terms
from .provider import SCREEN_KINDS, SCREEN_MAX_FACTS_PER_FLAG, input_budget_units_for, request_prompt_and_budget

SCREENED_RETRIEVAL_METHOD_VERSION = PASSAGE_METHOD_VERSION
SCREEN_MIN_CLAIMS = 6
SCREEN_PART_CHARS = 3000
SCREEN_FACTS_PER_SENTENCE = 3
SCREEN_MAX_FACTS = 90
# Evidence per reviewed sentence: passages in rank order up to about one chapter's worth of text. A
# long work gets about five 500-character passages; a short project's 100-character spans fit more,
# which a claim resting on a rule and a separate record needs.
VERIFY_PASSAGE_CHARS = 2500
VERIFY_MAX_PASSAGES = 8
DEEP_KINDS = ("conflict", "gap")
DEEP_MAX_CLAIMS = 1
TRIAGE_MAX_CLAIMS = 8
TRIAGE_ESCALATION_MIN_SCORE = 2
TRIAGE_ESCALATION_CAP = 4
# The triage only scores, so each sentence brings its three best passages.
TRIAGE_PASSAGES_PER_CLAIM = 3
# One evaluation of a screened review may send its larger input up to three times (high, medium and
# a non-thinking fallback), so it gets a larger token guard than the per-sentence review's 50,000.
SCREENED_RUN_TOKEN_BUDGET = 90000
VERIFY_CONTEXT_CHARS = 3000
VERIFY_CONTEXT_MARGIN = 800
NO_LATER_CHAPTER = 10 ** 9


class ScreenContractError(ValueError):
    """A screen answer the validator cannot use; the code is retried once as a repair."""


def before_chapter(claim: dict[str, Any]) -> int:
    """Evidence for a claim comes from chapters before its own; a draft comes after every chapter."""
    number = claim.get("chapter_number")
    return number if isinstance(number, int) and not isinstance(number, bool) else NO_LATER_CHAPTER


def fact_text(item: dict[str, Any]) -> str:
    return f"{item.get('subject', '')} {item.get('value', '')}"


def build_index(sources: list[dict[str, Any]], memory: list[dict[str, Any]]) -> PassageIndex:
    """Passages of every source span, Memory subjects as entities, Memory facts as the fact route."""
    passages: list[Passage] = []
    chapter_of_span: dict[str, int] = {}
    for source in sorted(sources, key=lambda row: (row["chapter_number"], str(row["id"]))):
        chapter_of_span[source["id"]] = source["chapter_number"]
        passages.extend(split_passages(str(source.get("body", "")), span_id=source["id"], chapter_id=source["chapter_id"],
                                       chapter_number=source["chapter_number"]))
    facts = [FactKey(fact_text(item), chapter_of_span[item["source_span_id"]], item["id"])
             for item in memory if item.get("source_span_id") in chapter_of_span]
    return PassageIndex(passages, [str(item.get("subject", "")) for item in memory], facts)


def memory_chapters(sources: list[dict[str, Any]], memory: list[dict[str, Any]]) -> dict[str, int]:
    """The chapter each Memory fact holds from, by its source span; facts without one are omitted."""
    chapter_of_span = {source["id"]: source["chapter_number"] for source in sources}
    return {item["id"]: chapter_of_span[item["source_span_id"]] for item in memory if item.get("source_span_id") in chapter_of_span}


def screen_parts(claims: list[dict[str, Any]], limit: int | None = None) -> list[list[dict[str, Any]]]:
    """Consecutive claims of one context, at most about `limit` characters per screen request."""
    limit = limit or SCREEN_PART_CHARS
    parts: list[list[dict[str, Any]]] = []
    size = 0
    for claim in claims:
        if parts and parts[-1][0].get("context") == claim.get("context") and size + len(claim["text"]) <= limit:
            parts[-1].append(claim)
            size += len(claim["text"])
        else:
            parts.append([claim])
            size = len(claim["text"])
    return parts


def screen_request(part: list[dict[str, Any]], index: PassageIndex, memory: list[dict[str, Any]],
                   chapters: dict[str, int]) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """One screen request with short prompt ids, and the maps back to claim and Memory ids."""
    by_id = {item["id"]: item for item in memory}
    limit = before_chapter(part[0])
    ranked: dict[str, tuple[int, int]] = {}
    for position, claim in enumerate(part):
        for rank, (_, fact) in enumerate(index.search_facts(claim["text"], before_chapter=limit, k=SCREEN_FACTS_PER_SENTENCE)):
            if fact.id in by_id:
                ranked[fact.id] = min(ranked.get(fact.id, (rank, position)), (rank, position))
    # Ordered by content, never by id: ids are random, and a different order changes the screen's answer.
    content = lambda fact_id: tuple(str(by_id[fact_id].get(key, "")) for key in ("subject", "predicate", "value"))
    chosen = sorted(ranked, key=lambda fact_id: (ranked[fact_id], chapters.get(fact_id, 0), content(fact_id)))[:SCREEN_MAX_FACTS]
    chosen.sort(key=lambda fact_id: (chapters.get(fact_id, 0), content(fact_id)))
    sentence_ids = {f"s{position + 1}": claim["id"] for position, claim in enumerate(part)}
    fact_ids = {f"f{position + 1}": fact_id for position, fact_id in enumerate(chosen)}
    request = {
        "task": "continuity_screen",
        "facts": [{"id": short, "chapter": chapters.get(fact_id), "type": by_id[fact_id].get("memory_type"),
                   "subject": by_id[fact_id].get("subject"), "predicate": by_id[fact_id].get("predicate"), "value": by_id[fact_id].get("value")}
                  for short, fact_id in fact_ids.items()],
        "sentences": [{"id": short, "text": claim["text"]} for short, claim in zip(sentence_ids, part)],
    }
    return request, sentence_ids, fact_ids


def parse_screen(payload: Any, sentence_ids: dict[str, str], fact_ids: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Flagged claim id -> {"kind", "facts": Memory ids}. Unknown fact ids are dropped, not fatal."""
    if not isinstance(payload, dict) or set(payload) != {"flags"} or not isinstance(payload["flags"], list):
        raise ScreenContractError("screen_shape_invalid")
    flags: dict[str, dict[str, Any]] = {}
    for row in payload["flags"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ScreenContractError("screen_flag_invalid")
        if row["id"] not in sentence_ids:
            raise ScreenContractError("screen_unknown_sentence")
        claim_id = sentence_ids[row["id"]]
        kind = row.get("kind") if row.get("kind") in SCREEN_KINDS else "check"
        cited = [fact_ids[value] for value in (row.get("facts") if isinstance(row.get("facts"), list) else [])
                 if isinstance(value, str) and value in fact_ids]
        entry = flags.setdefault(claim_id, {"kind": kind, "facts": []})
        entry["facts"] = list(dict.fromkeys(entry["facts"] + cited))[:SCREEN_MAX_FACTS_PER_FLAG]
    return flags


# Attribute classes that mark a concrete, checkable property (not the rule-word class).
CONTACT_CLASSES = tuple(token for token in ATTRIBUTE_CLASSES if token != "§规")


def attribute_contacts(claims: list[dict[str, Any]], memory: list[dict[str, Any]], chapters: dict[str, int]) -> set[str]:
    """Claims that name a confirmed Memory subject and state a concrete attribute of some kind.

    A safety net under the model screen, whose flags shift with the facts it is shown (lf1 dev set,
    2026-10-04: the same chapter got 4 flags in one run and 6 in another, missing two conflicts once).
    These claims go to the cheap triage, never straight to a thinking review.
    """
    found = set()
    for claim in claims:
        before = before_chapter(claim)
        subjects = {str(item.get("subject", "")).strip() for item in memory if chapters.get(item["id"], 0) < before}
        if any(len(subject) >= 2 and subject in claim["text"] for subject in subjects) and any(token in CONTACT_CLASSES for token in terms(claim["text"])):
            found.add(claim["id"])
    return found


def claim_evidence(claim: dict[str, Any], index: PassageIndex, cited_facts: list[str],
                   limit: int | None = None, chars: int | None = None) -> list[dict[str, Any]]:
    """Passages for one flagged claim: those of its cited facts first, then the best direct matches,
    at most `limit` of them and about `chars` characters in all (the first always fits)."""
    limit, chars = limit or VERIFY_MAX_PASSAGES, chars or VERIFY_PASSAGE_CHARS
    before = before_chapter(claim)
    ranked: list[Passage] = []
    for fact_id in cited_facts:
        passage = index.fact_passage(fact_id)
        if passage is not None and passage.chapter_number < before and passage not in ranked:
            ranked.append(passage)
    ranked.extend(passage for _, passage in index.search(claim["text"], before_chapter=before, k=limit) if passage not in ranked)
    picked: list[Passage] = []
    used = 0
    for passage in ranked:
        if len(picked) == limit or (picked and used + len(passage.text) > chars):
            break
        picked.append(passage)
        used += len(passage.text)
    return [{"id": passage.id, "chapter_id": passage.chapter_id, "body": passage.text, "prompt_excerpt": passage.text,
             "source_span_id": passage.span_id, "chapter_number": passage.chapter_number, "passage_start": passage.start}
            for passage in picked]


def triage_request(claims: list[dict[str, Any]], context: str) -> tuple[dict[str, Any], dict[str, str]]:
    """One triage request for claims of one context: each passage once, claims list the ones they may use."""
    passage_ids: dict[str, str] = {}
    passages = []
    for claim in claims:
        for span in claim["allowed_evidence"][:TRIAGE_PASSAGES_PER_CLAIM]:
            if span["id"] not in passage_ids:
                passage_ids[span["id"]] = f"p{len(passage_ids) + 1}"
                passages.append({"id": passage_ids[span["id"]], "chapter": span.get("chapter_number"), "text": span["prompt_excerpt"]})
    sentence_ids = {f"s{position + 1}": claim["id"] for position, claim in enumerate(claims)}
    request = {"task": "continuity_triage", "chapter": context_window(context, [claim["text"] for claim in claims]), "passages": passages,
               "sentences": [{"id": short, "text": claim["text"], "passages": [passage_ids[span["id"]] for span in claim["allowed_evidence"][:TRIAGE_PASSAGES_PER_CLAIM]]}
                             for short, claim in zip(sentence_ids, claims)]}
    return request, sentence_ids


def triage_batches(claims: list[dict[str, Any]], contexts: dict[str, str]) -> list[tuple[dict[str, Any], dict[str, str]]]:
    """Consecutive claims of one context, at most TRIAGE_MAX_CLAIMS per request and within its budget."""
    batches, current = [], []
    def fits(group):
        request, _ = triage_request(group, contexts[group[0]["context"]])
        return request_prompt_and_budget(request)[1] <= input_budget_units_for(request)
    for claim in claims:
        candidate = current + [claim]
        if current and (current[-1].get("context") != claim.get("context") or len(candidate) > TRIAGE_MAX_CLAIMS or not fits(candidate)):
            batches.append(current)
            candidate = [claim]
        current = candidate
    if current:
        batches.append(current)
    return [triage_request(group, contexts[group[0]["context"]]) for group in batches]


def parse_triage(payload: Any, sentence_ids: dict[str, str]) -> dict[str, int]:
    """Claim id -> score 0-3. Every sentence must be scored once; a missing one is rejected."""
    if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
        raise ScreenContractError("triage_shape_invalid")
    scores: dict[str, int] = {}
    for row in payload["scores"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row.get("score") not in (0, 1, 2, 3) or isinstance(row.get("score"), bool):
            raise ScreenContractError("triage_row_invalid")
        if row["id"] not in sentence_ids:
            raise ScreenContractError("triage_unknown_sentence")
        scores[sentence_ids[row["id"]]] = max(scores.get(sentence_ids[row["id"]], 0), row["score"])
    if len(scores) != len(sentence_ids):
        raise ScreenContractError("triage_sentence_missing")
    return scores


def triage_escalations(claims: list[dict[str, Any]], scores: dict[str, int]) -> set[str]:
    """Claims scored TRIAGE_ESCALATION_MIN_SCORE or more, highest first, at most TRIAGE_ESCALATION_CAP per context."""
    by_context: dict[Any, list[tuple[int, int, str]]] = {}
    for position, claim in enumerate(claims):
        score = scores.get(claim["id"], 0)
        if score >= TRIAGE_ESCALATION_MIN_SCORE:
            by_context.setdefault(claim.get("context"), []).append((-score, position, claim["id"]))
    return {claim_id for rows in by_context.values() for _, _, claim_id in sorted(rows)[:TRIAGE_ESCALATION_CAP]}


def context_window(text: str, claim_texts: list[str], limit: int = VERIFY_CONTEXT_CHARS, margin: int = VERIFY_CONTEXT_MARGIN) -> str:
    """The whole context when short, else the stretches around the claims joined by an ellipsis."""
    if len(text) <= limit:
        return text
    ranges = []
    for claim_text in claim_texts:
        start = text.find(claim_text)
        if start >= 0:
            ranges.append([max(0, start - margin), min(len(text), start + len(claim_text) + margin)])
    if not ranges:
        return text[:limit]
    ranges.sort()
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return "…".join(text[start:end] for start, end in merged)


def bind_passage_evidence(issues: list[dict[str, Any]], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn cited passage ids back into SourceSpan ids; passages of one span become one evidence item.

    Stored evidence and its chain are keyed by SourceSpan. Two cited passages of the same span are
    merged in text order, joined by an ellipsis, keeping the strongest relation and the first role.
    """
    allowed = {span["id"]: span for claim in claims for span in claim["allowed_evidence"]}
    strength = {"contradicts": 2, "supports": 1, "context": 0}
    bound = []
    for issue in issues:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in issue["evidence"]:
            span = allowed[item["span_id"]]
            grouped.setdefault(span["source_span_id"], []).append({**item, "_start": span["passage_start"]})
        evidence = []
        for span_id, items in grouped.items():
            items.sort(key=lambda row: row["_start"])
            evidence.append({
                "chapter_id": items[0]["chapter_id"], "span_id": span_id, "excerpt": "…".join(row["excerpt"] for row in items),
                "relation": max((row["relation"] for row in items), key=lambda value: strength.get(value, 0)),
                "sufficiency": "insufficient" if any(row["sufficiency"] != "sufficient" for row in items) else "sufficient",
                "related_memory_ids": list(dict.fromkeys(memory_id for row in items for memory_id in row["related_memory_ids"])),
            })
        chain = issue.get("evidence_chain")
        if isinstance(chain, list):
            roles: dict[str, str] = {}
            for item in chain:
                roles.setdefault(allowed[item["span_id"]]["source_span_id"], item["role"])
            chain = [{"span_id": span_id, "role": role} for span_id, role in roles.items()]
        bound.append({**issue, "evidence": evidence, "evidence_chain": chain})
    return bound


def retrieval_traces(claims: list[dict[str, Any]], evidence: dict[str, list[dict[str, Any]]],
                     flags: dict[str, Any], screened: bool, reviews: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every claim's screen outcome, review path and returned SourceSpan ids in rank order.

    screen is "flagged" or "passed" when the screen ran, "unscreened" for a short draft reviewed
    whole. review is "triage" (passed by the triage), "escalated" (flagged by the triage, then a
    thinking review) or "deep" (thinking review only), absent when the claim was not reviewed. A claim that was not
    reviewed (passed, or with no earlier passage) returns no spans.
    """
    def state(claim_id: str) -> str:
        return ("flagged" if claim_id in flags else "passed") if screened else "unscreened"
    rows = []
    for claim in claims:
        row = {"claim_id": claim["id"], "screen": state(claim["id"]),
               "returned_span_ids": list(dict.fromkeys(span["source_span_id"] for span in evidence.get(claim["id"], [])))}
        if (reviews or {}).get(claim["id"]):
            row["review"] = reviews[claim["id"]]
        rows.append(row)
    return rows
