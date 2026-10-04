"""Long-form runner: check each target chapter through the real app, metered.

    python -m evaluation.longform.run --set <set_dir> --run-id <id>
        [--mode dev|formal] [--replay off|record|replay|replay_or_record] [--budget-cny 10]
        [--only TARGET ...] [--smoke] [--subset NAME] [--chapter-limit N] [--cache-hit-price X] [--dry-run]

Adapter "draft_replace_v1" (today's pipeline): for each target chapter N a fresh project imports
chapters 1..N-1, accepts every Memory candidate, then checks chapter N as the draft. Chapter N
never sees chapter N or anything later, which is the rule the new pipeline must keep too. Setup
(import + Memory) and the check are metered separately; only the check is the per-chapter cost.
Today's pipeline has no multi-chapter check, so a selection is reported as the sequential sum of
its chapters' checks (selection_mode "sequential_sum"); phase 5 replaces this with a real run.

Dev runs may replay recorded responses (timings are then marked invalid). A formal run requires
a frozen set, approved thresholds, a pinned prompt version, the production concurrency, no
replay and the whole set. Output: evaluation/results/longform-<set_id>-<run_id>.json plus a
per-target checkpoint; it refuses to overwrite either. No model prose is kept.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys
import tempfile
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.longform import meter as metering  # noqa: E402  (puts backend on sys.path)
from evaluation.longform import thresholds  # noqa: E402
from evaluation.longform.schema import SET_HASH_FILE, LongformSet, Target, compute_set_hash, load  # noqa: E402
from evaluation.longform.score import normalise_issue, score_run  # noqa: E402
from evaluation.longform.validate import validate  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.config import AppPaths  # noqa: E402
from app.engine import PROMPT_VERSION, SCREENED_PROMPT_VERSION, ContinuityEngine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.stage13 import Stage13Settings  # noqa: E402
from app.v2_database import split_continuity_claims  # noqa: E402

ADAPTER = "draft_replace_v1"
RETRYABLE_ERRORS = {"provider_timeout", "provider_unavailable", "provider_error"}
RETRYABLE_STATUSES = {"timed_out"}
POLL_SECONDS = 600
# What a formal run must match. prompt_version stays None until the phase-4 pipeline is pinned
# deliberately; until then a formal run refuses to start.
FORMAL_RUNTIME = {"model": "deepseek-flash", "review_thinking": "high", "concurrency": "4", "prompt_version": None}
DEFAULT_BUDGET_CNY = 10.0


def prompt_version() -> str:
    """The prompt version a check created now records: screened by default, legacy under the rollback switch."""
    return SCREENED_PROMPT_VERSION if ContinuityEngine.pipeline() == "screened" else PROMPT_VERSION


def data(response):
    if response.status_code >= 300:
        raise RuntimeError(f"{response.status_code} {response.text[:300]}")
    return response.json()["data"]


def idem() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


def prefix_markdown(lf: LongformSet, target: Target) -> str:
    return "\n\n".join(f"# {c.title}\n\n{c.body}" for c in lf.works[target.work] if c.index < target.chapter.index) + "\n"


def open_prefix(lf: LongformSet, target: Target, provider) -> tuple[TestClient, str, dict[str, int]]:
    """A fresh account and project holding chapters 1..N-1, with every Memory candidate accepted."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="longform-run-"))
    app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                     provider=provider, executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
    client = TestClient(app)
    data(client.post("/api/auth/register", json={
        "account_name": f"lf{uuid.uuid4().hex[:8]}", "display_name": "Longform run",
        "password": "longform-local-pass-123", "recovery_email": "longform@example.test"}, headers=idem()))
    source = prefix_markdown(lf, target)
    preview = data(client.post("/api/imports/preview", files={"file": ("work.md", source.encode("utf-8"), "text/markdown")}, headers=idem()))
    project = data(client.post(f"/api/imports/{preview['import_id']}/commit", json={
        "confirm": True, "title": target.work,
        "chapter_preview_ids": [row["preview_id"] for row in preview["detected"]["chapters"]]}, headers=idem()))["project"]["id"]
    listing = data(client.get(f"/api/projects/{project}/chapters?include=excerpt"))["chapters"]
    index_by_title = {c.title: c.index for c in lf.works[target.work]}
    chapter_index = {row["id"]: index_by_title.get(row["title"]) for row in listing}
    init = data(client.post(f"/api/projects/{project}/memory/initializations", json={"source_revision": 1}, headers=idem()))["initialization"]
    if init.get("status") == "failed":
        raise RuntimeError(f"longform_memory_initialization_failed:{target.id}:{init.get('error_code')}")
    for candidate in init.get("candidates") or []:
        client.post(f"/api/projects/{project}/memory/initializations/{init['id']}/candidates/{candidate['id']}/decision",
                    json={"decision": "accepted"}, headers=idem())
    data(client.post(f"/api/projects/{project}/memory/initializations/{init['id']}/commit", json={"confirm": True}, headers=idem()))
    return client, project, chapter_index


