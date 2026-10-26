"""A3 runner (SPEC section 4): long tasks on works that carry starting materials, a scripted author, a runner killed once
mid-step in pass 1 and taken up by a new one, and every card confirmed and undone a group at a time after each pass.

The works are prepared as A2's: the product's import, the starting facts as the confirmed facts of the first version, the
threads through the materials API. Nothing is confirmed during a pass, so every task starts from the starting materials. A
long task goes the author's way through the API: the plan card (narrowed to `plan_edit` on a narrowed task, otherwise
started as proposed), the questions it stops on, and its result. The runner the product would run in the background runs
in this process (the app's executor runs it at once), except in pass 1 until it has been killed: there each stretch of the
runner runs in a separate process (`child.py`) that dies, without any cleanup, once the step chosen with seed 20261024 has
started; the product's own sweep then takes the task up when the dead runner's lease has run out (this process's runner
looks at the lease a lease-length later, instead of waiting for it).

The cost ledger, the priced provider and the product settings are A1's; the work, the card read back by number and the
comparison of a confirmed and undone card A2's.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import pathlib
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from evaluation.assistant_a1 import run as a1
from evaluation.assistant_a1.run import ROOT, Ledger, PricedProvider, chapters, git, rates, response_data, write_json, WRITE_LOCK
from evaluation.assistant_a2 import run as a2

from fastapi.testclient import TestClient
from app import long_tasks as lt
from app.assistant_actions import ACTIONS
from app.config import AppPaths
from app.main import create_app

from ..models import REGISTERED_MODELS
from . import score
from .judge import Judge
from .thresholds import PRE_REGISTRATION

DEV_SETS = ("eval_set_a3d2_dev",)  # addendum 1: the first dev set used its 3 runs and is not run again
FORMAL_SETS = tuple(PRE_REGISTRATION["formal_sets"])
RESUME_SEED = 20261024
KILLED = 86  # the runner process's exit code when it died as planned
CHECK_CHARS = 100_000_000  # three passes of 32 long tasks read about nine million characters; A1's settings allow ten
TASK_RESERVE_CNY = 2.5  # kept free before a long task starts: its ceiling (CNY 2) and its judging
def workspaces(out):
    """Where a run keeps its works' files: a short name beside the results. Named after the checkpoint, the formal pair's paths
    passed Windows' 260-character limit and the runner process could not write its result (formal run f1-d524302)."""
    return out["checkpoint"].parent / ("ws-" + hashlib.sha256(out["checkpoint"].name.encode("utf-8")).hexdigest()[:12])


CHILD_PROVIDER = "priced"  # what the runner process answers with: A1's priced provider, or "module:function" (tests)
CHOICE = re.compile(r"选\s*([abAB])")
MAX_ANSWERS = 3
QUOTE_PROBE = 10


# --- sets -------------------------------------------------------------------------------------------------------------
def set_names(value):
    names = value.split(",")
    if len(names) != len(set(names)):
        raise ValueError("invalid_sets")
    if (len(names) == 1 and names[0] in DEV_SETS) or sorted(names) == sorted(FORMAL_SETS):
        return names
    raise ValueError("invalid_sets")


