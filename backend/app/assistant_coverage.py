"""Does the note of an answer only claim what the assistant really looked at? (v1.8.0, prompt assistant-p5)

The note tells the author where the assistant looked ("查过第5章与第7章正文"). The model writes it, so the server checks it
against the step records before the answer is accepted: every chapter a clause says was looked at must have been read by a
`read_chapter` call or lie inside a `search_text` range, and a clause about the draft or its check result needs the matching
tool to have run. A clause that says something was *not* looked at is left alone, and so is a clause about facts, plans,
foreshadowing or check results that does not speak of the chapter text.
"""
from __future__ import annotations

import json
import re
from typing import Any

MAX_RANGE = 1000  # a range written as 第1至99999章 is not expanded further than this

_NUM = r"(?:[0-9]+|[〇零一二两三四五六七八九十百]+)"
_SEP = r"(?:至|到|[-–—~～])"
_SEG = rf"{_NUM}(?:\s*章)?(?:\s*{_SEP}\s*(?:第\s*)?{_NUM})?"
_CHAPTERS = re.compile(rf"第\s*({_SEG}(?:\s*(?:、|和|与|及|,)\s*(?:第\s*)?{_SEG})*)\s*章")
_SEGMENT = re.compile(rf"({_NUM})(?:\s*章)?(?:\s*{_SEP}\s*(?:第\s*)?({_NUM}))?")
_DRAFT_CHAPTER = re.compile(rf"第\s*{_SEG}\s*章\s*(?:的)?\s*草稿")
# Clauses end at sentence punctuation, brackets and the list comma (but not the comma inside 第5、7章).
_CLAUSES = re.compile(r"[，,；;。.!?！？\n（()）]+|(?<![0-9〇零一二两三四五六七八九十百])、|、(?![0-9〇零一二两三四五六七八九十百])")
_NEGATIONS = ("没", "未", "不曾", "无法", "不能", "不到")
_NOT_TEXT_TOPICS = ("事实", "计划", "伏笔", "检查结果")
_TEXT_WORDS = ("正文", "原文")

_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100}


def chapter_number(text: str) -> int | None:
    """An Arabic or Chinese numeral ("12", "三十", "七十一", "一百零五") as an integer, or None when it is not one."""
    text = text.strip()
    if text.isascii():
        return int(text) if text.isdigit() else None
    total = digit = 0
    seen_unit = False
    for char in text:
        if char in _DIGITS:
            digit = _DIGITS[char]
        elif char in _UNITS:
            total += (digit or 1) * _UNITS[char]
            digit = 0
            seen_unit = True
        else:
            return None
    total += digit
    return total if total > 0 or seen_unit else None


def mentioned_chapters(clause: str) -> list[tuple[int, int]]:
    """The chapters a clause names, as (first, last) pairs: 第5章 → (5, 5); 第三至六章 → (3, 6); 第5、7章 → (5, 5), (7, 7)."""
    found: list[tuple[int, int]] = []
    for match in _CHAPTERS.finditer(clause):
        for segment in _SEGMENT.finditer(match.group(1)):
            low = chapter_number(segment.group(1))
            high = chapter_number(segment.group(2)) if segment.group(2) else low
            if low is None or high is None:
                continue
            found.append((min(low, high), min(max(low, high), min(low, high) + MAX_RANGE)))
    return found


def _clauses(note: str) -> list[str]:
    return [part.strip() for part in _CLAUSES.split(note) if part and part.strip()]


def _looked_at(steps: list[dict[str, Any]]) -> tuple[set[int], list[tuple[int, int]], set[str]]:
    """From the step records: chapters read, chapter ranges searched, and the names of the other tools that succeeded."""
    read: set[int] = set()
    searched: list[tuple[int, int]] = []
    used: set[str] = set()
    for step in steps:
        if step.get("kind") != "tool" or step.get("error_code"):
            continue
        args = json.loads(step.get("args_json") or "{}")
        name = step.get("tool_name")
        if name == "read_chapter" and isinstance(args.get("chapter_number"), int):
            read.add(args["chapter_number"])
        elif name == "search_text" and isinstance(args.get("chapter_from"), int) and isinstance(args.get("chapter_to"), int):
            searched.append((args["chapter_from"], args["chapter_to"]))
        elif name:
            used.add(name)
    return read, searched, used


