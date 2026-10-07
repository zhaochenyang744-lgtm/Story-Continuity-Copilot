"""v1.7.0 author organisation: 「考虑中」 plans and author-defined setting categories.

Both live in side tables so the existing plan and world-entry tables keep their shape, and an older
release can still open the database (rollback needs no restore).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import Header, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .database import DomainError

SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_plan_states(plan_kind TEXT NOT NULL CHECK(plan_kind IN ('story','character','world')),plan_id TEXT NOT NULL,project_id TEXT NOT NULL REFERENCES v2_projects(id),state TEXT NOT NULL CHECK(state IN ('considering')),updated_at TEXT NOT NULL,PRIMARY KEY(plan_kind,plan_id));
CREATE TABLE IF NOT EXISTS v2_setting_categories(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),builtin_key TEXT,name TEXT NOT NULL,position INTEGER NOT NULL,archived INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,builtin_key));
CREATE TABLE IF NOT EXISTS v2_setting_category_assignments(entry_id TEXT PRIMARY KEY REFERENCES v2_world_entries(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),category_id TEXT NOT NULL REFERENCES v2_setting_categories(id),updated_at TEXT NOT NULL);
"""
# Child-first, for project reset and visitor cleanup.
TABLES = ("v2_setting_category_assignments", "v2_setting_categories", "v2_plan_states")
# The categories every work starts with; the author may rename, hide or add to them.
BUILTIN_CATEGORIES = (("location", "地点"), ("rule", "规则"), ("organization", "组织"), ("object", "物品"), ("term", "术语"))


def migrate(c):
    for statement in SCHEMA.split(";"):
        if statement.strip():
            c.execute(statement)


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ 「考虑中」 plans
def considering_ids(c, project_id):
    """Plan ids marked 「考虑中」, as {(kind, plan_id)}. Such plans are reminders only and stay out of analyses."""
    return {(row["plan_kind"], row["plan_id"]) for row in c.execute("SELECT plan_kind,plan_id FROM v2_plan_states WHERE project_id=? AND state='considering'", (project_id,))}


def plan_states(db, user_id, project_id):
    with db.connection() as c:
        db._project(c, user_id, project_id)
        return {"considering": [{"kind": kind, "plan_id": plan_id} for kind, plan_id in sorted(considering_ids(c, project_id))]}


PLAN_TABLES = {"story": "v2_author_story_plans", "character": "v2_author_character_plans", "world": "v2_author_world_plans"}


def set_plan_state(db, user_id, project_id, payload, key):
    with db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        db._project(c, user_id, project_id, True)
        def apply():
            table = PLAN_TABLES[payload["kind"]]
            if not c.execute(f"SELECT 1 FROM {table} WHERE id=? AND project_id=?", (payload["plan_id"], project_id)).fetchone():
                raise DomainError("resource_not_found", 404)
            if payload["considering"]:
                c.execute("INSERT OR REPLACE INTO v2_plan_states VALUES(?,?,?,?,?)", (payload["kind"], payload["plan_id"], project_id, "considering", _now()))
            else:
                c.execute("DELETE FROM v2_plan_states WHERE plan_kind=? AND plan_id=? AND project_id=?", (payload["kind"], payload["plan_id"], project_id))
            return {"kind": payload["kind"], "plan_id": payload["plan_id"], "considering": bool(payload["considering"])}
        return db._idem(c, user_id, f"plan_state:{project_id}:{payload['kind']}:{payload['plan_id']}", key, payload, apply)


# ------------------------------------------------------------------ setting categories
def _category_rows(c, project_id):
    return {row["builtin_key"] or row["id"]: row for row in c.execute("SELECT * FROM v2_setting_categories WHERE project_id=? ORDER BY position,created_at,id", (project_id,))}


def setting_categories(db, user_id, project_id):
    """The categories shown on 资料 · 设定, with the entries in each.

    Built-in categories come from each entry's type unless the author renamed or hid them; the author's
    own categories hold the entries assigned to them.
    """
    with db.connection() as c:
        db._project(c, user_id, project_id)
        return _categories_view(c, project_id)


def _categories_view(c, project_id):
    rows = _category_rows(c, project_id)
    assigned = {row["entry_id"]: row["category_id"] for row in c.execute("SELECT entry_id,category_id FROM v2_setting_category_assignments WHERE project_id=?", (project_id,))}
    entries = c.execute("SELECT id,entry_type FROM v2_world_entries WHERE project_id=?", (project_id,)).fetchall()
    categories = []
    for position, (builtin_key, default_name) in enumerate(BUILTIN_CATEGORIES):
        row = rows.get(builtin_key)
        if row and row["archived"]:
            continue
        categories.append({"id": row["id"] if row else None, "key": builtin_key, "name": row["name"] if row else default_name, "builtin": True, "position": row["position"] if row else position})
    for row in rows.values():
        if row["builtin_key"] is None and not row["archived"]:
            categories.append({"id": row["id"], "key": row["id"], "name": row["name"], "builtin": False, "position": row["position"]})
    categories.sort(key=lambda item: (item["position"], item["name"]))
    visible = {item["key"] for item in categories}
    by_id = {row["id"]: (row["builtin_key"] or row["id"]) for row in rows.values()}
    membership = {}
    for entry in entries:
        key = by_id.get(assigned.get(entry["id"])) or entry["entry_type"]
        # An entry whose category was hidden falls back to its own type; an unknown type shows under 其他.
        if key not in visible:
            key = entry["entry_type"] if entry["entry_type"] in visible else "other"
        membership[entry["id"]] = key
    if "other" in membership.values():
        categories.append({"id": None, "key": "other", "name": "其他", "builtin": True, "position": 10_000})
    for item in categories:
        item["count"] = sum(1 for key in membership.values() if key == item["key"])
    return {"categories": categories, "membership": membership}


