"""Phase-4 tuning harness: the screened review in process, real model, metered, per-dispatch diagnostics.

    python -m evaluation.longform.review_eval --set <set_dir> --facts <fact_coverage report> --run-id <id>
        [--replay off|record|replay|replay_or_record] [--budget-cny 3] [--only TARGET ...]
        [--start-effort high|medium] [--max-claims N] [--passages N]

Each target chapter N goes through ContinuityEngine.execute exactly as a draft check would, but
without the app around it: chapters 1..N-1 are the sources and the facts of a real import (a
fact_coverage report) from chapters before N are the confirmed Memory. That skips the per-target
import and Memory setup of evaluation.longform.run, so a variant can be tried for the price of the
check alone. Quality is scored with score.score_run; cost and time per chapter come from the meter,
with one row per dispatch (purpose, effort, tokens, finish reason, claims and passages sent) so
runaway thinking and contract repairs can be traced. --start-effort, --max-claims and --passages are
tuning knobs for this harness only. Timings are only valid without replay. Never on a formal set.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.longform import meter as metering  # noqa: E402  (puts backend on sys.path)
from evaluation.longform.schema import LongformSet, Target, load  # noqa: E402
from evaluation.longform.score import normalise_issue, score_run  # noqa: E402
from evaluation.longform.screen_eval import target_inputs  # noqa: E402

from app import engine as engine_module  # noqa: E402
from app import provider as provider_module  # noqa: E402
from app import review_screening as screening  # noqa: E402
from app.engine import SCREENED_PROMPT_VERSION, ContinuityEngine  # noqa: E402
from app.provider import request_prompt_and_budget  # noqa: E402


class Recorder:
    """Wraps the metered provider: one row per evaluate with what was sent."""

    def __init__(self, provider):
        self._provider, self.rows = provider, []

    def __getattr__(self, name):
        return getattr(self._provider, name)

    def evaluate(self, request):
        row = {"task": request.get("task") or ("review_repair" if "contract_repair" in request else "review"),
               "claims": len(request.get("claims") or request.get("sentences") or []),
               "passages": len({span["id"] for claim in request.get("claims") or [] for span in claim.get("allowed_evidence") or []}),
               "units": request_prompt_and_budget(request)[1],
               "repair_reason": (request.get("contract_repair") or {}).get("reason_code")}
        started = time.perf_counter()
        try:
            result = self._provider.evaluate(request)
        except Exception as error:
            row.update(error=type(error).__name__, seconds=round(time.perf_counter() - started, 1))
            self.rows.append(row)
            raise
        row.update(input_tokens=result.input_tokens, output_tokens=result.output_tokens, seconds=round(time.perf_counter() - started, 1))
        self.rows.append(row)
        return result


def review_target(provider, lf: LongformSet, target: Target, facts: list[dict], meter: metering.Meter) -> dict:
    sources, memory, claims, _ = target_inputs(lf, target, facts)
    body = target.chapter.body
    data = {"pipeline": "screened", "draft": {"id": target.id, "revision": 1, "body": body}, "claims": claims,
            "memory": memory, "sources": sources, "contexts": {"draft": body}}
    recorder = Recorder(provider)
    started = time.perf_counter()
    with meter.scope("check", target.id):
        result = ContinuityEngine(recorder).execute(data)
    seconds = round(time.perf_counter() - started, 1)
    text_of = {claim["id"]: claim["text"] for claim in claims}
    chapter_of = {source["chapter_id"]: source["chapter_number"] for source in sources}
    issues = []
    for issue in result.get("issues") or []:
        start = body.find(text_of[issue["claim_span_id"]])
        issues.append(normalise_issue(issue.get("nature"), issue.get("category"), (start, start + len(text_of[issue["claim_span_id"]])),
                                      [chapter_of[e["chapter_id"]] for e in issue.get("evidence") or [] if e["chapter_id"] in chapter_of]))
    return {"target_id": target.id, "status": result["status"], "error_code": result.get("error_code"), "seconds": seconds,
            "chars": len(body), "sentence_count": len(claims), "undecided_count": result.get("undecided_claim_count", 0),
            "undecided": result.get("undecided_claims") or [], "screening": result.get("screening"), "issues": issues,
            "normalizations": result.get("contract_normalizations") or [],
            "check_cost": meter.summary("check", target.id), "requests": recorder.rows,
            "dispatches": [{key: row[key] for key in ("purpose", "effort", "finish_reason", "tokens", "latency_ms")}
                           for row in meter.records if row["target"] == target.id]}


def _stats(values):
    return {"mean": statistics.fmean(values), "median": statistics.median(values), "max": max(values)} if values else None


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", required=True, type=pathlib.Path)
    parser.add_argument("--facts", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--replay", choices=metering.REPLAY_MODES, default="replay_or_record")
    parser.add_argument("--budget-cny", type=float, default=3.0)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--start-effort", choices=("high", "medium"), default="high")
    parser.add_argument("--max-claims", type=int, help="claims per thinking review")
    parser.add_argument("--passages", type=int)
    parser.add_argument("--results-dir", type=pathlib.Path, default=ROOT / "evaluation" / "results")
    args = parser.parse_args(argv)
    lf = load(args.set)
    if lf.errors:
        raise RuntimeError(f"longform_set_invalid:{len(lf.errors)}")
    if lf.kind == "formal":
        raise RuntimeError("review_eval_never_runs_on_the_formal_set")
    out = args.results_dir / f"longform-review-{lf.data['set_id']}-{args.run_id}.json"
    if out.exists():
        raise FileExistsError(out)
    if args.max_claims:
        screening.DEEP_MAX_CLAIMS = args.max_claims
    if args.passages:
        screening.VERIFY_MAX_PASSAGES = args.passages
    if args.start_effort != "high":
        @contextlib.contextmanager
        def scope():
            token = provider_module._review_effort.set({"effort": args.start_effort})
            try:
                yield
            finally:
                provider_module._review_effort.reset(token)
        engine_module.review_effort_scope = scope
    facts = json.loads(args.facts.read_text(encoding="utf-8"))["facts"]
    meter = metering.Meter(budget_cny=args.budget_cny, replay=args.replay)
    provider = metering.MeteredProvider(client_factory=meter.client_factory)
    if not provider.available or provider.review_thinking != "high":
        raise RuntimeError("review_eval needs CONTINUITY_PROVIDER/MODEL/BASE_URL/API_KEY and CONTINUITY_REVIEW_THINKING=high")
    targets = [t for t in lf.targets if not args.only or t.id in set(args.only)]
    records = {}

    def one(target):
        if meter.stop_reason:
            return
        try:
            records[target.id] = review_target(provider, lf, target, facts.get(target.work, []), meter)
        except metering.BudgetExceeded:
            return
        row = records[target.id]
        print(json.dumps({"target": target.id, "status": row["status"], "error": row["error_code"], "seconds": row["seconds"],
                          "cards": len(row["issues"]), "reviewed": (row["screening"] or {}).get("reviewed"),
                          "cost_cny": round(row["check_cost"]["cost_cny"]["total"], 4), "spent_cny": round(meter.spent_cny, 4)}, ensure_ascii=False), flush=True)

    # Targets run one after another: the meter attributes dispatches to the current target.
    for target in targets:
        one(target)
    done = [t for t in targets if t.id in records]
    quality = score_run(LongformSet(lf.root, lf.data, lf.works, done, []), records)
    completed = [r for r in records.values() if r["status"] == "completed"]
    report = {
        "kind": "longform_review_eval", "set_id": lf.data["set_id"], "run_id": args.run_id, "prompt_version": SCREENED_PROMPT_VERSION,
        "knobs": {"start_effort": args.start_effort, "max_claims": screening.DEEP_MAX_CLAIMS,
                  "passages": screening.VERIFY_MAX_PASSAGES}, "model": provider.model, "stopped_early": meter.stop_reason,
        "quality": {key: value for key, value in quality.items() if not isinstance(value, (list, dict))},
        "per_point": quality.get("per_point"),
        "cost_time": {"seconds": _stats([r["seconds"] for r in completed]),
                      "cost_cny": _stats([r["check_cost"]["cost_cny"]["total"] for r in completed]),
                      "timing_valid": all(r["check_cost"]["replayed_dispatches"] == 0 for r in records.values())},
        "totals": meter.summary("check"), "meter": meter.describe(), "records": records,
    }
    args.results_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": out.name, **report["quality"], "cost_time": report["cost_time"], "spent_cny": round(meter.spent_cny, 4)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
