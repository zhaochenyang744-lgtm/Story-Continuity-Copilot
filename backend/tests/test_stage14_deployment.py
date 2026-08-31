from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.config import AppPaths
from app.deployment import DeploymentError, create_backup, migrate, restore_backup


class Stage14DeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="stage14-deployment-")
        root = Path(self.temporary.name)
        self.project_root = root / "application"
        self.backup_dir = root / "backups"
        self.project_root.mkdir()
        self.paths = AppPaths.from_project_root(self.project_root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_empty_volume_migrates_and_readiness_survives_restart(self) -> None:
        first = migrate(self.paths)
        self.assertEqual(first["operation"], "migrate")
        self.assertEqual(first["integrity"], "ok")
        connection = sqlite3.connect(self.paths.database_path)
        try:
            connection.execute("CREATE TABLE stage14_restart_probe(value TEXT NOT NULL)")
            connection.execute("INSERT INTO stage14_restart_probe VALUES('retained')")
            connection.commit()
        finally:
            connection.close()
        second = migrate(self.paths)
        self.assertEqual(second["schema_max_version"], first["schema_max_version"])
        connection = sqlite3.connect(self.paths.database_path)
        try:
            self.assertEqual(connection.execute("SELECT value FROM stage14_restart_probe").fetchone()[0], "retained")
        finally:
            connection.close()

    def test_online_backup_and_offline_restore_are_hash_verified(self) -> None:
        migrate(self.paths)
        connection = sqlite3.connect(self.paths.database_path)
        try:
            connection.execute("CREATE TABLE stage14_restore_probe(value TEXT NOT NULL)")
            connection.execute("INSERT INTO stage14_restore_probe VALUES('before')")
            connection.commit()
        finally:
            connection.close()
        backup = create_backup(self.paths, self.backup_dir, label="test")
        self.assertEqual(backup["integrity"], "ok")
        self.assertRegex(str(backup["sha256"]), r"^[0-9A-F]{64}$")
        connection = sqlite3.connect(self.paths.database_path)
        try:
            connection.execute("UPDATE stage14_restore_probe SET value='after'")
            connection.commit()
        finally:
            connection.close()
        restored = restore_backup(
            self.paths,
            self.backup_dir,
            str(backup["backup_name"]),
            str(backup["sha256"]),
            offline_confirmation="APPLICATION_STOPPED",
        )
        self.assertEqual(restored["sha256"], backup["sha256"])
        self.assertNotEqual(restored["pre_restore_backup_name"], "none")
        connection = sqlite3.connect(self.paths.database_path)
        try:
            self.assertEqual(connection.execute("SELECT value FROM stage14_restore_probe").fetchone()[0], "before")
        finally:
            connection.close()

    def test_restore_fails_closed_on_hash_name_and_offline_confirmation(self) -> None:
        migrate(self.paths)
        backup = create_backup(self.paths, self.backup_dir, label="negative")
        arguments = (self.paths, self.backup_dir, str(backup["backup_name"]), str(backup["sha256"]))
        with self.assertRaisesRegex(DeploymentError, "offline_confirmation_required"):
            restore_backup(*arguments, offline_confirmation="RUNNING")
        with self.assertRaisesRegex(DeploymentError, "backup_hash_mismatch"):
            restore_backup(
                self.paths,
                self.backup_dir,
                str(backup["backup_name"]),
                "0" * 64,
                offline_confirmation="APPLICATION_STOPPED",
            )
        with self.assertRaisesRegex(DeploymentError, "backup_name_invalid"):
            restore_backup(
                self.paths,
                self.backup_dir,
                "../" + str(backup["backup_name"]),
                str(backup["sha256"]),
                offline_confirmation="APPLICATION_STOPPED",
            )

    def test_backup_evidence_is_sanitized(self) -> None:
        migrate(self.paths)
        backup = create_backup(self.paths, self.backup_dir, label="evidence")
        serialized = json.dumps(backup, sort_keys=True)
        self.assertNotIn(str(self.project_root), serialized)
        self.assertNotIn(str(self.backup_dir), serialized)
        self.assertNotIn("retained", serialized)


if __name__ == "__main__":
    unittest.main()