def set_names_arg(value):
    try:
        set_names(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None
    return value


def readable(name):
    return name in DEV_SETS


def load_set(name):
    data = a2.load_set(name)
    data["review"] = json.loads((ROOT / "evaluation" / name / "authoring" / "self-review.json").read_text(encoding="utf-8"))
    return data


def paths(name, run_id, output=None):
    if not run_id or not all(ch.isalnum() or ch in "_-" for ch in run_id):
        raise ValueError("invalid_run_id")
    base = (output or ROOT / "evaluation/results") / f"a3-{name.replace(',', '+')}-{run_id}"
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
        if git("status", "--porcelain", "--", "backend/app", "evaluation/assistant_a1", "evaluation/assistant_a2", "evaluation/assistant_a3",
               *[f"evaluation/{n}" for n in names]):
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
        a2.validate_set(name)
    if args.only is not None:
        ids = {t["id"] for name in names if readable(name) for t in a2.load_set(name)["tasks"]}
        if not args.only or not set(args.only) <= ids:
            raise ValueError("unknown_or_empty_selection")
    return out


def settings_for(price):
    return dataclasses.replace(a1.settings(price), registered_check_chars=CHECK_CHARS)


# --- the provider the app is given ------------------------------------------------------------------------------------
class Recorder:
    """Every product call answered, with the task it was made for (`label`) and its cost: what the evaluation paid for, to
    hold against what the task booked."""

    def __init__(self, provider, label=None):
        self._provider, self.label, self.paid = provider, label, []

    def __getattr__(self, name):
        return getattr(self._provider, name)

    def chat(self, *args, **kwargs):
        return self._keep(self._provider.chat(*args, **kwargs))

    def route(self, *args, **kwargs):
        return self._keep(self._provider.route(*args, **kwargs))

    def _keep(self, result):
        self.paid.append({"label": self.label, "cost_cny": result.cost_cny})
        return result


# --- a work ---------------------------------------------------------------------------------------------------------------
class Work(a2.Work):
    """A2's work with A3's settings, and the long task's API."""

    def settings_for(self, price):
        return settings_for(price)

    def long(self, method, path="", body=None):
        url = self.base + "/assistant/long-tasks" + path
        return self.response(method, url, **({"json": body} if body is not None else {}))

    def view(self, task_id):
        return response_data(self.long("GET", f"/{task_id}"))

    def records(self, task_id):
        """What the product kept of a long task: its row, plan, steps, booked calls, and the passages it was shown."""
        with self.app.state.database.connection() as c:
            task = dict(c.execute("SELECT status,cost_cny,steps_used,error_code,internal_error_type,chars_charged FROM assistant_tasks WHERE id=?",
                                  (task_id,)).fetchone())
            plan = c.execute("SELECT approved_json,chars_read,cap_cny FROM assistant_long_plans WHERE task_id=?", (task_id,)).fetchone()
            steps = [{"ordinal": s["ordinal"], "spec": json.loads(s["spec_json"]), "status": s["status"], "attempt": s["attempt"],
                      "chars_read": s["chars_read"], "cost_cny": s["cost_cny"], "output": json.loads(s["output_json"] or "{}")}
                     for s in c.execute("SELECT * FROM assistant_long_steps WHERE task_id=? ORDER BY ordinal", (task_id,))]
            calls = [dict(r) for r in c.execute("SELECT step,attempt,seq,role,model,cost_cny FROM assistant_long_calls WHERE task_id=? "
                                                "ORDER BY step,attempt,seq", (task_id,))]
            sources = {r["ref"]: dict(r) for r in c.execute("SELECT ref,kind,chapter_number,text FROM assistant_sources WHERE task_id=?", (task_id,))}
        return {"task_row": task, "approved": json.loads(plan["approved_json"]) if plan and plan["approved_json"] else None,
                "chars_read": plan["chars_read"] if plan else None, "steps": steps, "calls": calls, "sources": sources}


# --- the scripted author ---------------------------------------------------------------------------------------------------
def decision_point_of(task, question, points):
    """The task's decision point when this question's two passages are its two chapters, else None."""
    if not task.get("decision_point"):
        return None
    point = points["decision_points"][task["decision_point"] - 1]
    asked = sorted(option.get("chapter") or 0 for option in question.get("options") or [])
    return point if asked == sorted([point["a"]["chapter"], point["b"]["chapter"]]) else None


def author_choice(task, question, points):
    """The scripted author's answer to a decision question: the side `author_replies.decision` picks, when the question is the
    task's decision point; '你定' to anything else."""
    point = decision_point_of(task, question, points)
    found = CHOICE.search((task.get("author_replies") or {}).get("decision") or "")
    if point is None or not found:
        return "you_decide", point is not None
    wanted = point[found.group(1).lower()]
    options = [o for o in question["options"] if o.get("chapter") == wanted["chapter"]]
    if len(options) > 1:  # both passages in one chapter: the one that quotes the chosen side
        options = [o for o in options if squeezed(wanted["quote"])[:QUOTE_PROBE] in squeezed(o["quote"])
                   or squeezed(o["quote"])[:QUOTE_PROBE] in squeezed(wanted["quote"])] or options
    return options[0]["key"], True


def squeezed(text):
    return "".join(str(text or "").split())


class Interrupt:
    """Pass 1 of a long task: its runner runs in a runner process until that process has died once at the start of the step
    chosen with the seed; the product's sweep, in this process, then takes the task up."""

    def __init__(self, work, ledger, recorder, row, seed_key):
        self.work, self.ledger, self.recorder, self.row = work, ledger, recorder, row
        self.seed_key = seed_key
        self.state = row["long"].setdefault("interrupt", {"step": None, "killed": False, "runs": 0})

    @property
    def done(self):
        return self.state["killed"]

    def step(self, task_id):
        if self.state["step"] is None:
            with self.work.app.state.database.connection() as c:
                reads = [s["ordinal"] for s in c.execute("SELECT ordinal,spec_json FROM assistant_long_steps WHERE task_id=? ORDER BY ordinal", (task_id,))
                         if json.loads(s["spec_json"])["kind"] == "read"]
            self.state["step"] = random.Random(f"{RESUME_SEED}:{self.seed_key}").choice(reads) if reads else 0
        return self.state["step"]

    def run(self, task_id):
        """One stretch of the runner in a runner process; when it died as planned, the sweep takes the task up here."""
        step = self.step(task_id)
        if not step:
            return self.work.app.state.long_tasks.run(task_id)
        self.state["runs"] += 1
        result_path = self.work.root / f"runner-{task_id}-{self.state['runs']}.json"
        remaining = self.ledger.max_cny - self.ledger.spent if self.ledger else 100.0
        command = [sys.executable, "-X", "utf8", "-B", "-m", "evaluation.assistant_a3.child", "--root", str(self.work.root), "--task", task_id,
                   "--kill-step", str(step), "--result", str(result_path), "--rates", ",".join(map(str, self.work.price)),
                   "--max-cny", str(max(remaining, 0.01)), "--label", self.recorder.label or "", "--provider", CHILD_PROVIDER]
        done = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3600)
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        self.recorder.paid += result.get("paid", [])
        if self.ledger and result.get("calls"):
            with self.ledger.lock:
                self.ledger.calls += [{**call, "run_number": self.ledger.run_number, "task_id": self.ledger.task_id} for call in result["calls"]]
            self.ledger.persist()
        if done.returncode == KILLED and result.get("killed"):
            self.state.update(killed=True, at=result.get("at"))
            self.resume()
        elif done.returncode:
            self.state["child_error"] = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [f"exit_{done.returncode}"]
            raise RuntimeError("runner_process_failed")

    def resume(self):
        """A new runner takes the task up: the sweep looks a lease-length later, so the dead runner's lease has run out."""
        long = self.work.app.state.long_tasks
        clock = long.clock
        long.clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=lt.LEASE_SECONDS + 1)
        try:
            self.state["taken_up"] = long.sweep()
        finally:
            long.clock = clock


