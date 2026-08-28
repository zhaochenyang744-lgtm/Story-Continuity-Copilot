"""Evaluation-only corpus loader for temporary V2-schema databases."""
from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.database import digest
from app.main import COOKIE, create_app
from app.v2_database import V2Database


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation" / "fixtures"
CORPUS_PATHS = {
    "calibration_spire": FIXTURES / "eval-v2-calibration-spire.json",
    "cloud_post": FIXTURES / "eval-v2-cloud-post.json",
    "crystal_archive": FIXTURES / "eval-v2-crystal-archive.json",
}
V3_CORPUS_PATHS = {
    "brine_station": FIXTURES / "eval-v3-brine-station.json",
    "basalt_theatre": FIXTURES / "eval-v3-basalt-theatre.json",
    "stair_post": FIXTURES / "eval-v3-stair-post.json",
}
V4_CORPUS_PATHS = {
    "mist_jetty": FIXTURES / "eval-v4-mist-jetty.json",
    "eave_cabin": FIXTURES / "eval-v4-eave-cabin.json",
    "mica_office": FIXTURES / "eval-v4-mica-office.json",
}


@dataclass(frozen=True)
class FixtureIdentity:
    corpus_key: str
    user_id: str
    project_id: str
    draft_id: str
    session_token: str
    semantic_spans: dict[tuple[int, str], str]


@dataclass
class FixtureRuntime:
    root: pathlib.Path
    app: Any
    client: TestClient
    identity: FixtureIdentity


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_corpus(corpus_key: str, corpus_paths: dict[str, pathlib.Path] = CORPUS_PATHS) -> dict[str, Any]:
    path = corpus_paths.get(corpus_key)
    if path is None:
        raise ValueError("unknown_evaluation_fixture_corpus")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "scc-evaluation-only-corpus-v1" or payload.get("corpus_key") != corpus_key:
        raise ValueError("evaluation_fixture_schema_invalid")
    if payload.get("evaluation_only") is not True or payload.get("production_seed") is not False or payload.get("protected_asset_source") is not False:
        raise ValueError("evaluation_fixture_boundary_invalid")
    if not isinstance(payload.get("chapters"), list) or not isinstance(payload.get("memory"), list):
        raise ValueError("evaluation_fixture_content_invalid")
    return payload


def corpus_catalog(corpus_paths: dict[str, pathlib.Path] = CORPUS_PATHS) -> dict[str, set[tuple[int, str]]]:
    catalog: dict[str, set[tuple[int, str]]] = {}
    for corpus_key in corpus_paths:
        corpus = load_corpus(corpus_key, corpus_paths)
        locations = {(chapter.get("chapter_number"), chapter.get("source_label")) for chapter in corpus["chapters"]}
        if len(locations) != len(corpus["chapters"]) or any(not isinstance(number, int) or not isinstance(label, str) or not label for number, label in locations):
            raise ValueError("evaluation_fixture_semantic_locations_invalid")
        catalog[corpus_key] = locations
    return catalog


def corpus_manifest_payload(corpus_paths: dict[str, pathlib.Path] = CORPUS_PATHS) -> dict[str, Any]:
    files = [{"corpus_key": key, "path": f"evaluation/fixtures/{path.name}", "sha256": sha256_file(path)} for key, path in corpus_paths.items()]
    return {
        "schema_version": "scc-evaluation-only-corpus-manifest-v1",
        "evaluation_only": True,
        "production_seed": False,
        "protected_asset_source": False,
        "files": files,
        "canonical_sha256": canonical_sha256([{key: load_corpus(key, corpus_paths)} for key in corpus_paths]),
    }


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ids(corpus_key: str) -> dict[str, str]:
    safe = corpus_key.replace("_", "-")
    return {"user": f"fixture-user-{safe}", "project": f"fixture-project-{safe}", "draft": f"fixture-draft-{safe}"}


def _fixture_identity(corpus_key: str, corpus_paths: dict[str, pathlib.Path] = CORPUS_PATHS) -> FixtureIdentity:
    corpus = load_corpus(corpus_key, corpus_paths)
    ids = _ids(corpus_key)
    semantic_spans = {
        (chapter["chapter_number"], chapter["source_label"]): f"fixture-span-{corpus_key}-{chapter['chapter_number']}"
        for chapter in corpus["chapters"]
    }
    return FixtureIdentity(corpus_key, ids["user"], ids["project"], ids["draft"], f"fixture-session-{corpus_key}", semantic_spans)


