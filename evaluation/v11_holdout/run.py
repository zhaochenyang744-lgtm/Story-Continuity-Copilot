"""V11 held-out runner: import each work, let Flash build Memory, then check every draft.

Unlike the V5-V10 runners this does not load fixture workspaces or look up seeded demo
projects; `evaluation/run_eval.py`'s `project_for_seed` no longer resolves, because a new
account starts with no projects. Each work here goes through the real author path: import
the full source, accept every Memory candidate, then replace the draft per case.

Scoring maps the issue's nature, not its status. `state_change` asserts that a prior state
and a later transition can both be true, which is a no-conflict verdict; scoring it as a
conflict, as the status field would, counts a correct judgement as a false positive.

    confirmed_conflict, possible_conflict -> conflict
    state_change                          -> no_conflict
    insufficient_evidence                 -> insufficient_evidence

Retrieval reach, Memory coverage, the timeless-rule premise and no_conflict card noise are
recorded as diagnostics and never decide a case.

Usage: python -m evaluation.v11_holdout.run --run-id <id> [--only ID ...] [--dry-run]
Output: evaluation/results/eval-v11-<run-id>.json (metadata only; no model prose is kept,
explanations are stored as SHA-256).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SCC_DISABLE_DEFAULT_APP", "1")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import AppPaths  # noqa: E402
from app.engine import PROMPT_VERSION  # noqa: E402
from app.main import create_app  # noqa: E402
from app.provider import DeepSeekProvider  # noqa: E402
from app.stage13 import Stage13Settings  # noqa: E402
from evaluation.v11_holdout.thresholds import evaluate as evaluate_thresholds  # noqa: E402

DEFAULT_SET = "eval_set_v11_authoring"
CLASSES = ("conflict", "no_conflict", "insufficient_evidence")
# Infrastructure, not an answer: retried once and recorded. A contract or schema failure is the
# model's answer and is never retried.
RETRYABLE_ERRORS = {"provider_timeout", "provider_unavailable", "provider_error"}
RETRYABLE_STATUSES = {"timed_out"}
NATURE_CLASS = {"confirmed_conflict": "conflict", "possible_conflict": "conflict",
                "state_change": "no_conflict", "insufficient_evidence": "insufficient_evidence"}
CLASS_PRECEDENCE = ("conflict", "insufficient_evidence", "no_conflict")
# The formal run is pinned to the deployed configuration, not to whatever the shell exports.
RUNTIME_CONTRACT = {"model": "deepseek-flash", "review_thinking": "high",
                    "prompt_version": "continuity-review-v22-settled-possible-conflict"}


def load_case_set(set_dir: pathlib.Path) -> dict:
    """Read the frozen set and fail closed if its bytes no longer match the recorded hash."""
    raw = (set_dir / "cases.json").read_bytes()
    recorded = (set_dir / "cases.sha256").read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(raw).hexdigest()
    if actual != recorded:
        raise RuntimeError(f"holdout_case_set_hash_mismatch:{actual}:{recorded}")
    return json.loads(raw.decode("utf-8"))


def assert_runtime(provider: DeepSeekProvider) -> None:
    checks = {"provider": os.environ.get("CONTINUITY_PROVIDER", "").lower() == "deepseek",
              "model": provider.model == RUNTIME_CONTRACT["model"],
              "review_thinking": provider.review_thinking == RUNTIME_CONTRACT["review_thinking"],
              "prompt_version": PROMPT_VERSION == RUNTIME_CONTRACT["prompt_version"],
              "available": provider.available}
    if not all(checks.values()):
        raise RuntimeError("v11_runtime_contract_invalid:" + ",".join(k for k, ok in checks.items() if not ok))


class FingerprintRecorder:
    """Captures system_fingerprint per response.

    CONTINUITY_MODEL "deepseek-flash" is a rolling alias, so the model name alone does not
    identify the build that produced a result. The product drops the field, so the client is
    wrapped here rather than changing it.
    """

    def __init__(self):
        self.seen: list[str] = []

    def factory(self):
        recorder = self

        class Client(httpx.Client):
            def post(self, *args, **kwargs):
                response = super().post(*args, **kwargs)
                try:
                    fingerprint = response.json().get("system_fingerprint")
                except ValueError:
                    fingerprint = None
                if fingerprint and fingerprint not in recorder.seen:
                    recorder.seen.append(fingerprint)
                return response

        return Client(timeout=httpx.Timeout(DeepSeekProvider.timeout_seconds))


def data(response):
    if response.status_code >= 300:
        raise RuntimeError(f"{response.status_code} {response.text[:300]}")
    return response.json()["data"]


def open_work(work: dict, provider) -> tuple[TestClient, str, list[dict], dict[str, str]]:
    """Import one work, accept every Memory candidate, and return the client and Memory snapshot."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="v11-holdout-"))
    app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                     provider=provider, executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
    client = TestClient(app)
    idem = lambda: {"Idempotency-Key": str(uuid.uuid4())}
    data(client.post("/api/auth/register", json={
        "account_name": f"v11{uuid.uuid4().hex[:8]}", "display_name": "V11 holdout",
        "password": "v11-holdout-local-pass-123", "recovery_email": "v11@example.test"}, headers=idem()))
    preview = data(client.post("/api/imports/preview",
                               files={"file": ("work.md", work["source"].encode("utf-8"), "text/markdown")}, headers=idem()))
    project = data(client.post(f"/api/imports/{preview['import_id']}/commit", json={
        "confirm": True, "title": work["title"],
        "chapter_preview_ids": [row["preview_id"] for row in preview["detected"]["chapters"]]}, headers=idem()))["project"]["id"]
    listing = data(client.get(f"/api/projects/{project}/chapters?include=excerpt"))["chapters"]
    chapters = {row["id"]: row["title"] for row in listing}
    # Retrieval traces report span ids only, so the span-to-chapter map is built once per work.
    chapters.update({span["span_id"]: row["title"] for row in listing for span in (row.get("source_spans") or [])})
    init = data(client.post(f"/api/projects/{project}/memory/initializations",
                            json={"source_revision": 1}, headers=idem()))["initialization"]
    if init.get("status") == "failed":
        raise RuntimeError(f"v11_memory_initialization_failed:{work['key']}:{init.get('error_code')}")
    for candidate in init.get("candidates") or []:
        client.post(f"/api/projects/{project}/memory/initializations/{init['id']}/candidates/{candidate['id']}/decision",
                    json={"decision": "accepted"}, headers=idem())
    data(client.post(f"/api/projects/{project}/memory/initializations/{init['id']}/commit",
                     json={"confirm": True}, headers=idem()))
    memory = [{"memory_type": row["memory_type"], "predicate": row["predicate"], "subject": row["subject"],
               "chapter": (row.get("source") or {}).get("chapter_title")
                          or chapters.get((row.get("source") or {}).get("chapter_id"), "?")}
              for row in (init.get("candidates") or [])]
    return client, project, memory, chapters