def run_long(work, task, row, points, recorder, interrupt=None):
    """One long task the author's way (SPEC section 4). Returns when the task has ended."""
    long_tasks = work.app.state.long_tasks
    record = row["long"] = {"questions": [], "runner_seconds": 0.0, "max_chapter": len(work.listing), "paid": []}
    if interrupt is not None:
        interrupt = interrupt(row)
    recorder.label = row["label"]
    context = {k: v for k, v in task["context"].items() if k in ("page", "chapter_number")}
    created = work.long("POST", "", {"question": task["request"], "context": context})
    if created.status_code != 202:
        row["execution_errors"].append(f"create_http_{created.status_code}:{(created.json().get('error') or {}).get('code')}")
        return
    task_id = record["task_id"] = created.json()["data"]["id"]
    view = work.view(task_id)  # the plan call ran with the request

    def runner(send):
        """Send what lets the runner go (start, an answer), and time the runner's stretch; in pass 1, before the kill, the
        stretch runs in a runner process."""
        start = time.perf_counter()
        if interrupt is None or interrupt.done:
            response = send()
        else:
            deferred = []
            long_tasks.run = deferred.append
            try:
                response = send()
            finally:
                del long_tasks.run
            for task_id_ in deferred:
                interrupt.run(task_id_)
        record["runner_seconds"] += time.perf_counter() - start
        return response

    if view["status"] == lt.AWAITING_PLAN:
        record["plan_proposed"] = view["plan"]["proposed"]
        if task.get("plan_edit"):
            edited = work.long("POST", f"/{task_id}/plan", {"chapters": task["plan_edit"]["chapters"]})
            record["plan_edit_status"] = edited.status_code
            view = response_data(edited) if edited.status_code == 200 else work.view(task_id)
        record["plan_shown"], record["cap_cny"] = view["plan"]["proposed"], view["plan"]["cap_cny"]
        started = runner(lambda: work.long("POST", f"/{task_id}/start"))
        if started.status_code != 202:
            row["execution_errors"].append(f"start_http_{started.status_code}:{(started.json().get('error') or {}).get('code')}")
        answered = 0
        for _ in range(12):
            view = work.view(task_id)
            if view["status"] == lt.WAITING:
                question = next(q for q in view["questions"] if q["answer"] is None)
                entry = {**{k: question.get(k) for k in ("id", "kind", "step", "text", "options")}}
                if question["kind"] == "budget":
                    entry["choice"] = "stop"  # 「到此为止，把已经做完的交给我」
                else:
                    if answered >= MAX_ANSWERS:  # a 4th question: the task stops, not completed
                        record["stopped_fourth_question"] = True
                        record["questions"].append({**entry, "choice": None})
                        runner(lambda: work.long("POST", f"/{task_id}/stop"))
                        continue
                    answered += 1
                    entry["choice"], entry["matched"] = author_choice(task, question, points)
                record["questions"].append(entry)
                runner(lambda: work.long("POST", f"/{task_id}/answer", {"question_id": question["id"], "choice": entry["choice"]}))
                continue
            if view["status"] in (lt.QUEUED, lt.RUNNING):  # nothing holds it here: the sweep takes it up
                runner(lambda: long_tasks.sweep())
                continue
            break
    if view["status"] in lt.ACTIVE:
        row["execution_errors"].append("long_task_left_active")
        work.long("POST", f"/{task_id}/stop")
        view = work.view(task_id)
    # The questions the program answered itself once the author had been asked three times.
    record["questions"] += [{**{k: q.get(k) for k in ("id", "kind", "step", "text", "options")}, "choice": (q["answer"] or {}).get("choice"), "by": "program"}
                            for q in view["questions"] if (q["answer"] or {}).get("by") == "program"]
    kept = work.records(task_id)
    sources = kept.pop("sources")
    cited = {ref for items in ((view.get("answer") or {}).get("sections") or {}).values() for item in items for ref in item.get("refs") or []}
    record.update(kept, passage_chapters={ref: s["chapter_number"] for ref, s in sources.items() if s["kind"] == "passage"},
                  sources={ref: {k: s[k] for k in ("kind", "chapter_number", "text")} for ref, s in sources.items() if ref in cited},
                  paid=[p for p in recorder.paid if p["label"] == row["label"]])
    row["assistant"] = {k: view.get(k) for k in ("id", "status", "answer", "error_code")}
    row["changes"] = work.card(task_id)


