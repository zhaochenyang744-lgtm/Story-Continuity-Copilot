"""Author controlled repeat decisions and immutable historical chapter revisions.

Chapter rows are current projections. Source spans, revision snapshots and author
events remain append only; a revised source never silently reconfirms Story Memory.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Header, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .database import DomainError, digest
from .text_content import visible_draft_text


SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_workflow_run_bindings(run_id TEXT PRIMARY KEY REFERENCES v2_runs(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),binding_json TEXT NOT NULL,binding_digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_decision_reuse(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),decision_id TEXT NOT NULL REFERENCES v2_decisions(id),fingerprint TEXT NOT NULL,binding_json TEXT NOT NULL,binding_digest TEXT NOT NULL,enabled INTEGER NOT NULL,revision INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,issue_id));
CREATE INDEX IF NOT EXISTS v2_decision_reuse_match ON v2_decision_reuse(project_id,fingerprint,binding_digest,enabled);
CREATE TABLE IF NOT EXISTS v2_decision_reuse_events(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),policy_id TEXT NOT NULL REFERENCES v2_decision_reuse(id),revision INTEGER NOT NULL,enabled INTEGER NOT NULL,actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,UNIQUE(policy_id,revision));
CREATE TABLE IF NOT EXISTS v2_chapter_revision_history(project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_id TEXT NOT NULL REFERENCES v2_chapters(id),source_revision INTEGER NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,body TEXT NOT NULL,body_format TEXT NOT NULL,source_span_ids_json TEXT NOT NULL,change_set_id TEXT,created_at TEXT NOT NULL,PRIMARY KEY(chapter_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_chapter_content_formats(chapter_id TEXT NOT NULL REFERENCES v2_chapters(id),source_revision INTEGER NOT NULL,body_format TEXT NOT NULL,PRIMARY KEY(chapter_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_source_revision_reviews(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),change_set_id TEXT NOT NULL REFERENCES v2_source_change_sets(id),chapter_id TEXT NOT NULL REFERENCES v2_chapters(id),source_revision INTEGER NOT NULL,memory_id TEXT NOT NULL,memory_json TEXT NOT NULL,old_source_span_ids_json TEXT NOT NULL,new_source_span_id TEXT NOT NULL REFERENCES v2_source_spans(id),status TEXT NOT NULL,revision INTEGER NOT NULL,decision TEXT,note TEXT,actor_user_id TEXT,resulting_memory_version INTEGER,created_at TEXT NOT NULL,resolved_at TEXT);
CREATE INDEX IF NOT EXISTS v2_source_revision_reviews_pending ON v2_source_revision_reviews(project_id,status);
"""


def migrate(c):
    # Execute individual statements: executescript would commit a surrounding migration.
    for statement in SCHEMA.split(";"):
        if statement.strip():
            c.execute(statement)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(kind):
    from .v2_database import new_id
    return new_id(kind)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def current_binding(c, project_id, draft_id):
    project = c.execute("SELECT * FROM v2_projects WHERE id=?", (project_id,)).fetchone()
    draft = c.execute("SELECT id,revision,checksum FROM v2_drafts WHERE id=? AND project_id=?", (draft_id, project_id)).fetchone()
    if not project or not draft:
        return None
    return {"project_id": project_id, "draft_id": draft_id, "draft_revision": draft["revision"], "draft_checksum": draft["checksum"], "source_revision": project["source_revision"], "memory_version": project["current_memory_version"], "author_context_version": project["author_context_version"], "alias_version": project["alias_version"]}


def bind_run(c, run_id):
    run = c.execute("SELECT * FROM v2_runs WHERE id=?", (run_id,)).fetchone()
    if run:
        binding = current_binding(c, run["project_id"], run["draft_id"])
        c.execute("INSERT OR IGNORE INTO v2_workflow_run_bindings VALUES(?,?,?,?)", (run_id, run["project_id"], _json(binding), digest(binding)))


