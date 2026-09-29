"""Canonical hashing and loading for the frozen V1 evaluation case set.

The structural validator that lived here checked the set against the three demo projects
registration used to create. v1.2.0 replaced those with one isolated tutorial project and
`seeded_projects` has returned an empty list since, so the catalogue it compared against
could no longer be built and the check could not pass. It was removed rather than ported:
the sets actually in use are covered by validate_eval_set_v2, _v3 and _v4. `canonical_sha256`
and `load_cases` stay, because run_eval and recover_first_formal use them."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))



CASE_SET_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v1.json"


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_cases(path: pathlib.Path = CASE_SET_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "scc-eval-case-set-v1" or not isinstance(payload.get("cases"), list):
        raise ValueError("invalid_case_set_schema")
    return payload
