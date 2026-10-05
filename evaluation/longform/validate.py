"""Validate a long-form evaluation set (format longform-eval/1).

    python -m evaluation.longform.validate <set_dir> [--against <other_set_dir> ...]
                                                     [--freeze | --require-frozen] [--structure-only]

Checks structure, the chapter and length rules, that every quote resolves exactly once, that all
evidence comes from earlier chapters, the per-kind counts, and (with --against) that two sets share
no work and no 20-character passage. Output is counts and ids only, never authored text, so it is
safe to run on a held-out set. It does not judge whether a label is semantically right.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from evaluation.longform.schema import (CATEGORIES, FORMAT, KINDS, SET_HASH_FILE, SELECTION_FIELDS, LongformSet,
                                        compute_set_hash, load)
from evaluation.longform.textutil import char_count, cjk_ratio, sentence_cover, sentences

# Names already used by the product seed work and earlier sets; a new work must not reuse them.
BANNED_NAMES = ("灰港", "纸月", "零号花园", "雾港", "白塔", "灰港回声")
SHINGLE = 20
SELF_REVIEW = "authoring/self-review.json"
# Prose checks (added 2026-10-04 after a template-generated delivery passed every other rule:
# about 68% of its sentences repeated across chapters and works). Real prose sits near zero.
MIN_REPEAT_SENTENCE_CHARS = 8
MAX_REPEATED_SENTENCE_SHARE = 0.03
MAX_REUSED_TEXT_SHARE = 0.05
MAX_ISOLATED_POINT_SHARE = 0.25
# Echo check (added 2026-10-04 after the second dev delivery): an issue sentence that repeats its
# evidence's wording makes keyword retrieval look better than it will be on real manuscripts. A
# pair "echoes" when the two sentences share a run of ECHO_RUN characters (punctuation dropped,
# a designated shared_time anchor removed first). Gated for the formal set; reported for all.
ECHO_RUN = 8
MAX_ECHO_PAIR_SHARE = 0.15
ISOLATED_POINT_MARGIN = 0.15

CHAPTER_RULES = {
    # (min chars, max chars) for any chapter, and for target chapters, plus minimum sentences per target.
    "dev": {"any": (800, 3500), "target": (2000, 3200), "target_sentences": 15, "chapters": (8, 14)},
    "formal": {"any": (800, 3500), "target": (2000, 3200), "target_sentences": 15, "chapters": (8, 14)},
    "import": {"any": (800, 4000), "target": (2000, 3200), "target_sentences": 15, "chapters": (100, 150)},
}
MIN_CJK_RATIO = 0.95
MIN_TARGET_INDEX = 3
MAX_ITEMS_PER_TARGET = 3


def distance(target, entry) -> int:
    """How far back the nearest evidence sits, in chapters."""
    return min((target.chapter.index - index for index, _ in entry.evidence), default=0)


def summarise(lf: LongformSet) -> dict:
    items = [(t, i) for t in lf.targets for i in t.items]
    traps = [p for t in lf.targets for p in t.traps]
    conflicts = [i for _, i in items if i.label == "conflict"]
    gaps = [i for _, i in items if i.label == "insufficient_evidence"]
    distances = [distance(t, i) for t, i in items]
    return {
        "set_id": lf.data.get("set_id"), "kind": lf.kind,
        "works": len(lf.works),
        "chapters": sum(len(chapters) for chapters in lf.works.values()),
        "total_chars": sum(c.length for chapters in lf.works.values() for c in chapters),
        "targets": len(lf.targets),
        "clean_targets": sum(1 for t in lf.targets if not t.items),
        "smoke_targets": sum(1 for t in lf.targets if t.smoke),
        "target_chars": {"min": min((t.chapter.length for t in lf.targets), default=0),
                         "max": max((t.chapter.length for t in lf.targets), default=0)},
        "target_sentences_min": min((len(sentences(t.chapter.body)) for t in lf.targets), default=0),
        "conflicts": len(conflicts),
        "conflict_categories": dict(collections.Counter(i.category for i in conflicts)),
        "insufficient_evidence": len(gaps),
        "missing_links": dict(collections.Counter(i.missing_link for i in gaps)),
        "traps": len(traps),
        "trap_kinds": dict(collections.Counter(p.trap_kind for p in traps)),
        "designated": [i.id for _, i in items if i.designated],
        "evidence_distance": {"1-2": sum(d < 3 for d in distances), "3-9": sum(3 <= d < 10 for d in distances),
                              "10-49": sum(10 <= d < 50 for d in distances), "50+": sum(d >= 50 for d in distances)},
        "selections": sorted(len(s.get("chapters") or []) for s in lf.data.get("selections") or [] if isinstance(s, dict)),
    }


def check_profile(lf: LongformSet, summary: dict, errors: list[str]) -> None:
    kind = lf.kind
    require = lambda ok, message: ok or errors.append(message)
    items = [(t, i) for t in lf.targets for i in t.items]
    conflicts = summary["conflict_categories"]
    long_range = sum(1 for t, i in items if distance(t, i) >= 3)
    if kind in ("dev", "formal"):
        require(long_range >= 0.4 * len(items), f"at least 40% of items need evidence 3+ chapters back (have {long_range}/{len(items)})")
    if kind == "dev":
        require(summary["works"] == 3, "dev: expected 3 works")
        require(12 <= summary["targets"] <= 18, "dev: expected 12..18 targets")
        require(summary["conflicts"] >= 12, "dev: expected at least 12 conflicts")
        require(set(conflicts) == set(CATEGORIES), "dev: conflicts must cover all 8 categories")
        require(summary["insufficient_evidence"] >= 8, "dev: expected at least 8 insufficient_evidence items")
        require(len(summary["missing_links"]) >= 3, "dev: insufficient_evidence must use at least 3 missing_link types")
        require(summary["traps"] >= 8 and len(summary["trap_kinds"]) >= 4, "dev: expected at least 8 traps of at least 4 kinds")
        require(summary["clean_targets"] >= 3, "dev: expected at least 3 clean targets (no items)")
        require(len(summary["designated"]) >= 1, "dev: expected at least 1 designated regression")
        require(5 in summary["selections"] and 8 in summary["selections"], "dev: expected a 5-chapter and an 8-chapter selection")
        smoke = [t for t in lf.targets if t.smoke]
        require(3 <= len(smoke) <= 4, "dev: expected 3..4 smoke targets")
        smoke_labels = {i.label for t in smoke for i in t.items}
        require(smoke_labels == {"conflict", "insufficient_evidence"}, "dev: smoke targets must include a conflict and an insufficient_evidence item")
    elif kind == "formal":
        require(summary["works"] == 4, "formal: expected 4 works")
        require(24 <= summary["targets"] <= 32, "formal: expected 24..32 targets")
        require(summary["conflicts"] == 24, "formal: expected exactly 24 conflicts")
        require(set(conflicts) == set(CATEGORIES) and min(conflicts.values(), default=0) >= 2, "formal: every category needs at least 2 conflicts")
        require(summary["insufficient_evidence"] == 12, "formal: expected exactly 12 insufficient_evidence items")
        require(len(summary["missing_links"]) >= 4, "formal: insufficient_evidence must use at least 4 missing_link types")
        require(summary["traps"] >= 16 and len(summary["trap_kinds"]) >= 4, "formal: expected at least 16 traps of at least 4 kinds")
        require(summary["clean_targets"] >= 6, "formal: expected at least 6 clean targets (no items)")
        designated = [i for _, i in items if i.designated]
        require(len(designated) == 3, "formal: expected exactly 3 designated regressions")
        bases = {item.get("designated_basis", {}).get("type") for t in lf.data.get("targets") or [] if isinstance(t, dict)
                 for item in t.get("items") or [] if isinstance(item, dict) and item.get("designated_regression") is True
                 and isinstance(item.get("designated_basis"), dict)}
        require(bases == {"timeless_rule", "shared_time"}, "formal: designated regressions must use both timeless_rule and shared_time")
        require(summary["selections"].count(5) == 2 and summary["selections"].count(8) == 1 and len(summary["selections"]) == 3,
                "formal: expected exactly two 5-chapter selections and one 8-chapter selection")
        require(len({s.get("work") for s in lf.data.get("selections") or [] if isinstance(s, dict)}) >= 2, "formal: selections must come from at least 2 works")
        require(summary["smoke_targets"] == 0, "formal: smoke must be false everywhere")
    elif kind == "import":
        require(summary["works"] == 1, "import: expected 1 work")
        require(280_000 <= summary["total_chars"] <= 360_000, "import: expected 280,000..360,000 characters")
        require(18 <= len(items) <= 22, "import: expected 18..22 items")
        require(summary["conflicts"] >= 14 and len(conflicts) >= 6, "import: expected at least 14 conflicts over at least 6 categories")
        require(summary["insufficient_evidence"] >= 4, "import: expected at least 4 insufficient_evidence items")
        require(summary["traps"] >= 8, "import: expected at least 8 traps")
        require(summary["clean_targets"] >= 10, "import: expected at least 10 clean targets")
        require(sum(1 for t, i in items if distance(t, i) >= 10) >= 10, "import: at least 10 items need evidence 10+ chapters back")
        require(sum(1 for t, i in items if distance(t, i) >= 50) >= 3, "import: at least 3 items need evidence 50+ chapters back")
        require(sum(1 for t, i in items if t.chapter.index <= 20) >= 3, "import: at least 3 items must sit in chapters 1..20 (the quick slice)")
        require(summary["smoke_targets"] == 0, "import: smoke must be false everywhere")


def validate(lf: LongformSet, structure_only: bool = False) -> tuple[list[str], dict]:
    errors = list(lf.errors)
    data = lf.data
    if not data:
        return errors, {}
    if data.get("format") != FORMAT:
        errors.append(f"format must be {FORMAT}")
    if data.get("kind") not in KINDS:
        errors.append(f"kind must be one of {KINDS}")
    if data.get("language") != "zh":
        errors.append("language must be zh")
    if not isinstance(data.get("set_id"), str) or not data["set_id"].strip():
        errors.append("set_id must be a non-empty string")
    authoring = data.get("authoring")
    if not isinstance(authoring, dict) or not {"model", "date"} <= set(authoring):
        errors.append("authoring must record at least model and date")
    rules = CHAPTER_RULES.get(lf.kind, CHAPTER_RULES["dev"])
    target_keys = {(t.work, t.chapter.title) for t in lf.targets}
    for key, chapters in lf.works.items():
        if not structure_only and not rules["chapters"][0] <= len(chapters) <= rules["chapters"][1]:
            errors.append(f"{key}: expected {rules['chapters'][0]}..{rules['chapters'][1]} chapters, got {len(chapters)}")
        text = "".join(c.title + c.body for c in chapters)
        if cjk_ratio(text) < MIN_CJK_RATIO:
            errors.append(f"{key}: the work must be written in Chinese (CJK ratio {cjk_ratio(text):.2f})")
        if any(name in text for name in BANNED_NAMES):
            errors.append(f"{key}: reuses a name from the product seed work or an earlier set")
        for chapter in chapters:
            low, high = rules["target"] if (key, chapter.title) in target_keys else rules["any"]
            if not structure_only and not low <= chapter.length <= high:
                errors.append(f"{key}: chapter {chapter.index} has {chapter.length} characters, expected {low}..{high}")
    work_titles = [w.get("title") for w in data.get("works") or [] if isinstance(w, dict)]
    for title in work_titles:
        if isinstance(title, str) and any(name in title for name in BANNED_NAMES):
            errors.append("a work title reuses a banned name")
    for target in lf.targets:
        if target.chapter.index < MIN_TARGET_INDEX:
            errors.append(f"{target.id}: target chapter {target.chapter.index} needs at least {MIN_TARGET_INDEX - 1} earlier chapters")
        if not structure_only and len(sentences(target.chapter.body)) < rules["target_sentences"]:
            errors.append(f"{target.id}: target chapter needs at least {rules['target_sentences']} sentences")
        if len(target.items) > MAX_ITEMS_PER_TARGET:
            errors.append(f"{target.id}: at most {MAX_ITEMS_PER_TARGET} items per target")
    targets_by_chapter = {(t.work, t.chapter.title): t.id for t in lf.targets}
    selection_ids = set()
    for position, selection in enumerate(data.get("selections") or []):
        where = f"selections[{position}]"
        if not isinstance(selection, dict) or set(selection) != SELECTION_FIELDS:
            errors.append(f"{where}: fields must be exactly {sorted(SELECTION_FIELDS)}")
            continue
        if selection["id"] in selection_ids or selection["id"] in targets_by_chapter.values():
            errors.append(f"{where}: duplicate id")
        selection_ids.add(selection["id"])
        chapters = selection["chapters"]
        if not isinstance(chapters, list) or not 2 <= len(chapters) <= 8 or len(set(chapters)) != len(chapters):
            errors.append(f"{where}: chapters must list 2..8 distinct titles")
            continue
        missing = [n for n, title in enumerate(chapters) if (selection["work"], title) not in targets_by_chapter]
        if missing:
            errors.append(f"{where}: every selected chapter must be a target of that work (positions {missing})")
    subsets = data.get("subsets")
    if not isinstance(subsets, dict):
        errors.append("subsets must be an object (use {} for none)")
    else:
        known = {t.id for t in lf.targets}
        for name, ids in subsets.items():
            if not isinstance(ids, list) or not ids or any(i not in known for i in ids):
                errors.append(f"subsets.{name}: must list known target ids")
    summary = summarise(lf)
    if not structure_only:
        check_profile(lf, summary, errors)
        check_self_review(lf, errors)
        summary["prose"] = check_prose(lf, errors)
        summary["echo"] = check_echo(lf, errors)
    return errors, summary


def _stripped_shingles(body: str) -> set[str]:
    text = "".join(body.split())
    return {text[i:i + SHINGLE] for i in range(max(len(text) - SHINGLE + 1, 0))}


def _reused_share(body: str, elsewhere: set[str]) -> tuple[int, int]:
    """Characters of a body covered by a 20-character passage that also occurs elsewhere."""
    text = "".join(body.split())
    covered = bytearray(len(text))
    for i in range(max(len(text) - SHINGLE + 1, 0)):
        if text[i:i + SHINGLE] in elsewhere:
            covered[i:i + SHINGLE] = b"\x01" * SHINGLE
    return sum(covered), len(text)


def _plain(text: str) -> str:
    return re.sub(r"[\W_]", "", text)


def _shares_run(a: str, b: str, run: int) -> bool:
    return any(a[i:i + run] in b for i in range(max(len(a) - run + 1, 0)))


def check_echo(lf: LongformSet, errors: list[str]) -> dict:
    """How often an issue sentence repeats the wording of its evidence sentence."""
    anchors = {item.get("id"): (item.get("designated_basis") or {}).get("anchor") or ""
               for target in lf.data.get("targets") or [] if isinstance(target, dict)
               for item in target.get("items") or [] if isinstance(item, dict)}
    pairs = echoed = 0
    for target in lf.targets:
        chapters = {c.index: c for c in lf.works[target.work]}
        for point in target.items:
            anchor = _plain(anchors.get(point.id) or "")
            issue = _plain("".join(target.chapter.body[s:e] for s, e in point.ranges))
            for index, span in point.evidence:
                body = chapters[index].body
                start, end = sentence_cover(body, span)
                evidence = _plain(body[start:end])
                if anchor:
                    issue_cut, evidence = issue.replace(anchor, "|"), evidence.replace(anchor, "|")
                else:
                    issue_cut = issue
                pairs += 1
                echoed += _shares_run(issue_cut, evidence, ECHO_RUN)
    share = echoed / pairs if pairs else 0.0
    if lf.kind == "formal" and share > MAX_ECHO_PAIR_SHARE:
        errors.append(f"{echoed} of {pairs} issue/evidence sentence pairs share an {ECHO_RUN}-character run of wording "
                      f"(max {MAX_ECHO_PAIR_SHARE:.0%}); restate the fact in the issue sentence in different words")
    return {"pairs": pairs, "echoed_pairs": echoed, "echo_pair_share": round(share, 4)}


def check_prose(lf: LongformSet, errors: list[str]) -> dict:
    """Catch generated or templated text, which makes retrieval and screening look easier than real prose.

    Per work: few repeated sentences, little text reused between its chapters. Across the works of
    one set: no shared 20-character passage. Labelled points: most must sit inside ordinary
    paragraphs rather than stand alone as one-sentence paragraphs.
    """
    report: dict = {"works": {}}
    owners: dict[str, set[str]] = collections.defaultdict(set)
    for key, chapters in lf.works.items():
        counts = collections.Counter(
            "".join(c.body[s:e].split()) for c in chapters for s, e in sentences(c.body)
            if char_count(c.body[s:e]) >= MIN_REPEAT_SENTENCE_CHARS)
        total = sum(counts.values())
        repeated = sum(n for n in counts.values() if n > 1)
        by_chapter = {c.index: _stripped_shingles(c.body) for c in chapters}
        seen_in: dict[str, int] = collections.Counter()
        for grams in by_chapter.values():
            seen_in.update(grams)
        shared = {gram for gram, n in seen_in.items() if n > 1}
        covered = length = 0
        for c in chapters:
            hit, size = _reused_share(c.body, shared)
            covered, length = covered + hit, length + size
        dup_share = repeated / total if total else 0.0
        reuse_share = covered / length if length else 0.0
        report["works"][key] = {"repeated_sentence_share": round(dup_share, 4), "reused_text_share": round(reuse_share, 4)}
        if dup_share > MAX_REPEATED_SENTENCE_SHARE:
            errors.append(f"{key}: {dup_share:.0%} of sentences repeat elsewhere in the work (max {MAX_REPEATED_SENTENCE_SHARE:.0%}); write each chapter as its own prose, not from templates")
        if reuse_share > MAX_REUSED_TEXT_SHARE:
            errors.append(f"{key}: {reuse_share:.0%} of the text reappears in another chapter (max {MAX_REUSED_TEXT_SHARE:.0%}); write each chapter as its own prose, not from templates")
        for grams in by_chapter.values():
            for gram in grams:
                owners[gram].add(key)
    cross = sum(1 for keys in owners.values() if len(keys) > 1)
    report["cross_work_shared_passages"] = cross
    if cross:
        errors.append(f"works in this set share {cross} {SHINGLE}-character passages; every work must be written separately")
    isolated = total_points = 0
    for target in lf.targets:
        chapter_by_index = {c.index: c for c in lf.works[target.work]}
        for point in target.items:
            spans = [(target.chapter.body, span) for span in point.ranges]
            spans += [(chapter_by_index[index].body, span) for index, span in point.evidence]
            for body, span in spans:
                total_points += 1
                isolated += _alone_in_paragraph(body, span)
    share = isolated / total_points if total_points else 0.0
    # Some prose (web fiction especially) puts most sentences on their own line, so the bar is
    # relative to the set's own habit: labelled sentences may not stand alone much more often
    # than its ordinary sentences do.
    alone = counted = 0
    for chapters in lf.works.values():
        for chapter in chapters:
            for start, end in sentences(chapter.body):
                if char_count(chapter.body[start:end]) >= MIN_REPEAT_SENTENCE_CHARS:
                    counted += 1
                    alone += _alone_in_paragraph(chapter.body, (start, end))
    base = alone / counted if counted else 0.0
    bar = max(MAX_ISOLATED_POINT_SHARE, base + ISOLATED_POINT_MARGIN)
    report["isolated_point_share"] = round(share, 4)
    report["base_single_sentence_paragraph_share"] = round(base, 4)
    if share > bar:
        errors.append(f"{share:.0%} of labelled sentences stand alone as one-sentence paragraphs, against {base:.0%} of all sentences "
                      f"(max {bar:.0%}); weave them into the surrounding narration")
    return report


def _alone_in_paragraph(body: str, span: tuple[int, int]) -> bool:
    start = body.rfind("\n", 0, span[0]) + 1
    end = body.find("\n", span[1])
    paragraph = body[start:end if end >= 0 else len(body)]
    return len(sentences(paragraph)) <= 1


def check_self_review(lf: LongformSet, errors: list[str]) -> None:
    """The author's per-target statement that the chapter holds no unplanned contradiction.

    Only coverage is checked; the notes are not read, so this works on a held-out set too.
    """
    path = lf.root / SELF_REVIEW
    try:
        review = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = review["targets"]
        covered = {row["target_id"] for row in rows if row.get("unintended_issues_checked") is True}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        errors.append(f"{SELF_REVIEW} missing or malformed")
        return
    missing = [t.id for t in lf.targets if t.id not in covered]
    if missing:
        errors.append(f"{SELF_REVIEW}: {len(missing)} targets lack unintended_issues_checked=true ({', '.join(missing[:5])})")


def shingles(lf: LongformSet) -> set[str]:
    found = set()
    for chapters in lf.works.values():
        for chapter in chapters:
            body = "".join(chapter.body.split())
            found.update(body[i:i + SHINGLE] for i in range(max(len(body) - SHINGLE + 1, 0)))
    return found


def cross_check(lf: LongformSet, other: LongformSet) -> list[str]:
    errors = []
    keys = set(lf.works) & set(other.works)
    titles = ({w.get("title") for w in lf.data.get("works") or [] if isinstance(w, dict)}
              & {w.get("title") for w in other.data.get("works") or [] if isinstance(w, dict)})
    if keys or titles:
        errors.append(f"shares {len(keys)} work keys and {len(titles)} work titles with {other.root.name}")
    shared = len(shingles(lf) & shingles(other))
    if shared:
        errors.append(f"shares {shared} {SHINGLE}-character passages with {other.root.name}")
    return errors


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("set_dir", type=pathlib.Path)
    parser.add_argument("--against", type=pathlib.Path, action="append", default=[], help="another set that must not overlap")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--freeze", action="store_true", help=f"write {SET_HASH_FILE} when there are no errors")
    mode.add_argument("--require-frozen", action="store_true", help=f"fail unless {SET_HASH_FILE} matches")
    parser.add_argument("--structure-only", action="store_true", help="skip length and count rules (for the template)")
    args = parser.parse_args(argv)

    lf = load(args.set_dir)
    errors, summary = validate(lf, structure_only=args.structure_only)
    for other_dir in args.against:
        errors.extend(cross_check(lf, load(other_dir)))
    hash_file = args.set_dir / SET_HASH_FILE
    if args.require_frozen and lf.data:
        actual = compute_set_hash(args.set_dir, lf.data)
        recorded = hash_file.read_text(encoding="utf-8").split()[0] if hash_file.exists() else None
        if actual != recorded:
            errors.append(f"{SET_HASH_FILE} missing or does not match the set (actual {actual[:12]})")
        summary["set_sha256"] = actual
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for error in errors:
        print("ERROR", error)
    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        return 1
    if args.freeze:
        digest = compute_set_hash(args.set_dir, lf.data)
        hash_file.write_text(digest + "\n", encoding="utf-8")
        print(f"frozen: {SET_HASH_FILE} = {digest}")
    print("PASS: structure, lengths, quotes, earlier-chapter evidence and counts. Semantic correctness needs separate review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