def check_once(client: TestClient, project: str, body: str) -> tuple[dict, float]:
    draft = data(client.get(f"/api/projects/{project}"))["current_draft"]
    patched = data(client.patch(f"/api/projects/{project}/drafts/{draft['id']}",
                                json={"base_revision": draft["revision"], "body": body}, headers=idem()))
    started = time.perf_counter()
    run = data(client.post(f"/api/projects/{project}/checks",
                           json={"draft_id": draft["id"], "draft_revision": patched["revision"]}, headers=idem()))
    url = f"/api/projects/{project}/checks/{run['run_id']}?include=issues,evidence,metrics"
    view = data(client.get(url))
    deadline = time.monotonic() + POLL_SECONDS
    while view["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(1)
        view = data(client.get(url))
    return view, round(time.perf_counter() - started, 1)


def anchor_of(body: str, claim_text: str | None) -> tuple[int, int] | None:
    if not claim_text:
        return None
    start = body.find(claim_text)
    return (start, start + len(claim_text)) if start >= 0 else None


def run_target(lf: LongformSet, target: Target, provider, meter: metering.Meter) -> dict:
    with meter.scope("setup", target.id):
        client, project, chapter_index = open_prefix(lf, target, provider)
    body = target.chapter.body
    with meter.scope("check", target.id):
        view, seconds = check_once(client, project, body)
        first = None
        if (view["status"] in RETRYABLE_STATUSES or view.get("error_code") in RETRYABLE_ERRORS) and not meter.stop_reason:
            first = {"status": view["status"], "error_code": view.get("error_code"), "seconds": seconds}
            view, seconds = check_once(client, project, body)
            seconds = round(seconds + first["seconds"], 1)
    client.close()
    issues = [normalise_issue(issue.get("nature"), issue.get("category"), anchor_of(body, issue.get("claim_text")),
                              [chapter_index[e["chapter_id"]] for e in issue.get("evidence") or []
                               if chapter_index.get(e.get("chapter_id")) is not None])
              for issue in view.get("issues") or []]
    metrics = view.get("metrics") or {}
    claims = split_continuity_claims(body)
    return {
        "target_id": target.id, "work": target.work, "chapter_index": target.chapter.index,
        "chars": target.chapter.length, "status": view["status"], "error_code": view.get("error_code"),
        "seconds": seconds, "infrastructure_retry": first,
        "sentence_count": len(split_continuity_claims(body)),
        "undecided_count": len(metrics.get("undecided_claims") or []),
        # The screened pipeline's per-sentence screen outcome (absent for legacy runs).
        "screen": {state: sum(1 for row in metrics.get("retrieval") or [] if row.get("screen") == state)
                   for state in ("flagged", "passed", "unscreened")},
        "reviewed_count": sum(1 for row in metrics.get("retrieval") or [] if row.get("returned_span_ids")),
        # Sentence ranges the screen flagged, so a missed point can be told apart from a missed screen.
        "flagged_ranges": [anchor_of(body, claims[row["claim_ordinal"] - 1]) for row in metrics.get("retrieval") or []
                           if row.get("screen") == "flagged" and row.get("claim_ordinal") and row["claim_ordinal"] <= len(claims)],
        "review_ranges": {path: [anchor_of(body, claims[row["claim_ordinal"] - 1]) for row in metrics.get("retrieval") or []
                                 if row.get("review") == path and row.get("claim_ordinal") and row["claim_ordinal"] <= len(claims)]
                          for path in ("triage", "escalated", "deep")},
        "issues": issues,
        "app_metrics": {key: metrics.get(key) for key in ("latency_ms", "input_tokens", "output_tokens", "cost_cny")},
        "check_cost": meter.summary("check", target.id),
        "setup_cost": meter.summary("setup", target.id),
    }


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "p90": None, "max": None}
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, max(0, round(0.9 * len(ordered) + 0.5) - 1))]
    return {"n": len(values), "mean": statistics.fmean(values), "median": statistics.median(values), "p90": p90, "max": ordered[-1]}


