"""The author's home page and settings (v1.8.0): writing days, the home payload, daily usage, the password change.

Everything here is read from, or added beside, the tables that already exist. The one new table,
v2_writing_days, holds the net characters an author wrote on one chapter of one work on one day;
an older release can still open the database (it never looks at that table).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict

from .database import DomainError

# Every per-day figure — the writing calendar, the streak, the last days of usage — is cut at midnight in
# Beijing time (UTC+8). The page reads the same constant back from the home payload.
DAY_UTC_OFFSET_HOURS = 8
DAY_TZ = timezone(timedelta(hours=DAY_UTC_OFFSET_HOURS))
CALENDAR_DAYS = 365
FEED_LIMIT = 20
BIO_MAX = 60
SAMPLE_ORIGINS = ("demo_seed", "tutorial_seed")
USAGE_DAYS_MAX = 31
# Attempts counted in v2_login_attempts under a key that cannot be an account name (those match [a-z0-9][a-z0-9_.-]{2,63}).
PASSWORD_ATTEMPTS = (5, 15)
EXPORT_ATTEMPTS = (3, 10)

SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_writing_days(user_id TEXT NOT NULL,project_id TEXT NOT NULL,chapter_number INTEGER NOT NULL,day TEXT NOT NULL,net_chars INTEGER NOT NULL DEFAULT 0,saves INTEGER NOT NULL DEFAULT 0,first_at TEXT NOT NULL,last_at TEXT NOT NULL,PRIMARY KEY(user_id,project_id,chapter_number,day));
CREATE INDEX IF NOT EXISTS v2_writing_days_by_user ON v2_writing_days(user_id,day);
CREATE INDEX IF NOT EXISTS v2_writing_days_by_project ON v2_writing_days(project_id);
"""
# v2_users columns this release adds; existing columns are never changed.
USER_COLUMNS = {"bio": "TEXT NOT NULL DEFAULT ''", "password_changed_at": "TEXT"}


def migrate(c) -> None:
    """Add the two user columns and the writing-days table. Safe to run again."""
    columns = {row[1] for row in c.execute("PRAGMA table_info(v2_users)")}
    for name, definition in USER_COLUMNS.items():
        if name not in columns:
            c.execute(f"ALTER TABLE v2_users ADD COLUMN {name} {definition}")
    for statement in SCHEMA.split(";"):
        if statement.strip():
            c.execute(statement)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _moment(value: str | datetime) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def local_day(value: str | datetime) -> str:
    """The Beijing-time calendar day (YYYY-MM-DD) a moment falls on."""
    return _moment(value).astimezone(DAY_TZ).date().isoformat()


def day_start(day: str) -> datetime:
    """The first instant of a Beijing-time day, in UTC."""
    return datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=DAY_TZ).astimezone(timezone.utc)


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


# ------------------------------------------------------------------------------ recording
def counts_writing(project) -> bool:
    """Writing in a sample or tutorial work is not the author's writing."""
    return project["data_origin"] not in SAMPLE_ORIGINS


def record_writing(c, project, user_id: str, chapter_number: int, net_chars: int, stamp: str, *, draft_save: bool) -> None:
    """Add one write to the day it happened on, in the transaction that made it.

    `net_chars` is the change of the work's character count across the write (negative when text was
    cut). A draft save also counts as a save, which is what the activity feed lists.
    """
    if not counts_writing(project):
        return
    c.execute(
        "INSERT INTO v2_writing_days(user_id,project_id,chapter_number,day,net_chars,saves,first_at,last_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id,project_id,chapter_number,day) DO UPDATE SET net_chars=net_chars+excluded.net_chars,saves=saves+excluded.saves,last_at=CASE WHEN excluded.saves>0 THEN excluded.last_at ELSE last_at END",
        (user_id, project["id"], chapter_number, local_day(stamp), net_chars, 1 if draft_save else 0, stamp, stamp),
    )


# ------------------------------------------------------------------------------ rate limits
def rate_limited(c, key: str, limit: tuple[int, int], code: str) -> None:
    """Count one attempt under `key`; refuse the one past `limit` = (attempts, minutes)."""
    maximum, minutes = limit
    cutoff = (_now() - timedelta(minutes=minutes)).isoformat()
    if c.execute("SELECT COUNT(*) FROM v2_login_attempts WHERE account_name=? AND attempted_at>?", (key, cutoff)).fetchone()[0] >= maximum:
        raise DomainError(code, 429, True)
    c.execute("INSERT INTO v2_login_attempts VALUES(?,?)", (key, _now().isoformat()))


