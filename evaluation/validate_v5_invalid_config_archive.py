"""Validate the immutable V5 invalid-config run archive without reopening quality scoring."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "evaluation" / "results" / "invalid-runs" / "v5-invalid-config-url-scheme-typo"
MANIFEST = ARCHIVE / "invalid-run-manifest.json"
EXPECTED_MANIFEST_SHA256 = "3edc0608493ff7fa95e6b00b8523b4b42ca607ee8b192496ae6f79e999d3bb1c"
EXPECTED_NOTE_SHA256 = "418adaa270406464f080ac2796eab7c3476b195d656d3af80337ab67993e6ddd"
EXPECTED_WORKSPACE_SUMMARY_SHA256 = "be5f9584c99914f5c0c6cfde189e8a7cd32441262b8e1b12abd5d5adb6b96ac9"


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate() -> dict[str, Any]:
    if sha256_file(MANIFEST) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("v5_invalid_archive_manifest_hash_mismatch")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != "scc-evaluation-invalid-run-manifest-v1"
        or manifest.get("archive_id") != "v5-invalid-config-url-scheme-typo"
        or manifest.get("status") != "invalid_configuration_run_excluded_from_quality_gate"
    ):
        raise ValueError("v5_invalid_archive_manifest_schema_invalid")
    incident = manifest.get("incident", {})
    if incident != {
        "base_url_scheme": "ttps",
        "failure_boundary": "client_url_validation_or_before_successful_transport",
        "provider_run_records": 30,
        "formal_run_records": 24,
        "stability_run_records": 6,
        "terminal_error_counts": {"provider_error": 30},
        "successful_provider_responses": 0,
        "input_tokens_returned": 0,
        "output_tokens_returned": 0,
        "cost": "unavailable",
        "counts_toward_v5_model_quality_gate": False,
    }:
        raise ValueError("v5_invalid_archive_incident_invalid")
    privacy = manifest.get("privacy", {})
    if set(privacy.values()) != {False} or len(privacy) != 5:
        raise ValueError("v5_invalid_archive_privacy_invalid")

    files = manifest.get("original_result_files")
    if not isinstance(files, dict) or len(files) != 8:
        raise ValueError("v5_invalid_archive_file_count_invalid")
    for name, expected in files.items():
        path = ARCHIVE / name
        if not path.is_file() or sha256_file(path) != expected.get("sha256") or path.stat().st_size != expected.get("size"):
            raise ValueError("v5_invalid_archive_file_hash_mismatch")

    note = manifest.get("incident_note", {})
    note_path = ROOT / note.get("path", "")
    if note_path != ARCHIVE / "incident.md" or sha256_file(note_path) != EXPECTED_NOTE_SHA256 or note.get("sha256") != EXPECTED_NOTE_SHA256 or note_path.stat().st_size != note.get("size"):
        raise ValueError("v5_invalid_archive_note_hash_mismatch")
    note_text = note_path.read_text(encoding="utf-8")
    if re.search(r"https?://|sk-[A-Za-z0-9_-]{8,}|Bearer\s+", note_text, re.IGNORECASE):
        raise ValueError("v5_invalid_archive_note_sensitive_value")

    old_integrity = json.loads((ARCHIVE / "v5-first-formal-post-run-integrity.json").read_text(encoding="utf-8"))
    old_workspaces = old_integrity.get("fixture_workspaces", {})
    archive_workspace = manifest.get("archived_workspace", {})
    summary = {
        "root": archive_workspace.get("path"),
        "sqlite_count": old_workspaces.get("sqlite_count"),
        "run_status_totals": old_workspaces.get("run_status_totals"),
        "sqlite_files": old_workspaces.get("sqlite_files"),
    }
    if (
        archive_workspace.get("sqlite_count") != 24
        or archive_workspace.get("run_status_totals") != {"failed": 30}
        or archive_workspace.get("canonical_summary_sha256") != EXPECTED_WORKSPACE_SUMMARY_SHA256
        or canonical_sha256(summary) != EXPECTED_WORKSPACE_SUMMARY_SHA256
    ):
        raise ValueError("v5_invalid_archive_workspace_summary_invalid")
    workspace_root = ROOT / archive_workspace["path"]
    sqlite_files = summary["sqlite_files"]
    if not isinstance(sqlite_files, list) or len(sqlite_files) != 24:
        raise ValueError("v5_invalid_archive_workspace_count_invalid")
    totals: dict[str, int] = {}
    for item in sqlite_files:
        path = workspace_root / item["workspace_key"] / "runtime" / "data" / "demo.sqlite3"
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("v5_invalid_archive_workspace_hash_mismatch")
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            statuses = dict(connection.execute("SELECT status, COUNT(*) FROM v2_runs GROUP BY status"))
        finally:
            connection.close()
        if statuses != item.get("run_status"):
            raise ValueError("v5_invalid_archive_workspace_status_mismatch")
        for status, count in statuses.items():
            totals[status] = totals.get(status, 0) + count
    if totals != {"failed": 30}:
        raise ValueError("v5_invalid_archive_workspace_totals_invalid")

    results = json.loads((ARCHIVE / "eval-v5-first-formal-results.json").read_text(encoding="utf-8"))
    formal = results.get("formal_case_results")
    stability = json.loads((ARCHIVE / "eval-v5-first-formal-stability.json").read_text(encoding="utf-8")).get("rows")
    if not isinstance(formal, list) or len(formal) != 24 or any(row.get("terminal_status") != "failed" or row.get("terminal_error_code") != "provider_error" for row in formal):
        raise ValueError("v5_invalid_archive_formal_outcome_invalid")
    if not isinstance(stability, list) or len(stability) != 3 or any(len(row.get("runs", [])) != 3 or any(run.get("terminal_status") != "failed" for run in row["runs"]) for row in stability):
        raise ValueError("v5_invalid_archive_stability_outcome_invalid")
    scan = json.loads((ARCHIVE / "eval-v5-first-formal-api-corpus-scan.json").read_text(encoding="utf-8"))
    if scan.get("unresolved") != 0:
        raise ValueError("v5_invalid_archive_api_scan_invalid")

    return {
        "valid": True,
        "status": manifest["status"],
        "archived_original_result_files": 8,
        "archived_sqlite_count": 24,
        "provider_run_records": 30,
        "successful_provider_responses": 0,
        "counts_toward_v5_model_quality_gate": False,
        "hashes_unchanged": True,
    }


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