def cost_time(lf: LongformSet, records: dict[str, dict], meter: metering.Meter) -> dict:
    done = [r for r in records.values() if r["status"] == "completed"]
    replayed = sum(r["check_cost"]["replayed_dispatches"] for r in records.values())
    selections = []
    for selection in lf.data.get("selections") or []:
        ids = [t.id for t in lf.targets if t.work == selection["work"] and t.chapter.title in selection["chapters"]]
        rows = [records.get(i) for i in ids]
        complete = all(r is not None for r in rows)
        selections.append({"id": selection["id"], "chapters": len(selection["chapters"]), "complete": complete,
                           "seconds": sum(r["seconds"] for r in rows) if complete else None,
                           "cost_cny": sum(r["check_cost"]["cost_cny"]["total"] for r in rows) if complete else None})
    return {
        "timing_valid": replayed == 0,
        "selection_mode": "sequential_sum",
        "single_chapter": {
            "seconds": _stats([r["seconds"] for r in done]),
            "cost_cny": _stats([r["check_cost"]["cost_cny"]["total"] for r in done]),
            "cost_cny_per_1000_chars": _stats([1000 * r["check_cost"]["cost_cny"]["total"] / r["chars"] for r in done if r["chars"]]),
            # The same checks priced as the product meter prices them (a cache hit like any input token).
            "product_meter_cost_cny": _stats([metering.PRODUCTION_PRICES.cost(r["check_cost"]["tokens"]["input_miss"], r["check_cost"]["tokens"]["input_hit"],
                                                                              r["check_cost"]["tokens"]["reasoning"] + r["check_cost"]["tokens"]["visible_output"]) for r in done]),
        },
        "selections": selections,
        "check_totals": meter.summary("check"),
        "setup_totals": meter.summary("setup"),
    }


def assert_formal(args, lf: LongformSet, provider) -> None:
    problems = []
    if args.replay != "off":
        problems.append("replay_must_be_off")
    if args.only or args.smoke or args.subset or args.chapter_limit:
        problems.append("formal_runs_the_whole_set")
    if lf.kind != "formal":
        problems.append("set_kind_is_not_formal")
    hash_file = lf.root / SET_HASH_FILE
    if not hash_file.exists() or hash_file.read_text(encoding="utf-8").split()[0] != compute_set_hash(lf.root, lf.data):
        problems.append("set_not_frozen")
    if not thresholds.APPROVED:
        problems.append("thresholds_not_approved")
    if FORMAL_RUNTIME["prompt_version"] is None or prompt_version() != FORMAL_RUNTIME["prompt_version"]:
        problems.append("prompt_version_not_pinned")
    if provider.model != FORMAL_RUNTIME["model"] or provider.review_thinking != FORMAL_RUNTIME["review_thinking"]:
        problems.append("model_or_thinking")
    if os.environ.get("CONTINUITY_REVIEW_CONCURRENCY") != FORMAL_RUNTIME["concurrency"]:
        problems.append("concurrency_not_production")
    if problems:
        raise RuntimeError("longform_formal_preconditions:" + ",".join(problems))