def predicted_class(issues: list[dict]) -> tuple[str, str | None]:
    """Fold the run's issue natures into one class, conflict taking precedence."""
    classes = {NATURE_CLASS.get(issue.get("nature")) for issue in issues}
    for label in CLASS_PRECEDENCE:
        if label in classes:
            category = next((issue.get("category") for issue in issues
                             if NATURE_CLASS.get(issue.get("nature")) == label), None)
            return label, category
    return "no_conflict", None


def check_once(client: TestClient, project: str, case: dict) -> tuple[dict, float]:
    idem = lambda: {"Idempotency-Key": str(uuid.uuid4())}
    draft = data(client.get(f"/api/projects/{project}"))["current_draft"]
    patched = data(client.patch(f"/api/projects/{project}/drafts/{draft['id']}",
                                json={"base_revision": draft["revision"], "body": case["draft"]}, headers=idem()))
    started = time.perf_counter()
    run = data(client.post(f"/api/projects/{project}/checks",
                           json={"draft_id": draft["id"], "draft_revision": patched["revision"]}, headers=idem()))
    view = data(client.get(f"/api/projects/{project}/checks/{run['run_id']}?include=issues,evidence,metrics"))
    for _ in range(120):
        if view["status"] not in {"queued", "running"}:
            break
        time.sleep(1)
        view = data(client.get(f"/api/projects/{project}/checks/{run['run_id']}?include=issues,evidence,metrics"))
    return view, round(time.perf_counter() - started, 1)


