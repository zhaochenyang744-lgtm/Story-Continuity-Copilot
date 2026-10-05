"""Read-only sensitive-data scan for the retained V7 formal result bundle."""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from typing import Any, Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results"
WORKSPACES = ROOT / "evaluation" / "fixture-workspaces" / "scc-web-demo-eval-v7-first-formal"
RESULT_NAMES = (
    "eval-v7-first-formal-checkpoint.json",
    "eval-v7-first-formal-results.json",
    "eval-v7-first-formal-report.md",
    "eval-v7-first-formal-bad-cases.json",
    "eval-v7-first-formal-stability.json",
    "eval-v7-first-formal-run-manifest.json",
    "eval-v7-first-formal-api-corpus-scan.json",
    "v7-first-formal-post-run-integrity.json",
)
PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
)
SENSITIVE_KEYS = {
    "prompt", "prompt_body", "raw_provider_body", "provider_body", "raw_body",
    "reasoning_content", "chain_of_thought", "authorization", "api_key", "api_key_value",
}


def _is_nonzero(value: Any) -> bool:
    return value not in (None, False, 0, "", [], {})


def scan(
    *,
    result_paths: Iterable[pathlib.Path] | None = None,
    database_paths: Iterable[pathlib.Path] | None = None,
) -> dict[str, Any]:
    """Count retained text and sensitive hits without returning any stored text."""
    fixed_results = result_paths is None
    paths = tuple(result_paths or (RESULTS / name for name in RESULT_NAMES))
    if fixed_results and len(paths) != 8:
        raise ValueError("v7_retained_result_set_invalid")
    if any(not path.is_file() for path in paths):
        raise ValueError("v7_retained_result_missing")
    fixed_databases = database_paths is None
    databases = tuple(database_paths or sorted(WORKSPACES.glob("*/runtime/data/demo.sqlite3")))
    if fixed_databases and len(databases) != 24:
        raise ValueError("v7_retained_database_count_invalid")
    if any(not path.is_file() for path in databases):
        raise ValueError("v7_retained_database_missing")

    counters = {"result_text_values": 0, "retained_sqlite_text_cells": 0, "secret_value_hits": 0, "nonzero_sensitive_fields": 0}

    def inspect_text(value: str, *, database: bool, key: str = "") -> None:
        counters["retained_sqlite_text_cells" if database else "result_text_values"] += 1
        counters["secret_value_hits"] += sum(bool(pattern.search(value)) for pattern in PATTERNS)
        if key.casefold() in SENSITIVE_KEYS and _is_nonzero(value):
            counters["nonzero_sensitive_fields"] += 1

    def walk(value: Any, key: str = "") -> None:
        if key.casefold() in SENSITIVE_KEYS and _is_nonzero(value):
            counters["nonzero_sensitive_fields"] += 1
        if isinstance(value, str):
            # The key check above handles JSON values; avoid double counting it.
            counters["result_text_values"] += 1
            counters["secret_value_hits"] += sum(bool(pattern.search(value)) for pattern in PATTERNS)
        elif isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)

    for path in paths:
        content = path.read_text(encoding="utf-8")
        walk(json.loads(content) if path.suffix == ".json" else content)

    for database in databases:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        try:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                quoted_table = '"' + table.replace('"', '""') + '"'
                columns = [(str(row[1]), str(row[2]).upper()) for row in connection.execute(f"PRAGMA table_info({quoted_table})")]
                text_columns = [name for name, kind in columns if kind in {"", "TEXT", "VARCHAR", "CHAR", "CLOB"}]
                if not text_columns:
                    continue
                quoted_columns = ",".join('"' + column.replace('"', '""') + '"' for column in text_columns)
                for row in connection.execute(f"SELECT {quoted_columns} FROM {quoted_table}"):
                    for column, value in zip(text_columns, row):
                        if isinstance(value, str):
                            inspect_text(value, database=True, key=column)
        finally:
            connection.close()

    clean = counters["secret_value_hits"] == 0 and counters["nonzero_sensitive_fields"] == 0
    return {"result_files": len(paths), "retained_sqlite_count": len(databases), **counters, "clean": clean}


if __name__ == "__main__":
    result = scan()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["clean"] else 1)