def check_card(work, row, provider):
    """Confirm the whole card a group at a time (a high-risk item alone, as the card shows it) and undo it again, on a copy of
    the work, and compare (SPEC section 4, as A2)."""
    items = [item for item in row.get("changes") or [] if item["status"] == "proposed"]
    groups, by_kind = [], {}
    for item in items:  # one group per kind, in the order the kinds first appear
        if ACTIONS[item["kind"]].risk == "high":
            groups.append([item])
        elif item["kind"] in by_kind:
            by_kind[item["kind"]].append(item)
        else:
            by_kind[item["kind"]] = [item]
            groups.append(by_kind[item["kind"]])
    task_id = row["assistant"]["id"]
    with tempfile.TemporaryDirectory(prefix="a3-card-") as folder:
        copy = pathlib.Path(folder) / "work"
        shutil.copytree(work.root, copy)
        app = create_app(AppPaths.from_project_root(copy, protected_poc_root=copy / "protected"), provider=provider,
                         executor=lambda fn, *args: fn(*args), settings=settings_for(work.price))
        client = TestClient(app)
        try:
            response_data(client.post("/api/auth/login", json={"account_name": work.account, "password": a2.PASSWORD}))
            start = a2.snapshot(app.state.database, work.project)
            confirmed = [client.post(work.base + f"/assistant/long-tasks/{task_id}/changes/confirm", headers=a1.idem(),
                                     json={"accepted": [i["id"] for i in group], "within": [i["id"] for i in group]}).status_code for group in groups]
            after = a2.snapshot(app.state.database, work.project)
            undone = [client.post(work.base + f"/assistant/changes/{item['id']}/undo", headers=a1.idem(), json={"confirm": False}).status_code
                      for item in reversed(items)]
            final = a2.snapshot(app.state.database, work.project)
        finally:
            client.close()
    ok = all(code == 200 for code in confirmed)
    return {"run_number": row["run_number"], "set": row["set"], "task_id": row["task"]["id"], "items": len(items), "groups": [len(g) for g in groups],
            "confirm_statuses": confirmed, "confirm_exact": ok and after == a2._expected_after(start, items, after), "undo_statuses": undone,
            "undo_exact": ok and all(code == 200 for code in undone) and a2.undo_restored(start, final, items), "start_matches_prepared": start == work.start}


