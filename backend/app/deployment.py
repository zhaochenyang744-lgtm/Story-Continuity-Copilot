from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone

from .config import AppPaths, PROJECT_ROOT, _is_within, _resolved
from .v2_database import V2Database


class DeploymentError(RuntimeError):
    pass


WORKFLOW_CONTRACT = "historical-source-review-and-decision-reuse-v1"
WORKFLOW_TABLES = frozenset({
    "v2_workflow_run_bindings", "v2_decision_reuse", "v2_decision_reuse_events",
    "v2_chapter_revision_history", "v2_chapter_content_formats", "v2_source_revision_reviews",
})


def rollback_capabilities() -> dict:
    """Static image marker: this command never opens or initializes a database."""
    return {"operation": "rollback-capabilities", "schema_max_supported": 146,
            "workflow_contracts": [WORKFLOW_CONTRACT]}


def rollback_preflight(paths: AppPaths, target_capabilities: str) -> dict:
    """Read the current database and fail closed before selecting an old image."""
    try:
        envelope = json.loads(target_capabilities)
        target = envelope["result"]
        if envelope["ok"] is not True or target["operation"] != "rollback-capabilities":
            raise ValueError
        maximum = target["schema_max_supported"]
        contracts = target["workflow_contracts"]
        if type(maximum) is not int or maximum < 1 or not isinstance(contracts, list):
            raise ValueError
        if any(not isinstance(contract, str) or not contract for contract in contracts):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise DeploymentError("rollback_target_capabilities_invalid") from None

    paths.validate_database_target()
    if not paths.database_path.is_file():
        raise DeploymentError("database_missing")
    connection = sqlite3.connect(paths.database_path.as_uri() + "?mode=ro", uri=True, timeout=15)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "schema_migrations" not in names or "v2_projects" not in names:
            raise DeploymentError("rollback_application_schema_missing")
        version = connection.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
        if type(version) is not int or version < 1:
            raise DeploymentError("rollback_application_schema_invalid")
        required = bool(names & WORKFLOW_TABLES) or version >= 146
        if "v2_source_change_sets" in names:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(v2_source_change_sets)")}
            if "mode" in columns:
                required = required or bool(connection.execute("SELECT 1 FROM v2_source_change_sets WHERE mode='revise' LIMIT 1").fetchone())
        if required and WORKFLOW_CONTRACT not in contracts:
            raise DeploymentError("rollback_workflow_contract_unsupported")
        if version > maximum:
            raise DeploymentError("rollback_schema_version_unsupported")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchone():
            raise DeploymentError("rollback_database_integrity_failed")
        return {"operation": "rollback-preflight", "compatible": True, "read_only": True,
                "schema_max_version": version, "target_schema_max_supported": maximum,
                "required_workflow_contracts": [WORKFLOW_CONTRACT] if required else []}
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _database_summary(path: Path) -> dict[str, int | str]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=15)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        migrations = connection.execute("SELECT COUNT(*), COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    finally:
        connection.close()
    if not integrity or integrity[0] != "ok" or foreign_keys:
        raise DeploymentError("backup_integrity_failed")
    return {
        "schema_migration_count": int(migrations[0]),
        "schema_max_version": int(migrations[1]),
        "integrity": "ok",
    }


def _safe_backup_dir(paths: AppPaths, backup_dir: Path) -> Path:
    destination = _resolved(backup_dir)
    if _is_within(destination, paths.project_root) or _is_within(destination, paths.protected_poc_root):
        raise DeploymentError("backup_directory_must_be_outside_application_and_protected_roots")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def migrate(paths: AppPaths) -> dict[str, int | str]:
    database = V2Database(paths)
    database.initialize()
    summary = _database_summary(paths.database_path)
    return {"operation": "migrate", **summary}


def create_backup(paths: AppPaths, backup_dir: Path, *, label: str = "manual") -> dict[str, int | str]:
    paths.validate_database_target()
    if not paths.database_path.is_file():
        raise DeploymentError("database_missing")
    destination_dir = _safe_backup_dir(paths, backup_dir)
    safe_label = "".join(character for character in label.casefold() if character.isalnum() or character in {"-", "_"})[:32]
    if not safe_label:
        raise DeploymentError("backup_label_invalid")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"story-continuity-{safe_label}-{timestamp}.sqlite3"
    destination = destination_dir / name
    if destination.exists():
        raise DeploymentError("backup_already_exists")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".backup-", suffix=".sqlite3", dir=destination_dir)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        source = sqlite3.connect(paths.database_path, timeout=30)
        target = sqlite3.connect(temporary)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        summary = _database_summary(temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "operation": "backup",
        "backup_name": name,
        "sha256": _sha256(destination),
        "bytes": destination.stat().st_size,
        **summary,
    }


