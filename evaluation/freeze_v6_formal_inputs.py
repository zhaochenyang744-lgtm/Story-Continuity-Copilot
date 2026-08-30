"""One-time, fail-closed freeze of controller-approved V6 candidate inputs."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V6_CORPUS_PATHS, corpus_manifest_payload
from evaluation.validate_eval_set_v6_candidate import validate_all as validate_candidate


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v6-candidate.json"
FORMAL_CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v6.json"
CANDIDATE_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-candidate-manifest.json"
FORMAL_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-manifest.json"
CANDIDATE_REVIEW_PATH = ROOT / "evaluation" / "v6-candidate-semantic-review.json"
FORMAL_REVIEW_PATH = ROOT / "evaluation" / "v6-semantic-review.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v6-corpus-manifest.json"
FORMAL_PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v6-first-formal-plan.json"
INTEGRITY_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v6-freeze-integrity.json"

EXPECTED_CASE_HASH = "3b40e1a157be6e61be58025f7429c7011f30461c6b995ddb1dd9c28adf7564f0"
EXPECTED_CORPUS_HASH = "24cc03de333f2dc397748c1e419df03b782c45e07364f8e11b8497c046f0c753"


def _read(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_once(path: pathlib.Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"v6_formal_freeze_target_exists:{path.name}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> dict[str, Any]:
    result = validate_candidate()
    if result["case_set"]["canonical_sha256"] != EXPECTED_CASE_HASH or result["manifest"]["corpus_canonical_sha256"] != EXPECTED_CORPUS_HASH:
        raise RuntimeError("v6_formal_freeze_controller_accepted_hash_mismatch")
    targets = (FORMAL_CASE_PATH, FORMAL_MANIFEST_PATH, FORMAL_REVIEW_PATH, INTEGRITY_PATH)
    if any(path.exists() for path in targets):
        raise RuntimeError("v6_formal_freeze_target_exists")
    candidate_bytes = CANDIDATE_CASE_PATH.read_bytes()
    candidate = _read(CANDIDATE_CASE_PATH)
    if canonical_sha256(candidate) != EXPECTED_CASE_HASH:
        raise RuntimeError("v6_formal_freeze_candidate_canonical_hash_mismatch")
    corpus = corpus_manifest_payload(V6_CORPUS_PATHS)
    if corpus["canonical_sha256"] != EXPECTED_CORPUS_HASH or _read(CORPUS_MANIFEST_PATH) != corpus:
        raise RuntimeError("v6_formal_freeze_corpus_hash_mismatch")

    # Byte identity is intentional: the formal case set is the accepted candidate,
    # not a regenerated or semantically equivalent copy.
    FORMAL_CASE_PATH.write_bytes(candidate_bytes)
    candidate_manifest = _read(CANDIDATE_MANIFEST_PATH)
    manifest = copy.deepcopy(candidate_manifest)
    manifest.update({
        "manifest_version": "scc-eval-manifest-v6",
        "status": "approved_for_formal_run",
        "case_set": {**candidate_manifest["case_set"], "path": "evaluation/case_sets/eval-set-v6.json"},
        "approval": {
            "controller_candidate_gate_passed": True,
            "real_provider_authorization_received": False,
            "approval_scope": "evaluation_input_freeze_only",
            "accepted_case_canonical_sha256": EXPECTED_CASE_HASH,
            "accepted_corpus_canonical_sha256": EXPECTED_CORPUS_HASH,
        },
        "boundaries": {**candidate_manifest["boundaries"], "controller_candidate_gate_passed": True},
        "formal_run_executed": False,
        "provider_calls": 0,
    })
    _write_once(FORMAL_MANIFEST_PATH, manifest)

    candidate_review = _read(CANDIDATE_REVIEW_PATH)
    case_by_id = {case["case_id"]: case for case in candidate["cases"]}
    entries = []
    for entry in candidate_review["entries"]:
        case = case_by_id[entry["case_id"]]
        entries.append({
            "case_id": entry["case_id"],
            "corpus_key": case["corpus_key"],
            "core_fact_key": case["core_fact_key"],
            "decision_point": entry["decision_point"],
            "prior_archetype_reference": entry["prior_archetype_reference"],
            "why_independent": entry["why_independent"],
            "same_decision_point": False,
            "review_status": "controller_accepted_for_freeze",
        })
    review = {
        "schema_version": "scc-eval-v6-semantic-review-v1",
        "review_scope": "controller_accepted_for_freeze",
        "status": "approved_for_formal_run",
        "formal_run_executed": False,
        "provider_calls": 0,
        "controller_acceptance": {
            "accepted_case_canonical_sha256": EXPECTED_CASE_HASH,
            "accepted_corpus_canonical_sha256": EXPECTED_CORPUS_HASH,
            "accepted_case_count": 24,
            "all_same_decision_point": False,
        },
        "structural_validation_note": "总控已人工复核 24/24 语义标签与独立性，并批准仅冻结正式评测输入；本签署不代表真实 Provider 授权或正式运行。",
        "entries": entries,
    }
    _write_once(FORMAL_REVIEW_PATH, review)

    plan = _read(FORMAL_PLAN_PATH)
    if plan.get("formal_run_executed") is not False or plan.get("provider_calls") != 0 or plan.get("real_provider_authorization_received") is not False:
        raise RuntimeError("v6_formal_freeze_plan_execution_boundary_invalid")
    plan["controller_candidate_gate_passed"] = True
    plan["execution_note"] = "Controller-approved formal input freeze only. V6 formal Provider authorization is absent; no result, checkpoint, report, Bad Case, stability, run manifest, API scan, workspace, or post-run integrity artifact exists."
    FORMAL_PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    frozen_paths = {
        "evaluation/case_sets/eval-set-v6.json": FORMAL_CASE_PATH,
        "evaluation/manifests/eval-set-v6-manifest.json": FORMAL_MANIFEST_PATH,
        "evaluation/v6-semantic-review.json": FORMAL_REVIEW_PATH,
        "evaluation/fixtures/eval-v6-corpus-manifest.json": CORPUS_MANIFEST_PATH,
        **{f"evaluation/fixtures/{path.name}": path for path in V6_CORPUS_PATHS.values()},
    }
    integrity = {
        "schema_version": "scc-eval-v6-freeze-integrity-v1",
        "status": "frozen_data_assets",
        "formal_run_executed": False,
        "provider_calls": 0,
        "real_provider_authorization_received": False,
        "case_canonical_sha256": EXPECTED_CASE_HASH,
        "corpus_canonical_sha256": EXPECTED_CORPUS_HASH,
        "frozen_files": {relative: _sha(path) for relative, path in frozen_paths.items()},
    }
    _write_once(INTEGRITY_PATH, integrity)
    return {
        "case_canonical_sha256": EXPECTED_CASE_HASH,
        "corpus_canonical_sha256": EXPECTED_CORPUS_HASH,
        "frozen_file_hashes": integrity["frozen_files"],
        "formal_run_executed": False,
        "provider_calls": 0,
    }


if __name__ == "__main__":
    print(json.dumps(freeze(), ensure_ascii=False, indent=2))
