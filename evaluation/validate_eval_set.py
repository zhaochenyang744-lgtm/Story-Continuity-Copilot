"""Structural validation for the frozen, demo-only evaluation case set."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import tempfile
from collections import Counter

from fastapi.testclient import TestClient


ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import AppPaths
from app.main import create_app


CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v1.json"


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_cases(path: pathlib.Path = CASE_SET_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "scc-eval-case-set-v1" or not isinstance(payload.get("cases"), list):
        raise ValueError("invalid_case_set_schema")
    return payload


def seed_span_catalog() -> dict[str, set[tuple[int, str]]]:
    root = pathlib.Path(tempfile.mkdtemp(prefix="scc-eval-set-"))
    paths = AppPaths.from_project_root(root, protected_poc_root=root / "protected-placeholder")
    client = TestClient(create_app(paths=paths))
    response = client.post("/api/auth/register", json={"account_name": "evalvalidator", "display_name": "Eval Validator", "password": "safe-password-66"}, headers={"Idempotency-Key": "9dd2d967-0969-4e77-9e20-156611115d69"})
    response.raise_for_status()
    catalog: dict[str, set[tuple[int, str]]] = {}
    for project in response.json()["data"]["seeded_projects"]:
        chapters = client.get(f"/api/projects/{project['id']}/chapters?include=excerpt")
        chapters.raise_for_status()
        catalog[project["seed_key"]] = {(chapter["number"], span["label"]) for chapter in chapters.json()["data"]["chapters"] for span in chapter["source_spans"]}
    return catalog


def validate_case_set(payload: dict | None = None) -> dict:
    payload = payload or load_cases()
    cases = payload["cases"]
    if len(cases) != 15:
        raise ValueError("case_count_must_be_15")
    required = {"case_id", "seed_key", "target_draft", "target_claim_ordinal", "expected_class", "expected_category", "expected_severity", "expected_evidence", "rubric"}
    ids = [case.get("case_id") for case in cases]
    if len(ids) != len(set(ids)) or any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise ValueError("case_ids_must_be_unique")
    classes = Counter(case.get("expected_class") for case in cases)
    if classes != Counter({"conflict": 5, "no_conflict": 5, "insufficient_evidence": 5}):
        raise ValueError("classes_must_be_balanced")
    seeds = Counter(case.get("seed_key") for case in cases)
    if set(seeds) != {"grey_harbor", "paper_moon", "zero_garden"}:
        raise ValueError("all_three_demo_seeds_are_required")
    conflict_categories = {case["expected_category"] for case in cases if case["expected_class"] == "conflict"}
    if len(conflict_categories) < 4:
        raise ValueError("conflict_categories_must_cover_at_least_four_types")
    difficult = sum(case.get("retrieval_difficulty") == "nearby_distractor" for case in cases)
    if difficult < 3:
        raise ValueError("at_least_three_nearby_distractor_cases_required")
    catalog = seed_span_catalog()
    for case in cases:
        if not required <= set(case):
            raise ValueError(f"missing_required_case_fields:{case.get('case_id')}")
        if case["seed_key"] not in catalog or not isinstance(case["target_draft"], str) or not case["target_draft"].strip() or case["target_claim_ordinal"] < 1:
            raise ValueError(f"invalid_case_input:{case['case_id']}")
        if case["expected_class"] == "conflict" and (not isinstance(case["expected_category"], str) or not case["expected_severity"]):
            raise ValueError(f"conflict_expectation_incomplete:{case['case_id']}")
        if not case["expected_evidence"]:
            raise ValueError(f"expected_evidence_required:{case['case_id']}")
        for expected in case["expected_evidence"]:
            location = (expected.get("chapter_number"), expected.get("source_label"))
            if location not in catalog[case["seed_key"]]:
                raise ValueError(f"unresolvable_expected_evidence:{case['case_id']}:{location}")
    return {"valid": True, "case_count": len(cases), "class_counts": dict(classes), "seed_counts": dict(seeds), "canonical_sha256": canonical_sha256(payload), "nearby_distractor_cases": difficult}


if __name__ == "__main__":
    print(json.dumps(validate_case_set(), ensure_ascii=False, indent=2))
