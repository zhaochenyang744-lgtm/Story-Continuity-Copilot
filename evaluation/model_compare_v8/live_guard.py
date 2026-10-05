"""Direct-file, standard-library-only verification before importing product code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "frozen-inputs.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(run_id, manifest_sha256):
    if not re.fullmatch(r"model-compare-v8-[a-z0-9-]{1,24}", run_id):
        raise ValueError("invalid_live_run_identity")
    if (HERE / "runs" / run_id).exists():
        raise FileExistsError("live_run_identity_already_exists")
    if sha(MANIFEST) != manifest_sha256:
        raise RuntimeError("v8_manifest_changed")
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    hashes = frozen.get("source_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise RuntimeError("manifest_hashes_invalid")
    for relative, expected in hashes.items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or sha(path) != expected:
            raise RuntimeError("frozen_dependency_drift:" + relative)
    required = {"evaluation/__init__.py", "evaluation/current_flash_v7/score.py", "evaluation/current_flash_v7/build_cases.py"}
    required |= {p.relative_to(ROOT).as_posix() for p in HERE.glob("*.py")}
    required |= {p.relative_to(ROOT).as_posix() for p in (ROOT / "backend/app").rglob("*.py")}
    # Do not run even a package initializer missing from the pinned closure.
    for relative in tuple(required):
        for parent in (ROOT / relative).parents:
            if parent == ROOT:
                break
            initializer = parent / "__init__.py"
            if initializer.is_file():
                required.add(initializer.relative_to(ROOT).as_posix())
    if not required <= set(hashes):
        raise RuntimeError("preimport_dependency_missing")
    runtime = frozen.get("runtime", {}).get("files")
    if not isinstance(runtime, dict) or str(pathlib.Path(sys.executable).resolve()) not in runtime:
        raise RuntimeError("runtime_pins_missing")
    for name, expected in runtime.items():
        path = pathlib.Path(name)
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError("installed_runtime_drift")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend"))
    from evaluation.model_compare_v8.freeze import verify as verify_freeze
    verified = verify_freeze()
    return {"verified": True, "run_id": run_id, "manifest_sha256": manifest_sha256,
            "source_files": len(verified["source_hashes"]), "runtime_files": len(runtime)}


def launch(run_id):
    key = os.environ.get("CONTINUITY_API_KEY")
    if not key:
        raise RuntimeError("CONTINUITY_API_KEY_environment_missing")
    from evaluation.model_compare_v8.harness import execute
    return execute(run_id, key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    receipt = verify(args.run_id, args.manifest_sha256)
    print(json.dumps(receipt))
    if not args.verify_only:
        print(launch(args.run_id))