def restore_backup(
    paths: AppPaths,
    backup_dir: Path,
    backup_name: str,
    expected_sha256: str,
    *,
    offline_confirmation: str,
) -> dict[str, int | str]:
    if offline_confirmation != "APPLICATION_STOPPED":
        raise DeploymentError("offline_confirmation_required")
    if Path(backup_name).name != backup_name or any(separator in backup_name for separator in ("/", "\\")):
        raise DeploymentError("backup_name_invalid")
    destination_dir = _safe_backup_dir(paths, backup_dir)
    source = destination_dir / backup_name
    if not source.is_file():
        raise DeploymentError("backup_missing")
    actual_sha256 = _sha256(source)
    if actual_sha256 != expected_sha256.upper():
        raise DeploymentError("backup_hash_mismatch")
    summary = _database_summary(source)
    paths.prepare_runtime()
    recovery = None
    if paths.database_path.exists():
        recovery = create_backup(paths, destination_dir, label="pre-restore")
    temporary = paths.database_path.with_name(".restore-candidate.sqlite3")
    if temporary.exists():
        raise DeploymentError("restore_candidate_exists")
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        if _sha256(temporary) != actual_sha256:
            raise DeploymentError("restore_copy_hash_mismatch")
        os.replace(temporary, paths.database_path)
        V2Database(paths).initialize()
        restored = _database_summary(paths.database_path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        if recovery:
            recovery_source = destination_dir / str(recovery["backup_name"])
            shutil.copyfile(recovery_source, paths.database_path)
        raise
    return {
        "operation": "restore",
        "backup_name": backup_name,
        "sha256": actual_sha256,
        "bytes": paths.database_path.stat().st_size,
        "pre_restore_backup_name": recovery["backup_name"] if recovery else "none",
        **summary,
        "restored_schema_max_version": restored["schema_max_version"],
    }


def _paths(project_root: Path) -> AppPaths:
    return AppPaths.from_project_root(project_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deployment-safe SQLite operations")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    subparsers.add_parser("rollback-capabilities")
    preflight_parser = subparsers.add_parser("rollback-preflight")
    preflight_parser.add_argument("--target-capabilities", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--backup-dir", type=Path, required=True)
    backup_parser.add_argument("--label", default="manual")
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup-dir", type=Path, required=True)
    restore_parser.add_argument("--backup-name", required=True)
    restore_parser.add_argument("--sha256", required=True)
    restore_parser.add_argument("--offline-confirmation", required=True)
    args = parser.parse_args()
    try:
        if args.command == "rollback-capabilities":
            print(json.dumps({"ok": True, "result": rollback_capabilities()}, sort_keys=True))
            return 0
        paths = _paths(args.project_root)
        if args.command == "rollback-preflight":
            result = rollback_preflight(paths, args.target_capabilities)
        elif args.command == "migrate":
            result = migrate(paths)
        elif args.command == "backup":
            result = create_backup(paths, args.backup_dir, label=args.label)
        else:
            result = restore_backup(
                paths,
                args.backup_dir,
                args.backup_name,
                args.sha256,
                offline_confirmation=args.offline_confirmation,
            )
    except (DeploymentError, sqlite3.Error, OSError) as error:
        print(json.dumps({"ok": False, "error_code": str(error)}, ensure_ascii=True))
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
