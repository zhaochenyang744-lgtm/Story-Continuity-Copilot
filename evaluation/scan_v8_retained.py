"""Read-only sensitive-data scan for the retained V8 formal result bundle."""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from typing import Any, Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/results"
WORKSPACES = ROOT / "evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal"
RESULT_NAMES = tuple(f"eval-v8-first-formal-{name}" for name in ("checkpoint.json", "results.json", "report.md", "bad-cases.json", "stability.json", "run-manifest.json", "api-corpus-scan.json")) + ("v8-first-formal-post-run-integrity.json",)
PATTERNS = (re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}"), re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.I), re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"))
SENSITIVE_KEYS = {"prompt", "prompt_body", "raw_provider_body", "provider_body", "raw_body", "reasoning_content", "chain_of_thought", "authorization", "api_key", "api_key_value"}


def _nonzero(value: Any) -> bool: return value not in (None, False, 0, "", [], {})


def scan(*, result_paths: Iterable[pathlib.Path] | None = None, database_paths: Iterable[pathlib.Path] | None = None) -> dict[str, Any]:
    """Count text and sensitive hits without returning retained text values."""
    fixed_results = result_paths is None; paths = tuple(result_paths or (RESULTS / name for name in RESULT_NAMES))
    if (fixed_results and len(paths) != 8) or any(not path.is_file() for path in paths): raise ValueError("v8_retained_result_set_invalid")
    fixed_databases = database_paths is None; databases = tuple(database_paths or sorted(WORKSPACES.glob("*/runtime/data/demo.sqlite3")))
    if (fixed_databases and len(databases) != 24) or any(not path.is_file() for path in databases): raise ValueError("v8_retained_database_set_invalid")
    counters = {"result_text_values": 0, "retained_sqlite_text_cells": 0, "secret_value_hits": 0, "nonzero_sensitive_fields": 0}
    def inspect_text(value: str, database: bool, key: str = "") -> None:
        counters["retained_sqlite_text_cells" if database else "result_text_values"] += 1
        counters["secret_value_hits"] += sum(bool(pattern.search(value)) for pattern in PATTERNS)
        if key.casefold() in SENSITIVE_KEYS and _nonzero(value): counters["nonzero_sensitive_fields"] += 1
    def walk(value: Any, key: str = "") -> None:
        if key.casefold() in SENSITIVE_KEYS and _nonzero(value): counters["nonzero_sensitive_fields"] += 1
        if isinstance(value, str):
            counters["result_text_values"] += 1; counters["secret_value_hits"] += sum(bool(pattern.search(value)) for pattern in PATTERNS)
        elif isinstance(value, dict):
            for child_key, child in value.items(): walk(child, str(child_key))
        elif isinstance(value, list):
            for child in value: walk(child, key)
    for path in paths:
        content = path.read_text(encoding="utf-8"); walk(json.loads(content) if path.suffix == ".json" else content)
    for database in databases:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        try:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'; columns = [(str(row[1]), str(row[2]).upper()) for row in connection.execute(f"PRAGMA table_info({quoted})")]
                names = [name for name, kind in columns if kind in {"", "TEXT", "VARCHAR", "CHAR", "CLOB"}]
                if names:
                    selected = ",".join('"' + name.replace('"', '""') + '"' for name in names)
                    for row in connection.execute(f"SELECT {selected} FROM {quoted}"):
                        for name, value in zip(names, row):
                            if isinstance(value, str): inspect_text(value, True, name)
        finally: connection.close()
    clean = counters["secret_value_hits"] == 0 and counters["nonzero_sensitive_fields"] == 0
    return {"result_files": len(paths), "retained_sqlite_count": len(databases), **counters, "clean": clean}


if __name__ == "__main__":
    result = scan(); print(json.dumps(result, ensure_ascii=False, indent=2)); raise SystemExit(0 if result["clean"] else 1)
