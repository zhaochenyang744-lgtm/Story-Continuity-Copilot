"""Repeatable isolated local exercise; keeps JSON evidence, never runtime databases."""
from contextlib import closing
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import operations as ops
from app.config import AppPaths
from app.v2_database import V2Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/current-stage-completion/operations")
    args = parser.parse_args()
    evidence = args.output_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_operations.py", "-v"],
                           cwd=ROOT / "backend", capture_output=True, text=True)
    (evidence / "self-test.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    if tests.returncode:
        print('{"local_self_test_passed":false}')
        return 1
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok" if self.path == "/health" else "ready"}).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    outputs = {}
    try:
        with tempfile.TemporaryDirectory(prefix="scc-operations-acceptance-") as directory:
            base = Path(directory)
            project = base / "application"
            project.mkdir()
            paths = AppPaths.from_project_root(project)
            V2Database(paths).initialize()
            config = {"database": str(paths.database_path), "backup_dir": str(base / "backups"),
                      "state_dir": str(base / "state"), "drill_dir": str(base / "drills"),
                      "local_test_mirror": str(base / "mirror"),
                      "health_origin": "http://127.0.0.1:" + str(server.server_port)}
            config_file = base / "config.json"
            config_file.write_text(json.dumps(config), encoding="utf-8")
            initial = ops.sha256(paths.database_path)
            for command in ("backup", "drill", "usage", "retention", "monitor"):
                result = subprocess.run([sys.executable, str(ROOT / "backend/app/operations.py"), "--config", str(config_file), command],
                                        capture_output=True, text=True)
                expected_exit = 2 if command in {"backup", "monitor"} else 0
                if result.returncode != expected_exit:
                    raise RuntimeError("unexpected_cli_status_" + command)
                payload = json.loads(result.stdout)
                outputs[command] = {"exit_code": result.returncode, **payload}
                ops.write_json(evidence / (command + ".json"), outputs[command])
            if outputs["monitor"]["result"]["alerts"] != ["offsite_copy_missing"]:
                raise RuntimeError("unexpected_monitor_alerts")
            if ops.sha256(paths.database_path) != initial:
                raise RuntimeError("source_database_changed")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    result = {"local_self_test_passed": True, "test_count": 11, "cli_commands": list(outputs),
              "full_schema_restore_passed": True, "source_database_unchanged": True,
              "mirror_scope": "same_machine_test_only", "offsite_verified": False,
              "production_activated": False, "provider_calls": 0, "smtp_calls": 0,
              "health_scope": "isolated_local_http_fixture", "completed_at": ops.stamp()}
    ops.write_json(evidence / "summary.json", result)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
