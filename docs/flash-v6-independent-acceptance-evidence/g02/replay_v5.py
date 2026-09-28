"""Six saved V5 G02 answers through the stable current validator; no live calls.

Run only after the controller announces stable code and a new frozen manifest:
  .venv\\Scripts\\python.exe -B docs/flash-v6-independent-acceptance-evidence/g02/replay_v5.py --run-id stable-01 --freeze-manifest <new manifest>
The manifest must bind the current engine/provider/brief_citations/v2_database.
Old V5 evidence and old result directories are never written.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import http.client
import importlib.util
import json
import pathlib
import re
import socket
import sqlite3
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LIVE = ROOT / "evaluation/current_flash_v5/runs/flash-v5-20260927-01/cases"
V5_FREEZE = ROOT / "evaluation/current_flash_v5/frozen-inputs.json"
OLD_PROVIDER = ROOT / "docs/g02-citation-repair-evidence/independent-round1-root/v4-source-snapshot/backend/app/provider.py"
SOURCE_NAMES = ["backend/app/engine.py", "backend/app/provider.py",
                "backend/app/brief_citations.py", "backend/app/v2_database.py"]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def differences(left, right, pointer=""):
    if type(left) is not type(right):
        return [pointer or "/"]
    if isinstance(left, dict):
        result = [pointer + "/" + str(k) for k in left.keys() ^ right.keys()]
        for key in left.keys() & right.keys():
            result.extend(differences(left[key], right[key], pointer + "/" + key))
        return result
    if isinstance(left, list):
        result = [pointer + "/length"] if len(left) != len(right) else []
        for i, (a, b) in enumerate(zip(left, right)):
            result.extend(differences(a, b, pointer + "/" + str(i)))
        return result
    return [] if left == right else [pointer or "/"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--freeze-manifest", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.run_id):
        raise SystemExit("invalid_run_id")
    target = HERE / "runs" / args.run_id
    if target.exists():
        raise SystemExit("existing_run_identity_refused_before_input_read")
    manifest = (ROOT / args.freeze_manifest).resolve()
    if ROOT not in manifest.parents:
        raise SystemExit("freeze_manifest_outside_worktree")
    target.mkdir(parents=True, exist_ok=False)
    write_new(target / "start.json", {"run_id": args.run_id, "kind": "offline_saved_answer_replay",
              "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "freeze_manifest": str(manifest.relative_to(ROOT)), "provider_calls": 0})
    guarded_attempts = []
    tracked = []
    before = {}
    rows = []

    def deny(kind):
        def blocked(*_args, **_kwargs):
            guarded_attempts.append(kind)
            raise RuntimeError("forbidden_offline_operation:" + kind)
        return blocked

    def audit_guard(event, _args):
        if event in {"socket.connect", "sqlite3.connect"}:
            deny("audit:" + event)()

    sys.addaudithook(audit_guard)

    # Install before importing application modules; no Provider is constructed.
    socket.create_connection = deny("socket.create_connection")
    socket.getaddrinfo = deny("socket.getaddrinfo")
    socket.socket.connect = deny("socket.connect")
    socket.socket.connect_ex = deny("socket.connect_ex")
    socket.socket.sendto = deny("socket.sendto")
    http.client.HTTPConnection.connect = deny("http.connect")
    http.client.HTTPConnection.request = deny("http.request")
    http.client.HTTPSConnection.connect = deny("https.connect")
    sqlite3.connect = deny("sqlite3.connect")
    import _sqlite3
    _sqlite3.connect = deny("_sqlite3.connect")

    try:
        import httpx
        httpx.Client.request = deny("httpx.request")
        httpx.Client.send = deny("httpx.send")
        httpx.AsyncClient.request = deny("httpx.async_request")
        httpx.AsyncClient.send = deny("httpx.async_send")
        frozen, old_frozen = read(manifest), read(V5_FREEZE)
        for name in SOURCE_NAMES:
            if frozen.get("source_hashes", {}).get(name) != sha(ROOT / name):
                raise RuntimeError("stable_manifest_source_mismatch:" + name)
        if sha(OLD_PROVIDER) != old_frozen["source_hashes"]["backend/app/provider.py"]:
            raise RuntimeError("historical_provider_not_v5_equivalent")
        tracked = [manifest, V5_FREEZE, OLD_PROVIDER, pathlib.Path(__file__).resolve(),
                   ROOT / "backend/app/memory_contract.py"] + [ROOT / n for n in SOURCE_NAMES]
        for ordinal in range(25, 31):
            tracked.extend(LIVE / str(ordinal) / name for name in
                           ("requests/01.json", "evaluations/01.json", "final-product.json", "attempts/01-start.json"))
        before = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in tracked}
        sys.path.insert(0, str(ROOT / "backend"))
        from app.engine import WritingAnalysisEngine, CONTEXT_BRIEF_PROMPT_VERSION
        from app import provider
        provider.DeepSeekProvider.__init__ = deny("provider.constructor")
        provider.DeepSeekProvider.evaluate = deny("provider.evaluate")
        spec = importlib.util.spec_from_file_location("app._g02_v5_reference_provider", OLD_PROVIDER)
        baseline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = baseline
        spec.loader.exec_module(baseline)
        baseline.DeepSeekProvider.__init__ = deny("old_provider.constructor")
        baseline.DeepSeekProvider.evaluate = deny("old_provider.evaluate")
        validator = WritingAnalysisEngine(object())
        for ordinal in range(25, 31):
            case = LIVE / str(ordinal)
            wrapped, evaluation = read(case / "requests/01.json"), read(case / "evaluations/01.json")
            request, raw = wrapped["business_request"], evaluation["parsed_business_json"]
            old_analysis = read(case / "final-product.json")["analysis"]
            attempt = read(case / "attempts/01-start.json")
            prompt, budget = provider.request_prompt_and_budget(copy.deepcopy(request))
            old_prompt, old_budget = baseline.request_prompt_and_budget(copy.deepcopy(request))
            prompt_payload = json.loads(prompt)
            actual = validator.validate(copy.deepcopy(raw), copy.deepcopy(request))
            # Historical envelope reconstruction checks formatter bytes; it does not execute transport.
            envelope = {"model": old_frozen["model"], "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
                        "temperature": 0, "max_tokens": provider.DeepSeekProvider.max_output_tokens}
            checks = {
                "request_hash_matches_record": digest(request) == wrapped["business_request_sha256"] == evaluation["business_request_sha256"],
                "analysis_exactly_equal_v5": actual == old_analysis,
                "schema_equal_saved_request": validator._schema("context_brief") == request["output_schema"],
                "request_rebuild_unchanged": validator._request(copy.deepcopy(request)) == request,
                "prompt_exactly_equal_v5_provider": prompt == old_prompt,
                "prompt_bound_layers_unchanged": all(prompt_payload[k] == request[k] for k in ("bindings", "layers", "retrieval", "output_schema")),
                "budget_equal_and_within_same_limit": budget == old_budget and budget <= provider.MAX_INPUT_BUDGET_UNITS == baseline.MAX_INPUT_BUDGET_UNITS,
                "formatter_reconstructs_recorded_http_body_hash": digest(envelope) == attempt["http_body_sha256"],
                "g02_prompt_version_unchanged": CONTEXT_BRIEF_PROMPT_VERSION == old_frozen["g02_prompt_version"],
                "provider_limits_unchanged": all(getattr(provider.DeepSeekProvider, k) == getattr(baseline.DeepSeekProvider, k) for k in ("max_output_tokens", "timeout_seconds", "max_retries")),
            }
            rows.append({"ordinal": ordinal, "case_id": wrapped["case_id"], "checks": checks,
                         "analysis_differences": differences(old_analysis, actual),
                         "old_analysis_sha256": digest(old_analysis), "actual_analysis_sha256": digest(actual),
                         "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                         "budget_units": budget, "actual_analysis": actual})
        after = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in tracked}
        passed = before == after and not guarded_attempts and all(all(r["checks"].values()) for r in rows)
        write_new(target / "results.json", {"passed": passed, "provider_calls": 0,
                  "database_connections": 0, "guarded_attempts": guarded_attempts,
                  "source_hashes_before": before, "source_hashes_after": after, "rows": rows,
                  "scope": "Saved V5 input/answer replay and pure prompt/schema/budget checks only; no new model, retrieval, persistence or UI claim. V5 raw-summary failures, P3 and empty parent chapters remain."})
        print(json.dumps({"run_id": args.run_id, "passed": passed, "cases": len(rows), "provider_calls": 0}))
        return 0 if passed else 1
    except Exception as error:
        after = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in tracked if p.exists()}
        write_new(target / "failure.json", {"error_type": type(error).__name__, "message": str(error)[:1000],
                  "provider_calls": 0, "guarded_attempts": guarded_attempts, "completed_rows": rows,
                  "source_hashes_before": before, "source_hashes_after": after})
        print(json.dumps({"run_id": args.run_id, "passed": False, "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