def binding_is_current(c, run):
    bound = c.execute("SELECT * FROM v2_workflow_run_bindings WHERE run_id=?", (run["id"],)).fetchone()
    if bound:
        return bound["binding_digest"] == digest(current_binding(c, run["project_id"], run["draft_id"]))
    # Historic runs cannot prove a corpus binding after a historical revision.
    return not c.execute("SELECT 1 FROM v2_source_change_sets WHERE project_id=? AND mode='revise' AND status='committed' AND committed_at>=?", (run["project_id"], run["created_at"])).fetchone()


def require_run_context(c, run):
    """Preserve the existing direct-draft-successor flow, but reject old context."""
    bound = c.execute("SELECT binding_json FROM v2_workflow_run_bindings WHERE run_id=?", (run["id"],)).fetchone()
    if not bound:
        if not binding_is_current(c, run):
            raise DomainError("run_basis_changed", 409)
        return
    binding = json.loads(bound["binding_json"])
    current = current_binding(c, run["project_id"], run["draft_id"])
    if not current or any(binding[name] != current[name] for name in ("project_id", "source_revision", "memory_version", "author_context_version", "alias_version")):
        raise DomainError("run_basis_changed", 409)


def pending_reviews(c, project_id):
    return c.execute("SELECT COUNT(*) FROM v2_source_revision_reviews WHERE project_id=? AND status='pending'", (project_id,)).fetchone()[0]


def require_review_complete(c, project_id):
    count = pending_reviews(c, project_id)
    if count:
        raise DomainError("source_revision_review_required", 409, False, {"pending_count": count, "review_path": f"/projects/{project_id}/sources#long-term-review"})


def memory_review_flags(c, memory, current_version):
    source_current = bool(memory["source_span_id"] and c.execute("SELECT 1 FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id AND ch.source_revision=s.source_revision WHERE s.id=? AND s.project_id=?", (memory["source_span_id"], memory["project_id"])).fetchone())
    needs_review = False
    if memory["version"] == current_version:
        for row in c.execute("SELECT memory_id,memory_json FROM v2_source_revision_reviews WHERE project_id=? AND status='pending'", (memory["project_id"],)).fetchall():
            if (memory["id"] == row["memory_id"] or memory["id"].startswith(row["memory_id"] + "-v")) and _memory_signature(memory) == _memory_signature(json.loads(row["memory_json"])):
                needs_review = True
                break
    return {"requires_source_review": needs_review, "source_is_current": source_current}


def _issue_fingerprint(c, issue):
    claim = c.execute("SELECT text FROM v2_run_claims WHERE id=? AND run_id=?", (issue["claim_span_id"], issue["run_id"])).fetchone()
    evidence = c.execute("SELECT e.*,s.body AS source_body,s.source_revision AS span_revision FROM v2_evidence e JOIN v2_source_spans s ON s.id=e.span_id AND s.project_id=e.project_id WHERE e.project_id=? AND e.issue_id=? ORDER BY e.span_id,e.excerpt,e.relation", (issue["project_id"], issue["id"])).fetchall()
    if not claim or not evidence:
        raise DomainError("decision_reuse_unavailable", 409)
    # Structured proposals are part of the question the author answered. The
    # same sentence and citation can support a different fact or edit next time.
    proposals = {key: json.loads(issue[key]) if issue[key] else None for key in ("proposed_change_json", "suggested_revision_json", "available_actions_json")}
    if isinstance(proposals["available_actions_json"], list):
        proposals["available_actions_json"] = sorted(proposals["available_actions_json"])
    return digest({"claim": claim["text"], "category": issue["category"], "classification": issue["classification"], "nature": issue["nature"], "severity": issue["severity"], "evidence_status": issue["evidence_status"], "review_contract_version": issue["review_contract_version"], "proposals": proposals, "evidence": [{key: row[key] for key in ("chapter_id", "span_id", "excerpt", "relation", "sufficiency", "source_body", "span_revision")} for row in evidence]})


def _policy_view(c, row):
    decision = c.execute("SELECT * FROM v2_decisions WHERE id=?", (row["decision_id"],)).fetchone()
    binding = json.loads(row["binding_json"])
    current = current_binding(c, row["project_id"], binding["draft_id"])
    changed = next((key for key in binding if not current or current.get(key) != binding[key]), None)
    return {"id": row["id"], "issue_id": row["issue_id"], "run_id": decision["run_id"], "decision": decision["decision"], "note": decision["note"], "enabled": bool(row["enabled"]), "revision": row["revision"], "is_current": changed is None, "invalidation_reason": (changed + "_changed") if changed else None, "scope": binding, "updated_at": row["updated_at"]}


