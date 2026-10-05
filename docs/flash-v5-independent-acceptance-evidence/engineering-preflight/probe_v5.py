"""Independent, bounded V5 probes. PREPARED ONLY until controller supplies freeze hash.

All transport is fabricated; existing prep JSON replaces database access. The
runner-loop checks deliberately patch fixture/API work and model preflight, so
their outputs are engineering controls, never model or product-quality results.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import socket
import sqlite3
import sys
import types
from contextlib import ExitStack
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST = ROOT / "evaluation/current_flash_v5/frozen-inputs.json"
PREP = ROOT / "evaluation/current_flash_v5/runs/prep-v5-03"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def expect_error(kind, function):
    try:
        function()
    except kind as exc:
        return {"type": type(exc).__name__, "message": str(exc)[:200]}
    raise AssertionError("expected exception: " + kind.__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-after-controller-release", action="store_true")
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--only", default="", help="Comma-separated targeted groups; completed controls need not be rerun")
    parser.add_argument("--dependency-manifest-sha256")
    args = parser.parse_args()
    if not args.execute_after_controller_release:
        raise SystemExit("Prepared only. Controller release and final manifest hash are required.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", args.run_id):
        raise SystemExit("invalid probe run id")
    if sha(MANIFEST) != args.manifest_sha256:
        raise SystemExit("controller manifest identity mismatch")
    frozen = read(MANIFEST)
    if not isinstance(frozen.get("source_hashes"), dict) or not frozen["source_hashes"]:
        raise SystemExit("final manifest source_hashes unavailable")
    bound_before = {name: sha(ROOT / name) for name in frozen["source_hashes"]}
    if bound_before != frozen["source_hashes"]:
        raise SystemExit("final manifest has source drift")

    output = HERE / "probe-runs" / args.run_id
    if os.name == "nt":
        output = pathlib.Path("\\\\?\\" + str(output))
    output.mkdir(parents=True, exist_ok=False)
    put(output / "frozen-hashes-before.json", bound_before)
    blocked = {"network": 0, "database": 0, "out_of_scope_write": 0}

    def forbidden(kind):
        def stop(*unused, **unused_kw):
            blocked[kind] += 1
            raise AssertionError("independent_probe_forbidden_" + kind)
        return stop

    def audit(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto"}:
            forbidden("network")()
        if event == "sqlite3.connect":
            forbidden("database")()
        if event == "open":
            path, mode, flags = values
            writing = isinstance(mode, str) and any(x in mode for x in "wax+")
            writing = writing or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if writing and isinstance(path, (str, bytes, os.PathLike)):
                resolved = pathlib.Path(os.fsdecode(path)).resolve()
                if not resolved.is_relative_to(output):
                    forbidden("out_of_scope_write")()
    sys.addaudithook(audit)

    # Overwrite the named configuration before imports. No previous value is read.
    os.environ["CONTINUITY_API_KEY"] = "offline-placeholder-never-a-credential"
    os.environ["CONTINUITY_PROVIDER"] = "deepseek"
    os.environ["CONTINUITY_MODEL"] = "deepseek-flash"
    os.environ["CONTINUITY_BASE_URL"] = "https://offline.invalid"
    os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
    sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

    with ExitStack() as guards:
        guards.enter_context(patch.object(sqlite3, "connect", forbidden("database")))
        guards.enter_context(patch.object(socket, "create_connection", forbidden("network")))
        import httpx
        guards.enter_context(patch.object(httpx.Client, "send", forbidden("network")))
        from app.provider import ProviderDispatchDenied, ProviderResult
        from evaluation.current_flash_v5 import journal as j, inputs as inp, run as r, score as score
        from evaluation.current_flash_v5 import build_cases

        cases = read(ROOT / "evaluation/current_flash_v5/cases.json")["cases"]
        comparison = copy.deepcopy(cases[0])
        g02 = copy.deepcopy(cases[24])
        request = read(PREP / "cases/01/requests/01.json")["business_request"]
        g02_request = read(PREP / "cases/25/requests/01.json")["business_request"]
        g02_binding = read(PREP / "cases/25/runtime-binding.json")
        fixture_paths = [PREP / "cases/01/requests/01.json", PREP / "cases/25/requests/01.json",
                         PREP / "cases/25/runtime-binding.json"]
        fixture_before = {str(p.relative_to(ROOT)): sha(p) for p in fixture_paths}
        rows = []
        selected = set(filter(None, args.only.split(",")))

        def check(name, callback):
            if selected and name not in selected:
                return
            try:
                details = callback()
                row = {"name": name, "passed": True, "details": details}
            except Exception as exc:
                row = {"name": name, "passed": False, "error_type": type(exc).__name__, "error": str(exc)[:500]}
            rows.append(row)
            put(output / "checks" / (name + ".json"), row)

        def new_case(name, case=None):
            owner = j.RunJournal(output / name, "independent-" + name, 108)
            return owner, owner.case(1, copy.deepcopy(case or comparison))

        def response(content='{"issues": []}', status=200, usage=None):
            envelope = {"model": "offline-fake", "choices": [{"finish_reason": "stop", "message": {
                "content": content, "reasoning_content": "DO_NOT_PERSIST_HIDDEN_SENTINEL"}}],
                "usage": usage if usage is not None else {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}
            return httpx.Response(status, json=envelope, request=httpx.Request("POST", "https://offline.invalid/chat/completions"))

        class Transport:
            def __init__(self, cj, actions, inspect=True):
                self.cj, self.actions, self.inspect = cj, list(actions), inspect
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

            def post(self, url, **kw):
                self.calls += 1
                if self.inspect:
                    snapshot = read(self.cj.root / "requests" / f"{self.cj.current_evaluation:02d}.json")
                    assert snapshot["business_request_sha256"] == canonical_sha(snapshot["business_request"])
                    assert snapshot["business_request"] == request or snapshot["business_request"].get("contract_repair")
                    assert snapshot["selected_source_bindings"]
                    start = read(self.cj.root / "attempts" / f"{self.cj.dispatch_count:02d}-start.json")
                    assert start["business_request_sha256"] == snapshot["business_request_sha256"]
                    assert start["http_body_sha256"] == canonical_sha(kw["json"])
                action = self.actions.pop(0)
                if action == "timeout":
                    raise httpx.ReadTimeout("offline injected timeout")
                return action

        def identity():
            base = output / "identity"
            run_id = "flash-v5-independent-duplicate"
            observed = []
            with patch.object(r, "RESULTS", base / "runs"), patch.object(r, "WORKSPACES", base / "workspaces"):
                for existing in (r.RESULTS / run_id, r.WORKSPACES / "flash-v5-workspace-existing"):
                    existing.mkdir(parents=True)
                for tested in (run_id, "flash-v5-workspace-existing"):
                    with patch.object(pathlib.Path, "read_text", side_effect=AssertionError("material_read_before_identity_reject")), \
                         patch.object(type(os.environ), "get", side_effect=AssertionError("environment_read_before_identity_reject")):
                        observed.append(expect_error(FileExistsError, lambda: r.execute("live", tested)))
                observed.append(expect_error(ValueError, lambda: r.execute("live", "flash-v5-../invalid")))
            return observed
        check("identity_before_material_and_environment", identity)

        def timeout_then_success():
            owner, cj = new_case("timeout-success")
            transport = Transport(cj, ["timeout", response()])
            provider = j.DurableProvider(cj, client_factory=lambda: transport)
            result = provider.evaluate(copy.deepcopy(request))
            assert transport.calls == 2 and result.payload == {"issues": []}
            ledger = r.usage_ledger(owner.root)
            assert ledger["post_attempt_start_records"] == 2 and ledger["http_responses_received"] == 1
            assert ledger["usage_counts"]["unknown"] == 1 and ledger["usage_counts"]["complete"] == 1
            assert ledger["prompt_tokens_total"] is None and ledger["known_prompt_tokens_partial_sum"] == 7
            assert r._service_failure({"status": "completed"}, r._attempts(cj.root))
            for path in owner.root.rglob("*.json"):
                text = path.read_text(encoding="utf-8")
                assert "DO_NOT_PERSIST_HIDDEN_SENTINEL" not in text
                assert "offline-placeholder-never-a-credential" not in text
                assert "Authorization" not in text
            return ledger
        check("predispatch_snapshot_timeout_usage_and_redaction", timeout_then_success)

        def persistence_failure():
            details = []
            for directory in ("requests", "attempts"):
                owner, cj = new_case("write-failure-" + directory)
                transport = Transport(cj, [response()])
                provider = j.DurableProvider(cj, client_factory=lambda: transport)
                original = j.write_x
                def fail_target(path, value):
                    if path.parent.name == directory:
                        raise OSError("independent injected persistence failure")
                    return original(path, value)
                with patch.object(j, "write_x", fail_target):
                    error = expect_error(OSError, lambda: provider.evaluate(copy.deepcopy(request)))
                assert transport.calls == 0
                details.append({"stage": directory, "transport_calls": 0, "error": error})
            return details
        check("persistence_failure_prevents_transport", persistence_failure)

        def usage_states():
            scenarios = [({"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}, "complete"),
                         ({}, "missing"), ({"usage": {"prompt_tokens": 4}}, "partial"),
                         (None, "unknown"), ({"usage": {"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "3"}}, "unknown"),
                         ({"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 99}}, "partial")]
            observed = []
            for envelope, expected in scenarios:
                value = j.usage_info(envelope)
                assert value["status"] == expected
                observed.append(value)
            return observed
        check("four_usage_states_and_invalid_counts", usage_states)

        def orphan():
            owner, cj = new_case("orphan")
            cj.begin_evaluation(copy.deepcopy(request))
            cj.start_post("https://offline.invalid/chat/completions", {"offline": True})
            put(owner.root / "models-start.json", {"kind": "fabricated_orphan_start"})
            ledger = r.usage_ledger(owner.root)
            assert ledger["post_attempt_start_records"] == 1 and ledger["http_responses_received"] == 0
            assert ledger["unfinished_attempt_count"] == 1 and ledger["usage_counts"]["unknown"] == 1
            assert ledger["server_receipt_for_unfinished_attempts"] == "unknown"
            assert ledger["models_get_start_records"] == 1 and ledger["models_get_finish_observed"] == 0
            assert "actual_post_dispatches" not in ledger and "models_get_dispatches" not in ledger
            return ledger
        check("orphan_post_and_models_start_are_unknown", orphan)

        def malformed():
            observed = []
            for index, payload in enumerate((None, [], {"issues": [None]}), 1):
                owner, cj = new_case("shape-" + str(index))
                cj.begin_evaluation(copy.deepcopy(request))
                cj.finish_evaluation(ProviderResult(payload))
                product = {"status": "failed", "error_code": "schema_invalid", "issues": []}
                result = score.score_case(comparison, cj.root, product, "live")
                assert result["parsed_output_count"] == 1
                assert result["first_raw"]["machine_result"] in {"unscorable", "score_error", "fail"}
                assert result["first_raw"]["machine_result"] != "unavailable"
                assert result["final"]["machine_result"] == "terminal_failure"
                assert read(cj.root / "evaluations/01.json")["parsed_business_json"] == payload
                put(cj.root / "independent-scores.json", result)
                observed.append(result)
            return observed
        check("parseable_null_and_bad_shape_preserved", malformed)

        def binding():
            contract = inp.InputContract()
            contract.bind_runtime(g02["case_id"], copy.deepcopy(g02_binding))
            positive = contract(g02, copy.deepcopy(g02_request))
            assert positive["database_binding"] == "matched_persisted_isolated_database"
            details = {"positive": positive, "negative": []}
            for target in ("chapter", "memory_value", "memory_source"):
                mutated = copy.deepcopy(g02_request)
                if target == "chapter":
                    mutated["layers"]["written"]["source_spans"][0]["chapter_id"] = "independent-wrong-chapter"
                elif target == "memory_value":
                    mutated["layers"]["confirmed"]["memory_records"][0]["value"] = "independent wrong value"
                else:
                    mutated["layers"]["confirmed"]["memory_records"][0]["source_span_id"] = "independent-wrong-span"
                error = expect_error(RuntimeError, lambda: contract(g02, mutated))
                assert "input_contract:" in error["message"]
                details["negative"].append({"mutation": target, "error": error})
            return details
        check("g02_same_run_database_binding_without_database", binding)

        def bounded_attempts():
            owner, cj = new_case("two-evaluations")
            transport = Transport(cj, ["timeout", response(), "timeout", response()])
            provider = j.DurableProvider(cj, client_factory=lambda: transport)
            provider.evaluate(copy.deepcopy(request))
            repair = {**copy.deepcopy(request), "contract_repair": {"attempt": 2, "reason_code": "offline_control"}}
            provider.evaluate(repair)
            expect_error(ProviderDispatchDenied, lambda: provider.evaluate(repair))
            assert transport.calls == 4 and cj.evaluation_count == 2
            assert read(cj.root / "requests/02.json")["stage"] == "repair"
            limit_owner, limited = new_case("global-boundary")
            limit_owner.post_count = 107  # Boundary injection, not 107 actual calls.
            limited.begin_evaluation(copy.deepcopy(request))
            fake = Transport(limited, [response()])
            with j.JournalClient(limited, client_factory=lambda: fake) as client:
                client.post("https://offline.invalid/chat/completions", json={"offline": True})
                expect_error(ProviderDispatchDenied, lambda: client.post("https://offline.invalid/chat/completions", json={"offline": True}))
            assert limit_owner.post_count == 108 and fake.calls == 1
            _, brief = new_case("g02-evaluation-boundary", g02)
            brief.begin_evaluation(copy.deepcopy(g02_request))
            expect_error(ProviderDispatchDenied, lambda: brief.begin_evaluation(copy.deepcopy(g02_request)))
            return {"mock_transport_calls_in_two_evaluations": 4, "global_boundary_injected": 107,
                    "last_allowed_mock_transport_calls": 1, "post_cap": 108, "g02_evaluation_cap": 1}
        check("two_evaluations_transport_and_global_caps", bounded_attempts)

        def simulated_matrix(name, service=False):
            base = output / name
            matrix = {"cases": [{**copy.deepcopy(comparison), "ordinal": n} for n in (1, 2, 3)]}
            put(base / "cases.json", matrix)
            put(base / "frozen-inputs.json", {"independent_mock_only": True})
            visited = []
            fake_freeze = types.ModuleType("evaluation.current_flash_v5.freeze")
            fake_freeze.verify = lambda: {"independent_mock_only": True}
            def fake_api(case, provider, workspace, record_root):
                visited.append(case["ordinal"])
                cj = provider.journal
                cj.begin_evaluation(copy.deepcopy(request))
                if service:
                    a, timer = cj.start_post("https://offline.invalid/chat/completions", {"mock": True})
                    cj.finish_post(a, timer, error=httpx.ReadTimeout("offline recovered timeout"))
                    b, timer = cj.start_post("https://offline.invalid/chat/completions", {"mock": True})
                    cj.finish_post(b, timer, response=response())
                    cj.finish_evaluation(ProviderResult({"issues": []}))
                    return {"status": "completed", "issues": [], "source_revision": 1}
                payload = ([], None, {"issues": [None]})[case["ordinal"] - 1]
                cj.finish_evaluation(ProviderResult(payload))
                if case["ordinal"] == 1:
                    raise AttributeError("offline product shape failure")
                return {"status": "failed", "error_code": "schema_invalid", "issues": []}
            with ExitStack() as patches:
                patches.enter_context(patch.object(r, "HERE", base))
                patches.enter_context(patch.object(r, "RESULTS", base / "runs"))
                patches.enter_context(patch.object(r, "WORKSPACES", base / "workspaces"))
                patches.enter_context(patch.object(build_cases, "build", lambda: matrix))
                patches.enter_context(patch.object(r, "_models_preflight", lambda *unused: None))
                patches.enter_context(patch.object(r, "_continuity", fake_api))
                patches.enter_context(patch.dict(sys.modules, {"evaluation.current_flash_v5.freeze": fake_freeze}))
                destination = r.execute("live", "flash-v5-" + name)
            summary = read(destination / "summary.json")
            if service:
                assert visited == [1, 2] and summary["service_stop"]
                assert read(destination / "service-stop.json")["reason"] == "two_consecutive_service_failures"
            else:
                assert visited == [1, 2, 3] and not summary["service_stop"]
                assert (destination / "cases/01/first-failure.json").exists()
                assert (destination / "cases/01/final-product-unavailable.json").exists()
                assert read(destination / "cases/02/scores.json")["first_raw"]["payload_type"] == "NoneType"
                assert read(destination / "cases/03/scores.json")["first_raw"]["machine_result"] == "score_error"
            return {"scope": "runner_control_simulation_with_mock_fixture_and_no_transport", "visited_ordinals": visited,
                    "logical_cases_finished": summary["logical_cases_finished"], "service_stop": summary["service_stop"]}
        check("malformed_results_do_not_swallow_next_cases", lambda: simulated_matrix("quality-continue"))
        check("two_recovered_service_failures_stop_third_case", lambda: simulated_matrix("service-stop", True))

        def auth_and_terminal():
            attempts = [{"finish": {"status": 401, "error_type": None}}]
            assert r._auth_or_model_rejection(attempts)
            assert r._service_failure({"status": "failed"}, attempts)
            assert not r._service_failure({"status": "failed", "error_code": "schema_invalid"}, [])
            return {"auth_401_stop": True, "schema_failure_is_not_service_failure": True}
        check("auth_and_quality_failure_classification", auth_and_terminal)

        def dependency_guard():
            path = HERE.parent / "live_guard.py"
            supplement = HERE.parent / "controller-dependency-freeze.json"
            assert args.dependency_manifest_sha256 and sha(supplement) == args.dependency_manifest_sha256
            before = {str(path.relative_to(ROOT)): sha(path), str(supplement.relative_to(ROOT)): sha(supplement)}
            before.update(read(supplement)["additional_source_hashes"])
            spec = importlib.util.spec_from_file_location("independent_controller_live_guard", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            identity = "flash-v5-audit-guard-check"
            result = module.verify(identity, args.dependency_manifest_sha256)
            assert result["verified"]
            assert not (module.V5 / "runs" / identity).exists()
            assert not (ROOT / "artifacts/current_flash_v5" / identity).exists()
            mismatch = expect_error(RuntimeError, lambda: module.verify(identity, "0" * 64))
            assert mismatch["message"] == "controller_dependency_manifest_changed"
            actual_sha = module.sha
            target = ROOT / "backend/app/text_content.py"
            with patch.object(module, "sha", lambda p: "0" * 64 if p == target else actual_sha(p)):
                drift = expect_error(RuntimeError, lambda: module.verify(identity, args.dependency_manifest_sha256))
            assert drift["message"] == "frozen_dependency_changed:backend/app/text_content.py"
            original_exists = pathlib.Path.exists
            occupied = module.V5 / "runs" / identity
            with patch.object(pathlib.Path, "exists", lambda p: True if p == occupied else original_exists(p)), \
                 patch.object(module, "sha", side_effect=AssertionError("guard_material_read_before_identity_reject")):
                duplicate = expect_error(FileExistsError, lambda: module.verify(identity, args.dependency_manifest_sha256))
            after = {relative: sha(ROOT / relative) for relative in before}
            assert before == after
            put(output / "dependency-guard-hashes-before.json", before)
            put(output / "dependency-guard-hashes-after.json", after)
            return {"positive_verify_only": result, "supplement_identity_rejection": mismatch,
                    "mock_dependency_drift_rejection": drift, "occupied_identity_early_rejection": duplicate,
                    "source_hashes_unchanged": True, "launch_called": False}
        check("controller_dependency_guard", dependency_guard)

        bound_after = {name: sha(ROOT / name) for name in frozen["source_hashes"]}
        fixture_after = {str(p.relative_to(ROOT)): sha(p) for p in fixture_paths}
        result = {"kind": "independent_offline_engineering_controls", "run_id": args.run_id,
                  "manifest_sha256": args.manifest_sha256, "probe_sha256": sha(pathlib.Path(__file__)),
                  "checks": rows, "passed": sum(x["passed"] for x in rows), "total": len(rows),
                  "network_calls": 0, "real_provider_calls": 0, "database_connections": 0,
                  "blocked_attempts": blocked, "frozen_sources_unchanged": bound_before == bound_after,
                  "fixture_json_unchanged": fixture_before == fixture_after,
                  "fixture_hashes": fixture_before,
                  "selected_groups": sorted(selected),
                  "limitations": "No real DB/API/browser/model execution; runner-loop tests replace fixture/API and models preflight. Semantic acceptance is separate."}
        result["all_passed"] = (all(x["passed"] for x in rows) and bound_before == bound_after and
                                fixture_before == fixture_after and not any(blocked.values()))
        put(output / "frozen-hashes-after.json", bound_after)
        put(output / "results.json", result)
        print(json.dumps({"output": str(output), "passed": result["passed"], "total": result["total"],
                          "all_passed": result["all_passed"]}))
        return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
