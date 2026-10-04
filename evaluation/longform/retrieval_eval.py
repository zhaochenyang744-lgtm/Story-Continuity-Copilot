"""Phase-3 offline retrieval comparison: no model, only rankings against the labelled evidence.

    python -m evaluation.longform.retrieval_eval --set <set_dir> [--facts <fact_coverage report>] [--out <json>]

For every target chapter, every query unit retrieves evidence from earlier chapters only, and
evaluation.longform.score.score_retrieval counts a labelled evidence quote as found at k when one
of the first k results overlaps it.

Methods
- old: today's check path, reproduced. Each sentence (claim) scores whole chapters by shared
  character pairs plus Memory links (v2_database.run_input), keeps 5, then the engine keeps 3
  with Memory weighting and shows a 500-character window of each (engine._selected_evidence).
- sentence: the passage index (backend/app/passages.py) queried with each sentence.
- passage: the passage index queried with each ~500-character passage of the target chapter,
  the unit phase 4 will check.
- multi: check a passage but retrieve per sentence; the sentence lists are merged rank by rank.
- *_plain: the same without entity terms, to see what Memory subjects add.
- *_facts: the same with the fact route: Memory facts scored on their wording, each mapped to the
  passage of its chapter that shares the most with it, interleaved with the direct results.

Entity terms and Memory links come from a fact_coverage report (the facts a real import
extracted); without one the old method has no Memory and the new one no entities.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.engine import _bounded_excerpt, _claim_terms  # noqa: E402
from app.passages import FactKey, PassageIndex, split_passages  # noqa: E402
from evaluation.longform.schema import LongformSet, load  # noqa: E402
from evaluation.longform.score import score_retrieval  # noqa: E402
from evaluation.longform.textutil import sentences  # noqa: E402

KS = (3, 5, 8, 10, 20)


def _chars(text: str) -> str:
    return "".join(re.findall(r"[一-鿿A-Za-z0-9]", text))


def old_results(claim: str, chapters: list, memory: list[dict], before: int) -> list[dict]:
    """run_input's chapter ranking, then the engine's three picks with 500-character windows."""
    chars = _chars(claim)
    grams = {chars[i:i + 2] for i in range(max(0, len(chars) - 1))}
    scored = []
    for chapter in chapters:
        if chapter.index >= before:
            continue
        score = sum(g in chapter.body for g in grams)
        score += sum(2 for m in memory if m["chapter_index"] == chapter.index and any(g in m["subject"] + m["value"] for g in grams))
        if score:
            scored.append((score, f"span-{chapter.index:04d}", chapter))
    top5 = [c for _, _, c in sorted(scored, key=lambda row: (-row[0], row[1]))[:5]]
    terms = _claim_terms(claim)
    ranked = []
    for chapter in top5:
        related = [m for m in memory if m["chapter_index"] == chapter.index]
        memory_text = " ".join(f"{m['subject']} {m['predicate']} {m['value']}" for m in related)
        text_score = len(terms & _claim_terms(chapter.body))
        ranked.append((10 * len(terms & _claim_terms(memory_text)) + min(20, text_score), f"chapter-{chapter.index:04d}", chapter, related, text_score))
    order = lambda row: (-row[0], row[1])
    direct = sorted((row for row in ranked if row[4] > 0), key=lambda row: (-row[4], row[1]))[:2]
    kept = {row[1] for row in direct}
    picks = (direct + [row for row in sorted(ranked, key=order) if row[1] not in kept])[:3]
    results = []
    for _, _, chapter, related, _ in sorted(picks, key=order):
        hints = [claim] + [str(m[key]) for m in sorted(related, key=lambda m: (m["subject"], m["value"])) for key in ("subject", "value")]
        window = _bounded_excerpt(chapter.body, hints, 500)
        start = chapter.body.find(window)
        results.append({"chapter_index": chapter.index, "start": start, "end": start + len(window)})
    return results


def run_method(lf: LongformSet, facts: dict[str, list[dict]], method: str, k: int = 20) -> dict:
    output = {"targets": {}}
    indexes = {}
    for work, chapters in lf.works.items():
        passages = [p for c in chapters for p in split_passages(c.body, span_id=f"{work}:{c.index}", chapter_id=work, chapter_number=c.index)]
        entities = [] if method.endswith("_plain") else [f["subject"] for f in facts.get(work, [])]
        keys = [FactKey(f"{f['subject']} {f['predicate']} {f['value']}", f["chapter_index"])
                for f in facts.get(work, [])] if method.endswith("_facts") else []
        indexes[work] = (PassageIndex(passages, entities, keys), chapters)
    for target in lf.targets:
        index, chapters = indexes[target.work]
        body = target.chapter.body
        if method.startswith(("passage", "multi")):
            units = [(p.start, p.end) for p in split_passages(body, span_id="target", chapter_id="target", chapter_number=target.chapter.index)]
        else:
            units = sentences(body)
        queries = []
        for start, end in units:
            text = body[start:end]
            if method == "old":
                results = old_results(text, chapters, facts.get(target.work, []), target.chapter.index)
            elif method.startswith("multi"):
                # Check a passage, retrieve per sentence: each sentence's list, merged rank by rank.
                lists = [[p for _, p in index.search(body[a:b], before_chapter=target.chapter.index, k=k)]
                         for a, b in sentences(body) if a < end and start < b]
                merged, seen = [], set()
                for rank in range(k):
                    for found in lists:
                        if rank < len(found) and found[rank].id not in seen:
                            seen.add(found[rank].id)
                            merged.append(found[rank])
                results = [{"chapter_index": p.chapter_number, "start": p.start, "end": p.end} for p in merged[:k]]
            else:
                results = [{"chapter_index": p.chapter_number, "start": p.start, "end": p.end}
                           for _, p in index.search(text, before_chapter=target.chapter.index, k=k)]
            queries.append({"start": start, "end": end, "results": results})
        output["targets"][target.id] = {"queries": queries}
    return output


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", required=True, type=pathlib.Path)
    parser.add_argument("--facts", type=pathlib.Path, help="fact_coverage report whose facts serve as Memory")
    parser.add_argument("--methods", nargs="*", default=["old", "sentence", "sentence_plain", "sentence_facts", "passage", "passage_facts", "multi", "multi_facts"])
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args(argv)
    lf = load(args.set)
    if lf.errors:
        raise RuntimeError(f"longform_set_invalid:{len(lf.errors)}")
    if lf.kind == "formal":
        raise RuntimeError("retrieval_eval_never_runs_on_the_formal_set")
    facts = json.loads(args.facts.read_text(encoding="utf-8"))["facts"] if args.facts else {}
    report = {"set_id": lf.data["set_id"], "facts": str(args.facts) if args.facts else None, "methods": {}}
    for method in args.methods:
        scored = score_retrieval(lf, run_method(lf, facts, method), ks=KS)
        by_label = Counter((row["label"], row["found"][10]["all"]) for row in scored["per_point"])
        report["methods"][method] = {key: scored[key] for key in ("points", "recall_all_evidence", "recall_any_evidence", "trap_recall_all_evidence", "later_chapter_leaks")}
        report["methods"][method]["found_at_10_by_label"] = {f"{label}:{found}": n for (label, found), n in sorted(by_label.items())}
        report["methods"][method]["per_point"] = scored["per_point"]
        print(json.dumps({"method": method, "all@3/5/8/10/20": [round(scored["recall_all_evidence"][k], 3) for k in KS],
                          "any@10": scored["recall_any_evidence"][10], "trap_all@10": scored["trap_recall_all_evidence"][10],
                          "leaks": scored["later_chapter_leaks"]}, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
