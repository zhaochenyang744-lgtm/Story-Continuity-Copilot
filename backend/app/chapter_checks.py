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

from . import long_term_workflow as workflow
from .database import DomainError
from .review_screening import SCREENED_RETRIEVAL_METHOD_VERSION
from .text_content import written_chars

CHAPTER_CHECK_MAX = 8
# Measured on the second long-text formal run (lf2-formal, 2026-10-05): 0.21 CNY per chapter of about
# 2,500 characters at DeepSeek billed rates. Shown to the author as an estimate before a check.
ESTIMATED_CNY_PER_1000_CHARS = 0.085
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


def estimate(db: Any, user_id: str, project_id: str, chapter_ids: list[str]) -> dict[str, Any]:
    characters = selection_characters(db, user_id, project_id, chapter_ids)
    return {"characters": characters, "estimated_cny": round(characters / 1000 * ESTIMATED_CNY_PER_1000_CHARS, 2)}


def create(db: Any, user_id: str, project_id: str, chapter_ids: list[str], key: str, provenance: dict[str, str]):
    """A queued chapter-check run; (response, status, created) like the other run creators."""
    chapter_ids = _validate_selection(chapter_ids)
    from .v2_database import new_id, utcnow  # late import: v2_database imports this module's siblings

    with db.connection() as c:
        def factory() -> dict[str, Any]:
            project = db._project(c, user_id, project_id, True)
            # Like a draft check: facts that a chapter revision put up for review must be settled first.
            workflow.require_review_complete(c, project_id)
            known = {row["id"] for row in c.execute("SELECT id FROM v2_chapters WHERE project_id=?", (project_id,)).fetchall()}
            if any(chapter_id not in known for chapter_id in chapter_ids):
                raise DomainError("chapter_selection_invalid", 422)
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
            "SELECT r.id,r.status,r.stage,r.error_code,r.created_at,r.completed_at,r.result_origin,r.source_span_ids_json,a.result_json FROM v2_runs r "
            "LEFT JOIN v2_analysis_results a ON a.run_id=r.id WHERE r.project_id=? AND r.run_type=? ORDER BY r.created_at DESC,r.rowid DESC LIMIT ?",
            (project_id, RUN_TYPE, max(1, min(limit, 20)))).fetchall()
    return [{"run_id": row["id"], "status": row["status"], "stage": row["stage"], "error_code": row["error_code"],
             "created_at": row["created_at"], "completed_at": row["completed_at"], "sample": row["result_origin"] == "demo_preset",
             "report": json.loads(row["result_json"]) if row["result_json"] else None} for row in rows]


def timeline(db: Any, user_id: str, project_id: str) -> dict[str, Any]:
    """Every chapter in order, the current draft last, each with where its check stands.

    checked: a finished check covered the chapter's current text (a chapter check, an incremental
    review, or the draft check of the exact revision that was completed into it) and no earlier
    chapter has been revised since. basis_changed: checked, but an earlier chapter was revised after
    that check. edited_unchecked: an earlier version was checked, then the chapter was revised.
    unchecked: no check ever covered it.
    """
    with db.connection() as c:
        db._project(c, user_id, project_id)
        chapters = [dict(row) for row in c.execute("SELECT id,chapter_number,title,source_revision FROM v2_chapters WHERE project_id=? ORDER BY chapter_number", (project_id,))]
        spans = c.execute("SELECT id,chapter_id,source_revision FROM v2_source_spans WHERE project_id=?", (project_id,)).fetchall()
        # A draft check keeps the draft revision it checked in source_revision (draft_revision stays empty).
        runs = c.execute("SELECT run_type,draft_id,COALESCE(draft_revision,source_revision) AS checked_revision,incremental_batch_id,source_span_ids_json,completed_at FROM v2_runs WHERE project_id=? AND status='completed' "
                         "AND run_type IN ('continuity','chapter_check') AND result_origin='provider'", (project_id,)).fetchall()
        completions = {row["target_source_revision"]: (row["draft_id"], row["draft_revision"]) for row in c.execute(
            "SELECT target_source_revision,draft_id,draft_revision FROM v2_source_change_sets WHERE project_id=? AND status='committed' AND input_method='draft_complete'", (project_id,))}
        revised_at = {row["chapter_id"]: row["at"] for row in c.execute(
            "SELECT chapter_id,MAX(created_at) at FROM v2_chapter_revision_history WHERE project_id=? AND change_set_id IS NOT NULL GROUP BY chapter_id", (project_id,))}
        draft = c.execute("SELECT id,chapter_number,title,revision,body FROM v2_drafts WHERE project_id=? AND status IN ('draft','saved') ORDER BY saved_at DESC LIMIT 1", (project_id,)).fetchone()
    span_checked: dict[str, str] = {}
    draft_checked: dict[tuple[str, int], str] = {}
    for run in runs:
        at = run["completed_at"] or ""
        for span_id in json.loads(run["source_span_ids_json"] or "[]"):
            span_checked[span_id] = max(at, span_checked.get(span_id, ""))
        if run["run_type"] == "continuity" and run["incremental_batch_id"] is None:
            key = (run["draft_id"], run["checked_revision"])
            draft_checked[key] = max(at, draft_checked.get(key, ""))
    by_chapter: dict[str, list[Any]] = {}
    for span in spans:
        by_chapter.setdefault(span["chapter_id"], []).append(span)
    rows = []
    for chapter in chapters:
        own = by_chapter.get(chapter["id"], [])
        current = [span["id"] for span in own if span["source_revision"] == chapter["source_revision"]]
        older = [span["id"] for span in own if span["source_revision"] < chapter["source_revision"]]
        checked_at = max([span_checked[span_id] for span_id in current if span_id in span_checked] or [""])
        if not checked_at and chapter["source_revision"] in completions and not older:
            checked_at = draft_checked.get(completions[chapter["source_revision"]], "")
        earlier_revision = max([revised_at.get(row["id"], "") for row in chapters if row["chapter_number"] < chapter["chapter_number"]] or [""])
        if checked_at:
            status = "basis_changed" if earlier_revision > checked_at else "checked"
        else:
            status = "edited_unchecked" if any(span_id in span_checked for span_id in older) else "unchecked"
        rows.append({"chapter_id": chapter["id"], "chapter_number": chapter["chapter_number"], "title": chapter["title"],
                     "draft": False, "status": status, "checked_at": checked_at or None})
    if draft:
        current_check = draft_checked.get((draft["id"], draft["revision"]))
        earlier_check = any(key[0] == draft["id"] for key in draft_checked)
        status = "checked" if current_check else "edited_unchecked" if earlier_check else "unchecked"
        rows.append({"chapter_id": None, "chapter_number": draft["chapter_number"], "title": draft["title"], "draft": True,
                     "status": status if (draft["body"] or "").strip() else "empty", "checked_at": current_check})
    return {"chapters": rows}
