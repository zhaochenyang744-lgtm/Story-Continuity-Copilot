"""A2 runner (SPEC section 4): the change task on works that carry starting materials, three passes for the formal sets.

Each work is imported once, through the product's own import, and its starting materials are put in as the author would have
left them: the facts as the confirmed facts of the first version (the starting materials are given, not extracted, so no
model is asked to find them), the foreshadowing records through the materials API. Every task then runs against those
materials; nothing on a card is confirmed during a pass, so the materials stay as they started.

After each pass every card of that pass is confirmed in full and then undone, each on its own copy of the work's database
(the copy taken after the pass), and the materials are compared with the card and with the start (SPEC section 4).

The cost ledger, the priced provider, the resumable request journal and the product settings are A1's.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from evaluation.assistant_a1 import run as a1
from evaluation.assistant_a1.run import ROOT, Ledger, PricedProvider, chapters, git, rates, response_data, retry, settings, write_json, WRITE_LOCK

import httpx
from fastapi.testclient import TestClient
from app.assistant import ASSISTANT_PROMPT_VERSION
from app.assistant_actions import fact_lineage
from app.config import AppPaths
from app.main import create_app
from app.v2_database import new_id

from ..models import REGISTERED_MODELS
from . import score
from .judge import Judge
from .thresholds import PRE_REGISTRATION

DEV_SETS = ("eval_set_a2_dev", "eval_set_a2t_dev")  # the second: the thread actions' dev set (addendum 7)
# Development material: the dev set, and the spent first formal pair (either set, alone or together, any selection).
SPENT_SETS = score.SPENT_FORMAL_SETS
# The registered formal pair that has not run yet (none until a new pair is registered).
FORMAL_SETS = tuple(name for name in PRE_REGISTRATION["formal_sets"] if name not in SPENT_SETS)
# long_task (v2.1) is a judgement like the others: on an A2 item it is a wrong route, not a broken response.
ROUTES = {"ask", "fix_issue", "recap", "check_passage", "change", "out_of_scope", "long_task"}
PASSWORD = "a2-local-evaluation-pass-123"
THREAD_FIELDS = ("title", "description", "status", "planted_chapter_id", "planted_source_span_id", "resolved_chapter_id",
                 "resolved_source_span_id", "archived_at")
FACT_FIELDS = ("memory_type", "subject", "predicate", "value", "source_span_id")


# --- sets -------------------------------------------------------------------------------------------------------------
def set_names(value):
    names = value.split(",")
    if len(names) != len(set(names)):
        raise ValueError("invalid_sets")
    if (len(names) == 1 and names[0] in DEV_SETS) or set(names) <= set(SPENT_SETS) or (FORMAL_SETS and sorted(names) == sorted(FORMAL_SETS)):
        return names
    raise ValueError("invalid_sets")


def set_names_arg(value):
    try:
        set_names(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None
    return value


def workspaces(out):
    """Where a run keeps its works' files: a short name beside the results (as A3's). Named after the checkpoint, a run over three
    spent sets passed Windows' 260-character limit and its database would not open (regression tune1-p58, 2026-10-27)."""
    return out["checkpoint"].parent / ("ws-" + hashlib.sha256(out["checkpoint"].name.encode("utf-8")).hexdigest()[:12])


def readable(name):
    return name in DEV_SETS or name in SPENT_SETS


