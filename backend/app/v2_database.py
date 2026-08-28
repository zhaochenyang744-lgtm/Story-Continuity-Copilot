"""Stage 4 account-scoped, forward-only SQLite storage.

V1 tables remain untouched. V2 data lives in namespaced tables and the one-time
migration assigns any legacy project to the explicit ``v1-migration`` account.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .config import AppPaths
from .database import DomainError, digest
from .seed_data import CHAPTERS, DRAFT, MEMORY_RECORDS


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(kind: str) -> str:
    return f"{kind}-{uuid.uuid4()}"


def _account(value: str) -> str:
    return value.strip().casefold()


def _password(value: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    value_hash = hashlib.scrypt(value.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${value_hash.hex()}"


def password_matches(value: str, saved: str) -> bool:
    try:
        _, n, r, p, salt, value_hash = saved.split("$")
        calculated = hashlib.scrypt(value.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)).hex()
        return secrets.compare_digest(calculated, value_hash)
    except (TypeError, ValueError):
        return False


def _rewrite_memory_identity(value: str | None, memory_ids: dict[str, str]) -> str | None:
    """Rewrite only known V1 memory identifiers inside persisted JSON."""
    if not value:
        return value
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return value
    if isinstance(decoded, dict) and decoded.get("affected_memory_id") in memory_ids:
        decoded["affected_memory_id"] = memory_ids[decoded["affected_memory_id"]]
    if isinstance(decoded, dict) and decoded.get("id") in memory_ids:
        decoded["id"] = memory_ids[decoded["id"]]
    return json.dumps(decoded, ensure_ascii=False, sort_keys=True)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS v2_users(id TEXT PRIMARY KEY,account_name TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,password_hash TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),token_hash TEXT NOT NULL UNIQUE,expires_at TEXT NOT NULL,revoked_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_projects(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),title TEXT NOT NULL,genre TEXT NOT NULL DEFAULT '',summary TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,metadata_revision INTEGER NOT NULL,data_origin TEXT NOT NULL,seed_key TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,current_memory_version INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS v2_projects_by_owner ON v2_projects(user_id,status,updated_at);
CREATE TABLE IF NOT EXISTS v2_outline_nodes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_number INTEGER NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,status TEXT NOT NULL,UNIQUE(project_id,chapter_number));
CREATE TABLE IF NOT EXISTS v2_characters(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),name TEXT NOT NULL,role_type TEXT NOT NULL,identity TEXT NOT NULL,goal TEXT NOT NULL,current_state TEXT NOT NULL,knowledge_boundary TEXT NOT NULL,relationships_json TEXT NOT NULL,source_ids_json TEXT NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_world_entries(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),entry_type TEXT NOT NULL,name TEXT NOT NULL,summary TEXT NOT NULL,related_character_ids_json TEXT NOT NULL,source_ids_json TEXT NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_chapters(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_number INTEGER NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(project_id,chapter_number));
CREATE TABLE IF NOT EXISTS v2_source_spans(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_id TEXT NOT NULL REFERENCES v2_chapters(id),label TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_spans_by_project ON v2_source_spans(project_id,chapter_id);
CREATE TABLE IF NOT EXISTS v2_memory_versions(project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,status TEXT NOT NULL,parent_version INTEGER,created_at TEXT NOT NULL,PRIMARY KEY(project_id,version));
CREATE TABLE IF NOT EXISTS v2_memory_records(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,memory_type TEXT NOT NULL,subject TEXT NOT NULL,predicate TEXT NOT NULL,value TEXT NOT NULL,source_span_id TEXT,review_status TEXT NOT NULL,valid_from INTEGER,valid_to INTEGER,source_claim_id TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_drafts(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_number INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,saved_at TEXT NOT NULL,parent_revision INTEGER,edit_context_json TEXT,checksum TEXT NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_draft_revisions(draft_id TEXT NOT NULL REFERENCES v2_drafts(id),revision INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,checksum TEXT NOT NULL,parent_revision INTEGER,edit_context_json TEXT,saved_at TEXT NOT NULL,PRIMARY KEY(draft_id,revision));
CREATE TABLE IF NOT EXISTS v2_runs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),draft_id TEXT NOT NULL REFERENCES v2_drafts(id),source_revision INTEGER NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,provider_label TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,latency_ms INTEGER,cost_cny REAL,error_code TEXT,retryable INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,completed_at TEXT,model_label TEXT,prompt_version TEXT,schema_version TEXT,retrieval_method_version TEXT,source_memory_version INTEGER,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_runs_by_project ON v2_runs(project_id,draft_id,source_revision,status);
CREATE TABLE IF NOT EXISTS v2_run_stages(run_id TEXT NOT NULL REFERENCES v2_runs(id),stage TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(run_id,stage));
CREATE TABLE IF NOT EXISTS v2_run_claims(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES v2_runs(id),ordinal INTEGER NOT NULL,text TEXT NOT NULL,UNIQUE(run_id,ordinal));
CREATE TABLE IF NOT EXISTS v2_retrieval_traces(run_id TEXT NOT NULL REFERENCES v2_runs(id),claim_id TEXT NOT NULL,terms TEXT NOT NULL,returned_span_ids_json TEXT NOT NULL,method_version TEXT NOT NULL,PRIMARY KEY(run_id,claim_id));
CREATE TABLE IF NOT EXISTS v2_issues(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),claim_span_id TEXT NOT NULL,status TEXT NOT NULL,classification TEXT NOT NULL DEFAULT 'conflict',category TEXT NOT NULL,severity TEXT NOT NULL,evidence_status TEXT NOT NULL,explanation TEXT NOT NULL,proposed_change_json TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_evidence(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),chapter_id TEXT NOT NULL,span_id TEXT NOT NULL,excerpt TEXT NOT NULL,relation TEXT NOT NULL,sufficiency TEXT NOT NULL,related_memory_ids_json TEXT NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),decision TEXT NOT NULL,note TEXT,source_revision INTEGER NOT NULL,resulting_revision INTEGER,lineage_status TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(issue_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_change_sets(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),source_run_revision INTEGER NOT NULL,resolved_revision INTEGER NOT NULL,lineage_status TEXT NOT NULL,base_version INTEGER NOT NULL,target_version INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,committed_at TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_change_set_items(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),change_set_id TEXT NOT NULL REFERENCES v2_change_sets(id),operation TEXT NOT NULL,before_json TEXT,after_json TEXT NOT NULL,source_ids_json TEXT NOT NULL,decision_ids_json TEXT NOT NULL,review_status TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_commit_audits(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),change_set_id TEXT NOT NULL REFERENCES v2_change_sets(id),status TEXT NOT NULL,accepted_json TEXT NOT NULL,rejected_json TEXT NOT NULL,note TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_reset_audits(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),user_id TEXT NOT NULL REFERENCES v2_users(id),reason TEXT NOT NULL,completed_at TEXT NOT NULL,response_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_idempotency(scope TEXT NOT NULL,operation TEXT NOT NULL,idempotency_key TEXT NOT NULL,fingerprint TEXT NOT NULL,response_json TEXT NOT NULL,status_code INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(scope,operation,idempotency_key));
CREATE TABLE IF NOT EXISTS v2_import_drafts(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),filename TEXT NOT NULL,byte_size INTEGER NOT NULL,sha256 TEXT NOT NULL,format TEXT NOT NULL,chapters_json TEXT NOT NULL,source_text TEXT,warnings_json TEXT NOT NULL,expires_at TEXT NOT NULL,committed_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_login_attempts(account_name TEXT NOT NULL,attempted_at TEXT NOT NULL);
"""