def _clause_missing(clause: str, looked: tuple[set[int], list[tuple[int, int]], set[str]]) -> list[str]:
    """What one clause claims to have looked at that the steps do not show (empty when the clause is fine)."""
    read, searched, used = looked
    if any(word in clause for word in _NEGATIONS):
        return []
    missing: list[str] = []
    if "草稿" in clause:
        if "检查" in clause:
            if "get_issues" not in used:
                missing.append("本章草稿的检查结果没有读过")
        elif "read_draft" not in used:
            missing.append("本章草稿没有读过")
    text_clause = any(word in clause for word in _TEXT_WORDS)
    if text_clause or not any(word in clause for word in _NOT_TEXT_TOPICS):
        unread = sorted({chapter for low, high in mentioned_chapters(_DRAFT_CHAPTER.sub("", clause))
                         for chapter in range(low, high + 1)
                         if chapter not in read and not any(lo <= chapter <= hi for lo, hi in searched)})
        if unread:
            missing.append("第 " + "、".join(str(chapter) for chapter in unread[:10]) + " 章的正文没有读过，也不在搜索范围内")
    return missing


def note_problems(note: str | None, steps: list[dict[str, Any]]) -> list[str]:
    """What in the note says something was looked at that the steps do not show. Empty when the note is fine (or absent)."""
    if not note:
        return []
    looked = _looked_at(steps)
    problems: list[str] = []
    for clause in _clauses(note):
        missing = _clause_missing(clause, looked)
        if missing:
            problems.append(f"note 里的「{clause[:40]}」和实际不符：{'；'.join(missing)}。请去掉这一处说法，或者先补查再写")
    return problems


# A note says where the assistant looked and that it found nothing; a sentence saying what the text says is story content.
_STORY_SENTENCE = re.compile(r"写(?:着|了|到|明|的是)?\s*「|写\s*[0-9〇零一二两三四五六七八九十百]|都写|只写了|写的是|写作|不一致|说法(?:不同|相反)"
                             r"|写法不同|互相矛盾|前后矛盾|(?:没有|没|未)写(?!到)[^；;。，,]{3,}|里没有[^；;。]{1,20}的(?:设定|条目|记载|描写)"
                             r"|夹(?:有|着)|备注要求|留言")
# A refusal or a rewrite suggestion belongs in the note (prompt rule 3): a sentence that opens as one stays, even when it
# names an inconsistency; a sentence between them that retells the text goes (a1c2 safety check with p19).
_KEEP_SENTENCE = re.compile(r"^[\s，,；;]*(?:我)?(?:不能|只能|无法|做不到)|^[\s，,；;]*(?:建议|若要改|如果要改|改法|改写建议|你要求)")


def without_story(note: str | None) -> str | None:
    """The note without its clauses that say what the story's text says ("第26章写二十七岁", "正文未写明寄件人是谁",
    "计划里没有…的条目", "另：两处不一致"). Places looked at and "没有找到…" stay; a sentence that opens as a refusal or a
    suggestion stays whole. Judged as stating story content in a1c2-spent-r1-p15 and the p19 safety checks."""
    if not note:
        return note
    kept: list[str] = []
    for piece in re.split(r"(?<=[；;。])", note):
        if not piece.strip():
            continue
        if _KEEP_SENTENCE.search(piece) or not _STORY_SENTENCE.search(piece):
            kept.append(piece)
            continue
        body, end = (piece[:-1], piece[-1]) if piece[-1] in "；;。" else (piece, "")
        clauses = [clause for clause in re.split(r"[，,]", body) if clause.strip() and not _STORY_SENTENCE.search(clause)]
        clauses = [clause for clause in clauses if not re.fullmatch(r"\s*(?:另|另外)[：:]?\s*", clause)]
        if len(clauses) == 1 and re.match(r"\s*(?:若|如果|假如|只改)", clauses[0]):
            clauses = []  # "若只改第九章" with its consequence cut says nothing
        if clauses:
            kept.append("，".join(clauses) + end)
    text = "".join(kept).strip().rstrip("；;，,")
    if text and not text.endswith(("。", "！", "？")):
        text += "。"
    return text or None


def without_untrue(note: str | None, steps: list[dict[str, Any]]) -> str | None:
    """The note with every clause that `note_problems` objects to taken out, keeping the rest as written.

    Used when the one repair is spent: a wrong place in the note should not cost the author the whole answer."""
    if not note:
        return note
    looked = _looked_at(steps)
    pieces = re.split(f"({_CLAUSES.pattern})", note)
    kept: list[str] = []
    for index in range(0, len(pieces), 2):
        clause, separator = pieces[index], pieces[index + 1] if index + 1 < len(pieces) else ""
        if clause.strip() and _clause_missing(clause.strip(), looked):
            continue
        kept.append(clause + separator)
    text = "".join(kept).strip().lstrip("，,；;、。").rstrip("，,；;、")
    if text and note.rstrip().endswith("。") and not text.endswith(("。", "！", "？")):
        text += "。"
    return text or None