def validate_set(name):
    """The set's own checker, every byte of its output discarded (a sealed set's numbers are not read here either)."""
    check = subprocess.run([sys.executable, "-m", f"evaluation.{name}.check"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check.returncode:
        raise ValueError("set_structure_or_hash_invalid")


def load_set(name):
    directory = ROOT / "evaluation" / name
    data = json.loads((directory / "tasks.json").read_text(encoding="utf-8"))
    data["manifest_sha256"] = hashlib.sha256((directory / "set.sha256").read_bytes()).hexdigest()
    for work in data["works"]:
        work["source"] = (directory / work["source_file"]).read_text(encoding="utf-8")
        work["facts"] = json.loads((directory / work["materials"]["facts"]).read_text(encoding="utf-8"))
        work["threads"] = json.loads((directory / work["materials"]["foreshadows"]).read_text(encoding="utf-8"))
    return data


def paths(name, run_id, output=None):
    if not run_id or not all(ch.isalnum() or ch in "_-" for ch in run_id):
        raise ValueError("invalid_run_id")
    base = (output or ROOT / "evaluation/results") / f"a2-{name.replace(',', '+')}-{run_id}"
    return {kind: base.with_name(base.name + "-" + kind + extension) for kind, extension in
            [("report", ".json"), ("markdown", ".md"), ("checkpoint", ".json"), ("audit", ".json")]}


def preflight(args, provider, output=None):
    names = set_names(args.set)
    formal = not all(readable(name) for name in names)
    if formal:
        if args.only is not None:
            raise ValueError("formal_only_forbidden")
        if not args.dry_run and args.runs != 3:
            raise ValueError("formal_requires_three_runs")
        if git("status", "--porcelain", "--", "backend/app", "evaluation/assistant_a2", *[f"evaluation/{n}" for n in names]):
            raise ValueError("formal_dirty_code_forbidden")
    if (not provider.available or provider.model != "deepseek-flash"
            or any(provider.model_for(role) != model for role, model in REGISTERED_MODELS.items())):
        raise ValueError("assistant_model_configuration_invalid")
    if args.judge_model != PRE_REGISTRATION["judging"]["judge_model"]:
        raise ValueError("judge_model_configuration_invalid")
    if not math.isfinite(args.max_cny) or args.max_cny <= 0:
        raise ValueError("max_cny_invalid")
    out = paths(args.set, args.run_id, output)
    if args.resume:
        if not out["checkpoint"].exists():
            raise ValueError("resume_checkpoint_missing")
    elif any(p.exists() for p in out.values()) or workspaces(out).exists():
        raise FileExistsError("run_output_already_exists")
    for name in names:
        validate_set(name)
    if args.only is not None:
        ids = {t["id"] for name in names if readable(name) for t in load_set(name)["tasks"]}
        if not args.only or not set(args.only) <= ids:
            raise ValueError("unknown_or_empty_selection")
    return out


# --- a work with its starting materials ---------------------------------------------------------------------------------
class Work(a1.Work):
    """A1's work (account, import, journaled requests, draft saving, task polling) with A2's starting materials."""

    def prepare(self, work, upto):
        self.response("POST", "/api/auth/register", json={"account_name": self.account, "display_name": "A2", "password": PASSWORD,
                                                          "recovery_email": "a2@example.test"})
        response_data(self.client.post("/api/auth/login", json={"account_name": self.account, "password": PASSWORD}))
        source = "".join(chapters(work["source"])[:upto])
        preview = self.request("POST", "/api/imports/preview", files={"file": ("work.md", source.encode("utf-8"), "text/markdown")})
        self.project = self.request("POST", f"/api/imports/{preview['import_id']}/commit", json={
            "confirm": True, "title": work["title"], "chapter_preview_ids": [c["preview_id"] for c in preview["detected"]["chapters"]]})["project"]["id"]
        self.base = f"/api/projects/{self.project}"
        self.listing = self.request("GET", self.base + "/chapters?include=excerpt")["chapters"]
        by_number = {c["number"]: c for c in self.listing}
        if len(by_number) != len(chapters(work["source"])):
            raise RuntimeError("import_chapter_count_mismatch")
        self.root = self.state_path.parent
        mapping_path = self.root / "materials.json"
        if mapping_path.exists():  # a resumed run: the facts went in before the crash
            self.facts = json.loads(mapping_path.read_text(encoding="utf-8"))["facts"]
        else:
            self.facts = self._put_facts(work["facts"], by_number)
            write_json(mapping_path, {"facts": self.facts})  # before anything else can fail, so a resume never puts them in twice
        self.threads = []
        version = 0
        for item in work["threads"]:
            planted, resolved = by_number[item["planted_chapter"]], by_number.get(item.get("resolved_chapter"))
            body = {"base_foreshadow_version": version, "title": item["title"], "description": item["description"], "status": item["status"],
                    "planted_chapter_id": planted["id"], "planted_source_span_id": planted["source_spans"][0]["span_id"]}
            if resolved:
                body.update(resolved_chapter_id=resolved["id"], resolved_source_span_id=resolved["source_spans"][0]["span_id"])
            self.threads.append(self.request("POST", self.base + "/foreshadows", json=body)["item"]["id"])
            version += 1
        write_json(mapping_path, {"facts": self.facts, "threads": self.threads})
        self.start = snapshot(self.app.state.database, self.project)
        self.initialization = {"facts": len(self.facts), "threads": len(self.threads)}

    def _put_facts(self, facts, by_number):
        """The starting facts as the confirmed facts of the first version, each sourced at the first span of its chapter."""
        db = self.app.state.database
        lineages = []
        with db.connection() as c:
            version = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (self.project,)).fetchone()[0]
            for fact in facts:
                record = new_id("mem")
                c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (record, self.project, version, fact["memory_type"], fact["subject"], fact["predicate"], fact["value"],
                                                             by_number[fact["chapter"]]["source_spans"][0]["span_id"], "author_confirmed", None, None, None))
                lineages.append(record)
        return lineages

    def route(self, body):
        """One routing request, journaled; the six uses of v2.0 are the valid answers."""
        if self.ledger:
            self.ledger.phase = "route"
        start = time.perf_counter()
        response = self.response("POST", self.base + "/assistant/route", json=body)
        elapsed = response.extensions.get("a1_route_elapsed_seconds", time.perf_counter() - start)
        payload = response.json() if response.content else {}
        if response.status_code >= 300:
            error = (payload or {}).get("error") or {}
            return {"status": "failed", "http_status": response.status_code, "error_code": error.get("code", f"http_{response.status_code}"),
                    "retryable": response.status_code >= 500, "elapsed_seconds": elapsed}
        result = payload.get("data", payload)
        if not isinstance(result, dict) or result.get("route") not in ROUTES:
            return {"status": "failed", "error_code": "route_schema_invalid", "retryable": False, "elapsed_seconds": elapsed}
        return {**result, "status": "completed", "elapsed_seconds": elapsed}

    def card(self, task_id):
        """The card of a task as stored, each item with its number in the starting materials (None for an added fact)."""
        facts = {lineage: i for i, lineage in enumerate(self.facts, 1)}
        threads = {thread: i for i, thread in enumerate(self.threads, 1)}
        with self.app.state.database.connection() as c:
            rows = c.execute("SELECT * FROM assistant_changes WHERE task_id=? ORDER BY ordinal", (task_id,)).fetchall()
        items = []
        for row in rows:
            index = facts.get(row["target_id"]) if row["kind"] == "change_fact" else threads.get(row["target_id"]) if row["kind"] in THREAD_KINDS else None
            items.append({"id": row["id"], "label": f"C{row['ordinal']}", "kind": row["kind"], "target_id": row["target_id"], "index": index,
                          "before": json.loads(row["before_json"]), "after": json.loads(row["after_json"]), "display": json.loads(row["display_json"]),
                          "evidence": json.loads(row["evidence_json"]), "status": row["status"]})
        return items