def _verify_existing_fixture(connection: Any, corpus_key: str, identity: FixtureIdentity, corpus_paths: dict[str, pathlib.Path] = CORPUS_PATHS) -> bool:
    """Return true only for a complete, matching fixture; reject partial state."""
    corpus = load_corpus(corpus_key, corpus_paths)
    exists = {
        "user": connection.execute("SELECT id FROM v2_users WHERE id=?", (identity.user_id,)).fetchone(),
        "project": connection.execute("SELECT user_id,seed_key,data_origin FROM v2_projects WHERE id=?", (identity.project_id,)).fetchone(),
        "draft": connection.execute("SELECT project_id,revision,body,checksum FROM v2_drafts WHERE id=?", (identity.draft_id,)).fetchone(),
    }
    if not any(exists.values()):
        return False
    if not all(exists.values()):
        raise ValueError("evaluation_fixture_existing_state_mismatch")
    if (exists["project"]["user_id"], exists["project"]["seed_key"], exists["project"]["data_origin"]) != (identity.user_id, corpus_key, "evaluation_fixture"):
        raise ValueError("evaluation_fixture_existing_state_mismatch")
    if exists["draft"]["project_id"] != identity.project_id or not isinstance(exists["draft"]["revision"], int) or exists["draft"]["revision"] < 1:
        raise ValueError("evaluation_fixture_existing_state_mismatch")
    expected = len(corpus["chapters"])
    counts = {
        "chapters": connection.execute("SELECT COUNT(*) FROM v2_chapters WHERE project_id=?", (identity.project_id,)).fetchone()[0],
        "spans": connection.execute("SELECT COUNT(*) FROM v2_source_spans WHERE project_id=?", (identity.project_id,)).fetchone()[0],
        "memory": connection.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=1", (identity.project_id,)).fetchone()[0],
        "revisions": connection.execute("SELECT COUNT(*) FROM v2_draft_revisions WHERE draft_id=?", (identity.draft_id,)).fetchone()[0],
    }
    if counts != {"chapters": expected, "spans": expected, "memory": len(corpus["memory"]), "revisions": exists["draft"]["revision"]}:
        raise ValueError("evaluation_fixture_existing_state_mismatch")
    for (number, label), span_id in identity.semantic_spans.items():
        row = connection.execute("SELECT id FROM v2_source_spans WHERE id=? AND project_id=? AND label=?", (span_id, identity.project_id, label)).fetchone()
        if row is None:
            raise ValueError("evaluation_fixture_existing_state_mismatch")
    return True