# ------------------------------------------------------------------------------ password
def change_password(db, user_id: str, session_token: str | None, current_password: str, new_password: str) -> dict[str, Any]:
    """Replace the password; every other session of the account and any unused reset link stop working."""
    import hashlib

    from .v2_database import _password, password_matches

    with db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        user = c.execute("SELECT id,account_type,password_hash FROM v2_users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise DomainError("authentication_required", 401)
        if user["account_type"] != "registered":
            raise DomainError("password_change_not_allowed", 403)
        if len(new_password) < 10 or len(set(new_password)) < 2:
            raise DomainError("password_policy_failed", 422)
        key = f"password:{user_id}"
        rate_limited(c, key, PASSWORD_ATTEMPTS, "password_change_rate_limited")
        if not password_matches(current_password, user["password_hash"]):
            # A wrong guess stays counted. 400, not 401: a 401 would read as a lost session.
            c.commit()
            raise DomainError("current_password_incorrect", 400)
        stamp = _now().isoformat()
        c.execute("DELETE FROM v2_login_attempts WHERE account_name=?", (key,))
        c.execute("UPDATE v2_users SET password_hash=?,password_changed_at=? WHERE id=?", (_password(new_password), stamp, user_id))
        kept = hashlib.sha256(session_token.encode()).hexdigest() if session_token else ""
        c.execute("UPDATE v2_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND token_hash!=?", (stamp, user_id, kept))
        c.execute("UPDATE v2_recovery_tokens SET revoked_at=? WHERE user_id=? AND purpose='password_reset' AND used_at IS NULL AND revoked_at IS NULL", (stamp, user_id))
        return {"changed": True, "password_changed_at": stamp}


# ------------------------------------------------------------------------------ the home payload
def _marks(values: list[Any]) -> str:
    return ",".join("?" * len(values))


def _levels(values: list[int]) -> list[int]:
    """Five shades of a day: 0 for no writing, 1–4 by where the day stands among this author's own writing days."""
    positive = sorted(value for value in values if value > 0)
    shades = []
    for value in values:
        if value <= 0:
            shades.append(0)
            continue
        below = sum(1 for other in positive if other < value)
        equal = sum(1 for other in positive if other == value)
        shades.append(min(4, 1 + int((below + equal / 2) / len(positive) * 4)))
    return shades


def _streaks(days: dict[str, int], today: str) -> tuple[int, bool]:
    """(consecutive writing days, whether today is one of them). Yesterday's run still counts before today is written."""
    wrote = {day for day, chars in days.items() if chars > 0}
    includes_today = today in wrote
    cursor = today if includes_today else _shift(today, -1)
    count = 0
    while cursor in wrote:
        count += 1
        cursor = _shift(cursor, -1)
    return count, includes_today


def _longest_run(wrote_days: list[str]) -> int:
    best = run = 0
    previous = None
    for day in sorted(wrote_days):
        run = run + 1 if previous is not None and day == _shift(previous, 1) else 1
        best = max(best, run)
        previous = day
    return best


def work_chars(c, project_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Chapters, characters (counted like the works list: chapters, with a non-empty latest draft in place of its chapter), titles and drafts, in two queries."""
    facts = {pid: {"chapters": {}, "titles": {}, "draft": None} for pid in project_ids}
    if not project_ids:
        return facts
    for row in c.execute(f"SELECT project_id,chapter_number,title,body FROM v2_chapters WHERE project_id IN ({_marks(project_ids)})", project_ids):
        facts[row["project_id"]]["chapters"][int(row["chapter_number"])] = str(row["body"] or "")
        facts[row["project_id"]]["titles"][int(row["chapter_number"])] = row["title"]
    for row in c.execute(f"SELECT * FROM v2_drafts WHERE project_id IN ({_marks(project_ids)}) ORDER BY saved_at DESC", project_ids):
        if facts[row["project_id"]]["draft"] is None:
            facts[row["project_id"]]["draft"] = row
    for item in facts.values():
        draft = item["draft"]
        text = dict(item["chapters"])
        if draft is not None and str(draft["body"] or "").strip():
            text[int(draft["chapter_number"])] = str(draft["body"])
        item["chars"] = sum(len(re.sub(r"\s+", "", body)) for body in text.values())
    return facts


def _check_events(c, user_id: str, work_ids: list[str], since: str | None, limit: int | None) -> list[dict[str, Any]]:
    """Finished checks of the author's own works, newest first: one entry per run, with the chapters it covered."""
    if not work_ids:
        return []
    sql = (
        f"SELECT r.id,r.project_id,r.run_type,r.completed_at,d.chapter_number draft_chapter,a.result_json,"
        f"(SELECT COUNT(*) FROM v2_issues i WHERE i.run_id=r.id) issue_count "
        f"FROM v2_runs r LEFT JOIN v2_drafts d ON d.id=r.draft_id LEFT JOIN v2_analysis_results a ON a.run_id=r.id "
        f"WHERE r.project_id IN ({_marks(work_ids)}) AND r.status='completed' AND r.result_origin='provider' AND r.completed_at IS NOT NULL "
        f"AND ((r.run_type='continuity' AND r.incremental_batch_id IS NULL) OR r.run_type='chapter_check')"
    )
    values: list[Any] = list(work_ids)
    if since:
        sql += " AND r.completed_at>=?"
        values.append(since)
    sql += " ORDER BY r.completed_at DESC"
    if limit:
        sql += " LIMIT ?"
        values.append(limit)
    events = []
    for row in c.execute(sql, values):
        if row["run_type"] == "chapter_check":
            try:
                report = (json.loads(row["result_json"]) if row["result_json"] else {}) or {}
            except ValueError:
                report = {}
            chapters = [int(item["chapter_number"]) for item in report.get("chapters", []) if isinstance(item.get("chapter_number"), int)]
            issues = int(report.get("issue_count") or 0)
        else:
            chapters = [int(row["draft_chapter"])] if row["draft_chapter"] is not None else []
            issues = int(row["issue_count"] or 0)
        events.append({"project_id": row["project_id"], "at": row["completed_at"], "chapters": sorted(chapters), "issues": issues})
    return events


def home(db, user_id: str) -> dict[str, Any]:
    """Everything the author's home page draws, read in one go."""
    from . import long_term_workflow as workflow

    now = _now()
    today = local_day(now)
    start = _shift(today, -(CALENDAR_DAYS - 1))
    with db.connection() as c:
        user = c.execute("SELECT id,account_name,display_name,avatar_preset,bio,created_at,account_type,visitor_expires_at,password_changed_at FROM v2_users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise DomainError("authentication_required", 401)
        projects = c.execute(
            f"SELECT * FROM v2_projects WHERE user_id=? AND data_origin NOT IN ({_marks(list(SAMPLE_ORIGINS))}) ORDER BY updated_at DESC,id", (user_id, *SAMPLE_ORIGINS)
        ).fetchall()
        ids = [row["id"] for row in projects]
        title_of = {row["id"]: row["title"] for row in projects}
        facts = work_chars(c, ids)
        checked = {row[0] for row in c.execute(
            f"SELECT DISTINCT project_id FROM v2_runs WHERE project_id IN ({_marks(ids)}) AND run_type IN ('continuity','memory_delta') AND status='completed'", ids)} if ids else set()
        works = []
        for project in projects:
            open_count = workflow.open_issue_count(c, project["id"])
            works.append({
                "id": project["id"], "title": project["title"], "genre": project["genre"], "summary": project["summary"], "status": project["status"],
                "data_origin": project["data_origin"], "chapter_count": len(facts[project["id"]]["chapters"]), "word_count": facts[project["id"]]["chars"],
                "open_issue_count": open_count, "continuity_status": "pending" if open_count else "checked_clear" if project["id"] in checked else "unchecked",
                "created_at": project["created_at"], "updated_at": project["updated_at"],
            })

        # Writing days: the sum of each day's chapters, never below zero on the calendar.
        day_sums = {row["day"]: int(row["total"]) for row in c.execute("SELECT day,SUM(net_chars) total FROM v2_writing_days WHERE user_id=? GROUP BY day", (user_id,))}
        window = [_shift(start, offset) for offset in range(CALENDAR_DAYS)]
        chars = [max(0, day_sums.get(day, 0)) for day in window]
        streak, includes_today = _streaks({day: max(0, total) for day, total in day_sums.items()}, today)
        wrote = [day for day, value in zip(window, chars) if value > 0]
        best = max(range(CALENDAR_DAYS), key=lambda index: chars[index]) if wrote else None

        window_start = day_start(start).isoformat()
        year_checks = _check_events(c, user_id, ids, window_start, None)
        covered = {(event["project_id"], number) for event in year_checks for number in event["chapters"]}

        # 正在写: the work whose draft was saved last (archived works are read-only).
        current = None
        for project in projects:
            draft = facts[project["id"]]["draft"]
            if project["status"] == "archived" or draft is None or draft["status"] not in ("draft", "saved") or not str(draft["body"] or "").strip():
                continue
            if current is None or draft["saved_at"] > current[1]["saved_at"]:
                current = (project, draft)
        current_view = None
        if current:
            project, draft = current
            runs = [row[0] for row in c.execute(
                "SELECT COALESCE(draft_revision,source_revision) FROM v2_runs WHERE draft_id=? AND run_type='continuity' AND incremental_batch_id IS NULL AND status='completed' AND result_origin='provider'", (draft["id"],))]
            current_view = {
                "project_id": project["id"], "project_title": project["title"], "chapter_number": int(draft["chapter_number"]), "chapter_title": draft["title"],
                "chars": len(re.sub(r"\s+", "", str(draft["body"]))), "saved_at": draft["saved_at"],
                "check_state": "checked" if draft["revision"] in runs else "edited" if runs else "unchecked",
            }

        feed = _feed(c, user_id, ids, title_of, facts, _check_events(c, user_id, ids, None, FEED_LIMIT))

    return {
        "today": today,
        "day_utc_offset_hours": DAY_UTC_OFFSET_HOURS,
        "profile": {
            "account_name": user["account_name"], "display_name": user["display_name"], "avatar_preset": user["avatar_preset"], "bio": user["bio"],
            "created_at": user["created_at"], "account_type": user["account_type"], "visitor_expires_at": user["visitor_expires_at"],
        },
        "totals": {
            "works": len(works), "chapters": sum(item["chapter_count"] for item in works), "chars": sum(item["word_count"] for item in works),
            "streak_days": streak, "streak_includes_today": includes_today,
        },
        "calendar": {"start": start, "end": today, "chars": chars, "levels": _levels(chars)},
        "year": {
            "chars": sum(chars), "writing_days": len(wrote), "best_day": {"day": window[best], "chars": chars[best]} if best is not None else None,
            "longest_streak": _longest_run(wrote), "checked_chapters": len(covered),
        },
        "current": current_view,
        "works": works,
        "activity": feed,
    }


def _feed(c, user_id: str, ids: list[str], title_of: dict[str, str], facts: dict[str, dict[str, Any]], checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The latest things the author did, newest first. Read from the records other features already keep; no text of the work is ever included."""
    if not ids:
        return []
    events: list[dict[str, Any]] = []

    def chapter_title(project_id: str, number: int | None) -> str:
        if number is None:
            return ""
        draft = facts[project_id]["draft"]
        return facts[project_id]["titles"].get(number) or (draft["title"] if draft is not None and int(draft["chapter_number"]) == number else "")

    def add(kind: str, at: str, project_id: str, numbers: list[int] | None = None, **extra: Any) -> None:
        numbers = numbers or []
        events.append({"kind": kind, "at": at, "day": local_day(at), "project_id": project_id, "project_title": title_of[project_id],
                       "chapter_number": numbers[0] if numbers else None, "chapter_numbers": numbers,
                       "chapter_title": chapter_title(project_id, numbers[0] if numbers else None), **extra})

    for row in c.execute(
        f"SELECT project_id,chapter_number,day,net_chars,last_at FROM v2_writing_days WHERE user_id=? AND saves>0 AND project_id IN ({_marks(ids)}) ORDER BY last_at DESC LIMIT ?",
        (user_id, *ids, FEED_LIMIT),
    ):
        add("draft_saved", row["last_at"], row["project_id"], [int(row["chapter_number"])], net_chars=int(row["net_chars"]))
    for row in c.execute(
        f"SELECT project_id,committed_at,commit_result_json,chapters_json FROM v2_source_change_sets WHERE user_id=? AND status='committed' AND mode='append' AND input_method='draft_complete' "
        f"AND project_id IN ({_marks(ids)}) ORDER BY committed_at DESC LIMIT ?",
        (user_id, *ids, FEED_LIMIT),
    ):
        try:
            following = int(json.loads(row["commit_result_json"])["next_draft"]["chapter_number"])
            count = len(json.loads(row["chapters_json"]))
        except (TypeError, ValueError, KeyError):
            continue
        add("chapter_finished", row["committed_at"], row["project_id"], list(range(following - count, following)))
    for item in checks:
        add("checked", item["at"], item["project_id"], item["chapters"], issue_count=item["issues"])
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assistant_proposals'").fetchone():
        for row in c.execute(
            f"SELECT t.project_id,p.chapter_number,p.decided_at FROM assistant_proposals p JOIN assistant_tasks t ON t.id=p.task_id "
            f"WHERE t.user_id=? AND p.status='adopted' AND p.decided_at IS NOT NULL AND t.project_id IN ({_marks(ids)}) ORDER BY p.decided_at DESC LIMIT ?",
            (user_id, *ids, FEED_LIMIT),
        ):
            add("assistant_adopted", row["decided_at"], row["project_id"], [int(row["chapter_number"])] if row["chapter_number"] is not None else [])
    for row in c.execute(
        f"SELECT id,created_at,data_origin FROM v2_projects WHERE id IN ({_marks(ids)}) ORDER BY created_at DESC LIMIT ?", (*ids, FEED_LIMIT)
    ):
        add("project_created", row["created_at"], row["id"], origin=row["data_origin"])
    events.sort(key=lambda item: item["at"], reverse=True)
    return events[:FEED_LIMIT]


# ------------------------------------------------------------------------------ usage by day
def daily_usage(db, user_id: str, days: int) -> dict[str, Any]:
    """Check and assistant characters spent on each of the last `days` Beijing-time days, and when the oldest charge still counting comes back."""
    now = _now()
    today = local_day(now)
    first = _shift(today, -(days - 1))
    with db.connection() as c:
        if not c.execute("SELECT 1 FROM v2_users WHERE id=?", (user_id,)).fetchone():
            raise DomainError("authentication_required", 401)
        rows = c.execute(
            "SELECT u.characters,u.created_at,COALESCE(r.workflow_kind,'') kind FROM v2_character_usage u "
            "LEFT JOIN v2_usage_reservations r ON r.user_id=u.user_id AND (u.id='chars-'||r.id OR u.id='chars-'||r.id||'-x1') "
            "WHERE u.user_id=? AND u.kind='check' AND u.created_at>=?",
            (user_id, day_start(first).isoformat()),
        ).fetchall()
        spent = {_shift(first, offset): [0, 0] for offset in range(days)}
        window = (now - timedelta(hours=24)).isoformat()
        oldest = None
        for row in rows:
            slot = spent.get(local_day(row["created_at"]))
            if slot is not None:
                slot[1 if row["kind"].startswith("assistant") else 0] += int(row["characters"])
            if row["created_at"] > window and row["characters"] > 0 and (oldest is None or row["created_at"] < oldest["created_at"]):
                oldest = row
    return {
        "today": today,
        "days": [{"day": day, "check_chars": values[0], "assistant_chars": values[1]} for day, values in spent.items()],
        "oldest_charge": {"recovers_at": (_moment(oldest["created_at"]) + timedelta(hours=24)).isoformat(), "chars": int(oldest["characters"])} if oldest else None,
    }


# ------------------------------------------------------------------------------ routes
class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str
    new_password: str


def register_routes(app, db, user: Callable, csrf: Callable, ok: Callable, operation: Callable, cookie: str) -> None:
    @app.get("/api/account/home")
    def account_home(request: Request):
        return ok(request, home(db, user(request)["id"]))

    @app.get("/api/account/usage/daily")
    def account_usage_daily(request: Request, days: int = Query(default=7, ge=1, le=USAGE_DAYS_MAX)):
        return ok(request, daily_usage(db, user(request)["id"], days))

    @app.post("/api/auth/password")
    def password_change(payload: PasswordChange, request: Request):
        csrf(request)
        operation(request, "password_change_failed")
        return ok(request, change_password(db, user(request)["id"], request.cookies.get(cookie), payload.current_password, payload.new_password))

    @app.get("/api/account/export")
    def account_export(request: Request):
        actor = user(request)
        with db.connection() as c:
            kind = c.execute("SELECT account_type FROM v2_users WHERE id=?", (actor["id"],)).fetchone()
            if not kind or kind["account_type"] != "registered":
                raise DomainError("export_not_allowed", 403)
            rate_limited(c, f"export:{actor['id']}", EXPORT_ATTEMPTS, "export_rate_limited")
        from .project_export import export_all_works

        return export_all_works(db, actor["id"], local_day(_now()))