def snapshot(db, project):
    """The materials a card may touch: the confirmed facts of the current version by lineage, and every thread."""
    with db.connection() as c:
        version = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (project,)).fetchone()[0]
        facts = {fact_lineage(f["id"]): {k: f[k] for k in FACT_FIELDS} for f in db._confirmed_memory(c, project, version)}
        threads = {r["id"]: {k: r[k] for k in THREAD_FIELDS} for r in c.execute("SELECT * FROM v2_foreshadows WHERE project_id=?", (project,))}
    return {"facts": facts, "threads": threads}


# The thread actions (v2.1 adds giving a thread up, its note and a new thread to marking it resolved).
THREAD_KINDS = ("resolve_thread", "abandon_thread", "edit_thread")


def _expected_after(start, items, after):
    """The materials a confirmed card should leave: the start with every item's new values. A new thread has an id and fields
    the program gives it; it is expected as written when every field the item names is what the item says."""
    expected = json.loads(json.dumps(start))
    for item in items:
        if item["kind"] in THREAD_KINDS:
            expected["threads"][item["target_id"]].update({k: v for k, v in item["after"].items() if k in THREAD_FIELDS})
        elif item["kind"] == "add_thread":
            made = after["threads"].get(item["target_id"])
            named = {k: v for k, v in item["after"].items() if k in THREAD_FIELDS}
            expected["threads"][item["target_id"]] = made if made and all(made.get(k) == v for k, v in named.items()) else named
        else:
            expected["facts"][item["target_id"]] = {k: item["after"][k] for k in FACT_FIELDS}
    return expected