def issue_reuse(c, issue, run):
    own = c.execute("SELECT * FROM v2_decision_reuse WHERE project_id=? AND issue_id=?", (issue["project_id"], issue["id"])).fetchone()
    result = {"reuse_policy": _policy_view(c, own) if own else None, "reused_decision": None}
    if not binding_is_current(c, run):
        return result
    bound = c.execute("SELECT binding_digest FROM v2_workflow_run_bindings WHERE run_id=?", (run["id"],)).fetchone()
    if not bound:
        return result
    try:
        fingerprint = _issue_fingerprint(c, issue)
    except DomainError:
        return result
    policy = c.execute("SELECT * FROM v2_decision_reuse WHERE project_id=? AND fingerprint=? AND binding_digest=? AND enabled=1 AND issue_id!=? ORDER BY updated_at DESC,id LIMIT 1", (issue["project_id"], fingerprint, bound["binding_digest"], issue["id"])).fetchone()
    if policy:
        result["reused_decision"] = {**_policy_view(c, policy), "status": "previously_reviewed", "requires_new_decision": False, "source_issue_id": policy["issue_id"], "review_path": f"/projects/{issue['project_id']}/sources#long-term-review"}
    return result


def open_issue_count(c, project_id, severity=None):
    issues = c.execute("SELECT * FROM v2_issues WHERE project_id=? AND status='open'", (project_id,)).fetchall()
    if severity:
        issues = [issue for issue in issues if issue["severity"] == severity]
    if not c.execute("SELECT 1 FROM v2_decision_reuse WHERE project_id=? AND enabled=1", (project_id,)).fetchone():
        return len(issues)
    runs = {}
    count = 0
    for issue in issues:
        if issue["run_id"] not in runs:
            runs[issue["run_id"]] = c.execute("SELECT * FROM v2_runs WHERE id=?", (issue["run_id"],)).fetchone()
        if not issue_reuse(c, issue, runs[issue["run_id"]])["reused_decision"]:
            count += 1
    return count


def set_reuse(db, user_id, project_id, issue_id, payload, key):
    with db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        db._project(c, user_id, project_id, True)
        def apply():
            issue = c.execute("SELECT * FROM v2_issues WHERE id=? AND project_id=?", (issue_id, project_id)).fetchone()
            if not issue:
                raise DomainError("resource_not_found", 404)
            decision = c.execute("SELECT * FROM v2_decisions WHERE issue_id=? AND project_id=?", (issue_id, project_id)).fetchone()
            policy = c.execute("SELECT * FROM v2_decision_reuse WHERE issue_id=? AND project_id=?", (issue_id, project_id)).fetchone()
            if payload["base_policy_revision"] != (policy["revision"] if policy else 0):
                raise DomainError("decision_reuse_revision_conflict", 409)
            if not decision or decision["decision"] not in {"keep_intentional", "false_positive"}:
                raise DomainError("decision_reuse_unavailable", 409)
            run = c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?", (issue["run_id"], project_id)).fetchone()
            bound = c.execute("SELECT * FROM v2_workflow_run_bindings WHERE run_id=?", (run["id"],)).fetchone()
            if payload["enabled"] and (not bound or not binding_is_current(c, run)):
                raise DomainError("decision_reuse_stale", 409)
            stamp, policy_id = _now(), policy["id"] if policy else _id("reuse")
            revision = (policy["revision"] if policy else 0) + 1
            if policy:
                c.execute("UPDATE v2_decision_reuse SET enabled=?,revision=?,updated_at=? WHERE id=?", (int(payload["enabled"]), revision, stamp, policy_id))
            else:
                if not bound:
                    raise DomainError("decision_reuse_unavailable", 409)
                c.execute("INSERT INTO v2_decision_reuse VALUES(?,?,?,?,?,?,?,?,?,?,?)", (policy_id, project_id, issue_id, decision["id"], _issue_fingerprint(c, issue), bound["binding_json"], bound["binding_digest"], int(payload["enabled"]), revision, stamp, stamp))
            c.execute("INSERT INTO v2_decision_reuse_events VALUES(?,?,?,?,?,?,?)", (_id("reuseevent"), project_id, policy_id, revision, int(payload["enabled"]), user_id, stamp))
            return {"reuse_policy": _policy_view(c, c.execute("SELECT * FROM v2_decision_reuse WHERE id=?", (policy_id,)).fetchone())}
        return db._idem(c, user_id, f"decision_reuse:{project_id}:{issue_id}", key, payload, apply)


