"""Four new verdict-type controls only; execute after a new stable freeze arrives.

Requires explicit new freeze path/hash. Reuses only synthetic fixture and output
helpers from the unchanged prior probe, never its nine-control runner.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
import datetime as dt
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


def sha(path):
    return hashlib.sha256(base.long_path(path).read_bytes()).hexdigest()


def freeze_check(path, expected):
    actual = sha(path)
    base.require(actual == expected, "explicit_freeze_digest_mismatch")
    document = json.loads(base.long_path(path).read_text(encoding="utf-8"))
    entries = document["source_hashes"]
    checks = {name: {"expected": digest, "actual": sha(ROOT / name)}
              for name, digest in entries.items()}
    base.require(bool(checks) and all(v["expected"] == v["actual"] for v in checks.values()), "frozen_source_mismatch")
    return {"freeze_path": str(path.relative_to(ROOT)), "freeze_sha256": actual,
            "source_hashes": checks, "probe_sha256": sha(Path(__file__)),
            "prior_probe_sha256": sha(HERE / "probe_v6_claim_verdicts.py")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--freeze-sha256", required=True)
    args = parser.parse_args()
    base.require(bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}", args.run_id)), "invalid_audit_identity")
    base.require(bool(re.fullmatch(r"[a-f0-9]{64}", args.freeze_sha256)), "invalid_freeze_digest")
    freeze = (ROOT / args.freeze).resolve()
    base.require(freeze.is_relative_to(ROOT / "docs/flash-v6-independent-acceptance-evidence"), "freeze_outside_authorized_evidence_root")
    root = HERE / "enum-probe-runs"
    base.long_path(root).mkdir(exist_ok=True)
    out = root / args.run_id
    base.long_path(out).mkdir(exist_ok=False)
    results = []
    fatal, before, after = None, None, None
    try:
        before = freeze_check(freeze, args.freeze_sha256)
        base.create_json(out / "before.json", {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(), **before})
        with ExitStack() as guard:
            for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex",
                           "socket.socket.send", "socket.socket.sendall", "socket.socket.sendto", "socket.getaddrinfo"):
                guard.enter_context(patch(target, base.blocked("socket")))
            for target in ("sqlite3.connect", "sqlite3.dbapi2.connect"):
                guard.enter_context(patch(target, base.blocked("sqlite")))
            import httpx
            for target in ("httpx.Client.send", "httpx.AsyncClient.send", "httpx.HTTPTransport.handle_request", "httpx.AsyncHTTPTransport.handle_async_request"):
                guard.enter_context(patch(target, base.blocked("http")))
            sys.path.insert(0, str(ROOT / "backend"))
            from app.engine import ContinuityEngine
            from app.provider import DeepSeekProvider, ProviderResult
            guard.enter_context(patch.object(DeepSeekProvider, "__init__", base.blocked("real_provider")))
            guard.enter_context(patch.object(DeepSeekProvider, "evaluate", base.blocked("real_provider")))

            class Stub:
                available = True
                label = "independent-verdict-type-stub"
                continuity_contract_version = "v6"
                allows_legacy_continuity_contract = False

                def __init__(self, responses):
                    self.responses = copy.deepcopy(responses)
                    self.requests = []

                def evaluate(self, request):
                    index = len(self.requests)
                    base.require(index < len(self.responses), "unexpected_extra_evaluation")
                    self.requests.append(copy.deepcopy(request))
                    return ProviderResult(copy.deepcopy(self.responses[index]), input_tokens=1, output_tokens=1)

            for label, value in [("list", []), ("dict", {}), ("null", None), ("number", 7)]:
                row = {"control": label}
                try:
                    data, valid = base.single_transition()
                    invalid = copy.deepcopy(valid)
                    invalid["claim_verdicts"][0]["verdict"] = value
                    try:
                        ContinuityEngine(Stub([])).validate(invalid, data)
                    except ValueError as error:
                        base.require(str(error).startswith("claim_verdicts_"), "unrelated_direct_rejection")
                        row["direct_rejection"] = str(error)
                    else:
                        raise AssertionError("nonstring_verdict_accepted")
                    repaired_stub = Stub([invalid, valid])
                    repaired = ContinuityEngine(repaired_stub).execute(data)
                    row["repaired"] = {"requests": repaired_stub.requests, "responses": repaired_stub.responses, "result": repaired}
                    base.require(repaired["status"] == "completed" and len(repaired_stub.requests) == 2, "type_error_not_repaired_once")
                    base.require(repaired["issues"][0]["nature"] == "state_change", "repair_changed_valid_issue_nature")
                    base.require(repaired_stub.requests[1]["contract_repair"]["rejected_issues"] == invalid["issues"], "repair_lost_first_issues")
                    failed_stub = Stub([invalid, invalid])
                    failed = ContinuityEngine(failed_stub).execute(data)
                    row["terminal"] = {"requests": failed_stub.requests, "responses": failed_stub.responses, "result": failed}
                    base.require(failed["status"] == "failed" and failed["error_code"].startswith("claim_verdicts_"), "repeated_bad_type_not_terminal_contract_failure")
                    base.require(len(failed_stub.requests) == 2, "terminal_attempt_bound_changed")
                    row["status"] = "pass"
                except Exception as error:
                    row.update(status="fail", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
                    if not base.long_path(out / "first-failure.json").exists():
                        base.create_json(out / "first-failure.json", row)
                results.append(row)
                base.create_json(out / (label + ".json"), row)
        after = freeze_check(freeze, args.freeze_sha256)
        base.create_json(out / "after.json", after)
    except Exception as error:
        fatal = {"error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()}
        if not base.long_path(out / "first-failure.json").exists():
            base.create_json(out / "first-failure.json", fatal)
    passed = (fatal is None and before == after and len(results) == 4 and
              all(r["status"] == "pass" for r in results) and not any(base.COUNTERS.values()))
    summary = {"status": "pass" if passed else "fail", "controls": [{"control": r["control"], "status": r["status"]} for r in results],
               "fatal": fatal, "frozen_sources_stable": before is not None and before == after,
               "blocked_boundary_attempts": base.COUNTERS, "scope": "new verdict value types through validate, one repair, and terminal failure only"}
    base.create_json(out / "results.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