def undo_restored(start, final, items):
    """Addendum 8: the materials are as at the start after the card is undone. A thread the card added is archived by its
    undo (as the materials page deletes one), so the threads compared are the live ones, and every added thread must be
    archived; the facts are compared as they are."""
    live = lambda snap: {**snap, "threads": {k: v for k, v in snap["threads"].items() if not v.get("archived_at")}}
    added = [item["target_id"] for item in items if item["kind"] == "add_thread"]
    return live(final) == live(start) and all((final["threads"].get(t) or {}).get("archived_at") for t in added)


def check_card(work, row, provider):
    """Confirm the whole card and undo it again on a copy of the work, and compare (SPEC section 4)."""
    items = [item for item in row.get("changes") or [] if item["status"] == "proposed"]
    task_id = row["assistant"]["id"]
    with tempfile.TemporaryDirectory(prefix="a2-card-") as folder:
        copy = pathlib.Path(folder) / "work"
        shutil.copytree(work.root, copy)
        app = create_app(AppPaths.from_project_root(copy, protected_poc_root=copy / "protected"), provider=provider,
                         executor=lambda fn, *args: fn(*args), settings=settings(work.price))
        client = TestClient(app)
        try:
            response_data(client.post("/api/auth/login", json={"account_name": work.account, "password": PASSWORD}))
            start = snapshot(app.state.database, work.project)
            confirmed = client.post(work.base + f"/assistant/tasks/{task_id}/changes/confirm", headers=a1.idem(),
                                    json={"accepted": [item["id"] for item in items]})
            after = snapshot(app.state.database, work.project)
            undone = [client.post(work.base + f"/assistant/changes/{item['id']}/undo", headers=a1.idem(), json={"confirm": False}).status_code
                      for item in reversed(items)]
            final = snapshot(app.state.database, work.project)
        finally:
            client.close()
    confirm_exact = confirmed.status_code == 200 and after == _expected_after(start, items, after)
    return {"run_number": row["run_number"], "set": row["set"], "task_id": row["task"]["id"], "items": len(items),
            "confirm_status": confirmed.status_code, "confirm_exact": confirm_exact, "undo_statuses": undone,
            "undo_exact": confirmed.status_code == 200 and all(code == 200 for code in undone) and undo_restored(start, final, items),
            "start_matches_prepared": start == work.start}


