"""Score long-form results against a set's labels, and score retrieval/screening offline.

A run is reduced to one normalised record per target chapter (see `normalise_issue` for the issue
shape), whatever pipeline produced it, so the current per-sentence check and the later
passage-level check are scored by the same code.

Matching is by position: an issue counts for a labelled point when its anchor range overlaps the
point's sentence-widened range. Classes fold by nature, as V11 does, with conflict taking
precedence over insufficient_evidence:

    confirmed_conflict, possible_conflict -> conflict
    insufficient_evidence                 -> insufficient_evidence
    state_change                          -> no card (counted as noise, never as an error)
"""
from __future__ import annotations

import collections
from typing import Any, Iterable

from evaluation.longform.schema import CATEGORIES, LongformSet, Located, Target
from evaluation.longform.textutil import overlaps

NATURE_CLASS = {"confirmed_conflict": "conflict", "possible_conflict": "conflict",
                "insufficient_evidence": "insufficient_evidence", "state_change": None}
PRECEDENCE = ("conflict", "insufficient_evidence")
RETRIEVAL_K = (5, 10, 20)


def normalise_issue(nature: str | None, category: str | None, anchor: tuple[int, int] | None,
                    evidence_chapters: Iterable[int] = ()) -> dict:
    return {"nature": nature, "category": category, "anchor": list(anchor) if anchor else None,
            "evidence_chapters": sorted(set(evidence_chapters))}


def card_class(issue: dict) -> str | None:
    return NATURE_CLASS.get(issue.get("nature"))


def _anchor(issue: dict) -> tuple[int, int] | None:
    anchor = issue.get("anchor")
    return (anchor[0], anchor[1]) if anchor else None


def _matching(issues: list[dict], point: Located) -> list[dict]:
    return [issue for issue in issues if _anchor(issue) and any(overlaps(_anchor(issue), span) for span in point.ranges)]


def _predicted(issues: list[dict]) -> str:
    classes = {card_class(issue) for issue in issues}
    return next((label for label in PRECEDENCE if label in classes), "no_issue")


