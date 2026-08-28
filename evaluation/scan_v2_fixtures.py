"""Sensitive-value scan for evaluation-only corpus files and their temporary databases."""
from __future__ import annotations

import json
import re
from typing import Any

from evaluation.v2_fixture_loader import CORPUS_PATHS, V3_CORPUS_PATHS, V4_CORPUS_PATHS, fixture_runtime


PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "api_key_value": re.compile(r"(?i)(?:api[_-]?key\s*[:=]\s*[\"']?|sk-)[A-Za-z0-9_-]{16,}"),
    "authorization_value": re.compile(r"(?i)authorization\s*[:=]\s*[\"']?bearer\s+(?!\{|\$)[A-Za-z0-9._-]{12,}"),
    "absolute_path": re.compile(r"[A-Za-z]:\\"),
    "prompt_body": re.compile(r'"prompt(?:_body)?"\s*:'),
    "raw_provider_body": re.compile(r'"(?:raw_provider_body|provider_body)"\s*:'),
    "chain_of_thought": re.compile(r'"(?:reasoning_content|chain_of_thought)"\s*:'),
}


class NoCallProvider:
    label = "fixture-scan-provider"
    model_label = "fixture-scan-model"
    available = True

    def evaluate(self, _: dict[str, Any]):
        raise AssertionError("fixture_scan_must_not_call_provider")


def _count_text(value: str, categories: dict[str, int]) -> None:
    for name, pattern in PATTERNS.items():
        categories[name] += len(pattern.findall(value))


def scan() -> dict[str, Any]:
    categories = {name: 0 for name in PATTERNS}
    source_files = 0
    corpus_sets = (CORPUS_PATHS, V3_CORPUS_PATHS, V4_CORPUS_PATHS)
    for corpus_paths in corpus_sets:
        for path in corpus_paths.values():
            source_files += 1
            _count_text(path.read_text(encoding="utf-8"), categories)
    temporary_databases = text_cells = 0
    for corpus_paths in corpus_sets:
        for corpus_key in corpus_paths:
            with fixture_runtime(corpus_key, NoCallProvider(), corpus_paths=corpus_paths) as runtime:
                with runtime.app.state.database.connection() as connection:
                    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'v2_%'")]
                    for table in tables:
                        columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
                        for _, name, data_type, *_ in columns:
                            if "TEXT" not in (data_type or "").upper():
                                continue
                            for (value,) in connection.execute(f'SELECT "{name}" FROM "{table}" WHERE "{name}" IS NOT NULL'):
                                if isinstance(value, str):
                                    text_cells += 1
                                    _count_text(value, categories)
                temporary_databases += 1
    return {"evaluation_only": True, "source_files": source_files, "temporary_databases": temporary_databases, "text_cells": text_cells, "categories": categories, "unresolved": sum(categories.values())}


if __name__ == "__main__":
    print(json.dumps(scan(), ensure_ascii=False, indent=2))
