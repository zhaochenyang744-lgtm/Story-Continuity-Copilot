"""Read-only Stage 6.6 SQLite scan with a narrow seed-boundary declaration allowlist."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "runtime" / "data" / "demo.sqlite3"
OUTPUT = ROOT / "evaluation" / "results" / "stage66-demo-sqlite-scan.json"
PATTERNS = {"private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "api_key_value": re.compile(r"(?i)(?:sk-|api[_-]?key\s*[:=]\s*[\"']?)[A-Za-z0-9_-]{16,}"), "authorization_value": re.compile(r"(?i)authorization\s*[:=]\s*[\"']?bearer\s+(?!\{|\$)[A-Za-z0-9._-]{12,}"), "raw_provider_body": re.compile(r"(?i)raw_provider_body"), "chain_of_thought": re.compile(r"(?i)reasoning_content|chain_of_thought"), "absolute_path": re.compile(r"[A-Za-z]:\\"), "protected_content": re.compile(r"(?i)story-continuity-poc|held-out|golden")}


def quote(value: str) -> str: return '"' + value.replace('"', '""') + '"'


def main() -> None:
    categories = {name: 0 for name in PATTERNS}; allowlisted = {"seed_boundary_declaration": 0}; table_count = text_cells = unresolved = 0
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]; table_count = len(tables)
        for table in tables:
            columns = connection.execute(f"PRAGMA table_info({quote(table)})").fetchall()
            for _, column, data_type, *_ in columns:
                if "TEXT" not in (data_type or "").upper(): continue
                for (value,) in connection.execute(f"SELECT {quote(column)} FROM {quote(table)} WHERE {quote(column)} IS NOT NULL"):
                    if not isinstance(value, str): continue
                    text_cells += 1
                    for name, pattern in PATTERNS.items():
                        if not pattern.search(value): continue
                        if name == "protected_content" and table == "seed_metadata" and column == "value":
                            allowlisted["seed_boundary_declaration"] += 1
                        else:
                            categories[name] += 1; unresolved += 1
    finally:
        connection.close()
    result = {"scanned_read_only": True, "table_count": table_count, "text_cell_count": text_cells, "categories": categories, "allowlisted": allowlisted, "unresolved": unresolved}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True); OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"); print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
