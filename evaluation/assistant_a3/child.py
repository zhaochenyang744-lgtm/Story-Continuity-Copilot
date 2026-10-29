"""A3's runner process (SPEC section 4, resume): the product's long-task runner on a work's database, in a process of its
own, that dies once the chosen step has started.

It is the product's runner as the server runs it, on an app of its own over the same files, with nothing changed but two
places where it may die: right after the step's first model call is booked (the call has been paid for and the step is
not done), or, for a step that makes no call, just before the step's results are written. It dies with `os._exit`, so
nothing of the runner's own runs after it: no transaction is finished, no lease let go. What it paid for is written to
`--result` first, so the evaluation counts it.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import pathlib
import sys

from evaluation.assistant_a1.run import Ledger, PricedProvider, rates, write_json
from evaluation.assistant_a3.run import KILLED, Recorder, settings_for

from app.config import AppPaths
from app.main import create_app


def provider_for(spec, ledger):
    if spec == "priced":
        return PricedProvider(ledger)
    module, name = spec.split(":", 1)
    return getattr(importlib.import_module(module), name)()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--kill-step", type=int, required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--rates", type=rates, required=True)
    p.add_argument("--max-cny", type=float, required=True)
    p.add_argument("--label", default="")
    p.add_argument("--provider", default="priced")
    args = p.parse_args()
    ledger = Ledger(args.max_cny, args.rates, args.rates)
    ledger.category, ledger.phase = "assistant", "assistant"
    recorder = Recorder(provider_for(args.provider, ledger), args.label)
    root = pathlib.Path(args.root)
    app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=recorder,
                     executor=lambda fn, *a: fn(*a), settings=settings_for(args.rates))
    runner = app.state.long_tasks
    state = {"killed": False, "at": None}

    def save():
        write_json(pathlib.Path(args.result), {**state, "calls": ledger.calls, "paid": recorder.paid})

    def die(at):
        state.update(killed=True, at=at)
        save()
        sys.stdout.flush()
        os._exit(KILLED)

    def step_running(task_id):
        with app.state.database.connection() as c:
            phase = c.execute("SELECT phase FROM assistant_tasks WHERE id=?", (task_id,)).fetchone()[0] or ""
        return int(phase.split(":", 1)[1]) if phase.startswith("step:") else None

    heartbeat, done = runner._heartbeat, runner._done

    def heartbeat_then_die(task_id):
        if step_running(task_id) == args.kill_step:
            die("after_call")
        heartbeat(task_id)

    def done_or_die(task_id, ordinal, *rest):
        if ordinal == args.kill_step:
            die("before_write")
        return done(task_id, ordinal, *rest)

    runner._heartbeat, runner._done = heartbeat_then_die, done_or_die
    runner.run(args.task)
    save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
