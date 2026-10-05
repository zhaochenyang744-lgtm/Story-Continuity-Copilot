"""Source-rendered context brief items.

Lexical scores only locate sources. Final prose quotes bound source text or displays
structured records, so a substring is never treated as proof of a model assertion.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Callable

_NONCONTENT = re.compile(r"[\W_]+", re.UNICODE)
_CLAUSES = re.compile(r"[，,；;。!?！？\n]+|但|却|然而")
_PAIRS = (("未", "已"), ("没有", "已经"), ("不知道", "知道"),
          ("昨天", "今天"), ("昨日", "今日"), ("此前", "此后"))


def _norm(value: str) -> str:
    return _NONCONTENT.sub("", value).casefold()


def _candidate_score(clause: str, source: str) -> float:
    """For search/ranking only, never for semantic acceptance."""
    a, b = _norm(clause), _norm(source)
    if not a or not b:
        return 0.0
    for left, right in _PAIRS:
        if (left in a and right in b and right not in a) or (right in a and left in b and left not in a):
            return 0.0
    if any(_norm(time) not in b for time in re.findall(r"\d{1,2}[:：]\d{2}", clause)):
        return 0.0
    if a in b or (len(b) >= 6 and b in a):
        return 1.0
    contiguous = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match().size / len(a)
    pairs = [a[i:i + 2] for i in range(len(a) - 1)]
    overlap = sum(pair in b for pair in pairs) / max(1, len(pairs))
    return max(contiguous, overlap)


def _source_text(kind: str, item: dict[str, Any]) -> str:
    if kind == "memory_record":
        predicate = {"does_not_know": "不知道", "knows": "知道", "holder": "持有者是 保管 持有",
                     "location": "位于", "time": "时间为", "received": "收到"}.get(item.get("predicate"), "")
        return f"{item.get('subject', '')}{predicate}{item.get('value', '')}"
    if kind == "author_context":
        return " ".join(str(item.get(key, "")) for key in ("title", "name", "content", "summary", "goal", "planned_state", "description"))
    return str(item.get("body", item.get("text", "")))


def _clauses(text: str) -> list[str]:
    result = []
    for raw in _CLAUSES.split(text):
        raw = raw.split("：")[-1].split(":")[-1].strip()
        if not raw or len(_norm(raw)) < 4:
            continue
        if raw.startswith(("所选草稿", "所选片段", "草稿证据", "本章为")):
            continue
        if re.fullmatch(r"第[一二三四五六七八九十\d]+章《[^》]+》(?:中|写到|写道)", raw):
            continue
        result.append(raw)
    return result


def locate_sources(text: str, cited: list[dict[str, Any]], maps: dict[str, dict[str, dict[str, Any]]],
                   clean: Callable[[dict[str, str]], dict[str, Any]], limit: int = 4
                   ) -> tuple[list[dict[str, Any]], int, int]:
    """Choose relevant supplied references, including missing direct ones."""
    chosen: list[dict[str, Any]] = []
    added = omitted = 0
    cited_keys = {(src["source_type"], src["source_id"]) for src in cited}
    for clause in _clauses(text):
        scored = []
        for kind in ("draft_claim", "source_span", "memory_record", "author_context"):
            for source_id, item in maps[kind].items():
                score = _candidate_score(clause, _source_text(kind, item))
                if score >= (0.28 if (kind, source_id) in cited_keys else 0.59):
                    scored.append((score, (kind, source_id) in cited_keys, kind, source_id))
        selected = sorted((x for x in scored if x[1]), reverse=True)
        if not selected and scored:
            selected = [max(scored)]
        if not selected:
            omitted += 1
            continue
        for _, was_cited, kind, source_id in selected:
            if len(chosen) >= limit:
                break
            if any(src["source_type"] == kind and src["source_id"] == source_id for src in chosen):
                continue
            chosen.append(clean({"source_type": kind, "source_id": source_id}))
            added += not was_cited
    if not chosen and cited:
        # The model wording may be unusable, but an attributed bound record is still safe.
        chosen = cited[:limit]
        omitted += 1
    return chosen, added, omitted


def _quote(text: str, budget: int) -> str:
    text = text.strip()
    return text if len(text) <= budget else text[:max(1, budget - 1)] + "…"


def render_sources(sources: list[dict[str, Any]], maps: dict[str, dict[str, dict[str, Any]]], limit: int = 600) -> str:
    """Never restate a SourceSpan's dialogue/negation as narrator-confirmed fact."""
    chunks = []
    for source in sources:
        kind, source_id = source["source_type"], source["source_id"]
        item = maps[kind][source_id]
        if kind == "draft_claim":
            prefix, content = f"当前草稿句{item['ordinal']}原文：", str(item["text"])
        elif kind == "source_span":
            prefix, content = f"第{item['chapter_number']}章所选原文：", str(item["body"])
        elif kind == "memory_record":
            subject, value = str(item["subject"]), str(item["value"])
            predicate = item["predicate"]
            if predicate == "does_not_know":
                prefix, content = f"已确认记录：{subject}不知道", value
            elif predicate == "holder":
                prefix, content = f"已确认记录：{subject}的持有者为", value
            elif predicate == "location":
                prefix, content = f"已确认记录：{subject}位于", value
            else:
                prefix, content = f"已确认记忆记录（{subject} · {predicate}）：", value
        else:
            prefix, content = "作者计划记录：", _source_text(kind, item)
        chunks.append((prefix, content))
    if not chunks:
        return ""
    overhead = sum(len(prefix) + 2 for prefix, _ in chunks) + max(0, len(chunks) - 1)
    allowance = max(20, limit - overhead)
    allocated = [min(len(content), allowance // len(chunks)) for _, content in chunks]
    spare = max(0, allowance - sum(allocated))
    for i, (_, content) in enumerate(chunks):
        extra = min(spare, len(content) - allocated[i])
        allocated[i] += extra
        spare -= extra
    return " ".join(f"{prefix}「{_quote(content, allocated[i])}」" for i, (prefix, content) in enumerate(chunks))


def section_for_sources(sources: list[dict[str, Any]], maps: dict[str, dict[str, dict[str, Any]]], proposed: str) -> str:
    if any(src["source_type"] in {"draft_claim", "source_span"} for src in sources):
        return "recent_source"
    if any(src["source_type"] == "author_context" for src in sources):
        return "related_plan"
    memory = next((maps["memory_record"][src["source_id"]] for src in sources if src["source_type"] == "memory_record"), None)
    if memory:
        return {"open_thread": "open_thread", "character_knowledge": "character_state",
                "dynamic_state": "character_state", "static_canon": "world_rule"}.get(memory.get("memory_type"), "confirmed_fact")
    return proposed
