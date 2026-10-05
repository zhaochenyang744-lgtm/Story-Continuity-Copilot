"""Freeze and verify the V10 held-out formal inputs; no Provider, SQLite, or result writes.

`approve` runs once after the fake-only dry run: it marks the manifest and plan
approved and records SHA-256 for every input the formal run depends on.
`validate_formal_freeze` then refuses any drift before a formal run starts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

from evaluation.build_v10_formal_assets import (AUTHORING, CASE_SET, CORPUS_MANIFEST, MANIFEST, OUTPUTS, PLAN,
                                               RUNTIME_CONTRACT, canonical)

ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRITY = ROOT / "evaluation/manifests/eval-set-v10-freeze-integrity.json"
WORKSPACE = ROOT / "evaluation/fixture-workspaces/scc-web-demo-eval-v10-first-formal"
PINNED = ("evaluation/eval_set_v10_authoring/cases.json", "evaluation/eval_set_v10_authoring/cases.sha256",
          "evaluation/case_sets/eval-set-v10.json", "evaluation/manifests/eval-set-v10-manifest.json",
          "evaluation/fixtures/eval-v10-corpus-manifest.json", "evaluation/build_v10_formal_assets.py",
          "evaluation/validate_eval_set_v10.py", "evaluation/execute_v10_first_formal.py", "evaluation/run_eval.py",
          "evaluation/v2_fixture_loader.py", "evaluation/metrics.py", "evaluation/results/fail-closed-contract.json",
          "backend/app/engine.py", "backend/app/provider.py", "backend/app/v2_database.py", "backend/app/brief_citations.py")


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pinned_paths() -> list[str]:
    corpus_files = [item["path"] for item in read(CORPUS_MANIFEST)["files"]]
    return sorted({*PINNED, *corpus_files})


def validate_inputs() -> dict:
    """Structural and hash consistency independent of approval state."""
    from evaluation.v2_fixture_loader import V10_CORPUS_PATHS, corpus_manifest_payload
    recorded = (AUTHORING / "cases.sha256").read_text(encoding="utf-8").split()[0].lower()
    manifest, cases = read(MANIFEST), read(CASE_SET)
    if sha(AUTHORING / "cases.json") != recorded or manifest["authoring"]["sha256"] != recorded or cases["authoring_source_sha256"] != recorded:
        raise RuntimeError("v10_authoring_hash_mismatch")
    if canonical(cases) != manifest["case_set"]["canonical_sha256"]:
        raise RuntimeError("v10_case_set_hash_mismatch")
    if read(CORPUS_MANIFEST) != corpus_manifest_payload(V10_CORPUS_PATHS) or manifest["fixture_corpus"]["canonical_sha256"] != read(CORPUS_MANIFEST)["canonical_sha256"]:
        raise RuntimeError("v10_corpus_hash_mismatch")
    split = manifest["case_set"]["split"]
    if len(cases["cases"]) != 36 or split != {"conflict": 12, "no_conflict": 12, "insufficient_evidence": 12}:
        raise RuntimeError("v10_case_split_invalid")
    designated = [c for c in cases["cases"] if "category_mismatch_regression" in c["challenge_tags"]]
    if len(designated) != 3 or any(c["expected_class"] != "conflict" for c in designated):
        raise RuntimeError("v10_designated_regression_invalid")
    if manifest["runtime_contract"] != RUNTIME_CONTRACT or read(PLAN)["runtime_contract"] != RUNTIME_CONTRACT:
        raise RuntimeError("v10_runtime_contract_drift")
    ids = set(manifest["stability_protocol"]["representative_case_ids"])
    if len(ids) != 3 or not ids <= {c["case_id"] for c in cases["cases"]}:
        raise RuntimeError("v10_stability_protocol_invalid")
    return {"cases": len(cases["cases"]), "designated": [c["case_id"] for c in designated]}


def output_counts() -> tuple[int, int]:
    results = sum((ROOT / path).exists() for path in [*OUTPUTS.values(), "evaluation/results/v10-first-formal-post-run-integrity.json"])
    return results, int(WORKSPACE.exists())


def approve() -> dict:
    if INTEGRITY.exists():
        raise RuntimeError("v10_already_frozen")
    validate_inputs()
    if any(output_counts()):
        raise RuntimeError("v10_formal_outputs_already_exist")
    manifest, plan = read(MANIFEST), read(PLAN)
    manifest.update({"status": "approved_for_formal_run"})
    manifest["boundaries"] = {"controller_candidate_gate_passed": True, "formal_run_executed": False, "provider_calls": 0}
    plan.update({"status": "approved_for_formal_run", "controller_candidate_gate_passed": True, "formal_inputs_frozen": True,
                 "real_provider_authorization_received": True,
                 "authorization_note": "User authorized Provider calls for this evaluation work in the conversation of 2026-09-28."})
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    integrity = {"schema_version": "scc-eval-v10-freeze-integrity-v1", "files": {p: sha(ROOT / p) for p in pinned_paths()}}
    INTEGRITY.write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"frozen_files": len(integrity["files"]), "integrity_sha256": sha(INTEGRITY)}


def validate_formal_freeze(plan_payload: dict | None = None) -> dict:
    details = validate_inputs()
    if not INTEGRITY.exists():
        raise RuntimeError("v10_not_frozen")
    frozen = read(INTEGRITY)["files"]
    drift = [path for path in pinned_paths() if frozen.get(path) != (sha(ROOT / path) if (ROOT / path).is_file() else None)]
    if drift or set(frozen) != set(pinned_paths()):
        raise RuntimeError("v10_freeze_drift:" + ",".join(drift))
    if read(MANIFEST).get("status") != "approved_for_formal_run":
        raise RuntimeError("v10_manifest_not_approved")
    results, workspaces = output_counts()
    return {"status": "frozen", "formal_result_count": results, "formal_workspace_count": workspaces, **details}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inputs", "approve", "verify"))
    command = parser.parse_args().command
    print(json.dumps(validate_inputs() if command == "inputs" else approve() if command == "approve" else validate_formal_freeze(),
                     ensure_ascii=False, indent=2))