def chapter_format(c, chapter):
    row = c.execute("SELECT body_format FROM v2_chapter_content_formats WHERE chapter_id=? AND source_revision=?", (chapter["id"], chapter["source_revision"])).fetchone()
    if row:
        return row[0]
    change = c.execute("SELECT draft_id,draft_revision,input_method FROM v2_source_change_sets WHERE project_id=? AND target_source_revision=? AND status='committed'", (chapter["project_id"], chapter["source_revision"])).fetchone()
    if change and change["input_method"] == "draft_complete":
        row = c.execute("SELECT body_format FROM v2_draft_content_formats WHERE draft_id=? AND revision=?", (change["draft_id"], change["draft_revision"])).fetchone()
        if row:
            return row[0]
    return "plain_text"


def _chapter_view(c, chapter):
    has_body = bool(chapter["body"].strip())
    fragments = [] if has_body else [dict(row) for row in c.execute("SELECT id,label,body FROM v2_source_spans WHERE project_id=? AND chapter_id=? AND source_revision=? ORDER BY rowid", (chapter["project_id"], chapter["id"], chapter["source_revision"])).fetchall()]
    return {"id": chapter["id"], "title": chapter["title"], "number": chapter["chapter_number"], "source_revision": chapter["source_revision"], "body": chapter["body"] if has_body else "\n\n".join(row["body"] for row in fragments), "body_format": chapter_format(c, chapter) if has_body else "plain_text", "body_origin": "chapter_body" if has_body else "source_fragments" if fragments else "unavailable", "revision_editable": has_body, "body_notice": None if has_body else "本章节只保存了来源片段，未保存完整章节正文；以下片段仅供查阅，不能作为完整原稿进行修订。", "source_fragments": fragments}


def require_complete_chapter(chapter):
    if not chapter["body"].strip():
        raise DomainError("chapter_full_text_unavailable", 409, False, {"reason": "only_source_fragments_available", "review_path": f"/projects/{chapter['project_id']}/sources", "recovery": "import_complete_manuscript_as_project"})


def _memory_signature(memory):
    return {key: memory[key] for key in ("memory_type", "subject", "predicate", "value", "source_span_id")}


def _impact(c, project_id, chapter_id):
    project = c.execute("SELECT * FROM v2_projects WHERE id=?", (project_id,)).fetchone()
    spans = c.execute("SELECT s.id FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.source_revision=s.source_revision WHERE s.project_id=? AND s.chapter_id=?", (project_id, chapter_id)).fetchall()
    span_ids = [row[0] for row in spans]
    memories = [dict(row) for row in c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?)", (project_id, project["current_memory_version"], project["current_memory_version"], project["current_memory_version"])).fetchall() if row["source_span_id"] in span_ids]
    runs = c.execute("SELECT COUNT(*) FROM v2_runs WHERE project_id=? AND status IN ('queued','running','completed')", (project_id,)).fetchone()[0]
    return {"affected_memory_count": len(memories), "affected_analysis_count": runs, "affected_memory": memories, "old_source_span_ids": span_ids, "base_memory_version": project["current_memory_version"], "requires_memory_delta": True}


def _preview_view(change):
    content = json.loads(change["content_json"])
    return {"id": change["id"], "chapter_id": content["chapter_id"], "content_sha256": change["content_hash"], "base_source_revision": change["base_source_revision"], "base_chapter_revision": content["base_chapter_revision"], "target_source_revision": change["target_source_revision"], "before": content["before"], "after": content["after"], "impact": content["impact"], "status": change["status"], "expires_at": change["expires_at"]}


