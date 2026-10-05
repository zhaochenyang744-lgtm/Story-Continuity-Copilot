"""Checking chosen written chapters (v1.6.0).

An author ticks up to CHAPTER_CHECK_MAX already written chapters and checks them together. Each
sentence is reviewed by the screened pipeline against earlier chapters only (its chapter number
bounds the passages it may cite), and the outcome is a read-only report grouped by chapter. It does
not enter the draft's decision workflow: an author who wants to change a chapter revises it on the
same page. Visitors cannot run it, and it spends the author's daily check characters.
"""
from __future__ import annotations

import json
from typing import Any

from .database import DomainError
from .review_screening import SCREENED_RETRIEVAL_METHOD_VERSION
from .text_content import written_chars

CHAPTER_CHECK_MAX = 8
RUN_TYPE = "chapter_check"
EVIDENCE_EXCERPT_CHARS = 160


def _selected_spans(db: Any, c: Any, project_id: str, chapter_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(chapter_ids)
    return [span for span in db._current_spans(c, project_id) if span["chapter_id"] in wanted]


def _validate_selection(chapter_ids: Any) -> list[str]:
    if not isinstance(chapter_ids, list) or not chapter_ids or not all(isinstance(item, str) and item for item in chapter_ids):
        raise DomainError("chapter_selection_invalid", 422)
    unique = list(dict.fromkeys(chapter_ids))
    if len(unique) > CHAPTER_CHECK_MAX:
        raise DomainError("chapter_selection_too_large", 422, False, {"limit": CHAPTER_CHECK_MAX, "selected": len(unique)})
    return unique


def selection_characters(db: Any, user_id: str, project_id: str, chapter_ids: list[str]) -> int:
    """Characters a check of these chapters spends: the text of their current passages."""
    chapter_ids = _validate_selection(chapter_ids)
    with db.connection() as c:
        db._project(c, user_id, project_id)
        return sum(written_chars(span["body"]) for span in _selected_spans(db, c, project_id, chapter_ids))


def create(db: Any, user_id: str, project_id: str, chapter_ids: list[str], key: str, provenance: dict[str, str]):
    """A queued chapter-check run; (response, status, created) like the other run creators."""
    chapter_ids = _validate_selection(chapter_ids)
    from .v2_database import new_id, utcnow  # late import: v2_database imports this module's siblings

    with db.connection() as c:
        def factory() -> dict[str, Any]:
            project = db._project(c, user_id, project_id, True)
            known = {row["id"] for row in c.execute("SELECT id FROM v2_chapters WHERE project_id=?", (project_id,)).fetchall()}
            if any(chapter_id not in known for chapter_id in chapter_ids):
                raise DomainError("chapter_selection_invalid", 422)
            coverage = db._memory_coverage(c, project_id)
            if coverage["status"] not in {"ready_partial", "ready_current"} or coverage["counts"]["pending_canon_count"] != 0:
                raise DomainError("insufficient_project_context", 422)
            spans = _selected_spans(db, c, project_id, chapter_ids)
            if not spans:
                raise DomainError("chapter_selection_empty", 422)
            draft = c.execute("SELECT * FROM v2_drafts WHERE project_id=? ORDER BY saved_at DESC LIMIT 1", (project_id,)).fetchone()
            if not draft:
                raise DomainError("draft_invalid", 422)
            stamp, run_id = utcnow(), new_id("run")
            author_version, author_digest = db._current_author_context_binding(c, project)
            c.execute(
                "INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,run_type,source_span_ids_json,root_run_id,attempt_number,author_context_version,author_context_snapshot_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, project_id, draft["id"], project["source_revision"], "queued", "queued", provenance["provider_label"], stamp,
                 provenance["model_label"], provenance["prompt_version"], provenance["schema_version"], SCREENED_RETRIEVAL_METHOD_VERSION,
                 project["current_memory_version"], "provider", RUN_TYPE, json.dumps([span["id"] for span in spans]), run_id, 1,
                 author_version, author_digest))
            db._append_run_event(c, run_id, "queued", "queued", None, stamp)
            return {"run_id": run_id, "project_id": project_id, "run_type": RUN_TYPE, "status": "queued", "stage": "queued",
                    "chapter_ids": chapter_ids, "created_at": stamp}

        return db._idem(c, user_id, "chapter_check:" + project_id, key, {"chapter_ids": chapter_ids}, factory, 202, with_created=True)


