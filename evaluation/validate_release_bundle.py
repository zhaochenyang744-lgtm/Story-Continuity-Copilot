"""Validate the published evaluation bundle without requiring retained runtime SQLite."""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from evaluation.post_run_integrity import sha256_file
from evaluation.validate_eval_set_v4 import validate_formal_freeze


ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRITY_PATH = ROOT / "evaluation" / "results" / "v4-first-formal-post-run-integrity.json"
REQUIRED_DOCUMENTS = {
    "README.md",
    "docs/local-setup.md",
    "docs/demo-guide.md",
    "docs/product-decisions-and-validation.md",
    "docs/verification-and-limitations.md",
}
REQUIRED_SCREENSHOTS = {
    "artifacts/stage6-screenshots/1440-home.png",
    "artifacts/stage6-screenshots/1440-grey-harbor-run-complete.png",
    "artifacts/stage6-screenshots/1440-memory-update-review.png",
    "artifacts/stage6-screenshots/1440-reset-confirmation.png",
}
SENSITIVE_FIELD = re.compile(r"^(authorization(?:_value)?|prompt(?:_body)?|raw_provider_body|provider_body|chain_of_thought|reasoning_content)$", re.IGNORECASE)


def _load(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _reject_sensitive_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SENSITIVE_FIELD.fullmatch(str(key)):
                if child in (None, "", 0, False, []):
                    continue
                raise ValueError("release_bundle_sensitive_field_present")
            _reject_sensitive_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_sensitive_fields(child)


def validate_release_bundle(root: pathlib.Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    if root != ROOT:
        raise ValueError("release_bundle_root_must_be_repository_root")
    freeze = validate_formal_freeze()
    integrity = _load(INTEGRITY_PATH)
    if (
        integrity.get("schema_version") != "scc-evaluation-post-run-integrity-v1"
        or integrity.get("evaluation") != "scc-web-demo-eval-v4-first-formal"
        or integrity.get("integrity_status") != "retained_baseline"
        or integrity.get("raw_provider_content_retained") is not False
    ):
        raise ValueError("release_bundle_integrity_schema_invalid")
    retained = integrity.get("retained_artifacts")
    files = retained.get("files") if isinstance(retained, dict) else None
    if retained.get("count") != 7 or not isinstance(files, list) or len(files) != 7:
        raise ValueError("release_bundle_artifact_count_invalid")
    for item in files:
        path = root / item.get("path", "")
        if not path.is_file() or sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("release_bundle_artifact_hash_mismatch")
        if path.suffix.lower() == ".json":
            _reject_sensitive_fields(_load(path))
    workspaces = integrity.get("fixture_workspaces")
    items = workspaces.get("sqlite_files") if isinstance(workspaces, dict) else None
    if (
        workspaces.get("root") != "evaluation/fixture-workspaces/scc-web-demo-eval-v4-first-formal"
        or workspaces.get("sqlite_count") != 15
        or not isinstance(items, list)
        or len(items) != 15
        or len({item.get("workspace_key") for item in items}) != 15
        or workspaces.get("run_status_totals") != {"completed": 21}
    ):
        raise ValueError("release_bundle_workspace_record_invalid")
    for item in items:
        if (
            not isinstance(item.get("workspace_key"), str)
            or not re.fullmatch(r"[0-9a-f]{24}", item["workspace_key"])
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256")))
            or not isinstance(item.get("size"), int)
            or item.get("size") <= 0
            or item.get("run_status") != {"completed": 1} and item.get("run_status") != {"completed": 3}
        ):
            raise ValueError("release_bundle_workspace_record_invalid")
    _reject_sensitive_fields(integrity)
    missing = [path for path in REQUIRED_DOCUMENTS | REQUIRED_SCREENSHOTS if not (root / path).is_file()]
    if missing:
        raise ValueError("release_bundle_required_surface_missing")
    return {
        "valid": True,
        "release_bundle": "self_consistent_with_frozen_v4_record",
        "formal_result_files": 7,
        "workspace_records": 15,
        "run_status_totals": {"completed": 21},
        "freeze": freeze,
    }


if __name__ == "__main__":
    print(json.dumps(validate_release_bundle(), ensure_ascii=False, indent=2))
