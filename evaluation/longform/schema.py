"""Load a long-form set and resolve every authored quote to offsets.

The resolved form is what the scorer and runner use; the validator reports the problems found on
the way. Error messages name ids, fields and chapter positions, never the authored text, so the
validator can be run on a held-out set without showing its content.
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

from evaluation.longform.textutil import Chapter, locate, occurrences, parse_chapters, sentence_cover, sentences_touched, text_digest, canonical_digest

FORMAT = "longform-eval/1"
KINDS = ("dev", "formal", "import")
CATEGORIES = ("attribute", "object_state", "relationship", "character_knowledge",
              "timeline", "event_status", "location_action", "world_rule")
CLASSES = ("conflict", "insufficient_evidence")
MISSING_LINKS = ("handoff", "authorization", "provenance", "outcome", "identity",
                 "causation", "witness", "measurement", "subsequent_state", "other")
TRAP_KINDS = ("state_change", "compatible_new_detail", "rule_exception", "similar_name",
              "time_passed", "reported_belief")
DESIGNATED_BASIS = ("timeless_rule", "shared_time")
TOP_FIELDS = {"format", "set_id", "kind", "language", "authoring", "works", "targets", "selections", "subsets"}
WORK_FIELDS = {"key", "title", "file", "origin", "source_note"}
TARGET_FIELDS = {"id", "work", "chapter", "smoke", "items", "traps"}
ITEM_FIELDS = {"id", "class", "category", "missing_link", "issue_quotes", "evidence",
               "designated_regression", "designated_basis", "explanation"}
TRAP_FIELDS = {"id", "kind", "quotes", "evidence", "explanation"}
EVIDENCE_FIELDS = {"chapter", "quote"}
SELECTION_FIELDS = {"id", "work", "chapters"}
ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,40}$")
KEY = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
ISSUE_QUOTE_LEN = (6, 150)
EVIDENCE_QUOTE_LEN = (6, 200)
EXPLANATION_MAX = 300
SET_HASH_FILE = "set.sha256"
# private_test: a copyrighted work the user tests with locally. Its set must live outside the
# repository so it can never be committed or published.
# open_license: a work whose licence allows adaptation and redistribution (e.g. CC BY), credited in source_note.
ORIGINS = ("original", "public_domain", "open_license", "private_test")
REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _inside_repository(path: pathlib.Path) -> bool:
    resolved = pathlib.Path(path).resolve()
    return resolved == REPOSITORY_ROOT or REPOSITORY_ROOT in resolved.parents


@dataclass
class Located:
    """A labelled sentence range in a target chapter, plus its evidence ranges in earlier chapters."""
    id: str
    label: str  # conflict | insufficient_evidence | trap
    category: str | None
    ranges: list[tuple[int, int]]  # sentence-widened ranges in the target body
    evidence: list[tuple[int, tuple[int, int]]]  # (chapter index, range)
    designated: bool = False
    missing_link: str | None = None
    trap_kind: str | None = None


@dataclass
class Target:
    id: str
    work: str
    chapter: Chapter
    smoke: bool
    items: list[Located] = field(default_factory=list)
    traps: list[Located] = field(default_factory=list)


@dataclass
class LongformSet:
    root: pathlib.Path
    data: dict
    works: dict[str, list[Chapter]]
    targets: list[Target]
    errors: list[str]

    @property
    def kind(self) -> str:
        return self.data.get("kind", "?")

    def chapter(self, work: str, title: str) -> Chapter | None:
        return next((c for c in self.works.get(work, []) if c.title == title), None)


def set_files(root: pathlib.Path, data: dict) -> list[pathlib.Path]:
    files = [root / "labels.json"] + [root / work["file"] for work in data.get("works", []) if isinstance(work, dict) and "file" in work]
    optional = [root / "README.md", root / "authoring" / "self-review.json"]
    return files + [path for path in optional if path.exists()]


def compute_set_hash(root: pathlib.Path, data: dict) -> str:
    """One digest over the LF-normalised text of every set file, keyed by relative path."""
    return canonical_digest({path.relative_to(root).as_posix(): text_digest(path) for path in set_files(root, data)})


def load(root: pathlib.Path) -> LongformSet:
    root = pathlib.Path(root)
    errors: list[str] = []
    try:
        data = json.loads((root / "labels.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        return LongformSet(root, {}, {}, [], [f"labels.json unreadable: {type(error).__name__}"])
    if not isinstance(data, dict):
        return LongformSet(root, {}, {}, [], ["labels.json must be an object"])
    if set(data) != TOP_FIELDS:
        errors.append(f"top-level fields: missing {sorted(TOP_FIELDS - set(data))}, extra {sorted(set(data) - TOP_FIELDS)}")

    works: dict[str, list[Chapter]] = {}
    for position, work in enumerate(data.get("works") or []):
        where = f"works[{position}]"
        if not isinstance(work, dict) or set(work) != WORK_FIELDS:
            errors.append(f"{where}: fields must be exactly {sorted(WORK_FIELDS)}")
            continue
        key = work["key"]
        if not isinstance(key, str) or not KEY.match(key):
            errors.append(f"{where}: key must be lower-case ascii (a-z, 0-9, _)")
            continue
        if key in works:
            errors.append(f"{where}: duplicate work key {key}")
            continue
        if work["origin"] not in ORIGINS:
            errors.append(f"{key}: origin must be one of {ORIGINS}")
        if work["origin"] != "original" and not (isinstance(work["source_note"], str) and work["source_note"].strip()):
            errors.append(f"{key}: {work['origin']} needs source_note (title, edition, what was changed)")
        if work["origin"] == "private_test" and _inside_repository(root):
            errors.append(f"{key}: a private_test work is someone else's copyrighted text; keep its set outside the repository")
        if not isinstance(work["title"], str) or not work["title"].strip():
            errors.append(f"{key}: empty title")
        if work["file"] != f"works/{key}.md":
            errors.append(f"{key}: file must be works/{key}.md")
        try:
            works[key] = parse_chapters((root / work["file"]).read_text(encoding="utf-8"))
        except OSError:
            errors.append(f"{key}: work file missing")
        except ValueError as error:
            errors.append(f"{key}: {error}")

    seen_ids: set[str] = set()

    def claim_id(value, where: str) -> str | None:
        if not isinstance(value, str) or not ID.match(value):
            errors.append(f"{where}: id must match {ID.pattern}")
            return None
        if value in seen_ids:
            errors.append(f"{where}: duplicate id {value}")
        seen_ids.add(value)
        return value

    def evidence_ranges(entries, work: str, target_index: int, where: str) -> list[tuple[int, tuple[int, int]]]:
        resolved = []
        if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
            errors.append(f"{where}: evidence must list 1..3 entries")
            return resolved
        for number, entry in enumerate(entries):
            spot = f"{where}.evidence[{number}]"
            if not isinstance(entry, dict) or set(entry) != EVIDENCE_FIELDS:
                errors.append(f"{spot}: fields must be exactly {sorted(EVIDENCE_FIELDS)}")
                continue
            chapter = next((c for c in works.get(work, []) if c.title == entry["chapter"]), None)
            if chapter is None:
                errors.append(f"{spot}: chapter title not found in the work")
                continue
            if chapter.index >= target_index:
                errors.append(f"{spot}: evidence chapter {chapter.index} is not earlier than the target chapter {target_index}")
                continue
            quote = entry["quote"]
            if not isinstance(quote, str) or not EVIDENCE_QUOTE_LEN[0] <= len(quote) <= EVIDENCE_QUOTE_LEN[1] or "\n" in quote:
                errors.append(f"{spot}: quote must be one line of {EVIDENCE_QUOTE_LEN[0]}..{EVIDENCE_QUOTE_LEN[1]} characters")
                continue
            span = locate(chapter.body, quote)
            if span is None:
                found = occurrences(chapter.body, quote)
                errors.append(f"{spot}: quote occurs {found} times in chapter {chapter.index}; it must occur exactly once")
                continue
            resolved.append((chapter.index, span))
        return resolved

    def quote_ranges(quotes, body: str, where: str) -> list[tuple[int, int]]:
        resolved = []
        if not isinstance(quotes, list) or not 1 <= len(quotes) <= 2:
            errors.append(f"{where}: must list 1..2 quotes")
            return resolved
        for number, quote in enumerate(quotes):
            spot = f"{where}[{number}]"
            if not isinstance(quote, str) or not ISSUE_QUOTE_LEN[0] <= len(quote) <= ISSUE_QUOTE_LEN[1] or "\n" in quote:
                errors.append(f"{spot}: quote must be one line of {ISSUE_QUOTE_LEN[0]}..{ISSUE_QUOTE_LEN[1]} characters")
                continue
            span = locate(body, quote)
            if span is None:
                errors.append(f"{spot}: quote occurs {occurrences(body, quote)} times in the target chapter; it must occur exactly once")
                continue
            if sentences_touched(body, span) > 2:
                errors.append(f"{spot}: quote spans more than two sentences")
            resolved.append(sentence_cover(body, span))
        return resolved

    def explanation(value, where: str) -> None:
        if not isinstance(value, str) or not value.strip() or len(value) > EXPLANATION_MAX:
            errors.append(f"{where}: explanation must be 1..{EXPLANATION_MAX} characters")

    targets: list[Target] = []
    target_chapters: set[tuple[str, str]] = set()
    for position, raw in enumerate(data.get("targets") or []):
        where = f"targets[{position}]"
        if not isinstance(raw, dict) or set(raw) != TARGET_FIELDS:
            errors.append(f"{where}: fields must be exactly {sorted(TARGET_FIELDS)}")
            continue
        tid = claim_id(raw["id"], where) or where
        if raw["work"] not in works:
            errors.append(f"{tid}: unknown work")
            continue
        chapter = next((c for c in works[raw["work"]] if c.title == raw["chapter"]), None)
        if chapter is None:
            errors.append(f"{tid}: chapter title not found in the work")
            continue
        if (raw["work"], raw["chapter"]) in target_chapters:
            errors.append(f"{tid}: chapter is already a target")
        target_chapters.add((raw["work"], raw["chapter"]))
        if not isinstance(raw["smoke"], bool):
            errors.append(f"{tid}: smoke must be true or false")
        target = Target(tid, raw["work"], chapter, raw["smoke"] is True)
        for number, item in enumerate(raw["items"] if isinstance(raw["items"], list) else []):
            spot = f"{tid}.items[{number}]"
            if not isinstance(item, dict) or set(item) != ITEM_FIELDS:
                errors.append(f"{spot}: fields must be exactly {sorted(ITEM_FIELDS)}")
                continue
            iid = claim_id(item["id"], spot) or spot
            label = item["class"]
            if label not in CLASSES:
                errors.append(f"{iid}: class must be one of {CLASSES}")
                continue
            if label == "conflict":
                if item["category"] not in CATEGORIES:
                    errors.append(f"{iid}: conflict category must be one of {CATEGORIES}")
                if item["missing_link"] is not None:
                    errors.append(f"{iid}: missing_link must be null for a conflict")
            else:
                if item["category"] is not None:
                    errors.append(f"{iid}: category must be null for insufficient_evidence")
                if item["missing_link"] not in MISSING_LINKS:
                    errors.append(f"{iid}: missing_link must be one of {MISSING_LINKS}")
            designated = item["designated_regression"]
            if not isinstance(designated, bool):
                errors.append(f"{iid}: designated_regression must be true or false")
            basis = item["designated_basis"]
            evidence = evidence_ranges(item["evidence"], raw["work"], chapter.index, iid)
            ranges = quote_ranges(item["issue_quotes"], chapter.body, f"{iid}.issue_quotes")
            if designated is True:
                if label != "conflict":
                    errors.append(f"{iid}: a designated regression must be a conflict")
                if not isinstance(basis, dict) or set(basis) != {"type", "anchor"} or basis.get("type") not in DESIGNATED_BASIS:
                    errors.append(f"{iid}: designated_basis must be {{type: timeless_rule|shared_time, anchor}}")
                elif basis["type"] == "shared_time":
                    anchor = basis["anchor"]
                    issue_text = "".join(q for q in item["issue_quotes"] if isinstance(q, str))
                    evidence_text = "".join(e.get("quote", "") for e in item["evidence"] if isinstance(e, dict) and isinstance(e.get("quote"), str))
                    if not isinstance(anchor, str) or not anchor or anchor not in issue_text or anchor not in evidence_text:
                        errors.append(f"{iid}: shared_time anchor must appear in an issue quote and an evidence quote")
                elif not isinstance(basis["anchor"], str) or not basis["anchor"]:
                    errors.append(f"{iid}: timeless_rule anchor must name the rule's key words")
                else:
                    evidence_text = "".join(e.get("quote", "") for e in item["evidence"] if isinstance(e, dict) and isinstance(e.get("quote"), str))
                    if basis["anchor"] not in evidence_text:
                        errors.append(f"{iid}: timeless_rule anchor must appear in an evidence quote")
            elif basis is not None:
                errors.append(f"{iid}: designated_basis must be null unless designated_regression is true")
            explanation(item["explanation"], iid)
            target.items.append(Located(iid, label, item["category"] if label == "conflict" else None, ranges, evidence,
                                        designated is True, item["missing_link"] if label != "conflict" else None))
        for number, trap in enumerate(raw["traps"] if isinstance(raw["traps"], list) else []):
            spot = f"{tid}.traps[{number}]"
            if not isinstance(trap, dict) or set(trap) != TRAP_FIELDS:
                errors.append(f"{spot}: fields must be exactly {sorted(TRAP_FIELDS)}")
                continue
            pid = claim_id(trap["id"], spot) or spot
            if trap["kind"] not in TRAP_KINDS:
                errors.append(f"{pid}: kind must be one of {TRAP_KINDS}")
            evidence = evidence_ranges(trap["evidence"], raw["work"], chapter.index, pid)
            ranges = quote_ranges(trap["quotes"], chapter.body, f"{pid}.quotes")
            explanation(trap["explanation"], pid)
            target.traps.append(Located(pid, "trap", None, ranges, evidence, trap_kind=trap["kind"]))
        if not isinstance(raw["items"], list) or not isinstance(raw["traps"], list):
            errors.append(f"{tid}: items and traps must be lists (use [] for none)")
        labelled = [(entry.id, span) for entry in target.items + target.traps for span in entry.ranges]
        for left in range(len(labelled)):
            for right in range(left + 1, len(labelled)):
                a, b = labelled[left], labelled[right]
                if a[0] != b[0] and a[1][0] < b[1][1] and b[1][0] < a[1][1]:
                    errors.append(f"{tid}: {a[0]} and {b[0]} share a sentence; every labelled point needs its own sentences")
        targets.append(target)
    return LongformSet(root, data, works, targets, errors)