def select_targets(args, lf: LongformSet) -> list[Target]:
    chosen = lf.targets
    if args.only:
        chosen = [t for t in chosen if t.id in set(args.only)]
    if args.smoke:
        chosen = [t for t in chosen if t.smoke]
    if args.subset:
        ids = set((lf.data.get("subsets") or {}).get(args.subset) or [])
        chosen = [t for t in chosen if t.id in ids]
    if args.chapter_limit:
        chosen = [t for t in chosen if t.chapter.index <= args.chapter_limit]
    return chosen


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", required=True, type=pathlib.Path, help="set directory")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=("dev", "formal"), default="dev")
    parser.add_argument("--replay", choices=metering.REPLAY_MODES, default="off")
    parser.add_argument("--budget-cny", type=float, default=DEFAULT_BUDGET_CNY)
    parser.add_argument("--live-check", action="store_true", help="dev only: replay the setup but call the model live for every check, so timings stay valid")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--subset")
    parser.add_argument("--chapter-limit", type=int)
    parser.add_argument("--cache-hit-price", type=float, help="CNY per million cache-hit input tokens, for the discount estimate only")
    parser.add_argument("--results-dir", type=pathlib.Path, default=ROOT / "evaluation" / "results")
    parser.add_argument("--allow-incomplete-set", action="store_true",
                        help="dev only: accept a set that passes the structure check but not the length/count rules (e.g. the template)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.allow_incomplete_set and args.mode == "formal":
        raise RuntimeError("longform_formal_needs_complete_set")
    lf = load(args.set)
    errors, _ = validate(lf, structure_only=args.allow_incomplete_set)
    if errors:
        raise RuntimeError(f"longform_set_invalid:{len(errors)} errors; run evaluation.longform.validate")
    targets = select_targets(args, lf)
    if not targets:
        raise RuntimeError("longform_no_targets_selected")
    out = args.results_dir / f"longform-{lf.data['set_id']}-{args.run_id}.json"
    checkpoint = out.with_name(out.stem + "-checkpoint.json")
    if out.exists() or checkpoint.exists():
        raise FileExistsError(out if out.exists() else checkpoint)

    discount = None
    if args.cache_hit_price is not None:
        p = metering.GATE_PRICES
        discount = metering.Prices(p.input_miss, args.cache_hit_price, p.output)
    budget = thresholds.FORMAL_BUDGET_CNY if args.mode == "formal" else args.budget_cny
    meter = metering.Meter(budget_cny=budget, replay=args.replay, discount_prices=discount, live_phases=("check",) if args.live_check else ())
    provider = metering.MeteredProvider(client_factory=meter.client_factory)
    if not provider.available:
        # Replay-only runs send nothing, but the provider still has to be configured; any
        # placeholder key will do there.
        raise RuntimeError("longform_provider_unavailable: set CONTINUITY_PROVIDER/MODEL/BASE_URL/API_KEY/REVIEW_THINKING")
    if args.mode == "formal":
        assert_formal(args, lf, provider)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "targets": len(targets), "mode": args.mode, "replay": args.replay,
                          "budget_cny": budget, "prompt_version": prompt_version(), "model": provider.model,
                          "out": out.name}, ensure_ascii=False))
        return 0

    args.results_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict] = {}
    for target in targets:
        if meter.stop_reason:
            break
        try:
            records[target.id] = run_target(lf, target, provider, meter)
        except Exception:
            # A refusal by the budget cap or the replay cache can surface as an app error during
            # setup; the run stops there. Anything else is a real failure and propagates.
            if meter.stop_reason:
                break
            raise
        if meter.stop_reason:
            records[target.id]["stopped_during_target"] = meter.stop_reason
        checkpoint.write_text(json.dumps({"run_id": args.run_id, "meter": meter.describe(), "records": records},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
        row = records[target.id]
        print(json.dumps({"target": target.id, "status": row["status"], "seconds": row["seconds"],
                          "cards": len(row["issues"]), "cost_cny": round(row["check_cost"]["cost_cny"]["total"], 4),
                          "spent_cny": round(meter.spent_cny, 4)}, ensure_ascii=False), flush=True)

    scoped = LongformSet(lf.root, lf.data, lf.works, [t for t in targets if t.id in records] if meter.stop_reason else targets, [])
    report = {
        "kind": f"longform_{lf.kind}_{args.mode}" + ("" if len(targets) == len(lf.targets) else "_partial"),
        "set_id": lf.data["set_id"], "set_sha256": compute_set_hash(lf.root, lf.data), "run_id": args.run_id,
        "adapter": ADAPTER, "mode": args.mode, "prompt_version": prompt_version(), "model": provider.model,
        "review_thinking": provider.review_thinking, "concurrency": os.environ.get("CONTINUITY_REVIEW_CONCURRENCY", "1"),
        "meter": meter.describe(), "stopped_early": meter.stop_reason,
        "targets_selected": [t.id for t in targets], "targets_run": list(records),
        "quality": score_run(scoped, records),
        "cost_time": cost_time(lf, records, meter),
        "records": records,
    }
    report["threshold_result"] = thresholds.evaluate(report) if args.mode == "formal" and not meter.stop_reason else None
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    quality, cost = report["quality"], report["cost_time"]["single_chapter"]
    print(json.dumps({"out": out.name, "targets": len(records), "stopped_early": meter.stop_reason,
                      "conflict_recall": quality["conflict_recall"], "ie_recall": quality["insufficient_evidence_recall"],
                      "median_seconds": cost["seconds"]["median"], "mean_cost_cny": cost["cost_cny"]["mean"],
                      "spent_cny": round(meter.spent_cny, 4)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
