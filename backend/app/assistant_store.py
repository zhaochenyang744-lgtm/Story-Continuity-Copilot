"""Storage for the built-in assistant (v1.8.0): tasks, their visible steps, the sources they cite and, later, proposals.

Tables are created by `AssistantStore.initialize()` (idempotent). `purge` removes a project's rows for
`V2Database.purge_project` and the work reset; it must run before the project row goes.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .assistant_tools import OUT_OF_SCOPE_TEXT, error_text

TABLES = ("assistant_feedback", "assistant_proposals", "assistant_sources", "assistant_steps", "assistant_tasks")
FEEDBACK_VERDICTS = ("up", "down")
FEEDBACK_REASONS = ("wrong", "verbose", "not_found", "bad_source")
# Columns added after v1.8.0 first shipped to developers; an older database gets them in `initialize()`.
ADDED_COLUMNS = {
    "assistant_tasks": (("phase", "TEXT"), ("phase_tool", "TEXT"), ("phase_chapter", "INTEGER"), ("phase_started_at", "TEXT"),
                        ("regenerated_from", "TEXT"), ("edited_from", "TEXT"), ("internal_error_type", "TEXT")),
    "assistant_steps": (("refs_json", "TEXT"),),
    "assistant_proposals": (("recheck_json", "TEXT"), ("adopted_draft_revision", "INTEGER"), ("after_edited", "TEXT"), ("edited_by_author", "INTEGER")),
}
# How much of a fact's source passage the page gets to find it by.
ANCHOR_CHARS = 120
TASK_KINDS = ("ask", "recap", "fix_issue")
ACTIVE_STATUSES = ("queued", "running")

SCHEMA = """
CREATE TABLE IF NOT EXISTS assistant_tasks(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES v2_projects(id), user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  input_json TEXT NOT NULL,
  draft_id TEXT, draft_revision INTEGER, source_revision INTEGER NOT NULL,
  memory_version INTEGER NOT NULL, author_context_version INTEGER NOT NULL,
  scope_json TEXT NOT NULL,
  answer_json TEXT, coverage_json TEXT,
  error_code TEXT, steps_used INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_cny REAL NOT NULL DEFAULT 0, chars_charged INTEGER NOT NULL DEFAULT 0,
  reservation_id TEXT, prompt_version TEXT NOT NULL, model_label TEXT NOT NULL,
  follow_up_of TEXT, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, hidden_at TEXT);