def preview_revision(db, user_id, project_id, chapter_id, payload, key):
    with db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        project = db._project(c, user_id, project_id, True)
        def preview():
            chapter = c.execute("SELECT * FROM v2_chapters WHERE id=? AND project_id=?", (chapter_id, project_id)).fetchone()
            if not chapter:
                raise DomainError("resource_not_found", 404)
            require_complete_chapter(chapter)
            if project["source_revision"] != payload["base_source_revision"] or chapter["source_revision"] != payload["base_chapter_revision"]:
                raise DomainError("source_revision_conflict", 409)
            require_review_complete(c, project_id)
            coverage = db._memory_coverage(c, project_id)
            if coverage["status"] not in {"ready_current", "ready_partial"}:
                raise DomainError("source_revision_context_review_required", 409, False, {"blocking_reason": coverage["blocking_reason"], "review_path": f"/projects/{project_id}/memory"})
            if not payload["body"].strip() or not payload["title"].strip():
                raise DomainError("chapter_revision_empty", 422)
            after = {"title": payload["title"].strip(), "body": payload["body"], "body_format": payload.get("body_format", "plain_text")}
            before = {"title": chapter["title"], "body": chapter["body"], "body_format": chapter_format(c, chapter)}
            if after == before:
                raise DomainError("chapter_revision_unchanged", 422)
            content = {"chapter_id": chapter_id, "base_chapter_revision": chapter["source_revision"], "before": before, "after": after, "text": after["body"], "impact": _impact(c, project_id, chapter_id), "audit": {"created_by_user_id": user_id, "request_fingerprint": digest(payload)}}
            change_id, stamp = _id("chapterrevision"), _now()
            expires = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
            chapters = [{"id": chapter_id, "title": after["title"], "order": chapter["chapter_number"], "body": after["body"], "source_body": visible_draft_text(after["body"], after["body_format"])}]
            c.execute("INSERT INTO v2_source_change_sets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (change_id, project_id, user_id, project["source_revision"], project["source_revision"] + 1, "revise", "chapter_revision", digest(content), _json(content), _json(chapters), "previewed", None, expires, stamp, None, None, None, None, None, None, None))
            c.execute("INSERT INTO v2_source_change_set_audits VALUES(?,?,?,?,?,?)", (_id("sourceaudit"), project_id, change_id, "revision_previewed", _json(content["audit"]), stamp))
            return {"revision_preview": _preview_view(c.execute("SELECT * FROM v2_source_change_sets WHERE id=?", (change_id,)).fetchone())}
        return db._idem(c, user_id, f"chapter_revision_preview:{project_id}:{chapter_id}", key, payload, preview, 201)


def _review_view(row):
    memory = json.loads(row["memory_json"])
    return {"id": row["id"], "chapter_id": row["chapter_id"], "source_revision": row["source_revision"], "memory": {"id": row["memory_id"], "type": memory["memory_type"], "subject": memory["subject"], "predicate": memory["predicate"], "value": memory["value"]}, "old_source_span_ids": json.loads(row["old_source_span_ids_json"]), "new_source_span_id": row["new_source_span_id"], "status": row["status"], "revision": row["revision"], "decision": row["decision"], "note": row["note"], "resulting_memory_version": row["resulting_memory_version"], "review_path": f"/projects/{row['project_id']}/sources#long-term-review"}


def commit_revision(db, user_id, project_id, change_id, payload, key):
    with db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        project = db._project(c, user_id, project_id, True)
        def commit():
            change = c.execute("SELECT * FROM v2_source_change_sets WHERE id=? AND project_id=? AND user_id=? AND mode='revise'", (change_id, project_id, user_id)).fetchone()
            if not change:
                raise DomainError("resource_not_found", 404)
            if payload["confirm"] is not True:
                raise DomainError("confirmation_required", 400)
            if payload["content_sha256"] != change["content_hash"]:
                raise DomainError("source_hash_mismatch", 409)
            if change["status"] == "committed":
                return json.loads(change["commit_result_json"])
            if change["expires_at"] <= _now():
                raise DomainError("source_change_set_expired", 409)
            content = json.loads(change["content_json"])
            if digest(content) != change["content_hash"]:
                raise DomainError("source_hash_mismatch", 409)
            chapter = c.execute("SELECT * FROM v2_chapters WHERE id=? AND project_id=?", (content["chapter_id"], project_id)).fetchone()
            if not chapter or project["source_revision"] != change["base_source_revision"] or chapter["source_revision"] != content["base_chapter_revision"]:
                raise DomainError("source_revision_conflict", 409)
            require_complete_chapter(chapter)
            require_review_complete(c, project_id)
            coverage = db._memory_coverage(c, project_id)
            if coverage["status"] not in {"ready_current", "ready_partial"}:
                raise DomainError("source_revision_context_review_required", 409, False, {"blocking_reason": coverage["blocking_reason"], "review_path": f"/projects/{project_id}/memory"})
            impact = _impact(c, project_id, chapter["id"])
            if impact["base_memory_version"] != content["impact"]["base_memory_version"] or impact["affected_memory"] != content["impact"]["affected_memory"]:
                raise DomainError("source_revision_impact_changed", 409)
            stamp, span_id, target = _now(), _id("span"), change["target_source_revision"]
            c.execute("INSERT OR IGNORE INTO v2_chapter_revision_history VALUES(?,?,?,?,?,?,?,?,?,?)", (project_id, chapter["id"], chapter["source_revision"], chapter["title"], chapter["summary"], chapter["body"], content["before"]["body_format"], _json(impact["old_source_span_ids"]), None, stamp))
            after = content["after"]
            c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?,?)", (span_id, project_id, chapter["id"], "chapter_revision", visible_draft_text(after["body"], after["body_format"]), target))
            c.execute("UPDATE v2_chapters SET title=?,body=?,summary='',source_revision=? WHERE id=? AND project_id=?", (after["title"], after["body"], target, chapter["id"], project_id))
            c.execute("INSERT INTO v2_chapter_content_formats VALUES(?,?,?)", (chapter["id"], target, after["body_format"]))
            c.execute("INSERT INTO v2_chapter_revision_history VALUES(?,?,?,?,?,?,?,?,?,?)", (project_id, chapter["id"], target, after["title"], "", after["body"], after["body_format"], _json([span_id]), change_id, stamp))
            for memory in impact["affected_memory"]:
                c.execute("INSERT INTO v2_source_revision_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (_id("sourcereview"), project_id, change_id, chapter["id"], target, memory["id"], _json(memory), _json(impact["old_source_span_ids"]), span_id, "pending", 1, None, None, None, None, stamp, None))
            c.execute("UPDATE v2_projects SET source_revision=?,updated_at=? WHERE id=?", (target, stamp, project_id))
            c.execute("UPDATE v2_source_change_sets SET status='committed',committed_at=? WHERE id=?", (stamp, change_id))
            audit = {"actor_user_id": user_id, "chapter_id": chapter["id"], "old_source_span_ids": impact["old_source_span_ids"], "new_source_span_id": span_id, "target_source_revision": target, "affected_memory_count": impact["affected_memory_count"], "affected_analysis_count": impact["affected_analysis_count"], "automatic_canon_changes": 0}
            c.execute("INSERT INTO v2_source_change_set_audits VALUES(?,?,?,?,?,?)", (_id("sourceaudit"), project_id, change_id, "revision_committed", _json(audit), stamp))
            final = c.execute("SELECT * FROM v2_source_change_sets WHERE id=?", (change_id,)).fetchone()
            result = {"revision_preview": {**_preview_view(final), "impact": impact}, "source_change_set": db._source_change_set_view(final), "source_revision_reviews": [_review_view(row) for row in c.execute("SELECT * FROM v2_source_revision_reviews WHERE change_set_id=?", (change_id,)).fetchall()], "review_path": f"/projects/{project_id}/sources#long-term-review", "next_step": "review_affected_memory_then_memory_delta"}
            c.execute("UPDATE v2_source_change_sets SET commit_result_json=? WHERE id=?", (_json(result), change_id))
            return result
        return db._idem(c, user_id, f"chapter_revision_commit:{project_id}:{change_id}", key, payload, commit)


def resolve_review(db, user_id, project_id, review_id, payload, key):
    with db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        project = db._project(c, user_id, project_id, True)
        def resolve():
            review = c.execute("SELECT * FROM v2_source_revision_reviews WHERE id=? AND project_id=?", (review_id, project_id)).fetchone()
            if not review:
                raise DomainError("resource_not_found", 404)
            if payload["confirm"] is not True:
                raise DomainError("confirmation_required", 400)
            if review["status"] != "pending" or review["revision"] != payload["base_revision"] or project["current_memory_version"] != payload["base_memory_version"]:
                raise DomainError("source_review_revision_conflict", 409)
            original = json.loads(review["memory_json"])
            base = project["current_memory_version"]
            matching = [row for row in c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?)", (project_id, base, base, base)).fetchall() if (row["id"] == review["memory_id"] or row["id"].startswith(review["memory_id"] + "-v")) and _memory_signature(row) == _memory_signature(original)]
            if len(matching) != 1:
                raise DomainError("source_review_memory_changed", 409)
            evidence = payload.get("evidence_span_id")
            if payload["decision"] == "retain":
                if evidence != review["new_source_span_id"] or not c.execute("SELECT 1 FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.source_revision=s.source_revision WHERE s.id=? AND s.project_id=?", (evidence, project_id)).fetchone():
                    raise DomainError("source_review_current_evidence_required", 422)
            target, stamp = base + 1, _now()
            c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)", (project_id, target, "current", base, stamp))
            rows = c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=?", (project_id, base)).fetchall()
            for row in rows:
                values = dict(row)
                values.update(id=row["id"] + "-v" + str(target), version=target)
                if row["id"] == matching[0]["id"]:
                    if payload["decision"] == "retain":
                        values["source_span_id"] = evidence
                    else:
                        values["valid_to"] = base
                c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", tuple(values[k] for k in ("id", "project_id", "version", "memory_type", "subject", "predicate", "value", "source_span_id", "review_status", "valid_from", "valid_to", "source_claim_id")))
            c.execute("UPDATE v2_memory_versions SET status='superseded' WHERE project_id=? AND version=?", (project_id, base))
            c.execute("UPDATE v2_projects SET current_memory_version=?,updated_at=? WHERE id=?", (target, stamp, project_id))
            c.execute("UPDATE v2_source_revision_reviews SET status='resolved',revision=revision+1,decision=?,note=?,actor_user_id=?,resulting_memory_version=?,resolved_at=? WHERE id=?", (payload["decision"], payload.get("note"), user_id, target, stamp, review_id))
            c.execute("INSERT INTO v2_source_change_set_audits VALUES(?,?,?,?,?,?)", (_id("sourceaudit"), project_id, review["change_set_id"], "affected_memory_reviewed", _json({"review_id": review_id, "memory_id": review["memory_id"], "decision": payload["decision"], "evidence_span_id": evidence, "base_memory_version": base, "target_memory_version": target, "actor_user_id": user_id}), stamp))
            return {"source_revision_review": _review_view(c.execute("SELECT * FROM v2_source_revision_reviews WHERE id=?", (review_id,)).fetchone()), "memory_version": target, "pending_count": pending_reviews(c, project_id), "next_step": "review_affected_memory" if pending_reviews(c, project_id) else "run_memory_delta", "review_path": f"/projects/{project_id}/memory"}
        return db._idem(c, user_id, f"source_review_resolve:{project_id}:{review_id}", key, payload, resolve)


