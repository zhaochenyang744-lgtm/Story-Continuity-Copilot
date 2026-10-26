"""A database with known assistant records for the usage statistics tests (and for the sample in the delivery report).

Every column that holds text carries SENTINEL; the statistics must never print it. The numbers are chosen so that the expected
results can be read off: see `test_v210_usage_stats.py`.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

SENTINEL = "正文哨兵XYZ"


def dumps(value, **_):
    return json.dumps(value, ensure_ascii=False)

PROMPT = "p-test-1"
LONG_PROMPT = "long-p1"


class Fixture:
    def __init__(self, c: sqlite3.Connection, registered: str, visitor: str, work: str, sample_work: str):
        self.c, self.registered, self.visitor, self.work, self.sample_work = c, registered, visitor, work, sample_work
        self.count = 0

    # -- rows ---------------------------------------------------------------------------------------------------------------
    def task(self, kind: str, status: str, created: str, *, user: str | None = None, project: str | None = None, prompt: str = PROMPT, cost: float = 0.1,
             steps: int = 2, chars: int = 500, error: str | None = None, seconds: float | None = 10, model: str = "deepseek-flash") -> str:
        self.count += 1
        task_id = f"atask-fixture-{self.count:04d}"
        started = created
        completed = None
        if seconds is not None:
            completed = (datetime.fromisoformat(created) + timedelta(seconds=seconds)).isoformat()
        self.c.execute(
            "INSERT INTO assistant_tasks(id,project_id,user_id,kind,status,input_json,source_revision,memory_version,author_context_version,scope_json,"
            "answer_json,coverage_json,error_code,steps_used,input_tokens,output_tokens,cost_cny,chars_charged,prompt_version,model_label,created_at,"
            "started_at,completed_at,consensus_json,models_json,internal_error_type) VALUES(?,?,?,?,?,?,1,1,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, project or self.work, user or self.registered, kind, status, dumps({"question": f"问题{SENTINEL}"}, ensure_ascii=False),
             dumps({"max_chapter": 10, "note": SENTINEL}, ensure_ascii=False), dumps({"sentences": [{"text": f"回答{SENTINEL}", "refs": []}]}, ensure_ascii=False),
             dumps({"checked": [f"第 1 章{SENTINEL}"]}, ensure_ascii=False), error, steps, 1000, 200, cost, chars, prompt, model, created, started, completed,
             dumps({"runs": [SENTINEL]}, ensure_ascii=False), dumps({"loop": "m", "note": SENTINEL}), None))
        self.c.execute("INSERT INTO assistant_sources VALUES(?,?,?,?,?,?,?,?,?)", (task_id, "R1", "passage", "obj", 3, f"章名{SENTINEL}", 0, 9, f"段落{SENTINEL}"))
        return task_id

    def step(self, task_id: str, ordinal: int, kind: str, *, tool: str | None = None, count: int | None = None, error: str | None = None,
             diagnostics: dict[str, Any] | None = None, elapsed: int | None = None) -> None:
        self.c.execute(
            "INSERT INTO assistant_steps(task_id,ordinal,round,kind,tool_name,args_json,summary,result_count,error_code,created_at,refs_json,diagnostics_json,elapsed_ms) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, ordinal, 1, kind, tool, dumps({"query": SENTINEL, "problems": [f"句子{SENTINEL}"]}, ensure_ascii=False), f"摘要{SENTINEL}", count, error,
             "2026-10-05T00:00:00+00:00", dumps(["R1"]), dumps(diagnostics) if diagnostics is not None else None, elapsed))

    def feedback(self, task_id: str, verdict: str, reasons: list[str] | None = None) -> None:
        self.c.execute("INSERT INTO assistant_feedback VALUES(?,?,?,?,?,?)", (task_id, self.registered, verdict, dumps(reasons or []), "2026-10-05T00:00:00+00:00", "2026-10-05T00:00:00+00:00"))

    def card(self, task_id: str, kind: str, status: str, *, events: tuple[str, ...] = (), edited: bool = False) -> str:
        change_id = f"achange-fixture-{self.c.execute('SELECT COUNT(*) FROM assistant_changes').fetchone()[0] + 1:04d}"
        applied = "2026-10-05T01:00:00+00:00" if status in ("applied", "undone") else None
        self.c.execute(
            "INSERT INTO assistant_changes(id,task_id,project_id,ordinal,kind,target_id,before_json,after_json,display_json,evidence_json,status,edited_by_author,"
            "created_at,decided_at,applied_at,undone_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (change_id, task_id, self.work, 1, kind, f"target-{SENTINEL}", dumps({"v": SENTINEL}), dumps({"v": SENTINEL}), dumps({"title": SENTINEL, "after": SENTINEL}),
             dumps([SENTINEL]), status, int(edited), "2026-10-05T00:30:00+00:00", "2026-10-05T01:00:00+00:00" if status != "proposed" else None, applied,
             "2026-10-05T02:00:00+00:00" if status == "undone" else None))
        for number, event in enumerate(events, 1):
            self.c.execute("INSERT INTO assistant_change_events VALUES(?,?,?,?,?,?,?)", (f"achevent-{change_id}-{number}", change_id, self.work, event, self.registered,
                                                                                        dumps({"with": SENTINEL}), "2026-10-05T01:00:00+00:00"))
        return change_id

    def proposal(self, task_id: str) -> None:
        self.c.execute("INSERT INTO assistant_proposals(id,task_id,ordinal,kind,target,before,after,rationale,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (f"aprop-{task_id}", task_id, 1, "edit_this", SENTINEL, SENTINEL, SENTINEL, SENTINEL, "proposed", "2026-10-05T00:00:00+00:00"))

    def long_plan(self, task_id: str, *, origin: str | None, plan_type: str | None, chapters: int | None, range_edited: int = 0, cap_edited: int = 0,
                  stopped_by: str | None = None, cap: float = 2.0) -> None:
        proposal = dumps({"type": plan_type, "target": f"对象{SENTINEL}", "focus": [SENTINEL], "steps": []}, ensure_ascii=False)
        self.c.execute("INSERT INTO assistant_long_plans(task_id,proposed_json,approved_json,cap_cny,created_at,origin,range_edited,cap_edited,stopped_by,plan_type,chapters_planned) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (task_id, proposal, proposal, cap, "2026-10-05T00:00:00+00:00", origin, range_edited, cap_edited, stopped_by, plan_type, chapters))

    def long_step(self, task_id: str, ordinal: int, status: str = "done", *, seconds: int = 30, diagnostics: dict[str, Any] | None = None, cost: float = 0.05) -> None:
        self.c.execute("INSERT INTO assistant_long_steps(task_id,ordinal,spec_json,status,attempt,output_json,cost_cny,chars_read,started_at,finished_at,diagnostics_json) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (task_id, ordinal, dumps({"look_for": SENTINEL}, ensure_ascii=False), status, 1, dumps({"threads": [{"title": SENTINEL, "note": SENTINEL}]}, ensure_ascii=False),
                        cost, 1000, "2026-10-05T00:00:00+00:00", (datetime(2026, 10, 5, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat() if status == "done" else None,
                        dumps(diagnostics) if diagnostics is not None else None))

    def long_question(self, task_id: str, kind: str, number: int = 1) -> None:
        self.c.execute("INSERT INTO assistant_long_questions(id,task_id,step,kind,body_json,answer_json,asked_at) VALUES(?,?,?,?,?,?,?)",
                       (f"alq-{task_id}-{number}", task_id, 1, kind, dumps({"text": SENTINEL}, ensure_ascii=False), dumps({"choice": "a", "note": SENTINEL}), "2026-10-05T00:00:00+00:00"))

    def in_text_columns_of_the_app(self) -> None:
        """The sentinel in the text of the work itself and of the accounts, which the statistics never open."""
        self.c.execute("UPDATE v2_projects SET title=?,summary=?", (f"书名{SENTINEL}", f"简介{SENTINEL}"))
        self.c.execute("UPDATE v2_chapters SET title=?,summary=?,body=?", (f"章名{SENTINEL}", f"摘要{SENTINEL}", f"正文{SENTINEL}"))
        self.c.execute("UPDATE v2_users SET display_name=?", (f"笔名{SENTINEL}",))

    # -- the data set --------------------------------------------------------------------------------------------------------------
    def populate(self) -> None:
        w1, w2 = "2026-10-05T08:00:00+00:00", "2026-10-12T08:00:00+00:00"
        # Registered authors, asks (prompt p-test-1, week 1): three completed (costs .1 .2 .3), one failed after a repair (cost .4); one thumbs-down, two up.
        a = [self.task("ask", "completed", w1, cost=0.1, steps=2, seconds=10), self.task("ask", "completed", w1, cost=0.2, steps=3, seconds=20),
             self.task("ask", "completed", w1, cost=0.3, steps=4, seconds=30),
             self.task("ask", "failed", w1, cost=0.4, steps=5, seconds=40, error="citation_validation_failed", chars=0)]
        self.step(a[0], 1, "tool", tool="search_text", count=3, elapsed=120)
        self.step(a[0], 2, "answer", count=1, elapsed=900)
        self.step(a[3], 1, "tool", tool="read_chapter", count=1, elapsed=80)
        self.step(a[3], 2, "repair", error="citation_validation_failed", elapsed=700, diagnostics={"problem_codes": ["ref_unknown", "sentence_no_ref"], "repairs": 1, "dropped": 0, "dropped_codes": {}})
        self.step(a[3], 3, "repair", error="citation_validation_failed", elapsed=650, diagnostics={"problem_codes": ["ref_unknown"], "repairs": 1, "dropped": 0, "dropped_codes": {}})
        self.step(a[1], 1, "answer", count=2, elapsed=800, diagnostics={"problem_codes": [], "repairs": 1, "dropped": 1, "dropped_codes": {"people_unsupported": 1}})
        self.feedback(a[0], "up")
        self.feedback(a[1], "up")
        self.feedback(a[3], "down", ["wrong", "bad_source"])
        # A second prompt version in week 2.
        b = self.task("ask", "completed", w2, prompt="p-test-2", cost=0.5, seconds=50)
        self.feedback(b, "down", ["verbose"])
        # Change tasks: four cards of one kind (3 confirmed, 1 of them undone, 1 rejected), one of another kind, still waiting.
        change = self.task("change", "completed", w1, cost=0.2, seconds=15)
        self.card(change, "add_fact", "applied", events=("applied",), edited=True)
        self.card(change, "add_fact", "undone", events=("applied", "undone"))
        self.card(change, "add_fact", "applied", events=("applied",))
        self.card(change, "add_fact", "rejected", events=("rejected",))
        self.card(change, "resolve_thread", "proposed")
        self.proposal(change)
        # Another author's account kind: a visitor's ask; and a sample work's ask, with a card, neither of which joins the totals.
        self.task("ask", "completed", w1, user=self.visitor, cost=0.01, seconds=5)
        sample = self.task("ask", "failed", w1, project=self.sample_work, cost=0.9, error="provider_timeout", seconds=60)
        self.card(self.task("change", "completed", w1, project=self.sample_work), "add_fact", "applied", events=("applied",))
        self.feedback(sample, "down", ["not_found"])
        # A hidden second run of a change task is not an author's task.
        self.task("change", "shadow", w1, cost=9)
        # Long tasks.
        done = self.task("long", "completed", w1, prompt=LONG_PROMPT, cost=0.3, steps=3, seconds=120, chars=1500)
        self.long_plan(done, origin="route", plan_type="thread_audit", chapters=10, range_edited=1)
        self.long_step(done, 1, seconds=20, diagnostics={"problem_codes": ["ref_outside_step"], "repairs": 1, "dropped": 0, "dropped_codes": {}, "apply_dropped_codes": {}})
        self.long_step(done, 2, seconds=40, diagnostics={"problem_codes": ["thread_unknown", "thread_unknown"], "repairs": 1, "dropped": 1, "dropped_codes": {"thread_unknown": 1},
                                                         "apply_dropped_codes": {"change_evidence_invalid": 1}})
        self.long_question(done, "decision")
        stopped = self.task("long", "stopped", w1, prompt=LONG_PROMPT, cost=0.6, steps=1, seconds=300)
        self.long_plan(stopped, origin="mode", plan_type="tidy", chapters=20, cap_edited=1, stopped_by="cost_cap")
        self.long_step(stopped, 1, seconds=60)
        self.long_question(stopped, "budget")
        failed = self.task("long", "failed", w1, prompt=LONG_PROMPT, cost=0.1, steps=0, seconds=30, error="assistant_long_report_invalid", chars=0)
        self.long_plan(failed, origin=None, plan_type="trace", chapters=5, stopped_by="program_error")
        self.long_step(failed, 1, "running", diagnostics={"problem_codes": ["conflict_malformed", "conflict_malformed"], "repairs": 1, "dropped": 0, "dropped_codes": {}, "apply_dropped_codes": {}})
        waiting = self.task("long", "awaiting_plan", w1, prompt=LONG_PROMPT, cost=0.0, steps=0, seconds=None, chars=0)
        self.long_plan(waiting, origin="mode", plan_type="thread_audit", chapters=10)
        self.in_text_columns_of_the_app()
