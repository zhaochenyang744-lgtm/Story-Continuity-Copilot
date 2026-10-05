"""Isolated migration and rollback guards; Docker itself is not exercised."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.config import AppPaths
from app.deployment import DeploymentError, WORKFLOW_CONTRACT, WORKFLOW_TABLES, rollback_capabilities, rollback_preflight
from app.v2_database import V2Database


BACKEND = Path(__file__).resolve().parents[1]
ROLLBACK = BACKEND.parent / "deployment" / "rollback.sh"


def envelope(**overrides):
    return json.dumps({"ok": True, "result": {**rollback_capabilities(), **overrides}})


def bash_executable():
    candidates = [shutil.which("bash")]
    git = shutil.which("git")
    if git:
        candidates.append(str(Path(git).parent.parent / "usr" / "bin" / "sh.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            result = subprocess.run([candidate, "--version"], capture_output=True, text=True, encoding="utf-8")
            if result.returncode == 0 and "GNU bash" in result.stdout:
                return candidate
    return None


class WorkflowDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-deploy-")
        self.root = Path(self.temp.name)
        self.paths = AppPaths.from_project_root(self.root / "application")
        self.db = V2Database(self.paths)
        self.db.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def dump(self):
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            return "\n".join(connection.iterdump())

    def tables(self, excluded=()):
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name") if row[0] not in excluded]
            return {name: {"columns": connection.execute(f'PRAGMA table_info("{name}")').fetchall(),
                           "rows": sorted(connection.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr)} for name in names}

    def remove_workflow(self):
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            for name in WORKFLOW_TABLES:
                connection.execute(f'DROP TABLE "{name}"')
            connection.execute("DELETE FROM schema_migrations WHERE version=146")

    def test_upgrade_145_to_146_preserves_every_existing_business_table(self):
        self.db.register({"account_name": "upgrade-author", "display_name": "Migration", "password": "safe-migration-password"}, "migration-author-registration")
        self.remove_workflow()
        before = self.tables(excluded={"schema_migrations"})
        self.assertGreater(len(before), 40)
        self.assertTrue(before["v2_projects"]["rows"])
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 145)
        self.db.initialize()
        self.assertEqual(self.tables(excluded=WORKFLOW_TABLES | {"schema_migrations"}), before)
        first = self.dump()
        self.db.initialize()
        self.assertEqual(self.dump(), first)
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            self.assertEqual(connection.execute("SELECT MAX(version),COUNT(CASE WHEN version=146 THEN 1 END) FROM schema_migrations").fetchone(), (146, 1))
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(WORKFLOW_TABLES <= names)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migration_marker_only_records_successful_initialization(self):
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            connection.execute("DELETE FROM schema_migrations WHERE version=146")
        before = self.dump()
        with patch.object(self.db, "_migrate_v140_rich_draft_formats", side_effect=RuntimeError("injected-tail-failure")):
            with self.assertRaisesRegex(RuntimeError, "injected-tail-failure"):
                self.db.initialize()
        self.assertEqual(self.dump(), before)
        self.db.initialize()
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 146)

    def test_preflight_requires_contract_for_empty_unversioned_workflow_tables(self):
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            connection.execute("DELETE FROM schema_migrations WHERE version=146")
        before = self.dump()
        with self.assertRaisesRegex(DeploymentError, "rollback_workflow_contract_unsupported"):
            rollback_preflight(self.paths, envelope(workflow_contracts=[], schema_max_supported=145))
        self.assertEqual(self.dump(), before)

    def test_compatible_preflight_reads_without_mutating_database(self):
        before = self.paths.database_path.read_bytes()
        result = rollback_preflight(self.paths, envelope())
        self.assertEqual(result["required_workflow_contracts"], [WORKFLOW_CONTRACT])
        self.assertTrue(result["read_only"])
        self.assertEqual(result["schema_max_version"], 146)
        self.assertEqual(self.paths.database_path.read_bytes(), before)
        self.assertFalse(self.paths.database_path.with_suffix(".sqlite3-journal").exists())

    def test_old_plain_schema_can_pass_explicit_capability_check(self):
        self.remove_workflow()
        result = rollback_preflight(self.paths, envelope(workflow_contracts=[], schema_max_supported=145))
        self.assertEqual(result["required_workflow_contracts"], [])

    def test_future_schema_and_invalid_capabilities_fail_closed(self):
        malformed = ["", "not json", "null", "[]", "{}", '{"ok":true,"result":null}', '{"ok":true,"result":[]}', envelope(schema_max_supported=True), envelope(schema_max_supported="146"),
                     envelope(workflow_contracts=WORKFLOW_CONTRACT), envelope(workflow_contracts=[1]),
                     json.dumps({"ok": "true", "result": rollback_capabilities()})]
        before = self.dump()
        for value in malformed:
            with self.subTest(capabilities=value), self.assertRaisesRegex(DeploymentError, "rollback_target_capabilities_invalid"):
                rollback_preflight(self.paths, value)
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            connection.execute("INSERT INTO schema_migrations VALUES(147,'future-fixture')")
        future = self.dump()
        with self.assertRaisesRegex(DeploymentError, "rollback_schema_version_unsupported"):
            rollback_preflight(self.paths, envelope())
        self.assertEqual(self.dump(), future)
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            connection.execute("DELETE FROM schema_migrations WHERE version=147")
        self.assertEqual(self.dump(), before)

    def test_preflight_does_not_create_missing_database(self):
        missing = AppPaths.from_project_root(self.root / "missing")
        with self.assertRaisesRegex(DeploymentError, "database_missing"):
            rollback_preflight(missing, envelope())
        self.assertFalse(missing.project_root.exists())

    def test_preflight_rejects_missing_schema_and_foreign_key_violations(self):
        before = self.dump()
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            connection.execute("INSERT INTO v2_workflow_run_bindings VALUES('missing-run','missing-project','{}','invalid')")
        with self.assertRaisesRegex(DeploymentError, "rollback_database_integrity_failed"):
            rollback_preflight(self.paths, envelope())
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            connection.execute("DELETE FROM v2_workflow_run_bindings")
        self.assertEqual(self.dump(), before)
        with closing(sqlite3.connect(self.paths.database_path)) as connection, connection:
            connection.execute("ALTER TABLE schema_migrations RENAME TO missing_schema_migrations")
        with self.assertRaisesRegex(DeploymentError, "rollback_application_schema_missing"):
            rollback_preflight(self.paths, envelope())

    def test_capability_command_does_not_initialize_application_or_database(self):
        absent = self.root / "absent"
        command = [sys.executable, "-B", "-m", "app.deployment", "--project-root", str(absent), "rollback-capabilities"]
        result = subprocess.run(command, cwd=BACKEND, env={**os.environ, "SCC_DISABLE_DEFAULT_APP": "1"}, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True, "result": rollback_capabilities()})
        self.assertFalse(absent.exists())

    def test_cli_rejects_incompatible_target_without_writes(self):
        before = self.dump()
        command = [sys.executable, "-B", "-m", "app.deployment", "--project-root", str(self.paths.project_root), "rollback-preflight", "--target-capabilities", envelope(workflow_contracts=[])]
        result = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error_code"], "rollback_workflow_contract_unsupported")
        self.assertEqual(self.dump(), before)

    def test_rollback_script_stops_before_backup_and_switch_on_every_precheck_failure(self):
        shell = bash_executable()
        if not shell:
            self.skipTest("GNU Bash unavailable; no Docker runtime is used by this test")
        environment_file = self.root / "deploy.env"
        environment_file.write_text("PUBLIC_HOST=local.test\nRELEASE_ID=wrong-release-from-env\n", encoding="utf-8", newline="\n")
        wrapper = self.root / "rollback-stub.sh"
        wrapper.write_text(r'''#!/usr/bin/env bash
set -euo pipefail
docker() {
  printf '%s | release=%s\n' "$*" "${RELEASE_ID:-unset}" >> "$STUB_LOG"
  if [[ "$1" == image ]]; then return 0; fi
  if [[ "$1" == run ]]; then
    if [[ "$STUB_MODE" == missing_target_command ]]; then return 2; fi
    if [[ "$STUB_MODE" == malformed ]]; then printf '%s\n' 'invalid output'; return 0; fi
    printf '%s\n' "$STUB_CAPABILITIES"; return 0
  fi
  if [[ "$*" == *' ps '* ]]; then
    if [[ "$STUB_MODE" != stopped ]]; then printf '%s\n' backend; fi
    return 0
  fi
  if [[ "$*" == *' rollback-preflight '* ]]; then
    if [[ "$STUB_MODE" == missing_current_command ]]; then return 2; fi
    "$STUB_PYTHON" -B -m app.deployment --project-root "$STUB_PROJECT" rollback-preflight --target-capabilities "${@: -1}"
    return $?
  fi
  if [[ "$*" == *' app.deployment backup '* && "$STUB_MODE" == backup_failure ]]; then return 1; fi
  return 0
}
bash() { return 0; }
curl() { return 0; }
seq() { printf '%s\n' 1; }
source "$1" "$2" target-release
''', encoding="utf-8", newline="\n")
        for mode in ("missing_target_command", "missing_current_command", "malformed", "incompatible", "stopped", "backup_failure", "compatible"):
            with self.subTest(mode=mode):
                log = self.root / f"{mode}.log"
                capabilities = envelope(workflow_contracts=[] if mode == "incompatible" else [WORKFLOW_CONTRACT])
                environment = {**os.environ, "STUB_MODE": mode, "STUB_LOG": log.as_posix(),
                               "PATH": str(Path(shell).parent) + os.pathsep + os.environ.get("PATH", ""),
                               "PYTHONPATH": str(BACKEND),
                               "STUB_CAPABILITIES": capabilities, "STUB_PYTHON": Path(sys.executable).as_posix(),
                               "STUB_PROJECT": self.paths.project_root.as_posix(), "SCC_DISABLE_DEFAULT_APP": "1"}
                result = subprocess.run([shell, str(wrapper), str(ROLLBACK), str(environment_file)], cwd=BACKEND, env=environment, capture_output=True, text=True, encoding="utf-8")
                lines = log.read_text(encoding="utf-8")
                if mode != "stopped":
                    self.assertIn("rollback-capabilities", lines)
                if mode not in {"stopped", "missing_target_command"}:
                    self.assertIn("rollback-preflight", lines)
                if mode == "compatible":
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertLess(lines.index("rollback-preflight"), lines.index("app.deployment backup"))
                    self.assertLess(lines.index("app.deployment backup"), lines.index("up -d"))
                    self.assertIn("up -d --no-build --remove-orphans | release=target-release", lines)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    if mode != "backup_failure":
                        self.assertNotIn("app.deployment backup", lines)
                    self.assertNotIn("up -d", lines)
                for line in lines.splitlines():
                    if line.startswith("run "):
                        self.assertIn("--network none --read-only", line)
                        self.assertIn("--entrypoint python", line)
                        self.assertIn("-B -m app.deployment rollback-capabilities", line)
                        self.assertNotIn("--volume", line)
                        self.assertNotIn("--mount", line)
                        self.assertNotIn("--env", line)
                        self.assertNotIn("/run/secrets", line)


if __name__ == "__main__":
    unittest.main()
