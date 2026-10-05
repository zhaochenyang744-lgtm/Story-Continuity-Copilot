"""Phase-4 screening measurement: the product's screen step alone, real model, metered.

    python -m evaluation.longform.screen_eval --set <set_dir> --facts <fact_coverage report> --run-id <id>
        [--replay off|record|replay|replay_or_record] [--budget-cny 1] [--only TARGET ...]

For every target chapter N, the sentences of chapter N are screened exactly as ContinuityEngine
screens a draft (engine._screen, review_screening.py), with chapters 1..N-1 as the passage index and
the facts of a real import (a fact_coverage report) from chapters before N as Story Memory. Then:

- screening (score.score_screening): labelled points whose sentence was flagged, and the share of
  the chapter's text that would go on to the careful review (dev targets: recall >= 0.95, share <= 0.40);
- reach: labelled points whose flagged sentence would also be reviewed against every labelled
  evidence quote (the passages review_screening.claim_evidence picks, cited facts included).

--app-memory takes Story Memory from the app instead: each target's chapters 1..N-1 are imported and
initialized exactly as evaluation.longform.run does (replayable), so the screen sees the facts a
real check would. --part-chars tries another screen part size.

Only the cheap non-thinking screen is called; nothing is reviewed. Never runs on a formal set.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.longform import meter as metering  # noqa: E402  (puts backend on sys.path)
from evaluation.longform.schema import LongformSet, Target, load  # noqa: E402
from evaluation.longform.score import overlaps, score_screening  # noqa: E402
from evaluation.longform import run as runner  # noqa: E402

from app import review_screening as screening  # noqa: E402
from app.engine import ContinuityEngine  # noqa: E402
from app.provider import CONTINUITY_SCREEN_PROMPT_VERSION  # noqa: E402
from app.v2_database import split_continuity_claims  # noqa: E402


def target_inputs(lf: LongformSet, target: Target, facts: list[dict]) -> tuple[list[dict], list[dict], list[dict], list[tuple[int, int]]]:
    """Sources (chapters before N), Memory (facts from before N), claims and their body ranges."""
    sources = [{"id": f"{target.work}:{c.index}", "chapter_id": f"chapter-{c.index}", "chapter_number": c.index, "body": c.body, "label": c.title}
               for c in lf.works[target.work] if c.index < target.chapter.index]
    memory = [{"id": f"m{i}", "memory_type": f["memory_type"], "subject": f["subject"], "predicate": f["predicate"], "value": f["value"],
               "source_span_id": f"{target.work}:{f['chapter_index']}"}
              for i, f in enumerate(facts, 1) if f["chapter_index"] < target.chapter.index]
    body, claims, ranges, cursor = target.chapter.body, [], [], 0
    for number, text in enumerate(split_continuity_claims(body), 1):
        start = body.find(text, cursor)
        cursor = start + len(text)
        claims.append({"id": f"{target.id}-c{number}", "text": text, "context": "draft"})
        ranges.append((start, cursor))
    return sources, memory, claims, ranges


def app_facts(lf: LongformSet, target: Target, provider) -> list[dict]:
    """The confirmed Memory an app import of chapters 1..N-1 builds, as fact_coverage-style facts."""
    client, project, chapter_index = runner.open_prefix(lf, target, provider)
    records = runner.data(client.get(f"/api/projects/{project}/memory"))["records"]
    client.close()
    return [{"memory_type": r["memory_type"], "subject": r["subject"], "predicate": r["predicate"], "value": r["value"],
             "chapter_index": chapter_index[r["source"]["chapter_id"]]}
            for r in records if r.get("source") and chapter_index.get(r["source"]["chapter_id"]) is not None]


def screen_target(engine: ContinuityEngine, lf: LongformSet, target: Target, facts: list[dict]) -> dict:
    sources, memory, claims, ranges = target_inputs(lf, target, facts)
    index = screening.build_index(sources, memory)
    chapters = screening.memory_chapters(sources, memory)
    summary = {"claims": len(claims), "parts": 0, "fallback_parts": 0}
    results: list = []
    flags = engine._screen(claims, index, memory, chapters, results, summary)
    if "error" in flags:
        raise RuntimeError(f"screen_failed:{target.id}:{flags['error']!r}")
    by_id = {claim["id"]: (claim, span) for claim, span in zip(claims, ranges)}
    flagged = [{"start": by_id[cid][1][0], "end": by_id[cid][1][1], "kind": flag["kind"], "facts": len(flag["facts"])} for cid, flag in flags.items()]
    passages = {cid: screening.claim_evidence(by_id[cid][0], index, flag["facts"]) for cid, flag in flags.items()}
    reach = []
    for point in target.items + target.traps:
        hit = [cid for cid in flags if any(overlaps(by_id[cid][1], span) for span in point.ranges)]
        seen = [(int(p["source_span_id"].rsplit(":", 1)[1]), p["passage_start"], p["passage_start"] + len(p["body"])) for cid in hit for p in passages[cid]]
        found = [any(ch == e_index and overlaps((s, e), e_span) for ch, s, e in seen) for e_index, e_span in point.evidence]
        reach.append({"id": point.id, "label": point.label, "flagged": bool(hit), "all": bool(found) and all(found), "any": any(found)})
    return {"flagged": flagged, "reach": reach, "summary": summary, "dispatches": len(results)}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", required=True, type=pathlib.Path)
    parser.add_argument("--facts", type=pathlib.Path, help="fact_coverage report (required unless --app-memory)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--replay", choices=metering.REPLAY_MODES, default="replay_or_record")
    parser.add_argument("--budget-cny", type=float, default=1.0)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--app-memory", action="store_true", help="screen against the Memory an app import of chapters 1..N-1 builds")
    parser.add_argument("--part-chars", type=int, help="screen part size (default review_screening.SCREEN_PART_CHARS)")
    parser.add_argument("--results-dir", type=pathlib.Path, default=ROOT / "evaluation" / "results")
    args = parser.parse_args(argv)
    lf = load(args.set)
    if lf.errors:
        raise RuntimeError(f"longform_set_invalid:{len(lf.errors)}")
    if lf.kind == "formal":
        raise RuntimeError("screen_eval_never_runs_on_the_formal_set")
    out = args.results_dir / f"longform-screen-{lf.data['set_id']}-{args.run_id}.json"
    if out.exists():
        raise FileExistsError(out)
    facts = json.loads(args.facts.read_text(encoding="utf-8"))["facts"] if args.facts else {}
    if args.part_chars:
        screening.SCREEN_PART_CHARS = args.part_chars
    meter = metering.Meter(budget_cny=args.budget_cny, replay=args.replay)
    provider = metering.MeteredProvider(client_factory=meter.client_factory)
    if not provider.available:
        raise RuntimeError("screen_eval_provider_unavailable: set CONTINUITY_PROVIDER/MODEL/BASE_URL/API_KEY/REVIEW_THINKING")
    engine = ContinuityEngine(provider)
    targets = [t for t in lf.targets if not args.only or t.id in set(args.only)]
    records = {}
    for target in targets:
        work_facts = facts.get(target.work, [])
        if args.app_memory:
            with meter.scope("setup", target.id):
                work_facts = app_facts(lf, target, provider)
        with meter.scope("check", target.id):
            records[target.id] = screen_target(engine, lf, target, work_facts)
        row = records[target.id]
        print(json.dumps({"target": target.id, "claims": row["summary"]["claims"], "flagged": len(row["flagged"]),
                          "fallback_parts": row["summary"]["fallback_parts"], "spent_cny": round(meter.spent_cny, 4)}, ensure_ascii=False), flush=True)
    scoped = LongformSet(lf.root, lf.data, lf.works, targets, [])
    scored = score_screening(scoped, {"targets": records})
    reach = [row for record in records.values() for row in record["reach"]]
    items = [row for row in reach if row["label"] != "trap"]
    report = {
        "kind": "longform_screen_eval", "set_id": lf.data["set_id"], "run_id": args.run_id,
        "screen_prompt_version": CONTINUITY_SCREEN_PROMPT_VERSION, "facts": str(args.facts), "model": provider.model,
        "screening": {key: scored[key] for key in ("item_recall", "conflict_recall", "insufficient_evidence_recall", "trap_flag_rate", "flagged_text_share")},
        "reach": {"items_all": sum(r["all"] for r in items) / len(items) if items else None,
                  "items_any": sum(r["any"] for r in items) / len(items) if items else None},
        "missed": [row["id"] for row in scored["per_point"] if not row["flagged"] and row["label"] != "trap"],
        "unreached": [row["id"] for row in items if row["flagged"] and not row["all"]],
        "cost": meter.summary("check"), "meter": meter.describe(), "records": records,
    }
    args.results_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": out.name, **report["screening"], **{f"reach_{k}": v for k, v in report["reach"].items()},
                      "missed": report["missed"], "unreached": report["unreached"],
                      "cost_cny": round(report["cost"]["cost_cny"]["total"], 4)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
