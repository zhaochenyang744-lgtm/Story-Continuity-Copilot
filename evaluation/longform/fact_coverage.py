"""Phase-2 measurement: how much of what a set labels as evidence reaches the fact library.

    python -m evaluation.longform.fact_coverage --set <set_dir> --run-id <id>
        [--replay off|record|replay|replay_or_record] [--budget-cny 3] [--chapter-limit N] [--work KEY]

Each work goes through the author's import path: import every chapter (or the first N), run
Memory initialization with the metered provider, accept every candidate. Then, for every labelled
point and trap, an evidence quote counts as covered when some extracted fact cites the evidence
chapter and shares wording with the evidence sentence (at least MIN_SHARED_BIGRAMS character
pairs). This is a lexical approximation meant for comparing extraction versions, not a gate; the
report keeps the matched fact so a person can check it. Rule coverage asks the same of points
whose category is world_rule or whose designated basis is a timeless rule, but only counts
static_canon facts. Facts are model output; run this on dev and import sets only, never on the
formal set.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import pathlib
import re
import sys
import tempfile
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.longform import meter as metering  # noqa: E402  (puts backend on sys.path)
from evaluation.longform.schema import LongformSet, load  # noqa: E402
from evaluation.longform.textutil import sentence_cover  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.config import AppPaths  # noqa: E402
from app.engine import MEMORY_PROMPT_VERSION  # noqa: E402
from app.main import create_app  # noqa: E402
from app.stage13 import Stage13Settings  # noqa: E402

MIN_SHARED_BIGRAMS = 2
# A whole-book import needs more provider dispatches than one account's rolling 24-hour quota
# (120 for registered users); the measurement lifts that quota, the product keeps it.
MEASUREMENT_SETTINGS = dataclasses.replace(Stage13Settings.for_test(), registered_provider_attempts=5000)
STOP_BIGRAMS = {"一个", "没有", "自己", "他们", "我们", "什么", "这个", "那个", "已经", "时候", "因为", "所以", "可以", "不是"}


def bigrams(text: str) -> set[str]:
    chars = "".join(re.findall(r"[一-鿿]", text))
    return {chars[i:i + 2] for i in range(len(chars) - 1)} - STOP_BIGRAMS


def data(response):
    if response.status_code >= 300:
        raise RuntimeError(f"{response.status_code} {response.text[:300]}")
    return response.json()["data"]


def idem() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


def extract_facts(lf: LongformSet, work: str, provider, meter: metering.Meter, chapter_limit: int | None) -> dict:
    chapters = [c for c in lf.works[work] if not chapter_limit or c.index <= chapter_limit]
    root = pathlib.Path(tempfile.mkdtemp(prefix="longform-facts-"))
    app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                     provider=provider, executor=lambda fn, *args: fn(*args), settings=MEASUREMENT_SETTINGS)
    client = TestClient(app)
    data(client.post("/api/auth/register", json={"account_name": f"lf{uuid.uuid4().hex[:8]}", "display_name": "Facts",
                                                  "password": "longform-local-pass-123", "recovery_email": "facts@example.test"}, headers=idem()))
    # Single line breaks: the product's import limit counts every character, blank lines included.
    source = "\n".join(f"# {c.title}\n" + "\n".join(line for line in c.body.split("\n") if line.strip()) for c in chapters) + "\n"
    preview = data(client.post("/api/imports/preview", files={"file": ("work.md", source.encode("utf-8"), "text/markdown")}, headers=idem()))
    project = data(client.post(f"/api/imports/{preview['import_id']}/commit", json={
        "confirm": True, "title": work, "chapter_preview_ids": [row["preview_id"] for row in preview["detected"]["chapters"]]},
        headers=idem()))["project"]["id"]
    with meter.scope("extract", work):
        response = client.post(f"/api/projects/{project}/memory/initializations", json={"source_revision": 1}, headers=idem())
    init = data(response)["initialization"]
    if init.get("status") == "failed":
        return {"status": "failed", "error_code": init.get("error_code"), "facts": [], "chapters": len(chapters)}
    titles = {c.title: c.index for c in chapters}
    facts = [{"memory_type": row["memory_type"], "subject": row["subject"], "predicate": row["predicate"], "value": row["value"],
              "review_priority": row["review_priority"], "chapter_index": titles.get(row["source"]["chapter_title"])}
             for row in init.get("candidates") or []]
    client.close()
    return {"status": "completed", "facts": facts, "chapters": len(chapters)}


def coverage(lf: LongformSet, facts_by_work: dict[str, list[dict]], chapter_limit: int | None) -> dict:
    rows = []
    for target in lf.targets:
        if target.work not in facts_by_work or (chapter_limit and target.chapter.index > chapter_limit):
            continue
        chapters = {c.index: c for c in lf.works[target.work]}
        facts = facts_by_work[target.work]
        raw = next((t for t in lf.data["targets"] if t["id"] == target.id), {})
        bases = {item["id"]: item for item in raw.get("items", [])}
        for point in target.items + target.traps:
            item = bases.get(point.id) or {}
            rule_point = point.category == "world_rule" or (item.get("designated_basis") or {}).get("type") == "timeless_rule"
            for index, span in point.evidence:
                body = chapters[index].body
                start, end = sentence_cover(body, span)
                wanted = bigrams(body[start:end])
                best, best_shared = None, 0
                for fact in facts:
                    if fact["chapter_index"] != index:
                        continue
                    shared = len(wanted & bigrams(fact["subject"] + fact["value"]))
                    if shared > best_shared:
                        best, best_shared = fact, shared
                covered = best_shared >= MIN_SHARED_BIGRAMS
                rule_covered = rule_point and any(f["chapter_index"] == index and f["memory_type"] == "static_canon"
                                                  and len(wanted & bigrams(f["subject"] + f["value"])) >= MIN_SHARED_BIGRAMS for f in facts)
                rows.append({"point": point.id, "label": point.label, "evidence_chapter": index, "covered": covered,
                             "rule_point": rule_point, "rule_covered": rule_covered if rule_point else None,
                             "best_fact": best if covered else None, "shared_bigrams": best_shared})
    items = [r for r in rows if r["label"] != "trap"]
    rules = [r for r in rows if r["rule_point"]]
    ratio = lambda n, d: round(n / d, 4) if d else None
    return {
        "evidence_quotes": len(rows),
        "item_evidence_covered": ratio(sum(r["covered"] for r in items), len(items)),
        "trap_evidence_covered": ratio(sum(r["covered"] for r in rows if r["label"] == "trap"), sum(r["label"] == "trap" for r in rows)),
        "rule_evidence_covered_by_static_canon": ratio(sum(bool(r["rule_covered"]) for r in rules), len(rules)),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--replay", choices=metering.REPLAY_MODES, default="off")
    parser.add_argument("--budget-cny", type=float, default=3.0)
    parser.add_argument("--chapter-limit", type=int)
    parser.add_argument("--work", action="append", help="work key; default every work in the set")
    parser.add_argument("--results-dir", type=pathlib.Path, default=ROOT / "evaluation" / "results")
    args = parser.parse_args(argv)

    lf = load(args.set)
    if lf.errors:
        raise RuntimeError(f"longform_set_invalid:{len(lf.errors)}")
    if lf.kind == "formal":
        raise RuntimeError("fact_coverage_never_runs_on_the_formal_set")
    out = args.results_dir / f"longform-facts-{lf.data['set_id']}-{args.run_id}.json"
    if out.exists():
        raise FileExistsError(out)
    meter = metering.Meter(budget_cny=args.budget_cny, replay=args.replay)
    provider = metering.MeteredProvider(client_factory=meter.client_factory)
    if not provider.available:
        raise RuntimeError("longform_provider_unavailable: set CONTINUITY_PROVIDER/MODEL/BASE_URL/API_KEY/REVIEW_THINKING")
    works = args.work or list(lf.works)
    extracted, facts_by_work = {}, {}
    for work in works:
        if meter.stop_reason:
            break
        try:
            result = extract_facts(lf, work, provider, meter, args.chapter_limit)
        except Exception:
            if meter.stop_reason:
                break
            raise
        extracted[work] = {key: value for key, value in result.items() if key != "facts"}
        extracted[work]["fact_count"] = len(result["facts"])
        extracted[work]["facts_per_chapter"] = dict(collections.Counter(f["chapter_index"] for f in result["facts"]))
        facts_by_work[work] = result["facts"]
        print(json.dumps({"work": work, "status": result["status"], "facts": len(result["facts"]),
                          "spent_cny": round(meter.spent_cny, 4)}, ensure_ascii=False), flush=True)
    report = {"kind": "longform_fact_coverage", "set_id": lf.data["set_id"], "run_id": args.run_id,
              "memory_prompt_version": MEMORY_PROMPT_VERSION, "chapter_limit": args.chapter_limit,
              "meter": meter.describe(), "cost": meter.summary(), "works": extracted,
              "coverage": coverage(lf, facts_by_work, args.chapter_limit), "facts": facts_by_work}
    args.results_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    c = report["coverage"]
    print(json.dumps({"out": out.name, "item_evidence_covered": c["item_evidence_covered"],
                      "rule_evidence_covered_by_static_canon": c["rule_evidence_covered_by_static_canon"],
                      "facts": sum(len(v) for v in facts_by_work.values()), "spent_cny": round(meter.spent_cny, 4)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
