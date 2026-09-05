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
import unicodedata
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
FORESHADOW_STATUSES = {"planned", "planted", "developing", "resolved", "abandoned"}
FORESHADOW_MAX_RECORDS = 200
REVISION_PLAN_MAX_ISSUES = 8
REVISION_TASK_MAX_RECORDS = 200
REVISION_TASK_PRIORITIES = {"high", "medium", "low"}
REVISION_TASK_STATUSES = {"todo", "in_progress", "completed"}
MAX_RESOURCE_VERSION = 2_147_483_647
TUTORIAL_VERSION = "1.2.0"
TUTORIAL_EVENT_STEPS = {
    "memory_source_opened": 2,
    "continuity_issue_located": 3,
    "evidence_opened": 4,
    "author_decision_recorded": 5,
}


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
CREATE TABLE IF NOT EXISTS v2_users(id TEXT PRIMARY KEY,account_name TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,password_hash TEXT NOT NULL,created_at TEXT NOT NULL,account_type TEXT NOT NULL DEFAULT 'registered',visitor_expires_at TEXT,recovery_email_hash TEXT,recovery_email_masked TEXT,recovery_email_verified_at TEXT,onboarding_status TEXT NOT NULL DEFAULT 'completed',onboarding_tutorial_project_id TEXT,onboarding_completed_at TEXT,onboarding_tutorial_version TEXT,onboarding_current_step INTEGER,onboarding_completed_events_json TEXT,onboarding_progress_revision INTEGER,onboarding_progress_updated_at TEXT,avatar_preset TEXT NOT NULL DEFAULT 'continuity_violet',profile_revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS v2_sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),token_hash TEXT NOT NULL UNIQUE,expires_at TEXT NOT NULL,revoked_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_projects(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),title TEXT NOT NULL,genre TEXT NOT NULL DEFAULT '',summary TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,metadata_revision INTEGER NOT NULL,data_origin TEXT NOT NULL,seed_key TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,current_memory_version INTEGER NOT NULL DEFAULT 1,source_revision INTEGER NOT NULL DEFAULT 1,author_context_version INTEGER NOT NULL DEFAULT 0,alias_version INTEGER NOT NULL DEFAULT 0,revision_task_version INTEGER NOT NULL DEFAULT 0);
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
CREATE TABLE IF NOT EXISTS v2_runs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),draft_id TEXT NOT NULL REFERENCES v2_drafts(id),source_revision INTEGER NOT NULL,draft_revision INTEGER,status TEXT NOT NULL,stage TEXT NOT NULL,provider_label TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,latency_ms INTEGER,cost_cny REAL,error_code TEXT,retryable INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,completed_at TEXT,model_label TEXT,prompt_version TEXT,schema_version TEXT,retrieval_method_version TEXT,source_memory_version INTEGER,result_origin TEXT NOT NULL DEFAULT 'provider',run_type TEXT NOT NULL DEFAULT 'continuity',source_change_set_id TEXT,source_span_ids_json TEXT NOT NULL DEFAULT '[]',started_at TEXT,cancel_requested_at TEXT,duration_ms INTEGER,retry_of_run_id TEXT,root_run_id TEXT,attempt_number INTEGER NOT NULL DEFAULT 1,incremental_batch_id TEXT,author_context_version INTEGER,author_context_snapshot_digest TEXT,alias_version INTEGER,alias_snapshot_digest TEXT,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_runs_by_project ON v2_runs(project_id,draft_id,source_revision,status);
CREATE TABLE IF NOT EXISTS v2_run_stages(run_id TEXT NOT NULL REFERENCES v2_runs(id),stage TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(run_id,stage));
CREATE TABLE IF NOT EXISTS v2_run_events(run_id TEXT NOT NULL REFERENCES v2_runs(id),sequence INTEGER NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,error_code TEXT,created_at TEXT NOT NULL,PRIMARY KEY(run_id,sequence));
CREATE INDEX IF NOT EXISTS v2_run_events_by_run ON v2_run_events(run_id,sequence);
CREATE TABLE IF NOT EXISTS v2_run_claims(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES v2_runs(id),ordinal INTEGER NOT NULL,text TEXT NOT NULL,UNIQUE(run_id,ordinal));
CREATE TABLE IF NOT EXISTS v2_retrieval_traces(run_id TEXT NOT NULL REFERENCES v2_runs(id),claim_id TEXT NOT NULL,terms TEXT NOT NULL,returned_span_ids_json TEXT NOT NULL,method_version TEXT NOT NULL,PRIMARY KEY(run_id,claim_id));
CREATE TABLE IF NOT EXISTS v2_issues(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),claim_span_id TEXT NOT NULL,status TEXT NOT NULL,classification TEXT NOT NULL DEFAULT 'conflict',category TEXT NOT NULL,severity TEXT NOT NULL,evidence_status TEXT NOT NULL,explanation TEXT NOT NULL,proposed_change_json TEXT,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_evidence(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),chapter_id TEXT NOT NULL,span_id TEXT NOT NULL,excerpt TEXT NOT NULL,relation TEXT NOT NULL,sufficiency TEXT NOT NULL,related_memory_ids_json TEXT NOT NULL,source_revision INTEGER NOT NULL,UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS v2_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),decision TEXT NOT NULL,note TEXT,source_revision INTEGER NOT NULL,resulting_revision INTEGER,lineage_status TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(issue_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_change_sets(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),source_run_revision INTEGER NOT NULL,resolved_revision INTEGER NOT NULL,lineage_status TEXT NOT NULL,base_version INTEGER NOT NULL,target_version INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,committed_at TEXT,change_set_kind TEXT NOT NULL DEFAULT 'continuity',actor_user_id TEXT,UNIQUE(project_id,id));
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
CREATE TABLE IF NOT EXISTS v2_memory_delta_batches(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),source_revision INTEGER NOT NULL,base_memory_version INTEGER NOT NULL,continuity_run_id TEXT NOT NULL REFERENCES v2_runs(id),memory_delta_run_id TEXT NOT NULL REFERENCES v2_runs(id),status TEXT NOT NULL,error_code TEXT,created_at TEXT NOT NULL,completed_at TEXT,covered_at TEXT,retrieval_json TEXT NOT NULL DEFAULT '{}',UNIQUE(project_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_memory_delta_candidates(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),batch_id TEXT NOT NULL REFERENCES v2_memory_delta_batches(id),source_revision INTEGER NOT NULL,candidate_ordinal INTEGER NOT NULL,memory_type TEXT NOT NULL,subject TEXT NOT NULL,predicate TEXT NOT NULL,value TEXT NOT NULL,chapter_id TEXT NOT NULL REFERENCES v2_chapters(id),source_span_id TEXT NOT NULL REFERENCES v2_source_spans(id),candidate_origin TEXT NOT NULL DEFAULT 'delta',review_priority TEXT NOT NULL,decision_status TEXT NOT NULL DEFAULT 'pending',decision_json TEXT,decided_at TEXT,change_kind TEXT NOT NULL DEFAULT 'new_fact',affected_memory_id TEXT,invalidation_reason TEXT,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_memory_delta_candidates_by_batch ON v2_memory_delta_candidates(batch_id,decision_status);
CREATE TABLE IF NOT EXISTS v2_memory_delta_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),batch_id TEXT NOT NULL REFERENCES v2_memory_delta_batches(id),candidate_id TEXT NOT NULL REFERENCES v2_memory_delta_candidates(id),decision TEXT NOT NULL,after_json TEXT,evidence_span_id TEXT,source_revision INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(candidate_id));
CREATE TABLE IF NOT EXISTS v2_source_coverage_audits(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),source_revision INTEGER NOT NULL,status TEXT NOT NULL,memory_version INTEGER NOT NULL,delta_batch_id TEXT NOT NULL REFERENCES v2_memory_delta_batches(id),actor_user_id TEXT,details_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,UNIQUE(project_id,source_revision));
CREATE TABLE IF NOT EXISTS v2_login_attempts(account_name TEXT NOT NULL,attempted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_author_story_plans(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),title TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',goal TEXT NOT NULL DEFAULT '',position INTEGER NOT NULL,status TEXT NOT NULL,target_chapter_number INTEGER,archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_author_story_plans_by_project ON v2_author_story_plans(project_id,archived_at,position);
CREATE TABLE IF NOT EXISTS v2_author_character_plans(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),name TEXT NOT NULL,role_type TEXT NOT NULL,goal TEXT NOT NULL DEFAULT '',planned_state TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',position INTEGER NOT NULL,archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_author_character_plans_by_project ON v2_author_character_plans(project_id,archived_at,position);
CREATE TABLE IF NOT EXISTS v2_author_world_plans(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),name TEXT NOT NULL,category TEXT NOT NULL,description TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',position INTEGER NOT NULL,archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,id));
CREATE INDEX IF NOT EXISTS v2_author_world_plans_by_project ON v2_author_world_plans(project_id,archived_at,position);
CREATE TABLE IF NOT EXISTS v2_author_context_versions(project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,parent_version INTEGER,snapshot_digest TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(project_id,version));
CREATE TABLE IF NOT EXISTS v2_author_story_plan_versions(project_id TEXT NOT NULL,version INTEGER NOT NULL,item_id TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,goal TEXT NOT NULL,position INTEGER NOT NULL,status TEXT NOT NULL,target_chapter_number INTEGER,archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,version,item_id),FOREIGN KEY(project_id,version) REFERENCES v2_author_context_versions(project_id,version));
CREATE INDEX IF NOT EXISTS v2_author_story_plan_versions_order ON v2_author_story_plan_versions(project_id,version,position,item_id);
CREATE TABLE IF NOT EXISTS v2_author_character_plan_versions(project_id TEXT NOT NULL,version INTEGER NOT NULL,item_id TEXT NOT NULL,name TEXT NOT NULL,role_type TEXT NOT NULL,goal TEXT NOT NULL,planned_state TEXT NOT NULL,notes TEXT NOT NULL,position INTEGER NOT NULL,archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,version,item_id),FOREIGN KEY(project_id,version) REFERENCES v2_author_context_versions(project_id,version));
CREATE INDEX IF NOT EXISTS v2_author_character_plan_versions_order ON v2_author_character_plan_versions(project_id,version,position,item_id);
CREATE TABLE IF NOT EXISTS v2_author_world_plan_versions(project_id TEXT NOT NULL,version INTEGER NOT NULL,item_id TEXT NOT NULL,name TEXT NOT NULL,category TEXT NOT NULL,description TEXT NOT NULL,notes TEXT NOT NULL,position INTEGER NOT NULL,archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,version,item_id),FOREIGN KEY(project_id,version) REFERENCES v2_author_context_versions(project_id,version));
CREATE INDEX IF NOT EXISTS v2_author_world_plan_versions_order ON v2_author_world_plan_versions(project_id,version,position,item_id);
CREATE TABLE IF NOT EXISTS v2_analysis_inputs(run_id TEXT PRIMARY KEY REFERENCES v2_runs(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),analysis_type TEXT NOT NULL,input_json TEXT NOT NULL,retrieval_json TEXT NOT NULL,input_digest TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_analysis_results(run_id TEXT PRIMARY KEY REFERENCES v2_runs(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),analysis_type TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS v2_analysis_results_by_project ON v2_analysis_results(project_id,analysis_type,created_at);
CREATE TABLE IF NOT EXISTS v2_character_alias_state(project_id TEXT NOT NULL REFERENCES v2_projects(id),character_id TEXT NOT NULL REFERENCES v2_characters(id),version INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,character_id));
CREATE TABLE IF NOT EXISTS v2_character_aliases(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),character_id TEXT NOT NULL REFERENCES v2_characters(id),alias TEXT NOT NULL,normalized_alias TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,archived_at TEXT,UNIQUE(project_id,id));
CREATE UNIQUE INDEX IF NOT EXISTS v2_character_aliases_active_name ON v2_character_aliases(project_id,character_id,normalized_alias) WHERE status='active';
CREATE INDEX IF NOT EXISTS v2_character_aliases_by_character ON v2_character_aliases(project_id,character_id,status,created_at);
CREATE TABLE IF NOT EXISTS v2_foreshadows(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),title TEXT NOT NULL,normalized_title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,planted_chapter_id TEXT REFERENCES v2_chapters(id),planted_source_span_id TEXT REFERENCES v2_source_spans(id),resolved_chapter_id TEXT REFERENCES v2_chapters(id),resolved_source_span_id TEXT REFERENCES v2_source_spans(id),version INTEGER NOT NULL,archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,id));
CREATE UNIQUE INDEX IF NOT EXISTS v2_foreshadows_active_title ON v2_foreshadows(project_id,normalized_title) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS v2_foreshadows_by_project ON v2_foreshadows(project_id,archived_at,status,updated_at);
CREATE TABLE IF NOT EXISTS v2_foreshadow_versions(item_id TEXT NOT NULL REFERENCES v2_foreshadows(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,snapshot_json TEXT NOT NULL,event TEXT NOT NULL,actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,PRIMARY KEY(item_id,version));
CREATE TABLE IF NOT EXISTS v2_foreshadow_candidates(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_ordinal INTEGER NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,suggested_status TEXT NOT NULL,planted_chapter_id TEXT REFERENCES v2_chapters(id),planted_source_span_id TEXT REFERENCES v2_source_spans(id),resolved_chapter_id TEXT REFERENCES v2_chapters(id),resolved_source_span_id TEXT REFERENCES v2_source_spans(id),evidence_json TEXT NOT NULL,decision_status TEXT NOT NULL DEFAULT 'pending',decision_json TEXT,decided_at TEXT,created_at TEXT NOT NULL,UNIQUE(run_id,candidate_ordinal));
CREATE INDEX IF NOT EXISTS v2_foreshadow_candidates_by_run ON v2_foreshadow_candidates(run_id,decision_status,candidate_ordinal);
CREATE TABLE IF NOT EXISTS v2_foreshadow_candidate_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_id TEXT NOT NULL REFERENCES v2_foreshadow_candidates(id),decision TEXT NOT NULL,after_json TEXT,created_record_id TEXT REFERENCES v2_foreshadows(id),actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,UNIQUE(candidate_id));
CREATE TABLE IF NOT EXISTS v2_revision_plan_candidates(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_ordinal INTEGER NOT NULL,issue_id TEXT NOT NULL REFERENCES v2_issues(id),title TEXT NOT NULL,normalized_title TEXT NOT NULL,instruction TEXT NOT NULL,priority TEXT NOT NULL,evidence_json TEXT NOT NULL,decision_status TEXT NOT NULL DEFAULT 'pending',decision_json TEXT,decided_at TEXT,created_at TEXT NOT NULL,UNIQUE(run_id,candidate_ordinal),UNIQUE(run_id,issue_id));
CREATE INDEX IF NOT EXISTS v2_revision_plan_candidates_by_run ON v2_revision_plan_candidates(run_id,decision_status,candidate_ordinal);
CREATE TABLE IF NOT EXISTS v2_revision_tasks(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),source_run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_id TEXT NOT NULL REFERENCES v2_revision_plan_candidates(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),title TEXT NOT NULL,normalized_title TEXT NOT NULL,instruction TEXT NOT NULL,priority TEXT NOT NULL,position INTEGER NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,id),UNIQUE(candidate_id));
CREATE INDEX IF NOT EXISTS v2_revision_tasks_by_project ON v2_revision_tasks(project_id,status,position,created_at);
CREATE TABLE IF NOT EXISTS v2_revision_task_versions(task_id TEXT NOT NULL REFERENCES v2_revision_tasks(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,snapshot_json TEXT NOT NULL,event TEXT NOT NULL,actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,PRIMARY KEY(task_id,version));
CREATE TABLE IF NOT EXISTS v2_revision_candidate_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_id TEXT NOT NULL REFERENCES v2_revision_plan_candidates(id),decision TEXT NOT NULL,after_json TEXT,created_task_id TEXT REFERENCES v2_revision_tasks(id),actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,UNIQUE(candidate_id));
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
            self._migrate_v110_onboarding(c)
            self._migrate_v120_tutorial_progress(c)
            self._migrate_v130_author_intent(c)
            self._migrate_v130_profile(c)
            self._migrate_legacy_project(c)
            self._migrate_stage12_run_lifecycle(c)
            self._migrate_v130_author_context_snapshots(c)
            self._migrate_v130_writing_analysis(c)
            self._migrate_v130_memory_delta_fact_lifecycle(c)
            self._migrate_v130_character_aliases(c)
            self._migrate_v130_foreshadows(c)
            self._migrate_v130_revision_plans(c)

    def readiness_probe(self) -> bool:
        """Verify that the configured database is readable and fully initialized."""
        with self.connection() as c:
            row = c.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()
            check = c.execute("PRAGMA quick_check").fetchone()
            return bool(row and row["count"] >= 1 and check and check[0] == "ok")

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

    def _migrate_v110_onboarding(self, c: sqlite3.Connection) -> None:
        """Add opt-in tutorial state without changing any existing account or project."""
        columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_users)")}
        additions = {
            "onboarding_status": "TEXT NOT NULL DEFAULT 'completed'",
            "onboarding_tutorial_project_id": "TEXT",
            "onboarding_completed_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                c.execute(f"ALTER TABLE v2_users ADD COLUMN {name} {definition}")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(110,?)", (utcnow(),))

    def _migrate_v120_tutorial_progress(self, c: sqlite3.Connection) -> None:
        """Add durable progress without reactivating completed or skipped accounts."""
        columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_users)")}
        additions = {
            "onboarding_tutorial_version": "TEXT",
            "onboarding_current_step": "INTEGER",
            "onboarding_completed_events_json": "TEXT",
            "onboarding_progress_revision": "INTEGER",
            "onboarding_progress_updated_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                c.execute(f"ALTER TABLE v2_users ADD COLUMN {name} {definition}")
        stamp = utcnow()
        c.execute(
            "UPDATE v2_users SET onboarding_tutorial_version=?,onboarding_current_step=1,"
            "onboarding_completed_events_json='[]',onboarding_progress_revision=1,"
            "onboarding_progress_updated_at=? "
            "WHERE account_type='registered' AND onboarding_status='active' "
            "AND onboarding_tutorial_version IS NULL "
            "AND EXISTS(SELECT 1 FROM v2_projects p WHERE p.id=v2_users.onboarding_tutorial_project_id "
            "AND p.user_id=v2_users.id AND p.data_origin='tutorial_seed')",
            (TUTORIAL_VERSION, stamp),
        )
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(120,?)", (stamp,))

    def _migrate_v130_author_intent(self, c: sqlite3.Connection) -> None:
        """Add an independent author-intent store and nullable Run binding."""
        project_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_projects)")}
        if "author_context_version" not in project_columns:
            c.execute("ALTER TABLE v2_projects ADD COLUMN author_context_version INTEGER NOT NULL DEFAULT 0")
        run_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_runs)")}
        if "author_context_version" not in run_columns:
            c.execute("ALTER TABLE v2_runs ADD COLUMN author_context_version INTEGER")
        c.execute("UPDATE v2_projects SET author_context_version=0 WHERE author_context_version IS NULL OR author_context_version<0")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(130,?)", (utcnow(),))

    def _migrate_v130_profile(self, c: sqlite3.Connection) -> None:
        """Add durable, local-only author profile presentation fields."""
        columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_users)")}
        additions = {
            "avatar_preset": "TEXT NOT NULL DEFAULT 'continuity_violet'",
            "profile_revision": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, definition in additions.items():
            if name not in columns:
                c.execute(f"ALTER TABLE v2_users ADD COLUMN {name} {definition}")
        c.execute("UPDATE v2_users SET avatar_preset='continuity_violet' WHERE avatar_preset IS NULL OR avatar_preset='' ")
        c.execute("UPDATE v2_users SET profile_revision=1 WHERE profile_revision IS NULL OR profile_revision<1")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(132,?)", (utcnow(),))

    def _migrate_v130_author_context_snapshots(self, c: sqlite3.Connection) -> None:
        """Freeze the current mutable Author Context without inventing old history."""
        run_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_runs)")}
        if "author_context_snapshot_digest" not in run_columns:
            c.execute("ALTER TABLE v2_runs ADD COLUMN author_context_snapshot_digest TEXT")
        for project in c.execute("SELECT * FROM v2_projects ORDER BY id").fetchall():
            project_id=project["id"]
            self._insert_empty_author_context_zero(c,project_id,project["created_at"])
            live_count=sum(c.execute(f"SELECT COUNT(*) FROM {spec['table']} WHERE project_id=?",(project_id,)).fetchone()[0] for spec in self._AUTHOR_INTENT.values())
            current=int(project["author_context_version"] or 0)
            if current==0 and live_count:
                current=1
                c.execute("UPDATE v2_projects SET author_context_version=? WHERE id=?",(current,project_id))
            if current>0 and not c.execute("SELECT 1 FROM v2_author_context_versions WHERE project_id=? AND version=?",(project_id,current)).fetchone():
                self._write_author_context_snapshot(c,project_id,current,0,project["updated_at"])
        for run in c.execute("SELECT id,project_id,author_context_version,author_context_snapshot_digest FROM v2_runs WHERE author_context_version IS NOT NULL").fetchall():
            version=c.execute("SELECT snapshot_digest FROM v2_author_context_versions WHERE project_id=? AND version=?",(run["project_id"],run["author_context_version"])).fetchone()
            if version:
                if run["author_context_snapshot_digest"] is None:
                    c.execute("UPDATE v2_runs SET author_context_snapshot_digest=? WHERE id=?",(version["snapshot_digest"],run["id"]))
            else:
                c.execute("UPDATE v2_runs SET author_context_version=NULL,author_context_snapshot_digest=NULL WHERE id=?",(run["id"],))
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(131,?)",(utcnow(),))

    def _migrate_v130_writing_analysis(self, c: sqlite3.Connection) -> None:
        """Add immutable state-bound analysis inputs and results."""
        columns={row["name"] for row in c.execute("PRAGMA table_info(v2_runs)").fetchall()}
        if "draft_revision" not in columns:c.execute("ALTER TABLE v2_runs ADD COLUMN draft_revision INTEGER")
        c.execute("CREATE TABLE IF NOT EXISTS v2_analysis_inputs(run_id TEXT PRIMARY KEY REFERENCES v2_runs(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),analysis_type TEXT NOT NULL,input_json TEXT NOT NULL,retrieval_json TEXT NOT NULL,input_digest TEXT NOT NULL,created_at TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS v2_analysis_results(run_id TEXT PRIMARY KEY REFERENCES v2_runs(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),analysis_type TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL)")
        c.execute("CREATE INDEX IF NOT EXISTS v2_analysis_results_by_project ON v2_analysis_results(project_id,analysis_type,created_at)")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(133,?)",(utcnow(),))

    def _migrate_v130_character_aliases(self, c: sqlite3.Connection) -> None:
        """Add independent character aliases and immutable analysis bindings."""
        project_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_projects)").fetchall()}
        if "alias_version" not in project_columns:c.execute("ALTER TABLE v2_projects ADD COLUMN alias_version INTEGER NOT NULL DEFAULT 0")
        run_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_runs)").fetchall()}
        if "alias_version" not in run_columns:c.execute("ALTER TABLE v2_runs ADD COLUMN alias_version INTEGER")
        if "alias_snapshot_digest" not in run_columns:c.execute("ALTER TABLE v2_runs ADD COLUMN alias_snapshot_digest TEXT")
        c.execute("CREATE TABLE IF NOT EXISTS v2_character_alias_state(project_id TEXT NOT NULL REFERENCES v2_projects(id),character_id TEXT NOT NULL REFERENCES v2_characters(id),version INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,character_id))")
        c.execute("CREATE TABLE IF NOT EXISTS v2_character_aliases(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),character_id TEXT NOT NULL REFERENCES v2_characters(id),alias TEXT NOT NULL,normalized_alias TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,archived_at TEXT,UNIQUE(project_id,id))")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS v2_character_aliases_active_name ON v2_character_aliases(project_id,character_id,normalized_alias) WHERE status='active'")
        c.execute("CREATE INDEX IF NOT EXISTS v2_character_aliases_by_character ON v2_character_aliases(project_id,character_id,status,created_at)")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(134,?)",(utcnow(),))

    def _migrate_v130_foreshadows(self, c: sqlite3.Connection) -> None:
        """Add author-owned foreshadows and immutable bindings for bounded AI tools."""
        project_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_projects)").fetchall()}
        if "foreshadow_version" not in project_columns:c.execute("ALTER TABLE v2_projects ADD COLUMN foreshadow_version INTEGER NOT NULL DEFAULT 0")
        run_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_runs)").fetchall()}
        if "foreshadow_version" not in run_columns:c.execute("ALTER TABLE v2_runs ADD COLUMN foreshadow_version INTEGER")
        if "foreshadow_snapshot_digest" not in run_columns:c.execute("ALTER TABLE v2_runs ADD COLUMN foreshadow_snapshot_digest TEXT")
        c.execute("CREATE TABLE IF NOT EXISTS v2_foreshadows(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),title TEXT NOT NULL,normalized_title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,planted_chapter_id TEXT REFERENCES v2_chapters(id),planted_source_span_id TEXT REFERENCES v2_source_spans(id),resolved_chapter_id TEXT REFERENCES v2_chapters(id),resolved_source_span_id TEXT REFERENCES v2_source_spans(id),version INTEGER NOT NULL,archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,id))")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS v2_foreshadows_active_title ON v2_foreshadows(project_id,normalized_title) WHERE archived_at IS NULL")
        c.execute("CREATE INDEX IF NOT EXISTS v2_foreshadows_by_project ON v2_foreshadows(project_id,archived_at,status,updated_at)")
        c.execute("CREATE TABLE IF NOT EXISTS v2_foreshadow_versions(item_id TEXT NOT NULL REFERENCES v2_foreshadows(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,snapshot_json TEXT NOT NULL,event TEXT NOT NULL,actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,PRIMARY KEY(item_id,version))")
        c.execute("CREATE TABLE IF NOT EXISTS v2_foreshadow_candidates(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_ordinal INTEGER NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,suggested_status TEXT NOT NULL,planted_chapter_id TEXT REFERENCES v2_chapters(id),planted_source_span_id TEXT REFERENCES v2_source_spans(id),resolved_chapter_id TEXT REFERENCES v2_chapters(id),resolved_source_span_id TEXT REFERENCES v2_source_spans(id),evidence_json TEXT NOT NULL,decision_status TEXT NOT NULL DEFAULT 'pending',decision_json TEXT,decided_at TEXT,created_at TEXT NOT NULL,UNIQUE(run_id,candidate_ordinal))")
        c.execute("CREATE INDEX IF NOT EXISTS v2_foreshadow_candidates_by_run ON v2_foreshadow_candidates(run_id,decision_status,candidate_ordinal)")
        c.execute("CREATE TABLE IF NOT EXISTS v2_foreshadow_candidate_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_id TEXT NOT NULL REFERENCES v2_foreshadow_candidates(id),decision TEXT NOT NULL,after_json TEXT,created_record_id TEXT REFERENCES v2_foreshadows(id),actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,UNIQUE(candidate_id))")

    def _migrate_v130_revision_plans(self, c: sqlite3.Connection) -> None:
        """Add review-only revision suggestions and author-owned durable tasks."""
        project_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_projects)").fetchall()}
        if "revision_task_version" not in project_columns:c.execute("ALTER TABLE v2_projects ADD COLUMN revision_task_version INTEGER NOT NULL DEFAULT 0")
        c.execute("CREATE TABLE IF NOT EXISTS v2_revision_plan_candidates(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_ordinal INTEGER NOT NULL,issue_id TEXT NOT NULL REFERENCES v2_issues(id),title TEXT NOT NULL,normalized_title TEXT NOT NULL,instruction TEXT NOT NULL,priority TEXT NOT NULL,evidence_json TEXT NOT NULL,decision_status TEXT NOT NULL DEFAULT 'pending',decision_json TEXT,decided_at TEXT,created_at TEXT NOT NULL,UNIQUE(run_id,candidate_ordinal),UNIQUE(run_id,issue_id))")
        c.execute("CREATE INDEX IF NOT EXISTS v2_revision_plan_candidates_by_run ON v2_revision_plan_candidates(run_id,decision_status,candidate_ordinal)")
        c.execute("CREATE TABLE IF NOT EXISTS v2_revision_tasks(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),source_run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_id TEXT NOT NULL REFERENCES v2_revision_plan_candidates(id),issue_id TEXT NOT NULL REFERENCES v2_issues(id),title TEXT NOT NULL,normalized_title TEXT NOT NULL,instruction TEXT NOT NULL,priority TEXT NOT NULL,position INTEGER NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,id),UNIQUE(candidate_id))")
        c.execute("CREATE INDEX IF NOT EXISTS v2_revision_tasks_by_project ON v2_revision_tasks(project_id,status,position,created_at)")
        c.execute("CREATE TABLE IF NOT EXISTS v2_revision_task_versions(task_id TEXT NOT NULL REFERENCES v2_revision_tasks(id),project_id TEXT NOT NULL REFERENCES v2_projects(id),version INTEGER NOT NULL,snapshot_json TEXT NOT NULL,event TEXT NOT NULL,actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,PRIMARY KEY(task_id,version))")
        c.execute("CREATE TABLE IF NOT EXISTS v2_revision_candidate_decisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v2_projects(id),run_id TEXT NOT NULL REFERENCES v2_runs(id),candidate_id TEXT NOT NULL REFERENCES v2_revision_plan_candidates(id),decision TEXT NOT NULL,after_json TEXT,created_task_id TEXT REFERENCES v2_revision_tasks(id),actor_user_id TEXT NOT NULL REFERENCES v2_users(id),created_at TEXT NOT NULL,UNIQUE(candidate_id))")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(135,?)",(utcnow(),))

    def _migrate_v130_memory_delta_fact_lifecycle(self, c: sqlite3.Connection) -> None:
        """Extend the existing delta approval chain without reinterpreting canon history."""
        batch_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_memory_delta_batches)").fetchall()}
        if "retrieval_json" not in batch_columns:c.execute("ALTER TABLE v2_memory_delta_batches ADD COLUMN retrieval_json TEXT NOT NULL DEFAULT '{}'")
        candidate_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_memory_delta_candidates)").fetchall()}
        added_change_kind="change_kind" not in candidate_columns
        for name,definition in {"change_kind":"TEXT NOT NULL DEFAULT 'new_fact'","affected_memory_id":"TEXT","invalidation_reason":"TEXT"}.items():
            if name not in candidate_columns:c.execute(f"ALTER TABLE v2_memory_delta_candidates ADD COLUMN {name} {definition}")
        change_set_columns={row["name"] for row in c.execute("PRAGMA table_info(v2_change_sets)").fetchall()}
        if "change_set_kind" not in change_set_columns:c.execute("ALTER TABLE v2_change_sets ADD COLUMN change_set_kind TEXT NOT NULL DEFAULT 'continuity'")
        if "actor_user_id" not in change_set_columns:c.execute("ALTER TABLE v2_change_sets ADD COLUMN actor_user_id TEXT")
        if added_change_kind:
            for row in c.execute("SELECT d.*,b.base_memory_version FROM v2_memory_delta_candidates d JOIN v2_memory_delta_batches b ON b.id=d.batch_id AND b.project_id=d.project_id ORDER BY d.id").fetchall():
                identity=self._candidate_key(row["memory_type"],row["subject"],row["predicate"],allow_legacy_alias=False)
                prior=next((record for record in c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed'",(row["project_id"],row["base_memory_version"])).fetchall() if self._candidate_key(record["memory_type"],record["subject"],record["predicate"],allow_legacy_alias=False)==identity),None)
                if prior and self._normalize(prior["value"])!=self._normalize(row["value"]):
                    c.execute("UPDATE v2_memory_delta_candidates SET change_kind='changed_fact',affected_memory_id=? WHERE id=?",(prior["id"],row["id"]))
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(134,?)",(utcnow(),))

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
        c.execute("INSERT INTO v2_projects(id,user_id,title,genre,summary,status,metadata_revision,data_origin,seed_key,created_at,updated_at,current_memory_version,source_revision,author_context_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (project_id,user_id,legacy["title"],"",legacy["summary"],"active",1,"v1_migrated",None,stamp,stamp,int(legacy["current_memory_version"]),1,0))
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
                c.execute("INSERT INTO v2_change_sets(id,project_id,run_id,source_run_revision,resolved_revision,lineage_status,base_version,target_version,status,created_at,committed_at,change_set_kind,actor_user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (change_set_id,project_id,run_id,changeset["source_run_revision"],changeset["resolved_revision"],changeset["lineage_status"],changeset["base_version"],changeset["target_version"],changeset["status"],changeset["created_at"],changeset["committed_at"],"continuity",None))
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
        c.execute("INSERT INTO v2_projects(id,user_id,title,genre,summary,status,metadata_revision,data_origin,seed_key,created_at,updated_at,current_memory_version,source_revision,author_context_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (project_id,user_id,title,genre,summary,"active",1,origin,seed_key,stamp,stamp,version,1,0))
        self._insert_empty_author_context_zero(c,project_id,stamp)
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
        project=c.execute("SELECT * FROM v2_projects WHERE id=?",(project_id,)).fetchone()
        author_version,author_digest=self._current_author_context_binding(c,project)
        c.execute(
            "INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,input_tokens,output_tokens,latency_ms,cost_cny,error_code,retryable,created_at,completed_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,started_at,duration_ms,root_run_id,attempt_number,author_context_version,author_context_snapshot_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id,project_id,draft_id,1,"completed","completed","not_called",None,None,None,None,None,0,stamp,stamp,"not_applicable","demo-preset-v1","demo-review-v1","demo-preset-v1",4,"demo_preset",stamp,0,run_id,1,author_version,author_digest),
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
                stamp = utcnow()
                c.execute(
                    "INSERT INTO v2_users(id,account_name,display_name,password_hash,created_at,recovery_email_hash,recovery_email_masked,onboarding_status,onboarding_tutorial_version,onboarding_current_step,onboarding_completed_events_json,onboarding_progress_revision,onboarding_progress_updated_at) VALUES(?,?,?,?,?,?,?,'active',?,1,'[]',1,?)",
                    (user_id,account_name,display_name,_password(password),stamp,payload.get("recovery_email_hash"),payload.get("recovery_email_masked"),TUTORIAL_VERSION,stamp),
                )
                tutorial_id = self._create_project(
                    c,
                    user_id,
                    "教学模式 · 灰港回声",
                    "悬疑 · 教学样例",
                    "隔离的确定性教学作品；不计入真实作品、搜索或待处理事项。",
                    "tutorial_seed",
                    "grey_harbor",
                )
                c.execute(
                    "UPDATE v2_users SET onboarding_tutorial_project_id=? WHERE id=?",
                    (tutorial_id, user_id),
                )
                progress = self._tutorial_progress(
                    c,
                    c.execute("SELECT * FROM v2_users WHERE id=?", (user_id,)).fetchone(),
                )
                token, expires_at = self._new_session(c, user_id)
                return {
                    "user":{"id":user_id,"account_name":account_name,"display_name":display_name},
                    "session":{"expires_at":expires_at,"_token":token},
                    "seeded_projects":[],
                    "onboarding":{
                        "status":"active",
                        "real_project_count":0,
                        "tutorial":{"project_id":tutorial_id,"title":"教学模式 · 灰港回声","data_origin":"tutorial_seed"},
                        "progress":progress,
                    },
                }
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

    # --- v1.2.0 durable first-run tutorial ---
    def _tutorial_progress(self, c: sqlite3.Connection, user: sqlite3.Row) -> dict[str, Any] | None:
        if user["account_type"] != "registered" or user["onboarding_status"] != "active":
            return None
        tutorial_id = user["onboarding_tutorial_project_id"]
        if not tutorial_id:
            return None
        project = c.execute(
            "SELECT 1 FROM v2_projects WHERE id=? AND user_id=? AND data_origin='tutorial_seed'",
            (tutorial_id, user["id"]),
        ).fetchone()
        if not project:
            return None
        try:
            events = json.loads(user["onboarding_completed_events_json"] or "[]")
        except (TypeError, ValueError):
            raise DomainError("tutorial_progress_unavailable", 503, True) from None
        step = user["onboarding_current_step"]
        revision = user["onboarding_progress_revision"]
        updated_at = user["onboarding_progress_updated_at"]
        if (
            user["onboarding_tutorial_version"] != TUTORIAL_VERSION
            or not isinstance(step, int)
            or isinstance(step, bool)
            or not 1 <= step <= 5
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
            or not isinstance(updated_at, str)
            or not isinstance(events, list)
            or len(events) != len(set(events))
            or any(event not in TUTORIAL_EVENT_STEPS for event in events)
        ):
            raise DomainError("tutorial_progress_unavailable", 503, True)
        canonical_events = sorted(events, key=TUTORIAL_EVENT_STEPS.__getitem__)
        canonical_step = max([1, *(TUTORIAL_EVENT_STEPS[event] for event in canonical_events)])
        if step != canonical_step:
            raise DomainError("tutorial_progress_unavailable", 503, True)
        return {
            "tutorial_version": TUTORIAL_VERSION,
            "tutorial_project_id": tutorial_id,
            "current_step": step,
            "completed_events": canonical_events,
            "revision": revision,
            "updated_at": updated_at,
        }

    def onboarding(self, user_id: str) -> dict[str, Any]:
        with self.connection() as c:
            user = c.execute(
                "SELECT * FROM v2_users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not user:
                raise DomainError("authentication_required", 401)
            real_count = c.execute(
                "SELECT COUNT(*) FROM v2_projects WHERE user_id=? AND data_origin!='tutorial_seed'",
                (user_id,),
            ).fetchone()[0]
            tutorial = None
            tutorial_id = user["onboarding_tutorial_project_id"]
            if tutorial_id:
                row = c.execute(
                    "SELECT id,title,status,data_origin FROM v2_projects WHERE id=? AND user_id=? AND data_origin='tutorial_seed'",
                    (tutorial_id, user_id),
                ).fetchone()
                if row:
                    tutorial = {
                        "project_id": row["id"],
                        "title": row["title"],
                        "status": row["status"],
                        "data_origin": row["data_origin"],
                    }
            return {
                "status": user["onboarding_status"],
                "real_project_count": real_count,
                "tutorial": tutorial,
                "progress": self._tutorial_progress(c, user),
                "completed_at": user["onboarding_completed_at"],
                "show_first_run": user["account_type"] == "registered" and user["onboarding_status"] == "active" and real_count == 0,
            }

    def record_tutorial_event(self, user_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            user = c.execute("SELECT * FROM v2_users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise DomainError("authentication_required", 401)
            if user["account_type"] != "registered" or user["onboarding_status"] != "active":
                raise DomainError("tutorial_unavailable", 409)
            project_id = payload["project_id"]
            if (
                payload["tutorial_version"] != TUTORIAL_VERSION
                or project_id != user["onboarding_tutorial_project_id"]
                or not c.execute(
                    "SELECT 1 FROM v2_projects WHERE id=? AND user_id=? AND data_origin='tutorial_seed'",
                    (project_id, user_id),
                ).fetchone()
            ):
                raise DomainError("tutorial_progress_target_invalid", 409)
            event = payload["event"]
            if event not in TUTORIAL_EVENT_STEPS:
                raise DomainError("invalid_request", 400)
            stored = c.execute(
                "SELECT fingerprint FROM v2_idempotency WHERE scope=? AND operation='onboarding_progress' AND idempotency_key=?",
                (user_id, key),
            ).fetchone()
            fingerprint = digest(payload)
            if stored and stored["fingerprint"] != fingerprint:
                raise DomainError("idempotency_conflict", 409)
            progress = self._tutorial_progress(c, user)
            if progress is None:
                raise DomainError("tutorial_progress_unavailable", 503, True)
            if event not in progress["completed_events"]:
                events = sorted(
                    [*progress["completed_events"], event],
                    key=TUTORIAL_EVENT_STEPS.__getitem__,
                )
                step = max(progress["current_step"], TUTORIAL_EVENT_STEPS[event])
                revision = progress["revision"] + 1
                stamp = utcnow()
                changed = c.execute(
                    "UPDATE v2_users SET onboarding_current_step=?,onboarding_completed_events_json=?,"
                    "onboarding_progress_revision=?,onboarding_progress_updated_at=? "
                    "WHERE id=? AND onboarding_progress_revision=?",
                    (step, json.dumps(events), revision, stamp, user_id, progress["revision"]),
                ).rowcount
                if changed != 1:
                    raise DomainError("tutorial_progress_conflict", 409, True)
                user = c.execute("SELECT * FROM v2_users WHERE id=?", (user_id,)).fetchone()
                progress = self._tutorial_progress(c, user)
            response_json = json.dumps(progress, ensure_ascii=False)
            if stored:
                c.execute(
                    "UPDATE v2_idempotency SET response_json=?,status_code=200 WHERE scope=? AND operation='onboarding_progress' AND idempotency_key=?",
                    (response_json, user_id, key),
                )
            else:
                c.execute(
                    "INSERT INTO v2_idempotency VALUES(?,?,?,?,?,?,?)",
                    (user_id, "onboarding_progress", key, fingerprint, response_json, 200, utcnow()),
                )
            return progress, 200

    def finish_onboarding(self, user_id: str, outcome: str, payload: dict[str, Any], key: str):
        if outcome not in {"completed", "skipped"}:
            raise DomainError("invalid_request", 400)
        with self.connection() as c:
            def finish() -> dict[str, Any]:
                if payload.get("confirm") is not True:
                    raise DomainError("confirmation_required", 400)
                user = c.execute("SELECT account_type FROM v2_users WHERE id=?", (user_id,)).fetchone()
                if not user:
                    raise DomainError("authentication_required", 401)
                if user["account_type"] != "registered":
                    raise DomainError("tutorial_unavailable", 409)
                stamp = utcnow()
                c.execute(
                    "UPDATE v2_users SET onboarding_status=?,onboarding_completed_at=? WHERE id=?",
                    (outcome, stamp, user_id),
                )
                return {"status": outcome, "completed_at": stamp, "real_project_count": c.execute("SELECT COUNT(*) FROM v2_projects WHERE user_id=? AND data_origin!='tutorial_seed'", (user_id,)).fetchone()[0], "progress": None}
            return self._idem(c, user_id, f"onboarding_{outcome}", key, payload, finish, 200)

    def reopen_onboarding(self, user_id: str, payload: dict[str, Any], key: str):
        if payload.get("confirm") is not True:
            raise DomainError("confirmation_required", 400)
        with self.connection() as c:
            user = c.execute(
                "SELECT account_type,onboarding_tutorial_project_id,onboarding_progress_revision FROM v2_users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not user:
                raise DomainError("authentication_required", 401)
            if user["account_type"] != "registered":
                raise DomainError("tutorial_unavailable", 409)
            tutorial_id = user["onboarding_tutorial_project_id"]
            previous_revision = user["onboarding_progress_revision"] or 0
        if tutorial_id:
            self.reset(user_id, tutorial_id, {"confirm": True, "reason": "demo_recovery"}, key)
        with self.connection() as c:
            def reopen() -> dict[str, Any]:
                current_id = tutorial_id
                exists = current_id and c.execute(
                    "SELECT 1 FROM v2_projects WHERE id=? AND user_id=? AND data_origin='tutorial_seed'",
                    (current_id, user_id),
                ).fetchone()
                if not exists:
                    current_id = self._create_project(
                        c,
                        user_id,
                        "教学模式 · 灰港回声",
                        "悬疑 · 教学样例",
                        "隔离的确定性教学作品；不计入真实作品、搜索或待处理事项。",
                        "tutorial_seed",
                        "grey_harbor",
                    )
                else:
                    c.execute(
                        "UPDATE v2_projects SET title='教学模式 · 灰港回声',genre='悬疑 · 教学样例',summary='隔离的确定性教学作品；不计入真实作品、搜索或待处理事项。',status='active',metadata_revision=metadata_revision+1,updated_at=? WHERE id=?",
                        (utcnow(), current_id),
                    )
                c.execute(
                    "UPDATE v2_users SET onboarding_status='active',onboarding_tutorial_project_id=?,onboarding_completed_at=NULL,"
                    "onboarding_tutorial_version=?,onboarding_current_step=1,onboarding_completed_events_json='[]',"
                    "onboarding_progress_revision=?,onboarding_progress_updated_at=? WHERE id=?",
                    (current_id, TUTORIAL_VERSION, previous_revision + 1, utcnow(), user_id),
                )
                refreshed = c.execute("SELECT * FROM v2_users WHERE id=?", (user_id,)).fetchone()
                return {"status": "active", "tutorial": {"project_id": current_id, "title": "教学模式 · 灰港回声", "data_origin": "tutorial_seed"}, "progress": self._tutorial_progress(c, refreshed)}
            return self._idem(c, user_id, "onboarding_reopen", key, payload, reopen, 200)

    def _complete_onboarding_for_real_project(self, c: sqlite3.Connection, user_id: str) -> None:
        c.execute(
            "UPDATE v2_users SET onboarding_status='completed',onboarding_completed_at=COALESCE(onboarding_completed_at,?) WHERE id=? AND account_type='registered' AND onboarding_status='active'",
            (utcnow(), user_id),
        )

    # --- project read/lifecycle implementation ---
    def home(self, user_id: str) -> dict[str, Any]:
        with self.connection() as c:
            projects = c.execute("SELECT * FROM v2_projects WHERE user_id=? AND status!='archived' AND data_origin!='tutorial_seed' ORDER BY updated_at DESC", (user_id,)).fetchall()
            recent, pending, continuation = [], [], None
            for project in projects:
                draft = c.execute("SELECT * FROM v2_drafts WHERE project_id=? ORDER BY saved_at DESC LIMIT 1", (project["id"],)).fetchone()
                issue_count = c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open'", (project["id"],)).fetchone()[0]
                completed_check = c.execute("SELECT 1 FROM v2_runs WHERE project_id=? AND run_type IN ('continuity','memory_delta') AND status='completed' LIMIT 1", (project["id"],)).fetchone()
                continuity_status = "pending" if issue_count else "checked_clear" if completed_check else "unchecked"
                recent.append({"project_id":project["id"],"title":project["title"],"status":project["status"],"updated_at":project["updated_at"]})
                levels={level:c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open' AND severity=?",(project["id"],level)).fetchone()[0] for level in ("high","medium","low")}
                pending.append({"project_id":project["id"],"title":project["title"],"open_count":issue_count,"continuity_status":continuity_status,**levels})
                if continuation is None and draft:
                    continuation = {"project_id":project["id"],"project_title":project["title"],"draft_id":draft["id"],"draft_title":draft["title"],"draft_revision":draft["revision"],"next_action":"continue_draft","updated_at":project["updated_at"]}
            failed=c.execute("SELECT r.id,r.project_id,r.status,r.error_code,r.created_at FROM v2_runs r JOIN v2_projects p ON p.id=r.project_id WHERE p.user_id=? AND p.data_origin!='tutorial_seed' AND r.run_type IN ('continuity','memory_delta') AND r.status IN ('failed','timed_out') ORDER BY r.created_at DESC LIMIT 1",(user_id,)).fetchone()
            latest={"run_id":failed["id"],"project_id":failed["project_id"],"status":failed["status"],"error_code":failed["error_code"],"created_at":failed["created_at"]} if failed else None
            return {"continue_work":continuation,"recent_projects":recent,"pending_continuity":pending,"latest_failed_run":latest}

    def list_projects(self, user_id: str, q: str | None, status: str | None, has_open_issues: bool | None, sort: str | None) -> dict[str, Any]:
        if status not in {None,"active","paused","completed","archived"} or sort not in {None,"updated_desc","title_asc"}:
            raise DomainError("invalid_filter", 400)
        with self.connection() as c:
            sql, values = "SELECT * FROM v2_projects WHERE user_id=? AND data_origin!='tutorial_seed'", [user_id]
            if status:
                sql += " AND status=?"; values.append(status)
            else:
                sql += " AND status!='archived'"
            if q:
                sql += " AND (title LIKE ? OR summary LIKE ?)"; values.extend([f"%{q}%",f"%{q}%"])
            sql += " ORDER BY " + ("title COLLATE NOCASE" if sort == "title_asc" else "updated_at DESC")
            result = []
            for project in c.execute(sql, values).fetchall():
                draft = c.execute("SELECT id,chapter_number,revision,status,body FROM v2_drafts WHERE project_id=? ORDER BY saved_at DESC LIMIT 1", (project["id"],)).fetchone()
                chapters = c.execute("SELECT chapter_number,body FROM v2_chapters WHERE project_id=? ORDER BY chapter_number", (project["id"],)).fetchall()
                writing_by_chapter = {int(chapter["chapter_number"]): str(chapter["body"] or "") for chapter in chapters}
                if draft and str(draft["body"] or "").strip():
                    writing_by_chapter[int(draft["chapter_number"])] = str(draft["body"])
                word_count = sum(len(re.sub(r"\s+", "", body)) for body in writing_by_chapter.values())
                open_count = c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open'", (project["id"],)).fetchone()[0]
                completed_check = c.execute("SELECT 1 FROM v2_runs WHERE project_id=? AND run_type IN ('continuity','memory_delta') AND status='completed' LIMIT 1", (project["id"],)).fetchone()
                if has_open_issues is not None and bool(open_count) != has_open_issues:
                    continue
                draft_summary = {key: draft[key] for key in ("id", "chapter_number", "revision", "status")} if draft else None
                result.append({"id":project["id"],"seed_key":project["seed_key"],"title":project["title"],"genre":project["genre"],"summary":project["summary"],"status":project["status"],"metadata_revision":project["metadata_revision"],"author_context_version":project["author_context_version"],"foreshadow_version":project["foreshadow_version"],"data_origin":project["data_origin"],"chapter_count":len(chapters),"word_count":word_count,"current_memory_version":project["current_memory_version"],"current_draft":draft_summary,"open_issue_count":open_count,"continuity_status":("pending" if open_count else "checked_clear" if completed_check else "unchecked"),"updated_at":project["updated_at"]})
            return {"projects":result}

    def create_project(self, user_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def create() -> dict[str, Any]:
                title, summary, genre = str(payload.get("title","")).strip(), str(payload.get("summary","")).strip(), str(payload.get("genre","")).strip()
                if not 1 <= len(title) <= 80 or len(summary) > 500:
                    raise DomainError("project_invalid", 422)
                project_id = self._create_project(c,user_id,title,genre,summary,"user_created")
                self._complete_onboarding_for_real_project(c, user_id)
                draft = c.execute("SELECT * FROM v2_drafts WHERE project_id=?", (project_id,)).fetchone()
                return {"project":{"id":project_id,"title":title,"genre":genre,"summary":summary,"status":"active","current_memory_version":1,"author_context_version":0,"foreshadow_version":0,"current_draft":{"id":draft["id"],"chapter_number":1,"revision":1,"status":"draft"}},"created_resources":{"outline":True,"characters":True,"world":True}}
            return self._idem(c,user_id,"create_project",key,payload,create,201)

    def project(self, user_id: str, project_id: str) -> dict[str, Any]:
        with self.connection() as c:
            project = self._project(c,user_id,project_id)
            draft = c.execute("SELECT id,chapter_number,revision,status FROM v2_drafts WHERE project_id=? AND status IN ('draft','saved') ORDER BY saved_at DESC LIMIT 1", (project_id,)).fetchone()
            run = c.execute("SELECT id,status,created_at,result_origin FROM v2_runs WHERE project_id=? AND run_type IN ('continuity','memory_delta') ORDER BY created_at DESC,rowid DESC LIMIT 1", (project_id,)).fetchone()
            open_count=c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=? AND status='open'",(project_id,)).fetchone()[0]
            return {"id":project["id"],"title":project["title"],"genre":project["genre"],"summary":project["summary"],"status":project["status"],"metadata_revision":project["metadata_revision"],"author_context_version":project["author_context_version"],"foreshadow_version":project["foreshadow_version"],"chapter_count":c.execute("SELECT COUNT(*) FROM v2_chapters WHERE project_id=?",(project_id,)).fetchone()[0],"outline_progress":0,"current_memory_version":project["current_memory_version"],"source_revision":project["source_revision"],"current_draft":dict(draft) if draft else None,"latest_run":({"run_id":run["id"],"status":run["status"],"created_at":run["created_at"],"result_origin":run["result_origin"]} if run else None),"open_issue_count":open_count,"continuity_status":("pending" if open_count else "checked_clear" if run and run["status"]=="completed" else "unchecked"),"updated_at":project["updated_at"],"data_origin":project["data_origin"],"is_tutorial":project["data_origin"]=="tutorial_seed","memory_initialization_status":self._memory_initialization_status(c,project_id,project["data_origin"]) }

    # --- v1.3 author intent: independent from confirmed Story Memory ---
    _AUTHOR_INTENT = {
        "story": {
            "table": "v2_author_story_plans", "collection": "story_plans", "prefix": "storyplan",
            "fields": ("title", "summary", "goal", "status", "target_chapter_number"),
            "required": ("title", "status"),
            "snapshot_table": "v2_author_story_plan_versions",
            "snapshot_fields": ("id","title","summary","goal","position","status","target_chapter_number","archived_at","created_at","updated_at"),
        },
        "character": {
            "table": "v2_author_character_plans", "collection": "character_plans", "prefix": "characterplan",
            "fields": ("name", "role_type", "goal", "planned_state", "notes"),
            "required": ("name", "role_type"),
            "snapshot_table": "v2_author_character_plan_versions",
            "snapshot_fields": ("id","name","role_type","goal","planned_state","notes","position","archived_at","created_at","updated_at"),
        },
        "world": {
            "table": "v2_author_world_plans", "collection": "world_plans", "prefix": "worldplan",
            "fields": ("name", "category", "description", "notes"),
            "required": ("name", "category", "description"),
            "snapshot_table": "v2_author_world_plan_versions",
            "snapshot_fields": ("id","name","category","description","notes","position","archived_at","created_at","updated_at"),
        },
    }

    @classmethod
    def _empty_author_context_payload(cls) -> dict[str, list[dict[str, Any]]]:
        return {spec["collection"]:[] for spec in cls._AUTHOR_INTENT.values()}

    @staticmethod
    def _author_snapshot_digest(version: int, parent_version: int | None, payload: dict[str, Any]) -> str:
        return digest({"version":version,"parent_version":parent_version,"snapshot":payload})

    @classmethod
    def _live_author_context_payload(cls, c: sqlite3.Connection, project_id: str) -> dict[str, list[dict[str, Any]]]:
        payload={}
        for spec in cls._AUTHOR_INTENT.values():
            rows=c.execute(f"SELECT * FROM {spec['table']} WHERE project_id=? ORDER BY position,id",(project_id,)).fetchall()
            payload[spec["collection"]]=[{field:row[field] for field in spec["snapshot_fields"]} for row in rows]
        return payload

    @classmethod
    def _stored_author_context_payload(cls, c: sqlite3.Connection, project_id: str, version: int) -> dict[str, list[dict[str, Any]]]:
        payload={}
        for spec in cls._AUTHOR_INTENT.values():
            rows=c.execute(f"SELECT * FROM {spec['snapshot_table']} WHERE project_id=? AND version=? ORDER BY position,item_id",(project_id,version)).fetchall()
            payload[spec["collection"]]=[{field:(row["item_id"] if field=="id" else row[field]) for field in spec["snapshot_fields"]} for row in rows]
        return payload

    @classmethod
    def _insert_empty_author_context_zero(cls, c: sqlite3.Connection, project_id: str, stamp: str) -> sqlite3.Row:
        empty_digest=cls._author_snapshot_digest(0,None,cls._empty_author_context_payload())
        existing=c.execute("SELECT * FROM v2_author_context_versions WHERE project_id=? AND version=0",(project_id,)).fetchone()
        if existing:
            if existing["parent_version"] is not None or existing["snapshot_digest"]!=empty_digest:
                raise DomainError("author_context_snapshot_invalid",409)
            return existing
        c.execute("INSERT INTO v2_author_context_versions(project_id,version,parent_version,snapshot_digest,created_at) VALUES(?,0,NULL,?,?)",(project_id,empty_digest,stamp))
        return c.execute("SELECT * FROM v2_author_context_versions WHERE project_id=? AND version=0",(project_id,)).fetchone()

    @classmethod
    def _write_author_context_snapshot(cls, c: sqlite3.Connection, project_id: str, version: int, parent_version: int, stamp: str) -> sqlite3.Row:
        if version<1 or parent_version<0 or version<=parent_version:
            raise DomainError("author_context_snapshot_invalid",409)
        if not c.execute("SELECT 1 FROM v2_author_context_versions WHERE project_id=? AND version=?",(project_id,parent_version)).fetchone():
            raise DomainError("author_context_snapshot_unresolvable",409)
        if c.execute("SELECT 1 FROM v2_author_context_versions WHERE project_id=? AND version=?",(project_id,version)).fetchone():
            raise DomainError("author_context_version_conflict",409)
        payload=cls._live_author_context_payload(c,project_id); snapshot_digest=cls._author_snapshot_digest(version,parent_version,payload)
        c.execute("INSERT INTO v2_author_context_versions(project_id,version,parent_version,snapshot_digest,created_at) VALUES(?,?,?,?,?)",(project_id,version,parent_version,snapshot_digest,stamp))
        for spec in cls._AUTHOR_INTENT.values():
            columns=("project_id","version","item_id",*spec["snapshot_fields"][1:])
            for item in payload[spec["collection"]]:
                values=(project_id,version,item["id"],*(item[field] for field in spec["snapshot_fields"][1:]))
                c.execute(f"INSERT INTO {spec['snapshot_table']}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",values)
        return c.execute("SELECT * FROM v2_author_context_versions WHERE project_id=? AND version=?",(project_id,version)).fetchone()

    @classmethod
    def _author_context_version_row(cls, c: sqlite3.Connection, project_id: str, version: int) -> sqlite3.Row | None:
        meta=c.execute("SELECT * FROM v2_author_context_versions WHERE project_id=? AND version=?",(project_id,version)).fetchone()
        if not meta:return None
        if cls._author_snapshot_digest(version,meta["parent_version"],cls._stored_author_context_payload(c,project_id,version))!=meta["snapshot_digest"]:
            raise DomainError("author_context_snapshot_invalid",409)
        return meta

    @classmethod
    def _current_author_context_binding(cls, c: sqlite3.Connection, project: sqlite3.Row) -> tuple[int,str]:
        version=int(project["author_context_version"])
        meta=cls._author_context_version_row(c,project["id"],version)
        if not meta:raise DomainError("author_context_snapshot_unresolvable",409)
        return version,meta["snapshot_digest"]

    @staticmethod
    def _author_item(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["archived"] = item["archived_at"] is not None
        return item

    @staticmethod
    def _require_author_version(project: sqlite3.Row, supplied: int) -> None:
        if supplied != project["author_context_version"]:
            raise DomainError("author_context_version_conflict",409,False,{"current_author_context_version":project["author_context_version"]})

    @classmethod
    def _clean_author_fields(cls, kind: str, payload: dict[str, Any], creating: bool) -> dict[str, Any]:
        spec=cls._AUTHOR_INTENT[kind]; values={}
        limits={"title":120,"name":120,"summary":2000,"goal":2000,"planned_state":2000,"notes":4000,"description":4000}
        enums={"status":{"planned","in_progress","paused","completed"},"role_type":{"protagonist","ally","antagonist","supporting","other"},"category":{"location","organization","rule","object","term","other"}}
        if creating and any(field not in payload for field in spec["required"]):
            raise DomainError("author_intent_invalid",422)
        for field in spec["fields"]:
            if field not in payload: continue
            value=payload[field]
            if field!="target_chapter_number":
                if not isinstance(value,str): raise DomainError("author_intent_invalid",422)
                value=value.strip()
                if len(value)>limits.get(field,120): raise DomainError("author_intent_invalid",422)
            if field in spec["required"] and not value: raise DomainError("author_intent_invalid",422)
            if field in enums and value not in enums[field]: raise DomainError("author_intent_invalid",422)
            if field=="target_chapter_number" and value is not None and (not isinstance(value,int) or isinstance(value,bool) or value<1):
                raise DomainError("author_intent_invalid",422)
            values[field]=value
        return values

    def author_intent(self, user_id: str, project_id: str, include_archived: bool = False, version: int | None = None) -> dict[str, Any]:
        with self.connection() as c:
            project=self._project(c,user_id,project_id)
            selected=int(project["author_context_version"] if version is None else version)
            meta=self._author_context_version_row(c,project_id,selected)
            if not meta:raise DomainError("author_context_version_not_found",404)
            snapshot=self._stored_author_context_payload(c,project_id,selected)
            result={"project_id":project_id,"author_context_version":selected,"version":selected,"parent_version":meta["parent_version"],"snapshot_digest":meta["snapshot_digest"]}
            for spec in self._AUTHOR_INTENT.values():
                rows=snapshot[spec["collection"]]
                result[spec["collection"]]=[{**item,"archived":item["archived_at"] is not None} for item in rows if include_archived or item["archived_at"] is None]
            return result

    def create_author_intent_item(self, user_id: str, project_id: str, kind: str, payload: dict[str, Any], key: str):
        spec=self._AUTHOR_INTENT[kind]
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def create() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                self._require_author_version(project,payload["base_author_context_version"])
                values=self._clean_author_fields(kind,payload,True)
                stamp,item_id=utcnow(),new_id(spec["prefix"])
                position=c.execute(f"SELECT COALESCE(MAX(position),0)+1 FROM {spec['table']} WHERE project_id=? AND archived_at IS NULL",(project_id,)).fetchone()[0]
                fields=("id","project_id",*values.keys(),"position","archived_at","created_at","updated_at")
                params=(item_id,project_id,*values.values(),position,None,stamp,stamp)
                c.execute(f"INSERT INTO {spec['table']}({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",params)
                version=project["author_context_version"]+1
                meta=self._write_author_context_snapshot(c,project_id,version,project["author_context_version"],stamp)
                c.execute("UPDATE v2_projects SET author_context_version=?,updated_at=? WHERE id=?",(version,stamp,project_id))
                item=c.execute(f"SELECT * FROM {spec['table']} WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
                return {"project_id":project_id,"author_context_version":version,"version":version,"parent_version":meta["parent_version"],"snapshot_digest":meta["snapshot_digest"],"item":self._author_item(item)}
            return self._idem(c,user_id,f"author_intent_create:{project_id}:{kind}",key,payload,create,201)

    def update_author_intent_item(self, user_id: str, project_id: str, kind: str, item_id: str, payload: dict[str, Any], key: str):
        spec=self._AUTHOR_INTENT[kind]
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def update() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                self._require_author_version(project,payload["base_author_context_version"])
                item=c.execute(f"SELECT * FROM {spec['table']} WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
                if not item: raise DomainError("resource_not_found",404)
                if item["archived_at"] is not None: raise DomainError("author_intent_item_archived",409)
                values=self._clean_author_fields(kind,payload,False)
                if not values: raise DomainError("author_intent_invalid",422)
                stamp=utcnow(); assignments=",".join(f"{field}=?" for field in values)
                c.execute(f"UPDATE {spec['table']} SET {assignments},updated_at=? WHERE id=? AND project_id=?",(*values.values(),stamp,item_id,project_id))
                version=project["author_context_version"]+1
                meta=self._write_author_context_snapshot(c,project_id,version,project["author_context_version"],stamp)
                c.execute("UPDATE v2_projects SET author_context_version=?,updated_at=? WHERE id=?",(version,stamp,project_id))
                refreshed=c.execute(f"SELECT * FROM {spec['table']} WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
                return {"project_id":project_id,"author_context_version":version,"version":version,"parent_version":meta["parent_version"],"snapshot_digest":meta["snapshot_digest"],"item":self._author_item(refreshed)}
            return self._idem(c,user_id,f"author_intent_update:{project_id}:{kind}:{item_id}",key,payload,update)

    def reorder_author_intent_items(self, user_id: str, project_id: str, kind: str, payload: dict[str, Any], key: str):
        spec=self._AUTHOR_INTENT[kind]
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def reorder() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                self._require_author_version(project,payload["base_author_context_version"])
                ordered=payload["ordered_ids"]
                active=[row["id"] for row in c.execute(f"SELECT id FROM {spec['table']} WHERE project_id=? AND archived_at IS NULL",(project_id,)).fetchall()]
                if len(ordered)!=len(set(ordered)) or set(ordered)!=set(active): raise DomainError("author_intent_reorder_invalid",422)
                stamp=utcnow()
                for position,current_id in enumerate(ordered,1):
                    c.execute(f"UPDATE {spec['table']} SET position=?,updated_at=? WHERE id=? AND project_id=? AND archived_at IS NULL",(position,stamp,current_id,project_id))
                version=project["author_context_version"]+1
                meta=self._write_author_context_snapshot(c,project_id,version,project["author_context_version"],stamp)
                c.execute("UPDATE v2_projects SET author_context_version=?,updated_at=? WHERE id=?",(version,stamp,project_id))
                rows=c.execute(f"SELECT * FROM {spec['table']} WHERE project_id=? AND archived_at IS NULL ORDER BY position,id",(project_id,)).fetchall()
                return {"project_id":project_id,"author_context_version":version,"version":version,"parent_version":meta["parent_version"],"snapshot_digest":meta["snapshot_digest"],spec["collection"]:[self._author_item(row) for row in rows]}
            return self._idem(c,user_id,f"author_intent_reorder:{project_id}:{kind}",key,payload,reorder)

    def archive_author_intent_item(self, user_id: str, project_id: str, kind: str, item_id: str, payload: dict[str, Any], key: str):
        if payload.get("confirm") is not True: raise DomainError("confirmation_required",400)
        spec=self._AUTHOR_INTENT[kind]
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def archive() -> dict[str, Any]:
                project=self._project(c,user_id,project_id,True)
                self._require_author_version(project,payload["base_author_context_version"])
                item=c.execute(f"SELECT * FROM {spec['table']} WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
                if not item: raise DomainError("resource_not_found",404)
                if item["archived_at"] is not None: raise DomainError("author_intent_item_archived",409)
                stamp=utcnow()
                c.execute(f"UPDATE {spec['table']} SET archived_at=?,updated_at=? WHERE id=? AND project_id=?",(stamp,stamp,item_id,project_id))
                active=c.execute(f"SELECT id FROM {spec['table']} WHERE project_id=? AND archived_at IS NULL ORDER BY position,id",(project_id,)).fetchall()
                for position,row in enumerate(active,1): c.execute(f"UPDATE {spec['table']} SET position=? WHERE id=?",(position,row["id"]))
                version=project["author_context_version"]+1
                meta=self._write_author_context_snapshot(c,project_id,version,project["author_context_version"],stamp)
                c.execute("UPDATE v2_projects SET author_context_version=?,updated_at=? WHERE id=?",(version,stamp,project_id))
                archived=c.execute(f"SELECT * FROM {spec['table']} WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
                return {"project_id":project_id,"author_context_version":version,"version":version,"parent_version":meta["parent_version"],"snapshot_digest":meta["snapshot_digest"],"item":self._author_item(archived)}
            return self._idem(c,user_id,f"author_intent_archive:{project_id}:{kind}:{item_id}",key,payload,archive)

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

    @staticmethod
    def _normalized_alias(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC",value).split()).casefold()

    def _character_alias_snapshot(self,c:sqlite3.Connection,project_id:str,character_id:str,include_archived:bool=True)->dict[str,Any]:
        character=c.execute("SELECT id,name FROM v2_characters WHERE id=? AND project_id=?",(character_id,project_id)).fetchone()
        if not character:raise DomainError("resource_not_found",404)
        state=c.execute("SELECT version,updated_at FROM v2_character_alias_state WHERE project_id=? AND character_id=?",(project_id,character_id)).fetchone()
        query="SELECT id,alias,status,created_at,updated_at,archived_at FROM v2_character_aliases WHERE project_id=? AND character_id=?"
        if not include_archived:query+=" AND status='active'"
        rows=c.execute(query+" ORDER BY status,created_at,id",(project_id,character_id)).fetchall()
        return {"project_id":project_id,"character_id":character_id,"primary_name":character["name"],"version":int(state["version"]) if state else 0,"updated_at":state["updated_at"] if state else None,"aliases":[dict(row) for row in rows]}

    def character_aliases(self,user_id:str,project_id:str,character_id:str,include_archived:bool=False)->dict[str,Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            return self._character_alias_snapshot(c,project_id,character_id,include_archived)

    def _write_character_alias(self,user_id:str,project_id:str,character_id:str,payload:dict[str,Any],key:str,operation:str,alias_id:str|None=None):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def write():
                self._project(c,user_id,project_id,True)
                character=c.execute("SELECT id,name FROM v2_characters WHERE id=? AND project_id=?",(character_id,project_id)).fetchone()
                if not character:raise DomainError("resource_not_found",404)
                state=c.execute("SELECT version FROM v2_character_alias_state WHERE project_id=? AND character_id=?",(project_id,character_id)).fetchone()
                current=int(state["version"]) if state else 0
                if payload["base_version"]!=current:raise DomainError("character_alias_version_conflict",409,False,{"current_version":current})
                target=None
                if alias_id:
                    target=c.execute("SELECT * FROM v2_character_aliases WHERE id=? AND project_id=? AND character_id=?",(alias_id,project_id,character_id)).fetchone()
                    if not target:raise DomainError("resource_not_found",404)
                stamp=utcnow()
                if operation in {"create","update"}:
                    alias=" ".join(str(payload["alias"]).split())
                    normalized=self._normalized_alias(alias)
                    if not alias or len(alias)>80:raise DomainError("character_alias_invalid",422)
                    if normalized==self._normalized_alias(character["name"]):raise DomainError("character_alias_duplicate",409)
                    duplicate=c.execute("SELECT id FROM v2_character_aliases WHERE project_id=? AND character_id=? AND normalized_alias=? AND status='active' AND id<>?",(project_id,character_id,normalized,alias_id or "")).fetchone()
                    if duplicate:raise DomainError("character_alias_duplicate",409)
                    active=c.execute("SELECT COUNT(*) FROM v2_character_aliases WHERE project_id=? AND character_id=? AND status='active'",(project_id,character_id)).fetchone()[0]
                    if operation=="create" and active>=20:raise DomainError("character_alias_limit_reached",409)
                    if operation=="create":
                        changed_alias_id=new_id("alias")
                        c.execute("INSERT INTO v2_character_aliases VALUES(?,?,?,?,?,?,?,?,?)",(changed_alias_id,project_id,character_id,alias,normalized,"active",stamp,stamp,None))
                    else:
                        if target["status"]!="active":raise DomainError("character_alias_archived",409)
                        changed_alias_id=alias_id
                        c.execute("UPDATE v2_character_aliases SET alias=?,normalized_alias=?,updated_at=? WHERE id=?",(alias,normalized,stamp,alias_id))
                else:
                    if target["status"]!="active":raise DomainError("character_alias_archived",409)
                    changed_alias_id=alias_id
                    c.execute("UPDATE v2_character_aliases SET status='archived',archived_at=?,updated_at=? WHERE id=?",(stamp,stamp,alias_id))
                version=current+1
                c.execute("INSERT INTO v2_character_alias_state(project_id,character_id,version,updated_at) VALUES(?,?,?,?) ON CONFLICT(project_id,character_id) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at",(project_id,character_id,version,stamp))
                c.execute("UPDATE v2_projects SET alias_version=alias_version+1,updated_at=? WHERE id=?",(stamp,project_id))
                snapshot=self._character_alias_snapshot(c,project_id,character_id,True)
                snapshot["changed_alias_id"]=changed_alias_id
                return snapshot
            return self._idem(c,user_id,f"character_alias_{operation}:{project_id}:{character_id}:{alias_id or ''}",key,payload,write,201 if operation=="create" else 200)

    def create_character_alias(self,user_id:str,project_id:str,character_id:str,payload:dict[str,Any],key:str):return self._write_character_alias(user_id,project_id,character_id,payload,key,"create")
    def update_character_alias(self,user_id:str,project_id:str,character_id:str,alias_id:str,payload:dict[str,Any],key:str):return self._write_character_alias(user_id,project_id,character_id,payload,key,"update",alias_id)
    def archive_character_alias(self,user_id:str,project_id:str,character_id:str,alias_id:str,payload:dict[str,Any],key:str):return self._write_character_alias(user_id,project_id,character_id,payload,key,"archive",alias_id)

    def _current_alias_binding(self,c:sqlite3.Connection,project_id:str)->tuple[int,str,list[dict[str,Any]]]:
        project=c.execute("SELECT alias_version FROM v2_projects WHERE id=?",(project_id,)).fetchone()
        rows=[dict(row) for row in c.execute("SELECT a.id,a.character_id,ch.name primary_name,a.alias,s.version character_alias_version FROM v2_character_aliases a JOIN v2_characters ch ON ch.id=a.character_id AND ch.project_id=a.project_id LEFT JOIN v2_character_alias_state s ON s.project_id=a.project_id AND s.character_id=a.character_id WHERE a.project_id=? AND a.status='active' ORDER BY a.character_id,a.normalized_alias,a.id",(project_id,)).fetchall()]
        version=int(project["alias_version"] or 0)
        return version,digest(rows),rows

    @staticmethod
    def _normalized_foreshadow_title(value:str)->str:
        return " ".join(unicodedata.normalize("NFKC",value).split()).casefold()

    def _foreshadow_reference(self,c:sqlite3.Connection,project_id:str,chapter_id:str|None,source_span_id:str|None)->dict[str,Any]|None:
        if source_span_id:
            row=c.execute("SELECT s.id,s.label,s.chapter_id,ch.chapter_number,ch.title chapter_title FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id WHERE s.id=? AND s.project_id=?",(source_span_id,project_id)).fetchone()
            if not row or (chapter_id and chapter_id!=row["chapter_id"]):raise DomainError("foreshadow_reference_invalid",422)
            return {"chapter_id":row["chapter_id"],"chapter_number":row["chapter_number"],"chapter_title":row["chapter_title"],"source_span_id":row["id"],"source_label":row["label"],"source_path":f"/projects/{project_id}/sources#span-{row['id']}"}
        if chapter_id:
            row=c.execute("SELECT id,chapter_number,title FROM v2_chapters WHERE id=? AND project_id=?",(chapter_id,project_id)).fetchone()
            if not row:raise DomainError("foreshadow_reference_invalid",422)
            return {"chapter_id":row["id"],"chapter_number":row["chapter_number"],"chapter_title":row["title"],"source_span_id":None,"source_label":None,"source_path":f"/projects/{project_id}/sources#chapter-{row['id']}"}
        return None

    def _foreshadow_item(self,c:sqlite3.Connection,row:sqlite3.Row|dict[str,Any])->dict[str,Any]:
        item=dict(row)
        planted=self._foreshadow_reference(c,item["project_id"],item.get("planted_chapter_id"),item.get("planted_source_span_id"))
        resolved=self._foreshadow_reference(c,item["project_id"],item.get("resolved_chapter_id"),item.get("resolved_source_span_id"))
        return {"id":item["id"],"project_id":item["project_id"],"title":item["title"],"description":item["description"],"status":item["status"],"version":item["version"],"planted":planted,"resolved":resolved,"archived_at":item.get("archived_at"),"created_at":item["created_at"],"updated_at":item["updated_at"]}

    def _foreshadow_snapshot(self,c:sqlite3.Connection,project_id:str,include_archived:bool=False)->dict[str,Any]:
        project=c.execute("SELECT foreshadow_version FROM v2_projects WHERE id=?",(project_id,)).fetchone()
        query="SELECT * FROM v2_foreshadows WHERE project_id=?"
        if not include_archived:query+=" AND archived_at IS NULL"
        rows=c.execute(query+" ORDER BY archived_at IS NOT NULL,status,updated_at DESC,id",(project_id,)).fetchall()
        return {"project_id":project_id,"foreshadow_version":int(project["foreshadow_version"] or 0),"records":[self._foreshadow_item(c,row) for row in rows]}

    def foreshadows(self,user_id:str,project_id:str,include_archived:bool=False)->dict[str,Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            return self._foreshadow_snapshot(c,project_id,include_archived)

    def _validate_foreshadow_payload(self,c:sqlite3.Connection,project_id:str,payload:dict[str,Any])->dict[str,Any]:
        title=" ".join(str(payload.get("title") or "").split())
        description=str(payload.get("description") or "").strip()
        status=payload.get("status")
        if not 1<=len(title)<=120 or not 1<=len(description)<=1200 or status not in FORESHADOW_STATUSES:raise DomainError("foreshadow_invalid",422)
        planted=self._foreshadow_reference(c,project_id,payload.get("planted_chapter_id"),payload.get("planted_source_span_id"))
        resolved=self._foreshadow_reference(c,project_id,payload.get("resolved_chapter_id"),payload.get("resolved_source_span_id"))
        return {"title":title,"normalized_title":self._normalized_foreshadow_title(title),"description":description,"status":status,"planted_chapter_id":planted["chapter_id"] if planted else None,"planted_source_span_id":planted["source_span_id"] if planted else None,"resolved_chapter_id":resolved["chapter_id"] if resolved else None,"resolved_source_span_id":resolved["source_span_id"] if resolved else None}

    def _record_foreshadow_version(self,c:sqlite3.Connection,row:sqlite3.Row|dict[str,Any],event:str,user_id:str,stamp:str)->None:
        item=dict(row)
        snapshot={key:item.get(key) for key in ("id","project_id","title","description","status","planted_chapter_id","planted_source_span_id","resolved_chapter_id","resolved_source_span_id","version","archived_at","created_at","updated_at")}
        c.execute("INSERT INTO v2_foreshadow_versions VALUES(?,?,?,?,?,?,?)",(item["id"],item["project_id"],item["version"],json.dumps(snapshot,ensure_ascii=False,sort_keys=True),event,user_id,stamp))

    def create_foreshadow(self,user_id:str,project_id:str,payload:dict[str,Any],key:str):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def create():
                project=self._project(c,user_id,project_id,True)
                current=int(project["foreshadow_version"] or 0)
                if payload["base_foreshadow_version"]!=current:raise DomainError("foreshadow_version_conflict",409,False,{"current_version":current})
                if current>=MAX_RESOURCE_VERSION:raise DomainError("foreshadow_version_limit",409)
                if c.execute("SELECT COUNT(*) FROM v2_foreshadows WHERE project_id=? AND archived_at IS NULL",(project_id,)).fetchone()[0]>=FORESHADOW_MAX_RECORDS:raise DomainError("foreshadow_limit_reached",409)
                values=self._validate_foreshadow_payload(c,project_id,payload)
                if c.execute("SELECT 1 FROM v2_foreshadows WHERE project_id=? AND normalized_title=? AND archived_at IS NULL",(project_id,values["normalized_title"])).fetchone():raise DomainError("foreshadow_duplicate",409)
                item_id,stamp=new_id("foreshadow"),utcnow()
                c.execute("INSERT INTO v2_foreshadows VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(item_id,project_id,values["title"],values["normalized_title"],values["description"],values["status"],values["planted_chapter_id"],values["planted_source_span_id"],values["resolved_chapter_id"],values["resolved_source_span_id"],1,None,stamp,stamp))
                row=c.execute("SELECT * FROM v2_foreshadows WHERE id=?",(item_id,)).fetchone();self._record_foreshadow_version(c,row,"created",user_id,stamp)
                c.execute("UPDATE v2_projects SET foreshadow_version=foreshadow_version+1,updated_at=? WHERE id=?",(stamp,project_id))
                return {**self._foreshadow_snapshot(c,project_id,True),"item":self._foreshadow_item(c,row)}
            return self._idem(c,user_id,f"foreshadow_create:{project_id}",key,payload,create,201)

    def update_foreshadow(self,user_id:str,project_id:str,item_id:str,payload:dict[str,Any],key:str):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def update():
                project=self._project(c,user_id,project_id,True)
                row=c.execute("SELECT * FROM v2_foreshadows WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
                if not row:raise DomainError("resource_not_found",404)
                if row["archived_at"]:raise DomainError("foreshadow_archived",409)
                if payload["base_version"]!=row["version"]:raise DomainError("foreshadow_version_conflict",409,False,{"current_version":row["version"]})
                if row["version"]>=MAX_RESOURCE_VERSION or int(project["foreshadow_version"] or 0)>=MAX_RESOURCE_VERSION:raise DomainError("foreshadow_version_limit",409)
                provided={key:value for key,value in payload.items() if key!="base_version"}
                if not provided:raise DomainError("foreshadow_invalid",422)
                merged={key:row[key] for key in ("title","description","status","planted_chapter_id","planted_source_span_id","resolved_chapter_id","resolved_source_span_id")}
                merged.update(provided);values=self._validate_foreshadow_payload(c,project_id,merged)
                duplicate=c.execute("SELECT 1 FROM v2_foreshadows WHERE project_id=? AND normalized_title=? AND archived_at IS NULL AND id<>?",(project_id,values["normalized_title"],item_id)).fetchone()
                if duplicate:raise DomainError("foreshadow_duplicate",409)
                stamp=utcnow();version=row["version"]+1
                c.execute("UPDATE v2_foreshadows SET title=?,normalized_title=?,description=?,status=?,planted_chapter_id=?,planted_source_span_id=?,resolved_chapter_id=?,resolved_source_span_id=?,version=?,updated_at=? WHERE id=?",(values["title"],values["normalized_title"],values["description"],values["status"],values["planted_chapter_id"],values["planted_source_span_id"],values["resolved_chapter_id"],values["resolved_source_span_id"],version,stamp,item_id))
                changed=c.execute("SELECT * FROM v2_foreshadows WHERE id=?",(item_id,)).fetchone();self._record_foreshadow_version(c,changed,"updated",user_id,stamp)
                c.execute("UPDATE v2_projects SET foreshadow_version=foreshadow_version+1,updated_at=? WHERE id=?",(stamp,project_id))
                return {**self._foreshadow_snapshot(c,project_id,True),"item":self._foreshadow_item(c,changed)}
            return self._idem(c,user_id,f"foreshadow_update:{project_id}:{item_id}",key,payload,update)

    def archive_foreshadow(self,user_id:str,project_id:str,item_id:str,payload:dict[str,Any],key:str):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def archive():
                project=self._project(c,user_id,project_id,True)
                row=c.execute("SELECT * FROM v2_foreshadows WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
                if not row:raise DomainError("resource_not_found",404)
                if row["archived_at"]:raise DomainError("foreshadow_archived",409)
                if payload["base_version"]!=row["version"]:raise DomainError("foreshadow_version_conflict",409,False,{"current_version":row["version"]})
                if row["version"]>=MAX_RESOURCE_VERSION or int(project["foreshadow_version"] or 0)>=MAX_RESOURCE_VERSION:raise DomainError("foreshadow_version_limit",409)
                stamp=utcnow();version=row["version"]+1
                c.execute("UPDATE v2_foreshadows SET version=?,archived_at=?,updated_at=? WHERE id=?",(version,stamp,stamp,item_id))
                changed=c.execute("SELECT * FROM v2_foreshadows WHERE id=?",(item_id,)).fetchone();self._record_foreshadow_version(c,changed,"archived",user_id,stamp)
                c.execute("UPDATE v2_projects SET foreshadow_version=foreshadow_version+1,updated_at=? WHERE id=?",(stamp,project_id))
                return {**self._foreshadow_snapshot(c,project_id,True),"item":self._foreshadow_item(c,changed)}
            return self._idem(c,user_id,f"foreshadow_archive:{project_id}:{item_id}",key,payload,archive)

    def _current_foreshadow_binding(self,c:sqlite3.Connection,project_id:str)->tuple[int,str,list[dict[str,Any]]]:
        project=c.execute("SELECT foreshadow_version FROM v2_projects WHERE id=?",(project_id,)).fetchone()
        rows=[dict(row) for row in c.execute("SELECT id,title,description,status,planted_chapter_id,planted_source_span_id,resolved_chapter_id,resolved_source_span_id,version FROM v2_foreshadows WHERE project_id=? AND archived_at IS NULL ORDER BY normalized_title,id",(project_id,)).fetchall()]
        return int(project["foreshadow_version"] or 0),digest(rows),rows

    @staticmethod
    def _normalized_revision_task_title(value:str)->str:
        return re.sub(r"\s+","",value).casefold()

    def _validate_revision_task_fields(self,payload:dict[str,Any])->dict[str,Any]:
        title=" ".join(str(payload.get("title") or "").split());instruction=str(payload.get("instruction") or "").strip();priority=payload.get("priority")
        if not 1<=len(title)<=120 or not 1<=len(instruction)<=1200 or priority not in REVISION_TASK_PRIORITIES:raise DomainError("revision_task_invalid",422)
        return {"title":title,"normalized_title":self._normalized_revision_task_title(title),"instruction":instruction,"priority":priority}

    @staticmethod
    def _revision_task_item(row:sqlite3.Row|dict[str,Any])->dict[str,Any]:
        item=dict(row)
        return {key:item[key] for key in ("id","project_id","source_run_id","candidate_id","issue_id","title","instruction","priority","position","status","version","created_at","updated_at")}|{"evidence":json.loads(item.get("evidence_json") or "[]")}

    def _revision_task_snapshot(self,c:sqlite3.Connection,project_id:str,include_completed:bool=True)->dict[str,Any]:
        project=c.execute("SELECT revision_task_version FROM v2_projects WHERE id=?",(project_id,)).fetchone()
        query="SELECT t.*,c.evidence_json FROM v2_revision_tasks t JOIN v2_revision_plan_candidates c ON c.id=t.candidate_id WHERE t.project_id=?"
        args:list[Any]=[project_id]
        if not include_completed:query+=" AND t.status!='completed'"
        query+=" ORDER BY CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,t.position,t.created_at,t.id"
        rows=c.execute(query,args).fetchall()
        return {"project_id":project_id,"task_version":int(project["revision_task_version"] or 0),"tasks":[self._revision_task_item(row) for row in rows]}

    def revision_tasks(self,user_id:str,project_id:str,include_completed:bool=True)->dict[str,Any]:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            return self._revision_task_snapshot(c,project_id,include_completed)

    def _record_revision_task_version(self,c:sqlite3.Connection,row:sqlite3.Row,event:str,user_id:str,stamp:str)->None:
        item=dict(row);snapshot={key:item[key] for key in ("id","source_run_id","candidate_id","issue_id","title","instruction","priority","position","status","version","created_at","updated_at")}
        c.execute("INSERT INTO v2_revision_task_versions VALUES(?,?,?,?,?,?,?)",(item["id"],item["project_id"],item["version"],json.dumps(snapshot,ensure_ascii=False,sort_keys=True),event,user_id,stamp))

    def update_revision_task(self,user_id:str,project_id:str,task_id:str,payload:dict[str,Any],key:str):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def update():
                project=self._project(c,user_id,project_id,True)
                row=c.execute("SELECT * FROM v2_revision_tasks WHERE id=? AND project_id=?",(task_id,project_id)).fetchone()
                if not row:raise DomainError("resource_not_found",404)
                if payload["base_version"]!=row["version"]:raise DomainError("revision_task_version_conflict",409,False,{"current_version":row["version"]})
                if row["version"]>=MAX_RESOURCE_VERSION or int(project["revision_task_version"] or 0)>=MAX_RESOURCE_VERSION:raise DomainError("revision_task_version_limit",409)
                status=payload.get("status")
                if status not in REVISION_TASK_STATUSES or status==row["status"]:raise DomainError("revision_task_status_invalid",422)
                if row["status"]=="completed" and status!="completed":
                    if c.execute("SELECT COUNT(*) FROM v2_revision_tasks WHERE project_id=? AND status!='completed'",(project_id,)).fetchone()[0]>=REVISION_TASK_MAX_RECORDS:raise DomainError("revision_task_limit_reached",409)
                    if c.execute("SELECT 1 FROM v2_revision_tasks WHERE project_id=? AND normalized_title=? AND status!='completed' AND id<>?",(project_id,row["normalized_title"],task_id)).fetchone():raise DomainError("revision_task_duplicate",409)
                stamp=utcnow();version=row["version"]+1
                c.execute("UPDATE v2_revision_tasks SET status=?,version=?,updated_at=? WHERE id=? AND project_id=?",(status,version,stamp,task_id,project_id))
                changed=c.execute("SELECT * FROM v2_revision_tasks WHERE id=?",(task_id,)).fetchone();self._record_revision_task_version(c,changed,"status_"+status,user_id,stamp)
                c.execute("UPDATE v2_projects SET revision_task_version=revision_task_version+1,updated_at=? WHERE id=?",(stamp,project_id))
                return {**self._revision_task_snapshot(c,project_id,True),"item":self._revision_task_item({**dict(changed),"evidence_json":c.execute("SELECT evidence_json FROM v2_revision_plan_candidates WHERE id=?",(changed["candidate_id"],)).fetchone()[0]})}
            return self._idem(c,user_id,f"revision_task_update:{project_id}:{task_id}",key,payload,update)

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
            confirmed=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?)",(project_id,project["current_memory_version"],project["current_memory_version"],project["current_memory_version"])).fetchone()[0]
            if delta["status"] != "covered":
                return {"project_id":project_id,"status":"update_pending","source_revision":delta["source_revision"],"memory_version":project["current_memory_version"],"counts":{"core_pending":core_pending,"supporting_pending":supporting_pending,"confirmed":confirmed,"confirmed_core":confirmed_core,"pending_canon_count":0},"blocking_reason":delta["error_code"] or "delta_core_review_required"}
            return {"project_id":project_id,"status":"ready_partial" if supporting_pending else "ready_current","source_revision":delta["source_revision"],"memory_version":project["current_memory_version"],"counts":{"core_pending":0,"supporting_pending":supporting_pending,"confirmed":confirmed,"confirmed_core":confirmed_core,"pending_canon_count":0},"blocking_reason":"none"}
        if c.execute("SELECT source_revision FROM v2_projects WHERE id=?",(project_id,)).fetchone()[0] > 1:
            return {"project_id":project_id,"status":"update_pending","source_revision":c.execute("SELECT source_revision FROM v2_projects WHERE id=?",(project_id,)).fetchone()[0],"memory_version":project["current_memory_version"],"counts":{"core_pending":0,"supporting_pending":0,"confirmed":0,"confirmed_core":0,"pending_canon_count":0},"blocking_reason":"delta_review_required"}
        initialization=c.execute("SELECT * FROM v2_memory_initializations WHERE project_id=? AND source_revision=1",(project_id,)).fetchone()
        if not initialization:
            confirmed=c.execute("SELECT COUNT(*) FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?)",(project_id,project["current_memory_version"],project["current_memory_version"],project["current_memory_version"])).fetchone()[0]
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
        return [dict(row) for row in c.execute("SELECT id,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?) ORDER BY id",(project_id,version,version,version)).fetchall()]

    def _delta_priority(self,item,confirmed):
        if item.get("change_kind") in {"changed_fact","invalidated_fact"}:return "core"
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
            identity=(item.get("change_kind","new_fact"),item.get("affected_memory_id"),self._normalize(item["memory_type"]),self._normalize(item["subject"]),normalized_predicate(item["predicate"],allow_legacy_alias=False),self._normalize(item["value"]))
            duplicate=identity in seen
            priority="supporting" if duplicate else self._delta_priority(item,confirmed)
            seen.add(identity); result.append(priority)
        return result

    def _validate_delta_candidates_against_memory(self,items,confirmed):
        by_id={row["id"]:row for row in confirmed}; by_key={self._candidate_key(row["memory_type"],row["subject"],row["predicate"],allow_legacy_alias=False):row for row in confirmed}
        affected=set(); targets=set()
        for item in items:
            kind=item.get("change_kind"); memory_id=item.get("affected_memory_id"); key=self._candidate_key(item["memory_type"],item["subject"],item["predicate"],allow_legacy_alias=False)
            if kind=="new_fact":
                if memory_id is not None or key in by_key:raise DomainError("candidate_conflict",422)
            elif kind in {"changed_fact","invalidated_fact"}:
                before=by_id.get(memory_id)
                if not before:raise DomainError("affected_memory_unresolvable",422)
                if memory_id in affected:raise DomainError("duplicate_candidate",422)
                affected.add(memory_id)
                before_fact={field:str(before[field]).strip() for field in ("memory_type","subject","predicate","value")}
                if kind=="invalidated_fact" and any(str(item[field]).strip()!=before_fact[field] for field in before_fact):raise DomainError("candidate_conflict",422)
                if kind=="changed_fact":
                    collision=by_key.get(key)
                    if collision and collision["id"]!=memory_id:raise DomainError("candidate_conflict",422)
            else:raise DomainError("change_kind_invalid",422)
            target=(kind,memory_id,key,self._normalize(item["value"]))
            if target in targets:raise DomainError("duplicate_candidate",422)
            targets.add(target)

    def _coverage_audit_view(self,c,project_id,row):
        return {"id":row["id"],"project_id":project_id,"source_revision":row["source_revision"],"status":row["status"],"memory_version":row["memory_version"],"delta_batch_id":row["delta_batch_id"],"actor_user_id":row["actor_user_id"],"details":json.loads(row["details_json"] or "{}"),"created_at":row["created_at"]}

    def _delta_memory_view(self,c,project_id,version,memory_id):
        row=c.execute("SELECT m.*,s.chapter_id,s.body excerpt,ch.chapter_number,ch.title chapter_title FROM v2_memory_records m LEFT JOIN v2_source_spans s ON s.id=m.source_span_id AND s.project_id=m.project_id LEFT JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=m.project_id WHERE m.id=? AND m.project_id=? AND m.version=? AND m.review_status='author_confirmed'",(memory_id,project_id,version)).fetchone()
        if not row or (row["valid_from"] is not None and row["valid_from"]>version) or (row["valid_to"] is not None and row["valid_to"]<version):raise DomainError("affected_memory_unresolvable",422)
        if row["source_span_id"] and not row["chapter_id"]:raise DomainError("evidence_unresolvable",422)
        return {"id":row["id"],"memory_type":row["memory_type"],"subject":row["subject"],"predicate":row["predicate"],"value":row["value"],"valid_from":row["valid_from"],"valid_to":row["valid_to"],"review_status":row["review_status"],"source":({"chapter_id":row["chapter_id"],"chapter_number":row["chapter_number"],"chapter_title":row["chapter_title"],"span_id":row["source_span_id"],"excerpt":row["excerpt"][:500],"source_path":f"/projects/{project_id}/sources#span-{row['source_span_id']}"} if row["source_span_id"] else None)}

    def _delta_change_set_view(self,c,project_id,batch):
        row=c.execute("SELECT * FROM v2_change_sets WHERE project_id=? AND run_id=? AND change_set_kind='memory_delta' ORDER BY created_at DESC LIMIT 1",(project_id,batch["memory_delta_run_id"])).fetchone()
        if not row:return None
        ordinals={candidate["id"]:candidate["candidate_ordinal"] for candidate in c.execute("SELECT id,candidate_ordinal FROM v2_memory_delta_candidates WHERE project_id=? AND batch_id=?",(project_id,batch["id"])).fetchall()}; items=[]
        for item in c.execute("SELECT * FROM v2_change_set_items WHERE project_id=? AND change_set_id=? ORDER BY id",(project_id,row["id"])).fetchall():
            items.append({"id":item["id"],"operation":item["operation"],"before":json.loads(item["before_json"]) if item["before_json"] else None,"after":json.loads(item["after_json"]),"source_ids":json.loads(item["source_ids_json"]),"decision_ids":json.loads(item["decision_ids_json"]),"review_status":item["review_status"],"committed_after":json.loads(item["committed_after_json"]) if item["committed_after_json"] else None})
        items.sort(key=lambda item:(ordinals.get(item["after"].get("candidate_id"),10**9),item["id"]))
        return {"id":row["id"],"project_id":project_id,"change_set_kind":row["change_set_kind"],"status":row["status"],"base_memory_version":row["base_version"],"target_memory_version":row["target_version"],"source_revision":row["source_run_revision"],"run_id":row["run_id"],"batch_id":batch["id"],"actor_user_id":row["actor_user_id"],"created_at":row["created_at"],"committed_at":row["committed_at"],"items":items}

    def _delta_view(self,c,project_id,batch):
        sources={row["id"]:row for row in self._delta_sources(c,project_id,batch["source_revision"])}; items=[]
        for row in c.execute("SELECT * FROM v2_memory_delta_candidates WHERE batch_id=? AND project_id=? ORDER BY candidate_ordinal,id",(batch["id"],project_id)).fetchall():
            source=sources.get(row["source_span_id"])
            if not source or source["chapter_id"]!=row["chapter_id"]: raise DomainError("evidence_unresolvable",422)
            before=self._delta_memory_view(c,project_id,batch["base_memory_version"],row["affected_memory_id"]) if row["affected_memory_id"] else None
            fact={field:row[field] for field in ("memory_type","subject","predicate","value")}
            items.append({"id":row["id"],"change_kind":row["change_kind"],"affected_memory_id":row["affected_memory_id"],"invalidation_reason":row["invalidation_reason"],**fact,"before":before,"after":fact if row["change_kind"]!="invalidated_fact" else None,"candidate_origin":"delta","review_priority":row["review_priority"],"decision_status":row["decision_status"],"decision":json.loads(row["decision_json"]) if row["decision_json"] else None,"source_revision":row["source_revision"],"source":{"chapter_id":source["chapter_id"],"chapter_number":source["chapter_number"],"chapter_title":source["chapter_title"],"span_id":source["id"],"label":source["label"],"excerpt":source["body"][:500],"source_path":f"/projects/{project_id}/sources#span-{source['id']}"}})
        audit=c.execute("SELECT * FROM v2_source_coverage_audits WHERE project_id=? AND delta_batch_id=?",(project_id,batch["id"])).fetchone()
        retrieval=json.loads(batch["retrieval_json"] or "{}") if "retrieval_json" in batch.keys() else {}
        return {"id":batch["id"],"project_id":project_id,"source_revision":batch["source_revision"],"base_memory_version":batch["base_memory_version"],"status":batch["status"],"error_code":batch["error_code"],"continuity_run_id":batch["continuity_run_id"],"memory_delta_run_id":batch["memory_delta_run_id"],"candidates":items,"retrieval":retrieval,"change_set":self._delta_change_set_view(c,project_id,batch),"coverage":self._memory_coverage(c,project_id),"coverage_audit":self._coverage_audit_view(c,project_id,audit) if audit else None}

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
                if existing and existing["status"] not in {"failed","cancelled","timed_out"}:
                    if existing["status"]=="in_review" and existing["base_memory_version"]!=project["current_memory_version"]:
                        c.execute("DELETE FROM v2_memory_delta_decisions WHERE project_id=? AND batch_id=?",(project_id,existing["id"]));c.execute("DELETE FROM v2_memory_delta_candidates WHERE project_id=? AND batch_id=?",(project_id,existing["id"]))
                    else:return {"delta":self._delta_view(c,project_id,existing)}
                draft=c.execute("SELECT * FROM v2_drafts WHERE project_id=? AND status IN ('draft','saved') ORDER BY saved_at DESC LIMIT 1",(project_id,)).fetchone()
                if not draft: raise DomainError("draft_invalid",422)
                change=c.execute("SELECT id FROM v2_source_change_sets WHERE project_id=? AND target_source_revision=? AND status='committed' ORDER BY committed_at DESC LIMIT 1",(project_id,revision)).fetchone()
                spans=self._delta_sources(c,project_id,revision)
                if not change or not spans: raise DomainError("source_lineage_not_available",409)
                stamp,batch_id,continuity_id,delta_id=utcnow(),new_id("memorydelta"),new_id("run"),new_id("run")
                author_version,author_digest=self._current_author_context_binding(c,project)
                prior={}
                if existing:
                    batch_id=existing["id"]
                    prior={row["run_type"]:row for row in c.execute("SELECT * FROM v2_runs WHERE id IN (?,?)",(existing["continuity_run_id"],existing["memory_delta_run_id"])).fetchall()}
                for run_id,kind,prov in ((continuity_id,"continuity",continuity_provenance),(delta_id,"memory_delta",delta_provenance)):
                    previous=prior.get(kind); root=(previous["root_run_id"] or previous["id"]) if previous else run_id; attempt=(previous["attempt_number"]+1) if previous else 1
                    c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,run_type,source_change_set_id,source_span_ids_json,retry_of_run_id,root_run_id,attempt_number,incremental_batch_id,author_context_version,author_context_snapshot_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,project_id,draft["id"],revision,"queued","queued",prov["provider_label"],stamp,prov["model_label"],prov["prompt_version"],prov["schema_version"],prov["retrieval_method_version"],project["current_memory_version"],"provider",kind,change["id"],json.dumps([row["id"] for row in spans]),previous["id"] if previous else None,root,attempt,batch_id,author_version,author_digest)); self._append_run_event(c,run_id,"queued","queued",None,stamp)
                if existing:
                    c.execute("UPDATE v2_memory_delta_batches SET base_memory_version=?,continuity_run_id=?,memory_delta_run_id=?,status='processing',error_code=NULL,created_at=?,completed_at=NULL,covered_at=NULL,retrieval_json='{}' WHERE id=?",(project["current_memory_version"],continuity_id,delta_id,stamp,batch_id))
                else: c.execute("INSERT INTO v2_memory_delta_batches(id,project_id,source_revision,base_memory_version,continuity_run_id,memory_delta_run_id,status,error_code,created_at,completed_at,covered_at,retrieval_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(batch_id,project_id,revision,project["current_memory_version"],continuity_id,delta_id,"processing",None,stamp,None,None,"{}"))
                return {"delta":self._delta_view(c,project_id,c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=?",(batch_id,)).fetchone()),"continuity_run_id":continuity_id,"memory_delta_run_id":delta_id,"batch_id":batch_id}
            return self._idem(c,user_id,"incremental_runs:"+project_id,key,payload,create,202,with_created=True)

    def incremental_inputs(self,project_id,batch_id):
        with self.connection() as c:
            batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=? AND project_id=?",(batch_id,project_id)).fetchone()
            if not batch: raise DomainError("resource_not_found",404)
            sources=self._delta_sources(c,project_id,batch["source_revision"]); memory=self._confirmed_memory(c,project_id,batch["base_memory_version"])
            historical={row["id"]:dict(row) for row in c.execute("SELECT s.id,s.chapter_id,s.label,s.body,ch.chapter_number,ch.title chapter_title FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id WHERE s.project_id=? AND s.id IN (SELECT source_span_id FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND source_span_id IS NOT NULL AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?))",(project_id,project_id,batch["base_memory_version"],batch["base_memory_version"],batch["base_memory_version"])).fetchall()}
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
            self._validate_delta_candidates_against_memory(delta["candidates"],delta_input["memory"])
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
                c.execute("INSERT INTO v2_memory_delta_candidates(id,project_id,batch_id,source_revision,candidate_ordinal,memory_type,subject,predicate,value,chapter_id,source_span_id,candidate_origin,review_priority,decision_status,decision_json,decided_at,change_kind,affected_memory_id,invalidation_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(new_id("memorydeltacandidate"),project_id,batch_id,batch["source_revision"],ordinal,item["memory_type"],item["subject"],item["predicate"],item["value"],source["chapter_id"],source["id"],"delta",priority,"pending",None,None,item["change_kind"],item.get("affected_memory_id"),item.get("invalidation_reason")))
            c.execute("UPDATE v2_memory_delta_batches SET status='in_review',completed_at=?,retrieval_json=? WHERE id=?",(stamp,json.dumps(delta.get("retrieval",{}),ensure_ascii=False),batch_id))
            return True

    def decide_memory_delta_candidate(self,user_id,project_id,batch_id,candidate_id,payload,key):
        with self.connection() as c:
            def decide():
                project=self._project(c,user_id,project_id,True); batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=? AND project_id=?",(batch_id,project_id)).fetchone(); row=c.execute("SELECT * FROM v2_memory_delta_candidates WHERE id=? AND batch_id=? AND project_id=?",(candidate_id,batch_id,project_id)).fetchone()
                if not batch or not row: raise DomainError("resource_not_found",404)
                if batch["status"]!="in_review": raise DomainError("memory_delta_closed",409)
                if project["source_revision"]!=batch["source_revision"] or project["current_memory_version"]!=batch["base_memory_version"]:raise DomainError("memory_delta_stale",409)
                decision=payload.get("decision"); base={key:row[key] for key in ("memory_type","subject","predicate","value")}; after=base; evidence=None
                if decision not in {"accepted","rejected","edited"}: raise DomainError("invalid_candidate_decision",422)
                if row["decision_status"]!="pending":
                    saved=json.loads(row["decision_json"] or "{}")
                    same_plain=saved.get("decision")==decision and decision!="edited" and payload.get("after") is None and payload.get("evidence_span_id") is None
                    same_edit=saved.get("decision")==decision=="edited" and digest(saved.get("after"))==digest(payload.get("after")) and saved.get("evidence_span_id")==payload.get("evidence_span_id")
                    if same_plain or same_edit:return {"candidate_id":candidate_id,"decision_status":row["decision_status"],"delta":self._delta_view(c,project_id,batch)}
                    raise DomainError("candidate_already_decided",409)
                if decision=="edited":
                    if row["change_kind"]=="invalidated_fact":raise DomainError("invalid_candidate_decision",422)
                    edit=payload.get("after") or {}; after={name:str(edit.get(name," ")).strip() for name in base}; evidence=payload.get("evidence_span_id")
                    if after["memory_type"] not in {"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"} or not all(after.values()) or len(after["subject"])>80 or len(after["predicate"])>80 or len(after["value"])>240 or not self._is_controlled_candidate(after["memory_type"],after["predicate"],allow_legacy_alias=False) or evidence!=row["source_span_id"]: raise DomainError("invalid_item_edit",422)
                    if row["change_kind"]=="changed_fact":
                        before=self._delta_memory_view(c,project_id,batch["base_memory_version"],row["affected_memory_id"])
                        if all(self._normalize(after[field])==self._normalize(before[field]) for field in base):raise DomainError("candidate_conflict",422)
                elif payload.get("after") is not None or payload.get("evidence_span_id") is not None: raise DomainError("invalid_candidate_decision",422)
                if not c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=? AND source_revision=?",(row["source_span_id"],project_id,batch["source_revision"])).fetchone(): raise DomainError("evidence_unresolvable",422)
                if row["affected_memory_id"]:self._delta_memory_view(c,project_id,batch["base_memory_version"],row["affected_memory_id"])
                saved={"decision":decision,"change_kind":row["change_kind"],"affected_memory_id":row["affected_memory_id"],"after":after if decision!="rejected" and row["change_kind"]!="invalidated_fact" else None,"invalidation_reason":row["invalidation_reason"],"evidence_span_id":evidence}; stamp=utcnow()
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
                    return {"delta":self._delta_view(c,project_id,batch),"memory_version":audit["memory_version"] if audit else project["current_memory_version"],"coverage_audit":self._coverage_audit_view(c,project_id,audit) if audit else None,"change_set":self._delta_change_set_view(c,project_id,batch)}
                if payload.get("confirm") is not True:raise DomainError("confirmation_required",400)
                if batch["status"]!="in_review":raise DomainError("memory_delta_closed",409)
                if project["source_revision"]!=batch["source_revision"] or project["current_memory_version"]!=batch["base_memory_version"]:raise DomainError("memory_delta_stale",409)
                rows=c.execute("SELECT * FROM v2_memory_delta_candidates WHERE batch_id=? AND project_id=? ORDER BY candidate_ordinal",(batch_id,project_id)).fetchall(); core=[row for row in rows if row["review_priority"]=="core"]
                if any(row["decision_status"]=="pending" for row in core): raise DomainError("unresolved_required_decisions",409)
                accepted=[row for row in rows if row["decision_status"] in {"accepted","edited"}]; stamp=utcnow(); base_version=batch["base_memory_version"]; target=base_version+1 if accepted else base_version
                confirmed=self._confirmed_memory(c,project_id,base_version); confirmed_by_id={row["id"]:row for row in confirmed}; target_keys={}
                change_set_id=new_id("changeset"); change_status="committed" if accepted else "rejected"
                c.execute("INSERT INTO v2_change_sets(id,project_id,run_id,source_run_revision,resolved_revision,lineage_status,base_version,target_version,status,created_at,committed_at,change_set_kind,actor_user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(change_set_id,project_id,batch["memory_delta_run_id"],batch["source_revision"],batch["source_revision"],"incremental_source_revision",base_version,target,change_status,stamp,stamp,"memory_delta",user_id))
                item_rows=[]; accepted_item_ids=[]; rejected_item_ids=[]; edited_item_ids=[]; decisions=[]
                for row in rows:
                    if not c.execute("SELECT 1 FROM v2_source_spans WHERE id=? AND project_id=? AND source_revision=?",(row["source_span_id"],project_id,batch["source_revision"])).fetchone():raise DomainError("evidence_unresolvable",422)
                    decision=c.execute("SELECT * FROM v2_memory_delta_decisions WHERE candidate_id=? AND project_id=? AND batch_id=?",(row["id"],project_id,batch_id)).fetchone()
                    saved=json.loads(row["decision_json"] or "{}")
                    before=self._delta_memory_view(c,project_id,base_version,row["affected_memory_id"]) if row["affected_memory_id"] else None
                    after=saved.get("after") if row["decision_status"] in {"accepted","edited"} else ({field:row[field] for field in ("memory_type","subject","predicate","value")} if row["change_kind"]!="invalidated_fact" else None)
                    if row["change_kind"]=="invalidated_fact":after={"candidate_id":row["id"],"change_kind":"invalidated_fact","affected_memory_id":row["affected_memory_id"],"invalidation_reason":row["invalidation_reason"]}
                    else:after={"candidate_id":row["id"],"change_kind":row["change_kind"],"affected_memory_id":row["affected_memory_id"],**after,"source_span_id":row["source_span_id"]}
                    if row["decision_status"] in {"accepted","edited"} and row["change_kind"]!="invalidated_fact":
                        if not self._is_controlled_candidate(after["memory_type"],after["predicate"],allow_legacy_alias=False):raise DomainError("invalid_item_edit",422)
                        target_key=self._candidate_key(after["memory_type"],after["subject"],after["predicate"],allow_legacy_alias=False)
                        collision=next((item for item in confirmed if self._candidate_key(item["memory_type"],item["subject"],item["predicate"],allow_legacy_alias=False)==target_key and item["id"]!=row["affected_memory_id"]),None)
                        if collision or target_key in target_keys:raise DomainError("candidate_conflict",422)
                        target_keys[target_key]=row["id"]
                    operation={"new_fact":"add","changed_fact":"replace","invalidated_fact":"retire"}[row["change_kind"]]
                    source_ids=[row["source_span_id"]]+([row["affected_memory_id"]] if row["affected_memory_id"] else [])
                    decision_ids=[decision["id"]] if decision else []
                    item_id=new_id("changeitem"); committed_after=after if row["decision_status"] in {"accepted","edited"} else None
                    c.execute("INSERT INTO v2_change_set_items(id,project_id,change_set_id,operation,before_json,after_json,source_ids_json,decision_ids_json,review_status,committed_after_json) VALUES(?,?,?,?,?,?,?,?,?,?)",(item_id,project_id,change_set_id,operation,json.dumps(before,ensure_ascii=False) if before else None,json.dumps(after,ensure_ascii=False),json.dumps(source_ids),json.dumps(decision_ids),row["decision_status"],json.dumps(committed_after,ensure_ascii=False) if committed_after else None))
                    item_rows.append((row,after,item_id)); decisions.append({"candidate_id":row["id"],"change_kind":row["change_kind"],"affected_memory_id":row["affected_memory_id"],"decision":row["decision_status"],"before":before,"after":committed_after,"invalidation_reason":row["invalidation_reason"],"evidence_span_id":row["source_span_id"]})
                    if row["decision_status"] in {"accepted","edited"}:accepted_item_ids.append(item_id)
                    if row["decision_status"]=="edited":edited_item_ids.append(item_id)
                    if row["decision_status"]=="rejected":rejected_item_ids.append(item_id)
                audit_details={"change_set_id":change_set_id,"candidate_ids":[row["id"] for row in rows],"decisions":decisions,"source_revision":batch["source_revision"],"base_memory_version":base_version,"target_memory_version":target}
                audit_id=new_id("sourcecoverage")
                if not accepted:
                    c.execute("INSERT INTO v2_source_coverage_audits(id,project_id,source_revision,status,memory_version,delta_batch_id,actor_user_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(audit_id,project_id,batch["source_revision"],"covered_without_memory_change",base_version,batch_id,user_id,json.dumps(audit_details,ensure_ascii=False),stamp)); c.execute("UPDATE v2_memory_delta_batches SET status='covered',covered_at=? WHERE id=?",(stamp,batch_id)); c.execute("INSERT INTO v2_commit_audits(id,project_id,change_set_id,status,accepted_json,rejected_json,note,created_at) VALUES(?,?,?,?,?,?,?,?)",(new_id("commit"),project_id,change_set_id,"rejected",json.dumps([]),json.dumps(rejected_item_ids),"Memory Delta review",stamp)); audit=c.execute("SELECT * FROM v2_source_coverage_audits WHERE id=?",(audit_id,)).fetchone(); current_batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=?",(batch_id,)).fetchone(); delta_view=self._delta_view(c,project_id,current_batch); return {"delta":delta_view,"memory_version":base_version,"status":"covered_without_memory_change","coverage_audit":self._coverage_audit_view(c,project_id,audit),"change_set":delta_view["change_set"]}
                c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)",(project_id,target,"current",base_version,stamp)); c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) SELECT id||'-v'||?,project_id,?,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id FROM v2_memory_records WHERE project_id=? AND version=?",(target,target,project_id,base_version))
                for row,after,_ in item_rows:
                    if row["decision_status"] not in {"accepted","edited"}:continue
                    if row["change_kind"]=="new_fact":
                        c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(new_id("mem"),project_id,target,after["memory_type"],after["subject"],after["predicate"],after["value"],row["source_span_id"],"author_confirmed",target,None,None))
                    else:
                        target_id=row["affected_memory_id"]+f"-v{target}"
                        if not c.execute("SELECT 1 FROM v2_memory_records WHERE id=? AND project_id=? AND version=?",(target_id,project_id,target)).fetchone():raise DomainError("affected_memory_unresolvable",422)
                        if row["change_kind"]=="changed_fact":c.execute("UPDATE v2_memory_records SET memory_type=?,subject=?,predicate=?,value=?,source_span_id=?,review_status='author_confirmed',valid_from=?,valid_to=NULL WHERE id=? AND project_id=? AND version=?",(after["memory_type"],after["subject"],after["predicate"],after["value"],row["source_span_id"],target,target_id,project_id,target))
                        else:c.execute("UPDATE v2_memory_records SET valid_to=? WHERE id=? AND project_id=? AND version=?",(target-1,target_id,project_id,target))
                c.execute("UPDATE v2_memory_versions SET status='superseded' WHERE project_id=? AND version=?",(project_id,base_version)); c.execute("UPDATE v2_projects SET current_memory_version=?,updated_at=? WHERE id=?",(target,stamp,project_id)); c.execute("INSERT INTO v2_source_coverage_audits(id,project_id,source_revision,status,memory_version,delta_batch_id,actor_user_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(audit_id,project_id,batch["source_revision"],"covered_with_memory_change",target,batch_id,user_id,json.dumps(audit_details,ensure_ascii=False),stamp)); c.execute("UPDATE v2_memory_delta_batches SET status='covered',covered_at=? WHERE id=?",(stamp,batch_id)); c.execute("INSERT INTO v2_commit_audits(id,project_id,change_set_id,status,accepted_json,rejected_json,note,created_at) VALUES(?,?,?,?,?,?,?,?)",(new_id("commit"),project_id,change_set_id,"committed",json.dumps(accepted_item_ids),json.dumps(rejected_item_ids),"Memory Delta review",stamp)); audit=c.execute("SELECT * FROM v2_source_coverage_audits WHERE id=?",(audit_id,)).fetchone(); current_batch=c.execute("SELECT * FROM v2_memory_delta_batches WHERE id=?",(batch_id,)).fetchone(); delta_view=self._delta_view(c,project_id,current_batch)
                return {"delta":delta_view,"memory_version":target,"status":"covered_with_memory_change","coverage_audit":self._coverage_audit_view(c,project_id,audit),"change_set":delta_view["change_set"],"edited_item_ids":edited_item_ids}
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
                running=c.execute("SELECT id FROM v2_runs WHERE project_id=? AND draft_id=? AND source_revision=? AND run_type='continuity' AND status IN ('queued','running')",(project_id,draft["id"],draft["revision"])).fetchone()
                if running: raise DomainError("run_already_active",409,False,{"run_id":running["id"]})
                run_id,stamp=new_id("run"),utcnow()
                author_version,author_digest=self._current_author_context_binding(c,project)
                c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,root_run_id,attempt_number,author_context_version,author_context_snapshot_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,project_id,draft["id"],draft["revision"],"queued","queued",provenance["provider_label"],stamp,provenance["model_label"],provenance["prompt_version"],provenance["schema_version"],provenance["retrieval_method_version"],project["current_memory_version"],"provider",run_id,1,author_version,author_digest))
                self._append_run_event(c,run_id,"queued","queued",None,stamp)
                return {"run_id":run_id,"project_id":project_id,"run_type":"continuity","status":"queued","source_revision":draft["revision"],"author_context_version":author_version,"author_context_snapshot_digest":author_digest,"stage":"queued","result_origin":"provider","result_origin_label":"Provider 检查结果","retry_of_run_id":None,"root_run_id":run_id,"attempt_number":1,"created_at":stamp}
            return self._idem(c,user_id,"create_check:"+project_id,key,payload,create,202,with_created=True)

    @staticmethod
    def _analysis_terms(*values: str) -> set[str]:
        compact="".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]"," ".join(values))).casefold()
        return {compact[index:index+2] for index in range(max(0,len(compact)-1))}

    @classmethod
    def _analysis_rank(cls, terms: set[str], *values: str) -> int:
        text=" ".join(values).casefold()
        return sum(term in text for term in terms)

    @classmethod
    def _analysis_draft_excerpt(cls, body: str, hints: list[str], limit: int = 1200) -> str:
        if len(body)<=limit:return body
        terms=cls._analysis_terms(*hints)
        anchors=sorted({body.casefold().find(term) for term in terms if body.casefold().find(term)>=0})
        pieces=[]; remaining=limit
        for anchor in ([0]+anchors)[:8]:
            if remaining<=0:break
            size=min(600,remaining); start=max(0,min(anchor-size//3,len(body)-size))
            piece=body[start:start+size]
            if piece not in pieces:pieces.append(piece); remaining-=len(piece)
        return "\n…\n".join(pieces)[:limit]

    def _revision_plan_issue_binding(self,c:sqlite3.Connection,project_id:str,issue_ids:list[str])->tuple[sqlite3.Row,str,list[dict[str,Any]]]:
        if not isinstance(issue_ids,list) or not 1<=len(issue_ids)<=REVISION_PLAN_MAX_ISSUES or len(set(issue_ids))!=len(issue_ids) or any(not isinstance(item,str) or not item for item in issue_ids):raise DomainError("revision_plan_issue_invalid",422)
        issues=[];source_run=None
        for issue_id in issue_ids:
            issue=c.execute("SELECT * FROM v2_issues WHERE id=? AND project_id=?",(issue_id,project_id)).fetchone()
            if not issue:raise DomainError("resource_not_found",404)
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(issue["run_id"],project_id)).fetchone()
            if not run or run["run_type"]!="continuity" or public_run_status(run["status"])!="completed":raise DomainError("revision_plan_issue_invalid",422)
            if source_run is not None and source_run["id"]!=run["id"]:raise DomainError("revision_plan_issue_invalid",422)
            if issue["status"]!="open" or c.execute("SELECT 1 FROM v2_decisions WHERE project_id=? AND issue_id=?",(project_id,issue_id)).fetchone():raise DomainError("revision_plan_issue_stale",409)
            evidence=[item for item in self._resolved_evidence(c,project_id,issue,run) if item["sufficiency"]=="sufficient"][:5]
            if not evidence:raise DomainError("revision_plan_evidence_unavailable",422)
            claim=c.execute("SELECT text FROM v2_run_claims WHERE id=? AND run_id=?",(issue["claim_span_id"],run["id"])).fetchone()
            if not claim:raise DomainError("revision_plan_evidence_unavailable",422)
            issues.append({"id":issue_id,"claim_text":claim["text"],"classification":issue["classification"],"category":issue["category"],"severity":issue["severity"],"explanation":issue["explanation"],"evidence":evidence})
            source_run=run
        if source_run is None:raise DomainError("revision_plan_issue_invalid",422)
        return source_run,digest(issues),issues

    def create_analysis_run(self, user_id: str, project_id: str, payload: dict[str, Any], key: str, provenance: dict[str, str]):
        analysis_type=payload.get("analysis_type")
        if analysis_type not in {"context_brief","plan_alignment","change_impact","story_qa","foreshadow_scan","revision_plan"}:raise DomainError("analysis_type_invalid",422)
        if (analysis_type=="change_impact") != bool(payload.get("proposal")):raise DomainError("change_impact_proposal_invalid",422)
        if analysis_type=="story_qa":
            question=" ".join(str(payload.get("question") or "").split());scope=payload.get("scope")
            if not 1<=len(question)<=1000 or not isinstance(scope,list) or not scope or len(scope)>3 or len(set(scope))!=len(scope) or not set(scope)<={"confirmed","written","planned"}:raise DomainError("story_qa_input_invalid",422)
            payload={**payload,"question":question,"scope":scope}
        elif payload.get("question") is not None or payload.get("scope") is not None:raise DomainError("analysis_input_invalid",422)
        if analysis_type=="revision_plan":
            issue_ids=payload.get("issue_ids")
            if not isinstance(issue_ids,list) or not 1<=len(issue_ids)<=REVISION_PLAN_MAX_ISSUES or len(set(issue_ids))!=len(issue_ids):raise DomainError("revision_plan_issue_invalid",422)
        elif payload.get("issue_ids") is not None:raise DomainError("analysis_input_invalid",422)
        with self.connection() as c:
            def create():
                project=self._project(c,user_id,project_id,True)
                draft=c.execute("SELECT * FROM v2_drafts WHERE id=? AND project_id=?",(payload["draft_id"],project_id)).fetchone()
                if not draft:raise DomainError("resource_not_found",404)
                if draft["revision"]!=payload["draft_revision"]:raise DomainError("draft_revision_not_current",409)
                if analysis_type=="plan_alignment" and not draft["body"].strip():raise DomainError("analysis_draft_empty",422)
                selected_issues=[];selected_issue_digest=None;source_issue_run=None
                if analysis_type=="revision_plan":
                    source_issue_run,selected_issue_digest,selected_issues=self._revision_plan_issue_binding(c,project_id,payload["issue_ids"])
                    # Continuity Run source_revision is the checked draft revision;
                    # writing-analysis source_revision separately binds the committed corpus.
                    if source_issue_run["draft_id"]!=draft["id"] or source_issue_run["source_revision"]!=draft["revision"] or source_issue_run["source_memory_version"]!=project["current_memory_version"]:raise DomainError("revision_plan_issue_stale",409)
                author_version,author_digest=self._current_author_context_binding(c,project)
                alias_version,alias_digest,aliases=self._current_alias_binding(c,project_id)
                foreshadow_version,foreshadow_digest,foreshadows=self._current_foreshadow_binding(c,project_id)
                author_payload=self._stored_author_context_payload(c,project_id,author_version)
                story=[item for item in author_payload["story_plans"] if item["archived_at"] is None]
                if analysis_type=="plan_alignment" and not story:raise DomainError("analysis_plan_unavailable",422)
                running=c.execute("SELECT id FROM v2_runs WHERE project_id=? AND draft_id=? AND draft_revision=? AND run_type=? AND status IN ('queued','running')",(project_id,draft["id"],draft["revision"],analysis_type)).fetchone()
                if running:raise DomainError("run_already_active",409,False,{"run_id":running["id"]})
                hints=[draft["title"],str(payload.get("question") or "")]+[str(item.get(field) or "") for item in story for field in ("title","summary","goal")]+[str(item.get(field) or "") for item in foreshadows for field in ("title","description")]+[str(item.get(field) or "") for item in selected_issues for field in ("claim_text","explanation")]
                terms=self._analysis_terms(*hints, draft["body"][:2400])
                story=sorted(story,key=lambda item:(0 if item.get("target_chapter_number")==draft["chapter_number"] else 1,item["position"],item["id"]))[:4]
                characters=[item for item in author_payload["character_plans"] if item["archived_at"] is None]
                characters=sorted(characters,key=lambda item:(-self._analysis_rank(terms,item["name"],item["goal"],item["planned_state"],item["notes"]),item["position"],item["id"]))[:2]
                worlds=[item for item in author_payload["world_plans"] if item["archived_at"] is None]
                worlds=sorted(worlds,key=lambda item:(-self._analysis_rank(terms,item["name"],item["description"],item["notes"]),item["position"],item["id"]))[:2]
                memory_rows=[dict(row) for row in c.execute("SELECT id,memory_type,subject,predicate,value,source_span_id FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?) ORDER BY id",(project_id,project["current_memory_version"],project["current_memory_version"],project["current_memory_version"])).fetchall()]
                memory=sorted(memory_rows,key=lambda item:(-self._analysis_rank(terms,item["subject"],item["predicate"],item["value"]),item["id"]))[:8]
                span_rows=[dict(row) for row in c.execute("SELECT s.id,s.chapter_id,s.label,s.body,s.source_revision,ch.chapter_number,ch.title chapter_title FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id WHERE s.project_id=? AND s.source_revision<=? ORDER BY s.source_revision DESC,ch.chapter_number DESC,s.id",(project_id,project["source_revision"])).fetchall()]
                spans=sorted(span_rows,key=lambda item:(-self._analysis_rank(terms,item["label"],item["body"]),-item["source_revision"],-item["chapter_number"],item["id"]))[:4]
                run_id,stamp=new_id("run"),utcnow()
                all_claims=[{"id":f"draft-claim-{draft['id']}-r{draft['revision']}-{ordinal}","text":text[:240],"ordinal":ordinal} for ordinal,text in enumerate((x.strip() for x in re.split(r"(?<=[。！？.!?])",draft["body"]) if x.strip()),1)]
                ranked_claims=sorted(all_claims,key=lambda item:(-self._analysis_rank(terms,item["text"]),item["ordinal"]))
                claims=[] if analysis_type=="context_brief" else sorted(({item["id"]:item for item in (all_claims[:2]+all_claims[-2:]+ranked_claims[:8])}).values(),key=lambda item:item["ordinal"])[:8]
                selected_author={"story_plans":story,"character_plans":characters,"world_plans":worlds}
                source_items=[{**item,"body":self._bounded_excerpt(item["body"],terms,500)} for item in spans]
                factual_characters=[dict(row) for row in c.execute("SELECT id,name,role_type,identity,goal,current_state,knowledge_boundary,source_ids_json FROM v2_characters WHERE project_id=? ORDER BY id",(project_id,)).fetchall()]
                factual_world=[dict(row) for row in c.execute("SELECT id,entry_type,name,summary,source_ids_json FROM v2_world_entries WHERE project_id=? ORDER BY id",(project_id,)).fetchall()]
                chapters=[]
                for item in source_items:
                    if not any(row["id"]==item["chapter_id"] for row in chapters):chapters.append({"id":item["chapter_id"],"chapter_number":item["chapter_number"],"title":item["chapter_title"]})
                retrieval={"method_version":provenance["retrieval_method_version"],"selected_ids":{"author_context":[item["id"] for group in selected_author.values() for item in group],"memory_record":[item["id"] for item in memory],"source_span":[item["id"] for item in source_items],"draft_claim":[item["id"] for item in claims],"character_alias":[item["id"] for item in aliases] if analysis_type=="change_impact" else [],"foreshadow_record":[item["id"] for item in foreshadows] if analysis_type in {"story_qa","foreshadow_scan","revision_plan"} else [],"issue":[item["id"] for item in selected_issues],"issue_evidence":[evidence["id"] for item in selected_issues for evidence in item["evidence"]]},"counts":{"author_context":{"available":sum(len(author_payload[name]) for name in author_payload),"selected":sum(len(group) for group in selected_author.values())},"memory_record":{"available":len(memory_rows),"selected":len(memory)},"source_span":{"available":len(span_rows),"selected":len(source_items)},"draft_claim":{"available":len(all_claims),"selected":len(claims)},"character_alias":{"available":len(aliases),"selected":len(aliases) if analysis_type=="change_impact" else 0},"foreshadow_record":{"available":len(foreshadows),"selected":len(foreshadows) if analysis_type in {"story_qa","foreshadow_scan","revision_plan"} else 0},"issue":{"available":len(selected_issues),"selected":len(selected_issues)},"issue_evidence":{"available":sum(len(item["evidence"]) for item in selected_issues),"selected":sum(len(item["evidence"]) for item in selected_issues)}},"truncated":{"author_context":sum(len(author_payload[name]) for name in author_payload)>sum(len(group) for group in selected_author.values()),"memory_record":len(memory_rows)>len(memory),"source_span":len(span_rows)>len(source_items),"draft_claim":len(all_claims)>len(claims),"draft_body":len(draft["body"])>1200,"character_alias":False,"foreshadow_record":False,"issue":False,"issue_evidence":False}}
                if analysis_type=="context_brief" and not (retrieval["selected_ids"]["author_context"] or retrieval["selected_ids"]["memory_record"] or retrieval["selected_ids"]["source_span"]):raise DomainError("analysis_evidence_unavailable",422)
                bindings={"project_id":project_id,"draft_id":draft["id"],"draft_revision":draft["revision"],"source_revision":project["source_revision"],"memory_version":project["current_memory_version"],"author_context_version":author_version,"author_context_snapshot_digest":author_digest}
                layers={"planned":selected_author,"confirmed":{"memory_records":memory},"written":{"draft":{"id":draft["id"],"revision":draft["revision"],"chapter_number":draft["chapter_number"],"title":draft["title"],"excerpt":self._analysis_draft_excerpt(draft["body"],hints)},"draft_claims":claims,"source_spans":source_items}}
                if analysis_type=="change_impact":
                    proposal=payload["proposal"]
                    targets={"chapter":{item["id"] for item in chapters},"character":{item["id"] for item in factual_characters},"world":{item["id"] for item in factual_world},"memory":{item["id"] for item in memory},"plan":{item["id"] for group in selected_author.values() for item in group}}
                    if proposal.get("target_id") and (proposal["target_type"]=="general" or proposal["target_id"] not in targets.get(proposal["target_type"],set())):raise DomainError("change_impact_target_invalid",422)
                    bindings.update({"alias_version":alias_version,"alias_snapshot_digest":alias_digest})
                    layers["identity"]={"characters":factual_characters,"aliases":aliases}
                    layers["reference"]={"chapters":chapters,"world_entries":factual_world}
                if analysis_type=="story_qa":
                    scope=set(payload["scope"])
                    if "planned" not in scope:
                        layers["planned"]={"story_plans":[],"character_plans":[],"world_plans":[]};retrieval["selected_ids"]["author_context"]=[];retrieval["counts"]["author_context"]["selected"]=0
                    if "confirmed" not in scope:
                        layers["confirmed"]={"memory_records":[]};retrieval["selected_ids"]["memory_record"]=[];retrieval["counts"]["memory_record"]["selected"]=0
                    if "written" not in scope:
                        layers["written"]={"draft":{**layers["written"]["draft"],"excerpt":""},"draft_claims":[],"source_spans":[]};retrieval["selected_ids"]["source_span"]=[];retrieval["selected_ids"]["draft_claim"]=[];retrieval["counts"]["source_span"]["selected"]=0;retrieval["counts"]["draft_claim"]["selected"]=0
                if analysis_type=="foreshadow_scan":
                    layers["planned"]={"story_plans":[],"character_plans":[],"world_plans":[]};layers["confirmed"]={"memory_records":[]}
                    retrieval["selected_ids"]["author_context"]=[];retrieval["selected_ids"]["memory_record"]=[];retrieval["counts"]["author_context"]["selected"]=0;retrieval["counts"]["memory_record"]["selected"]=0
                if analysis_type in {"story_qa","foreshadow_scan","revision_plan"}:bindings.update({"foreshadow_version":foreshadow_version,"foreshadow_snapshot_digest":foreshadow_digest})
                if analysis_type=="revision_plan":bindings.update({"source_run_id":source_issue_run["id"],"selected_issue_digest":selected_issue_digest})
                input_data={"task":analysis_type,"bindings":bindings,"layers":layers,"retrieval":retrieval,**({"proposal":payload["proposal"]} if analysis_type=="change_impact" else {}),**({"question":payload["question"],"scope":payload["scope"]} if analysis_type=="story_qa" else {}),**({"author_records":{"foreshadows":foreshadows}} if analysis_type in {"foreshadow_scan","revision_plan"} else {}),**({"source_run_id":source_issue_run["id"],"selected_issues":selected_issues} if analysis_type=="revision_plan" else {})}
                input_json=json.dumps(input_data,ensure_ascii=False,sort_keys=True,separators=(",",":"))
                c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,draft_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,run_type,root_run_id,attempt_number,author_context_version,author_context_snapshot_digest,alias_version,alias_snapshot_digest,foreshadow_version,foreshadow_snapshot_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,project_id,draft["id"],project["source_revision"],draft["revision"],"queued","queued",provenance["provider_label"],stamp,provenance["model_label"],provenance["prompt_version"],provenance["schema_version"],provenance["retrieval_method_version"],project["current_memory_version"],"provider",analysis_type,run_id,1,author_version,author_digest,alias_version if analysis_type=="change_impact" else None,alias_digest if analysis_type=="change_impact" else None,foreshadow_version if analysis_type in {"story_qa","foreshadow_scan","revision_plan"} else None,foreshadow_digest if analysis_type in {"story_qa","foreshadow_scan","revision_plan"} else None))
                c.execute("INSERT INTO v2_analysis_inputs VALUES(?,?,?,?,?,?,?)",(run_id,project_id,analysis_type,input_json,json.dumps(retrieval,ensure_ascii=False,sort_keys=True),digest(input_data),stamp))
                self._append_run_event(c,run_id,"queued","queued",None,stamp)
                return {"run_id":run_id,"project_id":project_id,"analysis_type":analysis_type,"run_type":analysis_type,"status":"queued","stage":"queued","draft_revision":draft["revision"],"source_revision":project["source_revision"],"source_memory_version":project["current_memory_version"],"author_context_version":author_version,"author_context_snapshot_digest":author_digest,"alias_version":alias_version if analysis_type=="change_impact" else None,"alias_snapshot_digest":alias_digest if analysis_type=="change_impact" else None,"foreshadow_version":foreshadow_version if analysis_type in {"story_qa","foreshadow_scan","revision_plan"} else None,"foreshadow_snapshot_digest":foreshadow_digest if analysis_type in {"story_qa","foreshadow_scan","revision_plan"} else None,"proposal":payload.get("proposal"),"question":payload.get("question"),"scope":payload.get("scope"),"issue_ids":payload.get("issue_ids"),"source_run_id":source_issue_run["id"] if source_issue_run else None,"retry_of_run_id":None,"root_run_id":run_id,"attempt_number":1,"created_at":stamp}
            return self._idem(c,user_id,"create_analysis:"+analysis_type+":"+project_id,key,payload,create,202,with_created=True)

    def analysis_run_input(self, project_id: str, run_id: str) -> dict[str, Any]:
        with self.connection() as c:
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            row=c.execute("SELECT * FROM v2_analysis_inputs WHERE run_id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not run or not row:raise DomainError("resource_not_found",404)
            if run["status"] not in RUN_ACTIVE_STATUSES or run["cancel_requested_at"]:raise DomainError("run_cancelled",409)
            data=json.loads(row["input_json"])
            if digest(data)!=row["input_digest"]:raise DomainError("analysis_input_invalid",409)
            return data

    def finish_analysis_run(self, project_id: str, run_id: str, result: dict[str, Any]) -> bool:
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not run:raise DomainError("resource_not_found",404)
            if run["status"] not in RUN_ACTIVE_STATUSES:return False
            stamp=utcnow()
            if run["cancel_requested_at"]:status,terminal,error,retryable="cancelled","cancelled","author_cancelled",True
            else:
                status,terminal,error=self._normalized_terminal(result);retryable=bool(result.get("retryable")) or status in {"timed_out","cancelled"}
            duration=elapsed_ms(run["started_at"] or run["created_at"],stamp)
            changed=c.execute("UPDATE v2_runs SET status=?,stage=?,input_tokens=?,output_tokens=?,latency_ms=?,cost_cny=?,error_code=?,retryable=?,completed_at=?,duration_ms=? WHERE id=? AND project_id=? AND status IN ('queued','running')",(status,terminal,result.get("input_tokens"),result.get("output_tokens"),result.get("latency_ms"),result.get("cost_cny"),error,int(retryable),stamp,duration,run_id,project_id)).rowcount
            if not changed:return False
            self._append_run_event(c,run_id,status,terminal,error,stamp)
            if status=="completed":
                if not isinstance(result.get("analysis"),dict):raise DomainError("analysis_result_invalid",409)
                analysis=result["analysis"]
                if run["run_type"]=="foreshadow_scan":
                    stored=[]
                    for ordinal,candidate in enumerate(analysis.get("candidates",[]),1):
                        candidate_id=new_id("foreshadowcandidate")
                        self._foreshadow_reference(c,project_id,candidate.get("planted_chapter_id"),candidate.get("planted_source_span_id"));self._foreshadow_reference(c,project_id,candidate.get("resolved_chapter_id"),candidate.get("resolved_source_span_id"))
                        c.execute("INSERT INTO v2_foreshadow_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(candidate_id,project_id,run_id,ordinal,candidate["title"],candidate["description"],candidate["suggested_status"],candidate.get("planted_chapter_id"),candidate.get("planted_source_span_id"),candidate.get("resolved_chapter_id"),candidate.get("resolved_source_span_id"),json.dumps(candidate["evidence"],ensure_ascii=False,sort_keys=True),"pending",None,None,stamp))
                        stored.append({**candidate,"id":candidate_id,"decision_status":"pending","decision":None})
                    analysis={**analysis,"candidates":stored}
                if run["run_type"]=="revision_plan":
                    stored=[]
                    for ordinal,candidate in enumerate(analysis.get("candidates",[]),1):
                        candidate_id=new_id("revisioncandidate")
                        c.execute("INSERT INTO v2_revision_plan_candidates(id,project_id,run_id,candidate_ordinal,issue_id,title,normalized_title,instruction,priority,evidence_json,decision_status,decision_json,decided_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(candidate_id,project_id,run_id,ordinal,candidate["issue_id"],candidate["title"],self._normalized_revision_task_title(candidate["title"]),candidate["instruction"],candidate["priority"],json.dumps(candidate["evidence"],ensure_ascii=False,sort_keys=True),"pending",None,None,stamp))
                        stored.append({**candidate,"id":candidate_id,"decision_status":"pending","decision":None})
                    analysis={**analysis,"candidates":stored}
                c.execute("INSERT INTO v2_analysis_results VALUES(?,?,?,?,?)",(run_id,project_id,run["run_type"],json.dumps(analysis,ensure_ascii=False,sort_keys=True),stamp))
            return True

    def analysis_view(self, user_id: str, project_id: str, run_id: str) -> dict[str, Any]:
        result=self.run_view(user_id,project_id,run_id,set())
        with self.connection() as c:
            project=self._project(c,user_id,project_id)
            run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if run["run_type"] not in {"context_brief","plan_alignment","change_impact","story_qa","foreshadow_scan","revision_plan"}:raise DomainError("resource_not_found",404)
            draft=c.execute("SELECT revision FROM v2_drafts WHERE id=? AND project_id=?",(run["draft_id"],project_id)).fetchone()
            alias_current=run["run_type"]!="change_impact" or (project["alias_version"]==run["alias_version"] and self._current_alias_binding(c,project_id)[1]==run["alias_snapshot_digest"])
            foreshadow_current=True
            if run["run_type"] in {"story_qa","foreshadow_scan","revision_plan"}:
                current_foreshadow=self._current_foreshadow_binding(c,project_id)
                if run["run_type"]=="foreshadow_scan":
                    own_ids={row["created_record_id"] for row in c.execute("SELECT created_record_id FROM v2_foreshadow_candidate_decisions WHERE run_id=? AND created_record_id IS NOT NULL",(run_id,)).fetchall()}
                    original_rows=[item for item in current_foreshadow[2] if item["id"] not in own_ids]
                    foreshadow_current=current_foreshadow[0]==run["foreshadow_version"]+len(own_ids) and digest(original_rows)==run["foreshadow_snapshot_digest"]
                else:foreshadow_current=current_foreshadow[:2]==(run["foreshadow_version"],run["foreshadow_snapshot_digest"])
            input_row=c.execute("SELECT input_json,retrieval_json,input_digest FROM v2_analysis_inputs WHERE run_id=?",(run_id,)).fetchone()
            input_payload=json.loads(input_row["input_json"]) if input_row else {}
            issue_current=True
            if run["run_type"]=="revision_plan":
                try:
                    issue_run,issue_digest,_=self._revision_plan_issue_binding(c,project_id,input_payload.get("bindings",{}).get("selected_issue_ids") or [item["id"] for item in input_payload.get("selected_issues",[])])
                    issue_current=issue_run["id"]==input_payload.get("source_run_id") and issue_digest==input_payload.get("bindings",{}).get("selected_issue_digest")
                except DomainError:issue_current=False
            current=bool(draft and draft["revision"]==run["draft_revision"] and project["source_revision"]==run["source_revision"] and project["current_memory_version"]==run["source_memory_version"] and project["author_context_version"]==run["author_context_version"] and result["author_context_resolvable"] and alias_current and foreshadow_current and issue_current)
            stored=c.execute("SELECT result_json FROM v2_analysis_results WHERE run_id=?",(run_id,)).fetchone()
            result.update({"analysis_type":run["run_type"],"draft_revision":run["draft_revision"],"current_draft_revision":draft["revision"] if draft else None,"alias_version":run["alias_version"],"alias_snapshot_digest":run["alias_snapshot_digest"],"foreshadow_version":run["foreshadow_version"],"foreshadow_snapshot_digest":run["foreshadow_snapshot_digest"],"proposal":input_payload.get("proposal"),"question":input_payload.get("question"),"scope":input_payload.get("scope"),"issue_ids":[item["id"] for item in input_payload.get("selected_issues",[])],"source_run_id":input_payload.get("source_run_id"),"is_stale":not current,"superseded":not current,"lineage_status":"current" if current else "bound_state_changed","retrieval":json.loads(input_row["retrieval_json"]) if input_row else None,"input_digest":input_row["input_digest"] if input_row else None})
            if result["status"]=="completed":
                if not stored:raise DomainError("analysis_result_unresolvable",409)
                result["analysis"]=json.loads(stored["result_json"])
                if run["run_type"]=="foreshadow_scan":
                    decisions={row["id"]:row for row in c.execute("SELECT id,decision_status,decision_json,decided_at FROM v2_foreshadow_candidates WHERE run_id=? ORDER BY candidate_ordinal",(run_id,)).fetchall()}
                    for candidate in result["analysis"].get("candidates",[]):
                        state=decisions.get(candidate["id"])
                        if state:candidate.update({"decision_status":state["decision_status"],"decision":json.loads(state["decision_json"]) if state["decision_json"] else None,"decided_at":state["decided_at"]})
                if run["run_type"]=="revision_plan":
                    decisions={row["id"]:row for row in c.execute("SELECT id,decision_status,decision_json,decided_at FROM v2_revision_plan_candidates WHERE run_id=? ORDER BY candidate_ordinal",(run_id,)).fetchall()}
                    for candidate in result["analysis"].get("candidates",[]):
                        state=decisions.get(candidate["id"])
                        if state:candidate.update({"decision_status":state["decision_status"],"decision":json.loads(state["decision_json"]) if state["decision_json"] else None,"decided_at":state["decided_at"]})
            return result

    def latest_analysis(self, user_id: str, project_id: str, analysis_type: str, limit: int = 10) -> dict[str, Any]:
        if analysis_type not in {"context_brief","plan_alignment","change_impact","story_qa","foreshadow_scan","revision_plan"}:raise DomainError("analysis_type_invalid",422)
        with self.connection() as c:
            self._project(c,user_id,project_id)
            rows=c.execute("SELECT id FROM v2_runs WHERE project_id=? AND run_type=? ORDER BY created_at DESC,rowid DESC LIMIT ?",(project_id,analysis_type,limit)).fetchall()
        runs=[self.analysis_view(user_id,project_id,row["id"]) for row in rows]
        return {"analysis_type":analysis_type,"run":runs[0] if runs else None,"runs":runs}

    def decide_foreshadow_candidate(self,user_id:str,project_id:str,run_id:str,candidate_id:str,payload:dict[str,Any],key:str):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def decide():
                project=self._project(c,user_id,project_id,True)
                run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=? AND run_type='foreshadow_scan'",(run_id,project_id)).fetchone()
                candidate=c.execute("SELECT * FROM v2_foreshadow_candidates WHERE id=? AND project_id=? AND run_id=?",(candidate_id,project_id,run_id)).fetchone()
                if not run or not candidate:raise DomainError("resource_not_found",404)
                if public_run_status(run["status"])!="completed":raise DomainError("foreshadow_candidate_unavailable",409)
                if candidate["decision_status"]!="pending":raise DomainError("foreshadow_candidate_decided",409)
                draft=c.execute("SELECT revision FROM v2_drafts WHERE id=? AND project_id=?",(run["draft_id"],project_id)).fetchone()
                author=self._current_author_context_binding(c,project);foreshadow=self._current_foreshadow_binding(c,project_id)
                own_ids={row["created_record_id"] for row in c.execute("SELECT created_record_id FROM v2_foreshadow_candidate_decisions WHERE run_id=? AND created_record_id IS NOT NULL",(run_id,)).fetchall()}
                original_rows=[item for item in foreshadow[2] if item["id"] not in own_ids]
                decision_current=foreshadow[0]==run["foreshadow_version"]+len(own_ids) and digest(original_rows)==run["foreshadow_snapshot_digest"]
                if not draft or draft["revision"]!=run["draft_revision"] or project["source_revision"]!=run["source_revision"] or project["current_memory_version"]!=run["source_memory_version"] or author!=(run["author_context_version"],run["author_context_snapshot_digest"]) or not decision_current:raise DomainError("foreshadow_candidate_stale",409)
                if payload["base_foreshadow_version"]!=project["foreshadow_version"]:raise DomainError("foreshadow_version_conflict",409,False,{"current_version":project["foreshadow_version"]})
                decision=payload["decision"]
                if decision not in {"accepted","edited","rejected"}:raise DomainError("foreshadow_candidate_decision_invalid",422)
                edited=payload.get("edited")
                if (decision=="edited") != bool(edited):raise DomainError("foreshadow_candidate_decision_invalid",422)
                stamp=utcnow();created_record_id=None;after=None
                if decision!="rejected":
                    if int(project["foreshadow_version"] or 0)>=MAX_RESOURCE_VERSION:raise DomainError("foreshadow_version_limit",409)
                    if c.execute("SELECT COUNT(*) FROM v2_foreshadows WHERE project_id=? AND archived_at IS NULL",(project_id,)).fetchone()[0]>=FORESHADOW_MAX_RECORDS:raise DomainError("foreshadow_limit_reached",409)
                    values=self._validate_foreshadow_payload(c,project_id,edited or {"title":candidate["title"],"description":candidate["description"],"status":candidate["suggested_status"],"planted_chapter_id":candidate["planted_chapter_id"],"planted_source_span_id":candidate["planted_source_span_id"],"resolved_chapter_id":candidate["resolved_chapter_id"],"resolved_source_span_id":candidate["resolved_source_span_id"]})
                    if c.execute("SELECT 1 FROM v2_foreshadows WHERE project_id=? AND normalized_title=? AND archived_at IS NULL",(project_id,values["normalized_title"])).fetchone():raise DomainError("foreshadow_duplicate",409)
                    created_record_id=new_id("foreshadow")
                    c.execute("INSERT INTO v2_foreshadows VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(created_record_id,project_id,values["title"],values["normalized_title"],values["description"],values["status"],values["planted_chapter_id"],values["planted_source_span_id"],values["resolved_chapter_id"],values["resolved_source_span_id"],1,None,stamp,stamp))
                    record=c.execute("SELECT * FROM v2_foreshadows WHERE id=?",(created_record_id,)).fetchone();self._record_foreshadow_version(c,record,"candidate_"+decision,user_id,stamp);after=self._foreshadow_item(c,record)
                    c.execute("UPDATE v2_projects SET foreshadow_version=foreshadow_version+1,updated_at=? WHERE id=?",(stamp,project_id))
                decision_payload={"decision":decision,"after":after,"created_record_id":created_record_id}
                c.execute("UPDATE v2_foreshadow_candidates SET decision_status=?,decision_json=?,decided_at=? WHERE id=?",(decision,json.dumps(decision_payload,ensure_ascii=False,sort_keys=True),stamp,candidate_id))
                c.execute("INSERT INTO v2_foreshadow_candidate_decisions VALUES(?,?,?,?,?,?,?,?,?)",(new_id("foreshadowdecision"),project_id,run_id,candidate_id,decision,json.dumps(after,ensure_ascii=False,sort_keys=True) if after else None,created_record_id,user_id,stamp))
                return {"project_id":project_id,"run_id":run_id,"candidate_id":candidate_id,"decision_status":decision,"decision":decision_payload,"foreshadows":self._foreshadow_snapshot(c,project_id,True)}
            return self._idem(c,user_id,f"foreshadow_candidate_decision:{project_id}:{run_id}:{candidate_id}",key,payload,decide)

    def decide_revision_candidate(self,user_id:str,project_id:str,run_id:str,candidate_id:str,payload:dict[str,Any],key:str):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            def decide():
                project=self._project(c,user_id,project_id,True)
                run=c.execute("SELECT * FROM v2_runs WHERE id=? AND project_id=? AND run_type='revision_plan'",(run_id,project_id)).fetchone()
                candidate=c.execute("SELECT * FROM v2_revision_plan_candidates WHERE id=? AND project_id=? AND run_id=?",(candidate_id,project_id,run_id)).fetchone()
                if not run or not candidate:raise DomainError("resource_not_found",404)
                if public_run_status(run["status"])!="completed":raise DomainError("revision_candidate_unavailable",409)
                if candidate["decision_status"]!="pending":raise DomainError("revision_candidate_decided",409)
                input_row=c.execute("SELECT input_json FROM v2_analysis_inputs WHERE run_id=? AND project_id=?",(run_id,project_id)).fetchone()
                if not input_row:raise DomainError("revision_candidate_stale",409)
                input_payload=json.loads(input_row["input_json"]);issue_ids=[item["id"] for item in input_payload.get("selected_issues",[])]
                try:source_run,issue_digest,_=self._revision_plan_issue_binding(c,project_id,issue_ids)
                except DomainError:raise DomainError("revision_candidate_stale",409) from None
                draft=c.execute("SELECT revision FROM v2_drafts WHERE id=? AND project_id=?",(run["draft_id"],project_id)).fetchone()
                current_author=self._current_author_context_binding(c,project);current_foreshadow=self._current_foreshadow_binding(c,project_id)
                bindings=input_payload.get("bindings",{})
                if not draft or draft["revision"]!=run["draft_revision"] or project["source_revision"]!=run["source_revision"] or project["current_memory_version"]!=run["source_memory_version"] or current_author!=(run["author_context_version"],run["author_context_snapshot_digest"]) or current_foreshadow[:2]!=(run["foreshadow_version"],run["foreshadow_snapshot_digest"]) or source_run["id"]!=input_payload.get("source_run_id") or issue_digest!=bindings.get("selected_issue_digest"):raise DomainError("revision_candidate_stale",409)
                decision=payload.get("decision");edited=payload.get("edited")
                if decision not in {"accepted","edited","rejected"} or (decision=="edited")!=bool(edited):raise DomainError("revision_candidate_decision_invalid",422)
                if payload.get("base_task_version")!=project["revision_task_version"]:raise DomainError("revision_task_version_conflict",409,False,{"current_version":project["revision_task_version"]})
                stamp=utcnow();created_task_id=None;after=None
                if decision!="rejected":
                    if int(project["revision_task_version"] or 0)>=MAX_RESOURCE_VERSION:raise DomainError("revision_task_version_limit",409)
                    if c.execute("SELECT COUNT(*) FROM v2_revision_tasks WHERE project_id=? AND status!='completed'",(project_id,)).fetchone()[0]>=REVISION_TASK_MAX_RECORDS:raise DomainError("revision_task_limit_reached",409)
                    values=self._validate_revision_task_fields(edited or {"title":candidate["title"],"instruction":candidate["instruction"],"priority":candidate["priority"]})
                    if c.execute("SELECT 1 FROM v2_revision_tasks WHERE project_id=? AND normalized_title=? AND status!='completed'",(project_id,values["normalized_title"])).fetchone():raise DomainError("revision_task_duplicate",409)
                    created_task_id=new_id("revisiontask");position=c.execute("SELECT COALESCE(MAX(position),0)+1 FROM v2_revision_tasks WHERE project_id=?",(project_id,)).fetchone()[0]
                    c.execute("INSERT INTO v2_revision_tasks(id,project_id,source_run_id,candidate_id,issue_id,title,normalized_title,instruction,priority,position,status,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(created_task_id,project_id,run_id,candidate_id,candidate["issue_id"],values["title"],values["normalized_title"],values["instruction"],values["priority"],position,"todo",1,stamp,stamp))
                    task=c.execute("SELECT * FROM v2_revision_tasks WHERE id=?",(created_task_id,)).fetchone();self._record_revision_task_version(c,task,"candidate_"+decision,user_id,stamp)
                    c.execute("UPDATE v2_projects SET revision_task_version=revision_task_version+1,updated_at=? WHERE id=?",(stamp,project_id))
                    after=self._revision_task_item({**dict(task),"evidence_json":candidate["evidence_json"]})
                decision_payload={"decision":decision,"after":after,"created_task_id":created_task_id}
                c.execute("UPDATE v2_revision_plan_candidates SET decision_status=?,decision_json=?,decided_at=? WHERE id=?",(decision,json.dumps(decision_payload,ensure_ascii=False,sort_keys=True),stamp,candidate_id))
                c.execute("INSERT INTO v2_revision_candidate_decisions VALUES(?,?,?,?,?,?,?,?,?)",(new_id("revisiondecision"),project_id,run_id,candidate_id,decision,json.dumps(after,ensure_ascii=False,sort_keys=True) if after else None,created_task_id,user_id,stamp))
                return {"project_id":project_id,"run_id":run_id,"candidate_id":candidate_id,"decision_status":decision,"decision":decision_payload,"revision_tasks":self._revision_task_snapshot(c,project_id,True)}
            return self._idem(c,user_id,f"revision_candidate_decision:{project_id}:{run_id}:{candidate_id}",key,payload,decide)

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
            source_memory_version=run["source_memory_version"]
            memory=[dict(x) for x in c.execute("SELECT id,memory_type,subject,predicate,value,source_span_id FROM v2_memory_records WHERE project_id=? AND version=? AND review_status='author_confirmed' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?) ORDER BY id",(project_id,source_memory_version,source_memory_version,source_memory_version)).fetchall()]
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

    def require_run_type(self,user_id:str,project_id:str,run_id:str,allowed:set[str])->str:
        with self.connection() as c:
            self._project(c,user_id,project_id)
            row=c.execute("SELECT run_type FROM v2_runs WHERE id=? AND project_id=?",(run_id,project_id)).fetchone()
            if not row or row["run_type"] not in allowed:raise DomainError("resource_not_found",404)
            return row["run_type"]

    def _retry_copy(self,c,previous,batch_id=None):
        run_id,stamp=new_id("run"),utcnow(); root=previous["root_run_id"] or previous["id"]
        attempt=c.execute("SELECT COALESCE(MAX(attempt_number),0)+1 FROM v2_runs WHERE root_run_id=?",(root,)).fetchone()[0]
        project=c.execute("SELECT * FROM v2_projects WHERE id=?",(previous["project_id"],)).fetchone()
        analysis=previous["run_type"] in {"context_brief","plan_alignment","change_impact","story_qa","foreshadow_scan","revision_plan"}
        if analysis:author_version,author_digest=previous["author_context_version"],previous["author_context_snapshot_digest"]
        else:author_version,author_digest=self._current_author_context_binding(c,project)
        c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,draft_revision,status,stage,provider_label,created_at,model_label,prompt_version,schema_version,retrieval_method_version,source_memory_version,result_origin,run_type,source_change_set_id,source_span_ids_json,retry_of_run_id,root_run_id,attempt_number,incremental_batch_id,author_context_version,author_context_snapshot_digest,alias_version,alias_snapshot_digest,foreshadow_version,foreshadow_snapshot_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,previous["project_id"],previous["draft_id"],previous["source_revision"],previous["draft_revision"],"queued","queued",previous["provider_label"],stamp,previous["model_label"],previous["prompt_version"],previous["schema_version"],previous["retrieval_method_version"],previous["source_memory_version"],previous["result_origin"],previous["run_type"],previous["source_change_set_id"],previous["source_span_ids_json"],previous["id"],root,attempt,batch_id,author_version,author_digest,previous["alias_version"],previous["alias_snapshot_digest"],previous["foreshadow_version"],previous["foreshadow_snapshot_digest"]))
        if analysis:
            source=c.execute("SELECT * FROM v2_analysis_inputs WHERE run_id=?",(previous["id"],)).fetchone()
            if not source:raise DomainError("run_retry_lineage_stale",409)
            c.execute("INSERT INTO v2_analysis_inputs VALUES(?,?,?,?,?,?,?)",(run_id,source["project_id"],source["analysis_type"],source["input_json"],source["retrieval_json"],source["input_digest"],stamp))
        self._append_run_event(c,run_id,"queued","queued",None,stamp)
        output={"run_id":run_id,"project_id":previous["project_id"],"run_type":previous["run_type"],"analysis_type":previous["run_type"] if analysis else None,"status":"queued","stage":"queued","draft_revision":previous["draft_revision"],"source_revision":previous["source_revision"],"source_memory_version":previous["source_memory_version"],"author_context_version":previous["author_context_version"],"alias_version":previous["alias_version"],"foreshadow_version":previous["foreshadow_version"],"created_at":stamp,"retry_of_run_id":previous["id"],"root_run_id":root,"attempt_number":attempt}
        if analysis:
            analysis_input=json.loads(source["input_json"]);output.update({"proposal":analysis_input.get("proposal"),"question":analysis_input.get("question"),"scope":analysis_input.get("scope"),"issue_ids":[item["id"] for item in analysis_input.get("selected_issues",[])],"source_run_id":analysis_input.get("source_run_id")})
        return output

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
                    c.execute("UPDATE v2_memory_delta_batches SET continuity_run_id=?,memory_delta_run_id=?,status='processing',error_code=NULL,created_at=?,completed_at=NULL,covered_at=NULL,retrieval_json='{}' WHERE id=?",(continuity_id,delta_id,utcnow(),batch["id"]))
                    return {"paired":True,"batch_id":batch["id"],"continuity_run_id":continuity_id,"memory_delta_run_id":delta_id,"runs":[created["continuity"],created["memory_delta"]]}
                if target["run_type"] in {"context_brief","plan_alignment","change_impact","story_qa","foreshadow_scan","revision_plan"}:
                    draft=c.execute("SELECT revision FROM v2_drafts WHERE id=? AND project_id=?",(target["draft_id"],project_id)).fetchone()
                    current_author=self._current_author_context_binding(c,project)
                    alias_current=target["run_type"]!="change_impact" or self._current_alias_binding(c,project_id)[:2]==(target["alias_version"],target["alias_snapshot_digest"])
                    foreshadow_current=target["run_type"] not in {"story_qa","foreshadow_scan","revision_plan"} or self._current_foreshadow_binding(c,project_id)[:2]==(target["foreshadow_version"],target["foreshadow_snapshot_digest"])
                    issue_current=True
                    if target["run_type"]=="revision_plan":
                        source=c.execute("SELECT input_json FROM v2_analysis_inputs WHERE run_id=?",(target["id"],)).fetchone()
                        try:
                            analysis_input=json.loads(source["input_json"]);issue_run,issue_digest,_=self._revision_plan_issue_binding(c,project_id,[item["id"] for item in analysis_input.get("selected_issues",[])])
                            issue_current=issue_run["id"]==analysis_input.get("source_run_id") and issue_digest==analysis_input.get("bindings",{}).get("selected_issue_digest")
                        except (DomainError,TypeError,ValueError):issue_current=False
                    if not draft or draft["revision"]!=target["draft_revision"] or project["source_revision"]!=target["source_revision"] or project["current_memory_version"]!=target["source_memory_version"] or current_author!=(target["author_context_version"],target["author_context_snapshot_digest"]) or not alias_current or not foreshadow_current or not issue_current:raise DomainError("run_retry_lineage_stale",409)
                    root=target["root_run_id"] or target["id"]
                    if c.execute("SELECT 1 FROM v2_runs WHERE root_run_id=? AND status IN ('queued','running')",(root,)).fetchone():raise DomainError("run_already_active",409)
                    return {"paired":False,"run":self._retry_copy(c,target)}
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
            analysis=run["run_type"] in {"context_brief","plan_alignment","change_impact"}
            project=c.execute("SELECT source_revision,current_memory_version,author_context_version,alias_version FROM v2_projects WHERE id=?",(project_id,)).fetchone()
            alias_current=run["run_type"]!="change_impact" or project["alias_version"]==run["alias_version"]
            current=(draft["revision"]==run["draft_revision"] and project["source_revision"]==run["source_revision"] and project["current_memory_version"]==run["source_memory_version"] and project["author_context_version"]==run["author_context_version"] and alias_current) if analysis else (project["source_revision"]==run["source_revision"] and project["current_memory_version"]==run["source_memory_version"]) if incremental else run["run_type"]!="continuity" or draft["revision"]==run["source_revision"] or direct_successor
            status=public_run_status(run["status"]); stage=status if run["status"]=="budget_paused" else run["stage"]; error_code=public_run_error(run["status"],run["error_code"])
            transitions=[{"sequence":row["sequence"],"status":public_run_status(row["status"]),"stage":row["stage"],"error_code":public_run_error(row["status"],row["error_code"]),"created_at":row["created_at"]} for row in c.execute("SELECT * FROM v2_run_events WHERE run_id=? ORDER BY sequence",(run_id,)).fetchall()]
            author_meta=None
            if run["author_context_version"] is not None:
                try:author_meta=self._author_context_version_row(c,project_id,run["author_context_version"])
                except DomainError:author_meta=None
            author_resolved=bool(author_meta and run["author_context_snapshot_digest"] and author_meta["snapshot_digest"]==run["author_context_snapshot_digest"])
            author_status="not_recorded" if run["author_context_version"] is None else "recorded" if author_resolved else "unresolvable"
            provenance={"provider_label":run["provider_label"],"model_label":run["model_label"] or "legacy_unspecified","prompt_version":run["prompt_version"] or "legacy_unspecified","schema_version":run["schema_version"] or "legacy_unspecified","retrieval_method_version":run["retrieval_method_version"] or "legacy_unspecified","source_memory_version":run["source_memory_version"]}
            if incremental:provenance.update({"source_change_set_id":run["source_change_set_id"],"source_span_ids":source_span_ids,"incremental_batch_id":run["incremental_batch_id"]})
            metrics={"latency_ms":run["latency_ms"],"input_tokens":run["input_tokens"],"output_tokens":run["output_tokens"],"cost_cny":run["cost_cny"],"cost_available":run["cost_cny"] is not None,"provenance":provenance,"retrieval":[]}
            result={"run_id":run_id,"project_id":project_id,"run_type":run["run_type"],"status":status,"stage":stage,"source_revision":run["source_revision"],"draft_revision":run["draft_revision"],"source_memory_version":run["source_memory_version"],"author_context_version":run["author_context_version"],"author_context_version_status":author_status,"author_context_resolvable":author_resolved,"author_context_snapshot_digest":run["author_context_snapshot_digest"] if author_resolved else None,"alias_version":run["alias_version"],"alias_snapshot_digest":run["alias_snapshot_digest"],"source_change_set_id":run["source_change_set_id"],"source_span_ids":source_span_ids,"incremental_batch_id":run["incremental_batch_id"],"current_revision":draft["revision"],"is_stale":not current,"superseded":not current,"lineage_status":(("incremental_source_revision" if current else "incremental_state_changed_requires_recheck") if incremental else "validated_direct_successor" if direct_successor else "current" if current else "lineage_invalid_requires_recheck"),"result_origin":run["result_origin"],"result_origin_label":("预置演示审阅数据（未调用 Provider）" if run["result_origin"]=="demo_preset" else "Provider 检查结果"),"error_code":error_code,"retryable":bool(run["retryable"]) or run["status"]=="budget_paused","created_at":run["created_at"],"started_at":run["started_at"],"completed_at":run["completed_at"],"cancel_requested_at":run["cancel_requested_at"],"duration_ms":run["duration_ms"],"retry_of_run_id":run["retry_of_run_id"],"root_run_id":run["root_run_id"] or run_id,"attempt_number":run["attempt_number"] or 1,"transitions":transitions,"provenance":provenance,"provider_metrics":{key:metrics[key] for key in ("latency_ms","input_tokens","output_tokens","cost_cny","cost_available")}}
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
                c.execute("INSERT INTO v2_change_sets(id,project_id,run_id,source_run_revision,resolved_revision,lineage_status,base_version,target_version,status,created_at,committed_at,change_set_kind,actor_user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(change_set_id,project_id,run["id"],run["source_revision"],draft["revision"],lineage,project["current_memory_version"],project["current_memory_version"]+1,"draft",utcnow(),None,"continuity",user_id))
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
                stamp=utcnow()
                # dependent children first. The set is deliberately project-scoped.
                for table in ("v2_author_story_plan_versions","v2_author_character_plan_versions","v2_author_world_plan_versions"):
                    c.execute(f"DELETE FROM {table} WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_author_context_versions WHERE project_id=?",(project_id,))
                for table in ("v2_author_story_plans","v2_author_character_plans","v2_author_world_plans"):
                    c.execute(f"DELETE FROM {table} WHERE project_id=?",(project_id,))
                c.execute("UPDATE v2_projects SET author_context_version=0,updated_at=? WHERE id=?",(stamp,project_id))
                zero=self._insert_empty_author_context_zero(c,project_id,stamp)
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
                c.execute("DELETE FROM v2_revision_candidate_decisions WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_revision_task_versions WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_revision_tasks WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_revision_plan_candidates WHERE project_id=?",(project_id,))
                c.execute("UPDATE v2_projects SET revision_task_version=0 WHERE id=?",(project_id,))
                c.execute("DELETE FROM v2_decisions WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_evidence WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_issues WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_retrieval_traces WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_analysis_results WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_analysis_inputs WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_character_aliases WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_character_alias_state WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_run_claims WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_run_events WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_run_stages WHERE run_id IN (SELECT id FROM v2_runs WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_runs WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_draft_revisions WHERE draft_id IN (SELECT id FROM v2_drafts WHERE project_id=?)",(project_id,))
                c.execute("DELETE FROM v2_drafts WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_records WHERE project_id=?",(project_id,))
                c.execute("DELETE FROM v2_memory_versions WHERE project_id=?",(project_id,))
                if project["data_origin"] in {"demo_seed", "tutorial_seed"}:
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
                c.execute("UPDATE v2_projects SET current_memory_version=?,author_context_version=0,alias_version=0,updated_at=? WHERE id=?",(version,utcnow(),project_id))
                # A project reset invalidates replay records that reference
                # deleted drafts/runs, but retains this reset's own replay.
                c.execute("DELETE FROM v2_idempotency WHERE scope=? AND operation LIKE ? AND operation!=?",(user_id,"%"+project_id+"%","reset:"+project_id))
                reset_id=new_id("reset")
                result={"reset_id":reset_id,"project_id":project_id,"current_memory_version":version,"author_context_version":0,"author_context_snapshot_digest":zero["snapshot_digest"],"draft_revision":1,"status":"completed","data_origin":project["data_origin"]}
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
                self._complete_onboarding_for_real_project(c, user_id)
                draft=c.execute("SELECT * FROM v2_drafts WHERE project_id=?",(project_id,)).fetchone()
                c.execute("UPDATE v2_import_drafts SET committed_at=?,source_text=NULL WHERE id=?",(utcnow(),import_id))
                return {"project":{"id":project_id,"title":title,"data_origin":"user_import","status":"active","current_memory_version":1,"memory_initialization_status":"required","current_draft":{"id":draft["id"],"chapter_number":draft["chapter_number"],"revision":1}},"import":{"chapter_count":len(chapters),"source_span_count":len(chapters),"sha256":imported["sha256"],"status":"completed"}}
            return self._idem(c,user_id,"commit_import:"+import_id,key,payload,commit,201)

    def cancel_import(self, user_id: str, import_id: str, payload: dict[str, Any], key: str):
        with self.connection() as c:
            def cancel() -> dict[str, Any]:
                imported=c.execute("SELECT id,committed_at FROM v2_import_drafts WHERE id=? AND user_id=?",(import_id,user_id)).fetchone()
                if not imported: raise DomainError("import_not_found",404)
                if imported["committed_at"]: raise DomainError("already_committed",409)
                if payload.get("confirm") is not True: raise DomainError("confirmation_required",400)
                c.execute("DELETE FROM v2_import_drafts WHERE id=? AND user_id=? AND committed_at IS NULL",(import_id,user_id))
                return {"import_id":import_id,"status":"cancelled"}
            return self._idem(c,user_id,"cancel_import:"+import_id,key,payload,cancel)

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