def run_case(client: TestClient, project: str, case: dict, chapters: dict[str, str], memory: list[dict]) -> dict:
    """One case, with a single retry reserved for infrastructure failures, never for an answer."""
    view, seconds = check_once(client, project, case)
    retried = False
    if view["status"] in RETRYABLE_STATUSES or view.get("error_code") in RETRYABLE_ERRORS:
        retried = True
        first = {"status": view["status"], "error_code": view.get("error_code"), "seconds": seconds}
        view, seconds = check_once(client, project, case)
        seconds = round(seconds + first["seconds"], 1)
    issues = view.get("issues") or []
    expected_chapters = set(case["evidence"])
    cited = {chapters.get(item.get("chapter_id"), "?") for issue in issues for item in (issue.get("evidence") or [])}
    retrieved = {chapters.get(span_id, "?")
                 for trace in (view.get("metrics", {}).get("retrieval") or [])
                 for span_id in (trace.get("returned_span_ids") or [])}
    label, category = predicted_class(issues)
    return {
        "case_id": case["id"], "corpus": case["corpus"],
        "expected_class": case["expected_class"], "predicted_class": label,
        "expected_category": case["category"], "predicted_category": category,
        "designated_regression": case["designated_regression"],
        "status": view["status"], "error_code": view.get("error_code"), "seconds": seconds,
        "infrastructure_retry": first if retried else None,
        "natures": sorted(issue.get("nature") for issue in issues),
        "issue_count": len(issues),
        "explanation_sha256": [hashlib.sha256((issue.get("explanation") or "").encode("utf-8")).hexdigest()
                               for issue in issues],
        "metrics": {key: view.get("metrics", {}).get(key) for key in ("latency_ms", "input_tokens", "output_tokens")},
        "contract_normalization_count": view.get("metrics", {}).get("contract_normalization_count"),
        # Diagnostics. None of these decide the case.
        "diagnostics": {
            "expected_chapters": sorted(expected_chapters),
            "cited_expected_chapters": sorted(cited & expected_chapters),
            # None, not False, when the review emitted no issue and so cited nothing.
            "citation_reached_expected": bool(cited & expected_chapters) if issues else None,
            "retrieval_reached_expected": bool(retrieved & expected_chapters) if retrieved else None,
            "cards_on_no_conflict_case": len(issues) if case["expected_class"] == "no_conflict" else None,
            "state_change_present": "state_change" in {issue.get("nature") for issue in issues},
            "static_canon_from_expected_chapter": sorted(
                item["subject"] for item in memory
                if item["memory_type"] == "static_canon" and item["chapter"] in expected_chapters),
        },
    }


