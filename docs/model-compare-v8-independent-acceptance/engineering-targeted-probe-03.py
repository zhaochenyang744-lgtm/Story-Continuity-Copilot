"""Independent, bounded V8 guard/scoring probes; no real I/O services."""
import builtins
import hashlib
import importlib.util
import json
import pathlib
import socket
import sqlite3
import sys
from contextlib import ExitStack
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
OUTPUT = HERE / "engineering-targeted-probe-03.json"
if OUTPUT.exists():
    raise FileExistsError("independent_probe_identity_already_exists")
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
FILES = ["harness.py", "provider.py", "journal.py", "score.py", "freeze.py", "live_guard.py"]
def hashfile(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def hashes():
    return {name: hashfile(ROOT / "evaluation/model_compare_v8" / name) for name in FILES}
before = hashes()
blocked = {"network": 0, "sqlite": 0, "guard_product_import": 0, "guard_env": 0}
def deny(kind):
    def fail(*args, **kwargs):
        blocked[kind] += 1
        raise AssertionError("forbidden_" + kind)
    return fail
rows = []
def check(name, function):
    try:
        detail = function()
        rows.append({"name": name, "pass": True, "detail": detail})
    except Exception as error:
        rows.append({"name": name, "pass": False, "error_type": type(error).__name__, "error": str(error)})

with ExitStack() as protections:
    protections.enter_context(patch("socket.socket.connect", deny("network")))
    protections.enter_context(patch("socket.socket.connect_ex", deny("network")))
    protections.enter_context(patch("socket.create_connection", deny("network")))
    protections.enter_context(patch("sqlite3.connect", deny("sqlite")))
    import httpx
    protections.enter_context(patch("httpx.HTTPTransport.handle_request", deny("network")))
    protections.enter_context(patch("httpx.Client.send", deny("network")))
    spec = importlib.util.spec_from_file_location("independent_v8_guard", ROOT / "evaluation/model_compare_v8/live_guard.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    original_import = builtins.__import__
    def guard_import(name, *args, **kwargs):
        if name == "app" or name.startswith("app.") or name == "evaluation" or name.startswith("evaluation."):
            return deny("guard_product_import")()
        return original_import(name, *args, **kwargs)
    def rejected(mode):
        run_id = "model-compare-v8-independent-guard03"
        pin = "a" * 64
        manifest = {"source_hashes": {"backend/app/engine.py": "0" * 64}}
        if mode == "missing_closure":
            manifest["source_hashes"]["backend/app/engine.py"] = hashfile(ROOT / "backend/app/engine.py")
        def controlled_sha(path):
            if mode == "identity":
                raise AssertionError("identity_read_material_before_rejection")
            if path == guard.MANIFEST:
                return "b" * 64 if mode == "manifest" else pin
            return hashfile(path)
        expected = {"identity": "live_run_identity_already_exists", "manifest": "v8_manifest_changed",
                    "source": "frozen_dependency_drift:backend/app/engine.py", "missing_closure": "preimport_dependency_missing"}[mode]
        with ExitStack() as stack:
            stack.enter_context(patch.object(guard, "sha", controlled_sha))
            stack.enter_context(patch("builtins.__import__", guard_import))
            stack.enter_context(patch("os.environ.get", deny("guard_env")))
            stack.enter_context(patch("pathlib.Path.exists", return_value=mode == "identity"))
            stack.enter_context(patch("pathlib.Path.read_text", return_value=json.dumps(manifest)))
            try:
                guard.verify(run_id, pin)
            except (FileExistsError, RuntimeError) as error:
                assert str(error).replace("\\", "/") == expected, type(error).__name__
            else:
                raise AssertionError("guard_failed_to_reject")
        return {"rejection": expected, "product_imports": blocked["guard_product_import"], "environment_accesses": blocked["guard_env"]}
    for mode in ("identity", "manifest", "source", "missing_closure"):
        check("guard_" + mode, lambda mode=mode: rejected(mode))

    from evaluation.model_compare_v8.config import cases, request_for
    from evaluation.model_compare_v8.score import safe_score, raw_score
    case = cases()[1]
    request = request_for(case)
    malformed = {"issues": [{"evidence": [{"span_id": []}]}]}
    def combined_shape_and_length():
        result = safe_score(raw_score, case, malformed, request, "length")
        assert result["machine_result"] == "score_error", "malformed_shape_should_not_be_pass"
        assert result.get("layers", {}).get("generation"), "score_error_lost_nonstop_generation_dimension"
        return result
    check("parsed_bad_shape_plus_length_keeps_both_dimensions", combined_shape_and_length)

after = hashes()
report = {"probe": "engineering-targeted-probe-03", "script_sha256": hashfile(pathlib.Path(__file__)),
          "source_hashes_before": before, "source_hashes_after": after, "source_hashes_stable": before == after,
          "results": rows, "passed": sum(row["pass"] for row in rows), "total": len(rows),
          "external_attempts_blocked": blocked, "real_provider_calls": 0, "database_connections": 0,
          "historical_baseline_rescan": False, "full_replay_repeated": False}
with OUTPUT.open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print(json.dumps({"passed": report["passed"], "total": report["total"], "hashes_stable": report["source_hashes_stable"], "blocked": blocked}))
raise SystemExit(0 if report["passed"] == report["total"] and report["source_hashes_stable"] else 1)
