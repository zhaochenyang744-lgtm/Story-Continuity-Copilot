"""Fail-closed validation for immutable V7 formal inputs across both lifecycles."""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from evaluation.validate_eval_set import canonical_sha256
from evaluation.v2_fixture_loader import V7_CORPUS_PATHS, corpus_manifest_payload
from evaluation.validate_eval_set_v7_candidate import (
    validate_all as validate_candidate,
    validate_v7_semantic_review,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v7-candidate.json"
CASE_PATH = ROOT / "evaluation" / "case_sets" / "eval-set-v7.json"
CANDIDATE_MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-candidate-manifest.json"
MANIFEST_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-manifest.json"
CANDIDATE_REVIEW_PATH = ROOT / "evaluation" / "v7-candidate-semantic-review.json"
REVIEW_PATH = ROOT / "evaluation" / "v7-semantic-review.json"
CORPUS_MANIFEST_PATH = ROOT / "evaluation" / "fixtures" / "eval-v7-corpus-manifest.json"
PLAN_PATH = ROOT / "evaluation" / "manifests" / "eval-v7-first-formal-plan.json"
INTEGRITY_PATH = ROOT / "evaluation" / "manifests" / "eval-set-v7-freeze-integrity.json"
FORMAL_WORKSPACE = ROOT / "evaluation" / "fixture-workspaces" / "scc-web-demo-eval-v7-first-formal"

EXPECTED_CASE_CANONICAL_HASH = "e53eba34c29f889855c01f0c2657e4769d2f19e458cf5631a3f3d2ffcee0b3fd"
EXPECTED_CORPUS_CANONICAL_HASH = "04a9e6e1b4c847c12433d42de640b8906252f3590cb5135f77d375fedda683c0"
EXPECTED_FROZEN_FILE_HASHES = {
    "evaluation/case_sets/eval-set-v7.json": "fbc29c5e5ced0cab7877ffff9f5912937d260deadccc1215b4f2a19fc6a389f9",
    "evaluation/manifests/eval-set-v7-manifest.json": "d169704f31826c1fa752a47364a609a17eaad50733e398d7d4d061c8dcc9f744",
    "evaluation/v7-semantic-review.json": "213a3e3e5dab63fbdf5bc11582c09ec5e0537b86d1c8240a1305ec1c0cf65e40",
    "evaluation/fixtures/eval-v7-corpus-manifest.json": "b78a7d78d5f36508ad04b15abbd945641c226915ce48bd442d77b83bcc6109f0",
    "evaluation/fixtures/eval-v7-indigo-cartography.json": "7ff21604332e8d9ccdb6591d560b76cb9f04f9a31ae5f5bb5d6183f7c3908bbb",
    "evaluation/fixtures/eval-v7-ember-siltworks.json": "ecfc5df446499b7c298b5205af4e8137a47293c7fa6b8d6ddb70191d2bde629c",
    "evaluation/fixtures/eval-v7-brass-migration.json": "48a07b40d4ef48da1299d445bf939eaae19e5f466243f8f24a715e6a2a7de8db",
    "evaluation/fixtures/eval-v7-orchid-signalhouse.json": "d817ca87bf7dc3316f171f78bb3bc6908659211dd7ac89df637c2f160dafc5db",
}
OUTPUT_PATHS = {
    key: ROOT / value
    for key, value in ({
        "checkpoint": "evaluation/results/eval-v7-first-formal-checkpoint.json",
        "results": "evaluation/results/eval-v7-first-formal-results.json",
        "report": "evaluation/results/eval-v7-first-formal-report.md",
        "bad_cases": "evaluation/results/eval-v7-first-formal-bad-cases.json",
        "stability": "evaluation/results/eval-v7-first-formal-stability.json",
        "run_manifest": "evaluation/results/eval-v7-first-formal-run-manifest.json",
        "api_scan": "evaluation/results/eval-v7-first-formal-api-corpus-scan.json",
        "post_run_integrity": "evaluation/results/v7-first-formal-post-run-integrity.json",
    }).items()
}


def _read(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_paths() -> dict[str, pathlib.Path]:
    return {
        "evaluation/case_sets/eval-set-v7.json": CASE_PATH,
        "evaluation/manifests/eval-set-v7-manifest.json": MANIFEST_PATH,
        "evaluation/v7-semantic-review.json": REVIEW_PATH,
        "evaluation/fixtures/eval-v7-corpus-manifest.json": CORPUS_MANIFEST_PATH,
        **{f"evaluation/fixtures/{path.name}": path for path in V7_CORPUS_PATHS.values()},
    }


def validate_formal_freeze(
    case_path: pathlib.Path = CASE_PATH,
    manifest_path: pathlib.Path = MANIFEST_PATH,
    review_path: pathlib.Path = REVIEW_PATH,
    integrity_path: pathlib.Path = INTEGRITY_PATH,
    *,
    plan_payload: dict[str, Any] | None = None,
    manifest_payload: dict[str, Any] | None = None,
    integrity_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate fixed V7 inputs before and after its one permitted formal run."""
    fixed = ((case_path, CASE_PATH), (manifest_path, MANIFEST_PATH), (review_path, REVIEW_PATH), (integrity_path, INTEGRITY_PATH))
    if any(actual.resolve() != expected.resolve() for actual, expected in fixed):
        raise ValueError("formal_v7_assets_must_use_frozen_paths")
    candidate_result = validate_candidate(plan_payload)
    if candidate_result.get("status") not in {"formal_inputs_frozen", "formal_run_completed"}:
        raise ValueError("formal_v7_accepted_candidate_no_longer_valid")
    plan = candidate_result["formal_plan"]
    post_run = plan.get("formal_run_executed") is True
    if post_run:
        if (plan.get("status") != "gate_failed" or plan.get("formal_inputs_frozen") is not True
                or plan.get("real_provider_authorization_received") is not True or plan.get("provider_calls") != 30):
            raise ValueError("formal_v7_plan_post_run_state_invalid")
    else:
        if (plan.get("status") not in {"awaiting_real_provider_authorization", "approved_for_formal_run"} or plan.get("formal_inputs_frozen") is not True
                or plan.get("formal_run_executed") is not False or plan.get("provider_calls") != 0):
            raise ValueError("formal_v7_plan_not_pre_run")
        if any(path.exists() for path in OUTPUT_PATHS.values()) or FORMAL_WORKSPACE.exists():
            raise ValueError("formal_v7_pre_run_outputs_or_workspace_present")

    if CANDIDATE_CASE_PATH.read_bytes() != CASE_PATH.read_bytes():
        raise ValueError("formal_v7_case_set_not_byte_identical_to_candidate")
    candidate, case_set = _read(CANDIDATE_CASE_PATH), _read(CASE_PATH)
    if candidate != case_set or canonical_sha256(case_set) != EXPECTED_CASE_CANONICAL_HASH:
        raise ValueError("formal_v7_case_set_hash_invalid")
    if CANDIDATE_REVIEW_PATH.read_bytes() != REVIEW_PATH.read_bytes():
        raise ValueError("formal_v7_semantic_review_not_byte_identical_to_candidate")
    review = _read(REVIEW_PATH)
    review_result = validate_v7_semantic_review(candidate, review)
    if review_result["entry_count"] != 24:
        raise ValueError("formal_v7_semantic_review_coverage_invalid")

    candidate_manifest, manifest = _read(CANDIDATE_MANIFEST_PATH), (manifest_payload or _read(MANIFEST_PATH))
    expected_case_set = {
        "path": "evaluation/case_sets/eval-set-v7.json",
        "canonical_sha256": EXPECTED_CASE_CANONICAL_HASH,
        "case_count": 24,
        "split": {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8},
        "per_corpus_split": {"conflict": 2, "no_conflict": 2, "insufficient_evidence": 2},
    }
    expected_approval = {
        "controller_candidate_gate_passed": True,
        "formal_inputs_frozen": True,
        "real_provider_authorization_received": False,
        "approval_scope": "evaluation_input_freeze_only",
        "accepted_case_canonical_sha256": EXPECTED_CASE_CANONICAL_HASH,
        "accepted_corpus_canonical_sha256": EXPECTED_CORPUS_CANONICAL_HASH,
    }
    expected_boundaries = {**candidate_manifest["boundaries"], "controller_candidate_gate_passed": True, "formal_inputs_frozen": True}
    if (manifest.get("manifest_version") != "scc-eval-manifest-v7" or manifest.get("status") != "approved_for_formal_run"
            or manifest.get("case_set") != expected_case_set or manifest.get("runtime_mode") != "evaluation_fixture"
            or manifest.get("formal_run_plan") != {"path": "evaluation/manifests/eval-v7-first-formal-plan.json", "status": "awaiting_real_provider_authorization"}
            or manifest.get("approval") != expected_approval or manifest.get("boundaries") != expected_boundaries
            or manifest.get("formal_run_executed") is not False or manifest.get("provider_calls") != 0):
        raise ValueError("formal_v7_manifest_approval_or_execution_boundary_invalid")
    for field in ("required_thresholds", "scoring", "stability_protocol", "fixture_corpus"):
        if manifest.get(field) != candidate_manifest.get(field):
            raise ValueError("formal_v7_manifest_rules_differ_from_accepted_candidate")

    corpus = _read(CORPUS_MANIFEST_PATH)
    if corpus != corpus_manifest_payload(V7_CORPUS_PATHS) or corpus.get("canonical_sha256") != EXPECTED_CORPUS_CANONICAL_HASH:
        raise ValueError("formal_v7_corpus_manifest_invalid")
    integrity = integrity_payload or _read(INTEGRITY_PATH)
    if (integrity.get("schema_version") != "scc-eval-v7-freeze-integrity-v1" or integrity.get("status") != "frozen_formal_inputs"
            or integrity.get("controller_candidate_gate_passed") is not True or integrity.get("formal_inputs_frozen") is not True
            or integrity.get("real_provider_authorization_received") is not False or integrity.get("formal_run_executed") is not False
            or integrity.get("provider_calls") != 0 or integrity.get("case_canonical_sha256") != EXPECTED_CASE_CANONICAL_HASH
            or integrity.get("corpus_canonical_sha256") != EXPECTED_CORPUS_CANONICAL_HASH):
        raise ValueError("formal_v7_freeze_integrity_schema_invalid")
    frozen_paths = _frozen_paths()
    if (integrity.get("frozen_files") != EXPECTED_FROZEN_FILE_HASHES or set(frozen_paths) != set(EXPECTED_FROZEN_FILE_HASHES)
            or any(_sha(path) != EXPECTED_FROZEN_FILE_HASHES[key] for key, path in frozen_paths.items())):
        raise ValueError("formal_v7_freeze_integrity_hash_mismatch")
    formal_case_sets = sorted(path.name for path in CASE_PATH.parent.glob("eval-set-v7*.json"))
    if formal_case_sets != ["eval-set-v7-candidate.json", "eval-set-v7.json"]:
        raise ValueError("formal_v7_case_path_not_unique")
    if post_run:
        from evaluation.validate_v7_first_formal_results import validate as validate_post_run
        post = validate_post_run()
        expected_result_paths = {path.resolve() for path in OUTPUT_PATHS.values()}
        actual_result_paths = {path.resolve() for path in (ROOT / "evaluation" / "results").glob("eval-v7-first-formal-*")}
        actual_result_paths.add((ROOT / "evaluation" / "results" / "v7-first-formal-post-run-integrity.json").resolve())
        if actual_result_paths != expected_result_paths:
            raise ValueError("formal_v7_post_run_result_paths_not_unique")
        return {
            "valid": True,
            "status": "formal_run_completed",
            "lifecycle": "post_run",
            "formal_result_status": post["status"],
            "case_canonical_sha256": EXPECTED_CASE_CANONICAL_HASH,
            "corpus_canonical_sha256": EXPECTED_CORPUS_CANONICAL_HASH,
            "semantic_review_entries": 24,
            "frozen_file_count": len(frozen_paths),
            "case_set_byte_identical_to_candidate": True,
            "semantic_review_byte_identical_to_candidate": True,
            "controller_candidate_gate_passed": True,
            "formal_inputs_frozen": True,
            "real_provider_authorization_received": True,
            "formal_run_executed": True,
            "provider_calls": 30,
            "formal_result_count": len(OUTPUT_PATHS),
            "formal_workspace_count": 24,
        }
    return {
        "valid": True,
        "status": plan["status"],
        "case_canonical_sha256": EXPECTED_CASE_CANONICAL_HASH,
        "corpus_canonical_sha256": EXPECTED_CORPUS_CANONICAL_HASH,
        "semantic_review_entries": 24,
        "frozen_file_count": len(frozen_paths),
        "case_set_byte_identical_to_candidate": True,
        "semantic_review_byte_identical_to_candidate": True,
        "controller_candidate_gate_passed": True,
        "formal_inputs_frozen": True,
        "real_provider_authorization_received": plan["real_provider_authorization_received"],
        "formal_run_executed": False,
        "provider_calls": 0,
        "formal_result_count": 0,
        "formal_workspace_count": 0,
        "lifecycle": "pre_run",
    }


if __name__ == "__main__":
    print(json.dumps(validate_formal_freeze(), ensure_ascii=False, indent=2))
