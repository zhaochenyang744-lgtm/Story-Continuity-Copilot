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
from .memory_contract import is_controlled_candidate, normalize_memory_value, normalized_predicate
from .seed_data import CHAPTERS, DEMO_REVIEW_ISSUES, DRAFT, MEMORY_RECORDS


RUN_ACTIVE_STATUSES = {"queued", "running"}
RUN_TERMINAL_STATUSES = {"completed", "failed", "timed_out", "cancelled"}


def public_run_status(status: str) -> str:
    """Expose only the frozen Stage 12 state vocabulary."""
    return "failed" if status == "budget_paused" else status


def public_run_error(status: str, error_code: str | None) -> str | None:
    if status == "budget_paused" or error_code in {"budget_paused", "session_guard_paused"}:
        return "budget_guard_exceeded"
    return error_code


def elapsed_ms(started_at: str | None, completed_at: str | None) -> int | None:
    if not started_at or not completed_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
    except ValueError:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(kind: str) -> str:
    return f"{kind}-{uuid.uuid4()}"


def scoped_seed_id(kind: str, project_id: str, key: str) -> str:
    """Stable inside one demo project, unique across accounts and projects."""
    return f"{kind}-{uuid.uuid5(uuid.NAMESPACE_URL, f'scc-demo:{project_id}:{key}')}"


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
CREATE TABLE IF NOT EXISTS v2_users(id TEXT PRIMARY KEY,account_name TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,password_hash TEXT NOT NULL,created_at TEXT NOT NULL,account_type TEXT NOT NULL DEFAULT 'registered',visitor_expires_at TEXT,recovery_email_hash TEXT,recovery_email_masked TEXT,recovery_email_verified_at TEXT);
CREATE TABLE IF NOT EXISTS v2_sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),token_hash TEXT NOT NULL UNIQUE,expires_at TEXT NOT NULL,revoked_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_projects(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),title TEXT NOT NULL,genre TEXT NOT NULL DEFAULT '',summary TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,metadata_revision INTEGER NOT NULL,data_origin TEXT NOT NULL,seed_key TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,current_memory_version INTEGER NOT NULL DEFAULT 1,source_revision INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS v2_projects_by_owner ON v2_projects(user_id,status,updated_at);
CREATE TABLE IF NOT EXISTS v2_outline_nodes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_number INTEGER NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,status TEXT NOT NULL,UNIQUE(project_id,chapter_number));
CREATE TABLE IF NOT EXISTS v2_characters(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),name TEXT NOT NULL,role_type TEXT NOT NULL,identity TEXT NOT NULL,goal TEXT NOT NULL,current_state TEXT NOT NULL,knowledge_boundary TEXT NOT NULL,relationships_json TEXT NOT NULL,source_ids_json TEXT NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_world_entries(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),entry_type TEXT NOT NULL,name TEXT NOT NULL,summary TEXT NOT NULL,related_character_ids_json TEXT NOT NULL,source_ids_json TEXT NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_chapters(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_number INTEGER NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,body TEXT NOT NULL,source_revision INTEGER NOT NULL DEFAULT 1,UNIQUE(project_id,chapter_number));
CREATE TABLE IF NOT EXISTS v2_source_spans(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_id TEXT NOT NULL REFERENCES v2_chapters(id),label TEXT NOT NULL,body TEXT NOT NULL,source_revision INTEGER NOT NULL DEFAULT 1,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_spans_by_project ON v2_source_spans(project_id,chapter_id);
CREATE TABLE IF NOT EXISTS v2_memory_versions(project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,status TEXT NOT NULL,parent_version INTEGER,created_at TEXT NOT NULL,PRIMARY KEY(project_id,version));
CREATE TABLE IF NOT EXISTS v2_memory_records(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,memory_type TEXT NOT NULL,subject TEXT NOT NULL,predicate TEXT NOT NULL,value TEXT NOT NULL,source_span_id TEXT,review_status TEXT NOT NULL,valid_from INTEGER,valid_to INTEGER,source_claim_id TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_drafts(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),chapter_number INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,saved_at TEXT NOT NULL,parent_revision INTEGER,edit_context_json TEXT,checksum TEXT NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_draft_revisions(draft_id TEXT NOT NULL REFERENCES v2_drafts(id),revision INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,checksum TEXT NOT NULL,parent_revision INTEGER,edit_context_json TEXT,saved_at TEXT NOT NULL,PRIMARY KEY(draft_id,revision));
CREATE TABLE IF NOT EXISTS v2_runs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),draft_id TEXT NOT NULL REFERENCES v2_drafts(id),source_revision INTEGER NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,provider_label TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,latency_ms INTEGER,cost_cny REAL,error_code TEXT,retryable INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,completed_at TEXT,model_label TEXT,prompt_version TEXT,schema_version TEXT,retrieval_method_version TEXT,source_memory_version INTEGER,result_origin TEXT NOT NULL DEFAULT 'provider',run_type TEXT NOT NULL DEFAULT 'continuity',source_change_set_id TEXT,source_span_ids_json TEXT NOT NULL DEFAULT '[]',started_at TEXT,cancel_requested_at TEXT,duration_ms INTEGER,retry_of_run_id TEXT,root_run_id TEXT,attempt_number INTEGER NOT NULL DEFAULT 1,incremental_batch_id TEXT,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_runs_by_project ON v2_runs(project_id,draft_id,source_revision,status);
CREATE TABLE IF NOT EXISTS v2_run_stages(run_id TEXT NOT NULL REFERENCES v2_runs(id),stage TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(run_id,stage));
CREATE TABLE IF NOT EXISTS v2_run_events(run_id TEXT NOT NULL REFERENCES v2_runs(id),sequence INTEGER NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,error_code TEXT,created_at TEXT NOT NULL,PRIMARY KEY(run_id,sequence));
CREATE INDEX IF NOT EXISTS v2_run_events_by_run ON v2_run_events(run_id,sequence);
CREATE TABLE IF NOT EXISTS v2_run_claims(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES v2_runs(id),ordinal INTEGER NOT NULL,text TEXT NOT NULL,UNIQUE(run_id,ordinal));
CREATE TABLE IF NOT EXISTS v2_retrieval_traces(run_id TEXT NOT NULL REFERENCES v2_runs(id),claim_id TEXT NOT NULL,terms TEXT NOT NULL,returned_span_ids_json TEXT NOT NULL,method_version TEXT NOT NULL,PRIMARY KEY(run_id,claim_id));
CREATE TABLE IF NOT EXISTS v2_issues(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),claim_span_id TEXT NOT NULL,status TEXT NOT NULL,classification TEXT NOT NULL DEFAULT 'conflict',category TEXT NOT NULL,severity TEXT NOT NULL,evidence_status TEXT NOT NULL,explanation TEXT NOT NULL,proposed_change_json TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_evidence(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),chapter_id TEXT NOT NULL,span_id TEXT NOT NULL,excerpt TEXT NOT NULL,relation TEXT NOT NULL,sufficiency TEXT NOT NULL,related_memory_ids_json TEXT NOT NULL,source_revision INTEGER NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),decision TEXT NOT NULL,note TEXT,source_revision INTEGER NOT NULL,resulting_revision INTEGER,lineage_status TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(issue_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_change_sets(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),source_run_revision INTEGER NOT NULL,resolved_revision INTEGER NOT NULL,lineage_status TEXT NOT NULL,base_version INTEGER NOT NULL,target_version INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,committed_at TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_change_set_items(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),change_set_id TEXT NOT NULL REFERENCES v2_change_sets(id),operation TEXT NOT NULL,before_json TEXT,after_json TEXT NOT NULL,source_ids_json TEXT NOT NULL,decision_ids_json TEXT NOT NULL,review_status TEXT,committed_after_json TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_commit_audits(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),change_set_id TEXT NOT NULL REFERENCES v2_change_sets(id),status TEXT NOT NULL,accepted_json TEXT NOT NULL,rejected_json TEXT NOT NULL,note TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_reset_audits(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),user_id TEXT NOT NULL REFERENCES v2_users(id),reason TEXT NOT NULL,completed_at TEXT NOT NULL,response_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_idempotency(scope TEXT NOT NULL,operation TEXT NOT NULL,idempotency_key TEXT NOT NULL,fingerprint TEXT NOT NULL,response_json TEXT NOT NULL,status_code INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(scope,operation,idempotency_key));
CREATE TABLE IF NOT EXISTS v2_import_drafts(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),filename TEXT NOT NULL,byte_size INTEGER NOT NULL,sha256 TEXT NOT NULL,format TEXT NOT NULL,chapters_json TEXT NOT NULL,source_text TEXT,warnings_json TEXT NOT NULL,expires_at TEXT NOT NULL,committed_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_memory_initializations(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),source_revision INTEGER NOT NULL,source_snapshot_digest TEXT NOT NULL,status TEXT NOT NULL,provider_label TEXT NOT NULL,model_label TEXT NOT NULL,prompt_version TEXT NOT NULL,schema_version TEXT NOT NULL,error_code TEXT,created_at TEXT NOT NULL,completed_at TEXT,UNIQUE(project_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_memory_candidates(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),initialization_id TEXT NOT NULL REFERENCES v2_memory_initializations(id),source_revision INTEGER NOT NULL,candidate_ordinal INTEGER NOT NULL DEFAULT 0,memory_type TEXT NOT NULL,subject TEXT NOT NULL,predicate TEXT NOT NULL,value TEXT NOT NULL,chapter_id TEXT NOT NULL REFERENCES v2_chapters(id),source_span_id TEXT NOT NULL REFERENCES v2_source_spans(id),candidate_origin TEXT NOT NULL DEFAULT 'initialization',review_priority TEXT NOT NULL DEFAULT 'supporting',decision_status TEXT NOT NULL DEFAULT 'pending',decision_json TEXT,decided_at TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_memory_candidate_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),initialization_id TEXT NOT NULL REFERENCES v2_memory_initializations(id),candidate_id TEXT NOT NULL REFERENCES v2_memory_candidates(id),decision TEXT NOT NULL,after_json TEXT,evidence_span_id TEXT,source_revision INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(candidate_id));
CREATE INDEX IF NOT EXISTS v2_memory_candidates_by_initialization ON v2_memory_candidates(initialization_id,decision_status);
CREATE TABLE IF NOT EXISTS v2_source_change_sets(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),user_id TEXT NOT NULL REFERENCES v2_users(id),base_source_revision INTEGER NOT NULL,target_source_revision INTEGER NOT NULL,mode TEXT NOT NULL,input_method TEXT NOT NULL,content_hash TEXT NOT NULL,content_json TEXT NOT NULL,chapters_json TEXT NOT NULL,status TEXT NOT NULL,error_code TEXT,expires_at TEXT NOT NULL,created_at TEXT NOT NULL,committed_at TEXT,draft_id TEXT,draft_revision INTEGER,draft_checksum TEXT,failed_at TEXT,failure_code TEXT,commit_result_json TEXT,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_source_change_sets_by_project ON v2_source_change_sets(project_id,status,created_at);
CREATE TABLE IF NOT EXISTS v2_source_change_set_audits(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),change_set_id TEXT NOT NULL REFERENCES v2_source_change_sets(id),event TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_memory_delta_batches(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),source_revision INTEGER NOT NULL,base_memory_version INTEGER NOT NULL,continuity_run_id TEXT NOT NULL REFERENCES v2_runs(id),memory_delta_run_id TEXT NOT NULL REFERENCES v2_runs(id),status TEXT NOT NULL,error_code TEXT,created_at TEXT NOT NULL,completed_at TEXT,covered_at TEXT,UNIQUE(project_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_memory_delta_candidates(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),batch_id TEXT NOT NULL REFERENCES v2_memory_delta_batches(id),source_revision INTEGER NOT NULL,candidate_ordinal INTEGER NOT NULL,memory_type TEXT NOT NULL,subject TEXT NOT NULL,predicate TEXT NOT NULL,value TEXT NOT NULL,chapter_id TEXT NOT NULL REFERENCES v2_chapters(id),source_span_id TEXT NOT NULL REFERENCES v2_source_spans(id),candidate_origin TEXT NOT NULL DEFAULT 'delta',review_priority TEXT NOT NULL,decision_status TEXT NOT NULL DEFAULT 'pending',decision_json TEXT,decided_at TEXT,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_memory_delta_candidates_by_batch ON v2_memory_delta_candidates(batch_id,decision_status);
CREATE TABLE IF NOT EXISTS v2_memory_delta_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),batch_id TEXT NOT NULL REFERENCES v2_memory_delta_batches(id),candidate_id TEXT NOT NULL REFERENCES v2_memory_delta_candidates(id),decision TEXT NOT NULL,after_json TEXT,evidence_span_id TEXT,source_revision INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(candidate_id));
CREATE TABLE IF NOT EXISTS v2_source_coverage_audits(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),source_revision INTEGER NOT NULL,status TEXT NOT NULL,memory_version INTEGER NOT NULL,delta_batch_id TEXT NOT NULL REFERENCES v2_memory_delta_batches(id),actor_user_id TEXT,details_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,UNIQUE(project_id,source_revision));
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
            self._migrate_stage8_review_contract(c)
            self._migrate_stage9_initialization_contract(c)
            self._migrate_stage11i_core_coverage(c)
            self._migrate_stage11j_source_revisions(c)
            self._migrate_stage11j_lifecycle_repair(c)
            self._migrate_stage11k_incremental_delta(c)
            self._migrate_stage11k_run_audit_fields(c)
            self._migrate_stage11k_coverage_audit_details(c)
            self._migrate_stage13_identity(c)
            self._migrate_legacy_project(c)
            self._migrate_stage12_run_lifecycle(c)

    def _migrate_stage13_identity(self, c: sqlite3.Connection) -> None:
        columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_users)")}
        additions = {
            "account_type": "TEXT NOT NULL DEFAULT 'registered'",
            "visitor_expires_at": "TEXT",
            "recovery_email_hash": "TEXT",
            "recovery_email_masked": "TEXT",
            "recovery_email_verified_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                c.execute(f"ALTER TABLE v2_users ADD COLUMN {name} {definition}")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS v2_users_recovery_email_unique ON v2_users(recovery_email_hash) WHERE recovery_email_hash IS NOT NULL")

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

    def _migrate_stage8_review_contract(self, c: sqlite3.Connection) -> None:
        run_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_runs)").fetchall()}
        if "result_origin" not in run_columns:
            c.execute("ALTER TABLE v2_runs ADD COLUMN result_origin TEXT NOT NULL DEFAULT 'provider'")
        evidence_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_evidence)").fetchall()}
        if "source_revision" not in evidence_columns:
            c.execute("ALTER TABLE v2_evidence ADD COLUMN source_revision INTEGER")
            c.execute("UPDATE v2_evidence SET source_revision=(SELECT r.source_revision FROM v2_issues i JOIN v2_runs r ON r.id=i.run_id AND r.project_id=i.project_id WHERE i.id=v2_evidence.issue_id AND i.project_id=v2_evidence.project_id)")
        item_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_change_set_items)").fetchall()}
        if "committed_after_json" not in item_columns:
            c.execute("ALTER TABLE v2_change_set_items ADD COLUMN committed_after_json TEXT")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(7,?)", (utcnow(),))

    def _migrate_stage9_initialization_contract(self, c: sqlite3.Connection) -> None:
        """Stage 9 is additive: imported text remains immutable and V1 stays V1."""
        decision_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_memory_candidate_decisions)").fetchall()}
        if "evidence_span_id" not in decision_columns:
            c.execute("ALTER TABLE v2_memory_candidate_decisions ADD COLUMN evidence_span_id TEXT")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(9,?)", (utcnow(),))

    def _migrate_stage11i_core_coverage(self, c: sqlite3.Connection) -> None:
        if c.execute("SELECT 1 FROM schema_migrations WHERE version=11").fetchone():
            return
        columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_memory_candidates)").fetchall()}
        if "candidate_origin" not in columns:
            c.execute("ALTER TABLE v2_memory_candidates ADD COLUMN candidate_origin TEXT NOT NULL DEFAULT 'initialization'")
        if "review_priority" not in columns:
            c.execute("ALTER TABLE v2_memory_candidates ADD COLUMN review_priority TEXT NOT NULL DEFAULT 'supporting'")
        if "candidate_ordinal" not in columns:
            c.execute("ALTER TABLE v2_memory_candidates ADD COLUMN candidate_ordinal INTEGER NOT NULL DEFAULT 0")
        # The legacy table had no ordinal. Preserve its insertion order
        # (rowid), while tracking ordinals independently per initialization.
        rows = c.execute("SELECT rowid,* FROM v2_memory_candidates ORDER BY rowid").fetchall()
        grouped: dict[str, set[tuple[str, str, str]]] = {}
        ordinal_by_initialization: dict[str, int] = {}
        for row in rows:
            key = self._candidate_key(row["memory_type"], row["subject"], row["predicate"])
            valid = self._is_controlled_candidate(row["memory_type"], row["predicate"])
            seen = grouped.setdefault(row["initialization_id"], set())
            priority = "core" if valid and key not in seen else "supporting"
            if valid: seen.add(key)
            ordinal_by_initialization[row["initialization_id"]] = ordinal_by_initialization.get(row["initialization_id"], 0) + 1
            c.execute("UPDATE v2_memory_candidates SET candidate_origin='initialization',review_priority=?,candidate_ordinal=? WHERE id=?", (priority,ordinal_by_initialization[row["initialization_id"]],row["id"]))
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(11,?)", (utcnow(),))

    def _migrate_stage11j_source_revisions(self, c: sqlite3.Connection) -> None:
        if c.execute("SELECT 1 FROM schema_migrations WHERE version=12").fetchone():
            return
        columns={row["name"] for row in c.execute("PRAGMA table_info(v2_projects)").fetchall()}
        if "source_revision" not in columns:
            c.execute("ALTER TABLE v2_projects ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 1")
        chapter_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_chapters)").fetchall()}
        if "source_revision" not in chapter_columns:
            c.execute("ALTER TABLE v2_chapters ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 1")
        span_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_source_spans)").fetchall()}
        if "source_revision" not in span_columns:
            c.execute("ALTER TABLE v2_source_spans ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 1")
        c.execute("CREATE INDEX IF NOT EXISTS v2_spans_by_project_revision ON v2_source_spans(project_id,source_revision)")
        c.execute("UPDATE v2_projects SET source_revision=1 WHERE source_revision IS NULL OR source_revision<1")
        c.execute("INSERT INTO schema_migrations VALUES(12,?)",(utcnow(),))

    def _migrate_stage11j_lifecycle_repair(self, c: sqlite3.Connection) -> None:
        if c.execute("SELECT 1 FROM schema_migrations WHERE version=13").fetchone(): return
        for table in ("v2_chapters","v2_source_spans"):
            fields={row["name"] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
            if "source_revision" not in fields: c.execute(f"ALTER TABLE {table} ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 1")
        c.execute("CREATE INDEX IF NOT EXISTS v2_spans_by_project_revision ON v2_source_spans(project_id,source_revision)")
        columns={row["name"] for row in c.execute("PRAGMA table_info(v2_source_change_sets)").fetchall()}
        for name,definition in {"draft_id":"TEXT","draft_revision":"INTEGER","draft_checksum":"TEXT","failed_at":"TEXT","failure_code":"TEXT","commit_result_json":"TEXT"}.items():
            if name not in columns: c.execute(f"ALTER TABLE v2_source_change_sets ADD COLUMN {name} {definition}")
        c.execute("INSERT INTO schema_migrations VALUES(13,?)",(utcnow(),))

    def _migrate_stage11k_incremental_delta(self, c: sqlite3.Connection) -> None:
        """One-time additive boundary for independent incremental runs.

        It deliberately only introduces a discriminator for historic Run rows;
        existing source, Memory, and candidate lineage is never recalculated.
        The delta tables themselves are created by ``SCHEMA`` for both a new
        and an upgraded database.
        """
        if c.execute("SELECT 1 FROM schema_migrations WHERE version=14").fetchone():
            return
        fields={row["name"] for row in c.execute("PRAGMA table_info(v2_runs)").fetchall()}
        if "run_type" not in fields:
            c.execute("ALTER TABLE v2_runs ADD COLUMN run_type TEXT NOT NULL DEFAULT 'continuity'")
        if "source_change_set_id" not in fields:
            c.execute("ALTER TABLE v2_runs ADD COLUMN source_change_set_id TEXT")
        if "source_span_ids_json" not in fields:
            c.execute("ALTER TABLE v2_runs ADD COLUMN source_span_ids_json TEXT NOT NULL DEFAULT '[]'")
        c.execute("CREATE INDEX IF NOT EXISTS v2_runs_by_project_type_revision ON v2_runs(project_id,run_type,source_revision,status)")
        c.execute("INSERT INTO schema_migrations VALUES(14,?)",(utcnow(),))

    def _migrate_stage11k_run_audit_fields(self, c: sqlite3.Connection) -> None:
        """Forward-safe repair for databases opened during an earlier 11K build."""
        if c.execute("SELECT 1 FROM schema_migrations WHERE version=15").fetchone(): return
        fields={row["name"] for row in c.execute("PRAGMA table_info(v2_runs)").fetchall()}
        if "source_change_set_id" not in fields: c.execute("ALTER TABLE v2_runs ADD COLUMN source_change_set_id TEXT")
        if "source_span_ids_json" not in fields: c.execute("ALTER TABLE v2_runs ADD COLUMN source_span_ids_json TEXT NOT NULL DEFAULT '[]'")
        c.execute("INSERT INTO schema_migrations VALUES(15,?)",(utcnow(),))

    def _migrate_stage11k_coverage_audit_details(self, c: sqlite3.Connection) -> None:
        """Add readable audit payloads without changing prior audit facts."""
        if c.execute("SELECT 1 FROM schema_migrations WHERE version=16").fetchone(): return
        fields={row["name"] for row in c.execute("PRAGMA table_info(v2_source_coverage_audits)").fetchall()}
        if "actor_user_id" not in fields: c.execute("ALTER TABLE v2_source_coverage_audits ADD COLUMN actor_user_id TEXT")
        if "details_json" not in fields: c.execute("ALTER TABLE v2_source_coverage_audits ADD COLUMN details_json TEXT NOT NULL DEFAULT '{}'")
        c.execute("INSERT INTO schema_migrations VALUES(16,?)",(utcnow(),))

    def _migrate_stage12_run_lifecycle(self, c: sqlite3.Connection) -> None:
        """Add lifecycle lineage without rewriting historic terminal facts."""
        columns={row["name"] for row in c.execute("PRAGMA table_info(v2_runs)").fetchall()}
        additions={
            "started_at":"TEXT",
            "cancel_requested_at":"TEXT",
            "duration_ms":"INTEGER",
            "retry_of_run_id":"TEXT",
            "root_run_id":"TEXT",
            "attempt_number":"INTEGER NOT NULL DEFAULT 1",
            "incremental_batch_id":"TEXT",
        }
        for name,definition in additions.items():
            if name not in columns:c.execute(f"ALTER TABLE v2_runs ADD COLUMN {name} {definition}")
        c.execute("CREATE TABLE IF NOT EXISTS v2_run_events(run_id TEXT NOT NULL REFERENCES v2_runs(id),sequence INTEGER NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,error_code TEXT,created_at TEXT NOT NULL,PRIMARY KEY(run_id,sequence))")
        c.execute("CREATE INDEX IF NOT EXISTS v2_run_events_by_run ON v2_run_events(run_id,sequence)")
        c.execute("UPDATE v2_runs SET root_run_id=id WHERE root_run_id IS NULL")
        c.execute("UPDATE v2_runs SET attempt_number=1 WHERE attempt_number IS NULL OR attempt_number<1")
        c.execute("UPDATE v2_runs SET incremental_batch_id=(SELECT b.id FROM v2_memory_delta_batches b WHERE b.continuity_run_id=v2_runs.id OR b.memory_delta_run_id=v2_runs.id) WHERE incremental_batch_id IS NULL AND source_change_set_id IS NOT NULL")
        c.execute("UPDATE v2_runs SET duration_ms=CAST(MAX(0,(julianday(completed_at)-julianday(started_at))*86400000) AS INTEGER) WHERE duration_ms IS NULL AND started_at IS NOT NULL AND completed_at IS NOT NULL")
        for run in c.execute("SELECT * FROM v2_runs WHERE NOT EXISTS(SELECT 1 FROM v2_run_events e WHERE e.run_id=v2_runs.id)").fetchall():
            status=public_run_status(run["status"]); stage=status if run["status"]=="budget_paused" else run["stage"]
            c.execute("INSERT INTO v2_run_events VALUES(?,?,?,?,?,?)",(run["id"],1,status,stage,public_run_error(run["status"],run["error_code"]),run["completed_at"] or run["created_at"]))
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(17,?)",(utcnow(),))

    @staticmethod
    def _normalize(value: str) -> str:
        return normalize_memory_value(value)

    @classmethod
    def _candidate_key(cls, memory_type: str, subject: str, predicate: str, *, allow_legacy_alias: bool = True) -> tuple[str, str, str]:
        return (cls._normalize(memory_type), cls._normalize(subject), normalized_predicate(predicate, allow_legacy_alias=allow_legacy_alias))

    @staticmethod
    def _is_controlled_candidate(memory_type: str, predicate: str, *, allow_legacy_alias: bool = True) -> bool:
        return is_controlled_candidate(memory_type, predicate, allow_legacy_alias=allow_legacy_alias)

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
        c.execute("INSERT INTO v2_users(id,account_name,display_name,password_hash,created_at) VALUES(?,?,?,?,?)", (user_id, "v1-migration", "V1 local migration", _password(secrets.token_urlsafe(24)), utcnow()))
        project_id = new_id("prj")
        stamp = utcnow()
        c.execute("INSERT INTO v2_projects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (project_id,user_id,legacy["title"],"",legacy["summary"],"active",1,"v1_migrated",None,stamp,stamp,int(legacy["current_memory_version"]),1))
        chapters = c.execute("SELECT * FROM chapters WHERE project_id=? ORDER BY chapter_number", (legacy["id"],)).fetchall()
        chapter_ids: dict[str, str] = {}
        span_ids: dict[str, str] = {}
        for chapter in chapters:
            chapter_id = new_id("ch")
            chapter_ids[chapter["id"]] = chapter_id
            c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?,?)", (chapter_id,project_id,chapter["chapter_number"],chapter["title"],chapter["summary"],"",1))
            c.execute("INSERT INTO v2_outline_nodes VALUES(?,?,?,?,?,?)", (new_id("outline"),project_id,chapter["chapter_number"],chapter["title"],chapter["summary"],"complete"))
            for span in c.execute("SELECT * FROM source_spans WHERE chapter_id=?", (chapter["id"],)).fetchall():
                span_id=new_id("span"); span_ids[span["id"]]=span_id
                c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?,?)", (span_id,project_id,chapter_id,span["label"],span["body"],1))
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
            c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,input_tokens,output_tokens,latency_ms,cost_cny,error_code,retryable,created_at,completed_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id,project_id,draft_id,run["source_revision"],run["status"],run["stage"],run["provider_label"],run["input_tokens"],run["output_tokens"],run["latency_ms"],run["cost_cny"],run["error_code"],run["retryable"],run["created_at"],run["completed_at"],"legacy_unspecified","legacy_unspecified","legacy_unspecified","legacy_unspecified",int(legacy["current_memory_version"]),"provider"))
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
                    source_revision = c.execute("SELECT r.source_revision FROM v2_issues i JOIN v2_runs r ON r.id=i.run_id WHERE i.id=? AND i.project_id=?", (issue_id,project_id)).fetchone()[0]
                    c.execute("INSERT INTO v2_evidence(id,project_id,issue_id,chapter_id,span_id,excerpt,relation,sufficiency,related_memory_ids_json,source_revision) VALUES(?,?,?,?,?,?,?,?,?,?)", (new_id("evidence"),project_id,issue_id,chapter_id,span_id,evidence["excerpt"],evidence["relation"],evidence["sufficiency"],json.dumps(related),source_revision))
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
                    c.execute("INSERT INTO v2_change_set_items(id,project_id,change_set_id,operation,before_json,after_json,source_ids_json,decision_ids_json,review_status,committed_after_json) VALUES(?,?,?,?,?,?,?,?,?,?)", (new_id("changeitem"),project_id,change_set_id,item["operation"],_rewrite_memory_identity(item["before_json"],memory_ids),_rewrite_memory_identity(item["after_json"],memory_ids),json.dumps(sources),json.dumps(decisions),review,None))
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

    @staticmethod
    def _append_run_event(c: sqlite3.Connection, run_id: str, status: str, stage: str, error_code: str | None, stamp: str) -> None:
        sequence=c.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM v2_run_events WHERE run_id=?",(run_id,)).fetchone()[0]
        c.execute("INSERT INTO v2_run_events(run_id,sequence,status,stage,error_code,created_at) VALUES(?,?,?,?,?,?)",(run_id,sequence,public_run_status(status),stage,public_run_error(status,error_code),stamp))
        c.execute("INSERT OR IGNORE INTO v2_run_stages(run_id,stage,created_at) VALUES(?,?,?)",(run_id,stage,stamp))

    @staticmethod
    def _normalized_terminal(result: dict[str, Any]) -> tuple[str, str, str | None]:
        original=str(result.get("status") or "failed")
        status=public_run_status(original)
        if status not in RUN_TERMINAL_STATUSES:status="failed"
        error=public_run_error(original,result.get("error_code"))
        if status=="failed" and not error:error="internal_run_error"
        return status,status,error

    @staticmethod
    def _cancel_active_row(c: sqlite3.Connection, run: sqlite3.Row, stamp: str) -> dict[str, Any]:
        if run["status"]=="queued":
            duration=elapsed_ms(run["started_at"] or run["created_at"],stamp)
            changed=c.execute("UPDATE v2_runs SET status='cancelled',stage='cancelled',cancel_requested_at=COALESCE(cancel_requested_at,?),completed_at=?,duration_ms=?,error_code='author_cancelled',retryable=1 WHERE id=? AND status='queued'",(stamp,stamp,duration,run["id"])).rowcount
            if changed:V2Database._append_run_event(c,run["id"],"cancelled","cancelled","author_cancelled",stamp)
            return {"run_id":run["id"],"status":"cancelled","stage":"cancelled"}
        changed=c.execute("UPDATE v2_runs SET stage='cancelling',cancel_requested_at=COALESCE(cancel_requested_at,?),error_code='author_cancelled',retryable=1 WHERE id=? AND status='running' AND stage!='cancelling'",(stamp,run["id"])).rowcount
        if changed:V2Database._append_run_event(c,run["id"],"running","cancelling","author_cancelled",stamp)
        return {"run_id":run["id"],"status":"running","stage":"cancelling"}

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
        c.execute("INSERT INTO v2_projects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (project_id,user_id,title,genre,summary,"active",1,origin,seed_key,stamp,stamp,version,1))
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
        old_chapter_to_new: dict[str, str] = {}
        for chapter_old, number, title, summary, source_items in CHAPTERS:
            chapter_id = new_id("ch")
            old_chapter_to_new[chapter_old] = chapter_id
            c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?,?)", (chapter_id,project_id,number,title,summary,"",1))
            c.execute("INSERT INTO v2_outline_nodes VALUES(?,?,?,?,?,?)", (new_id("outline"),project_id,number,title,summary,"complete"))
            for old_span_id, label, body in source_items:
                span_id = new_id("span")
                old_span_to_new[old_span_id] = span_id
                c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?,?)", (span_id,project_id,chapter_id,label,body,1))
        draft_id = new_id("draft")
        checksum = digest(DRAFT["body"])
        c.execute("INSERT INTO v2_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (draft_id,project_id,11,DRAFT["title"],DRAFT["body"],1,"saved",stamp,None,None,checksum))
        c.execute("INSERT INTO v2_draft_revisions VALUES(?,?,?,?,?,?,?,?)", (draft_id,1,DRAFT["title"],DRAFT["body"],checksum,None,None,stamp))
        c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)", (project_id,4,"current",None,stamp))
        old_memory_to_new: dict[str, str] = {}
        for old_memory_id, memory_type, subject, predicate, value, old_span_id in MEMORY_RECORDS:
            memory_id = new_id("mem")
            old_memory_to_new[old_memory_id] = memory_id
            c.execute("INSERT INTO v2_memory_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (memory_id,project_id,4,memory_type,subject,predicate,value,old_span_to_new[old_span_id],"author_confirmed",1,None,None))
        c.execute("INSERT INTO v2_characters VALUES(?,?,?,?,?,?,?,?,?,?)", (new_id("char"),project_id,"温岚","ally","灰港档案员","核对潮表","保管罗盘","不知道廊桥钥匙的含义","[]","[]"))
        c.execute("INSERT INTO v2_world_entries VALUES(?,?,?,?,?,?,?)", (new_id("world"),project_id,"location","灰港","雾钟与北潮闸所在的港口","[]","[]"))
        self._seed_grey_harbor_review(c, project_id, draft_id, old_span_to_new, old_memory_to_new)

    def _seed_grey_harbor_review(self, c: sqlite3.Connection, project_id: str, draft_id: str, span_ids: dict[str, str], memory_ids: dict[str, str]) -> None:
        """Create a reviewable preset without executing or impersonating a Provider."""
        stamp = utcnow()
        run_id = scoped_seed_id("run", project_id, "grey-harbor-review-v1")
        c.execute(
            "INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,input_tokens,output_tokens,latency_ms,cost_cny,error_code,retryable,created_at,completed_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,started_at,duration_ms,root_run_id,attempt_number) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id,project_id,draft_id,1,"completed","completed","not_called",None,None,None,None,None,0,stamp,stamp,"not_applicable","demo-preset-v1","demo-review-v1","demo-preset-v1",4,"demo_preset",stamp,0,run_id,1),
        )
        c.execute("INSERT INTO v2_run_stages(run_id,stage,created_at) VALUES(?,?,?)", (run_id,"completed",stamp))
        c.execute("INSERT INTO v2_run_events(run_id,sequence,status,stage,error_code,created_at) VALUES(?,?,?,?,?,?)", (run_id,1,"completed","completed",None,stamp))
        for ordinal, fixture in enumerate(DEMO_REVIEW_ISSUES, 1):
            claim_id = scoped_seed_id("claim", project_id, f"grey-harbor-claim-{ordinal}")
            issue_id = scoped_seed_id("issue", project_id, f"grey-harbor-issue-{ordinal}")
            span_id = span_ids[fixture["evidence_span_id"]]
            chapter_id = c.execute("SELECT chapter_id FROM v2_source_spans WHERE id=? AND project_id=?", (span_id,project_id)).fetchone()[0]
            related_memory_id = memory_ids[fixture["related_memory_id"]]
            proposed = fixture["proposed_memory_change"]
            if proposed:
                proposed = dict(proposed)
                if proposed.get("affected_memory_id"):
                    proposed["affected_memory_id"] = memory_ids[proposed["affected_memory_id"]]
            c.execute("INSERT INTO v2_run_claims(id,run_id,ordinal,text) VALUES(?,?,?,?)", (claim_id,run_id,ordinal,fixture["claim_text"]))
            c.execute("INSERT INTO v2_retrieval_traces(run_id,claim_id,terms,returned_span_ids_json,method_version) VALUES(?,?,?,?,?)", (run_id,claim_id,"demo preset",json.dumps([span_id]),"demo-preset-v1"))
            c.execute("INSERT INTO v2_issues(id,project_id,run_id,claim_span_id,status,classification,category,severity,evidence_status,explanation,proposed_change_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (issue_id,project_id,run_id,claim_id,"open","conflict",fixture["category"],fixture["severity"],"sufficient",fixture["explanation"],json.dumps(proposed,ensure_ascii=False) if proposed else None))
            excerpt = c.execute("SELECT body FROM v2_source_spans WHERE id=? AND project_id=?", (span_id,project_id)).fetchone()[0]
            c.execute("INSERT INTO v2_evidence(id,project_id,issue_id,chapter_id,span_id,excerpt,relation,sufficiency,related_memory_ids_json,source_revision) VALUES(?,?,?,?,?,?,?,?,?,?)", (scoped_seed_id("evidence",project_id,f"grey-harbor-evidence-{ordinal}"),project_id,issue_id,chapter_id,span_id,excerpt,"contradicts","sufficient",json.dumps([related_memory_id]),1))

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
            c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?,?)", (chapter_id,project_id,number,title,body,body,1))
            c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?,?)", (span_id,project_id,chapter_id,label,body,1))
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
            c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?,?)", (chapter_id,project_id,number,chapter["title"],body[:180],body,1))
            c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?,?)", (span_id,project_id,chapter_id,"导入章节",body,1))
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
                if payload.get("recovery_email_hash") and c.execute("SELECT 1 FROM v2_users WHERE recovery_email_hash=?", (payload["recovery_email_hash"],)).fetchone():
                    raise DomainError("recovery_email_unavailable", 409)
                user_id = new_id("usr")
                c.execute(
                    "INSERT INTO v2_users(id,account_name,display_name,password_hash,created_at,recovery_email_hash,recovery_email_masked) VALUES(?,?,?,?,?,?,?)",
                    (user_id,account_name,display_name,_password(password),utcnow(),payload.get("recovery_email_hash"),payload.get("recovery_email_masked")),
                )
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
            data, status, created = self._idem(c, f"register:{account_name}", "register", key, payload, create, 201, with_created=True)
            if "_token" not in data.get("session", {}):
                token, expires_at = self._new_session(c, data["user"]["id"])
                data["session"] = {"expires_at":expires_at,"_token":token}
            data["_registration_created"] = created
            return data, status

    def finalize_registration_replay(self, account_name: str, key: str, data: dict[str, Any], status: int) -> None:
        scope = f"register:{_account(account_name)}"
        persisted = json.loads(json.dumps({name:value for name,value in data.items() if name not in {"_registration_created"}}, ensure_ascii=False))
        if isinstance(persisted.get("session"), dict):
            persisted["session"] = {name:value for name,value in persisted["session"].items() if name != "_token"}
        with self.connection() as c:
            changed = c.execute(
                "UPDATE v2_idempotency SET response_json=?,status_code=? WHERE scope=? AND operation='register' AND idempotency_key=?",
                (json.dumps(persisted, ensure_ascii=False), status, scope, key),
            ).rowcount
            if changed != 1:
                raise DomainError("registration_failed", 503, True)

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
            stamp=utcnow()
            row = c.execute("SELECT u.id,u.account_name,u.display_name,s.expires_at FROM v2_sessions s JOIN v2_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND (u.account_type!='visitor' OR u.visitor_expires_at>?)", (hashlib.sha256(raw_token.encode()).hexdigest(),stamp,stamp)).fetchone()
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
                completed_check = c.execute("SELECT 1 FROM v2_runs WHERE project_id=? AND status='completed' LIMIT 1", (project["id"],)).fetchone()
                continuity_status = "pending" if issue_count else "checked_clear" if completed_check else "unchecked"
                recent.append({"project_id":project["id"],"title":project["title"],"status":project["status"],"updated_at":project["updated_at"]})
                levels={level:c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open' AND severity=?",(project["id"],level)).fetchone()[0] for level in ("high","medium","low")}
                pending.append({"project_id":project["id"],"title":project["title"],"open_count":issue_count,"continuity_status":continuity_status,**levels})
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
                completed_check = c.execute("SELECT 1 FROM v2_runs WHERE project_id=? AND status='completed' LIMIT 1", (project["id"],)).fetchone()
                if has_open_issues is not None and bool(open_count) != has_open_issues:
                    continue
                result.append({"id":project["id"],"seed_key":project["seed_key"],"title":project["title"],"genre":project["genre"],"summary":project["summary"],"status":project["status"],"metadata_revision":project["metadata_revision"],"data_origin":project["data_origin"],"chapter_count":c.execute("SELECT COUNT(*) FROM v2_chapters WHERE project_id=?",(project["id"],)).fetchone()[0],"current_memory_version":project["current_memory_version"],"current_draft":dict(draft) if draft else None,"open_issue_count":open_count,"continuity_status":("pending" if open_count else "checked_clear" if completed_check else "unchecked"),"updated_at":project["updated_at"]})
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
            draft = c.execute("SELECT id,chapter_number,revision,status FROM v2_drafts WHERE project_id=? AND status IN ('draft','saved') ORDER BY saved_at DESC LIMIT 1", (project_id,)).fetchone()
            run = c.execute("SELECT id,status,created_at,result_origin FROM v2_runs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (project_id,)).fetchone()
            open_count=c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open'",(project_id,)).fetchone()[0]
            return {"id":project["id"],"title":project["title"],"genre":project["genre"],"summary":project["summary"],"status":project["status"],"metadata_revision":project["metadata_revision"],"chapter_count":c.execute("SELECT COUNT(*) FROM v2_chapters WHERE project_id=?",(project_id,)).fetchone()[0],"outline_progress":0,"current_memory_version":project["current_memory_version"],"source_revision":project["source_revision"],"current_draft":dict(draft) if draft else None,"latest_run":({"run_id":run["id"],"status":run["status"],"created_at":run["created_at"],"result_origin":run["result_origin"]} if run else None),"open_issue_count":open_count,"continuity_status":("pending" if open_count else "checked_clear" if run and run["status"]=="completed" else "unchecked"),"updated_at":project["updated_at"],"data_origin":project["data_origin"],"memory_initialization_status":self._memory_initialization_status(c,project_id,project["data_origin"]) }

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
                item={"id":chapter["id"],"number":chapter["chapter_number"],"title":chapter["title"],"summary":chapter["summary"],"source_revision":chapter["source_revision"]}
                if include_excerpt:
                    item["source_spans"]=[{"span_id":x["id"],"label":x["label"],"source_revision":x["source_revision"],"text_excerpt":x["body"][:500]} for x in c.execute("SELECT * FROM v2_source_spans WHERE project_id=? AND chapter_id=?",(project_id,chapter["id"])).fetchall()]
                result.append(item)
            return {"project_id":project_id,"chapters":result}

    def source_revision_spans(self, user_id: str, project_id: str, source_revision: int) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            rows=c.execute("SELECT s.id,s.chapter_id,s.label,s.body,ch.chapter_number,ch.title FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id WHERE s.project_id=? AND s.source_revision=? ORDER BY ch.chapter_number,s.id",(project_id,source_revision)).fetchall()
            return {"project_id":project_id,"source_revision":source_revision,"source_spans":[{"id":row["id"],"chapter_id":row["chapter_id"],"chapter_number":row["chapter_number"],"chapter_title":row["title"],"label":row["label"],"text_excerpt":row["body"][:500]} for row in rows]}

    def memory(self, user_id: str, project_id: str, version: int | None) -> dict[str, Any]:
        with self.connection() as c:
            project=self._project(c,user_id,project_id); version=version or project["current_memory_version"]
            if not c.execute("SELECT 1 FROM v2_memory_versions WHERE project_id=? AND version=?",(project_id,version)).fetchone(): raise DomainError("resource_not_found",404)
            records=[]
            rows=c.execute("SELECT m.*,s.chapter_id,s.id span_id,s.body excerpt,ch.chapter_number,ch.title chapter_title FROM v2_memory_records m LEFT JOIN v2_source_spans s ON s.id=m.source_span_id AND s.project_id=m.project_id LEFT JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=m.project_id WHERE m.project_id=? AND m.version=?",(project_id,version)).fetchall()
            for row in rows:
                if row["source_span_id"] and not row["span_id"]: raise DomainError("source_unavailable",422)
                records.append({"id":row["id"],"memory_type":row["memory_type"],"subject":row["subject"],"predicate":row["predicate"],"value":row["value"],"valid_from":row["valid_from"],"valid_to":row["valid_to"],"review_status":row["review_status"],"source":({"chapter_id":row["chapter_id"],"chapter_number":row["chapter_number"],"chapter_title":row["chapter_title"],"span_id":row["span_id"],"excerpt":row["excerpt"][:500],"source_path":f"/projects/{project_id}/sources#span-{row['span_id']}"} if row["span_id"] else None)})
            return {"project_id":project_id,"memory_version":version,"records":records}

    # --- imported-source Story Memory initialization ---
    def _import_sources(self, c: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
        # Initialization is an immutable r1 snapshot. Later append-only spans
        # belong to Stage 11K delta review and must not invalidate V1 Evidence.
        rows=c.execute("SELECT s.id,s.project_id,s.chapter_id,s.label,s.body,ch.chapter_number,ch.title chapter_title FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id WHERE s.project_id=? AND s.source_revision=1 ORDER BY ch.chapter_number,s.id",(project_id,)).fetchall()
        return [{"id":row["id"],"chapter_id":row["chapter_id"],"chapter_number":row["chapter_number"],"chapter_title":row["chapter_title"],"label":row["label"],"body":row["body"]} for row in rows]

    def _source_snapshot_digest(self, sources: list[dict[str, Any]]) -> str:
        return digest([{key:item[key] for key in ("id","chapter_id","chapter_number","chapter_title","label","body")} for item in sources])

    def _memory_initialization_status(self, c: sqlite3.Connection, project_id: str, origin: str | None = None) -> str:
        if origin is not None and origin != "user_import": return "not_required"
        record_count=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=1",(project_id,)).fetchone()[0]
        if record_count:return "completed"
        initialized=c.execute("SELECT status FROM v2_memory_initializations WHERE project_id=? AND source_revision=1",(project_id,)).fetchone()
        return "in_review" if initialized and initialized["status"]=="draft" else "required"

    def _memory_coverage(self, c: sqlite3.Connection, project_id: str) -> dict[str, Any]:
        project=c.execute("SELECT data_origin,current_memory_version FROM v2_projects WHERE id=?",(project_id,)).fetchone()
        delta=c.execute("SELECT * FROM v2_memory_delta_batches WHERE project_id=? AND source_revision=(SELECT source_revision FROM v2_projects WHERE id=?)",(project_id,project_id)).fetchone()
        if delta:
            rows=c.execute("SELECT review_priority,decision_status FROM v2_memory_delta_candidates WHERE batch_id=? AND project_id=?",(delta["id"],project_id)).fetchall()
            core_pending=sum(row["review_priority"]=="core" and row["decision_status"]=="pending" for row in rows)
            supporting_pending=sum(row["review_priority"]=="supporting" and row["decision_status"]=="pending" for row in rows)
            confirmed_core=sum(row["review_priority"]=="core" and row["decision_status"] in {"accepted","edited"} for row in rows)
            confirmed=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed'",(project_id,project["current_memory_version"])).fetchone()[0]
            if delta["status"] != "covered":
                return {"project_id":project_id,"status":"update_pending","source_revision":delta["source_revision"],"memory_version":project["current_memory_version"],"counts":{"core_pending":core_pending,"supporting_pending":supporting_pending,"confirmed":confirmed,"confirmed_core":confirmed_core,"pending_canon_count":0},"blocking_reason":delta["error_code"] or "delta_core_review_required"}
            return {"project_id":project_id,"status":"ready_partial" if supporting_pending else "ready_current","source_revision":delta["source_revision"],"memory_version":project["current_memory_version"],"counts":{"core_pending":0,"supporting_pending":supporting_pending,"confirmed":confirmed,"confirmed_core":confirmed_core,"pending_canon_count":0},"blocking_reason":"none"}
        if c.execute("SELECT source_revision FROM v2_projects WHERE id=?",(project_id,)).fetchone()[0] > 1:
            return {"project_id":project_id,"status":"update_pending","source_revision":c.execute("SELECT source_revision FROM v2_projects WHERE id=?",(project_id,)).fetchone()[0],"memory_version":project["current_memory_version"],"counts":{"core_pending":0,"supporting_pending":0,"confirmed":0,"confirmed_core":0,"pending_canon_count":0},"blocking_reason":"delta_review_required"}
        initialization=c.execute("SELECT * FROM v2_memory_initializations WHERE project_id=? AND source_revision=1",(project_id,)).fetchone()
        if not initialization:
            confirmed=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed'",(project_id,project["current_memory_version"])).fetchone()[0]
            if confirmed:
                return {"project_id":project_id,"status":"ready_current","source_revision":1,"memory_version":project["current_memory_version"],"counts":{"core_pending":0,"supporting_pending":0,"confirmed":confirmed,"confirmed_core":confirmed,"pending_canon_count":0},"blocking_reason":"none"}
            return {"project_id":project_id,"status":"required","source_revision":1,"memory_version":project["current_memory_version"],"counts":{"core_pending":0,"supporting_pending":0,"confirmed":0,"confirmed_core":0,"pending_canon_count":0},"blocking_reason":"core_review_required"}
        rows=c.execute("SELECT review_priority,decision_status,decision_json FROM v2_memory_candidates WHERE initialization_id=? AND project_id=?",(initialization["id"],project_id)).fetchall()
        core=[row for row in rows if row["review_priority"]=="core"]
        core_pending=sum(row["decision_status"]=="pending" for row in core)
        supporting_pending=sum(row["decision_status"]=="pending" for row in rows if row["review_priority"]=="supporting")
        confirmed_core=sum(row["decision_status"] in {"accepted","edited"} for row in core)
        confirmed=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=1 AND review_status='author_confirmed'",(project_id,)).fetchone()[0]
        if core_pending or not core or confirmed_core == 0:
            status,reason="in_review",("core_review_required" if core_pending or not core else "no_confirmed_core")
        elif initialization["status"] != "committed":
            status,reason="in_review","core_review_required"
        elif supporting_pending:
            status,reason="ready_partial","none"
        else:
            status,reason="ready_current","none"
        return {"project_id":project_id,"status":status,"source_revision":initialization["source_revision"],"memory_version":project["current_memory_version"],"counts":{"core_pending":core_pending,"supporting_pending":supporting_pending,"confirmed":confirmed,"confirmed_core":confirmed_core,"pending_canon_count":0},"blocking_reason":reason}

    def memory_coverage(self, user_id: str, project_id: str) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            return self._memory_coverage(c,project_id)

    def _initialization_view(self, c: sqlite3.Connection, project_id: str, initialization: sqlite3.Row | None = None) -> dict[str, Any]:
        initialization=initialization or c.execute("SELECT * FROM v2_memory_initializations WHERE project_id=? AND source_revision=1",(project_id,)).fetchone()
        if not initialization:return {"project_id":project_id,"status":"required","source_revision":1,"candidates":[]}
        sources=self._import_sources(c,project_id)
        if initialization["source_snapshot_digest"] != self._source_snapshot_digest(sources): raise DomainError("evidence_unresolvable",422)
        source_by_id={item["id"]:item for item in sources}
        candidates=[]
        rows=c.execute("SELECT * FROM v2_memory_candidates WHERE initialization_id=? AND project_id=? ORDER BY candidate_ordinal,id",(initialization["id"],project_id)).fetchall()
        for candidate in rows:
            source=source_by_id.get(candidate["source_span_id"])
            if not source or source["chapter_id"]!=candidate["chapter_id"] or candidate["source_revision"]!=initialization["source_revision"]:raise DomainError("evidence_unresolvable",422)
            decision=json.loads(candidate["decision_json"]) if candidate["decision_json"] else None
            candidates.append({"id":candidate["id"],"memory_type":candidate["memory_type"],"subject":candidate["subject"],"predicate":candidate["predicate"],"value":candidate["value"],"candidate_origin":candidate["candidate_origin"],"review_priority":candidate["review_priority"],"decision_status":candidate["decision_status"],"decision":decision,"source_revision":candidate["source_revision"],"source":{"chapter_id":source["chapter_id"],"chapter_number":source["chapter_number"],"chapter_title":source["chapter_title"],"span_id":source["id"],"label":source["label"],"excerpt":source["body"][:500],"text":source["body"],"source_path":f"/projects/{project_id}/sources#span-{source['id']}"}})
        return {"id":initialization["id"],"project_id":project_id,"status":initialization["status"],"source_revision":initialization["source_revision"],"provider_label":initialization["provider_label"],"error_code":initialization["error_code"],"created_at":initialization["created_at"],"completed_at":initialization["completed_at"],"candidates":candidates,"coverage":self._memory_coverage(c,project_id)}

    def _initialization_summary(self, initialization: sqlite3.Row) -> dict[str, Any]:
        """Bounded write acknowledgement; full Evidence remains on the GET view."""
        return {field:initialization[field] for field in ("id","project_id","status","source_revision","created_at","completed_at")}

    def _assert_initialization_sources_current(self, c: sqlite3.Connection, project_id: str, initialization: sqlite3.Row) -> None:
        sources=self._import_sources(c,project_id)
        if initialization["source_snapshot_digest"] != self._source_snapshot_digest(sources):
            raise DomainError("evidence_unresolvable",422)

    def memory_initialization(self, user_id: str, project_id: str) -> dict[str, Any]:
        with self.connection() as c:
            project=self._project(c,user_id,project_id)
            if project["data_origin"]!="user_import": raise DomainError("memory_initialization_not_available",409)
            return self._initialization_view(c,project_id)

    def memory_initialization_input(self, user_id: str, project_id: str, source_revision: int) -> dict[str, Any] | None:
        with self.connection() as c:
            project=self._project(c,user_id,project_id,True)
            if project["data_origin"]!="user_import": raise DomainError("memory_initialization_not_available",409)
            if source_revision!=1: raise DomainError("source_revision_not_current",409)
            existing=c.execute("SELECT * FROM v2_memory_initializations WHERE project_id=? AND source_revision=?",(project_id,source_revision)).fetchone()
            if existing:return None
            if c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=1",(project_id,)).fetchone()[0]: raise DomainError("memory_initialization_conflict",409)
            sources=self._import_sources(c,project_id)
            if not sources: raise DomainError("insufficient_project_context",422)
            return {"project_id":project_id,"source_revision":source_revision,"sources":sources,"source_snapshot_digest":self._source_snapshot_digest(sources)}

    def complete_memory_initialization(self, user_id: str, project_id: str, input_data: dict[str, Any], result: dict[str, Any], provenance: dict[str, str], key: str):
        payload={"source_revision":input_data["source_revision"],"candidate_digest":digest(result["candidates"])}
        with self.connection() as c:
            def complete():
                project=self._project(c,user_id,project_id,True)
                if project["data_origin"]!="user_import": raise DomainError("memory_initialization_not_available",409)
                existing=c.execute("SELECT * FROM v2_memory_initializations WHERE project_id=? AND source_revision=?",(project_id,input_data["source_revision"])).fetchone()
                if existing:return {"initialization":self._initialization_summary(existing)}
                if c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=1",(project_id,)).fetchone()[0]: raise DomainError("memory_initialization_conflict",409)
                current_sources=self._import_sources(c,project_id)
                if input_data["source_snapshot_digest"] != self._source_snapshot_digest(current_sources): raise DomainError("source_revision_not_current",409)
                available={item["id"]:item for item in current_sources}
                initialization_id,stamp=new_id("memoryinit"),utcnow()
                c.execute("INSERT INTO v2_memory_initializations(id,project_id,source_revision,source_snapshot_digest,status,provider_label,model_label,prompt_version,schema_version,error_code,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(initialization_id,project_id,input_data["source_revision"],input_data["source_snapshot_digest"],"draft",provenance["provider_label"],provenance["model_label"],provenance["prompt_version"],provenance["schema_version"],None,stamp,None))
                seen: set[tuple[str,str,str]]=set()
                for ordinal,item in enumerate(result["candidates"],start=1):
                    source=available.get(item["source_span_id"])
                    if not source or source["chapter_id"]!=item["chapter_id"]:raise DomainError("evidence_unresolvable",422)
                    candidate_key=self._candidate_key(item["memory_type"],item["subject"],item["predicate"],allow_legacy_alias=False)
                    controlled=self._is_controlled_candidate(item["memory_type"],item["predicate"],allow_legacy_alias=False)
                    priority="core" if controlled and candidate_key not in seen else "supporting"
                    if controlled: seen.add(candidate_key)
                    c.execute("INSERT INTO v2_memory_candidates(id,project_id,initialization_id,source_revision,candidate_ordinal,memory_type,subject,predicate,value,chapter_id,source_span_id,candidate_origin,review_priority,decision_status,decision_json,decided_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(new_id("memorycandidate"),project_id,initialization_id,input_data["source_revision"],ordinal,item["memory_type"],item["subject"],item["predicate"],item["value"],item["chapter_id"],item["source_span_id"],"initialization",priority,"pending",None,None))
                c.execute("UPDATE v2_projects SET updated_at=? WHERE id=?",(stamp,project_id))
                created=c.execute("SELECT * FROM v2_memory_initializations WHERE id=? AND project_id=?",(initialization_id,project_id)).fetchone()
                return {"initialization":self._initialization_summary(created)}
            return self._idem(c,user_id,"memory_initialization:"+project_id,key,payload,complete,201)

    def decide_memory_candidate(self, user_id: str, project_id: str, initialization_id: str, candidate_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def decide():
                project=self._project(c,user_id,project_id,True)
                initialization=c.execute("SELECT * FROM v2_memory_initializations WHERE id=? AND project_id=?",(initialization_id,project_id)).fetchone()
                candidate=c.execute("SELECT * FROM v2_memory_candidates WHERE id=? AND initialization_id=? AND project_id=?",(candidate_id,initialization_id,project_id)).fetchone()
                if not initialization or not candidate: raise DomainError("resource_not_found",404)
                if initialization["status"]!="draft": raise DomainError("memory_initialization_closed",409)
                self._assert_initialization_sources_current(c,project_id,initialization)
                if candidate["decision_status"]!="pending":
                    saved=json.loads(candidate["decision_json"])
                    same_decision=saved.get("decision")==payload.get("decision")
                    same_edit=(saved.get("decision")!="edited" and payload.get("after") is None and payload.get("evidence_span_id") is None) or (saved.get("decision")=="edited" and digest(saved.get("after"))==digest(payload.get("after")) and saved.get("evidence_span_id")==payload.get("evidence_span_id"))
                    if same_decision and same_edit:return {"candidate_id":candidate_id,"decision_status":candidate["decision_status"]}
                    raise DomainError("candidate_already_decided",409)
                decision=payload.get("decision")
                if decision not in {"accepted","rejected","edited"}: raise DomainError("invalid_candidate_decision",422)
                base={field:candidate[field] for field in ("memory_type","subject","predicate","value")}
                after=base
                evidence_span_id=None
                if decision=="edited":
                    edited=payload.get("after")
                    if not isinstance(edited,dict): raise DomainError("invalid_item_edit",422)
                    after={field:str(edited.get(field," ")).strip() for field in base}
                    if after["memory_type"] not in {"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"} or not all(after.values()) or len(after["subject"])>200 or len(after["predicate"])>200 or len(after["value"])>1000: raise DomainError("invalid_item_edit",422)
                    evidence_span_id=payload.get("evidence_span_id")
                    if not isinstance(evidence_span_id,str) or evidence_span_id!=candidate["source_span_id"]: raise DomainError("evidence_unresolvable",422)
                    evidence=c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=? AND chapter_id=?",(evidence_span_id,project_id,candidate["chapter_id"])).fetchone()
                    if not evidence or candidate["source_revision"]!=initialization["source_revision"]: raise DomainError("evidence_unresolvable",422)
                elif payload.get("after") is not None or payload.get("evidence_span_id") is not None: raise DomainError("invalid_candidate_decision",422)
                saved={"decision":decision,"after":after if decision!="rejected" else None,"evidence_span_id":evidence_span_id}
                stamp=utcnow()
                c.execute("UPDATE v2_memory_candidates SET decision_status=?,decision_json=?,decided_at=? WHERE id=? AND project_id=?",(decision,json.dumps(saved,ensure_ascii=False),stamp,candidate_id,project_id))
                c.execute("INSERT INTO v2_memory_candidate_decisions(id,project_id,initialization_id,candidate_id,decision,after_json,evidence_span_id,source_revision,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(new_id("memorydecision"),project_id,initialization_id,candidate_id,decision,json.dumps(saved["after"],ensure_ascii=False) if saved["after"] else None,evidence_span_id,initialization["source_revision"],stamp))
                return {"candidate_id":candidate_id,"decision_status":decision}
            return self._idem(c,user_id,"memory_candidate_decision:"+project_id+":"+candidate_id,key,payload,decide)

    def commit_memory_initialization(self, user_id: str, project_id: str, initialization_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def commit():
                project=self._project(c,user_id,project_id,True)
                initialization=c.execute("SELECT * FROM v2_memory_initializations WHERE id=? AND project_id=?",(initialization_id,project_id)).fetchone()
                if not initialization: raise DomainError("resource_not_found",404)
                if initialization["status"] in {"committed","rejected"}: return {"initialization":self._initialization_summary(initialization),"memory_version":1,"accepted_candidate_ids":[],"coverage":self._memory_coverage(c,project_id)}
                if initialization["status"]!="draft" or payload.get("confirm") is not True: raise DomainError("confirmation_required",400)
                self._initialization_view(c,project_id,initialization)
                if project["current_memory_version"]!=1 or c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=1",(project_id,)).fetchone()[0]: raise DomainError("memory_initialization_conflict",409)
                candidates=c.execute("SELECT * FROM v2_memory_candidates WHERE initialization_id=? AND project_id=? ORDER BY candidate_ordinal,id",(initialization_id,project_id)).fetchall()
                core=[row for row in candidates if row["review_priority"]=="core"]
                if not core or any(row["decision_status"]=="pending" or not row["decision_json"] for row in core): raise DomainError("unresolved_required_decisions",409)
                confirmed_core=sum(row["decision_status"] in {"accepted","edited"} for row in core)
                if confirmed_core == 0: raise DomainError("insufficient_project_context",422)
                accepted=[]
                for candidate in candidates:
                    if candidate["decision_status"]=="pending": continue
                    saved=json.loads(candidate["decision_json"])
                    if saved["decision"] not in {"accepted","edited","rejected"}: raise DomainError("invalid_candidate_decision",422)
                    if saved["decision"]=="rejected": continue
                    after=saved["after"]
                    source=c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=? AND chapter_id=?",(candidate["source_span_id"],project_id,candidate["chapter_id"])).fetchone()
                    if not source: raise DomainError("evidence_unresolvable",422)
                    c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(new_id("mem"),project_id,1,after["memory_type"],after["subject"],after["predicate"],after["value"],candidate["source_span_id"],"author_confirmed",1,None,None))
                    accepted.append(candidate["id"])
                stamp=utcnow(); status="committed"
                c.execute("UPDATE v2_memory_initializations SET status=?,completed_at=? WHERE id=? AND project_id=?",(status,stamp,initialization_id,project_id))
                c.execute("UPDATE v2_projects SET updated_at=? WHERE id=?",(stamp,project_id))
                committed=c.execute("SELECT * FROM v2_memory_initializations WHERE id=? AND project_id=?",(initialization_id,project_id)).fetchone()
                return {"initialization":self._initialization_summary(committed),"memory_version":1,"accepted_candidate_ids":accepted,"coverage":self._memory_coverage(c,project_id)}
            return self._idem(c,user_id,"memory_initialization_commit:"+project_id+":"+initialization_id,key,payload,commit)

    # --- Stage 11K incremental source revision review ---
    def _delta_sources(self,c,project_id,revision):
        rows=c.execute("SELECT s.id,s.chapter_id,s.label,s.body,ch.chapter_number,ch.title chapter_title FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id WHERE s.project_id=? AND s.source_revision=? ORDER BY ch.chapter_number,s.id",(project_id,revision)).fetchall()
        return [dict(row) for row in rows]

    def _confirmed_memory(self,c,project_id,version):
        return [dict(row) for row in c.execute("SELECT id,memory_type,subject,predicate,value,source_span_id,review_status FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' ORDER BY id",(project_id,version)).fetchall()]

    def _delta_priority(self,item,confirmed):
        if item["memory_type"]=="open_thread" or not self._is_controlled_candidate(item["memory_type"],item["predicate"],allow_legacy_alias=False): return "supporting"
        identity=self._candidate_key(item["memory_type"],item["subject"],item["predicate"],allow_legacy_alias=False)
        prior=[row for row in confirmed if self._candidate_key(row["memory_type"],row["subject"],row["predicate"],allow_legacy_alias=False)==identity]
        return "core" if not prior or any(self._normalize(row["value"])!=self._normalize(item["value"]) for row in prior) else "supporting"

    def _delta_priorities(self,items,confirmed):
        """Classify in deterministic provider order after source validation.

        A second normalized tuple in the same new revision can add no new
        author obligation, even if the tuple is a previously unseen canon key.
        """
        seen=set(); result=[]
        for item in items:
            identity=(self._normalize(item["memory_type"]),self._normalize(item["subject"]),normalized_predicate(item["predicate"],allow_legacy_alias=False),self._normalize(item["value"]))
            duplicate=identity in seen
            priority="supporting" if duplicate else self._delta_priority(item,confirmed)
            seen.add(identity); result.append(priority)
        return result

    def _coverage_audit_view(self,c,project_id,row):
        return {"id":row["id"],"project_id":project_id,"source_revision":row["source_revision"],"status":row["status"],"memory_version":row["memory_version"],"delta_batch_id":row["delta_batch_id"],"actor_user_id":row["actor_user_id"],"details":json.loads(row["details_json"] or "{}"),"created_at":row["created_at"]}

    def _delta_view(self,c,project_id,batch):
        sources={row["id"]:row for row in self._delta_sources(c,project_id,batch["source_revision"])}; items=[]
        for row in c.execute("SELECT * FROM v2_memory_delta_candidates WHERE batch_id=? AND project_id=? ORDER BY candidate_ordinal,id",(batch["id"],project_id)).fetchall():
            source=sources.get(row["source_span_id"])
            if not source or source["chapter_id"]!=row["chapter_id"]: raise DomainError("evidence_unresolvable",422)
            items.append({"id":row["id"],"memory_type":row["memory_type"],"subject":row["subject"],"predicate":row["predicate"],"value":row["value"],"candidate_origin":"delta","review_priority":row["review_priority"],"decision_status":row["decision_status"],"decision":json.loads(row["decision_json"]) if row["decision_json"] else None,"source_revision":row["source_revision"],"source":{"chapter_id":source["chapter_id"],"chapter_number":source["chapter_number"],"chapter_title":source["chapter_title"],"span_id":source["id"],"label":source["label"],"excerpt":source["body"][:500],"source_path":f"/projects/{project_id}/sources#span-{source['id']}"}})
        audit=c.execute("SELECT * FROM v2_source_coverage_audits WHERE project_id=? AND delta_batch_id=?",(project_id,batch["id"])).fetchone()
        return {"id":batch["id"],"project_id":project_id,"source_revision":batch["source_revision"],"base_memory_version":batch["base_memory_version"],"status":batch["status"],"error_code":batch["error_code"],"continuity_run_id":batch["continuity_run_id"],"memory_delta_run_id":batch["memory_delta_run_id"],"candidates":items,"coverage":self._memory_coverage(c,project_id),"coverage_audit":self._coverage_audit_view(c,project_id,audit) if audit else None}

    def memory_delta(self,user_id,project_id):
        with self.connection() as c:
            self._project(c,user_id,project_id); batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE project_id=? ORDER BY source_revision DESC LIMIT 1",(project_id,)).fetchone()
            return self._delta_view(c,project_id,batch) if batch else {"project_id":project_id,"status":"not_started","candidates":[],"coverage":self._memory_coverage(c,project_id)}

    def source_coverage_audit(self,user_id,project_id,audit_id):
        with self.connection() as c:
            self._project(c,user_id,project_id); row=c.execute("SELECT * FROM v2_source_coverage_audits WHERE id=? AND project_id=?",(audit_id,project_id)).fetchone()
            if not row: raise DomainError("resource_not_found",404)
            return {"audit":self._coverage_audit_view(c,project_id,row)}

    def create_incremental_runs(self,user_id,project_id,payload,key,continuity_provenance,delta_provenance):
        with self.connection() as c:
            def create():
                project=self._project(c,user_id,project_id,True); revision=payload["source_revision"]
                if revision!=project["source_revision"] or revision<=1: raise DomainError("source_revision_not_current",409)
                if not self._confirmed_memory(c,project_id,project["current_memory_version"]): raise DomainError("insufficient_project_context",422)
                if not self._delta_sources(c,project_id,revision): raise DomainError("source_revision_not_current",409)
                existing=c.execute("SELECT * FROM v2_memory_delta_batches WHERE project_id=? AND source_revision=?",(project_id,revision)).fetchone()
                if existing and existing["status"] not in {"failed","cancelled","timed_out"}: return {"delta":self._delta_view(c,project_id,existing)}
                draft=c.execute("SELECT * FROM v2_drafts WHERE project_id=? AND status IN ('draft','saved') ORDER BY saved_at DESC LIMIT 1",(project_id,)).fetchone()
                if not draft: raise DomainError("draft_invalid",422)
                change=c.execute("SELECT id FROM v2_source_change_sets WHERE project_id=? AND target_source_revision=? AND status='committed' ORDER BY committed_at DESC LIMIT 1",(project_id,revision)).fetchone()
                spans=self._delta_sources(c,project_id,revision)
                if not change or not spans: raise DomainError("source_lineage_not_available",409)
                stamp,batch_id,continuity_id,delta_id=utcnow(),new_id("memorydelta"),new_id("run"),new_id("run")
                prior={}
                if existing:
                    batch_id=existing["id"]
                    prior={row["run_type"]:row for row in c.execute("SELECT * FROM v2_runs WHERE id IN (?,?)",(existing["continuity_run_id"],existing["memory_delta_run_id"])).fetchall()}
                for run_id,kind,prov in ((continuity_id,"continuity",continuity_provenance),(delta_id,"memory_delta",delta_provenance)):
                    previous=prior.get(kind); root=(previous["root_run_id"] or previous["id"]) if previous else run_id; attempt=(previous["attempt_number"]+1) if previous else 1
                    c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,run_type,source_change_set_id,source_span_ids_json,retry_of_run_id,root_run_id,attempt_number,incremental_batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,project_id,draft["id"],revision,"queued","queued",prov["provider_label"],stamp,prov["model_label"],prov["prompt_version"],prov["schema_version"],prov["retrieval_method_version"],project["current_memory_version"],"provider",kind,change["id"],json.dumps([row["id"] for row in spans]),previous["id"] if previous else None,root,attempt,batch_id)); self._append_run_event(c,run_id,"queued","queued",None,stamp)
                if existing:
                    c.execute("UPDATE v2_memory_delta_batches SET base_memory_version=?,continuity_run_id=?,memory_delta_run_id=?,status='processing',error_code=NULL,created_at=?,completed_at=NULL,covered_at=NULL WHERE id=?",(project["current_memory_version"],continuity_id,delta_id,stamp,batch_id))
                else: c.execute("INSERT INTO v2_memory_delta_batches VALUES(?,?,?,?,?,?,?,?,?,?,?)",(batch_id,project_id,revision,project["current_memory_version"],continuity_id,delta_id,"processing",None,stamp,None,None))
                return {"delta":self._delta_view(c,project_id,c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=?",(batch_id,)).fetchone()),"continuity_run_id":continuity_id,"memory_delta_run_id":delta_id,"batch_id":batch_id}
            return self._idem(c,user_id,"incremental_runs:"+project_id,key,payload,create,202,with_created=True)

    def incremental_inputs(self,project_id,batch_id):
        with self.connection() as c:
            batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=? AND project_id=?",(batch_id,project_id)).fetchone()
            if not batch: raise DomainError("resource_not_found",404)
            sources=self._delta_sources(c,project_id,batch["source_revision"]); memory=self._confirmed_memory(c,project_id,batch["base_memory_version"])
            historical={row["id"]:dict(row) for row in c.execute("SELECT s.id,s.chapter_id,s.label,s.body,ch.chapter_number,ch.title chapter_title FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id WHERE s.project_id=? AND s.id IN (SELECT source_span_id FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND source_span_id IS NOT NULL)",(project_id,project_id,batch["base_memory_version"])).fetchall()}
            claims=[]; allowed=sorted(historical.values(),key=lambda row:(row["chapter_number"],row["id"]))
            for source in sources:
                for text in (part.strip() for part in re.split(r"(?<=[。！？])",source["body"])):
                    if text: claims.append({"id":f"claim-{batch['continuity_run_id']}-{len(claims)+1}","text":text,"allowed_evidence":allowed})
            if not claims or not memory: raise DomainError("insufficient_project_context",422)
            return {"claims":claims,"memory":memory,"draft":{"id":batch["continuity_run_id"],"revision":batch["source_revision"],"body":"\n".join(x["text"] for x in claims)}},{"source_revision":batch["source_revision"],"sources":sources,"memory":memory}

    def advance_incremental_runs(self,project_id,batch_id,stage):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=? AND project_id=?",(batch_id,project_id)).fetchone()
            if not batch:raise DomainError("resource_not_found",404)
            runs=c.execute("SELECT * FROM v2_runs WHERE id IN (?,?) ORDER BY run_type",(batch["continuity_run_id"],batch["memory_delta_run_id"])).fetchall()
            if len(runs)!=2:return False
            stamp=utcnow()
            if batch["status"]=="cancelled" or any(run["cancel_requested_at"] or run["status"]=="cancelled" for run in runs):
                for run in runs:
                    if run["status"] in RUN_ACTIVE_STATUSES:
                        duration=elapsed_ms(run["started_at"] or run["created_at"],stamp)
                        if c.execute("UPDATE v2_runs SET status='cancelled',stage='cancelled',completed_at=?,duration_ms=?,error_code='author_cancelled',retryable=1,cancel_requested_at=COALESCE(cancel_requested_at,?) WHERE id=? AND status IN ('queued','running')",(stamp,duration,stamp,run["id"])).rowcount:self._append_run_event(c,run["id"],"cancelled","cancelled","author_cancelled",stamp)
                c.execute("UPDATE v2_memory_delta_batches SET status='cancelled',error_code='author_cancelled',completed_at=COALESCE(completed_at,?) WHERE id=?",(stamp,batch_id))
                return False
            if any(run["status"] not in RUN_ACTIVE_STATUSES for run in runs):return False
            for run in runs:
                if run["status"]=="running" and run["stage"]==stage:continue
                if c.execute("UPDATE v2_runs SET status='running',stage=?,started_at=COALESCE(started_at,?) WHERE id=? AND status IN ('queued','running') AND cancel_requested_at IS NULL",(stage,stamp,run["id"])).rowcount:self._append_run_event(c,run["id"],"running",stage,None,stamp)
            return True

    def finish_incremental_runs(self,project_id,batch_id,continuity,delta):
        prepared=None
        if continuity["status"]=="completed" and delta["status"]=="completed":
            # Do not open a second SQLite connection inside the write
            # transaction below.  Failure here is handled by execute_incremental
            # as a terminal failed pair, before any result rows exist.
            inputs,delta_input=self.incremental_inputs(project_id,batch_id)
            sources=[]
            for item in delta["candidates"]:
                source=next((x for x in delta_input["sources"] if x["id"]==item["source_span_id"] and x["chapter_id"]==item["chapter_id"]),None)
                if not source: raise DomainError("evidence_unresolvable",422)
                sources.append(source)
            prepared=(inputs,sources,self._delta_priorities(delta["candidates"],delta_input["memory"]))
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=? AND project_id=?",(batch_id,project_id)).fetchone()
            if not batch: raise DomainError("resource_not_found",404)
            run_rows={row["id"]:row for row in c.execute("SELECT * FROM v2_runs WHERE id IN (?,?)",(batch["continuity_run_id"],batch["memory_delta_run_id"])).fetchall()}
            if len(run_rows)!=2:return False
            stamp=utcnow(); cancelled=batch["status"]=="cancelled" or any(row["cancel_requested_at"] or row["status"]=="cancelled" for row in run_rows.values())
            if cancelled:
                group_status,group_error="cancelled","author_cancelled"
            elif continuity["status"]=="completed" and delta["status"]=="completed":
                group_status,group_error="completed",None
            elif continuity.get("status")=="timed_out" or delta.get("status")=="timed_out":
                group_status,group_error="timed_out",continuity.get("error_code") or delta.get("error_code") or "provider_timeout"
            else:
                group_status="failed"; group_error=public_run_error(str(continuity.get("status")),continuity.get("error_code")) or public_run_error(str(delta.get("status")),delta.get("error_code")) or "incremental_run_failed"
            changed=0
            for run_id,result in ((batch["continuity_run_id"],continuity),(batch["memory_delta_run_id"],delta)):
                run=run_rows[run_id]
                if run["status"] not in RUN_ACTIVE_STATUSES:continue
                duration=elapsed_ms(run["started_at"] or run["created_at"],stamp)
                metrics=result if not cancelled else result
                changed+=c.execute("UPDATE v2_runs SET status=?,stage=?,input_tokens=?,output_tokens=?,latency_ms=?,cost_cny=?,error_code=?,retryable=?,completed_at=?,duration_ms=? WHERE id=? AND status IN ('queued','running')",(group_status,group_status,metrics.get("input_tokens"),metrics.get("output_tokens"),metrics.get("latency_ms"),metrics.get("cost_cny"),group_error,int(group_status!="completed"),stamp,duration,run_id)).rowcount
                self._append_run_event(c,run_id,group_status,group_status,group_error,stamp)
            if group_status!="completed":
                batch_status="cancelled" if group_status=="cancelled" else "failed"
                c.execute("UPDATE v2_memory_delta_batches SET status=?,error_code=?,completed_at=? WHERE id=?",(batch_status,group_error,stamp,batch_id)); return bool(changed)
            if changed!=2:return False
            inputs,sources,priorities=prepared
            trace_rows=continuity.get("retrieval_traces",[]); trace_by_claim={row.get("claim_id"):row.get("returned_span_ids") for row in trace_rows if isinstance(row,dict)}
            method=continuity.get("retrieval_method_version")
            if method!="bounded-lexical-v4-longform":raise DomainError("retrieval_trace_invalid",422)
            for ordinal,claim in enumerate(inputs["claims"],1):
                returned=trace_by_claim.get(claim["id"]); allowed_ids={item["id"] for item in claim["allowed_evidence"]}
                if not isinstance(returned,list) or len(returned)!=len(set(returned)) or len(returned)>3 or not set(returned)<=allowed_ids:raise DomainError("retrieval_trace_invalid",422)
                c.execute("INSERT INTO v2_run_claims VALUES(?,?,?,?)",(claim["id"],batch["continuity_run_id"],ordinal,claim["text"])); c.execute("INSERT INTO v2_retrieval_traces VALUES(?,?,?,?,?)",(batch["continuity_run_id"],claim["id"],"bounded_lexical",json.dumps(returned),method))
            for issue in continuity.get("issues",[]):
                issue_id=new_id("issue"); c.execute("INSERT INTO v2_issues(id,project_id,run_id,claim_span_id,status,classification,category,severity,evidence_status,explanation,proposed_change_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(issue_id,project_id,batch["continuity_run_id"],issue["claim_span_id"],"open",issue["status"],issue["category"],issue["severity"],issue["evidence_status"],issue["explanation"],json.dumps(issue.get("proposed_memory_change")) if issue.get("proposed_memory_change") else None))
                for evidence in issue["evidence"]: c.execute("INSERT INTO v2_evidence(id,project_id,issue_id,chapter_id,span_id,excerpt,relation,sufficiency,related_memory_ids_json,source_revision) VALUES(?,?,?,?,?,?,?,?,?,?)",(new_id("evidence"),project_id,issue_id,evidence["chapter_id"],evidence["span_id"],evidence["excerpt"],evidence["relation"],evidence["sufficiency"],json.dumps(evidence["related_memory_ids"]),batch["source_revision"]))
            for ordinal,(item,source,priority) in enumerate(zip(delta["candidates"],sources,priorities),1):
                c.execute("INSERT INTO v2_memory_delta_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(new_id("memorydeltacandidate"),project_id,batch_id,batch["source_revision"],ordinal,item["memory_type"],item["subject"],item["predicate"],item["value"],source["chapter_id"],source["id"],"delta",priority,"pending",None,None))
            c.execute("UPDATE v2_memory_delta_batches SET status='in_review',completed_at=? WHERE id=?",(stamp,batch_id))
            return True

    def decide_memory_delta_candidate(self,user_id,project_id,batch_id,candidate_id,payload,key):
        with self.connection() as c:
            def decide():
                self._project(c,user_id,project_id,True); batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=? AND project_id=?",(batch_id,project_id)).fetchone(); row=c.execute("SELECT * FROM v2_memory_delta_candidates WHERE id=? AND batch_id=? AND project_id=?",(candidate_id,batch_id,project_id)).fetchone()
                if not batch or not row: raise DomainError("resource_not_found",404)
                if batch["status"]!="in_review": raise DomainError("memory_delta_closed",409)
                if row["decision_status"]!="pending": raise DomainError("candidate_already_decided",409)
                decision=payload.get("decision"); base={key:row[key] for key in ("memory_type","subject","predicate","value")}; after=base; evidence=None
                if decision not in {"accepted","rejected","edited"}: raise DomainError("invalid_candidate_decision",422)
                if decision=="edited":
                    edit=payload.get("after") or {}; after={name:str(edit.get(name," ")).strip() for name in base}; evidence=payload.get("evidence_span_id")
                    if after["memory_type"] not in {"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"} or not all(after.values()) or evidence!=row["source_span_id"]: raise DomainError("invalid_item_edit",422)
                elif payload.get("after") is not None or payload.get("evidence_span_id") is not None: raise DomainError("invalid_candidate_decision",422)
                if not c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=? AND source_revision=?",(row["source_span_id"],project_id,batch["source_revision"])).fetchone(): raise DomainError("evidence_unresolvable",422)
                saved={"decision":decision,"after":after if decision!="rejected" else None,"evidence_span_id":evidence}; stamp=utcnow()
                c.execute("UPDATE v2_memory_delta_candidates SET decision_status=?,decision_json=?,decided_at=? WHERE id=?",(decision,json.dumps(saved,ensure_ascii=False),stamp,candidate_id)); c.execute("INSERT INTO v2_memory_delta_decisions VALUES(?,?,?,?,?,?,?,?,?)",(new_id("memorydeltadecision"),project_id,batch_id,candidate_id,decision,json.dumps(saved["after"],ensure_ascii=False) if saved["after"] else None,evidence,batch["source_revision"],stamp))
                return {"candidate_id":candidate_id,"decision_status":decision,"delta":self._delta_view(c,project_id,batch)}
            return self._idem(c,user_id,"memory_delta_decision:"+project_id+":"+candidate_id,key,payload,decide)

    def commit_memory_delta(self,user_id,project_id,batch_id,payload,key):
        with self.connection() as c:
            def commit():
                project=self._project(c,user_id,project_id,True); batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=? AND project_id=?",(batch_id,project_id)).fetchone()
                if not batch: raise DomainError("resource_not_found",404)
                if batch["status"]=="covered":
                    audit=c.execute("SELECT * FROM v2_source_coverage_audits WHERE project_id=? AND delta_batch_id=?",(project_id,batch_id)).fetchone()
                    return {"delta":self._delta_view(c,project_id,batch),"memory_version":project["current_memory_version"],"coverage_audit":self._coverage_audit_view(c,project_id,audit) if audit else None}
                if batch["status"]!="in_review" or payload.get("confirm") is not True or project["source_revision"]!=batch["source_revision"]: raise DomainError("confirmation_required",400)
                rows=c.execute("SELECT * FROM v2_memory_delta_candidates WHERE batch_id=? AND project_id=? ORDER BY candidate_ordinal",(batch_id,project_id)).fetchall(); core=[row for row in rows if row["review_priority"]=="core"]
                if not core or any(row["decision_status"]=="pending" for row in core): raise DomainError("unresolved_required_decisions",409)
                confirmed_core=[row for row in core if row["decision_status"] in {"accepted","edited"}]; accepted=[row for row in rows if row["decision_status"] in {"accepted","edited"}]; stamp=utcnow()
                audit_details={"candidate_ids":[row["id"] for row in rows],"decisions":[{"candidate_id":row["id"],"decision":row["decision_status"],"after":json.loads(row["decision_json"])["after"] if row["decision_json"] else None,"evidence_span_id":json.loads(row["decision_json"] or "{}").get("evidence_span_id") or row["source_span_id"]} for row in rows],"source_revision":batch["source_revision"]}
                audit_id=new_id("sourcecoverage")
                if not confirmed_core:
                    c.execute("INSERT INTO v2_source_coverage_audits(id,project_id,source_revision,status,memory_version,delta_batch_id,actor_user_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(audit_id,project_id,batch["source_revision"],"covered_without_memory_change",project["current_memory_version"],batch_id,user_id,json.dumps(audit_details,ensure_ascii=False),stamp)); c.execute("UPDATE v2_memory_delta_batches SET status='covered',covered_at=? WHERE id=?",(stamp,batch_id)); audit=c.execute("SELECT * FROM v2_source_coverage_audits WHERE id=?",(audit_id,)).fetchone(); return {"delta":self._delta_view(c,project_id,batch),"memory_version":project["current_memory_version"],"status":"covered_without_memory_change","coverage_audit":self._coverage_audit_view(c,project_id,audit)}
                target=project["current_memory_version"]+1; c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)",(project_id,target,"current",project["current_memory_version"],stamp)); c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) SELECT id||'-v'||?,project_id,?,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id FROM v2_memory_records WHERE project_id=? AND version=?",(target,target,project_id,project["current_memory_version"]))
                for row in accepted:
                    after=json.loads(row["decision_json"])["after"]
                    if not c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=? AND source_revision=?",(row["source_span_id"],project_id,batch["source_revision"])).fetchone(): raise DomainError("evidence_unresolvable",422)
                    identity=self._candidate_key(after["memory_type"],after["subject"],after["predicate"],allow_legacy_alias=False); old=next((item for item in c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=?",(project_id,target)).fetchall() if self._candidate_key(item["memory_type"],item["subject"],item["predicate"],allow_legacy_alias=False)==identity),None)
                    if old: c.execute("UPDATE v2_memory_records SET value=?,source_span_id=?,review_status='author_confirmed' WHERE id=?",(after["value"],row["source_span_id"],old["id"]))
                    else: c.execute("INSERT INTO v2_memory_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(new_id("mem"),project_id,target,after["memory_type"],after["subject"],after["predicate"],after["value"],row["source_span_id"],"author_confirmed",None,None,None))
                c.execute("UPDATE v2_memory_versions SET status='superseded' WHERE project_id=? AND version=?",(project_id,project["current_memory_version"])); c.execute("UPDATE v2_projects SET current_memory_version=?,updated_at=? WHERE id=?",(target,stamp,project_id)); c.execute("INSERT INTO v2_source_coverage_audits(id,project_id,source_revision,status,memory_version,delta_batch_id,actor_user_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(audit_id,project_id,batch["source_revision"],"covered_with_memory_change",target,batch_id,user_id,json.dumps(audit_details,ensure_ascii=False),stamp)); c.execute("UPDATE v2_memory_delta_batches SET status='covered',covered_at=? WHERE id=?",(stamp,batch_id)); audit=c.execute("SELECT * FROM v2_source_coverage_audits WHERE id=?",(audit_id,)).fetchone()
                return {"delta":self._delta_view(c,project_id,batch),"memory_version":target,"status":"covered_with_memory_change","coverage_audit":self._coverage_audit_view(c,project_id,audit)}
            return self._idem(c,user_id,"memory_delta_commit:"+project_id+":"+batch_id,key,payload,commit)

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
            coverage=self._memory_coverage(c,project_id)
            if coverage["status"] not in {"ready_partial","ready_current"} or coverage["counts"]["confirmed_core"] < 1:
                raise DomainError("insufficient_project_context",422)
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
                coverage=self._memory_coverage(c,project_id)
                if coverage["status"] not in {"ready_partial","ready_current"} or coverage["counts"]["confirmed_core"] < 1:
                    raise DomainError("insufficient_project_context",422)
                context=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=?",(project_id,project["current_memory_version"])).fetchone()[0]
                if not context: raise DomainError("insufficient_project_context",422)
                running=c.execute("SELECT id FROM v2_runs WHERE project_id=? AND draft_id=? AND source_revision=? AND status IN ('queued','running')",(project_id,draft["id"],draft["revision"])).fetchone()
                if running: raise DomainError("run_already_active",409,False,{"run_id":running["id"]})
                run_id,stamp=new_id("run"),utcnow()
                c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,root_run_id,attempt_number) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,project_id,draft["id"],draft["revision"],"queued","queued",provenance["provider_label"],stamp,provenance["model_label"],provenance["prompt_version"],provenance["schema_version"],provenance["retrieval_method_version"],project["current_memory_version"],"provider",run_id,1))
                self._append_run_event(c,run_id,"queued","queued",None,stamp)
                return {"run_id":run_id,"project_id":project_id,"run_type":"continuity","status":"queued","source_revision":draft["revision"],"stage":"queued","result_origin":"provider","result_origin_label":"Provider 检查结果","retry_of_run_id":None,"root_run_id":run_id,"attempt_number":1,"created_at":stamp}
            return self._idem(c,user_id,"create_check:"+project_id,key,payload,create,202,with_created=True)

    def advance_run(self, project_id: str, run_id: str, stage: str) -> bool:
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not run: raise DomainError("resource_not_found",404)
            if run["status"] not in RUN_ACTIVE_STATUSES:return False
            stamp=utcnow()
            if run["cancel_requested_at"]:
                duration=elapsed_ms(run["started_at"] or run["created_at"],stamp)
                changed=c.execute("UPDATE v2_runs SET status='cancelled',stage='cancelled',completed_at=?,duration_ms=?,error_code='author_cancelled',retryable=1 WHERE id=? AND status IN ('queued','running')",(stamp,duration,run_id)).rowcount
                if changed:self._append_run_event(c,run_id,"cancelled","cancelled","author_cancelled",stamp)
                return False
            if run["status"]=="running" and run["stage"]==stage:return True
            changed=c.execute("UPDATE v2_runs SET status='running',stage=?,started_at=COALESCE(started_at,?) WHERE id=? AND project_id=? AND status IN ('queued','running') AND cancel_requested_at IS NULL",(stage,stamp,run_id,project_id)).rowcount
            if changed:self._append_run_event(c,run_id,"running",stage,None,stamp)
            return bool(changed)

    def session_budget_exhausted(self, project_id: str, limit: int = 40000) -> bool:
        with self.connection() as c:
            used=c.execute("SELECT COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0) FROM v2_runs WHERE project_id=?",(project_id,)).fetchone()[0]
            return used>=limit

    @staticmethod
    def _bounded_excerpt(body: str, terms: set[str], limit: int = 720) -> str:
        """Keep prompt evidence local to the first deterministic lexical hit."""
        if len(body) <= limit:
            return body
        positions = [body.find(term) for term in sorted(terms) if body.find(term) >= 0]
        center = min(positions) if positions else 0
        start = max(0, min(center - limit // 3, len(body) - limit))
        excerpt = body[start:start + limit]
        return ("…" if start else "") + excerpt + ("…" if start + limit < len(body) else "")

    def run_input(self, project_id: str, run_id: str) -> dict[str, Any]:
        with self.connection() as c:
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not run: raise DomainError("resource_not_found",404)
            if run["status"] not in RUN_ACTIVE_STATUSES or run["cancel_requested_at"]: raise DomainError("run_cancelled",409)
            coverage=self._memory_coverage(c,project_id)
            if coverage["status"] not in {"ready_partial","ready_current"} or coverage["counts"]["pending_canon_count"] != 0:
                raise DomainError("insufficient_project_context",422)
            revision=c.execute("SELECT * FROM v2_draft_revisions WHERE draft_id=? AND revision=?",(run["draft_id"],run["source_revision"])).fetchone()
            claims=[]
            for ordinal,text in enumerate(x.strip() for x in re.split(r"(?<=[。！？])",revision["body"]) if x.strip()):
                claim_id=f"claim-{run_id}-{ordinal+1}"; claims.append({"id":claim_id,"text":text})
                c.execute("INSERT OR IGNORE INTO v2_run_claims VALUES(?,?,?,?)",(claim_id,run_id,ordinal+1,text))
            memory=[dict(x) for x in c.execute("SELECT id,memory_type,subject,predicate,value,source_span_id FROM v2_memory_records WHERE project_id=? AND version=(SELECT current_memory_version FROM v2_projects WHERE id=?) AND review_status='author_confirmed' ORDER BY id",(project_id,project_id)).fetchall()]
            if not memory: raise DomainError("insufficient_project_context",422)
            spans=[dict(x) for x in c.execute("SELECT id,chapter_id,body,label FROM v2_source_spans WHERE project_id=?",(project_id,)).fetchall()]
            for claim in claims:
                characters="".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]",claim["text"])); terms={characters[index:index+2] for index in range(max(0,len(characters)-1))}; scored=[]
                for span in spans:
                    score=sum(term in span["body"] for term in terms)
                    score+=sum(2 for record in memory if record["source_span_id"]==span["id"] and any(term in (record["subject"]+record["value"]) for term in terms))
                    if score: scored.append((score,span))
                hits=[{**pair[1],"prompt_excerpt":self._bounded_excerpt(pair[1]["body"],terms)} for pair in sorted(scored,key=lambda pair:(-pair[0],pair[1]["id"]))[:5]]
                c.execute("INSERT OR REPLACE INTO v2_retrieval_traces VALUES(?,?,?,?,?)",(run_id,claim["id"],",".join(sorted(terms))[:200],json.dumps([hit["id"] for hit in hits]),run["retrieval_method_version"] or "legacy_unspecified"))
                claim["allowed_evidence"]=hits
            return {"run":dict(run),"draft":{"id":revision["draft_id"],"revision":revision["revision"],"body":revision["body"]},"claims":claims,"memory":memory}

    def finish_run(self, project_id: str, run_id: str, result: dict[str, Any]) -> bool:
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not run: raise DomainError("resource_not_found",404)
            if run["status"] not in RUN_ACTIVE_STATUSES:return False
            stamp=utcnow()
            if run["cancel_requested_at"]:
                status,terminal,error="cancelled","cancelled","author_cancelled"
                retryable=True
            else:
                status,terminal,error=self._normalized_terminal(result)
                retryable=bool(result.get("retryable")) or status in {"timed_out","cancelled"}
            duration=elapsed_ms(run["started_at"] or (run["created_at"] if run["status"]=="queued" else None),stamp)
            changed=c.execute("UPDATE v2_runs SET status=?,stage=?,input_tokens=?,output_tokens=?,latency_ms=?,cost_cny=?,error_code=?,retryable=?,completed_at=?,duration_ms=? WHERE id=? AND project_id=? AND status IN ('queued','running')",(status,terminal,result.get("input_tokens"),result.get("output_tokens"),result.get("latency_ms"),result.get("cost_cny"),error,int(retryable),stamp,duration,run_id,project_id)).rowcount
            if not changed:return False
            self._append_run_event(c,run_id,status,terminal,error,stamp)
            if status!="completed": return True
            for issue in result.get("issues",[]):
                issue_id=new_id("issue")
                c.execute("INSERT INTO v2_issues(id,project_id,run_id,claim_span_id,status,classification,category,severity,evidence_status,explanation,proposed_change_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(issue_id,project_id,run_id,issue["claim_span_id"],"open",issue["status"],issue["category"],issue["severity"],issue["evidence_status"],issue["explanation"],json.dumps(issue.get("proposed_memory_change")) if issue.get("proposed_memory_change") else None))
                for evidence in issue["evidence"]:
                    c.execute("INSERT INTO v2_evidence(id,project_id,issue_id,chapter_id,span_id,excerpt,relation,sufficiency,related_memory_ids_json,source_revision) VALUES(?,?,?,?,?,?,?,?,?,?)",(new_id("evidence"),project_id,issue_id,evidence["chapter_id"],evidence["span_id"],evidence["excerpt"],evidence["relation"],evidence["sufficiency"],json.dumps(evidence["related_memory_ids"]),run["source_revision"]))
            return True

    def cancel_run(self,user_id,project_id,run_id,payload,key):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def cancel():
                self._project(c,user_id,project_id,True)
                target=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
                if not target:raise DomainError("resource_not_found",404)
                if public_run_status(target["status"]) in RUN_TERMINAL_STATUSES:raise DomainError("run_cancel_terminal",409)
                rows=[target]
                if target["incremental_batch_id"]:
                    rows=c.execute("SELECT * FROM v2_runs WHERE project_id=? AND incremental_batch_id=? AND attempt_number=? ORDER BY run_type",(project_id,target["incremental_batch_id"],target["attempt_number"])).fetchall()
                    if len(rows)!=2:raise DomainError("internal_run_error",409)
                stamp=utcnow(); outputs=[]
                for row in rows:
                    if row["status"] in RUN_ACTIVE_STATUSES:outputs.append(self._cancel_active_row(c,row,stamp))
                if target["incremental_batch_id"]:
                    c.execute("UPDATE v2_memory_delta_batches SET status='cancelled',error_code='author_cancelled',completed_at=COALESCE(completed_at,?) WHERE id=? AND project_id=?",(stamp,target["incremental_batch_id"],project_id))
                current=next((item for item in outputs if item["run_id"]==run_id),{"run_id":run_id,"status":"running","stage":"cancelling"})
                return {**current,"cancel_requested_at":target["cancel_requested_at"] or stamp,"sibling_run_ids":[item["run_id"] for item in outputs if item["run_id"]!=run_id]}
            return self._idem(c,user_id,"cancel_run:"+project_id+":"+run_id,key,payload,cancel)

    def _retry_copy(self,c,previous,batch_id=None):
        run_id,stamp=new_id("run"),utcnow(); root=previous["root_run_id"] or previous["id"]
        attempt=c.execute("SELECT COALESCE(MAX(attempt_number),0)+1 FROM v2_runs WHERE root_run_id=?",(root,)).fetchone()[0]
        c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,run_type,source_change_set_id,source_span_ids_json,retry_of_run_id,root_run_id,attempt_number,incremental_batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,previous["project_id"],previous["draft_id"],previous["source_revision"],"queued","queued",previous["provider_label"],stamp,previous["model_label"],previous["prompt_version"],previous["schema_version"],previous["retrieval_method_version"],previous["source_memory_version"],previous["result_origin"],previous["run_type"],previous["source_change_set_id"],previous["source_span_ids_json"],previous["id"],root,attempt,batch_id))
        self._append_run_event(c,run_id,"queued","queued",None,stamp)
        return {"run_id":run_id,"run_type":previous["run_type"],"status":"queued","stage":"queued","created_at":stamp,"retry_of_run_id":previous["id"],"root_run_id":root,"attempt_number":attempt}

    def retry_run(self,user_id,project_id,run_id,payload,key):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def retry():
                project=self._project(c,user_id,project_id,True)
                target=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
                if not target:raise DomainError("resource_not_found",404)
                status=public_run_status(target["status"])
                allowed=(status in {"timed_out","cancelled"}) or (status=="failed" and bool(target["retryable"]))
                if not allowed:raise DomainError("run_retry_not_allowed",409)
                if target["result_origin"]!="provider":raise DomainError("run_retry_not_allowed",409)
                if target["incremental_batch_id"]:
                    batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=? AND project_id=?",(target["incremental_batch_id"],project_id)).fetchone()
                    if not batch or run_id not in {batch["continuity_run_id"],batch["memory_delta_run_id"]}:raise DomainError("run_retry_lineage_stale",409)
                    previous=c.execute("SELECT * FROM v2_runs WHERE id IN (?,?) ORDER BY run_type",(batch["continuity_run_id"],batch["memory_delta_run_id"])).fetchall()
                    if len(previous)!=2:raise DomainError("run_retry_lineage_stale",409)
                    if project["source_revision"]!=target["source_revision"] or project["current_memory_version"]!=batch["base_memory_version"]:raise DomainError("run_retry_lineage_stale",409)
                    change=c.execute("SELECT 1 FROM v2_source_change_sets WHERE id=? AND project_id=? AND target_source_revision=? AND status='committed'",(target["source_change_set_id"],project_id,target["source_revision"])).fetchone()
                    span_ids=json.loads(target["source_span_ids_json"] or "[]")
                    count=c.execute("SELECT COUNT(*) FROM v2_source_spans WHERE project_id=? AND source_revision=? AND id IN (%s)" % ",".join("?" for _ in span_ids),(project_id,target["source_revision"],*span_ids)).fetchone()[0] if span_ids else 0
                    if not change or not span_ids or count!=len(span_ids):raise DomainError("run_retry_lineage_stale",409)
                    roots={row["root_run_id"] or row["id"] for row in previous}
                    if c.execute("SELECT 1 FROM v2_runs WHERE root_run_id IN (%s) AND status IN ('queued','running') LIMIT 1" % ",".join("?" for _ in roots),tuple(roots)).fetchone():raise DomainError("run_already_active",409)
                    created={row["run_type"]:self._retry_copy(c,row,batch["id"]) for row in previous}
                    continuity_id=created["continuity"]["run_id"]; delta_id=created["memory_delta"]["run_id"]
                    c.execute("UPDATE v2_memory_delta_batches SET continuity_run_id=?,memory_delta_run_id=?,status='processing',error_code=NULL,created_at=?,completed_at=NULL,covered_at=NULL WHERE id=?",(continuity_id,delta_id,utcnow(),batch["id"]))
                    return {"paired":True,"batch_id":batch["id"],"continuity_run_id":continuity_id,"memory_delta_run_id":delta_id,"runs":[created["continuity"],created["memory_delta"]]}
                draft=c.execute("SELECT revision FROM v2_drafts WHERE id=? AND project_id=?",(target["draft_id"],project_id)).fetchone()
                if not draft or draft["revision"]!=target["source_revision"] or project["current_memory_version"]!=target["source_memory_version"]:raise DomainError("run_retry_lineage_stale",409)
                root=target["root_run_id"] or target["id"]
                if c.execute("SELECT 1 FROM v2_runs WHERE root_run_id=? AND status IN ('queued','running')",(root,)).fetchone():raise DomainError("run_already_active",409)
                return {"paired":False,"run":self._retry_copy(c,target)}
            return self._idem(c,user_id,"retry_run:"+project_id+":"+run_id,key,payload,retry,202,with_created=True)

    def _resolved_evidence(self, c: sqlite3.Connection, project_id: str, issue: sqlite3.Row, run: sqlite3.Row) -> list[dict[str, Any]]:
        claim = c.execute("SELECT text FROM v2_run_claims WHERE id=? AND run_id=?", (issue["claim_span_id"],run["id"])).fetchone()
        if not claim:
            raise DomainError("evidence_unresolvable",422)
        rows = c.execute(
            "SELECT e.*,s.body source_context,ch.chapter_number,ch.title chapter_title "
            "FROM v2_evidence e "
            "JOIN v2_source_spans s ON s.id=e.span_id AND s.project_id=e.project_id AND s.chapter_id=e.chapter_id "
            "JOIN v2_chapters ch ON ch.id=e.chapter_id AND ch.project_id=e.project_id "
            "WHERE e.project_id=? AND e.issue_id=?",
            (project_id,issue["id"]),
        ).fetchall()
        if issue["classification"] == "conflict" and not rows:
            raise DomainError("evidence_unresolvable",422)
        resolved=[]
        for row in rows:
            if row["source_revision"] != run["source_revision"] or not row["excerpt"] or not row["source_context"]:
                raise DomainError("evidence_unresolvable",422)
            related = json.loads(row["related_memory_ids_json"])
            if not isinstance(related,list) or any(
                not c.execute("SELECT 1 FROM v2_memory_records WHERE id=? AND project_id=? AND version=?", (memory_id,project_id,run["source_memory_version"])).fetchone()
                for memory_id in related
            ):
                raise DomainError("evidence_unresolvable",422)
            resolved.append({
                "id":row["id"],"chapter_id":row["chapter_id"],"chapter_number":row["chapter_number"],"chapter_title":row["chapter_title"],
                "span_id":row["span_id"],"source_revision":row["source_revision"],"excerpt":row["excerpt"],"excerpt_context":row["source_context"][:500],
                "relation":row["relation"],"sufficiency":row["sufficiency"],"related_memory_ids":related,
                "source_path":f"/projects/{project_id}/sources#span-{row['span_id']}",
            })
        return resolved

    def run_view(self, user_id: str, project_id: str, run_id: str, include: set[str]) -> dict[str, Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not run: raise DomainError("resource_not_found",404)
            draft=c.execute("SELECT revision,edit_context_json FROM v2_drafts WHERE id=? AND project_id=?",(run["draft_id"],project_id)).fetchone()
            source_span_ids=json.loads(run["source_span_ids_json"] or "[]")
            incremental=bool(run["source_change_set_id"]) and bool(source_span_ids)
            direct_successor=draft["revision"]==run["source_revision"]+1 and draft["edit_context_json"] and json.loads(draft["edit_context_json"]).get("source_run_id")==run_id
            current=incremental or run["run_type"]!="continuity" or draft["revision"]==run["source_revision"] or direct_successor
            status=public_run_status(run["status"]); stage=status if run["status"]=="budget_paused" else run["stage"]; error_code=public_run_error(run["status"],run["error_code"])
            transitions=[{"sequence":row["sequence"],"status":public_run_status(row["status"]),"stage":row["stage"],"error_code":public_run_error(row["status"],row["error_code"]),"created_at":row["created_at"]} for row in c.execute("SELECT * FROM v2_run_events WHERE run_id=? ORDER BY sequence",(run_id,)).fetchall()]
            provenance={"provider_label":run["provider_label"],"model_label":run["model_label"] or "legacy_unspecified","prompt_version":run["prompt_version"] or "legacy_unspecified","schema_version":run["schema_version"] or "legacy_unspecified","retrieval_method_version":run["retrieval_method_version"] or "legacy_unspecified","source_memory_version":run["source_memory_version"]}
            if incremental:provenance.update({"source_change_set_id":run["source_change_set_id"],"source_span_ids":source_span_ids,"incremental_batch_id":run["incremental_batch_id"]})
            metrics={"latency_ms":run["latency_ms"],"input_tokens":run["input_tokens"],"output_tokens":run["output_tokens"],"cost_cny":run["cost_cny"],"cost_available":run["cost_cny"] is not None,"provenance":provenance,"retrieval":[]}
            result={"run_id":run_id,"project_id":project_id,"run_type":run["run_type"],"status":status,"stage":stage,"source_revision":run["source_revision"],"source_memory_version":run["source_memory_version"],"source_change_set_id":run["source_change_set_id"],"source_span_ids":source_span_ids,"incremental_batch_id":run["incremental_batch_id"],"current_revision":draft["revision"],"is_stale":not current,"superseded":not current,"lineage_status":("incremental_source_revision" if incremental else "validated_direct_successor" if direct_successor else "current" if current else "lineage_invalid_requires_recheck"),"result_origin":run["result_origin"],"result_origin_label":("预置演示审阅数据（未调用 Provider）" if run["result_origin"]=="demo_preset" else "Provider 检查结果"),"error_code":error_code,"retryable":bool(run["retryable"]) or run["status"]=="budget_paused","created_at":run["created_at"],"started_at":run["started_at"],"completed_at":run["completed_at"],"cancel_requested_at":run["cancel_requested_at"],"duration_ms":run["duration_ms"],"retry_of_run_id":run["retry_of_run_id"],"root_run_id":run["root_run_id"] or run_id,"attempt_number":run["attempt_number"] or 1,"transitions":transitions,"provenance":provenance,"provider_metrics":{key:metrics[key] for key in ("latency_ms","input_tokens","output_tokens","cost_cny","cost_available")}}
            if "issues" in include and status=="completed":
                issues=[]
                for issue in c.execute("SELECT * FROM v2_issues WHERE project_id=? AND run_id=?",(project_id,run_id)).fetchall():
                    claim=c.execute("SELECT text FROM v2_run_claims WHERE id=? AND run_id=?",(issue["claim_span_id"],run_id)).fetchone()
                    if not claim: raise DomainError("evidence_unresolvable",422)
                    decision=c.execute("SELECT decision,resulting_revision FROM v2_decisions WHERE project_id=? AND issue_id=? AND source_revision=?",(project_id,issue["id"],run["source_revision"])).fetchone()
                    item={"id":issue["id"],"claim_span_id":issue["claim_span_id"],"claim_text":claim["text"],"status":issue["status"],"classification":issue["classification"],"category":issue["category"],"severity":issue["severity"],"evidence_status":issue["evidence_status"],"explanation":issue["explanation"],"decision":dict(decision) if decision else None}
                    if "evidence" in include:
                        item["evidence"]=self._resolved_evidence(c,project_id,issue,run)
                    issues.append(item)
                result["issues"]=issues
            if "metrics" in include:
                traces=[]
                for trace in c.execute("SELECT claim_id,returned_span_ids_json,method_version FROM v2_retrieval_traces WHERE run_id=? ORDER BY claim_id",(run_id,)).fetchall():
                    claim=c.execute("SELECT ordinal FROM v2_run_claims WHERE id=? AND run_id=?",(trace["claim_id"],run_id)).fetchone()
                    traces.append({"claim_ordinal":claim["ordinal"] if claim else None,"returned_span_ids":json.loads(trace["returned_span_ids_json"]),"method_version":trace["method_version"]})
                result["metrics"]={**metrics,"retrieval":traces}
            return result

    def decide(self, user_id: str, project_id: str, issue_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def decide() -> dict[str, Any]:
                self._project(c,user_id,project_id,True)
                issue=c.execute("SELECT * FROM v2_issues WHERE id=? AND project_id=?",(issue_id,project_id)).fetchone()
                run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(payload["run_id"],project_id)).fetchone()
                if not issue or not run or issue["run_id"]!=run["id"] or payload["source_revision"]!=run["source_revision"]: raise DomainError("resource_not_found",404)
                self._resolved_evidence(c,project_id,issue,run)
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
                        self._resolved_evidence(c,project_id,issue,run)
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
                    c.execute("INSERT INTO v2_change_set_items(id,project_id,change_set_id,operation,before_json,after_json,source_ids_json,decision_ids_json,review_status,committed_after_json) VALUES(?,?,?,?,?,?,?,?,?,?)",(item_id,project_id,change_set_id,after["operation"],json.dumps(before),json.dumps(after),json.dumps([issue["id"],issue["claim_span_id"]]),json.dumps([decision["id"]]),None,None))
                    items.append({"id":item_id,"operation":after["operation"],"before":before,"after":after,"source_ids":[issue["id"],issue["claim_span_id"]],"decision_ids":[decision["id"]],"review_status":None})
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
                edited_rows=payload.get("edited_items",[])
                edited_ids=[row.get("item_id") for row in edited_rows]
                if len(edited_ids)!=len(set(edited_ids)) or not set(edited_ids)<=accepted:
                    raise DomainError("invalid_item_edit",422)
                run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(change_set["run_id"],project_id)).fetchone()
                draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(run["draft_id"],project_id)).fetchone() if run else None
                successor=draft and draft["revision"]==run["source_revision"]+1 and draft["edit_context_json"] and json.loads(draft["edit_context_json"]).get("source_run_id")==run["id"]
                if not run or not draft or run["source_revision"]!=change_set["source_run_revision"] or draft["revision"]!=change_set["resolved_revision"] or not (draft["revision"]==run["source_revision"] or successor):
                    raise DomainError("lineage_invalid_requires_recheck",409)
                edited_by_id={row["item_id"]:row for row in edited_rows}
                committed_after: dict[str, dict[str, Any]] = {}
                for item in items:
                    if item["id"] not in accepted:
                        continue
                    original=json.loads(item["after_json"])
                    edit=edited_by_id.get(item["id"])
                    if edit:
                        values={field:str(edit.get(field,"")).strip() for field in ("memory_type","subject","predicate","value")}
                        if values["memory_type"] not in {"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"} or not all(values.values()) or len(values["subject"])>200 or len(values["predicate"])>200 or len(values["value"])>1000:
                            raise DomainError("invalid_item_edit",422)
                        original={**original,**values}
                    issue_id=json.loads(item["source_ids_json"])[0]
                    issue=c.execute("SELECT * FROM v2_issues WHERE id=? AND project_id=? AND run_id=?",(issue_id,project_id,run["id"])).fetchone()
                    if not issue:
                        raise DomainError("commit_failed",503,True)
                    self._resolved_evidence(c,project_id,issue,run)
                    committed_after[item["id"]]=original
                stamp,audit_id=utcnow(),new_id("commit")
                if not accepted:
                    c.execute("UPDATE v2_change_sets SET status='rejected',committed_at=? WHERE id=?",(stamp,change_set_id))
                    c.execute("UPDATE v2_change_set_items SET review_status='rejected' WHERE project_id=? AND change_set_id=?",(project_id,change_set_id))
                    c.execute("INSERT INTO v2_commit_audits VALUES(?,?,?,?,?,?,?,?)",(audit_id,project_id,change_set_id,"rejected",json.dumps([]),json.dumps(sorted(rejected)),payload.get("note"),stamp))
                    return {"change_set_id":change_set_id,"status":"rejected","memory_version":{"previous":project["current_memory_version"],"current":project["current_memory_version"]},"committed_item_ids":[],"edited_item_ids":[],"rejected_item_ids":sorted(rejected),"audit_id":audit_id}
                target=change_set["target_version"]
                c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)",(project_id,target,"current",project["current_memory_version"],stamp))
                # V5 starts with the complete V4 canon; accepted changes apply after copy.
                c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) SELECT id||'-v'||?,project_id,?,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id FROM v2_memory_records WHERE project_id=? AND version=?",(target,target,project_id,project["current_memory_version"]))
                for item in items:
                    if item["id"] not in accepted: continue
                    after=committed_after[item["id"]]; issue_id=json.loads(item["source_ids_json"])[0]
                    issue=c.execute("SELECT * FROM v2_issues WHERE id=? AND project_id=?",(issue_id,project_id)).fetchone()
                    evidence=self._resolved_evidence(c,project_id,issue,run)[0]
                    if after["operation"]=="replace":
                        before=json.loads(item["before_json"]); record_id=before["id"]+f"-v{target}"
                        if not c.execute("SELECT 1 FROM v2_memory_records WHERE id=? AND project_id=? AND version=?",(record_id,project_id,target)).fetchone(): raise DomainError("commit_failed",503,True)
                        c.execute("UPDATE v2_memory_records SET memory_type=?,subject=?,predicate=?,value=?,source_span_id=?,review_status='author_confirmed' WHERE id=? AND project_id=? AND version=?",(after["memory_type"],after["subject"],after["predicate"],after["value"],evidence["span_id"],record_id,project_id,target))
                    else:
                        c.execute("INSERT INTO v2_memory_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(new_id("mem"),project_id,target,after["memory_type"],after["subject"],after["predicate"],after["value"],evidence["span_id"],"author_confirmed",None,None,None))
                    c.execute("UPDATE v2_change_set_items SET committed_after_json=? WHERE id=? AND project_id=?",(json.dumps(after,ensure_ascii=False),item["id"],project_id))
                c.execute("UPDATE v2_memory_versions SET status='superseded' WHERE project_id=? AND version=?",(project_id,project["current_memory_version"]))
                c.execute("UPDATE v2_projects SET current_memory_version=?,updated_at=? WHERE id=?",(target,stamp,project_id))
                c.execute("UPDATE v2_change_sets SET status='committed',committed_at=? WHERE id=?",(stamp,change_set_id))
                plain_accepted=accepted-set(edited_ids)
                if plain_accepted: c.execute("UPDATE v2_change_set_items SET review_status='accepted' WHERE id IN ("+",".join("?"*len(plain_accepted))+")",tuple(plain_accepted))
                if edited_ids: c.execute("UPDATE v2_change_set_items SET review_status='edited' WHERE id IN ("+",".join("?"*len(edited_ids))+")",tuple(edited_ids))
                if rejected: c.execute("UPDATE v2_change_set_items SET review_status='rejected' WHERE id IN ("+",".join("?"*len(rejected))+")",tuple(rejected))
                c.execute("INSERT INTO v2_commit_audits VALUES(?,?,?,?,?,?,?,?)",(audit_id,project_id,change_set_id,"committed",json.dumps(sorted(accepted)),json.dumps(sorted(rejected)),payload.get("note"),stamp))
                return {"change_set_id":change_set_id,"status":"committed","memory_version":{"previous":project["current_memory_version"],"current":target},"committed_item_ids":sorted(accepted),"edited_item_ids":sorted(edited_ids),"rejected_item_ids":sorted(rejected),"audit_id":audit_id}
            return self._idem(c,user_id,"commit:"+project_id+":"+change_set_id,key,payload,commit)

    # --- reset and imports ---
    def reset(self, user_id: str, project_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def reset() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                if payload.get("confirm") is not True: raise DomainError("confirmation_required",400)
                if payload.get("reason") not in {"fresh_start","demo_recovery"}: raise DomainError("invalid_request",400)
                # dependent children first. The set is deliberately project-scoped.
                c.execute("DELETE FROM v2_memory_candidate_decisions WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_candidates WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_initializations WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_delta_decisions WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_delta_candidates WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_source_coverage_audits WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_delta_batches WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_commit_audits WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_change_set_items WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_change_sets WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_decisions WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_evidence WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_issues WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_retrieval_traces WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_run_claims WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_run_events WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
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

    # --- Stage 11J append-only source revisions ---
    def _source_change_set_view(self, row: sqlite3.Row) -> dict[str, Any]:
        chapters=json.loads(row["chapters_json"])
        return {"id":row["id"],"project_id":row["project_id"],"base_source_revision":row["base_source_revision"],"target_source_revision":row["target_source_revision"],"mode":row["mode"],"input_method":row["input_method"],"content_sha256":row["content_hash"],"status":row["status"],"chapter_count":len(chapters),"source_span_count":len(chapters),"chapters":[{"preview_id":x["id"],"title":x["title"],"order":x["order"],"character_count":len(x["body"])} for x in chapters],"previewed_at":row["created_at"],"committed_at":row["committed_at"],"failed_at":row["failed_at"],"failure_code":row["failure_code"],"expires_at":row["expires_at"],"audit":json.loads(row["content_json"]).get("audit",{})}

    def preview_source_change_set(self, user_id: str, project_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def preview() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                if payload["base_source_revision"]!=project["source_revision"]: raise DomainError("source_revision_conflict",409,False,{"current_source_revision":project["source_revision"]})
                method=payload["input_method"]
                draft_id=draft_revision=draft_checksum=None
                if method=="draft_complete":
                    draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(payload.get("draft_id"),project_id)).fetchone()
                    if not draft or not draft["body"].strip(): raise DomainError("draft_invalid",422)
                    text,title=draft["body"],draft["title"]
                    draft_id,draft_revision,draft_checksum=draft["id"],draft["revision"],draft["checksum"]
                else:
                    text=str(payload.get("content") or "")
                    title=str(payload.get("title") or "").strip()
                    if method=="file" and not str(payload.get("filename") or "").lower().endswith((".md",".txt")): raise DomainError("unsupported_format",415)
                    if not text.strip(): raise DomainError("empty_source",422)
                if len(text.encode("utf-8"))>5*1024*1024: raise DomainError("source_too_large",413)
                chapters,_,_=self._parse_import(text)
                if title and len(chapters)==1: chapters[0]["title"]=title[:120]
                change_id,stamp=new_id("sourcechangeset"),utcnow(); expires=(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(); content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()
                audit={"created_by_user_id":user_id,"idempotency_key_fingerprint":digest(key),"request_fingerprint":digest(payload),"file_basename":(str(payload.get("filename","")).replace("\\","/").split("/")[-1] if method=="file" else None)}
                c.execute("INSERT INTO v2_source_change_sets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(change_id,project_id,user_id,project["source_revision"],project["source_revision"]+1,"append",method,content_hash,json.dumps({"text":text,"audit":audit},ensure_ascii=False),json.dumps(chapters,ensure_ascii=False),"previewed",None,expires,stamp,None,draft_id,draft_revision,draft_checksum,None,None,None))
                c.execute("INSERT INTO v2_source_change_set_audits VALUES(?,?,?,?,?,?)",(new_id("sourceaudit"),project_id,change_id,"previewed",json.dumps(audit,ensure_ascii=False),stamp))
                row=c.execute("SELECT * FROM v2_source_change_sets WHERE id=?",(change_id,)).fetchone()
                return {"source_change_set":self._source_change_set_view(row)}
            return self._idem(c,user_id,"source_change_preview:"+project_id,key,payload,preview,201)

    def commit_source_change_set(self, user_id: str, project_id: str, change_id: str, payload: dict[str, Any], key: str):
        try:
            with self.connection() as c:
                def commit() -> dict[str, Any]:
                    self._project(c,user_id,project_id,True)
                    change=c.execute("SELECT * FROM v2_source_change_sets WHERE id=? AND project_id=? AND user_id=?",(change_id,project_id,user_id)).fetchone()
                    if not change: raise DomainError("source_change_set_not_found",404)
                    if change["status"]=="committed":
                        row=c.execute("SELECT * FROM v2_source_change_sets WHERE id=?",(change_id,)).fetchone(); return json.loads(row["commit_result_json"])
                    project=c.execute("SELECT * FROM v2_projects WHERE id=?",(project_id,)).fetchone()
                    if payload.get("confirm") is not True: raise DomainError("confirmation_required",400)
                    if payload.get("content_sha256")!=change["content_hash"]: raise DomainError("source_hash_mismatch",409)
                    if change["expires_at"]<=utcnow(): raise DomainError("source_change_set_expired",409)
                    if change["base_source_revision"]!=project["source_revision"]: raise DomainError("source_revision_conflict",409,False,{"current_source_revision":project["source_revision"]})
                    content=json.loads(change["content_json"])
                    if hashlib.sha256(content["text"].encode("utf-8")).hexdigest()!=change["content_hash"]: raise DomainError("source_hash_mismatch",409)
                    if change["input_method"]=="draft_complete":
                        draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(change["draft_id"],project_id)).fetchone()
                        if not draft or draft["revision"]!=change["draft_revision"] or draft["checksum"]!=change["draft_checksum"]: raise DomainError("source_draft_stale",409)
                    chapters=json.loads(change["chapters_json"]); start=c.execute("SELECT COALESCE(MAX(chapter_number),0) FROM v2_chapters WHERE project_id=?",(project_id,)).fetchone()[0]
                    for ordinal,item in enumerate(chapters,1):
                        chapter_id,span_id=new_id("chapter"),new_id("span"); number=start+ordinal
                        c.execute("INSERT INTO v2_chapters VALUES(?,?,?,?,?,?,?)",(chapter_id,project_id,number,item["title"],"",item["body"],change["target_source_revision"]))
                        c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?,?)",(span_id,project_id,chapter_id,"append",item["body"],change["target_source_revision"]))
                    c.execute("UPDATE v2_drafts SET status='completed' WHERE project_id=? AND status IN ('draft','saved')",(project_id,))
                    next_draft_id=self._draft(c,project_id,start+len(chapters)+1); stamp=utcnow()
                    c.execute("UPDATE v2_projects SET source_revision=?,updated_at=? WHERE id=?",(change["target_source_revision"],stamp,project_id))
                    commit_audit={"target_source_revision":change["target_source_revision"],"next_draft_id":next_draft_id,"idempotency_key_fingerprint":digest(key),"request_fingerprint":digest(payload)}
                    content["audit"]["commit_idempotency_key_fingerprint"]=commit_audit["idempotency_key_fingerprint"]
                    content["audit"]["commit_request_fingerprint"]=commit_audit["request_fingerprint"]
                    c.execute("UPDATE v2_source_change_sets SET status='committed',committed_at=?,content_json=? WHERE id=?",(stamp,json.dumps(content,ensure_ascii=False),change_id))
                    c.execute("INSERT INTO v2_source_change_set_audits VALUES(?,?,?,?,?,?)",(new_id("sourceaudit"),project_id,change_id,"committed",json.dumps(commit_audit),stamp))
                    row=c.execute("SELECT * FROM v2_source_change_sets WHERE id=?",(change_id,)).fetchone(); draft=c.execute("SELECT * FROM v2_drafts WHERE id=?",(next_draft_id,)).fetchone()
                    result={"source_change_set":self._source_change_set_view(row),"next_draft":{"id":draft["id"],"chapter_number":draft["chapter_number"],"revision":draft["revision"],"title":draft["title"]}}
                    c.execute("UPDATE v2_source_change_sets SET commit_result_json=? WHERE id=?",(json.dumps(result,ensure_ascii=False),change_id))
                    return result
                return self._idem(c,user_id,"source_change_commit:"+project_id+":"+change_id,key,payload,commit,200)
        except DomainError as error:
            # A rejected commit never writes a Chapter, Span, Revision, or Draft.  It may
            # still leave a project-scoped audit marker so a later preview/recovery is traceable.
            with self.connection() as c:
                change=c.execute("SELECT id FROM v2_source_change_sets WHERE id=? AND project_id=? AND user_id=?",(change_id,project_id,user_id)).fetchone()
                if change:
                    stamp=utcnow()
                    c.execute("UPDATE v2_source_change_sets SET failed_at=?,failure_code=? WHERE id=?",(stamp,error.code,change_id))
                    c.execute("INSERT INTO v2_source_change_set_audits VALUES(?,?,?,?,?,?)",(new_id("sourceaudit"),project_id,change_id,"failed",json.dumps({"failure_code":error.code,"idempotency_key_fingerprint":digest(key),"request_fingerprint":digest(payload)}),stamp))
            raise

    def counts(self) -> dict[str, int]:
        self.initialize()
        with self.connection() as c:
            return {table:c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("v2_users","v2_projects","v2_runs")}