def load_fixture(database: V2Database, corpus_key: str, fail_after: str | None = None, corpus_paths: dict[str, pathlib.Path] = CORPUS_PATHS) -> FixtureIdentity:
    """Insert one corpus with explicit columns; any injected failure rolls back."""
    corpus = load_corpus(corpus_key, corpus_paths)
    identity = _fixture_identity(corpus_key, corpus_paths)
    ids = _ids(corpus_key)
    token = identity.session_token
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    stamp = _stamp()
    semantic_spans: dict[tuple[int, str], str] = {}
    with database.connection() as connection:
        if _verify_existing_fixture(connection, corpus_key, identity, corpus_paths):
            return identity
        connection.execute(
            "INSERT INTO v2_users(id,account_name,display_name,password_hash,created_at) VALUES(?,?,?,?,?)",
            (ids["user"], f"fixture-{corpus_key}", "Evaluation Fixture", "not-used-for-fixture-session", stamp),
        )
        connection.execute(
            "INSERT INTO v2_sessions(id,user_id,token_hash,expires_at,revoked_at,created_at) VALUES(?,?,?,?,?,?)",
            (f"fixture-session-row-{corpus_key}", ids["user"], token_hash, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), None, stamp),
        )
        connection.execute(
            "INSERT INTO v2_projects(id,user_id,title,genre,summary,status,metadata_revision,data_origin,seed_key,created_at,updated_at,current_memory_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ids["project"], ids["user"], corpus["title"], "evaluation", "Isolated evaluation fixture", "active", 1, "evaluation_fixture", corpus_key, stamp, stamp, 1),
        )
        if fail_after == "project":
            raise RuntimeError("fixture_injected_failure")
        for chapter in corpus["chapters"]:
            number, label = chapter["chapter_number"], chapter["source_label"]
            chapter_id = f"fixture-chapter-{corpus_key}-{number}"
            span_id = f"fixture-span-{corpus_key}-{number}"
            semantic_spans[(number, label)] = span_id
            connection.execute(
                "INSERT INTO v2_chapters(id,project_id,chapter_number,title,summary,body) VALUES(?,?,?,?,?,?)",
                (chapter_id, ids["project"], number, chapter["title"], chapter["body"][:180], chapter["body"]),
            )
            connection.execute(
                "INSERT INTO v2_source_spans(id,project_id,chapter_id,label,body) VALUES(?,?,?,?,?)",
                (span_id, ids["project"], chapter_id, label, chapter["body"]),
            )
            connection.execute(
                "INSERT INTO v2_outline_nodes(id,project_id,chapter_number,title,summary,status) VALUES(?,?,?,?,?,?)",
                (f"fixture-outline-{corpus_key}-{number}", ids["project"], number, chapter["title"], chapter["body"][:180], "complete"),
            )
        if fail_after == "chapters":
            raise RuntimeError("fixture_injected_failure")
        connection.execute(
            "INSERT INTO v2_memory_versions(project_id,version,status,parent_version,created_at) VALUES(?,?,?,?,?)",
            (ids["project"], 1, "current", None, stamp),
        )
        for ordinal, record in enumerate(corpus["memory"], 1):
            source = record["source"]
            span_id = semantic_spans[(source["chapter_number"], source["source_label"])]
            connection.execute(
                "INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"fixture-memory-{corpus_key}-{ordinal}", ids["project"], 1, record["memory_type"], record["subject"], record["predicate"], record["value"], span_id, "author_confirmed", 1, None, None),
            )
        if fail_after == "memory":
            raise RuntimeError("fixture_injected_failure")
        connection.execute(
            "INSERT INTO v2_drafts(id,project_id,chapter_number,title,body,revision,status,saved_at,parent_revision,edit_context_json,checksum) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (ids["draft"], ids["project"], len(corpus["chapters"]) + 1, "Evaluation draft", "", 1, "draft", stamp, None, None, digest("")),
        )
        connection.execute(
            "INSERT INTO v2_draft_revisions(draft_id,revision,title,body,checksum,parent_revision,edit_context_json,saved_at) VALUES(?,?,?,?,?,?,?,?)",
            (ids["draft"], 1, "Evaluation draft", "", digest(""), None, None, stamp),
        )
        if fail_after == "draft":
            raise RuntimeError("fixture_injected_failure")
    return FixtureIdentity(corpus_key, ids["user"], ids["project"], ids["draft"], token, semantic_spans)


def fixture_runtime_at(root: pathlib.Path, corpus_key: str, provider: Any, corpus_paths: dict[str, pathlib.Path] = CORPUS_PATHS) -> FixtureRuntime:
    """Open a persistent, evaluation-owned runtime that can be resumed safely."""
    root = root.resolve()
    demo_database = (ROOT / "runtime" / "data" / "demo.sqlite3").resolve()
    if root == ROOT or root == (ROOT / "runtime").resolve() or root == demo_database.parent:
        raise ValueError("evaluation_fixture_runtime_root_forbidden")
    paths = AppPaths.from_project_root(root, protected_poc_root=root / "protected-placeholder")
    if paths.database_path == demo_database:
        raise ValueError("evaluation_fixture_demo_database_forbidden")
    app = create_app(paths=paths, provider=provider, executor=lambda fn, *args: fn(*args))
    identity = load_fixture(app.state.database, corpus_key, corpus_paths=corpus_paths)
    client = TestClient(app)
    client.cookies.set(COOKIE, identity.session_token)
    return FixtureRuntime(root, app, client, identity)


@contextmanager
def fixture_runtime(corpus_key: str, provider: Any, corpus_paths: dict[str, pathlib.Path] = CORPUS_PATHS) -> Iterator[FixtureRuntime]:
    """Create one temporary app/database and authenticated client for one corpus."""
    with tempfile.TemporaryDirectory(prefix="scc-eval-v2-") as temporary:
        root = pathlib.Path(temporary)
        runtime = fixture_runtime_at(root, corpus_key, provider, corpus_paths)
        try:
            yield runtime
        finally:
            runtime.client.close()