def new_record(task):
    return {"task": task, "auto": {}, "execution_errors": [], "judgments": []}


# --- the run ----------------------------------------------------------------------------------------------------------------
def execute(args, datasets, provider, judge, ledger, out):
    names = set_names(args.set)
    tasks = [(name, t) for name in names for t in datasets[name]["tasks"] if args.only is None or t["id"] in args.only]
    recorder = Recorder(provider)
    fingerprint = {"sets": names, "runs": args.runs, "only": args.only, "git_commit": git("rev-parse", "HEAD"),
                   "assistant_model": provider.assistant_model, "model": provider.model,
                   "models": {role: provider.model_for(role) for role in (*REGISTERED_MODELS, "plan")},
                   "judge_model": args.judge_model, "assistant_rates": list(args.assistant_rates), "judge_rates": list(args.judge_rates),
                   "manifests": {n: datasets[n].get("manifest_sha256") for n in names},
                   "code_sha256": hashlib.sha256(b"".join(p.read_bytes() for directory in (ROOT / "backend/app", ROOT / "evaluation/assistant_a3")
                                                          for p in sorted(directory.glob("*.py")))).hexdigest()}
    # Every work's planted points and chapter text, before anything is paid for.
    points = {(name, w["key"]): score.planted(datasets[name]["review"], w["key"]) for name in names for w in datasets[name]["works"]}
    texts = {(name, w["key"]): {i: score.squeeze(text.split("\n", 1)[1] if "\n" in text else "") for i, text in enumerate(chapters(w["source"]), 1)}
             for name in names for w in datasets[name]["works"]}
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
            works[key] = Work(source, len(chapters(source["source"])), recorder, args.assistant_rates,
                              root=state_root / hashlib.sha256(repr(key).encode()).hexdigest()[:20])
            if not any((p["set"], p["work"]) == key for p in report["preparations"]):
                report["preparations"].append({"set": name, "work": key[1], **works[key].initialization})
            checkpoint()
        for number in range(1, args.runs + 1):
            for name, task in tasks:
                row = next((r for r in report["records"] if r["run_number"] == number and r["set"] == name and r["task"]["id"] == task["id"]), None)
                if row and row.get("finished"):
                    continue
                if ledger.stopped or ledger.spent + (.05 if task["suite"] == "route" else TASK_RESERVE_CNY) > ledger.max_cny:
                    report["stop_reason"] = "budget_stop"
                    return report
                source = next(w for w in datasets[name]["works"] if w["key"] == task["work"])
                work, key = works[(name, source["key"])], (name, source["key"])
                ledger.task_id, ledger.category, ledger.run_number = task["id"], "assistant", number
                if row is None:
                    row = new_record(task)
                    row.update(set=name, run_number=number, operations=[], label=f"{number}:{name}:{task['id']}")
                    report["records"].append(row)
                if not row.get("execution_complete"):
                    run_one(work, task, row, source, points[key], recorder, ledger, number, checkpoint)
                    row["execution_complete"] = True
                    checkpoint()
                ledger.category, ledger.phase = "judge", "judge"
                score.grade(row, judge, points[key], texts[key], checkpoint)
                row["usage"] = ledger.totals(task["id"], number)
                row["finished"] = True
                checkpoint()
                print(json.dumps({"run": number, "completed": sum(r.get("finished", False) for r in report["records"]),
                                  "total": len(tasks) * args.runs, "cost_cny": ledger.spent}), flush=True)
            for row in report["records"]:
                done = {(c["run_number"], c["set"], c["task_id"]) for c in report["card_checks"]}
                if (row["run_number"] != number or not row.get("changes") or (row.get("assistant") or {}).get("status") not in score.FINISHED
                        or (number, row["set"], row["task"]["id"]) in done):
                    continue
                source = next(w for w in datasets[row["set"]]["works"] if w["key"] == row["task"]["work"])
                report["card_checks"].append(check_card(works[(row["set"], source["key"])], row, recorder))
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