class V2Database:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.paths.validate_database_target()

    def _connect(self) -> sqlite3.Connection:
        self.paths.prepare_runtime()
        connection = sqlite3.connect(self.paths.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as c:
            c.executescript(SCHEMA)
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(5,?)", (utcnow(),))
            self._migrate_run_provenance(c)
            self._migrate_legacy_project(c)

    def _migrate_run_provenance(self, c: sqlite3.Connection) -> None:
        """Add safe, version-only Run provenance without rewriting old results."""
        columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_runs)").fetchall()}
        additions = {
            "model_label": "TEXT",
            "prompt_version": "TEXT",
            "schema_version": "TEXT",
            "retrieval_method_version": "TEXT",
            "source_memory_version": "INTEGER",
        }
        for name, definition in additions.items():
            if name not in columns:
                c.execute(f"ALTER TABLE v2_runs ADD COLUMN {name} {definition}")
        issue_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_issues)").fetchall()}
        if "classification" not in issue_columns:
            c.execute("ALTER TABLE v2_issues ADD COLUMN classification TEXT NOT NULL DEFAULT 'conflict'")
        c.execute(
            "UPDATE v2_runs SET model_label=COALESCE(model_label,'legacy_unspecified'), "
            "prompt_version=COALESCE(prompt_version,'legacy_unspecified'), "
            "schema_version=COALESCE(schema_version,'legacy_unspecified'), "
            "retrieval_method_version=COALESCE(retrieval_method_version,'legacy_unspecified'), "
            "source_memory_version=COALESCE(source_memory_version,(SELECT current_memory_version FROM v2_projects WHERE id=v2_runs.project_id))"
        )
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(6,?)", (utcnow(),))

    def _migrate_legacy_project(self, c: sqlite3.Connection) -> None:
        """Migrate one legacy project without mutating its V1 tables.

        The migration owns every generated V2 identifier.  Keeping the maps in
        this transaction is important: a V2 run is only useful if its claims,
        evidence, decisions, and change-set lineage resolve inside the same
        project.
        """
        if c.execute("SELECT 1 FROM v2_users WHERE account_name='v1-migration'").fetchone():
            return
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'").fetchone():
            return
        legacy = c.execute("SELECT * FROM projects LIMIT 1").fetchone()
        if not legacy:
            return
        user_id = new_id("usr")
        c.execute("INSERT INTO v2_users VALUES(?,?,?,?,?)", (user_id, "v1-migration", "V1 local migration", _password(secrets.token_urlsafe(24)), utcnow()))
        project_id = new_id("prj")
        stamp = utcnow()
        c.execute("INSERT INTO v2_projects VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (project_id,user_id,legacy["title"],"",legacy["summary"],"active",1,"v1_migrated",None,stamp,stamp,int(legacy["current_memory_version"])))
        chapters = c.execute("SELECT * FROM chapters WHERE project_id=? ORDER BY chapter_number", (legacy["id"],)).fetchall()
        chapter_ids: dict[str, str] = {}
        span_ids: dict[str, str] = {}
        for chapter in chapters:
            chapter_id = new_id("ch")
            chapter_ids[chapter["id"]] = chapter_id
            c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?)", (chapter_id,project_id,chapter["chapter_number"],chapter["title"],chapter["summary"],""))
            c.execute("INSERT INTO v2_outline_nodes VALUES(?,?,?,?,?,?)", (new_id("outline"),project_id,chapter["chapter_number"],chapter["title"],chapter["summary"],"complete"))
            for span in c.execute("SELECT * FROM source_spans WHERE chapter_id=?", (chapter["id"],)).fetchall():
                span_id=new_id("span"); span_ids[span["id"]]=span_id
                c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?)", (span_id,project_id,chapter_id,span["label"],span["body"]))
        for version in c.execute("SELECT * FROM memory_versions WHERE project_id=?",(legacy["id"],)).fetchall():
            c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)",(project_id,version["version"],version["status"],version["parent_version"],version["created_at"]))
        memory_ids: dict[str, str] = {}
        for record in c.execute("SELECT * FROM memory_records WHERE project_id=?",(legacy["id"],)).fetchall():
            source=span_ids.get(record["source_span_id"])
            if source:
                memory_id = new_id("mem"); memory_ids[record["id"]] = memory_id
                c.execute("INSERT INTO v2_memory_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(memory_id,project_id,record["version"],record["memory_type"],record["subject"],record["predicate"],record["value"],source,record["review_status"],record["valid_from"],record["valid_to"],record["source_claim_id"]))
        draft_ids: dict[str, str] = {}
        for draft in c.execute("SELECT * FROM drafts WHERE project_id=?",(legacy["id"],)).fetchall():
            draft_id=new_id("draft"); checksum=draft["body_checksum"] or digest(draft["body"])
            draft_ids[draft["id"]] = draft_id
            c.execute("INSERT INTO v2_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?)",(draft_id,project_id,draft["chapter_number"],draft["title"],draft["body"],draft["revision"],draft["status"],draft["saved_at"],draft["parent_revision"],draft["edit_context"],checksum))
            revisions=c.execute("SELECT * FROM draft_revisions WHERE draft_id=?",(draft["id"],)).fetchall()
            for revision in revisions:
                c.execute("INSERT INTO v2_draft_revisions VALUES(?,?,?,?,?,?,?,?)",(draft_id,revision["revision"],revision["title"],revision["body"],revision["body_checksum"],revision["parent_revision"],revision["edit_context"],revision["saved_at"]))
        # Continuity history is migrated after drafts so every V2 run keeps a
        # project-scoped draft reference.  The legacy tables are optional for
        # early V1 installations; schema checks make that safe and idempotent.
        tables = {row["name"] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "runs" not in tables:
            return
        run_ids: dict[str, str] = {}
        for run in c.execute("SELECT * FROM runs WHERE project_id=?", (legacy["id"],)).fetchall():
            draft_id = draft_ids.get(run["draft_id"])
            if not draft_id:
                continue
            run_id = new_id("run"); run_ids[run["id"]] = run_id
            c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,input_tokens,output_tokens,latency_ms,cost_cny,error_code,retryable,created_at,completed_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id,project_id,draft_id,run["source_revision"],run["status"],run["stage"],run["provider_label"],run["input_tokens"],run["output_tokens"],run["latency_ms"],run["cost_cny"],run["error_code"],run["retryable"],run["created_at"],run["completed_at"],"legacy_unspecified","legacy_unspecified","legacy_unspecified","legacy_unspecified",None))
        if "run_stages" in tables:
            for stage in c.execute("SELECT * FROM run_stages").fetchall():
                if stage["run_id"] in run_ids:
                    c.execute("INSERT INTO v2_run_stages VALUES(?,?,?)", (run_ids[stage["run_id"]],stage["stage"],stage["created_at"]))
        claim_ids: dict[str, str] = {}
        if "run_claims" in tables:
            for claim in c.execute("SELECT * FROM run_claims").fetchall():
                if claim["run_id"] in run_ids:
                    claim_id = new_id("claim"); claim_ids[claim["id"]] = claim_id
                    c.execute("INSERT INTO v2_run_claims VALUES(?,?,?,?)", (claim_id,run_ids[claim["run_id"]],claim["ordinal"],claim["text"]))
        if "retrieval_traces" in tables:
            for trace in c.execute("SELECT * FROM retrieval_traces").fetchall():
                if trace["run_id"] in run_ids and trace["claim_id"] in claim_ids:
                    spans = [span_ids.get(item, item) for item in json.loads(trace["returned_span_ids"])]
                    if all(item in span_ids.values() for item in spans):
                        c.execute("INSERT INTO v2_retrieval_traces VALUES(?,?,?,?,?)", (run_ids[trace["run_id"]],claim_ids[trace["claim_id"]],trace["query_terms"],json.dumps(spans),trace["method_version"]))
        issue_ids: dict[str, str] = {}
        if "issues" in tables:
            for issue in c.execute("SELECT * FROM issues").fetchall():
                if issue["run_id"] not in run_ids or issue["claim_span_id"] not in claim_ids:
                    continue
                issue_id = new_id("issue"); issue_ids[issue["id"]] = issue_id
                columns = {x["name"] for x in c.execute("PRAGMA table_info(issues)").fetchall()}
                proposed = _rewrite_memory_identity(issue["proposed_change_json"], memory_ids) if "proposed_change_json" in columns else None
                c.execute("INSERT INTO v2_issues(id,project_id,run_id,claim_span_id,status,classification,category,severity,evidence_status,explanation,proposed_change_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (issue_id,project_id,run_ids[issue["run_id"]],claim_ids[issue["claim_span_id"]],issue["status"],"conflict",issue["category"],issue["severity"],issue["evidence_status"],issue["explanation"],proposed))
        if "evidence" in tables:
            for evidence in c.execute("SELECT * FROM evidence").fetchall():
                issue_id = issue_ids.get(evidence["issue_id"]); chapter_id = chapter_ids.get(evidence["chapter_id"]); span_id = span_ids.get(evidence["span_id"])
                related = [memory_ids.get(item, item) for item in json.loads(evidence["related_memory_ids"])]
                if issue_id and chapter_id and span_id and all(item in memory_ids.values() for item in related):
                    c.execute("INSERT INTO v2_evidence VALUES(?,?,?,?,?,?,?,?,?)", (new_id("evidence"),project_id,issue_id,chapter_id,span_id,evidence["excerpt"],evidence["relation"],evidence["sufficiency"],json.dumps(related)))
        decision_ids: dict[str, str] = {}
        if "decisions" in tables:
            for decision in c.execute("SELECT * FROM decisions").fetchall():
                issue_id, run_id = issue_ids.get(decision["issue_id"]), run_ids.get(decision["run_id"])
                if issue_id and run_id:
                    decision_id = new_id("decision"); decision_ids[decision["id"]] = decision_id
                    c.execute("INSERT INTO v2_decisions VALUES(?,?,?,?,?,?,?,?,?,?)", (decision_id,project_id,issue_id,run_id,decision["decision"],decision["note"],decision["source_revision"],decision["resulting_revision"],decision["lineage_status"],decision["created_at"]))
        change_set_ids: dict[str, str] = {}
        if "change_sets" in tables:
            for changeset in c.execute("SELECT * FROM change_sets WHERE project_id=?", (legacy["id"],)).fetchall():
                run_id = run_ids.get(changeset["run_id"])
                if not run_id:
                    continue
                change_set_id = new_id("changeset"); change_set_ids[changeset["id"]] = change_set_id
                c.execute("INSERT INTO v2_change_sets VALUES(?,?,?,?,?,?,?,?,?,?,?)", (change_set_id,project_id,run_id,changeset["source_run_revision"],changeset["resolved_revision"],changeset["lineage_status"],changeset["base_version"],changeset["target_version"],changeset["status"],changeset["created_at"],changeset["committed_at"]))
        if "change_set_items" in tables:
            item_columns = {x["name"] for x in c.execute("PRAGMA table_info(change_set_items)").fetchall()}
            for item in c.execute("SELECT * FROM change_set_items").fetchall():
                change_set_id = change_set_ids.get(item["change_set_id"])
                if not change_set_id:
                    continue
                sources = [issue_ids.get(value, claim_ids.get(value, value)) for value in json.loads(item["source_ids"])]
                decisions = [decision_ids.get(value, value) for value in json.loads(item["decision_ids"])]
                if all(value in set(issue_ids.values()) | set(claim_ids.values()) for value in sources) and all(value in decision_ids.values() for value in decisions):
                    review = item["review_status"] if "review_status" in item_columns else None
                    c.execute("INSERT INTO v2_change_set_items VALUES(?,?,?,?,?,?,?,?,?)", (new_id("changeitem"),project_id,change_set_id,item["operation"],_rewrite_memory_identity(item["before_json"],memory_ids),_rewrite_memory_identity(item["after_json"],memory_ids),json.dumps(sources),json.dumps(decisions),review))
        if "commit_audits" in tables:
            for audit in c.execute("SELECT * FROM commit_audits").fetchall():
                change_set_id = change_set_ids.get(audit["change_set_id"])
                if change_set_id:
                    c.execute("INSERT INTO v2_commit_audits VALUES(?,?,?,?,?,?,?,?)", (new_id("commit"),project_id,change_set_id,audit["status"],audit["accepted_item_ids"],audit["rejected_item_ids"],audit["note"],audit["created_at"]))

    # --- generic ownership, idempotency, and seeds ---
    def _project(self, c: sqlite3.Connection, user_id: str, project_id: str, writable: bool = False) -> sqlite3.Row:
        project = c.execute("SELECT * FROM v2_projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
        if not project:
            raise DomainError("resource_not_found", 404)
        if writable and project["status"] == "archived":
            raise DomainError("project_archived", 409)
        return project

    def _idem(self, c: sqlite3.Connection, scope: str, operation: str, key: str, payload: Any, factory: Callable[[], dict[str, Any]], status_code: int = 200, with_created: bool = False):
        fingerprint = digest(payload)
        stored = c.execute("SELECT fingerprint,response_json,status_code FROM v2_idempotency WHERE scope=? AND operation=? AND idempotency_key=?", (scope, operation, key)).fetchone()
        if stored:
            if stored["fingerprint"] != fingerprint:
                raise DomainError("idempotency_conflict", 409)
            replay = (json.loads(stored["response_json"]), int(stored["status_code"]))
            return (*replay, False) if with_created else replay
        result = factory()
        # A transient cookie token may be returned only on the initial account
        # creation response. It is never persisted in the idempotency ledger.
        persisted = json.loads(json.dumps({name:value for name,value in result.items() if name != "_token"}, ensure_ascii=False))
        if isinstance(persisted.get("session"), dict):
            persisted["session"] = {name:value for name,value in persisted["session"].items() if name != "_token"}
        c.execute("INSERT INTO v2_idempotency VALUES(?,?,?,?,?,?,?)", (scope,operation,key,fingerprint,json.dumps(persisted,ensure_ascii=False),status_code,utcnow()))
        created = (result, status_code)
        return (*created, True) if with_created else created

    def _empty_project_state(self, c: sqlite3.Connection, project_id: str, chapter_number: int = 1) -> str:
        stamp = utcnow()
        c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)", (project_id,1,"current",None,stamp))
        draft_id = new_id("draft")
        checksum = digest("")
        title = f"第{chapter_number}章"
        c.execute("INSERT INTO v2_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (draft_id,project_id,chapter_number,title,"",1,"draft",stamp,None,None,checksum))
        c.execute("INSERT INTO v2_draft_revisions VALUES(?,?,?,?,?,?,?,?)", (draft_id,1,title,"",checksum,None,None,stamp))
        return draft_id

    def _create_project(self, c: sqlite3.Connection, user_id: str, title: str, genre: str, summary: str, origin: str, seed_key: str | None = None, imported: list[dict[str, Any]] | None = None) -> str:
        project_id = new_id("prj")
        stamp = utcnow()
        version = 4 if seed_key == "grey_harbor" else 1
        c.execute("INSERT INTO v2_projects VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (project_id,user_id,title,genre,summary,"active",1,origin,seed_key,stamp,stamp,version))
        if seed_key == "grey_harbor":
            self._seed_grey_harbor(c, project_id)
        elif seed_key in {"paper_moon", "zero_garden"}:
            self._seed_other(c, project_id, seed_key)
        elif imported is not None:
            self._seed_import(c, project_id, imported)
        else:
            self._empty_project_state(c, project_id)
        return project_id

    def _seed_grey_harbor(self, c: sqlite3.Connection, project_id: str) -> None:
        stamp = utcnow()
        old_span_to_new: dict[str, str] = {}
        for chapter_old, number, title, summary, source_items in CHAPTERS:
            chapter_id = new_id("ch")
            c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?)", (chapter_id,project_id,number,title,summary,""))
            c.execute("INSERT INTO v2_outline_nodes VALUES(?,?,?,?,?,?)", (new_id("outline"),project_id,number,title,summary,"complete"))
            for old_span_id, label, body in source_items:
                span_id = new_id("span")
                old_span_to_new[old_span_id] = span_id
                c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?)", (span_id,project_id,chapter_id,label,body))
        draft_id = new_id("draft")
        checksum = digest(DRAFT["body"])
        c.execute("INSERT INTO v2_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (draft_id,project_id,11,DRAFT["title"],DRAFT["body"],1,"saved",stamp,None,None,checksum))
        c.execute("INSERT INTO v2_draft_revisions VALUES(?,?,?,?,?,?,?,?)", (draft_id,1,DRAFT["title"],DRAFT["body"],checksum,None,None,stamp))
        c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)", (project_id,4,"current",None,stamp))
        for _, memory_type, subject, predicate, value, old_span_id in MEMORY_RECORDS:
            c.execute("INSERT INTO v2_memory_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (new_id("mem"),project_id,4,memory_type,subject,predicate,value,old_span_to_new[old_span_id],"author_confirmed",1,None,None))
        c.execute("INSERT INTO v2_characters VALUES(?,?,?,?,?,?,?,?,?,?)", (new_id("char"),project_id,"温岚","ally","灰港档案员","核对潮表","保管罗盘","不知道廊桥钥匙的含义","[]","[]"))
        c.execute("INSERT INTO v2_world_entries VALUES(?,?,?,?,?,?,?)", (new_id("world"),project_id,"location","灰港","雾钟与北潮闸所在的港口","[]","[]"))

    def _seed_other(self, c: sqlite3.Connection, project_id: str, seed_key: str) -> None:
        seed = {
            "paper_moon": {
                "chapters": [
                    ("封蜡的月历", "守夜约定", "陆栖与档案馆守夜人姚笺约定只交换编号，不交换姓名。"),
                    ("失页编号", "月蚀规则", "纸月档案只能在月蚀夜用银墨揭封，普通火光会令字迹褪去。"),
                    ("旧印刷厂", "钥匙保管", "姚笺把封蜡钥匙交给陆栖保管，钥匙始终留在陆栖的书盒里。"),
                    ("空白签名", "未知署名", "失页的署名人尚未找到，陆栖只确认了编号缺失的范围。"),
                    ("河灯目录", "目录时间", "河灯目录在子夜前完成抄录，陆栖没有离开旧印刷厂。"),
                    ("纸月归档", "知识边界", "姚笺仍不知道第七页背面的暗记由谁留下。"),
                ],
                "character": ("陆栖", "独立作品的调查者", "追查章节线索", "正在记录发现", "只知道已出现的章节事实"),
                "world": ("旧印刷厂", "纸月档案的可追溯地点"),
                "memory": [("static_canon", "纸月档案", "unseal_rule", "只在月蚀夜用银墨揭封", 1), ("dynamic_state", "封蜡钥匙", "holder", "陆栖", 2), ("static_canon", "陆栖与姚笺", "agreement", "只交换编号，不交换姓名", 0)],
            },
            "zero_garden": {
                "chapters": [
                    ("玻璃温室", "守夜规则", "玻璃温室的萤苔只在零点到零点十分钟发蓝光，日光下休眠。"),
                    ("倒走的时钟", "访客记录", "程末在零点前锁上温室侧门，访客不能自行进入培育区。"),
                    ("无名花粉", "样本状态", "夜班结束后，程末把无名花粉样本封进低温盒，盒子留在北侧冷柜。"),
                    ("守夜手册", "配方未知", "花粉配方尚未公开，守夜手册只记录了观察时间和蓝光反应。"),
                ],
                "character": ("程末", "独立作品的夜班园丁", "记录零点开放的花", "正在守夜", "只知道已验证的温室记录"),
                "world": ("玻璃温室", "零点花园的可追溯地点"),
                "memory": [("static_canon", "萤苔", "blue_light_window", "仅在零点到零点十分钟发蓝光", 0), ("dynamic_state", "无名花粉样本", "location", "北侧冷柜的低温盒", 2), ("static_canon", "培育区", "entry_rule", "访客不能自行进入", 1)],
            },
        }[seed_key]
        chapters = seed["chapters"]
        spans: list[str] = []
        for number, (title, label, body) in enumerate(chapters, 1):
            chapter_id, span_id = new_id("ch"), new_id("span")
            c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?)", (chapter_id,project_id,number,title,body,body))
            c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?)", (span_id,project_id,chapter_id,label,body))
            c.execute("INSERT INTO v2_outline_nodes VALUES(?,?,?,?,?,?)", (new_id("outline"),project_id,number,title,body,"complete"))
            spans.append(span_id)
        c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)", (project_id,1,"current",None,utcnow()))
        for memory_type, subject, predicate, value, source_index in seed["memory"]:
            c.execute("INSERT INTO v2_memory_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (new_id("mem"),project_id,1,memory_type,subject,predicate,value,spans[source_index],"author_confirmed",1,None,None))
        character_name, identity, goal, current_state, knowledge_boundary = seed["character"]
        world_name, world_summary = seed["world"]
        character_id = new_id("char")
        c.execute("INSERT INTO v2_characters VALUES(?,?,?,?,?,?,?,?,?,?)",(character_id,project_id,character_name,"protagonist",identity,goal,current_state,knowledge_boundary,"[]",json.dumps([spans[0]])))
        c.execute("INSERT INTO v2_world_entries VALUES(?,?,?,?,?,?,?)",(new_id("world"),project_id,"location",world_name,world_summary,json.dumps([character_id]),json.dumps([spans[0]])))
        self._draft(c, project_id, len(chapters) + 1)

    def _draft(self, c: sqlite3.Connection, project_id: str, chapter_number: int) -> str:
        stamp, draft_id, checksum = utcnow(), new_id("draft"), digest("")
        title = f"第{chapter_number}章"
        c.execute("INSERT INTO v2_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (draft_id,project_id,chapter_number,title,"",1,"draft",stamp,None,None,checksum))
        c.execute("INSERT INTO v2_draft_revisions VALUES(?,?,?,?,?,?,?,?)", (draft_id,1,title,"",checksum,None,None,stamp))
        return draft_id

    def _seed_import(self, c: sqlite3.Connection, project_id: str, chapters: list[dict[str, Any]]) -> None:
        for number, chapter in enumerate(chapters, 1):
            chapter_id, span_id, body = new_id("ch"), new_id("span"), chapter["body"]
            c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?)", (chapter_id,project_id,number,chapter["title"],body[:180],body))
            c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?)", (span_id,project_id,chapter_id,"导入章节",body))
            c.execute("INSERT INTO v2_outline_nodes VALUES(?,?,?,?,?,?)", (new_id("outline"),project_id,number,chapter["title"],body[:180],"complete"))
        c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)", (project_id,1,"current",None,utcnow()))
        self._draft(c, project_id, len(chapters) + 1)

    # --- account/session API implementation ---
    def register(self, payload: dict[str, Any], key: str):
        account_name = _account(payload["account_name"])
        with self.connection() as c:
            def create() -> dict[str, Any]:
                display_name, password = payload.get("display_name", "").strip(), payload.get("password", "")
                if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", account_name) or not 1 <= len(display_name) <= 60:
                    raise DomainError("invalid_request", 400)
                if len(password) < 10 or len(set(password)) < 2:
                    raise DomainError("password_policy_failed", 422)
                if c.execute("SELECT 1 FROM v2_users WHERE account_name=?", (account_name,)).fetchone():
                    raise DomainError("account_name_unavailable", 409)
                user_id = new_id("usr")
                c.execute("INSERT INTO v2_users VALUES(?,?,?,?,?)", (user_id,account_name,display_name,_password(password),utcnow()))
                seeded = []
                seed_times = {
                    "grey_harbor": "2026-08-26T09:43:00+00:00",
                    "paper_moon": "2026-08-25T16:20:00+00:00",
                    "zero_garden": "2026-08-24T11:05:00+00:00",
                }
                for seed_key, title, genre, summary in (("grey_harbor","灰港回声","悬疑","潮图修复师追查被改写的航线记录。"),("paper_moon","纸月档案","奇幻","档案修复员追查消失的纸月。"),("zero_garden","零点花园","科幻","夜班园丁记录零点开放的花。")):
                    project_id = self._create_project(c,user_id,title,genre,summary,"demo_seed",seed_key)
                    seed_time = seed_times[seed_key]
                    c.execute("UPDATE v2_projects SET created_at=?,updated_at=? WHERE id=?", (seed_time, seed_time, project_id))
                    seeded.append({"id":project_id,"seed_key":seed_key,"title":title})
                token, expires_at = self._new_session(c, user_id)
                return {"user":{"id":user_id,"account_name":account_name,"display_name":display_name},"session":{"expires_at":expires_at,"_token":token},"seeded_projects":seeded}
            data, status = self._idem(c, f"register:{account_name}", "register", key, payload, create, 201)
            if "_token" not in data.get("session", {}):
                token, expires_at = self._new_session(c, data["user"]["id"])
                data["session"] = {"expires_at":expires_at,"_token":token}
            return data, status

    def _new_session(self, c: sqlite3.Connection, user_id: str) -> tuple[str, str]:
        token = secrets.token_urlsafe(48)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        c.execute("INSERT INTO v2_sessions VALUES(?,?,?,?,?,?)", (new_id("session"),user_id,hashlib.sha256(token.encode()).hexdigest(),expires_at,None,utcnow()))
        return token, expires_at

    def login(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_name = _account(str(payload.get("account_name", "")))
        with self.connection() as c:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            if c.execute("SELECT COUNT(*) FROM v2_login_attempts WHERE account_name=? AND attempted_at>?", (account_name,cutoff)).fetchone()[0] >= 8:
                raise DomainError("authentication_rate_limited", 429, True)
            c.execute("INSERT INTO v2_login_attempts VALUES(?,?)", (account_name,utcnow()))
            user = c.execute("SELECT * FROM v2_users WHERE account_name=?", (account_name,)).fetchone()
            if not user or not password_matches(str(payload.get("password", "")), user["password_hash"]):
                # Failed attempts are intentionally durable while the returned
                # error remains identical for missing and wrong credentials.
                c.commit()
                raise DomainError("invalid_credentials", 401)
            c.execute("DELETE FROM v2_login_attempts WHERE account_name=?",(account_name,))
            c.execute("UPDATE v2_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (utcnow(),user["id"]))
            token, expires_at = self._new_session(c, user["id"])
            return {"user":{"id":user["id"],"account_name":user["account_name"],"display_name":user["display_name"]},"session":{"expires_at":expires_at,"_token":token}}

    def session_user(self, raw_token: str | None) -> dict[str, Any]:
        if not raw_token:
            raise DomainError("authentication_required", 401)
        with self.connection() as c:
            row = c.execute("SELECT u.id,u.account_name,u.display_name,s.expires_at FROM v2_sessions s JOIN v2_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?", (hashlib.sha256(raw_token.encode()).hexdigest(),utcnow())).fetchone()
            if not row:
                raise DomainError("authentication_required", 401)
            return dict(row)

    def logout(self, raw_token: str | None) -> None:
        if raw_token:
            with self.connection() as c:
                c.execute("UPDATE v2_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (utcnow(),hashlib.sha256(raw_token.encode()).hexdigest()))

    # --- project read/lifecycle implementation ---
    def home(self, user_id: str) -> dict[str, Any]:
        with self.connection() as c:
            projects = c.execute("SELECT * FROM v2_projects WHERE user_id=? AND status!='archived' ORDER BY updated_at DESC", (user_id,)).fetchall()
            recent, pending, continuation = [], [], None
            for project in projects:
                draft = c.execute("SELECT * FROM v2_drafts WHERE project_id=? ORDER BY saved_at DESC LIMIT 1", (project["id"],)).fetchone()
                issue_count = c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open'", (project["id"],)).fetchone()[0]
                recent.append({"project_id":project["id"],"title":project["title"],"status":project["status"],"updated_at":project["updated_at"]})
                levels={level:c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open' AND severity=?",(project["id"],level)).fetchone()[0] for level in ("high","medium","low")}
                pending.append({"project_id":project["id"],"title":project["title"],"open_count":issue_count,**levels})
                if continuation is None and draft:
                    continuation = {"project_id":project["id"],"project_title":project["title"],"draft_id":draft["id"],"draft_title":draft["title"],"draft_revision":draft["revision"],"next_action":"continue_draft","updated_at":project["updated_at"]}
            failed=c.execute("SELECT r.id,r.project_id,r.status,r.error_code,r.created_at FROM v2_runs r JOIN v2_projects p ON p.id=r.project_id WHERE p.user_id=? AND r.status IN ('failed','timed_out') ORDER BY r.created_at DESC LIMIT 1",(user_id,)).fetchone()
            latest={"run_id":failed["id"],"project_id":failed["project_id"],"status":failed["status"],"error_code":failed["error_code"],"created_at":failed["created_at"]} if failed else None
            return {"continue_work":continuation,"recent_projects":recent,"pending_continuity":pending,"latest_failed_run":latest}

    def list_projects(self, user_id: str, q: str | None, status: str | None, has_open_issues: bool | None, sort: str | None) -> dict[str, Any]:
        if status not in {None,"active","paused","completed","archived"} or sort not in {None,"updated_desc","title_asc"}:
            raise DomainError("invalid_filter", 400)
        with self.connection() as c:
            sql, values = "SELECT * FROM v2_projects WHERE user_id=?", [user_id]
            if status:
                sql += " AND status=?"; values.append(status)
            else:
                sql += " AND status!='archived'"
            if q:
                sql += " AND (title LIKE ? OR summary LIKE ?)"; values.extend([f"%{q}%",f"%{q}%"])
            sql += " ORDER BY " + ("title COLLATE NOCASE" if sort == "title_asc" else "updated_at DESC")
            result = []
            for project in c.execute(sql, values).fetchall():
                draft = c.execute("SELECT id,chapter_number,revision,status FROM v2_drafts WHERE project_id=? ORDER BY saved_at DESC LIMIT 1", (project["id"],)).fetchone()
                open_count = c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open'", (project["id"],)).fetchone()[0]
                if has_open_issues is not None and bool(open_count) != has_open_issues:
                    continue
                result.append({"id":project["id"],"seed_key":project["seed_key"],"title":project["title"],"genre":project["genre"],"summary":project["summary"],"status":project["status"],"metadata_revision":project["metadata_revision"],"chapter_count":c.execute("SELECT COUNT(*) FROM v2_chapters WHERE project_id=?",(project["id"],)).fetchone()[0],"current_memory_version":project["current_memory_version"],"current_draft":dict(draft) if draft else None,"open_issue_count":open_count,"updated_at":project["updated_at"]})
            return {"projects":result}

    def create_project(self, user_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def create() -> dict[str, Any]:
                title, summary, genre = str(payload.get("title","")).strip(), str(payload.get("summary","")).strip(), str(payload.get("genre","")).strip()
                if not 1 <= len(title) <= 80 or len(summary) > 500:
                    raise DomainError("project_invalid", 422)
                project_id = self._create_project(c,user_id,title,genre,summary,"user_created")
                draft = c.execute("SELECT * FROM v2_drafts WHERE project_id=?", (project_id,)).fetchone()
                return {"project":{"id":project_id,"title":title,"genre":genre,"summary":summary,"status":"active","current_memory_version":1,"current_draft":{"id":draft["id"],"chapter_number":1,"revision":1,"status":"draft"}},"created_resources":{"outline":True,"characters":True,"world":True}}
            return self._idem(c,user_id,"create_project",key,payload,create,201)

    def project(self, user_id: str, project_id: str) -> dict[str, Any]:
        with self.connection() as c:
            project = self._project(c,user_id,project_id)
            draft = c.execute("SELECT id,chapter_number,revision,status FROM v2_drafts WHERE project_id=? ORDER BY saved_at DESC LIMIT 1", (project_id,)).fetchone()
            run = c.execute("SELECT id,status,created_at FROM v2_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
            return {"id":project["id"],"title":project["title"],"genre":project["genre"],"summary":project["summary"],"status":project["status"],"metadata_revision":project["metadata_revision"],"chapter_count":c.execute("SELECT COUNT(*) FROM v2_chapters WHERE project_id=?",(project_id,)).fetchone()[0],"outline_progress":0,"current_memory_version":project["current_memory_version"],"current_draft":dict(draft) if draft else None,"latest_run":({"run_id":run["id"],"status":run["status"],"created_at":run["created_at"]} if run else None),"open_issue_count":c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open'",(project_id,)).fetchone()[0],"updated_at":project["updated_at"],"data_origin":project["data_origin"]}

    def outline(self, user_id: str, project_id: str) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            nodes = c.execute("SELECT * FROM v2_outline_nodes WHERE project_id=? ORDER BY chapter_number", (project_id,)).fetchall()
            return {"project_id":project_id,"summary":"","volumes":[],"chapter_nodes":[{"id":x["id"],"chapter_number":x["chapter_number"],"title":x["title"],"summary":x["summary"],"status":x["status"],"open_thread_ids":[]} for x in nodes],"open_threads":[]}

    def characters(self, user_id: str, project_id: str) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            rows = c.execute("SELECT * FROM v2_characters WHERE project_id=?", (project_id,)).fetchall()
            values=[]
            for x in rows:
                source_ids=json.loads(x["source_ids_json"])
                if any(not c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=?",(source_id,project_id)).fetchone() for source_id in source_ids):
                    raise DomainError("source_unavailable",422)
                values.append({"id":x["id"],"name":x["name"],"role_type":x["role_type"],"identity":x["identity"],"goal":x["goal"],"current_state":x["current_state"],"knowledge_boundary":x["knowledge_boundary"],"relationships":json.loads(x["relationships_json"]),"source_ids":source_ids})
            return {"project_id":project_id,"characters":values}

    def world(self, user_id: str, project_id: str) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            rows = c.execute("SELECT * FROM v2_world_entries WHERE project_id=?", (project_id,)).fetchall()
            values=[]
            for x in rows:
                related_ids=json.loads(x["related_character_ids_json"]); source_ids=json.loads(x["source_ids_json"])
                if any(not c.execute("SELECT 1 FROM v2_characters WHERE id=? AND project_id=?",(character_id,project_id)).fetchone() for character_id in related_ids):
                    raise DomainError("source_unavailable",422)
                if any(not c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=?",(source_id,project_id)).fetchone() for source_id in source_ids):
                    raise DomainError("source_unavailable",422)
                values.append({"id":x["id"],"entry_type":x["entry_type"],"name":x["name"],"summary":x["summary"],"related_character_ids":related_ids,"source_ids":source_ids})
            return {"project_id":project_id,"entries":values}

    def chapters(self, user_id: str, project_id: str, include_excerpt: bool) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id); result=[]
            for chapter in c.execute("SELECT * FROM v2_chapters WHERE project_id=? ORDER BY chapter_number", (project_id,)).fetchall():
                item={"id":chapter["id"],"number":chapter["chapter_number"],"title":chapter["title"],"summary":chapter["summary"]}
                if include_excerpt:
                    item["source_spans"]=[{"span_id":x["id"],"label":x["label"],"text_excerpt":x["body"][:500]} for x in c.execute("SELECT * FROM v2_source_spans WHERE project_id=? AND chapter_id=?",(project_id,chapter["id"])).fetchall()]
                result.append(item)
            return {"project_id":project_id,"chapters":result}

    def memory(self, user_id: str, project_id: str, version: int | None) -> dict[str, Any]:
        with self.connection() as c:
            project=self._project(c,user_id,project_id); version=version or project["current_memory_version"]
            if not c.execute("SELECT 1 FROM v2_memory_versions WHERE project_id=? AND version=?",(project_id,version)).fetchone(): raise DomainError("resource_not_found",404)
            records=[]
            rows=c.execute("SELECT m.*,s.chapter_id,s.id span_id,s.body excerpt FROM v2_memory_records m LEFT JOIN v2_source_spans s ON s.id=m.source_span_id AND s.project_id=m.project_id WHERE m.project_id=? AND m.version=?",(project_id,version)).fetchall()
            for row in rows:
                if row["source_span_id"] and not row["span_id"]: raise DomainError("source_unavailable",422)
                records.append({"id":row["id"],"memory_type":row["memory_type"],"subject":row["subject"],"predicate":row["predicate"],"value":row["value"],"valid_from":row["valid_from"],"valid_to":row["valid_to"],"review_status":row["review_status"],"source":({"chapter_id":row["chapter_id"],"span_id":row["span_id"],"excerpt":row["excerpt"][:500]} if row["span_id"] else None)})
            return {"project_id":project_id,"memory_version":version,"records":records}

    def draft(self, user_id: str, project_id: str, draft_id: str) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(draft_id,project_id)).fetchone()
            if not draft: raise DomainError("resource_not_found",404)
            return {key:draft[key] for key in ("id","project_id","title","body","chapter_number","revision","status","saved_at")}

    def update_project(self, user_id: str, project_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def update():
                project=self._project(c,user_id,project_id)
                if payload["base_metadata_revision"] != project["metadata_revision"]: raise DomainError("metadata_revision_conflict",409)
                status=payload.get("status",project["status"])
                if project["status"]=="archived" and status != "active": raise DomainError("project_archived",409)
                if status=="archived" and payload.get("confirm_archive") is not True: raise DomainError("confirmation_required",400)
                title,summary,genre=str(payload.get("title",project["title"])).strip(),str(payload.get("summary",project["summary"])).strip(),str(payload.get("genre",project["genre"])).strip()
                if not title or len(title)>80 or len(summary)>500 or status not in {"active","paused","completed","archived"}: raise DomainError("project_invalid",422)
                stamp=utcnow(); revision=project["metadata_revision"]+1
                c.execute("UPDATE v2_projects SET title=?,genre=?,summary=?,status=?,metadata_revision=?,updated_at=? WHERE id=?",(title,genre,summary,status,revision,stamp,project_id))
                return {"project":{"id":project_id,"title":title,"genre":genre,"summary":summary,"status":status,"metadata_revision":revision,"updated_at":stamp}}
            return self._idem(c,user_id,"update_project:"+project_id,key,payload,update)

    # --- draft/revision and continuity persistence ---
    def check_preflight(self, user_id: str, project_id: str, draft_id: str, draft_revision: int) -> None:
        """Validate a check request before inspecting provider availability.

        Empty user-created projects have neither confirmed memory nor usable
        retrieval sources.  This is a product-state response, not a provider
        outage, and it intentionally performs no writes.
        """
        with self.connection() as c:
            project=self._project(c,user_id,project_id,True)
            draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(draft_id,project_id)).fetchone()
            if not draft: raise DomainError("resource_not_found",404)
            if draft["revision"]!=draft_revision: raise DomainError("draft_revision_not_current",409)
            context=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=?",(project_id,project["current_memory_version"])).fetchone()[0]
            if not context: raise DomainError("insufficient_project_context",422)
            if not draft["body"].strip(): raise DomainError("draft_invalid",422)

    def patch_draft(self, user_id: str, project_id: str, draft_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def patch():
                self._project(c,user_id,project_id,True)
                draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(draft_id,project_id)).fetchone()
                if not draft: raise DomainError("resource_not_found",404)
                body=payload["body"]
                if len(body.encode("utf-8"))>120000: raise DomainError("draft_too_large",413)
                if payload["base_revision"]!=draft["revision"]: raise DomainError("revision_conflict",409,False,{"current_revision":draft["revision"]})
                edit=payload.get("edit_context"); edit_json=None
                if edit:
                    run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=? AND status='completed'",(edit["source_run_id"],project_id)).fetchone()
                    issue=c.execute("SELECT * FROM v2_issues WHERE id=? AND project_id=?",(edit["issue_id"],project_id)).fetchone()
                    if not run or not issue or issue["run_id"]!=run["id"] or run["source_revision"]!=draft["revision"] or edit["source_revision"]!=draft["revision"]: raise DomainError("edit_context_invalid",422)
                    edit_json=json.dumps(edit,ensure_ascii=False,sort_keys=True)
                revision,stamp,checksum=draft["revision"]+1,utcnow(),digest(body)
                title=payload.get("title") or draft["title"]
                c.execute("UPDATE v2_drafts SET title=?,body=?,revision=?,status='saved',saved_at=?,parent_revision=?,edit_context_json=?,checksum=? WHERE id=?",(title,body,revision,stamp,draft["revision"],edit_json,checksum,draft_id))
                c.execute("INSERT INTO v2_draft_revisions VALUES(?,?,?,?,?,?,?,?)",(draft_id,revision,title,body,checksum,draft["revision"],edit_json,stamp))
                c.execute("UPDATE v2_projects SET updated_at=? WHERE id=?",(stamp,project_id))
                output={"id":draft_id,"project_id":project_id,"revision":revision,"saved_at":stamp,"body_checksum":checksum,"status":"saved"}
                if edit: output.update({"parent_revision":draft["revision"],"edit_context":edit,"lineage_status":"pending_decision_validation"})
                return output
            return self._idem(c,user_id,"patch_draft:"+project_id+":"+draft_id,key,payload,patch)

    def create_run(self, user_id: str, project_id: str, payload: dict[str, Any], key: str, provenance: dict[str, str]):
        with self.connection() as c:
            def create():
                project=self._project(c,user_id,project_id,True)
                draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(payload["draft_id"],project_id)).fetchone()
                if not draft: raise DomainError("resource_not_found",404)
                if draft["revision"]!=payload["draft_revision"]: raise DomainError("draft_revision_not_current",409)
                if not draft["body"].strip(): raise DomainError("draft_invalid",422)
                context=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=?",(project_id,project["current_memory_version"])).fetchone()[0]
                if not context: raise DomainError("insufficient_project_context",422)
                running=c.execute("SELECT id FROM v2_runs WHERE project_id=? AND draft_id=? AND source_revision=? AND status IN ('queued','running')",(project_id,draft["id"],draft["revision"])).fetchone()
                if running: raise DomainError("run_already_active",409,False,{"run_id":running["id"]})
                run_id,stamp=new_id("run"),utcnow()
                c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,project_id,draft["id"],draft["revision"],"queued","queued",provenance["provider_label"],stamp,provenance["model_label"],provenance["prompt_version"],provenance["schema_version"],provenance["retrieval_method_version"],project["current_memory_version"]))
                c.execute("INSERT INTO v2_run_stages VALUES(?,?,?)",(run_id,"queued",stamp))
                return {"run_id":run_id,"project_id":project_id,"status":"queued","source_revision":draft["revision"],"stage":"queued","created_at":stamp}
            return self._idem(c,user_id,"create_check:"+project_id,key,payload,create,202,with_created=True)

    def advance_run(self, project_id: str, run_id: str, stage: str) -> None:
        with self.connection() as c:
            if not c.execute("SELECT 1 FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone(): raise DomainError("resource_not_found",404)
            c.execute("UPDATE v2_runs SET status='running',stage=? WHERE id=? AND project_id=?",(stage,run_id,project_id))
            c.execute("INSERT OR IGNORE INTO v2_run_stages VALUES(?,?,?)",(run_id,stage,utcnow()))

    def session_budget_exhausted(self, project_id: str, limit: int = 40000) -> bool:
        with self.connection() as c:
            used=c.execute("SELECT COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0) FROM v2_runs WHERE project_id=?",(project_id,)).fetchone()[0]
            return used>=limit

    def run_input(self, project_id: str, run_id: str) -> dict[str, Any]:
        with self.connection() as c:
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not run: raise DomainError("resource_not_found",404)
            revision=c.execute("SELECT * FROM v2_draft_revisions WHERE draft_id=? AND revision=?",(run["draft_id"],run["source_revision"])).fetchone()
            claims=[]
            for ordinal,text in enumerate(x.strip() for x in re.split(r"(?<=[。！？])",revision["body"]) if x.strip()):
                claim_id=f"claim-{run_id}-{ordinal+1}"; claims.append({"id":claim_id,"text":text})
                c.execute("INSERT OR IGNORE INTO v2_run_claims VALUES(?,?,?,?)",(claim_id,run_id,ordinal+1,text))
            memory=[dict(x) for x in c.execute("SELECT id,memory_type,subject,predicate,value,source_span_id FROM v2_memory_records WHERE project_id=? AND version=(SELECT current_memory_version FROM v2_projects WHERE id=?)",(project_id,project_id)).fetchall()]
            spans=[dict(x) for x in c.execute("SELECT id,chapter_id,body,label FROM v2_source_spans WHERE project_id=?",(project_id,)).fetchall()]
            for claim in claims:
                characters="".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]",claim["text"])); terms={characters[index:index+2] for index in range(max(0,len(characters)-1))}; scored=[]
                for span in spans:
                    score=sum(term in span["body"] for term in terms)
                    score+=sum(2 for record in memory if record["source_span_id"]==span["id"] and any(term in (record["subject"]+record["value"]) for term in terms))
                    if score: scored.append((score,span))
                hits=[pair[1] for pair in sorted(scored,key=lambda pair:(-pair[0],pair[1]["id"]))[:5]]
                c.execute("INSERT OR REPLACE INTO v2_retrieval_traces VALUES(?,?,?,?,?)",(run_id,claim["id"],",".join(sorted(terms))[:200],json.dumps([hit["id"] for hit in hits]),run["retrieval_method_version"] or "legacy_unspecified"))
                claim["allowed_evidence"]=hits
            return {"run":dict(run),"draft":{"id":revision["draft_id"],"revision":revision["revision"],"body":revision["body"]},"claims":claims,"memory":memory}

    def finish_run(self, project_id: str, run_id: str, result: dict[str, Any]) -> None:
        with self.connection() as c:
            terminal={"completed":"completed","failed":"failed","timed_out":"timed_out","budget_paused":"budget_paused"}.get(result["status"],"failed")
            stamp=utcnow()
            c.execute("UPDATE v2_runs SET status=?,stage=?,input_tokens=?,output_tokens=?,latency_ms=?,cost_cny=?,error_code=?,retryable=?,completed_at=? WHERE id=? AND project_id=?",(result["status"],terminal,result.get("input_tokens"),result.get("output_tokens"),result.get("latency_ms"),result.get("cost_cny"),result.get("error_code"),int(bool(result.get("retryable"))),stamp,run_id,project_id))
            c.execute("INSERT OR IGNORE INTO v2_run_stages VALUES(?,?,?)",(run_id,terminal,stamp))
            if result["status"]!="completed": return
            for issue in result.get("issues",[]):
                issue_id=new_id("issue")
                c.execute("INSERT INTO v2_issues(id,project_id,run_id,claim_span_id,status,classification,category,severity,evidence_status,explanation,proposed_change_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(issue_id,project_id,run_id,issue["claim_span_id"],"open",issue["status"],issue["category"],issue["severity"],issue["evidence_status"],issue["explanation"],json.dumps(issue.get("proposed_memory_change")) if issue.get("proposed_memory_change") else None))
                for evidence in issue["evidence"]:
                    c.execute("INSERT INTO v2_evidence VALUES(?,?,?,?,?,?,?,?,?)",(new_id("evidence"),project_id,issue_id,evidence["chapter_id"],evidence["span_id"],evidence["excerpt"],evidence["relation"],evidence["sufficiency"],json.dumps(evidence["related_memory_ids"])))

    def run_view(self, user_id: str, project_id: str, run_id: str, include: set[str]) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not run: raise DomainError("resource_not_found",404)
            draft=c.execute("SELECT revision,edit_context_json FROM v2_drafts WHERE id=? AND project_id=?",(run["draft_id"],project_id)).fetchone()
            direct_successor=draft["revision"]==run["source_revision"]+1 and draft["edit_context_json"] and json.loads(draft["edit_context_json"]).get("source_run_id")==run_id
            current=draft["revision"]==run["source_revision"] or direct_successor
            result={"run_id":run_id,"project_id":project_id,"status":run["status"],"stage":run["stage"],"source_revision":run["source_revision"],"current_revision":draft["revision"],"is_stale":not current,"superseded":not current,"lineage_status":("validated_direct_successor" if direct_successor else "current" if current else "lineage_invalid_requires_recheck"),"error_code":run["error_code"],"retryable":bool(run["retryable"]),"created_at":run["created_at"],"completed_at":run["completed_at"]}
            if "issues" in include:
                issues=[]
                for issue in c.execute("SELECT * FROM v2_issues WHERE project_id=? AND run_id=?",(project_id,run_id)).fetchall():
                    item={"id":issue["id"],"claim_span_id":issue["claim_span_id"],"status":issue["status"],"classification":issue["classification"],"category":issue["category"],"severity":issue["severity"],"evidence_status":issue["evidence_status"],"explanation":issue["explanation"]}
                    if "evidence" in include:
                        evidence=[]
                        for row in c.execute("SELECT * FROM v2_evidence WHERE project_id=? AND issue_id=?",(project_id,issue["id"])).fetchall():
                            if not c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=? AND chapter_id=?",(row["span_id"],project_id,row["chapter_id"])).fetchone(): raise DomainError("evidence_unresolvable",422)
                            evidence.append({"id":row["id"],"chapter_id":row["chapter_id"],"span_id":row["span_id"],"excerpt":row["excerpt"],"relation":row["relation"],"sufficiency":row["sufficiency"],"related_memory_ids":json.loads(row["related_memory_ids_json"])})
                        item["evidence"]=evidence
                    issues.append(item)
                result["issues"]=issues
            if "metrics" in include:
                traces=[]
                for trace in c.execute("SELECT claim_id,returned_span_ids_json,method_version FROM v2_retrieval_traces WHERE run_id=? ORDER BY claim_id",(run_id,)).fetchall():
                    claim=c.execute("SELECT ordinal FROM v2_run_claims WHERE id=? AND run_id=?",(trace["claim_id"],run_id)).fetchone()
                    traces.append({"claim_ordinal":claim["ordinal"] if claim else None,"returned_span_ids":json.loads(trace["returned_span_ids_json"]),"method_version":trace["method_version"]})
                result["metrics"]={"latency_ms":run["latency_ms"],"input_tokens":run["input_tokens"],"output_tokens":run["output_tokens"],"cost_cny":run["cost_cny"],"provenance":{"provider_label":run["provider_label"],"model_label":run["model_label"] or "legacy_unspecified","prompt_version":run["prompt_version"] or "legacy_unspecified","schema_version":run["schema_version"] or "legacy_unspecified","retrieval_method_version":run["retrieval_method_version"] or "legacy_unspecified","source_memory_version":run["source_memory_version"]},"retrieval":traces}
            return result

    def decide(self, user_id: str, project_id: str, issue_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def decide() -> dict[str, Any]:
                self._project(c,user_id,project_id,True)
                issue=c.execute("SELECT * FROM v2_issues WHERE id=? AND project_id=?",(issue_id,project_id)).fetchone()
                run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(payload["run_id"],project_id)).fetchone()
                if not issue or not run or issue["run_id"]!=run["id"] or payload["source_revision"]!=run["source_revision"]: raise DomainError("resource_not_found",404)
                if c.execute("SELECT 1 FROM v2_decisions WHERE issue_id=? AND source_revision=?",(issue_id,run["source_revision"])).fetchone(): raise DomainError("already_decided",409)
                draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(run["draft_id"],project_id)).fetchone()
                decision=payload["decision"]; resulting=payload.get("resulting_revision")
                if decision=="accept_and_edit":
                    valid=resulting==run["source_revision"]+1 and draft["revision"]==resulting and draft["edit_context_json"] and json.loads(draft["edit_context_json"]).get("source_run_id")==run["id"] and json.loads(draft["edit_context_json"]).get("issue_id")==issue_id
                    if not valid: raise DomainError("invalid_resulting_revision",422)
                    lineage="validated_direct_successor"
                else:
                    if draft["revision"]!=run["source_revision"]: raise DomainError("lineage_invalid_requires_recheck",409)
                    lineage="current"
                decision_id=new_id("decision")
                c.execute("INSERT INTO v2_decisions VALUES(?,?,?,?,?,?,?,?,?,?)",(decision_id,project_id,issue_id,run["id"],decision,payload.get("note"),run["source_revision"],resulting,lineage,utcnow()))
                c.execute("UPDATE v2_issues SET status='decided' WHERE id=?",(issue_id,))
                return {"id":decision_id,"project_id":project_id,"issue_id":issue_id,"run_id":run["id"],"decision":decision,"source_revision":run["source_revision"],"resulting_revision":resulting,"lineage_status":lineage,"issue_status":"decided"}
            return self._idem(c,user_id,"decision:"+project_id+":"+issue_id,key,payload,decide)

    def create_changeset(self, user_id: str, project_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def make() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(payload["run_id"],project_id)).fetchone()
                if not run: raise DomainError("resource_not_found",404)
                if payload["source_run_revision"]!=run["source_revision"]: raise DomainError("revision_mismatch",422)
                draft=c.execute("SELECT * FROM v2_drafts WHERE id=?",(run["draft_id"],)).fetchone()
                successor=draft["revision"]==run["source_revision"]+1 and draft["edit_context_json"] and json.loads(draft["edit_context_json"]).get("source_run_id")==run["id"]
                if not (draft["revision"]==run["source_revision"] or successor) or payload["resolved_revision"]!=draft["revision"]: raise DomainError("lineage_invalid_requires_recheck",409)
                issues=c.execute("SELECT * FROM v2_issues WHERE project_id=? AND run_id=?",(project_id,run["id"])).fetchall()
                decisions=c.execute("SELECT * FROM v2_decisions WHERE project_id=? AND run_id=?",(project_id,run["id"])).fetchall()
                if len(issues)!=len(decisions): raise DomainError("unresolved_required_decisions",409)
                proposed=[]
                for decision in decisions:
                    issue=next(item for item in issues if item["id"]==decision["issue_id"])
                    # only a deliberate author keep can propose canon change
                    if decision["decision"]=="keep_intentional" and issue["proposed_change_json"]:
                        after=json.loads(issue["proposed_change_json"]); before=None
                        if after["operation"]=="replace":
                            old=c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=? AND id=?",(project_id,project["current_memory_version"],after.get("affected_memory_id"))).fetchone()
                            if not old: raise DomainError("no_reviewable_changes",422)
                            before={field:old[field] for field in ("id","memory_type","subject","predicate","value")}
                        proposed.append((issue,decision,after,before))
                if not proposed: raise DomainError("no_reviewable_changes",422)
                change_set_id=new_id("changeset"); lineage="validated_direct_successor" if successor else "current"
                c.execute("INSERT INTO v2_change_sets VALUES(?,?,?,?,?,?,?,?,?,?,?)",(change_set_id,project_id,run["id"],run["source_revision"],draft["revision"],lineage,project["current_memory_version"],project["current_memory_version"]+1,"draft",utcnow(),None))
                items=[]
                for issue,decision,after,before in proposed:
                    item_id=new_id("changeitem")
                    c.execute("INSERT INTO v2_change_set_items VALUES(?,?,?,?,?,?,?,?,?)",(item_id,project_id,change_set_id,after["operation"],json.dumps(before),json.dumps(after),json.dumps([issue["id"],issue["claim_span_id"]]),json.dumps([decision["id"]]),None))
                    items.append({"id":item_id,"operation":after["operation"],"before":before,"after":after,"review_status":None})
                return {"change_set":{"id":change_set_id,"project_id":project_id,"status":"draft","base_memory_version":project["current_memory_version"],"target_memory_version":project["current_memory_version"]+1,"source_run_revision":run["source_revision"],"resolved_revision":draft["revision"],"lineage_status":lineage,"items":items}}
            return self._idem(c,user_id,"changeset:"+project_id,key,payload,make,201)

    def commit_changeset(self, user_id: str, project_id: str, change_set_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def commit() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                change_set=c.execute("SELECT * FROM v2_change_sets WHERE id=? AND project_id=?",(change_set_id,project_id)).fetchone()
                if not change_set: raise DomainError("resource_not_found",404)
                if change_set["status"]!="draft": raise DomainError("already_committed",409)
                if payload.get("confirm") is not True: raise DomainError("confirmation_required",400)
                items=c.execute("SELECT * FROM v2_change_set_items WHERE project_id=? AND change_set_id=?",(project_id,change_set_id)).fetchall(); available={item["id"] for item in items}; accepted=set(payload.get("accepted_item_ids",[])); rejected=set(payload.get("rejected_item_ids",[]))
                if accepted&rejected or accepted|rejected!=available: raise DomainError("invalid_item_selection",422)
                if project["current_memory_version"]!=change_set["base_version"]: raise DomainError("base_version_changed",409)
                stamp,audit_id=utcnow(),new_id("commit")
                if not accepted:
                    c.execute("UPDATE v2_change_sets SET status='rejected',committed_at=? WHERE id=?",(stamp,change_set_id))
                    c.execute("UPDATE v2_change_set_items SET review_status='rejected' WHERE project_id=? AND change_set_id=?",(project_id,change_set_id))
                    c.execute("INSERT INTO v2_commit_audits VALUES(?,?,?,?,?,?,?,?)",(audit_id,project_id,change_set_id,"rejected",json.dumps([]),json.dumps(sorted(rejected)),payload.get("note"),stamp))
                    return {"change_set_id":change_set_id,"status":"rejected","memory_version":{"previous":project["current_memory_version"],"current":project["current_memory_version"]},"committed_item_ids":[],"rejected_item_ids":sorted(rejected),"audit_id":audit_id}
                target=change_set["target_version"]
                c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)",(project_id,target,"current",project["current_memory_version"],stamp))
                # V5 starts with the complete V4 canon; accepted changes apply after copy.
                c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) SELECT id||'-v'||?,project_id,?,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id FROM v2_memory_records WHERE project_id=? AND version=?",(target,target,project_id,project["current_memory_version"]))
                for item in items:
                    if item["id"] not in accepted: continue
                    after=json.loads(item["after_json"]); issue_id=json.loads(item["source_ids_json"])[0]
                    evidence=c.execute("SELECT span_id FROM v2_evidence WHERE project_id=? AND issue_id=? LIMIT 1",(project_id,issue_id)).fetchone()
                    if not evidence: raise DomainError("commit_failed",503,True)
                    if after["operation"]=="replace":
                        before=json.loads(item["before_json"]); record_id=before["id"]+f"-v{target}"
                        if not c.execute("SELECT 1 FROM v2_memory_records WHERE id=? AND project_id=? AND version=?",(record_id,project_id,target)).fetchone(): raise DomainError("commit_failed",503,True)
                        c.execute("UPDATE v2_memory_records SET memory_type=?,subject=?,predicate=?,value=?,source_span_id=?,review_status='author_confirmed' WHERE id=? AND project_id=? AND version=?",(after["memory_type"],after["subject"],after["predicate"],after["value"],evidence["span_id"],record_id,project_id,target))
                    else:
                        c.execute("INSERT INTO v2_memory_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(new_id("mem"),project_id,target,after["memory_type"],after["subject"],after["predicate"],after["value"],evidence["span_id"],"author_confirmed",None,None,None))
                c.execute("UPDATE v2_memory_versions SET status='superseded' WHERE project_id=? AND version=?",(project_id,project["current_memory_version"]))
                c.execute("UPDATE v2_projects SET current_memory_version=?,updated_at=? WHERE id=?",(target,stamp,project_id))
                c.execute("UPDATE v2_change_sets SET status='committed',committed_at=? WHERE id=?",(stamp,change_set_id))
                if accepted: c.execute("UPDATE v2_change_set_items SET review_status='accepted' WHERE id IN ("+",".join("?"*len(accepted))+")",tuple(accepted))
                if rejected: c.execute("UPDATE v2_change_set_items SET review_status='rejected' WHERE id IN ("+",".join("?"*len(rejected))+")",tuple(rejected))
                c.execute("INSERT INTO v2_commit_audits VALUES(?,?,?,?,?,?,?,?)",(audit_id,project_id,change_set_id,"committed",json.dumps(sorted(accepted)),json.dumps(sorted(rejected)),payload.get("note"),stamp))
                return {"change_set_id":change_set_id,"status":"committed","memory_version":{"previous":project["current_memory_version"],"current":target},"committed_item_ids":sorted(accepted),"rejected_item_ids":sorted(rejected),"audit_id":audit_id}
            return self._idem(c,user_id,"commit:"+project_id+":"+change_set_id,key,payload,commit)

    # --- reset and imports ---
    def reset(self, user_id: str, project_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def reset() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                if payload.get("confirm") is not True: raise DomainError("confirmation_required",400)
                if payload.get("reason") not in {"fresh_start","demo_recovery"}: raise DomainError("invalid_request",400)
                # dependent children first. The set is deliberately project-scoped.
                c.execute("DELETE FROM v2_commit_audits WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_change_set_items WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_change_sets WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_decisions WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_evidence WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_issues WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_retrieval_traces WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_run_claims WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_run_stages WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_runs WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_draft_revisions WHERE draft_id IN (SELECT id FROM v2_drafts WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_drafts WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_records WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_versions WHERE project_id=?",(project_id,))
                if project["data_origin"]=="demo_seed":
                    c.execute("DELETE FROM v2_characters WHERE project_id=?",(project_id,))
                    c.execute("DELETE FROM v2_world_entries WHERE project_id=?",(project_id,))
                    c.execute("DELETE FROM v2_outline_nodes WHERE project_id=?",(project_id,))
                    c.execute("DELETE FROM v2_source_spans WHERE project_id=?",(project_id,))
                    c.execute("DELETE FROM v2_chapters WHERE project_id=?",(project_id,))
                    if project["seed_key"]=="grey_harbor":
                        self._seed_grey_harbor(c,project_id); version=4
                    else:
                        self._seed_other(c,project_id,project["seed_key"]); version=1
                elif project["data_origin"]=="user_import":
                    # Import preserves confirmed chapters/spans but never reparses original text.
                    c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)",(project_id,1,"current",None,utcnow()))
                    number=c.execute("SELECT COALESCE(MAX(chapter_number),0)+1 FROM v2_chapters WHERE project_id=?",(project_id,)).fetchone()[0]
                    self._draft(c,project_id,number); version=1
                else:
                    c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)",(project_id,1,"current",None,utcnow()))
                    self._draft(c,project_id,1); version=1
                c.execute("UPDATE v2_projects SET current_memory_version=?,updated_at=? WHERE id=?",(version,utcnow(),project_id))
                # A project reset invalidates replay records that reference
                # deleted drafts/runs, but retains this reset's own replay.
                c.execute("DELETE FROM v2_idempotency WHERE scope=? AND operation LIKE ? AND operation!=?",(user_id,"%"+project_id+"%","reset:"+project_id))
                reset_id=new_id("reset")
                result={"reset_id":reset_id,"project_id":project_id,"current_memory_version":version,"draft_revision":1,"status":"completed","data_origin":project["data_origin"]}
                c.execute("INSERT INTO v2_reset_audits VALUES(?,?,?,?,?,?)",(reset_id,project_id,user_id,payload["reason"],utcnow(),json.dumps(result)))
                return result
            return self._idem(c,user_id,"reset:"+project_id,key,payload,reset)

    def _parse_import(self, text: str) -> tuple[list[dict[str, Any]], str, list[str]]:
        # Markdown headings take priority, then Chinese/Arabic chapter headings.
        matcher=re.compile(r"(?mi)^\s*(?:#{1,6}\s+|第\s*[0-9一二三四五六七八九十百]+\s*[章节回]|chapter\s+\d+\s*[:：]?\s*)(.+)$")
        found=list(matcher.finditer(text))
        if not found:
            return [{"id":"preview-1","title":"第1章","order":1,"body":text}],"single_chapter_fallback",["chapter_heading_not_found"]
        chapters=[]
        for index,match in enumerate(found):
            end=found[index+1].start() if index+1<len(found) else len(text)
            body=text[match.end():end].strip()
            if body: chapters.append({"id":f"preview-{len(chapters)+1}","title":match.group(1).strip()[:120],"order":len(chapters)+1,"body":body})
        if not chapters: raise DomainError("chapter_detection_failed",422)
        return chapters,"markdown_or_chinese_heading",[]

    def preview_import(self, user_id: str, filename: str, content: bytes, key: str):
        if not filename.lower().endswith((".txt",".md")): raise DomainError("unsupported_format",415)
        if not content: raise DomainError("empty_file",400)
        if len(content)>5*1024*1024: raise DomainError("import_too_large",413)
        try: text=content.decode("utf-8")
        except UnicodeDecodeError: raise DomainError("unsupported_encoding",415)
        with self.connection() as c:
            payload={"filename":filename,"sha256":hashlib.sha256(content).hexdigest()}
            def preview() -> dict[str, Any]:
                chapters,strategy,warnings=self._parse_import(text); import_id=new_id("import"); expires_at=(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()
                c.execute("INSERT INTO v2_import_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(import_id,user_id,filename,len(content),payload["sha256"],filename.rsplit(".",1)[-1].lower(),json.dumps(chapters,ensure_ascii=False),text,json.dumps(warnings),expires_at,None,utcnow()))
                return {"import_id":import_id,"file":{"name":filename,"size":len(content),"sha256":payload["sha256"],"format":filename.rsplit(".",1)[-1].lower()},"detected":{"strategy":strategy,"chapter_count":len(chapters),"chapters":[{"preview_id":item["id"],"title":item["title"],"order":item["order"],"character_count":len(item["body"]),"excerpt":item["body"][:180]} for item in chapters]},"warnings":warnings,"expires_at":expires_at}
            return self._idem(c,user_id,"preview_import",key,payload,preview,201)

    def commit_import(self, user_id: str, import_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def commit() -> dict[str, Any]:
                imported=c.execute("SELECT * FROM v2_import_drafts WHERE id=? AND user_id=?",(import_id,user_id)).fetchone()
                if not imported: raise DomainError("import_not_found",404)
                if imported["committed_at"]: raise DomainError("already_committed",409)
                if imported["expires_at"]<=utcnow():
                    c.execute("UPDATE v2_import_drafts SET source_text=NULL WHERE id=?",(import_id,))
                    c.commit()
                    raise DomainError("import_expired",409)
                if payload.get("confirm") is not True: raise DomainError("confirmation_required",400)
                chapters=json.loads(imported["chapters_json"])
                if set(payload.get("chapter_preview_ids",[]))!={chapter["id"] for chapter in chapters}: raise DomainError("invalid_chapter_selection",422)
                title,summary,genre=str(payload.get("title","")).strip(),str(payload.get("summary","")).strip(),str(payload.get("genre","")).strip()
                if not title or len(title)>80 or len(summary)>500: raise DomainError("project_invalid",422)
                project_id=self._create_project(c,user_id,title,genre,summary,"user_import",imported=chapters)
                draft=c.execute("SELECT * FROM v2_drafts WHERE project_id=?",(project_id,)).fetchone()
                c.execute("UPDATE v2_import_drafts SET committed_at=?,source_text=NULL WHERE id=?",(utcnow(),import_id))
                return {"project":{"id":project_id,"title":title,"data_origin":"user_import","status":"active","current_memory_version":1,"memory_initialization_status":"required","current_draft":{"id":draft["id"],"chapter_number":draft["chapter_number"],"revision":1}},"import":{"chapter_count":len(chapters),"source_span_count":len(chapters),"sha256":imported["sha256"],"status":"completed"}}
            return self._idem(c,user_id,"commit_import:"+import_id,key,payload,commit,201)

    def counts(self) -> dict[str, int]:
        self.initialize()
        with self.connection() as c:
            return {table:c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("v2_users","v2_projects","v2_runs")}