CREATE INDEX IF NOT EXISTS assistant_tasks_by_project ON assistant_tasks(project_id,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS assistant_tasks_one_active ON assistant_tasks(project_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS assistant_steps(
  task_id TEXT NOT NULL REFERENCES assistant_tasks(id), ordinal INTEGER NOT NULL,
  round INTEGER NOT NULL,
  kind TEXT NOT NULL,
  tool_name TEXT, args_json TEXT, summary TEXT NOT NULL,
  result_count INTEGER, error_code TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY(task_id, ordinal));
CREATE TABLE IF NOT EXISTS assistant_sources(
  task_id TEXT NOT NULL REFERENCES assistant_tasks(id), ref TEXT NOT NULL,
  kind TEXT NOT NULL,
  object_id TEXT NOT NULL, chapter_number INTEGER, chapter_title TEXT,
  start INTEGER, end INTEGER, text TEXT NOT NULL,
  PRIMARY KEY(task_id, ref));
CREATE TABLE IF NOT EXISTS assistant_proposals(
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES assistant_tasks(id), ordinal INTEGER NOT NULL,
  kind TEXT NOT NULL, target TEXT NOT NULL, chapter_number INTEGER,
  before TEXT NOT NULL, after TEXT NOT NULL, rationale TEXT NOT NULL,
  draft_id TEXT, draft_revision INTEGER, status TEXT NOT NULL, decided_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assistant_feedback(
  task_id TEXT NOT NULL REFERENCES assistant_tasks(id), user_id TEXT NOT NULL,
  verdict TEXT NOT NULL, reasons_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(task_id, user_id));
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_task_id() -> str:
    return f"atask-{uuid.uuid4()}"


def purge(c: sqlite3.Connection, project_id: str) -> None:
    """Delete a project's assistant rows, children first. A no-op where the tables do not exist yet."""
    existing = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "assistant_tasks" not in existing:
        return
    ids = "SELECT id FROM assistant_tasks WHERE project_id=?"
    for table in ("assistant_feedback", "assistant_proposals", "assistant_sources", "assistant_steps"):
        if table in existing:
            c.execute(f"DELETE FROM {table} WHERE task_id IN ({ids})", (project_id,))
    c.execute("DELETE FROM assistant_tasks WHERE project_id=?", (project_id,))


class AssistantStore:
    def __init__(self, database: Any):
        self.db = database

    def initialize(self) -> None:
        with self.db.connection() as c:
            c.executescript(SCHEMA)
            for table, added in ADDED_COLUMNS.items():
                columns = {row[1] for row in c.execute(f"PRAGMA table_info({table})")}
                for name, type_ in added:
                    if name not in columns:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {type_}")

    @staticmethod
    def proposal_view(row: Any) -> dict[str, Any]:
        return {"id": row["id"], "proposal": f"P{row['ordinal']}", "kind": row["kind"], "chapter_number": row["chapter_number"],
                "before": row["before"], "after": row["after"], "rationale": row["rationale"], "status": row["status"],
                "draft_id": row["draft_id"], "draft_revision": row["draft_revision"], "adopted_draft_revision": row["adopted_draft_revision"],
                "decided_at": row["decided_at"], "recheck": json.loads(row["recheck_json"]) if row["recheck_json"] else None,
                "after_edited": row["after_edited"], "edited_by_author": bool(row["edited_by_author"])}

    # --- creation and lookup ---------------------------------------------------------------------------------
    def active_task_id(self, c: sqlite3.Connection, project_id: str) -> str | None:
        row = c.execute("SELECT id FROM assistant_tasks WHERE project_id=? AND status IN ('queued','running')", (project_id,)).fetchone()
        return row["id"] if row else None

    def project_tokens_24h(self, c: sqlite3.Connection, project_id: str) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        return int(c.execute("SELECT COALESCE(SUM(input_tokens+output_tokens),0) FROM assistant_tasks WHERE project_id=? AND created_at>?", (project_id, cutoff)).fetchone()[0])

    def insert_task(self, c: sqlite3.Connection, values: dict[str, Any]) -> None:
        columns = ",".join(values)
        c.execute(f"INSERT INTO assistant_tasks({columns}) VALUES({','.join('?' for _ in values)})", tuple(values.values()))

    def row(self, task_id: str) -> sqlite3.Row | None:
        with self.db.connection() as c:
            return c.execute("SELECT * FROM assistant_tasks WHERE id=?", (task_id,)).fetchone()

    def status(self, task_id: str) -> str | None:
        row = self.row(task_id)
        return row["status"] if row else None

    def history(self, c: sqlite3.Connection, task_id: str | None, depth: int = 2) -> list[tuple[str, str]]:
        """The question and the final answer text of the task a follow-up continues, oldest first, at most `depth` turns."""
        turns: list[tuple[str, str]] = []
        while task_id and len(turns) < depth:
            row = c.execute("SELECT input_json,answer_json,follow_up_of FROM assistant_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                break
            if row["answer_json"]:
                answer = json.loads(row["answer_json"])
                text = "".join(sentence["text"] for sentence in answer.get("sentences") or [])
                if answer.get("status") == "out_of_scope":
                    text = OUT_OF_SCOPE_TEXT
                if answer.get("note"):
                    text = (text + " " if text else "") + answer["note"]
                turns.append((json.loads(row["input_json"])["question"], text))
            task_id = row["follow_up_of"]
        return turns[::-1]

    # --- running a task -----------------------------------------------------------------------------------------
    def mark_running(self, task_id: str) -> bool:
        with self.db.connection() as c:
            return c.execute("UPDATE assistant_tasks SET status='running',started_at=? WHERE id=? AND status='queued'", (utcnow(), task_id)).rowcount == 1

    def add_step(self, task_id: str, round_: int, kind: str, summary: str, *, tool_name: str | None = None,
                 args: dict[str, Any] | None = None, result_count: int | None = None, error_code: str | None = None,
                 refs: list[str] | None = None) -> None:
        with self.db.connection() as c:
            ordinal = c.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM assistant_steps WHERE task_id=?", (task_id,)).fetchone()[0]
            c.execute("INSERT INTO assistant_steps(task_id,ordinal,round,kind,tool_name,args_json,summary,result_count,error_code,created_at,refs_json) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (task_id, ordinal, round_, kind, tool_name, json.dumps(args, ensure_ascii=False) if args is not None else None,
                       summary, result_count, error_code, utcnow(), json.dumps(refs) if refs is not None else None))

    def steps(self, task_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as c:
            return [dict(row) for row in c.execute("SELECT * FROM assistant_steps WHERE task_id=? ORDER BY ordinal", (task_id,)).fetchall()]

    def set_phase(self, task_id: str, phase: str | None, tool: str | None = None, chapter: int | None = None) -> None:
        """What the running task is waiting on: the model (`thinking`) or a tool (`tool`). Only a running task has a phase."""
        with self.db.connection() as c:
            c.execute("UPDATE assistant_tasks SET phase=?,phase_tool=?,phase_chapter=?,phase_started_at=? WHERE id=? AND status='running'",
                      (phase, tool, chapter, utcnow() if phase else None, task_id))

    def update_usage(self, task_id: str, steps_used: int, input_tokens: int, output_tokens: int, cost_cny: float) -> None:
        with self.db.connection() as c:
            c.execute("UPDATE assistant_tasks SET steps_used=?,input_tokens=?,output_tokens=?,cost_cny=? WHERE id=?",
                      (steps_used, input_tokens, output_tokens, cost_cny, task_id))

    def finish(self, task_id: str, status: str, *, error_code: str | None = None, answer: dict[str, Any] | None = None,
               coverage: dict[str, Any] | None = None, internal_error_type: str | None = None) -> bool:
        """Close a task still queued or running; a cancelled task stays cancelled. Returns whether it was closed."""
        with self.db.connection() as c:
            return c.execute(
                "UPDATE assistant_tasks SET status=?,error_code=?,answer_json=?,coverage_json=?,completed_at=?,internal_error_type=?,"
                "phase=NULL,phase_tool=NULL,phase_chapter=NULL,phase_started_at=NULL WHERE id=? AND status IN ('queued','running')",
                (status, error_code, json.dumps(answer, ensure_ascii=False) if answer is not None else None,
                 json.dumps(coverage, ensure_ascii=False) if coverage is not None else None, utcnow(), internal_error_type, task_id)).rowcount == 1

    def save_coverage(self, task_id: str, coverage: dict[str, Any]) -> None:
        with self.db.connection() as c:
            c.execute("UPDATE assistant_tasks SET coverage_json=? WHERE id=?", (json.dumps(coverage, ensure_ascii=False), task_id))

    def set_chars_charged(self, task_id: str, characters: int) -> None:
        with self.db.connection() as c:
            c.execute("UPDATE assistant_tasks SET chars_charged=? WHERE id=?", (characters, task_id))

    def cancel(self, c: sqlite3.Connection, task_id: str) -> bool:
        return c.execute("UPDATE assistant_tasks SET status='cancelled',completed_at=?,phase=NULL,phase_tool=NULL,phase_chapter=NULL,phase_started_at=NULL "
                         "WHERE id=? AND status IN ('queued','running')", (utcnow(), task_id)).rowcount == 1

    def hide_all(self, c: sqlite3.Connection, project_id: str) -> int:
        return c.execute("UPDATE assistant_tasks SET hidden_at=? WHERE project_id=? AND hidden_at IS NULL", (utcnow(), project_id)).rowcount

    # --- feedback -------------------------------------------------------------------------------------------------
    def set_feedback(self, c: sqlite3.Connection, task_id: str, user_id: str, verdict: str, reasons: list[str]) -> None:
        """One verdict per task and author, changeable. Only the verdict and the reasons are kept, never any of the answer."""
        stamp = utcnow()
        c.execute("INSERT INTO assistant_feedback(task_id,user_id,verdict,reasons_json,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(task_id,user_id) DO UPDATE SET verdict=excluded.verdict,reasons_json=excluded.reasons_json,updated_at=excluded.updated_at",
                  (task_id, user_id, verdict, json.dumps(reasons), stamp, stamp))

    def clear_feedback(self, c: sqlite3.Connection, task_id: str, user_id: str) -> None:
        c.execute("DELETE FROM assistant_feedback WHERE task_id=? AND user_id=?", (task_id, user_id))

    # --- sources --------------------------------------------------------------------------------------------------
    def add_source(self, task_id: str, ref: str, kind: str, object_id: str, chapter_number: int | None, chapter_title: str | None,
                   start: int | None, end: int | None, text: str) -> None:
        with self.db.connection() as c:
            c.execute("INSERT INTO assistant_sources VALUES(?,?,?,?,?,?,?,?,?)",
                      (task_id, ref, kind, object_id, chapter_number, chapter_title, start, end, text))

    def sources(self, task_id: str) -> dict[str, dict[str, Any]]:
        with self.db.connection() as c:
            return {row["ref"]: dict(row) for row in c.execute("SELECT * FROM assistant_sources WHERE task_id=?", (task_id,)).fetchall()}

    # --- the view the page polls ----------------------------------------------------------------------------------
    @staticmethod
    def _fact_anchors(c: sqlite3.Connection, project_id: str, fact_ids: list[str]) -> dict[str, dict[str, Any] | None]:
        """For each fact a task registered: the words of the passage it was taken from (the first 120 characters) and that passage's
        chapter, so the page can find the place in the chapter. A fact without a source passage maps to None."""
        found: dict[str, dict[str, Any] | None] = {}
        for fact_id in set(fact_ids):
            found[fact_id] = None
            fact = c.execute("SELECT source_span_id FROM v2_memory_records WHERE id=? AND project_id=? ORDER BY version DESC LIMIT 1", (fact_id, project_id)).fetchone()
            if not fact or not fact["source_span_id"]:
                continue
            span = c.execute("SELECT s.body,ch.chapter_number FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id "
                             "WHERE s.id=? AND s.project_id=?", (fact["source_span_id"], project_id)).fetchone()
            if span and span["body"].strip():
                found[fact_id] = {"text": span["body"].strip()[:ANCHOR_CHARS], "chapter_number": span["chapter_number"]}
        return found

    def view(self, c: sqlite3.Connection, row: sqlite3.Row, viewer_id: str | None = None) -> dict[str, Any]:
        task_input = json.loads(row["input_json"])
        answer = json.loads(row["answer_json"]) if row["answer_json"] else None
        items = list((answer or {}).get("sentences") or [])
        for section in (answer or {}).get("sections", {}).values():
            items.extend(section)
        cited = {ref for sentence in items for ref in sentence.get("refs") or []}
        # Every source the task registered, so the page can show what a step found even when the answer did not cite it.
        registered = sorted(c.execute("SELECT * FROM assistant_sources WHERE task_id=?", (row["id"],)).fetchall(), key=lambda source: int(source["ref"][1:]))
        anchors = self._fact_anchors(c, row["project_id"], [source["object_id"] for source in registered if source["kind"] == "fact"])
        sources = {source["ref"]: {"kind": source["kind"], "chapter_number": source["chapter_number"], "chapter_title": source["chapter_title"],
                                   "start": source["start"], "end": source["end"], "text": source["text"], "cited": source["ref"] in cited,
                                   **({"anchor": anchors.get(source["object_id"])} if source["kind"] == "fact" else {})}
                   for source in registered}
        steps = [{"round": step["round"], "kind": step["kind"], "tool": step["tool_name"], "summary": step["summary"], "result_count": step["result_count"],
                  "group": f"g{step['round']}-{step['tool_name']}" if step["kind"] == "tool" and step["tool_name"] else None,
                  "refs": json.loads(step["refs_json"]) if step["refs_json"] else [],
                  "error_code": step["error_code"], "error_text": error_text(step["error_code"])}
                 for step in c.execute("SELECT * FROM assistant_steps WHERE task_id=? AND kind!='answer' ORDER BY ordinal", (row["id"],)).fetchall()]
        feedback = c.execute("SELECT verdict,reasons_json FROM assistant_feedback WHERE task_id=? AND user_id=?", (row["id"], viewer_id or row["user_id"])).fetchone()
        return {"id": row["id"], "kind": row["kind"], "status": row["status"], "question": task_input["question"], "context": task_input.get("context") or {},
                "follow_up_of": row["follow_up_of"], "regenerated_from": row["regenerated_from"], "edited_from": row["edited_from"],
                "steps": steps, "answer": answer, "sources": sources,
                "out_of_scope_text": OUT_OF_SCOPE_TEXT if answer and answer.get("status") == "out_of_scope" else None,
                "coverage": json.loads(row["coverage_json"]) if row["coverage_json"] else None,
                "usage": {"steps": row["steps_used"], "chars_charged": row["chars_charged"]},
                "phase": row["phase"], "phase_tool": row["phase_tool"] if row["phase"] else None,
                "phase_chapter": row["phase_chapter"] if row["phase"] == "tool" and row["phase_tool"] == "read_chapter" else None,
                "phase_started_at": row["phase_started_at"] if row["phase"] else None,
                "feedback": {"verdict": feedback["verdict"], "reasons": json.loads(feedback["reasons_json"])} if feedback else None,
                "error_code": row["error_code"], "created_at": row["created_at"], "started_at": row["started_at"], "completed_at": row["completed_at"],
                **({"proposals": [self.proposal_view(p) for p in c.execute("SELECT * FROM assistant_proposals WHERE task_id=? ORDER BY ordinal", (row["id"],))]}
                   if row["kind"] == "fix_issue" else {})}

    def visible_tasks(self, c: sqlite3.Connection, project_id: str, limit: int, viewer_id: str | None = None) -> list[dict[str, Any]]:
        """The latest `limit` tasks that were not cleared, oldest first."""
        rows = c.execute("SELECT * FROM assistant_tasks WHERE project_id=? AND hidden_at IS NULL ORDER BY created_at DESC,rowid DESC LIMIT ?", (project_id, limit)).fetchall()
        return [self.view(c, row, viewer_id) for row in reversed(rows)]
