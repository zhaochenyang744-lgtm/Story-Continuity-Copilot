"""Test-only: writes the record an old 「问一问」 question left behind.

v1.9.0 removed the way to ask a new question (POST /analyses no longer takes `story_qa`), but the
answers authors got before stay readable. A test that needs one writes it the way the old code did:
one `v2_runs` row, its bound input, its stored result and the run events.
"""
from __future__ import annotations

import json
from typing import Any

from app.database import digest
from app.v2_database import new_id, utcnow


def seed_story_qa(db, project_id: str, draft_id: str, draft_revision: int, *, question: str, scope: list[str] | None = None,
                  answer: str = "依据已确认事实，可以给出有界回答。", findings: list[dict[str, Any]] | None = None) -> str:
    scope = scope or ["confirmed"]
    findings = findings if findings is not None else [{"layer": "confirmed", "stance": "supports", "text": "该结论来自当前 Story Memory。", "evidence": []}]
    with db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        project = c.execute("SELECT * FROM v2_projects WHERE id=?", (project_id,)).fetchone()
        author_version, author_digest = db._current_author_context_binding(c, project)
        foreshadow_version, foreshadow_digest, _ = db._current_foreshadow_binding(c, project_id)
        run_id, stamp = new_id("run"), utcnow()
        retrieval = {"method_version": "writing-analysis-lexical-v2-draft-claims", "selected_ids": {}, "counts": {}, "truncated": {}}
        input_data = {"task": "story_qa", "question": question, "scope": scope, "retrieval": retrieval,
                      "bindings": {"project_id": project_id, "draft_id": draft_id, "draft_revision": draft_revision}}
        c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,draft_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,run_type,root_run_id,attempt_number,author_context_version,author_context_snapshot_digest,alias_version,alias_snapshot_digest,foreshadow_version,foreshadow_snapshot_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, project_id, draft_id, project["source_revision"], draft_revision, "queued", "queued", "legacy-test-provider", stamp, "legacy-test-model",
                   "story-qa-v3-no-prose-ids", "writing-analysis-v1", retrieval["method_version"], project["current_memory_version"], "provider", "story_qa", run_id, 1,
                   author_version, author_digest, None, None, foreshadow_version, foreshadow_digest))
        c.execute("INSERT INTO v2_analysis_inputs VALUES(?,?,?,?,?,?,?)",
                  (run_id, project_id, "story_qa", json.dumps(input_data, ensure_ascii=False, sort_keys=True), json.dumps(retrieval, ensure_ascii=False, sort_keys=True), digest(input_data), stamp))
        db._append_run_event(c, run_id, "queued", "queued", None, stamp)
        c.execute("UPDATE v2_runs SET status='completed',stage='completed',completed_at=?,started_at=?,duration_ms=1 WHERE id=?", (stamp, stamp, run_id))
        db._append_run_event(c, run_id, "completed", "completed", None, stamp)
        result = {"summary": answer, "items": [], "answer_status": "answered", "answer": answer, "evidence_status": "supported",
                  "findings": findings, "question": question, "scope": scope}
        c.execute("INSERT INTO v2_analysis_results VALUES(?,?,?,?,?)", (run_id, project_id, "story_qa", json.dumps(result, ensure_ascii=False, sort_keys=True), stamp))
    return run_id
