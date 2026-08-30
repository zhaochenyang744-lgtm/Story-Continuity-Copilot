"""Create V8's one-time post-run integrity record after an authorised run."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sqlite3
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
WORKSPACE_ROOT = ROOT / "evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal"
INTEGRITY_PATH = RESULTS / "v8-first-formal-post-run-integrity.json"
ARTIFACT_PATHS = tuple(f"evaluation/results/eval-v8-first-formal-{suffix}" for suffix in ("api-corpus-scan.json", "bad-cases.json", "checkpoint.json", "report.md", "results.json", "run-manifest.json", "stability.json"))


def sha256_file(path: pathlib.Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write_json(path: pathlib.Path, payload: Any) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as temporary:
        temporary.write(encoded); temporary_path = pathlib.Path(temporary.name)
    os.replace(temporary_path, path)


def build_integrity() -> dict[str, Any]:
    if INTEGRITY_PATH.exists(): raise RuntimeError("v8_post_run_integrity_already_exists")
    artifacts = []
    for relative in ARTIFACT_PATHS:
        path = ROOT / relative
        if not path.is_file(): raise RuntimeError(f"v8_retained_artifact_missing:{relative}")
        artifacts.append({"path": relative, "sha256": sha256_file(path), "size": path.stat().st_size})
    report = json.loads((RESULTS / "eval-v8-first-formal-results.json").read_text(encoding="utf-8"))
    stability = json.loads((RESULTS / "eval-v8-first-formal-stability.json").read_text(encoding="utf-8"))
    scan = json.loads((RESULTS / "eval-v8-first-formal-api-corpus-scan.json").read_text(encoding="utf-8"))
    aborted = report.get("status") == "aborted_valid_run_attempt"; expected = (1, 0, 1, 1) if aborted else (24, 3, 24, 30)
    if report.get("evaluation") != "scc-web-demo-eval-v8-first-formal" or len(report.get("formal_case_results", [])) != expected[0]: raise RuntimeError("v8_formal_result_shape_invalid")
    rows = stability.get("rows")
    if not isinstance(rows, list) or len(rows) != expected[1] or any(len(item.get("runs", [])) != 3 for item in rows): raise RuntimeError("v8_stability_result_shape_invalid")
    if scan.get("unresolved") != 0: raise RuntimeError("v8_api_scan_not_clean")
    databases = sorted(WORKSPACE_ROOT.glob("*/runtime/data/demo.sqlite3"))
    if len(databases) != expected[2]: raise RuntimeError("v8_workspace_database_count_invalid")
    sqlite_files, totals = [], {}
    for path in databases:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try: statuses = dict(connection.execute("SELECT status, COUNT(*) FROM v2_runs GROUP BY status"))
        finally: connection.close()
        for status, count in statuses.items(): totals[status] = totals.get(status, 0) + count
        sqlite_files.append({"workspace_key": path.parents[2].name, "sha256": sha256_file(path), "size": path.stat().st_size, "run_status": statuses})
    if sum(totals.values()) != expected[3]: raise RuntimeError("v8_provider_run_count_invalid")
    return {"schema_version": "scc-evaluation-post-run-integrity-v1", "evaluation": "scc-web-demo-eval-v8-first-formal", "retained_artifacts": {"count": 7, "files": artifacts}, "fixture_workspaces": {"root": "evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal", "sqlite_count": len(databases), "run_status_totals": totals, "sqlite_files": sqlite_files}, "raw_provider_content_retained": False, "integrity_status": "retained_baseline"}