# --- one task -------------------------------------------------------------------------------------------------------------
def run_task(work, task, shared_draft, row, checkpoint=lambda: None):
    context = dict(task["context"])
    if task["suite"] == "route":
        if context.pop("issue_from", None):
            row["execution_errors"].append("issue_from_not_supported")
            return row
        if context.get("selection"):
            work.save(shared_draft)
        row["route_request"] = {"input": task["input"], "context": context}
        attempts = row.setdefault("route_attempts", [])
        for attempt in range(2):
            result = work.route(row["route_request"])
            if attempt >= len(attempts):
                attempts.append(result)
                checkpoint()
            result = attempts[attempt]
            if not result.get("retryable") or attempt:
                break
        row["route_result"] = result
        row["route_seconds"] = sum(v.get("elapsed_seconds", 0) for v in attempts)
        if result.get("status") != "completed":
            row["execution_errors"].append(result.get("error_code", "route_failed"))
        return row
    kind = "change" if task["suite"] in ("action", "no_action") else task["run_kind"]
    if kind == "recap" or context.get("selection"):
        work.save(shared_draft)
    body = {"kind": kind, "context": {"page": "writing"} if kind == "recap" else context}
    if kind != "recap":
        body["question"] = task["request"]
    start = time.perf_counter()
    view, attempts = retry(lambda: work.assistant(body))
    row["assistant"], row["assistant_retries"] = view, attempts
    row["assistant_seconds"] = sum(v.get("elapsed_seconds", 0) for v in attempts + [view]) or time.perf_counter() - start
    row["assistant_cost_cny"] = sum(((v.get("token_usage", {}).get("input_tokens") or 0) * work.price[0]
                                     + (v.get("token_usage", {}).get("output_tokens") or 0) * work.price[1]) / 1e6 for v in attempts + [view])
    row["changes"] = work.card(view["id"]) if view.get("id") else []
    checkpoint()
    return row


def new_record(task):
    return {"task": task, "auto": {}, "execution_errors": [], "judgments": [], "assistant_cost_cny": 0}


