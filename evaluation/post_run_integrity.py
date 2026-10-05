"""Strict validation primitives for retained evaluation evidence."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from typing import Any


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_retained_integrity(
    root: pathlib.Path,
    integrity_path: pathlib.Path,
    *,
    expected_evaluation: str | None = None,
    expected_artifacts: dict[str, str] | None = None,
    expected_workspace_root: str | None = None,
    expected_run_status_totals: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Validate retained files and SQLite workspaces without modifying either."""
    payload = json.loads(integrity_path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "scc-evaluation-post-run-integrity-v1"
        or payload.get("integrity_status") != "retained_baseline"
        or payload.get("raw_provider_content_retained") is not False
        or (expected_evaluation is not None and payload.get("evaluation") != expected_evaluation)
    ):
        raise ValueError("post_run_integrity_schema_invalid")
    retained = payload.get("retained_artifacts")
    files = retained.get("files") if isinstance(retained, dict) else None
    if retained.get("count") != 7 or not isinstance(files, list) or len(files) != 7:
        raise ValueError("post_run_artifact_count_invalid")
    recorded_paths = {item.get("path") for item in files if isinstance(item, dict)}
    if len(recorded_paths) != 7 or any(not isinstance(path, str) or path.startswith("/") or ":" in path for path in recorded_paths):
        raise ValueError("post_run_artifact_paths_invalid")
    if expected_artifacts is not None and recorded_paths != set(expected_artifacts):
        raise ValueError("post_run_artifact_paths_invalid")
    for item in files:
        path = root / item["path"]
        expected_hash = expected_artifacts.get(item["path"]) if expected_artifacts is not None else item.get("sha256")
        if (
            not path.is_file()
            or item.get("sha256") != expected_hash
            or sha256_file(path) != expected_hash
            or path.stat().st_size != item.get("size")
        ):
            raise ValueError("post_run_artifact_hash_mismatch")
    workspaces = payload.get("fixture_workspaces")
    database_items = workspaces.get("sqlite_files") if isinstance(workspaces, dict) else None
    workspace_root = workspaces.get("root") if isinstance(workspaces, dict) else None
    if (
        not isinstance(workspace_root, str)
        or workspace_root.startswith("/")
        or ":" in workspace_root
        or workspaces.get("sqlite_count") != 15
        or not isinstance(database_items, list)
        or len(database_items) != 15
        or (expected_workspace_root is not None and workspace_root != expected_workspace_root)
    ):
        raise ValueError("post_run_workspace_count_invalid")
    keys = [item.get("workspace_key") for item in database_items if isinstance(item, dict)]
    if len(keys) != 15 or len(set(keys)) != 15 or any(not isinstance(key, str) or not key for key in keys):
        raise ValueError("post_run_workspace_keys_invalid")
    totals: dict[str, int] = {}
    for item in database_items:
        path = root / workspace_root / item["workspace_key"] / "runtime" / "data" / "demo.sqlite3"
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("post_run_workspace_hash_mismatch")
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            statuses = dict(connection.execute("SELECT status, COUNT(*) FROM v2_runs GROUP BY status"))
        finally:
            connection.close()
        if statuses != item.get("run_status"):
            raise ValueError("post_run_workspace_status_mismatch")
        for status, count in statuses.items():
            totals[status] = totals.get(status, 0) + count
    if totals != workspaces.get("run_status_totals") or (expected_run_status_totals is not None and totals != expected_run_status_totals):
        raise ValueError("post_run_status_totals_mismatch")
    return {
        "valid": True,
        "artifact_count": 7,
        "fixture_sqlite_count": 15,
        "run_status_totals": totals,
    }