def score_target(target: Target, record: dict) -> dict:
    issues = record.get("issues") or []
    cards = [issue for issue in issues if card_class(issue)]
    rows = []
    matched_cards: set[int] = set()
    for point in target.items + target.traps:
        hits = _matching(cards, point)
        matched_cards.update(id(issue) for issue in hits)
        predicted = _predicted(hits)
        row = {"id": point.id, "label": point.label, "predicted": predicted}
        if point.label == "conflict":
            row["category"] = point.category
            row["category_hit"] = any(issue.get("category") == point.category for issue in hits if card_class(issue) == "conflict")
            row["designated"] = point.designated
            row["confirmed"] = any(issue.get("nature") == "confirmed_conflict" for issue in hits)
        if point.label != "trap" and predicted == point.label:
            cited = {c for issue in hits for c in issue.get("evidence_chapters") or []}
            row["cited_labelled_chapter"] = bool(cited & {index for index, _ in point.evidence})
        rows.append(row)
    spurious = [issue for issue in cards if id(issue) not in matched_cards]
    unanchored = sum(1 for issue in cards if not _anchor(issue))
    return {
        "target_id": target.id, "status": record.get("status"), "error_code": record.get("error_code"),
        "clean": not target.items, "points": rows,
        "cards": len(cards), "spurious_cards": len(spurious), "unanchored_cards": unanchored,
        "state_change_cards": sum(1 for issue in issues if issue.get("nature") == "state_change"),
        "sentences": record.get("sentence_count"), "undecided": record.get("undecided_count"),
        "seconds": record.get("seconds"),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_run(lf: LongformSet, records: dict[str, dict]) -> dict:
    """Aggregate per-target scores. A target with no record is scored as a failed, empty run."""
    per_target = [score_target(t, records.get(t.id) or {"status": "missing", "issues": []}) for t in lf.targets]
    points = [row for target in per_target for row in target["points"]]
    by_label = collections.defaultdict(list)
    for row in points:
        by_label[row["label"]].append(row)
    conflicts, gaps, traps = by_label["conflict"], by_label["insufficient_evidence"], by_label["trap"]
    detected_conflicts = [row for row in conflicts if row["predicted"] == "conflict"]
    designated = [row for row in conflicts if row["designated"]]
    total_cards = sum(t["cards"] for t in per_target)
    clean = [t for t in per_target if t["clean"]]
    sentences = sum(t["sentences"] or 0 for t in per_target)
    undecided = sum(t["undecided"] or 0 for t in per_target)
    per_category = {category: _ratio(sum(r["predicted"] == "conflict" for r in conflicts if r["category"] == category),
                                     sum(1 for r in conflicts if r["category"] == category)) for category in CATEGORIES}
    return {
        "targets": len(per_target),
        "completed_targets": sum(1 for t in per_target if t["status"] == "completed"),
        "terminal": dict(collections.Counter(f"{t['status']}:{t['error_code']}" for t in per_target)),
        "conflict_recall": _ratio(len(detected_conflicts), len(conflicts)),
        "insufficient_evidence_recall": _ratio(sum(r["predicted"] == "insufficient_evidence" for r in gaps), len(gaps)),
        "insufficient_evidence_reported_as_conflict": sum(r["predicted"] == "conflict" for r in gaps),
        "conflict_category_accuracy": _ratio(sum(r["category_hit"] for r in detected_conflicts), len(detected_conflicts)),
        "trap_false_positive_rate": _ratio(sum(r["predicted"] != "no_issue" for r in traps), len(traps)),
        "card_precision": _ratio(total_cards - sum(t["spurious_cards"] for t in per_target), total_cards),
        "spurious_cards_per_target": _ratio(sum(t["spurious_cards"] for t in per_target), len(per_target)),
        "clean_target_zero_card_rate": _ratio(sum(1 for t in clean if t["cards"] == 0), len(clean)),
        "undecided_sentence_rate": _ratio(undecided, sentences),
        "designated": {"total": len(designated),
                       "confirmed_with_category": sum(r["predicted"] == "conflict" and r["category_hit"] and r["confirmed"] for r in designated),
                       "ids": [r["id"] for r in designated]},
        "counts": {"conflicts": len(conflicts), "insufficient_evidence": len(gaps), "traps": len(traps),
                   "clean_targets": len(clean), "cards": total_cards, "sentences": sentences, "undecided": undecided},
        # Reported, never gating.
        "diagnostics": {
            "conflict_recall_by_category": per_category,
            "cited_labelled_chapter": sum(1 for r in points if r.get("cited_labelled_chapter")),
            "unanchored_cards": sum(t["unanchored_cards"] for t in per_target),
            "state_change_cards": sum(t["state_change_cards"] for t in per_target),
        },
        "per_target": per_target,
    }


def _labelled_points(lf: LongformSet, include_traps: bool = True) -> list[tuple[Target, Located]]:
    return [(t, p) for t in lf.targets for p in t.items + (t.traps if include_traps else [])]


def score_retrieval(lf: LongformSet, output: dict[str, Any], ks: Iterable[int] = RETRIEVAL_K) -> dict:
    """Offline retrieval recall: no model, only a retriever's ranked results against the labels.

    `output["targets"][target_id]["queries"]` is a list of {"start", "end", "results"} where the
    query range is in the target body and each result is {"chapter_index", "start", "end"} in
    that earlier chapter's body, best first. For a labelled point the queries overlapping its
    sentences are merged by best rank; an evidence quote is found at k when one of the first k
    merged results overlaps it. A result from the target chapter or later is a leak.
    """
    ks = tuple(ks)
    rows, leaks = [], 0
    targets = output.get("targets") or {}
    for target, point in _labelled_points(lf):
        queries = (targets.get(target.id) or {}).get("queries") or []
        best: dict[tuple[int, int, int], int] = {}
        for query in queries:
            for rank, result in enumerate(query.get("results") or []):
                key = (result["chapter_index"], result["start"], result["end"])
                if key[0] >= target.chapter.index:
                    continue
                if any(overlaps((query["start"], query["end"]), span) for span in point.ranges):
                    best[key] = min(best.get(key, rank), rank)
        ranked = sorted(best, key=best.get)
        found = {}
        for k in ks:
            top = ranked[:k]
            hits = [any(index == e_index and overlaps((start, end), e_span) for index, start, end in top)
                    for e_index, e_span in point.evidence]
            found[k] = {"all": bool(hits) and all(hits), "any": any(hits)}
        rows.append({"id": point.id, "label": point.label, "queried": bool(best), "found": found})
    for target_id, entry in targets.items():
        target = next((t for t in lf.targets if t.id == target_id), None)
        if target:
            leaks += sum(1 for query in entry.get("queries") or [] for result in query.get("results") or []
                         if result["chapter_index"] >= target.chapter.index)
    def recall(label_filter, k, mode):
        chosen = [r for r in rows if label_filter(r["label"])]
        return _ratio(sum(r["found"][k][mode] for r in chosen), len(chosen))
    is_item = lambda label: label != "trap"
    return {
        "points": len(rows),
        "recall_all_evidence": {k: recall(is_item, k, "all") for k in ks},
        "recall_any_evidence": {k: recall(is_item, k, "any") for k in ks},
        "trap_recall_all_evidence": {k: recall(lambda label: label == "trap", k, "all") for k in ks},
        "later_chapter_leaks": leaks,
        "per_point": rows,
    }


def score_screening(lf: LongformSet, output: dict[str, Any]) -> dict:
    """Offline screening recall: did the cheap pass flag the passages that hold the labelled points?

    `output["targets"][target_id]["flagged"]` is a list of {"start", "end"} ranges in the target
    body. A missed item is a problem the deep check never sees; the flagged share of the text is
    what the deep check will cost.
    """
    targets = output.get("targets") or {}
    rows = []
    flagged_chars = total_chars = 0
    for target in lf.targets:
        flagged = [(f["start"], f["end"]) for f in (targets.get(target.id) or {}).get("flagged") or []]
        total_chars += len(target.chapter.body)
        covered = set()
        for start, end in flagged:
            covered.update(range(max(start, 0), min(end, len(target.chapter.body))))
        flagged_chars += len(covered)
        for point in target.items + target.traps:
            rows.append({"id": point.id, "label": point.label,
                         "flagged": any(overlaps(f, span) for f in flagged for span in point.ranges)})
    items = [r for r in rows if r["label"] != "trap"]
    traps = [r for r in rows if r["label"] == "trap"]
    return {
        "item_recall": _ratio(sum(r["flagged"] for r in items), len(items)),
        "conflict_recall": _ratio(sum(r["flagged"] for r in items if r["label"] == "conflict"), sum(r["label"] == "conflict" for r in items)),
        "insufficient_evidence_recall": _ratio(sum(r["flagged"] for r in items if r["label"] == "insufficient_evidence"),
                                               sum(r["label"] == "insufficient_evidence" for r in items)),
        "trap_flag_rate": _ratio(sum(r["flagged"] for r in traps), len(traps)),
        "flagged_text_share": _ratio(flagged_chars, total_chars),
        "per_point": rows,
    }
