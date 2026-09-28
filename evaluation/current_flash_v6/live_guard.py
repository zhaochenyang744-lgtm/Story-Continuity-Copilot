"""V6 identity-first frozen dependency guard for one authorized future live run."""
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
    if not re.fullmatch(r"flash-v6-[a-z0-9-]{1,24}", run_id):
        raise ValueError("invalid_live_run_identity")
    if (HERE / "runs" / run_id).exists() or (ROOT / "artifacts/current_flash_v6" / run_id).exists():
        raise FileExistsError("live_run_identity_already_exists")
    if sha(MANIFEST) != manifest_sha256:
        raise RuntimeError("v6_manifest_changed")
    frozen_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_hashes = frozen_manifest.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise RuntimeError("v6_manifest_source_hashes_invalid")
    for relative, expected in source_hashes.items():
        if (not isinstance(relative, str) or not isinstance(expected, str) or
            not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise RuntimeError("v6_manifest_source_hashes_invalid")
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or sha(path) != expected:
            raise RuntimeError("v6_frozen_hash_mismatch:" + relative)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend"))
    from evaluation.current_flash_v6.freeze import verify as verify_freeze
    frozen = verify_freeze()
    return {"run_id": run_id, "verified": True, "source_files_checked": len(frozen["source_hashes"]),
            "manifest_sha256": manifest_sha256, "max_generation_post": frozen["maximum_generation_post_attempts"]}


def launch(run_id: str):
    from evaluation.current_flash_v6.run import execute
    return execute("live", run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    receipt = verify(args.run_id, args.manifest_sha256)
    print(json.dumps(receipt, ensure_ascii=False)) if args.verify_only else print(launch(args.run_id))
