"""Direct-file V7 guard: verify local dependency bytes before product imports."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "frozen-inputs.json"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(run_id: str, manifest_sha256: str) -> dict:
    if not re.fullmatch(r"flash-v7-[a-z0-9-]{1,24}", run_id):
        raise ValueError("invalid_live_run_identity")
    if (HERE / "runs" / run_id).exists() or (HERE / "workspaces" / run_id).exists():
        raise FileExistsError("live_run_identity_already_exists")
    if sha(MANIFEST) != manifest_sha256:
        raise RuntimeError("v7_manifest_changed")
    frozen_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_hashes = frozen_manifest.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise RuntimeError("v7_manifest_source_hashes_invalid")
    for relative, expected in source_hashes.items():
        if (not isinstance(relative, str) or not isinstance(expected, str) or
                not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise RuntimeError("v7_manifest_source_hashes_invalid")
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or sha(path) != expected:
            raise RuntimeError("v7_frozen_hash_mismatch:" + relative)
    required = {"evaluation/__init__.py", "evaluation/current_flash_v5/inputs.py",
                "evaluation/current_flash_v5/journal.py", "evaluation/v2_fixture_loader.py"}
    required |= {path.relative_to(ROOT).as_posix() for path in HERE.glob("*.py")}
    required |= {path.relative_to(ROOT).as_posix() for path in (ROOT / "backend/app").rglob("*.py")}
    if not required <= set(source_hashes):
        raise RuntimeError("v7_preimport_dependency_missing:" + ",".join(sorted(required - set(source_hashes))))
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend"))
    from evaluation.current_flash_v7.freeze import verify as verify_freeze
    frozen = verify_freeze()
    return {"run_id": run_id, "verified": True, "source_files_checked": len(frozen["source_hashes"]),
            "manifest_sha256": manifest_sha256, "max_generation_post": frozen["maximum_generation_post_attempts"]}


def launch(run_id: str):
    from evaluation.current_flash_v7.run import execute
    return execute("live", run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    receipt = verify(args.run_id, args.manifest_sha256)
    print(json.dumps(receipt)) if args.verify_only else print(launch(args.run_id))
