"""Three new V6 guard negative controls; no product import or live launch.

Identity and drift are simulated in memory. No frozen source is modified.
Execute only against the handed-off manifest SHA; existing output is retained.
"""
from __future__ import annotations

import argparse
import builtins
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import traceback
from unittest.mock import patch

sys.dont_write_bytecode = True
import probe_v6_claim_verdicts as base

ROOT, HERE = base.ROOT, base.HERE
MANIFEST = ROOT / "evaluation/current_flash_v6/frozen-inputs.json"
GUARD = ROOT / "evaluation/current_flash_v6/live_guard.py"


def sha(path):
    return hashlib.sha256(base.long_path(path).read_bytes()).hexdigest()


def audit(expected):
    base.require(sha(MANIFEST) == expected, "handed_off_manifest_mismatch")
    manifest = json.loads(base.long_path(MANIFEST).read_text(encoding="utf-8"))
    hashes = {relative: sha(ROOT / relative) for relative in manifest["source_hashes"]}
    base.require(hashes == manifest["source_hashes"], "handed_off_sources_changed")
    return {"manifest_sha256": expected, "source_hashes": hashes,
            "independent_probe_sha256": sha(Path(__file__)), "guard_sha256": sha(GUARD)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    base.require(bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}", args.run_id)), "invalid_audit_identity")
    base.require(bool(re.fullmatch(r"[a-f0-9]{64}", args.manifest_sha256)), "invalid_manifest_digest")
    output_root = HERE / "guard-probe-runs"
    base.long_path(output_root).mkdir(exist_ok=True)
    out = output_root / args.run_id
    base.long_path(out).mkdir(exist_ok=False)
    before, after, fatal, results = None, None, None, []
    try:
        before = audit(args.manifest_sha256)
        base.create_json(out / "before.json", before)
        spec = importlib.util.spec_from_file_location("independent_v6_live_guard", GUARD)
        guard_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard_module)  # This module must be standard-library-only.
        original_import = builtins.__import__
        original_exists = Path.exists
        original_sha = guard_module.sha
        probe_identity = "flash-v6-guard-probe"
        run_path = guard_module.HERE / "runs" / probe_identity
        work_path = guard_module.ROOT / "artifacts/current_flash_v6" / probe_identity
        base.require(not run_path.exists() and not work_path.exists(), "probe_identity_already_exists_in_real_workspace")
        dependency = ROOT / "backend/app/engine.py"
        base.require("backend/app/engine.py" in before["source_hashes"], "engine_not_in_manifest")

        for label in ("occupied_identity_before_material", "manifest_digest_drift", "dependency_digest_drift_before_import"):
            counts = {"product_import": 0, "environment_read": 0, "sqlite": 0, "socket": 0, "http": 0}
            reads = []

            def denied(kind):
                def fail(*a, **kw):
                    counts[kind] += 1
                    raise AssertionError("forbidden_guard_probe_boundary:" + kind)
                return fail

            def tracked_import(name, *a, **kw):
                if name == "app" or name.startswith("app.") or name == "evaluation" or name.startswith("evaluation."):
                    counts["product_import"] += 1
                    raise AssertionError("product_loaded_before_rejection:" + name)
                return original_import(name, *a, **kw)

            def altered_sha(path):
                path = Path(path)
                reads.append(str(path.relative_to(ROOT)))
                if label == "occupied_identity_before_material":
                    raise AssertionError("occupied_identity_read_material")
                if label == "manifest_digest_drift" and path == guard_module.MANIFEST:
                    return "0" * 64
                if label == "dependency_digest_drift_before_import" and path == dependency:
                    return "0" * 64
                return original_sha(path)

            def exists(path):
                if label == "occupied_identity_before_material" and path == work_path:
                    return True
                return original_exists(path)

            row = {"control": label}
            try:
                with ExitStack() as stack:
                    import httpx
                    import sqlite3
                    import socket
                    stack.enter_context(patch("builtins.__import__", tracked_import))
                    stack.enter_context(patch("os.getenv", denied("environment_read")))
                    stack.enter_context(patch.object(os.environ, "get", denied("environment_read")))
                    for target in ("sqlite3.connect", "sqlite3.dbapi2.connect"):
                        stack.enter_context(patch(target, denied("sqlite")))
                    for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex", "socket.getaddrinfo"):
                        stack.enter_context(patch(target, denied("socket")))
                    for target in ("httpx.Client.send", "httpx.AsyncClient.send", "httpx.HTTPTransport.handle_request", "httpx.AsyncHTTPTransport.handle_async_request"):
                        stack.enter_context(patch(target, denied("http")))
                    stack.enter_context(patch.object(guard_module, "sha", altered_sha))
                    stack.enter_context(patch.object(Path, "exists", exists))
                    try:
                        guard_module.verify(probe_identity, args.manifest_sha256)
                    except (FileExistsError, RuntimeError) as error:
                        if label == "occupied_identity_before_material":
                            base.require(isinstance(error, FileExistsError) and not reads, "identity_not_rejected_first")
                        elif label == "manifest_digest_drift":
                            base.require(len(reads) == 1 and reads[0].endswith("frozen-inputs.json"), "manifest_rejection_after_dependency_reads")
                        else:
                            base.require("backend/app/engine.py" in reads, "dependency_failure_did_not_reach_mutation")
                        row.update(status="pass", rejection_type=type(error).__name__, rejection=str(error))
                    else:
                        raise AssertionError("guard_accepted_negative_control")
                base.require(not any(counts.values()), "guard_touched_forbidden_boundary")
            except Exception as error:
                row.update(status="fail", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
                if not base.long_path(out / "first-failure.json").exists():
                    base.create_json(out / "first-failure.json", row)
            row.update(material_hash_reads=reads, boundary_attempts=counts)
            results.append(row)
            base.create_json(out / (label + ".json"), row)
        after = audit(args.manifest_sha256)
        base.create_json(out / "after.json", after)
    except Exception as error:
        fatal = {"error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()}
        if not base.long_path(out / "first-failure.json").exists():
            base.create_json(out / "first-failure.json", fatal)
    passed = fatal is None and before == after and len(results) == 3 and all(r["status"] == "pass" for r in results)
    summary = {"status": "pass" if passed else "fail", "frozen_sources_stable": before is not None and before == after,
               "fatal": fatal, "controls": results, "actual_guard_launches": 0,
               "scope": "negative identity and hash drift rejection before product import, environment and external access"}
    base.create_json(out / "results.json", summary)
    print(json.dumps({"status": summary["status"], "groups": len(results), "passed": sum(r["status"] == "pass" for r in results), "fatal": fatal}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
