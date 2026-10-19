"""Author actions on proposals. Adoption records an already saved edit; it never writes a draft."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Header, Request
from pydantic import BaseModel, ConfigDict, Field

from .assistant_edits import MeteredProvider, check, check_after
from .assistant_tools import ToolContext, ToolError
from .assistant_store import utcnow
from .database import DomainError
from .stage13 import provider_usage
from .text_content import visible_draft_text, written_chars


class Adopt(BaseModel):
    """`draft_revision` is the saved draft that now holds the sentence (needed for a change to this chapter).
    `after` is the sentence as the author reworded it before adopting; left out, the assistant's own sentence is adopted."""
    model_config = ConfigDict(extra="forbid")
    draft_revision: int | None = Field(default=None, ge=1, strict=True)
    after: str | None = Field(default=None, max_length=5000)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckSources:
    """Recheck evidence is returned and stored inline; its R numbers are local to that recheck."""
    def __init__(self):
        self.keys = {}

    def register(self, kind, object_id, chapter_number, chapter_title, start, end, text):
        key = (kind, object_id, start, end)
        if key not in self.keys:
            self.keys[key] = f"R{len(self.keys) + 1}"
        return self.keys[key]


def register_routes(app, db, user, csrf, key, ok, operation, engine):
    base = "/api/projects/{project_id}/assistant/tasks/{task_id}/proposals/{proposal_id}"

    def lookup(c, actor, project_id, task_id, proposal_id):
        db._project(c, actor["id"], project_id, True)
        task = c.execute("SELECT * FROM assistant_tasks WHERE id=? AND project_id=? AND hidden_at IS NULL",
                         (task_id, project_id)).fetchone()
        proposal = c.execute("SELECT * FROM assistant_proposals WHERE id=? AND task_id=?", (proposal_id, task_id)).fetchone()
        if not task or not proposal:
            raise DomainError("resource_not_found", 404)
        if task["status"] != "completed":
            raise DomainError("proposal_task_not_completed", 409)
        return task, proposal

    def mutate(action, project_id, task_id, proposal_id, payload, request, idempotency_key):
        csrf(request)
        operation(request, f"assistant_proposal_{action}_failed")
        actor = user(request)
        with db.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            db._project(c, actor["id"], project_id, True)
            def change():
                task, proposal = lookup(c, actor, project_id, task_id, proposal_id)
                previous = json.loads(proposal["recheck_json"]) if proposal["recheck_json"] else {}
                if previous.get("status") == "running":
                    raise DomainError("proposal_recheck_running", 409)
                expected = "adopted" if action == "undo" else "proposed"
                if proposal["status"] != expected or (action in ("adopt", "undo") and proposal["kind"] not in ("edit_this", "add_setup")):
                    raise DomainError("proposal_state_invalid", 409)
                if action == "adopt":
                    # The sentence the author means to keep: their rewording when they made one, else the assistant's.
                    after = proposal["after"]
                    if payload.get("after") is not None and payload["after"] != proposal["after"]:
                        try:
                            check_after(proposal["kind"], proposal["before"], payload["after"])
                        except ToolError as error:
                            raise DomainError(error.code, 422) from error
                        after = payload["after"]
                    edited = after != proposal["after"]
                    revision = payload.get("draft_revision")
                    if proposal["kind"] == "edit_this":
                        if revision is None:
                            raise DomainError("invalid_request", 400)
                        draft = c.execute("SELECT * FROM v2_drafts WHERE project_id=? AND status IN ('draft','saved') ORDER BY saved_at DESC LIMIT 1",
                                          (project_id,)).fetchone()
                        if not draft or draft["id"] != proposal["draft_id"] or draft["revision"] != revision or revision <= proposal["draft_revision"]:
                            raise DomainError("proposal_not_applied", 409)
                        fmt = c.execute("SELECT body_format FROM v2_draft_content_formats WHERE draft_id=? AND revision=?",
                                        (draft["id"], revision)).fetchone()
                        body = visible_draft_text(draft["body"], fmt["body_format"] if fmt else "plain_text")
                        if after not in body or proposal["before"] in body:
                            raise DomainError("proposal_not_applied", 409)
                    # A setup for an earlier chapter is carried there by the author; the record keeps their final wording.
                    c.execute("UPDATE assistant_proposals SET status='adopted',decided_at=?,adopted_draft_revision=?,after_edited=?,edited_by_author=?,recheck_json=NULL WHERE id=?",
                              (utcnow(), revision, after if edited else None, 1 if edited else 0, proposal_id))
                elif action == "dismiss":
                    c.execute("UPDATE assistant_proposals SET status='dismissed',decided_at=? WHERE id=?", (utcnow(), proposal_id))
                else:
                    c.execute("UPDATE assistant_proposals SET status='proposed',decided_at=NULL,adopted_draft_revision=NULL,after_edited=NULL,edited_by_author=0,recheck_json=NULL WHERE id=?", (proposal_id,))
                return engine.store.proposal_view(c.execute("SELECT * FROM assistant_proposals WHERE id=?", (proposal_id,)).fetchone())
            data, status = db._idem(c, actor["id"], f"assistant_proposal_{action}:{project_id}:{task_id}:{proposal_id}",
                                   key(idempotency_key), payload, change)
        return ok(request, data, status)

    @app.post(base + "/adopt")
    def adopt(project_id: str, task_id: str, proposal_id: str, payload: Adopt, request: Request,
              idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        return mutate("adopt", project_id, task_id, proposal_id, payload.model_dump(), request, idempotency_key)

    @app.post(base + "/dismiss")
    def dismiss(project_id: str, task_id: str, proposal_id: str, request: Request, payload: Action | None = None,
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        return mutate("dismiss", project_id, task_id, proposal_id, {}, request, idempotency_key)

    @app.post(base + "/undo")
    def undo(project_id: str, task_id: str, proposal_id: str, request: Request, payload: Action | None = None,
             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        return mutate("undo", project_id, task_id, proposal_id, {}, request, idempotency_key)

    @app.post(base + "/recheck")
    def recheck(project_id: str, task_id: str, proposal_id: str, request: Request, payload: Action | None = None,
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        csrf(request)
        operation(request, "assistant_proposal_recheck_failed")
        actor, idem_key = user(request), key(idempotency_key)
        op = f"assistant_proposal_recheck:{project_id}:{task_id}:{proposal_id}"
        with db.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            db._project(c, actor["id"], project_id, True)
            if c.execute("SELECT account_type FROM v2_users WHERE id=?", (actor["id"],)).fetchone()["account_type"] == "visitor":
                raise DomainError("assistant_check_visitor_forbidden", 403)
            def prepare():
                task, proposal = lookup(c, actor, project_id, task_id, proposal_id)
                if proposal["status"] != "adopted" or proposal["kind"] != "edit_this":
                    raise DomainError("proposal_state_invalid", 409)
                previous = json.loads(proposal["recheck_json"]) if proposal["recheck_json"] else {}
                if previous.get("status") == "running":
                    raise DomainError("proposal_recheck_running", 409)
                sentence = proposal["after_edited"] or proposal["after"]  # what the author actually adopted
                if len(sentence) > 600:
                    raise DomainError("passage_too_long", 422)
                if not engine.provider.available:
                    raise DomainError("provider_unavailable", 503)
                reservation = engine.stage13.reserve_workflow(actor["id"], project_id, "assistant_recheck", proposal_id,
                    characters=written_chars(sentence), character_kind="check",
                    reservation_microunits=round(engine.settings.assistant_task_max_cny * 1_000_000), connection=c)
                c.execute("UPDATE assistant_proposals SET recheck_json=? WHERE id=?",
                          (json.dumps({"status": "running", "started_at": utcnow()}), proposal_id))
                return {"status": "running", "reservation_id": reservation}
            initial, status, created = db._idem(c, actor["id"], op, idem_key, {}, prepare, with_created=True)
            if created:
                task, proposal = lookup(c, actor, project_id, task_id, proposal_id)
                task, proposal = dict(task), dict(proposal)
        if not created:
            if initial["status"] == "running":
                raise DomainError("proposal_recheck_running", 409)
            if initial["status"] == "failed":
                raise DomainError(initial["error_code"], status, True)
            return ok(request, initial, status)
        reservation = initial["reservation_id"]
        meter = MeteredProvider(engine.provider, engine._cost, engine.settings.assistant_task_max_cny)
        # Rechecks use current written sources but preserve the proposal's target chapter boundary.
        with db.connection() as c:
            project = db._project(c, actor["id"], project_id)
            task["source_revision"], task["memory_version"] = project["source_revision"], project["current_memory_version"]
        ctx = ToolContext(db, project_id, task, json.loads(task["scope_json"]), CheckSources())
        status = 200
        try:
            with provider_usage(actor["id"], reservation):
                result = check(ctx, proposal["after_edited"] or proposal["after"], meter)
        except ToolError as error:
            result, status = {"status": "failed", "error_code": error.code}, 503
        except Exception:
            result, status = {"status": "failed", "error_code": "internal_error"}, 503
        if status != 200:
            engine.stage13.refund_characters(actor["id"], reservation)
        engine.stage13.settle_reservation(reservation, round(meter.cost * 1_000_000))
        with db.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE assistant_proposals SET recheck_json=? WHERE id=?", (json.dumps(result, ensure_ascii=False), proposal_id))
            c.execute("UPDATE v2_idempotency SET response_json=?,status_code=? WHERE scope=? AND operation=? AND idempotency_key=?",
                      (json.dumps(result, ensure_ascii=False), status, actor["id"], op, idem_key))
        if status != 200:
            raise DomainError(result["error_code"], status, True)
        return ok(request, result)
