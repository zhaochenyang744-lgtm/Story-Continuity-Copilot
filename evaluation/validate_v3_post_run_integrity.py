"""Strict, read-only validation for retained V3 formal-run evidence."""
from __future__ import annotations

import json
import pathlib

from evaluation.post_run_integrity import validate_retained_integrity


ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRITY_PATH = ROOT / "evaluation" / "results" / "v3-first-formal-post-run-integrity.json"


def validate(
    root: pathlib.Path = ROOT,
    integrity_path: pathlib.Path = INTEGRITY_PATH,
) -> dict:
    """Require all retained V3 result files and SQLite workspaces to be present."""
    payload = json.loads(integrity_path.read_text(encoding="utf-8"))
    if payload.get("schema_invalid_field_detail") != "raw body intentionally not retained":
        raise ValueError("v3_post_run_integrity_schema_invalid")
    return validate_retained_integrity(
        root,
        integrity_path,
        expected_evaluation="scc-web-demo-eval-v3-first-formal",
        expected_run_status_totals={"completed": 19, "failed": 2},
    )


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
