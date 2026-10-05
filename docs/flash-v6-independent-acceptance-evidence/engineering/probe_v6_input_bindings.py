"""Incremental in-memory input checks using prep-v6-02 case 25 JSON only.

No API replay or DB connection. Execute once after stable runner handoff.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import sys
import traceback
from unittest.mock import patch

sys.dont_write_bytecode = True
import probe_v6_claim_verdicts as base

ROOT, HERE = base.ROOT, base.HERE


def read(path):
    return json.loads(base.long_path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(base.long_path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-inputs-sha256", required=True)
    args = parser.parse_args()
    base.require(bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}", args.run_id)), "invalid_audit_identity")
    base.require(bool(re.fullmatch(r"[a-f0-9]{64}", args.expected_inputs_sha256)), "invalid_expected_digest")
    outputs = HERE / "input-probe-runs"
    base.long_path(outputs).mkdir(exist_ok=True)
    out = outputs / args.run_id
    base.long_path(out).mkdir(exist_ok=False)
    folder = ROOT / "evaluation/current_flash_v6"
    capture = folder / "runs/prep-v6-02/cases/25"
    files = {"inputs": folder / "inputs.py", "build_cases": folder / "build_cases.py",
             "v5_inputs": ROOT / "evaluation/current_flash_v5/inputs.py",
             "v5_journal": ROOT / "evaluation/current_flash_v5/journal.py",
             "case_document": folder / "cases-v2.json", "case_start": capture / "case-start.json",
             "request": capture / "requests/01.json", "binding": capture / "runtime-binding.json",
             "matrix": ROOT / "docs/flash-v6-independent-acceptance-evidence/semantics/control-matrix.json",
             "adaptation": folder / "INPUT-ADAPTATION.md", "probe": Path(__file__)}
    before, after, fatal, results = None, None, None, []
    try:
        before = {name: sha(path) for name, path in files.items()}
        base.create_json(out / "before.json", {"sha256": before, "capture": "prep-v6-02/cases/25"})
        base.require(before["inputs"] == args.expected_inputs_sha256, "inputs_changed_since_authorized_handoff")
        with ExitStack() as guard:
            for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex",
                           "socket.socket.send", "socket.socket.sendall", "socket.socket.sendto", "socket.getaddrinfo"):
                guard.enter_context(patch(target, base.blocked("socket")))
            for target in ("sqlite3.connect", "sqlite3.dbapi2.connect"):
                guard.enter_context(patch(target, base.blocked("sqlite")))
            import httpx
            for target in ("httpx.Client.send", "httpx.AsyncClient.send", "httpx.HTTPTransport.handle_request", "httpx.AsyncHTTPTransport.handle_async_request"):
                guard.enter_context(patch(target, base.blocked("http")))
            sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
            from app.provider import DeepSeekProvider
            guard.enter_context(patch.object(DeepSeekProvider, "__init__", base.blocked("real_provider")))
            guard.enter_context(patch.object(DeepSeekProvider, "evaluate", base.blocked("real_provider")))
            from evaluation.current_flash_v6.inputs import InputContract
            from evaluation.current_flash_v5.journal import digest
            case = next(c for c in read(files["case_document"])["cases"] if c["ordinal"] == 25)
            start = read(files["case_start"])
            request_record = read(files["request"])
            request = request_record["business_request"]
            binding = read(files["binding"])
            base.require(start["case_id"] == case["case_id"] and digest(case) == start["case_input_sha256"], "case_not_same_capture_identity")
            base.require(digest(request) == request_record["business_request_sha256"], "capture_request_digest_mismatch")
            base.require(len(request["memory"]) >= 2, "capture_lacks_memory_for_duplicate_control")
            contract = InputContract()
            contract.bind_runtime(case["case_id"], binding)
            positive = contract(case, request)
            results.append({"control": "unchanged_captured_input", "status": "pass", "audit": positive})
            variants = {}
            p = copy.deepcopy(request); p["draft"]["id"] += "-wrong"; variants["wrong_draft_id"] = p
            p = copy.deepcopy(request); p["draft"]["revision"] += 1; variants["wrong_draft_revision"] = p
            p = copy.deepcopy(request); p["memory"] = []; variants["empty_memory"] = p
            p = copy.deepcopy(request); p["memory"][-1] = copy.deepcopy(p["memory"][0]); variants["duplicate_memory_same_count"] = p
            for name, candidate in variants.items():
                row = {"control": name, "request_sha256": digest(candidate)}
                try:
                    try:
                        contract(case, candidate)
                    except RuntimeError as error:
                        expected = ("control_draft_id_or_revision_database_binding" if name.startswith("wrong_draft")
                                    else "control_selected_memory_set_drift")
                        base.require(str(error) == "input_contract:" + case["case_id"] + ":" + expected,
                                     "mutation_rejected_for_unrelated_reason:" + str(error))
                        row.update(status="pass", rejection=str(error))
                    else:
                        raise AssertionError("input_mutation_not_rejected")
                except Exception as error:
                    row.update(status="fail", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
                    if not base.long_path(out / "first-failure.json").exists():
                        base.create_json(out / "first-failure.json", row)
                results.append(row)
                base.create_json(out / (name + ".json"), row)
        after = {name: sha(path) for name, path in files.items()}
        base.create_json(out / "after.json", {"sha256": after})
    except Exception as error:
        fatal = {"error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()}
        if not base.long_path(out / "first-failure.json").exists():
            base.create_json(out / "first-failure.json", fatal)
    passed = fatal is None and before == after and len(results) == 5 and all(r["status"] == "pass" for r in results) and not any(base.COUNTERS.values())
    summary = {"status": "pass" if passed else "fail", "controls": results, "fatal": fatal,
               "sources_and_capture_stable": before is not None and before == after,
               "blocked_boundary_attempts": base.COUNTERS, "api_cases_replayed": 0}
    base.create_json(out / "results.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "controls"}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
