"""Passage index and retrieval for long chapters (long-text phase 3).

A chapter is one SourceSpan of ~2,500 characters, so ranking whole chapters and then cutting a
500-character window around the first shared character pair often showed the model the wrong
part of the right chapter. Here source text is split into 400-600-character passages that end at
sentence ends, each keeping its offsets in the SourceSpan body, and retrieval ranks passages:

- BM25 over Chinese character 2- and 3-grams, so pairs that occur everywhere count for little;
- entity terms (Story Memory subjects, characters, aliases) shared by query and passage add weight;
- passages that state a rule ("任何", "不得", "必须"…) or that carry an entity the query names are
  preferred when they match at all, because a rule outranks a state;
- given Story Memory facts, a fact route: facts scored on their short wording, each mapped to the
  passage of its chapter it shares most with, interleaved with the directly scored passages;
- at most PER_CHAPTER passages per chapter in the result, so one chapter cannot fill every slot;
- only chapters before the checked one are searched; later text never leaks backwards.

Pure functions only: no database and no model. Integration into checks is phase 4.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Iterable

PASSAGE_METHOD_VERSION = "passage-v1-bm25-entity-facts"
PASSAGE_TARGET = 500
PASSAGE_MIN = 400
PASSAGE_MAX = 600
TAIL_SLACK = 100  # a short last passage joins the previous one if the result stays within 700
PER_CHAPTER = 2
BM25_K1 = 1.2
BM25_B = 0.75
ENTITY_WEIGHT = 2.0
RULE_WEIGHT = 1.5
MIN_ENTITY_CHARS = 2
_TOKEN = re.compile(r"[㐀-䶿一-鿿]")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*[A-Za-z]|\d+")
# A sentence ends at 。！？ (or ASCII !?, or a full stop before a space or quote) plus closing quotes,
# or at a line break.
_SENTENCE_END = re.compile(r"(?:[。！？!?]+|\.(?=[\s”’\"')\]]|$))[”’」』）)\]\"']*|\n+")
_RULE = re.compile(r"任何|不得|禁止|必须|永远|一律|不准|严禁|不许|只能|绝不|不可|规定|规矩|法令|戒律")


@dataclass(frozen=True)
class Passage:
    id: str
    span_id: str
    chapter_id: str
    chapter_number: int
    ordinal: int
    start: int
    end: int
    text: str


def sentence_ends(body: str) -> list[int]:
    ends = [match.end() for match in _SENTENCE_END.finditer(body)]
    if not ends or ends[-1] < len(body):
        ends.append(len(body))
    return ends


def split_passages(body: str, *, span_id: str, chapter_id: str, chapter_number: int,
                   target: int = PASSAGE_TARGET, minimum: int = PASSAGE_MIN, maximum: int = PASSAGE_MAX) -> list[Passage]:
    """Cut a body into passages of about `target` characters that end at sentence ends.

    A passage grows sentence by sentence and closes once it reaches `target`, or earlier if the
    next sentence would push it past `maximum`. A single sentence longer than `maximum` is cut at
    `maximum`. A short tail is merged into the previous passage when the result stays within
    `maximum` plus TAIL_SLACK.
    """
    # Sentence boundaries, with any sentence longer than `maximum` cut into `maximum`-sized pieces.
    bounds: list[int] = []
    begin = 0
    for end in sentence_ends(body):
        while end - begin > maximum:
            begin += maximum
            bounds.append(begin)
        bounds.append(end)
        begin = end
    cuts: list[int] = []
    start = 0
    last = 0
    for end in bounds:
        if end - start > maximum and last > start:
            cuts.append(last)
            start = last
        if end - start >= target:
            cuts.append(end)
            start = end
        last = end
    if not cuts or cuts[-1] < len(body):
        cuts.append(len(body))
    if len(cuts) >= 2 and cuts[-1] - cuts[-2] < minimum and cuts[-1] - (cuts[-3] if len(cuts) >= 3 else 0) <= maximum + TAIL_SLACK:
        cuts.pop(-2)
    passages: list[Passage] = []
    begin = 0
    for end in cuts:
        left, right = begin, end
        while left < right and body[left].isspace():
            left += 1
        while right > left and body[right - 1].isspace():
            right -= 1
        if right > left:
            passages.append(Passage(f"{span_id}:p{len(passages) + 1}", span_id, chapter_id, chapter_number,
                                    len(passages) + 1, left, right, body[left:right]))
        begin = end
    if len(passages) == 1:
        # A span that is a single passage keeps its own id: the passage is the span.
        passages = [replace(passages[0], id=span_id)]
    return passages


# Attribute classes. An attribute conflict often shares only the entity and the kind of attribute
# with its evidence ("紫发碧眼的萝莉" against "赤色的眼眸", "从德国来的" against "祖国法兰西"),
# so each class adds one shared term wherever any of its words occurs.
ATTRIBUTE_CLASSES = {
    "§眼": r"眼眸|眼瞳|瞳孔|眼睛|双眼|[碧蓝绿黑金银赤红紫灰褐棕]眼|[眸瞳]",
    "§发": r"头发|长发|短发|卷发|发色|发丝|[红黑白金银灰紫蓝棕褐亚麻黄粉乌]发",
    "§色": r"[红黑白金银灰紫蓝碧绿棕褐赤黄粉]色|乌黑|雪白|金黄|亚麻",
    "§龄": r"\d+岁|[一二三四五六七八九十两]+岁|年纪|岁数|年龄",
    "§国": r"祖国|国籍|国人|[德法英美日俄意中]国|法兰西|德意志|安全区|出生在|故乡",
    "§亲": r"妹妹|姐姐|哥哥|弟弟|父亲|母亲|爸爸|妈妈|叔叔|伯伯|舅舅|姑姑|表姐|表妹|表哥|表弟|学姊|学姐|学妹|学长|学弟|义父|养父|养母|亲生",
    "§级": r"[一二三四五六七八九十\d]+级|等级|排名|排行",
    "§数": r"[一二三四五六七八九十百千万亿两\d]+(?:万|千|百)?(?:人|名|元|块|米|公里|次|天|年|个)",
    "§时": r"[一二三四五六七八九十\d]+(?:年|个月|天)(?:前|后)|[一二三四五六七八九十\d]+月[一二三四五六七八九十\d]+[日号]|[一二三四五六七八九十\d]+[时点]",
    "§规": _RULE.pattern,
}
_ATTRIBUTES = [(token, re.compile(pattern)) for token, pattern in ATTRIBUTE_CLASSES.items()]


def terms(text: str) -> Counter:
    """Character 2- and 3-grams over the Chinese characters of a text, its Latin words and numbers
    (lower-cased, so English drafts are retrieved too), plus attribute-class terms."""
    chars = "".join(_TOKEN.findall(text))
    grams = Counter(chars[i:i + 2] for i in range(len(chars) - 1))
    grams.update(chars[i:i + 3] for i in range(len(chars) - 2))
    grams.update("w:" + word.casefold() for word in _WORD.findall(text))
    for token, pattern in _ATTRIBUTES:
        count = len(pattern.findall(text))
        if count:
            grams[token] = count
    return grams


@dataclass
class _Entry:
    passage: Passage
    tf: Counter
    length: int
    entities: frozenset
    rule: bool


@dataclass(frozen=True)
class FactKey:
    """A confirmed fact as a retrieval key: its words and the chapter that established it."""
    text: str
    chapter_number: int
    id: str | None = None


def _idf(n: int, df: int) -> float:
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def _bm25(wanted: set[str], tf: Counter, length: int, average: float, idf) -> float:
    norm = BM25_K1 * (1 - BM25_B + BM25_B * length / average)
    return sum(idf(t) * tf[t] * (BM25_K1 + 1) / (tf[t] + norm) for t in wanted & tf.keys())


@dataclass
class PassageIndex:
    """Passages of one work, searchable as of any chapter.

    Two routes are interleaved: passages scored directly, and Story Memory facts scored on their
    short wording and mapped to the passage of their chapter that shares the most with them. A fact
    states an attribute or a state in a few words, so it finds the passage that first described,
    say, a character's eyes, which a query on the same character but different words misses.
    """
    passages: list[Passage]
    entities: Iterable[str] = ()
    facts: Iterable[FactKey] = ()
    _entries: list[_Entry] = field(init=False, repr=False)
    _df: Counter = field(init=False, repr=False)
    _avg: float = field(init=False, repr=False)
    _entity_list: list[str] = field(init=False, repr=False)
    _facts: list[tuple[Counter, int, Passage, FactKey]] = field(init=False, repr=False)
    _fact_home: dict[str, Passage] = field(init=False, repr=False)
    _fact_df: Counter = field(init=False, repr=False)
    _fact_avg: float = field(init=False, repr=False)

    def __post_init__(self):
        self._entity_list = sorted({e.strip() for e in self.entities if len(e.strip()) >= MIN_ENTITY_CHARS}, key=len, reverse=True)
        self._entries = []
        self._df = Counter()
        for passage in self.passages:
            tf = terms(passage.text)
            self._df.update(tf.keys())
            self._entries.append(_Entry(passage, tf, sum(tf.values()) or 1,
                                        frozenset(e for e in self._entity_list if e in passage.text),
                                        bool(_RULE.search(passage.text))))
        self._avg = sum(e.length for e in self._entries) / len(self._entries) if self._entries else 1.0
        by_chapter: dict[int, list[_Entry]] = {}
        for entry in self._entries:
            by_chapter.setdefault(entry.passage.chapter_number, []).append(entry)
        self._facts, self._fact_df, self._fact_home = [], Counter(), {}
        for fact in self.facts:
            tf = terms(fact.text)
            candidates = by_chapter.get(fact.chapter_number)
            if not tf or not candidates:
                continue
            home = max(candidates, key=lambda entry: (sum(self._idf(t) for t in tf.keys() & entry.tf.keys()), -entry.passage.ordinal))
            self._facts.append((tf, sum(tf.values()), home.passage, fact))
            self._fact_df.update(tf.keys())
            if fact.id is not None:
                self._fact_home[fact.id] = home.passage
        self._fact_avg = sum(row[1] for row in self._facts) / len(self._facts) if self._facts else 1.0

    def _idf(self, term: str) -> float:
        return _idf(len(self._entries), self._df.get(term, 0))

    def _passage_ranking(self, wanted: set[str], query_entities: set[str], before_chapter: int) -> list[tuple[float, Passage]]:
        scored = []
        for entry in self._entries:
            if entry.passage.chapter_number >= before_chapter or not wanted & entry.tf.keys():
                continue
            score = _bm25(wanted, entry.tf, entry.length, self._avg, self._idf)
            common = query_entities & entry.entities
            score += ENTITY_WEIGHT * sum(self._idf(e[:2]) for e in common)
            if entry.rule and (common or score > 0):
                score += RULE_WEIGHT
            scored.append((score, -entry.passage.chapter_number, entry.passage.ordinal, entry.passage))
        scored.sort(key=lambda row: (-row[0], row[1], row[2]))
        return [(score, passage) for score, _, _, passage in scored]

    def _scored_facts(self, wanted: set[str], before_chapter: int) -> list[tuple[float, Passage, FactKey]]:
        idf = lambda term: _idf(len(self._facts), self._fact_df.get(term, 0))
        scored = [(_bm25(wanted, tf, length, self._fact_avg, idf), passage, fact) for tf, length, passage, fact in self._facts
                  if passage.chapter_number < before_chapter and wanted & tf.keys()]
        scored.sort(key=lambda row: (-row[0], -row[1].chapter_number, row[1].ordinal, row[2].text))
        return scored

    def _fact_ranking(self, wanted: set[str], before_chapter: int) -> list[tuple[float, Passage]]:
        return [(score, passage) for score, passage, _ in self._scored_facts(wanted, before_chapter)]

    def search_facts(self, query: str, *, before_chapter: int, k: int = 3) -> list[tuple[float, FactKey]]:
        """The facts whose wording best matches the query, from chapters before `before_chapter`."""
        return [(round(score, 4), fact) for score, _, fact in self._scored_facts(set(terms(query)), before_chapter)[:k]]

    def fact_passage(self, fact_id: str) -> Passage | None:
        """The passage a fact was mapped to: the one of its chapter that shares the most with it."""
        return self._fact_home.get(fact_id)

    def search(self, query: str, *, before_chapter: int, k: int = 10, per_chapter: int = PER_CHAPTER) -> list[tuple[float, Passage]]:
        """Best passages from chapters before `before_chapter`, at most `per_chapter` per chapter.

        Fact-routed and directly scored passages alternate, fact route first, duplicates skipped.
        """
        wanted = set(terms(query))
        query_entities = {e for e in self._entity_list if e in query}
        routes = [self._fact_ranking(wanted, before_chapter), self._passage_ranking(wanted, query_entities, before_chapter)]
        picked, seen, per = [], set(), Counter()
        positions = [0, 0]
        while len(picked) < k and any(positions[i] < len(routes[i]) for i in range(2)):
            for i in range(2):
                while positions[i] < len(routes[i]):
                    score, passage = routes[i][positions[i]]
                    positions[i] += 1
                    if passage.id in seen or per[passage.chapter_number] >= per_chapter:
                        continue
                    seen.add(passage.id)
                    per[passage.chapter_number] += 1
                    picked.append((round(score, 4), passage))
                    break
                if len(picked) == k:
                    break
        return picked