def score(results: list[dict]) -> dict:
    matrix = {expected: {predicted: 0 for predicted in CLASSES} for expected in CLASSES}
    for row in results:
        matrix[row["expected_class"]][row["predicted_class"]] += 1
    per_class = {}
    for label in CLASSES:
        tp = matrix[label][label]
        fp = sum(matrix[other][label] for other in CLASSES if other != label)
        fn = sum(matrix[label][other] for other in CLASSES if other != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_class[label] = {"precision": precision, "recall": recall,
                            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}
    conflicts = [row for row in results if row["expected_class"] == "conflict"]
    designated = [row for row in results if row["designated_regression"]]
    no_conflict_total = sum(matrix["no_conflict"].values())
    noisy = sum(bool(row["diagnostics"]["cards_on_no_conflict_case"]) for row in results
                if row["expected_class"] == "no_conflict")
    return {
        "confusion_matrix": matrix,
        "per_class": per_class,
        "macro_f1": sum(per_class[label]["f1"] for label in CLASSES) / len(CLASSES),
        "no_conflict_false_positive_rate": (no_conflict_total - matrix["no_conflict"]["no_conflict"]) / no_conflict_total if no_conflict_total else 0.0,
        "conflict_category_accuracy": (sum(row["predicted_category"] == row["expected_category"] for row in conflicts) / len(conflicts)) if conflicts else 0.0,
        "designated": {"total": len(designated),
                       "class_and_category_correct": sum(row["predicted_class"] == "conflict" and row["predicted_category"] == row["expected_category"] for row in designated),
                       "confirmed_conflict": sum("confirmed_conflict" in row["natures"] for row in designated),
                       "case_ids": [row["case_id"] for row in designated]},
        "terminal": dict(collections.Counter(f"{row['status']}:{row['error_code']}" for row in results)),
        # Reported, never gating.
        "diagnostics": {
            "no_conflict_cases_with_any_card": noisy,
            "no_conflict_total": no_conflict_total,
            # citation_reached_expected is None when a case emitted no issue, so count truth only.
            "citation_reached_expected": sum(1 for row in results if row["diagnostics"]["citation_reached_expected"]),
            "retrieval_reached_expected": sum(1 for row in results if row["diagnostics"]["retrieval_reached_expected"]),
            "state_change_cases": [row["case_id"] for row in results if row["diagnostics"]["state_change_present"]],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--set", default=DEFAULT_SET, help="authoring directory under evaluation/")
    parser.add_argument("--only", nargs="*", help="case ids; default is the whole set")
    parser.add_argument("--dry-run", action="store_true", help="verify the set, contract and output path, call nothing")
    args = parser.parse_args()

    set_dir = ROOT / "evaluation" / args.set
    case_set = load_case_set(set_dir)
    # eval_set_v11_authoring -> v11, so a later set writes its own files without a code change.
    label = args.set.split("_")[2] if args.set.startswith("eval_set_") else args.set
    out = ROOT / "evaluation/results" / f"eval-{label}-{args.run_id}.json"
    checkpoint = out.with_name(out.stem + "-checkpoint.json")
    if out.exists() or checkpoint.exists():
        raise FileExistsError(out if out.exists() else checkpoint)
    selected = set(args.only) if args.only else None
    cases = [case for case in case_set["cases"] if not selected or case["id"] in selected]
    if not cases:
        raise RuntimeError("v11_no_cases_selected")

    recorder = FingerprintRecorder()
    provider = DeepSeekProvider(client_factory=recorder.factory)
    assert_runtime(provider)
    if args.dry_run:
        print(f"dry run ok: {len(cases)} cases, prompt {PROMPT_VERSION}, model {provider.model}, out {out.name}")
        return 0

    results, memories = [], {}
    for work in case_set["corpora"]:
        work_cases = [case for case in cases if case["corpus"] == work["key"]]
        if not work_cases:
            continue
        client, project, memory, chapters = open_work(work, provider)
        memories[work["key"]] = memory
        for case in work_cases:
            results.append(run_case(client, project, case, chapters, memory))
            # Written after every case: a held-out run costs real calls, and a later failure in
            # scoring must never be able to destroy the record of what the model answered.
            checkpoint.write_text(json.dumps({"run_id": args.run_id, "memory_snapshot": memories,
                                              "case_results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({key: results[-1][key] for key in ("case_id", "expected_class", "predicted_class", "status", "seconds")},
                             ensure_ascii=False), flush=True)
        client.close()

    report = {
        "kind": f"{label}_holdout_formal" if selected is None else f"{label}_holdout_partial",
        "case_set": args.set,
        "run_id": args.run_id,
        "case_set_sha256": hashlib.sha256((set_dir / "cases.json").read_bytes()).hexdigest(),
        "prompt_version": PROMPT_VERSION,
        "model": provider.model,
        "review_thinking": provider.review_thinking,
        "system_fingerprints": recorder.seen,
        "scoring": {"nature_to_class": NATURE_CLASS, "precedence": list(CLASS_PRECEDENCE),
                    "note": "state_change scores as no_conflict; diagnostics never decide a case"},
        "memory_snapshot": memories,
        "metrics": score(results),
        "case_results": results,
    }
    # A partial selection is not a gate result, so the bar is applied only to a whole run.
    report["threshold_result"] = evaluate_thresholds(report["metrics"]) if selected is None else None
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": out.name, "cases": len(results), "fingerprints": recorder.seen,
                      "macro_f1": report["metrics"]["macro_f1"], "terminal": report["metrics"]["terminal"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
