"""Scan retained V5 formal artifacts and SQLite text values without echoing them."""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results"
WORKSPACES = ROOT / "evaluation" / "fixture-workspaces" / "scc-web-demo-eval-v5-first-formal"
RESULT_NAMES = (
    "eval-v5-first-formal-checkpoint.json",
    "eval-v5-first-formal-results.json",
    "eval-v5-first-formal-report.md",
    "eval-v5-first-formal-bad-cases.json",
    "eval-v5-first-formal-stability.json",
    "eval-v5-first-formal-run-manifest.json",
    "eval-v5-first-formal-api-corpus-scan.json",
    "v5-first-formal-post-run-integrity.json",
)
PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
)
SENSITIVE_KEYS = {
    "prompt", "prompt_body", "raw_provider_body", "provider_body", "raw_body",
    "reasoning_content", "chain_of_thought", "authorization", "api_key", "api_key_value",
}


def scan() -> dict[str, Any]:
    result_paths = [RESULTS / name for name in RESULT_NAMES]
    if any(not path.is_file() for path in result_paths):
        raise ValueError("v5_retained_result_missing")
    counters = {"result_text_values": 0, "retained_sqlite_text_cells": 0, "secret_value_hits": 0, "nonzero_sensitive_fields": 0}

    def inspect_text(value: str, *, database: bool = False) -> None:
        counters["retained_sqlite_text_cells" if database else "result_text_values"] += 1
        counters["secret_value_hits"] += sum(bool(pattern.search(value)) for pattern in PATTERNS)

    def walk(value: Any, key: str = "") -> None:
        if key.casefold() in SENSITIVE_KEYS and value not in (None, False, 0, "", [], {}):
            counters["nonzero_sensitive_fields"] += 1
        if isinstance(value, str):
            inspect_text(value)
        elif isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)

    for path in result_paths:
        content = path.read_text(encoding="utf-8")
        walk(json.loads(content) if path.suffix == ".json" else content)

    databases = sorted(WORKSPACES.glob("*/runtime/data/demo.sqlite3"))
    if len(databases) != 24:
        raise ValueError("v5_retained_database_count_invalid")
    for database in databases:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        try:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                quoted_table = '"' + table.replace('"', '""') + '"'
                columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quoted_table})") if str(row[2]).upper() in {"", "TEXT", "VARCHAR", "CHAR", "CLOB"}]
                if not columns:
                    continue
                quoted_columns = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
                for row in connection.execute(f"SELECT {quoted_columns} FROM {quoted_table}"):
                    for value in row:
                        if isinstance(value, str):
                            inspect_text(value, database=True)
        finally:
            connection.close()

    clean = counters["secret_value_hits"] == 0 and counters["nonzero_sensitive_fields"] == 0
    return {"result_files": 8, "retained_sqlite_count": 24, **counters, "clean": clean}


if __name__ == "__main__":
    result = scan()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["clean"] else 1)