def _builtin_row(c, project_id, builtin_key):
    row = c.execute("SELECT * FROM v2_setting_categories WHERE project_id=? AND builtin_key=?", (project_id, builtin_key)).fetchone()
    if row:
        return row
    name = dict(BUILTIN_CATEGORIES)[builtin_key]
    position = [key for key, _ in BUILTIN_CATEGORIES].index(builtin_key)
    stamp = _now()
    c.execute("INSERT INTO v2_setting_categories VALUES(?,?,?,?,?,?,?,?)", (f"setcat-{uuid.uuid4()}", project_id, builtin_key, name, position, 0, stamp, stamp))
    return c.execute("SELECT * FROM v2_setting_categories WHERE project_id=? AND builtin_key=?", (project_id, builtin_key)).fetchone()


def _resolve(c, project_id, key):
    """A category key (built-in key or custom id) → its row, creating the row for an untouched built-in."""
    if key in dict(BUILTIN_CATEGORIES):
        return _builtin_row(c, project_id, key)
    row = c.execute("SELECT * FROM v2_setting_categories WHERE id=? AND project_id=? AND builtin_key IS NULL", (key, project_id)).fetchone()
    if not row:
        raise DomainError("resource_not_found", 404)
    return row


def change_setting_categories(db, user_id, project_id, payload, key):
    """One endpoint for the four edits: create, rename, hide (delete) a category, or move an entry."""
    with db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        db._project(c, user_id, project_id, True)
        def apply():
            action, stamp = payload["action"], _now()
            name = (payload.get("name") or "").strip()
            if action in {"create", "rename"} and not 1 <= len(name) <= 20:
                raise DomainError("setting_category_name_invalid", 422)
            if action == "create":
                position = (c.execute("SELECT MAX(position) FROM v2_setting_categories WHERE project_id=?", (project_id,)).fetchone()[0] or len(BUILTIN_CATEGORIES)) + 1
                c.execute("INSERT INTO v2_setting_categories VALUES(?,?,?,?,?,?,?,?)", (f"setcat-{uuid.uuid4()}", project_id, None, name, position, 0, stamp, stamp))
            elif action == "rename":
                row = _resolve(c, project_id, payload["category"])
                c.execute("UPDATE v2_setting_categories SET name=?,updated_at=? WHERE id=?", (name, stamp, row["id"]))
            elif action == "delete":
                row = _resolve(c, project_id, payload["category"])
                # Entries go back to their own type; nothing about the entries themselves changes.
                c.execute("DELETE FROM v2_setting_category_assignments WHERE category_id=? AND project_id=?", (row["id"], project_id))
                c.execute("UPDATE v2_setting_categories SET archived=1,updated_at=? WHERE id=?", (stamp, row["id"]))
            elif action == "assign":
                if not c.execute("SELECT 1 FROM v2_world_entries WHERE id=? AND project_id=?", (payload["entry_id"], project_id)).fetchone():
                    raise DomainError("resource_not_found", 404)
                if payload.get("category"):
                    row = _resolve(c, project_id, payload["category"])
                    c.execute("INSERT OR REPLACE INTO v2_setting_category_assignments VALUES(?,?,?,?)", (payload["entry_id"], project_id, row["id"], stamp))
                else:
                    c.execute("DELETE FROM v2_setting_category_assignments WHERE entry_id=? AND project_id=?", (payload["entry_id"], project_id))
            return _categories_view(c, project_id)
        return db._idem(c, user_id, f"setting_categories:{project_id}", key, payload, apply)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanState(Strict):
    kind: Literal["story", "character", "world"]
    plan_id: str = Field(min_length=1, max_length=120)
    considering: StrictBool


class SettingCategoryChange(Strict):
    action: Literal["create", "rename", "delete", "assign"]
    category: str | None = Field(default=None, max_length=120)
    name: str | None = Field(default=None, max_length=40)
    entry_id: str | None = Field(default=None, max_length=120)


def register_routes(app, db, user, csrf, key, ok, operation):
    @app.get("/api/projects/{project_id}/plan-states")
    def get_plan_states(project_id: str, request: Request):
        return ok(request, plan_states(db, user(request)["id"], project_id))

    @app.post("/api/projects/{project_id}/plan-states")
    def post_plan_state(project_id: str, payload: PlanState, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        csrf(request); operation(request, "plan_state_failed")
        data, status = set_plan_state(db, user(request)["id"], project_id, payload.model_dump(), key(idempotency_key))
        return ok(request, data, status)

    @app.get("/api/projects/{project_id}/setting-categories")
    def get_setting_categories(project_id: str, request: Request):
        return ok(request, setting_categories(db, user(request)["id"], project_id))

    @app.post("/api/projects/{project_id}/setting-categories")
    def post_setting_categories(project_id: str, payload: SettingCategoryChange, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        csrf(request); operation(request, "setting_category_failed")
        if payload.action in {"rename", "delete"} and not payload.category:
            raise DomainError("setting_category_required", 422)
        if payload.action == "assign" and not payload.entry_id:
            raise DomainError("setting_entry_required", 422)
        data, status = change_setting_categories(db, user(request)["id"], project_id, payload.model_dump(), key(idempotency_key))
        return ok(request, data, status)
