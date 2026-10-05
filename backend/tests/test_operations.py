from datetime import timedelta
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import operations as ops


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="scc-operations-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "runtime" / "demo.sqlite3"
        self.database.parent.mkdir()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript("""
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY);
            INSERT INTO schema_migrations VALUES(145);
            CREATE TABLE v2_runs(id TEXT PRIMARY KEY,status TEXT,input_tokens INTEGER,output_tokens INTEGER,
             cost_cny REAL,created_at TEXT,completed_at TEXT,started_at TEXT,result_origin TEXT);
            CREATE TABLE v2_usage_reservations(reserved_microunits INTEGER,created_at TEXT);
            CREATE TABLE v2_provider_attempts(created_at TEXT);
            CREATE TABLE private_content(body TEXT);
            INSERT INTO private_content VALUES('PRIVATE_NOVEL_CANARY_DO_NOT_EMIT');
            """)
        self.config_path = self.root / "config.json"
        self.raw = {"database": str(self.database), "backup_dir": str(self.root / "backups"),
                    "state_dir": str(self.root / "state"), "drill_dir": str(self.root / "drills"),
                    "health_origin": "http://127.0.0.1:1", "local_test_mirror": str(self.root / "mirror")}
        self.config_path.write_text(json.dumps(self.raw))
        self.config = ops.load_config(self.config_path)

    def insert_run(self, run_id, status, tokens, cost, created=None, completed=None, origin="provider"):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO v2_runs VALUES(?,?,?,?,?,?,?,?,?)",
                               (run_id, status, tokens, tokens, cost, created or ops.stamp(), completed,
                                created or ops.stamp(), origin))

    def test_online_wal_backup_mirror_and_isolated_recovery(self):
        connection = sqlite3.connect(self.database)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO private_content VALUES('committed_in_wal')")
        connection.commit()
        result = ops.backup(self.config)
        self.assertEqual(result["offsite"]["status"], "local_test_verified")
        self.assertFalse(result["offsite"]["is_off_instance"])
        connection.execute("INSERT INTO private_content VALUES('after_snapshot')")
        connection.commit()
        source_count = connection.execute("SELECT COUNT(*) FROM private_content").fetchone()[0]
        with ops.readonly(self.config["backup_dir"] / result["backup_name"]) as snapshot:
            self.assertEqual(snapshot.execute("SELECT COUNT(*) FROM private_content").fetchone()[0], 2)
        restored = ops.drill(self.config)
        self.assertEqual(restored["status"], "passed")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM private_content").fetchone()[0], source_count)
        self.assertEqual(list(self.config["drill_dir"].iterdir()), [])
        self.assertNotIn("PRIVATE_NOVEL", json.dumps([result, restored]))

    def test_corrupt_snapshot_is_rejected_before_drill(self):
        result = ops.backup(self.config)
        target = self.config["backup_dir"] / result["backup_name"]
        with target.open("ab") as handle:
            handle.write(b"corruption")
        with self.assertRaisesRegex(ops.OperationsError, "backup_hash_mismatch"):
            ops.drill(self.config)

    def test_unknown_metrics_are_not_zero_or_budget(self):
        self.insert_run("known", "completed", 12, 0.12)
        self.insert_run("unknown", "failed", None, None)
        self.insert_run("preset", "completed", 9000, 9000, origin="demo_preset")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO v2_usage_reservations VALUES(5000000,?)", (ops.stamp(),))
            connection.execute("INSERT INTO v2_provider_attempts VALUES(?)", (ops.stamp(),))
        result = ops.usage(self.config)
        self.assertEqual(result["provider_run_count"], 2)
        self.assertEqual(result["provider_attempt_count"], 1)
        self.assertEqual(result["reserved_budget_cny"], 5)
        costs = result["run_observed_metrics"]["cost_cny"]
        self.assertEqual(costs["known_run_sum"], 0.12)
        self.assertEqual(costs["unknown_run_count"], 1)
        self.assertIsNone(costs["all_run_sum"])
        self.assertIsNone(result["billed_cost_cny"])
        self.assertNotIn("PRIVATE_NOVEL", json.dumps(result))

    def test_zero_known_usage_and_missing_attempt_table_distinguished(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("DROP TABLE v2_provider_attempts")
        result = ops.usage(self.config)
        self.assertIsNone(result["provider_attempt_count"])
        self.assertEqual(result["provider_attempt_status"], "unknown")
        self.assertEqual(result["run_observed_metrics"]["input_tokens"]["all_run_sum"], 0)

    def test_old_stuck_and_recently_finished_old_run_are_detected(self):
        old = (ops.now() - timedelta(days=3)).isoformat()
        self.insert_run("old_running", "running", None, None, old)
        self.insert_run("old_failed", "failed", None, None, old, ops.stamp())
        result = ops.usage(self.config)
        self.assertEqual(result["stuck_run_count"], 1)
        self.assertEqual(result["run_status_counts"]["failed"], 1)

    def test_monitor_deduplicates_alerts_and_never_calls_provider(self):
        self.insert_run("failed", "timed_out", None, None)
        with patch.object(ops, "probe", return_value={"ok": False, "http_status": 503}):
            result = ops.monitor(self.config)
            again = ops.monitor(self.config)
        self.assertEqual(result["alerts"], again["alerts"])
        self.assertIn("backup_missing", result["alerts"])
        self.assertIn("failed_runs_in_window", result["alerts"])
        self.assertIn("health_unavailable", result["alerts"])
        self.assertEqual(len(list((self.config["state_dir"] / "alerts").glob("*.json"))), 1)
        self.assertTrue((self.config["state_dir"] / "usage-latest.json").exists())

    def test_mirror_does_not_clear_offsite_alert_and_stale_backup_alerts(self):
        result = ops.backup(self.config)
        ops.drill(self.config)
        result["created_at"] = (ops.now() - timedelta(days=2)).isoformat()
        ops.write_json((self.config["backup_dir"] / result["backup_name"]).with_suffix(".json"), result)
        with patch.object(ops, "probe", return_value={"ok": True, "http_status": 200}):
            alerts = ops.monitor(self.config)["alerts"]
        self.assertIn("backup_stale", alerts)
        self.assertIn("offsite_copy_missing", alerts)
        self.assertNotIn("restore_drill_missing", alerts)

    def test_retention_only_reports_and_preserves_existing_files(self):
        historical = self.config["backup_dir"] / "manual-legacy.sqlite3"
        historical.write_bytes(b"preserve old backup")
        self.config["minimum_backups"] = 1
        for _ in range(3):
            result = ops.backup(self.config)
            result["created_at"] = (ops.now() - timedelta(days=60)).isoformat()
            ops.write_json((self.config["backup_dir"] / result["backup_name"]).with_suffix(".json"), result)
        before = {p.name: ops.sha256(p) for p in self.config["backup_dir"].iterdir()}
        result = ops.retention(self.config)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["deleted_count"], 0)
        self.assertEqual(before, {p.name: ops.sha256(p) for p in self.config["backup_dir"].iterdir()})

    def test_overlapping_and_protected_paths_fail_before_writes(self):
        self.raw["backup_dir"] = str(self.database.parent / "backups")
        self.config_path.write_text(json.dumps(self.raw))
        with self.assertRaisesRegex(ops.OperationsError, "output_overlaps_source"):
            ops.load_config(self.config_path)
        self.assertFalse((self.database.parent / "backups").exists())

    def test_health_probe_validates_real_json_without_outputting_payload(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok" if self.path == "/health" else "not_ready",
                                            "secret": "PRIVATE_NOVEL_CANARY_DO_NOT_EMIT"}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = "http://127.0.0.1:" + str(server.server_port)
            health = ops.probe(origin, "/health")
            ready = ops.probe(origin, "/readiness")
            self.assertTrue(health["ok"])
            self.assertFalse(ready["ok"])
            self.assertNotIn("PRIVATE_NOVEL", json.dumps([health, ready]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_current_full_schema_restores_in_isolation(self):
        from app.config import AppPaths
        from app.v2_database import V2Database
        project = self.root / "full-application"
        project.mkdir()
        paths = AppPaths.from_project_root(project)
        V2Database(paths).initialize()
        self.config["database"] = paths.database_path
        result = ops.backup(self.config)
        restored = ops.drill(self.config)
        self.assertEqual(restored["schema_version"], result["schema_version"])
        self.assertGreater(restored["table_count"], 40)
        self.assertEqual(restored["committed_write_probe"], "passed")


if __name__ == "__main__":
    unittest.main()