def run_one(work, task, row, source, points, recorder, ledger, number, checkpoint):
    """A route item as A2's; a long task, once more after a provider failure (infrastructure retry, as A1), and after a crash
    of this process from the start, the half-done attempt stopped and kept aside."""
    if task["suite"] == "route":
        work.journal, work.cursor, work.persist = row["operations"], 0, checkpoint
        try:
            a2.run_task(work, task, source["shared_draft"]["body"], row, checkpoint)
        except RuntimeError as error:
            if not str(error).startswith("http_"):
                raise
            row["execution_errors"].append(str(error))
        work.journal = None
        return
    work.journal = None
    if row.get("long"):  # this process died during the task: stop what is left of it and start again
        task_id = row["long"].get("task_id")
        if task_id and work.view(task_id)["status"] in lt.ACTIVE:
            work.long("POST", f"/{task_id}/stop")
        row.setdefault("restarts", []).append({k: row.pop(k, None) for k in ("long", "assistant", "changes")})
        row["execution_errors"] = []
    interrupt = (lambda r: Interrupt(work, ledger, recorder, r, f"{row['set']}:{task['id']}")) if number == 1 else None
    for attempt in range(2):
        try:
            run_long(work, task, row, points, recorder, interrupt)
        except RuntimeError as error:
            if not str(error).startswith(("http_", "runner_process_failed")):
                raise
            row["execution_errors"].append(str(error))
        failed = (row.get("assistant") or {}).get("status") == "failed" and row["assistant"].get("error_code") == "assistant_long_provider_failed"
        if not failed or attempt:
            break
        row.setdefault("infrastructure_attempts", []).append({k: row.pop(k, None) for k in ("long", "assistant", "changes")})
        checkpoint()


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--set", type=set_names_arg, default=DEV_SETS[0])
    p.add_argument("--runs", type=int, choices=[1, 3], default=1)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--run-id", required=True)
    p.add_argument("--only", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-cny", type=float, default=30)
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
        print("a3_start_refused:" + type(error).__name__, file=sys.stderr)
        sys.exit(2)