# --- the run ----------------------------------------------------------------------------------------------------------------
def execute(args, datasets, provider, judge, ledger, out):
    names = set_names(args.set)
    tasks = [(name, t) for name in names for t in datasets[name]["tasks"] if not t.get("support") and (args.only is None or t["id"] in args.only)]
    fingerprint = {"sets": names, "runs": args.runs, "only": args.only, "git_commit": git("rev-parse", "HEAD"),
                   "prompt_version": ASSISTANT_PROMPT_VERSION, "assistant_model": provider.assistant_model, "model": provider.model,
                   "models": {role: provider.model_for(role) for role in REGISTERED_MODELS},
                   "judge_model": args.judge_model, "assistant_rates": list(args.assistant_rates), "judge_rates": list(args.judge_rates),
                   "manifests": {n: datasets[n].get("manifest_sha256") for n in names},
                   "code_sha256": hashlib.sha256(b"".join(p.read_bytes() for directory in (ROOT / "backend/app", ROOT / "evaluation/assistant_a2")
                                                          for p in sorted(directory.glob("*.py")))).hexdigest()}
    state_root = workspaces(out)
    if args.resume:
        report = json.loads(out["checkpoint"].read_text(encoding="utf-8"))
        if report["environment"] != fingerprint:
            raise ValueError("resume_environment_changed")
        ledger.calls = report.get("provider_calls", [])
        report["stop_reason"] = None
    else:
        report = {"protocol_version": 1, "set": args.set, "sets": names, "runs": args.runs, "selection": args.only, "run_id": args.run_id,
                  "complete": False, "expected_tasks": len(tasks) * args.runs, "records": [], "card_checks": [], "preparations": [],
                  "environment": fingerprint, "stop_reason": None, "started_at_utc": datetime.now(timezone.utc).isoformat()}
        out["report"].parent.mkdir(parents=True, exist_ok=True)
        with out["checkpoint"].open("x", encoding="utf-8") as f:
            json.dump(report, f)

    def checkpoint():
        with WRITE_LOCK:
            report["usage"], report["provider_calls"] = ledger.snapshot()
            write_json(out["checkpoint"], report)

    ledger.persist = checkpoint
    works = {}
    try:
        for name, task in tasks:
            source = next(w for w in datasets[name]["works"] if w["key"] == task["work"])
            key = (name, source["key"])
            if key in works:
                continue
            ledger.task_id, ledger.category, ledger.phase, ledger.run_number = None, "check", "prepare", None
            works[key] = Work(source, len(chapters(source["source"])), provider, args.assistant_rates,
                              root=state_root / hashlib.sha256(repr(key).encode()).hexdigest()[:20])
            if not any((p["set"], p["work"]) == key for p in report["preparations"]):
                report["preparations"].append({"set": name, "work": key[1], **works[key].initialization})
            checkpoint()
        for number in range(1, args.runs + 1):
            for name, task in tasks:
                row = next((r for r in report["records"] if r["run_number"] == number and r["set"] == name and r["task"]["id"] == task["id"]), None)
                if row and row.get("finished"):
                    continue
                if ledger.stopped or ledger.spent + (.05 if task["suite"] == "route" else .6) > ledger.max_cny:
                    report["stop_reason"] = "budget_stop"
                    return report
                source = next(w for w in datasets[name]["works"] if w["key"] == task["work"])
                work = works[(name, source["key"])]
                ledger.task_id, ledger.category, ledger.run_number = task["id"], "assistant", number
                if row is None:
                    row = new_record(task)
                    row.update(set=name, run_number=number, operations=[])
                    report["records"].append(row)
                if not row.get("execution_complete"):
                    work.journal, work.cursor, work.persist = row["operations"], 0, checkpoint
                    try:
                        run_task(work, task, source["shared_draft"]["body"], row, checkpoint)
                    except RuntimeError as error:
                        if not str(error).startswith("http_"):
                            raise
                        row["execution_errors"].append(str(error))
                    row["execution_complete"] = True
                    work.journal = None
                    checkpoint()
                ledger.category, ledger.phase = "judge", "judge"
                score.grade(row, judge, checkpoint)
                row["usage"] = ledger.totals(task["id"], number)
                row["finished"] = True
                checkpoint()
                print(json.dumps({"run": number, "completed": sum(r.get("finished", False) for r in report["records"]),
                                  "total": len(tasks) * args.runs, "cost_cny": ledger.spent}), flush=True)
            for row in report["records"]:
                done = {(c["run_number"], c["set"], c["task_id"]) for c in report["card_checks"]}
                # A card of a task that did not complete cannot be confirmed in the product either; it counts elsewhere.
                if (row["run_number"] != number or not row.get("changes") or (row.get("assistant") or {}).get("status") != "completed"
                        or (number, row["set"], row["task"]["id"]) in done):
                    continue
                source = next(w for w in datasets[row["set"]]["works"] if w["key"] == row["task"]["work"])
                report["card_checks"].append(check_card(works[(row["set"], source["key"])], row, provider))
                checkpoint()
        report["complete"] = len(report["records"]) == len(tasks) * args.runs and all(r.get("finished") for r in report["records"])
    except Exception as error:
        report["stop_reason"] = "budget_stop" if ledger.stopped else "runner_error"
        report["error_type"] = type(error).__name__
    finally:
        for work in works.values():
            work.close()
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        score.refresh(report)
        checkpoint()
        write_json(out["report"], report)
        write_json(out["audit"], score.audit(report))
        out["markdown"].write_text(score.markdown(report), encoding="utf-8")
        ledger.persist = lambda: None
    return report


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--set", type=set_names_arg, default="eval_set_a2_dev")
    p.add_argument("--runs", type=int, choices=[1, 3], default=1)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--run-id", required=True)
    p.add_argument("--only", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-cny", type=float, default=10)
    p.add_argument("--assistant-rates", type=rates, required=True)
    p.add_argument("--judge-rates", type=rates, required=True)
    p.add_argument("--judge-model", default=PRE_REGISTRATION["judging"]["judge_model"])
    return p


def main():
    args = parser().parse_args()
    ledger = Ledger(args.max_cny, args.assistant_rates, args.judge_rates)
    provider = SimpleNamespace(available=True, assistant_model="deepseek-flash", model="deepseek-flash", model_for=lambda role: "deepseek-flash") if args.dry_run else PricedProvider(ledger)
    out = preflight(args, provider)
    if args.dry_run:
        print("dry_run_ok")
        return 0
    datasets = {name: load_set(name) for name in set_names(args.set)}
    result = execute(args, datasets, provider, Judge(provider, args.judge_model), ledger, out)
    print(json.dumps({"complete": result["complete"], "cost_cny": ledger.spent, "status": result["gate_decision"]}))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, FileExistsError) as error:
        print("a2_start_refused:" + type(error).__name__, file=sys.stderr)
        sys.exit(2)
