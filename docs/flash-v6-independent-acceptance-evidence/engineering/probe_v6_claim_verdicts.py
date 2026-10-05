"""Independent V6 contract probes. Prepared only; run after root's stable signal.

All data are synthetic. No credentials, environment files, database, real Provider,
API, or V5 runner are used. Existing evidence is never overwritten. Expectations
derive from criteria.md, risk-note.md and the two declared DESIGN-ADDENDUM files.
Run: .venv\\Scripts\\python.exe -B <this file> --run-id <new audit identity>
"""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import traceback
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COUNTERS = {"socket": 0, "http": 0, "sqlite": 0, "real_provider": 0}


def long_path(path):
    value = str(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\" + str(path.absolute())
    return Path(value)


def require(value, message):
    if not value:
        raise AssertionError(message)


def blocked(kind):
    def deny(*args, **kwargs):
        COUNTERS[kind] += 1
        raise AssertionError("blocked_external_boundary:" + kind)
    return deny


def create_json(path, value):
    # Create-only output; a failed probe and an occupied identity remain intact.
    with long_path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def hashes():
    names = [
        "backend/app/engine.py", "backend/app/provider.py",
        "backend/app/brief_citations.py", "backend/app/memory_contract.py",
        "backend/app/__init__.py", "evaluation/current_flash_v6/CONTRACT.md",
        "evaluation/current_flash_v6/DESIGN-ADDENDUM.md",
        "evaluation/current_flash_v6/DESIGN-ADDENDUM-02.md",
    ]
    files = {name: ROOT / name for name in names}
    files["independent_probe"] = Path(__file__)
    return {name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in files.items()}


def verdict(claim_id, kind="no_issue", basis="This compatible new event needs no issue."):
    return {"claim_span_id": claim_id, "verdict": kind, "basis": basis}


def span(span_id, body):
    return {"id": span_id, "chapter_id": "chapter-" + span_id, "body": body}


def evidence(source, relation="context", sufficiency="sufficient", related=()):
    return {"chapter_id": source["chapter_id"], "span_id": source["id"],
            "relation": relation, "sufficiency": sufficiency,
            "related_memory_ids": list(related)}


def issue(claim_id, sources, nature="state_change"):
    insufficient = nature == "insufficient_evidence"
    return {
        "claim_span_id": claim_id,
        "status": "insufficient_evidence" if insufficient else "conflict",
        "nature": nature, "category": "object_state", "severity": "medium",
        "explanation": ("The record does not establish a delivery destination."
                        if insufficient else "The lamp's earlier and later states can coexist."),
        "reasoning": ("The destination is absent, so the delivery claim remains unknown."
                      if insufficient else "Before dawn it was dark; after dawn it was lit."),
        "temporal_basis": {"claim_anchor": None, "evidence_anchor": None,
                           "relation": "unknown" if insufficient else "explicit_later_transition"},
        "evidence": [evidence(s, sufficiency="insufficient" if insufficient else "sufficient")
                     for s in sources],
        "evidence_chain": [{"span_id": s["id"], "role": "missing_link" if insufficient else "prior_state"}
                           for s in sources],
        "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
    }


def coverage_fixture():
    prior = span("prior-lamp", "Before dawn, the bronze lamp was dark.")
    log = span("delivery-log", "The log names a courier but records no delivery destination.")
    claims = [
        {"id": "c-lamp", "text": "After dawn, the bronze lamp was lit.", "allowed_evidence": [prior]},
        {"id": "c-ribbon", "text": "The courier added a blue ribbon to a parcel.", "allowed_evidence": []},
        {"id": "c-delivery", "text": "The log proves the parcel reached the north tower.", "allowed_evidence": [log]},
    ]
    data = {"draft": {"id": "synthetic-draft", "revision": 1,
                      "body": "\n".join(c["text"] for c in claims)}, "claims": claims, "memory": []}
    payload = {"issues": [issue("c-lamp", [prior]), issue("c-delivery", [log], "insufficient_evidence")],
               "claim_verdicts": [verdict("c-lamp", "reviewed_issue", "This is a compatible explicit transition."),
                                  verdict("c-ribbon"),
                                  verdict("c-delivery", "insufficient_evidence", "The log omits the destination.")]}
    return data, payload


def single_transition():
    data, payload = coverage_fixture()
    data["claims"] = data["claims"][:1]
    data["draft"]["body"] = data["claims"][0]["text"]
    payload["issues"] = payload["issues"][:1]
    payload["claim_verdicts"] = payload["claim_verdicts"][:1]
    return data, payload


def compatible_claims():
    texts = ["A traveler tied a blue ribbon to a parcel.",
             "A porter painted a new sign beside the road.",
             "A gardener planted a young oak beside the gate."]
    claims = [{"id": "new-" + str(i), "text": text, "allowed_evidence": []}
              for i, text in enumerate(texts)]
    return {"draft": {"id": "synthetic-compatible", "revision": 1, "body": "\n".join(texts)},
            "claims": claims, "memory": []}


def empty_answer(data):
    return {"issues": [], "claim_verdicts": [verdict(c["id"]) for c in data["claims"]]}


def rule_fixture(cite_rule=True):
    person = span("mara-mortal", "Mara is a mortal.")
    rule = span("mortal-rule", "Mortals can never cast a spell.")
    memory = [
        {"id": "m-person", "memory_type": "static_canon", "subject": "Mara", "predicate": "identity", "value": "mortal", "source_span_id": person["id"], "chapter_id": person["chapter_id"]},
        {"id": "m-rule", "memory_type": "static_canon", "subject": "Mortals", "predicate": "rule", "value": "cannot cast spells", "source_span_id": rule["id"], "chapter_id": rule["chapter_id"]},
    ]
    data = {"draft": {"id": "synthetic-rule", "revision": 1, "body": "Mara cast a spell."},
            "claims": [{"id": "c-rule", "text": "Mara cast a spell.", "allowed_evidence": [person, rule]}],
            "memory": memory}
    cited = [person, rule] if cite_rule else [person]
    item = issue("c-rule", cited, "confirmed_conflict")
    item.update(category="world_rule", explanation="Mara is mortal and the cited rule prohibits mortal spellcasting.",
                reasoning="Mara's mortal identity plus the governing prohibition jointly contradict her casting a spell.")
    item["temporal_basis"]["relation"] = "timeless_rule"
    # The rule Memory is attached to the identity evidence, intentionally testing
    # set-level grounding without imposing per-item same-source equality.
    item["evidence"][0] = evidence(person, "contradicts", related=["m-person", "m-rule"])
    return data, {"issues": [item], "claim_verdicts": [verdict("c-rule", "reviewed_issue", "The identity and governing rule jointly establish the contradiction.")]}


def prepare_controls(engine_module, provider_module, out):
    Engine = engine_module.ContinuityEngine
    Result = provider_module.ProviderResult

    class StrictStub:
        available = True
        label = "independent-synthetic-stub"
        continuity_contract_version = "v6"
        allows_legacy_continuity_contract = False

        def __init__(self, replies=()):
            self.replies = list(replies)
            self.requests = []
            self.responses = []

        def evaluate(self, request):
            index = len(self.requests)
            require(index < len(self.replies), "unexpected_extra_stub_evaluation")
            self.requests.append(copy.deepcopy(request))
            value = self.replies[index]
            answer = value(request) if callable(value) else copy.deepcopy(value)
            self.responses.append(copy.deepcopy(answer))
            return Result(answer, input_tokens=1, output_tokens=1, latency_ms=0)

    def reject(engine, payload, data, prefix):
        try:
            engine.validate(payload, data)
        except ValueError as error:
            require(str(error).startswith(prefix), "rejected_for_unrelated_reason:" + str(error))
            return str(error)
        raise AssertionError("invalid_contract_was_accepted")

    def execute_record(stub, data, name):
        result = Engine(stub).execute(data)
        create_json(out / (name + "-trace.json"), {"input": data, "requests": stub.requests,
                                                  "responses": stub.responses, "result": result})
        return result

    def exact_cover():
        data, payload = coverage_fixture()
        clean = Engine(StrictStub()).validate(payload, data)
        require([i["claim_span_id"] for i in clean] == ["c-lamp", "c-delivery"], "coverage_changed_issue_mapping")
        require(clean[0]["nature"] == "state_change", "reviewed_issue_became_confirmed_conflict")
        require(clean[1]["nature"] == "insufficient_evidence", "insufficient_issue_disappeared")
        require(all("claim_verdicts" not in row for row in clean), "ledger_leaked_into_issue")
        return {"exact_claims": 3, "issues": 2, "preserved_state_change": True}

    def malformed_coverage():
        data, original = coverage_fixture()
        errors = {}
        variants = {}
        p = copy.deepcopy(original); p["claim_verdicts"].pop(); variants["missing"] = p
        p = copy.deepcopy(original); p["claim_verdicts"].append(copy.deepcopy(p["claim_verdicts"][0])); variants["duplicate"] = p
        p = copy.deepcopy(original); p["claim_verdicts"][0]["claim_span_id"] = "foreign"; variants["foreign"] = p
        for name, bad_id in [("null", None), ("number", 7), ("array", ["c-lamp"]), ("object", {"id": "c-lamp"})]:
            p = copy.deepcopy(original); p["claim_verdicts"][0]["claim_span_id"] = bad_id; variants[name] = p
        p = copy.deepcopy(original); p["claim_verdicts"][0]["basis"] = "  "; variants["blank_basis"] = p
        p = copy.deepcopy(original); del p["claim_verdicts"]; variants["missing_ledger"] = p
        for name, payload in variants.items():
            errors[name] = reject(Engine(StrictStub()), payload, data, "claim_verdicts_")
        return errors

    def contradictory_mapping():
        data, original = coverage_fixture()
        variants = {}
        p = copy.deepcopy(original); p["claim_verdicts"][0]["verdict"] = "no_issue"; variants["no_issue_with_issue"] = p
        p = copy.deepcopy(original); p["claim_verdicts"][0]["verdict"] = "insufficient_evidence"; variants["wrong_issue_status"] = p
        p = copy.deepcopy(original); p["claim_verdicts"][2]["verdict"] = "reviewed_issue"; variants["insufficient_as_reviewed"] = p
        p = copy.deepcopy(original); p["issues"].pop(0); variants["reviewed_without_issue"] = p
        p = copy.deepcopy(original); p["issues"].append(copy.deepcopy(p["issues"][0])); variants["duplicate_issue"] = p
        for name, bad_id in [("foreign_issue", "foreign"), ("nonstring_issue", ["c-lamp"])]:
            p = copy.deepcopy(original); p["issues"][0]["claim_span_id"] = bad_id; variants[name] = p
        return {name: reject(Engine(StrictStub()), p, data, "claim_verdicts_") for name, p in variants.items()}

    def explained_no_issue():
        data = compatible_claims()
        require(Engine(StrictStub()).validate(empty_answer(data), data) == [], "compatible_empty_result_rejected")
        stub = StrictStub([lambda request: empty_answer(request)])
        result = execute_record(stub, data, "explained-no-issue")
        require(result["status"] == "completed" and result["issues"] == [], "explained_no_issue_not_completed")
        require(len(stub.requests) == 1, "compatible_claims_unexpected_repair")
        return {"claims": 3, "stub_evaluations": 1}

    def repair_removal():
        data, first = single_transition()
        first["claim_verdicts"] = []  # A real compatible issue, but the required ledger is absent.
        valid_second = {"issues": [], "claim_verdicts": [verdict("c-lamp", "no_issue", "The earlier dark state and later lit state are compatible, so no review is needed.")]}
        good = StrictStub([first, valid_second])
        result = execute_record(good, data, "repair-explicit-removal")
        require(result["status"] == "completed" and result["issues"] == [], "explained_repair_removal_failed")
        require(len(good.requests) == 2, "repair_count_not_two")
        require(good.requests[1]["contract_repair"]["rejected_issues"] == first["issues"], "repair_lost_first_issues")
        require(good.responses[1] == valid_second, "repair_explanation_not_retained_in_observed_payload")
        bad = StrictStub([first, {"issues": [], "claim_verdicts": []}])
        failed = execute_record(bad, data, "repair-silent-removal")
        require(failed["status"] == "failed" and failed["error_code"].startswith("claim_verdicts_"), "silent_repair_was_no_conflict")
        require(len(bad.requests) == 2, "repair_bound_changed")
        return {"explained_removal": "completed", "uncovered_removal": failed["error_code"], "stub_evaluations_each": 2}

    def per_batch_cover():
        data = compatible_claims()
        planner = Engine(StrictStub())
        # Use the real planner and real prompt budget; only lower its in-memory
        # budget so these short synthetic claims exercise three actual batches.
        singles = [engine_module.request_prompt_and_budget(planner._request([c], [], data["draft"]))[1] for c in data["claims"]]
        pairs = [engine_module.request_prompt_and_budget(planner._request(data["claims"][i:i+2], [], data["draft"]))[1] for i in range(2)]
        limit = max(singles)
        require(min(pairs) > limit, "synthetic_fixture_cannot_force_separate_batches")
        with patch.object(engine_module, "MAX_INPUT_BUDGET_UNITS", limit):
            batches = planner._batches(data)
            require([len(b["claims"]) for b in batches] == [1, 1, 1], "actual_planner_not_three_batches")
            good = StrictStub([lambda r: empty_answer(r)] * 3)
            completed = execute_record(good, data, "batch-exact-cover")
            require(completed["status"] == "completed" and completed["issues"] == [], "exact_batch_coverage_failed")
            require([r["claims"][0]["id"] for r in good.requests] == [c["id"] for c in data["claims"]], "batch_ids_changed")
            stolen = {"issues": [], "claim_verdicts": [verdict(data["claims"][0]["id"])]}
            bad = StrictStub([lambda r: empty_answer(r), stolen, stolen])
            failed = execute_record(bad, data, "batch-foreign-cover")
            require(failed["status"] == "failed" and failed["error_code"].startswith("claim_verdicts_"), "prior_batch_id_covered_current_claim")
            require(len(bad.requests) == 3 and bad.requests[1]["claims"] == bad.requests[2]["claims"], "repair_not_bound_to_failing_batch")
            require(all(r["claims"][0]["id"] != data["claims"][2]["id"] for r in bad.requests), "continued_after_terminal_contract_failure")
        return {"batches": 3, "positive_evaluations": 3, "foreign_batch_evaluations": 3, "foreign_error": failed["error_code"]}

    def borrowed_rule():
        data, payload = rule_fixture(cite_rule=False)
        engine = Engine(StrictStub())
        error = reject(engine, payload, data, "timeless_rule_unproven")
        diagnostics = engine._repair_diagnostics(payload, data)
        require(any("timeless_rule_unproven" in d["problem_codes"] for d in diagnostics), "repair_diagnostic_accepted_uncited_rule")
        stub = StrictStub([payload, payload])
        result = execute_record(stub, data, "borrowed-rule")
        require(len(stub.requests) == 2, "borrowed_rule_not_bounded_repair")
        require(not any(i.get("nature") == "confirmed_conflict" for i in result.get("issues", [])), "borrowed_rule_survived_as_confirmed")
        if result["status"] == "completed":
            require(result["contract_normalization_count"] == 1 and result["issues"][0]["nature"] == "insufficient_evidence", "temporal_normalization_not_explicit")
        else:
            require(result["status"] == "failed", "unexpected_borrowed_rule_terminal")
        return {"strict_rejection": error, "execute_terminal": result["status"],
                "normalization_count": result.get("contract_normalization_count", 0)}

    def separately_cited_rule():
        data, payload = rule_fixture(cite_rule=True)
        clean = Engine(StrictStub()).validate(payload, data)
        require(clean[0]["nature"] == "confirmed_conflict", "separately_cited_rule_not_accepted")
        require(len(clean[0]["evidence"]) == 2 and clean[0]["evidence"][1]["relation"] == "context", "auxiliary_context_rewritten_as_contradiction")
        require(Engine(StrictStub())._repair_diagnostics(payload, data) == [], "diagnostics_disagree_with_valid_rule_set")
        unselected = copy.deepcopy(data)
        unselected["claims"][0]["allowed_evidence"] = unselected["claims"][0]["allowed_evidence"][:1]
        error = reject(Engine(StrictStub()), payload, unselected, "evidence_unresolvable")
        return {"separate_rule_citation": "accepted", "unselected_rule_source": error}

    def ordinary_cross_source():
        data, payload = single_transition()
        data["memory"] = [{"id": "m-cross", "memory_type": "dynamic_state", "subject": "bronze lamp",
                           "predicate": "location", "value": "courtyard", "source_span_id": "other-lamp-source", "chapter_id": "other-chapter"}]
        payload["issues"][0]["evidence"][0]["related_memory_ids"] = ["m-cross"]
        clean = Engine(StrictStub()).validate(payload, data)
        require(clean[0]["nature"] == "state_change" and clean[0]["evidence"][0]["related_memory_ids"] == ["m-cross"], "ordinary_cross_source_association_rejected")
        return {"association": "retained", "nature": "state_change", "proof_qualification": "not_used"}

    return [
        ("exact-multiclaim-cover-and-state-change", exact_cover),
        ("malformed-or-missing-cover", malformed_coverage),
        ("contradictory-issue-mapping", contradictory_mapping),
        ("explained-compatible-no-issue", explained_no_issue),
        ("repair-removal-still-covered", repair_removal),
        ("actual-batch-local-cover", per_batch_cover),
        ("borrowed-uncited-rule-rejected", borrowed_rule),
        ("separately-cited-rule-and-selection-boundary", separately_cited_rule),
        ("ordinary-cross-source-association-retained", ordinary_cross_source),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    require(bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}", args.run_id)), "invalid_audit_identity")
    audit_root = HERE / "probe-runs"
    long_path(audit_root).mkdir(exist_ok=True)
    out = audit_root / args.run_id
    long_path(out).mkdir(exist_ok=False)  # Reject before importing or probing product code.
    before = hashes()
    create_json(out / "start.json", {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                                   "scope": "synthetic offline changed-contract paths only", "before_sha256": before})
    records = []
    fatal = None
    try:
        with ExitStack() as guard:
            for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex",
                           "socket.socket.send", "socket.socket.sendall", "socket.socket.sendto", "socket.getaddrinfo"):
                guard.enter_context(patch(target, blocked("socket")))
            guard.enter_context(patch("sqlite3.connect", blocked("sqlite")))
            guard.enter_context(patch("sqlite3.dbapi2.connect", blocked("sqlite")))
            import httpx
            for target in ("httpx.Client.send", "httpx.AsyncClient.send", "httpx.HTTPTransport.handle_request", "httpx.AsyncHTTPTransport.handle_async_request"):
                guard.enter_context(patch(target, blocked("http")))
            sys.path.insert(0, str(ROOT / "backend"))
            from app import engine, provider
            guard.enter_context(patch.object(provider.DeepSeekProvider, "__init__", blocked("real_provider")))
            guard.enter_context(patch.object(provider.DeepSeekProvider, "evaluate", blocked("real_provider")))
            for index, (name, control) in enumerate(prepare_controls(engine, provider, out), 1):
                try:
                    detail = control()
                    row = {"name": name, "status": "pass", "detail": detail}
                except Exception as error:
                    row = {"name": name, "status": "fail", "exception_type": type(error).__name__,
                           "error": str(error), "traceback": traceback.format_exc()}
                    if not long_path(out / "first-failure.json").exists():
                        create_json(out / "first-failure.json", row)
                records.append(row)
                create_json(out / (f"{index:02d}-" + name + ".json"), row)
    except Exception as error:
        fatal = {"exception_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()}
        if not long_path(out / "first-failure.json").exists():
            create_json(out / "first-failure.json", fatal)
    after = hashes()
    passed = fatal is None and len(records) == 9 and all(r["status"] == "pass" for r in records) and before == after and not any(COUNTERS.values())
    result = {"status": "pass" if passed else "fail", "controls": records, "fatal": fatal,
              "blocked_boundary_attempts": COUNTERS, "source_hashes_stable": before == after,
              "before_sha256": before, "after_sha256": after,
              "limitations": ["Synthetic stub answers; zero live-model evidence.",
                              "Structural coverage and rule-source binding only; no general semantic proof.",
                              "V5 durability/usage controls are intentionally not repeated."]}
    create_json(out / "results.json", result)
    print(json.dumps({"status": result["status"], "groups": len(records), "passed": sum(r["status"] == "pass" for r in records), "output": str(out), "blocked_boundary_attempts": COUNTERS}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
