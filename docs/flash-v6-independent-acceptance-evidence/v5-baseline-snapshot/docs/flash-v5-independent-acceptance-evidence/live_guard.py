"""Controller dependency supplement; does not alter the frozen V5 runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUPPLEMENT = HERE / "controller-dependency-freeze.json"
V5 = ROOT / "evaluation/current_flash_v5"
EXPECTED_HEAD = "7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(run_id: str, supplement_sha256: str) -> dict:
    # Reject occupied or invalid identities before reading either freeze/materials.
    if not re.fullmatch(r"flash-v5-[a-z0-9-]{1,24}", run_id):
        raise ValueError("invalid_live_run_identity")
    if (V5 / "runs" / run_id).exists() or (ROOT / "artifacts/current_flash_v5" / run_id).exists():
        raise FileExistsError("live_run_identity_already_exists")
    if sha(SUPPLEMENT) != supplement_sha256:
        raise RuntimeError("controller_dependency_manifest_changed")
    supplement = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
    if supplement.get("git_head") != EXPECTED_HEAD:
        raise RuntimeError("controller_dependency_baseline_invalid")
    head = subprocess.check_output(["git", "-c", "core.longpaths=true", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != EXPECTED_HEAD:
        raise RuntimeError("git_head_changed")
    frozen_path = V5 / "frozen-inputs.json"
    if sha(frozen_path) != supplement["v5_manifest_sha256"]:
        raise RuntimeError("v5_manifest_changed")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    files = {**frozen["source_hashes"], **supplement["additional_source_hashes"]}
    for relative, digest in files.items():
        path = ROOT / relative
        if not path.is_file() or sha(path) != digest:
            raise RuntimeError("frozen_dependency_changed:" + relative)
    return {"run_id": run_id, "git_head": head, "files_checked": len(files),
            "v5_manifest_sha256": supplement["v5_manifest_sha256"],
            "controller_manifest_sha256": supplement_sha256, "verified": True}


def launch(run_id: str):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend"))
    from evaluation.current_flash_v5.run import execute
    return execute("live", run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dependency-manifest-sha256", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    receipt = verify(args.run_id, args.dependency_manifest_sha256)
    if args.verify_only:
        print(json.dumps(receipt, ensure_ascii=False))
    else:
        print(launch(args.run_id))
