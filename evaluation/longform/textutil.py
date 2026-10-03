"""Text primitives shared by the long-form validator, scorer and runner.

Every position is a code-point offset into a chapter body: the text between one level-one
heading and the next, with CRLF folded to LF and surrounding whitespace stripped. Authors never
write offsets; they write exact quotes, and `locate` turns a quote into a range only when it occurs
exactly once.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from dataclasses import dataclass

HEADING = re.compile(r"^# ([^\n]+)$", re.M)
CHAPTER_TITLE = re.compile(r"^第[零〇一二三四五六七八九十百千两\d]+章(?:\s+\S.*)?$")
# A sentence ends at 。！？ (or ASCII !?) plus any closing quotes/brackets that follow it. The
# product splits claims after 。！？ without the closing quote; overlap matching makes the two agree.
SENTENCE = re.compile(r"[^。！？!?\n]*(?:[。！？!?]+[”’」』）)\]]*|$)", re.M)
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATIN = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class Chapter:
    index: int  # 1-based position in the work
    title: str
    body: str

    @property
    def length(self) -> int:
        return char_count(self.body)


def normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def char_count(text: str) -> int:
    """Length as an author counts 字: every code point except whitespace."""
    return len(re.sub(r"\s", "", text))


def parse_chapters(source: str) -> list[Chapter]:
    """Split a Markdown work into chapters; raises ValueError naming the problem, never the text."""
    source = normalise(source).lstrip("﻿")
    matches = list(HEADING.finditer(source))
    if not matches:
        raise ValueError("no level-one chapter heading")
    if source[:matches[0].start()].strip():
        raise ValueError("text before the first chapter heading")
    chapters: list[Chapter] = []
    seen: set[str] = set()
    for position, match in enumerate(matches):
        title = match[1].strip()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(source)
        body = source[match.end():end].strip()
        if title in seen:
            raise ValueError(f"duplicate chapter title at chapter {position + 1}")
        seen.add(title)
        if re.search(r"^#{1,6}\s", body, re.M):
            raise ValueError(f"chapter {position + 1}: extra Markdown heading inside the body")
        chapters.append(Chapter(position + 1, title, body))
    return chapters


def sentences(body: str) -> list[tuple[int, int]]:
    """Ranges of the non-empty sentences in a body, in order."""
    ranges = []
    for match in SENTENCE.finditer(body):
        text = match.group()
        if not text.strip():
            continue
        start = match.start() + (len(text) - len(text.lstrip()))
        end = match.end() - (len(text) - len(text.rstrip()))
        ranges.append((start, end))
    return ranges


def locate(body: str, quote: str) -> tuple[int, int] | None:
    """The quote's range when it occurs exactly once in the body, else None."""
    first = body.find(quote)
    if first < 0 or body.find(quote, first + 1) >= 0:
        return None
    return first, first + len(quote)


def occurrences(body: str, quote: str) -> int:
    count, start = 0, 0
    while quote and (found := body.find(quote, start)) >= 0:
        count, start = count + 1, found + 1
    return count


def sentence_cover(body: str, span: tuple[int, int]) -> tuple[int, int]:
    """Widen a range to the whole sentence(s) it touches, so a label and a claim compare by sentence."""
    start, end = span
    for s_start, s_end in sentences(body):
        if s_start < span[1] and span[0] < s_end:
            start, end = min(start, s_start), max(end, s_end)
    return start, end


def sentences_touched(body: str, span: tuple[int, int]) -> int:
    return sum(1 for s_start, s_end in sentences(body) if s_start < span[1] and span[0] < s_end)


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def cjk_ratio(text: str) -> float:
    """Share of CJK characters among CJK plus Latin letters; digits and punctuation do not count."""
    cjk, latin = len(CJK.findall(text)), len(LATIN.findall(text))
    return cjk / (cjk + latin) if cjk + latin else 0.0


def text_digest(path: pathlib.Path) -> str:
    """SHA-256 of a text file after LF normalisation, so a CRLF checkout does not break a freeze."""
    return hashlib.sha256(normalise(path.read_text(encoding="utf-8")).encode("utf-8")).hexdigest()


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