def review_state(db, user_id, project_id):
    with db.connection() as c:
        c.execute("BEGIN")
        project = db._project(c, user_id, project_id)
        policies = [_policy_view(c, row) for row in c.execute("SELECT * FROM v2_decision_reuse WHERE project_id=? ORDER BY updated_at DESC,id", (project_id,)).fetchall()]
        eligible = []
        for row in c.execute("SELECT d.*,i.explanation,cl.text AS claim_text FROM v2_decisions d JOIN v2_issues i ON i.id=d.issue_id JOIN v2_run_claims cl ON cl.id=i.claim_span_id WHERE d.project_id=? AND d.decision IN ('keep_intentional','false_positive') ORDER BY d.created_at DESC", (project_id,)).fetchall():
            policy = next((item for item in policies if item["issue_id"] == row["issue_id"]), None)
            if policy:
                policy.update(claim_text=row["claim_text"], explanation=row["explanation"])
                continue
            run = c.execute("SELECT * FROM v2_runs WHERE id=?", (row["run_id"],)).fetchone()
            bound = c.execute("SELECT 1 FROM v2_workflow_run_bindings WHERE run_id=?", (run["id"],)).fetchone()
            current = bool(bound) and binding_is_current(c, run)
            eligible.append({"id": None, "issue_id": row["issue_id"], "run_id": row["run_id"], "decision": row["decision"], "note": row["note"], "claim_text": row["claim_text"], "explanation": row["explanation"], "enabled": False, "revision": 0, "is_current": current, "invalidation_reason": None if current else "run_basis_not_current"})
        reviews = [_review_view(row) for row in c.execute("SELECT * FROM v2_source_revision_reviews WHERE project_id=? ORDER BY created_at,id", (project_id,)).fetchall()]
        for review in reviews:
            review["new_source_excerpt"] = c.execute("SELECT body FROM v2_source_spans WHERE id=?", (review["new_source_span_id"],)).fetchone()[0][:2000]
        return {"project_id": project_id, "source_revision": project["source_revision"], "memory_version": project["current_memory_version"], "reusable_decisions": policies + eligible, "source_revision_reviews": reviews, "chapters": [_chapter_view(c, row) for row in c.execute("SELECT * FROM v2_chapters WHERE project_id=? ORDER BY chapter_number", (project_id,)).fetchall()]}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReusePatch(Strict):
    enabled: StrictBool
    base_policy_revision: StrictInt = Field(ge=0)


