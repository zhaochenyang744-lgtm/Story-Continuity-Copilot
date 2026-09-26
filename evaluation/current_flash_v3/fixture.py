"""Evaluation-only G03 fixture correction; never contacts a Provider by itself."""
from __future__ import annotations

import pathlib

from evaluation.current_flash_v2 import run as v2
from evaluation.v2_fixture_loader import fixture_runtime_at

CORPUS = v2.G03_CORPUS
KEY = "flash_v2_target"  # Keep deterministic IDs for exact request comparison.
MEMORY = f"fixture-memory-{KEY}-1"
TARGET = f"fixture-span-{KEY}-1"
OTHER = f"fixture-span-{KEY}-2"
CHAPTER1 = f"fixture-chapter-{KEY}-1"
CHAPTER2 = f"fixture-chapter-{KEY}-2"
FACT = "星钥始终由乔霁保管。"


def check_database(db, project_id: str, case: dict) -> None:
    """Fail before Provider dispatch if a parent, span or Memory is inconsistent."""
    expected = {CHAPTER1: v2.g03_body(case), CHAPTER2: case["other_body"]}
    with db.connection() as connection:
        project = connection.execute("SELECT source_revision,current_memory_version FROM v2_projects WHERE id=?", (project_id,)).fetchone()
        if project is None or project["source_revision"] != 1 or project["current_memory_version"] != 1:
            raise RuntimeError("fixture_project_revision_mismatch")
        chapters = {r["id"]: dict(r) for r in connection.execute(
            "SELECT id,body,summary,source_revision FROM v2_chapters WHERE project_id=?", (project_id,))}
        spans = {r["id"]: dict(r) for r in connection.execute(
            "SELECT id,chapter_id,body,source_revision FROM v2_source_spans WHERE project_id=?", (project_id,))}
        if set(chapters) != set(expected) or set(spans) != {TARGET, OTHER}:
            raise RuntimeError("fixture_identity_mismatch")
        for chapter_id, span_id in ((CHAPTER1, TARGET), (CHAPTER2, OTHER)):
            ch, span = chapters[chapter_id], spans[span_id]
            if ch["source_revision"] != project["source_revision"] or span["source_revision"] != project["source_revision"]:
                raise RuntimeError("fixture_source_revision_mismatch")
            if span["chapter_id"] != chapter_id or ch["body"] != span["body"] or ch["body"] != expected[chapter_id]:
                raise RuntimeError("fixture_chapter_span_body_mismatch")
            if ch["summary"] != ch["body"][:180]:
                raise RuntimeError("fixture_chapter_summary_mismatch")
        memory = connection.execute("SELECT id,version,memory_type,subject,predicate,value,source_span_id,review_status FROM v2_memory_records WHERE project_id=?", (project_id,)).fetchall()
        if len(memory) != 1 or dict(memory[0]) != {
            "id": MEMORY, "version": 1, "memory_type": "dynamic_state", "subject": "星钥", "predicate": "holder",
            "value": FACT, "source_span_id": TARGET, "review_status": "author_confirmed",
        }:
            raise RuntimeError("fixture_memory_contract_mismatch")


def check_request(case: dict, request: dict) -> None:
    v2.assert_business_input(case, request)
    memory = request["layers"]["confirmed"]["memory_records"]
    if len(memory) != 1 or memory[0].get("memory_type") != "dynamic_state":
        raise RuntimeError("g03_memory_type_mismatch")


def create_case_runtime(case: dict, provider, root: pathlib.Path):
    runtime = fixture_runtime_at(root, KEY, provider, {KEY: CORPUS})
    app, project_id = runtime.app, runtime.identity.project_id
    with app.state.database.connection() as connection:
        app.state.database._insert_empty_author_context_zero(connection, project_id, v2.stamp())
        connection.execute("UPDATE v2_memory_records SET memory_type=?,subject=?,predicate=?,value=? WHERE id=? AND project_id=? AND version=1",
                           ("dynamic_state", "星钥", "holder", FACT, MEMORY, project_id))
        for chapter_id, span_id, body in ((CHAPTER1, TARGET, v2.g03_body(case)),
                                          (CHAPTER2, OTHER, case["other_body"])):
            connection.execute("UPDATE v2_chapters SET body=?,summary=? WHERE id=? AND project_id=? AND source_revision=1",
                               (body, body[:180], chapter_id, project_id))
            connection.execute("UPDATE v2_source_spans SET body=? WHERE id=? AND chapter_id=? AND project_id=? AND source_revision=1",
                               (body, span_id, chapter_id, project_id))
            connection.execute("UPDATE v2_outline_nodes SET summary=? WHERE project_id=? AND chapter_number=?",
                               (body[:180], project_id, 1 if chapter_id == CHAPTER1 else 2))
    check_database(app.state.database, project_id, case)
    return runtime