def run_input(db: Any, project_id: str, run_id: str) -> dict[str, Any]:
    """The screened-pipeline input: the chosen chapters' sentences, each bounded to earlier chapters."""
    from .v2_database import split_continuity_claims

    with db.connection() as c:
        run = c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=? AND run_type=?", (run_id, project_id, RUN_TYPE)).fetchone()
        if not run:
            raise DomainError("resource_not_found", 404)
        span_ids = set(json.loads(run["source_span_ids_json"] or "[]"))
        sources = db._current_spans(c, project_id)
        chosen = [span for span in sources if span["id"] in span_ids]
        if not chosen:
            raise DomainError("run_basis_changed", 409)
        titles = {row["id"]: row["title"] for row in c.execute("SELECT id,title FROM v2_chapters WHERE project_id=?", (project_id,)).fetchall()}
        memory = db._confirmed_memory(c, project_id, run["source_memory_version"])
    claims = []
    for span in chosen:
        for text in split_continuity_claims(span["body"]):
            claims.append({"id": f"claim-{run_id}-{len(claims) + 1}", "text": text, "chapter_number": span["chapter_number"], "context": span["id"]})
    if not claims:
        raise DomainError("chapter_selection_empty", 422)
    return {"pipeline": "screened", "claims": claims, "memory": memory, "sources": sources,
            "contexts": {span["id"]: span["body"] for span in chosen},
            "draft": {"id": run_id, "revision": run["source_revision"], "body": "\n".join(claim["text"] for claim in claims)},
            "chapter_titles": titles}


def report(data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """A read-only report grouped by chapter: each issue with its sentence and where its evidence comes from."""
    claims = {claim["id"]: claim for claim in data["claims"]}
    spans = {span["id"]: span for span in data["sources"]}
    titles = data.get("chapter_titles") or {}
    chapters: dict[int, dict[str, Any]] = {}
    for claim in data["claims"]:
        span = spans[claim["context"]]
        chapters.setdefault(claim["chapter_number"], {"chapter_id": span["chapter_id"], "chapter_number": claim["chapter_number"],
                                                      "chapter_title": titles.get(span["chapter_id"], ""), "sentences": 0, "issues": [], "undecided": 0})
        chapters[claim["chapter_number"]]["sentences"] += 1
    for issue in result.get("issues") or []:
        claim = claims.get(issue.get("claim_span_id"))
        if not claim:
            continue
        evidence = []
        for item in issue.get("evidence") or []:
            span = spans.get(item.get("span_id"))
            if not span:
                continue
            excerpt = item.get("excerpt") or item.get("prompt_excerpt") or span["body"]
            evidence.append({"chapter_number": span["chapter_number"], "chapter_title": titles.get(span["chapter_id"], ""),
                             "excerpt": str(excerpt)[:EVIDENCE_EXCERPT_CHARS]})
        chapters[claim["chapter_number"]]["issues"].append({
            "sentence": claim["text"], "nature": issue.get("nature"), "category": issue.get("category"), "severity": issue.get("severity"),
            "explanation": issue.get("explanation") or "", "evidence": evidence})
    for row in result.get("undecided_claims") or []:
        claim = claims.get(row.get("claim_span_id"))
        if claim:
            chapters[claim["chapter_number"]]["undecided"] += 1
    ordered = [chapters[number] for number in sorted(chapters)]
    return {"chapters": ordered, "issue_count": sum(len(row["issues"]) for row in ordered),
            "undecided_count": sum(row["undecided"] for row in ordered)}


def recent(db: Any, user_id: str, project_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """The latest chapter checks of a project, newest first, with their reports when finished."""
    with db.connection() as c:
        db._project(c, user_id, project_id)
        rows = c.execute(
            "SELECT r.id,r.status,r.stage,r.error_code,r.created_at,r.completed_at,r.source_span_ids_json,a.result_json FROM v2_runs r "
            "LEFT JOIN v2_analysis_results a ON a.run_id=r.id WHERE r.project_id=? AND r.run_type=? ORDER BY r.created_at DESC,r.rowid DESC LIMIT ?",
            (project_id, RUN_TYPE, max(1, min(limit, 20)))).fetchall()
    return [{"run_id": row["id"], "status": row["status"], "stage": row["stage"], "error_code": row["error_code"],
             "created_at": row["created_at"], "completed_at": row["completed_at"],
             "report": json.loads(row["result_json"]) if row["result_json"] else None} for row in rows]