class RevisionPreview(Strict):
    base_source_revision: StrictInt = Field(ge=1)
    base_chapter_revision: StrictInt = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1_000_000)
    body_format: Literal["plain_text", "markdown"] = "plain_text"


class RevisionCommit(Strict):
    confirm: StrictBool
    content_sha256: str = Field(min_length=64, max_length=64)


class SourceReviewResolve(Strict):
    base_revision: StrictInt = Field(ge=1)
    base_memory_version: StrictInt = Field(ge=1)
    decision: Literal["retain", "invalidate"]
    confirm: StrictBool
    note: str = Field(min_length=1, max_length=2000)
    evidence_span_id: str | None = None


def register_long_term_routes(app, db, user, csrf, key, ok, operation):
    @app.get("/api/projects/{project_id}/long-term-review")
    def state(project_id: str, request: Request):
        return ok(request, review_state(db, user(request)["id"], project_id))

    @app.post("/api/projects/{project_id}/issues/{issue_id}/reuse")
    def reuse(project_id: str, issue_id: str, payload: ReusePatch, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        csrf(request); operation(request, "decision_reuse_failed")
        data, status = set_reuse(db, user(request)["id"], project_id, issue_id, payload.model_dump(), key(idempotency_key))
        return ok(request, data, status)

    @app.post("/api/projects/{project_id}/chapters/{chapter_id}/revisions/preview", status_code=201)
    def preview(project_id: str, chapter_id: str, payload: RevisionPreview, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        csrf(request); operation(request, "chapter_revision_preview_failed")
        data, status = preview_revision(db, user(request)["id"], project_id, chapter_id, payload.model_dump(), key(idempotency_key))
        return ok(request, data, status)

    @app.post("/api/projects/{project_id}/chapter-revisions/{change_id}/commit")
    def commit(project_id: str, change_id: str, payload: RevisionCommit, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        csrf(request); operation(request, "chapter_revision_commit_failed")
        data, status = commit_revision(db, user(request)["id"], project_id, change_id, payload.model_dump(), key(idempotency_key))
        return ok(request, data, status)

    @app.post("/api/projects/{project_id}/source-reviews/{review_id}/resolve")
    def resolve(project_id: str, review_id: str, payload: SourceReviewResolve, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        csrf(request); operation(request, "source_review_resolve_failed")
        data, status = resolve_review(db, user(request)["id"], project_id, review_id, payload.model_dump(), key(idempotency_key))
        return ok(request, data, status)
