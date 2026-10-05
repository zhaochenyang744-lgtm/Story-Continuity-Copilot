"""One independent retest of the retained V8 cross-path first failure."""
import hashlib
import json
import pathlib
import socket
import sqlite3
import sys
from contextlib import ExitStack
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
OUTPUT = HERE / "engineering-generation-fix-probe-04.json"
if OUTPUT.exists():
    raise FileExistsError("independent_probe_identity_already_exists")
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
SOURCE = ROOT / "evaluation/model_compare_v8/score.py"
EXPECTED = "d3308031a9ed850706bbd802058fb6c72e3eb136a3ede5bbaa40b618bc0ad01d"
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
before = sha(SOURCE)
assert before == EXPECTED, "source_not_stable_handoff"
blocked = {"network": 0, "sqlite": 0}
def deny(kind):
    def blocked_call(*args, **kwargs):
        blocked[kind] += 1
        raise AssertionError("forbidden_" + kind)
    return blocked_call
result = None
error = None
with ExitStack() as stack:
    stack.enter_context(patch("socket.socket.connect", deny("network")))
    stack.enter_context(patch("socket.socket.connect_ex", deny("network")))
    stack.enter_context(patch("socket.create_connection", deny("network")))
    stack.enter_context(patch("sqlite3.connect", deny("sqlite")))
    import httpx
    stack.enter_context(patch("httpx.HTTPTransport.handle_request", deny("network")))
    stack.enter_context(patch("httpx.Client.send", deny("network")))
    from evaluation.model_compare_v8.config import cases, request_for
    from evaluation.model_compare_v8.score import safe_score, raw_score
    try:
        case = cases()[1]
        malformed = {"issues": [{"evidence": [{"span_id": []}]}]}
        result = safe_score(raw_score, case, malformed, request_for(case), "length")
        assert result["machine_result"] == "score_error"
        assert result["layers"]["scoring"] == ["TypeError"]
        assert result["layers"]["generation"] == ["generation:finish_reason_length"]
        assert result["complete_answer"] is False
    except Exception as failure:
        error = {"type": type(failure).__name__, "message": str(failure)}
after = sha(SOURCE)
report = {"probe": "engineering-generation-fix-probe-04", "passed": error is None and before == after,
          "source_sha256_before": before, "source_sha256_after": after,
          "script_sha256": sha(pathlib.Path(__file__)), "score": result, "error": error,
          "external_attempts_blocked": blocked, "real_provider_calls": 0, "database_connections": 0,
          "first_failure_preserved": "engineering-targeted-probe-03.json",
          "prior_guard_controls_not_repeated": True, "full_replay_not_repeated": True}
with OUTPUT.open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print(json.dumps({"passed": report["passed"], "source_stable": before == after, "blocked": blocked}))
raise SystemExit(0 if report["passed"] else 1)
