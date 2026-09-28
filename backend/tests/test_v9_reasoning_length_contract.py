"""Offline regression for the V8 undisclosed reasoning-length rejection.

V8 Flash-high case 04 judged the facts correctly but returned an 881-character
reasoning that the engine rejected as a generic, non-repairable schema_invalid.
The 800 code-point limit is now one constant shared by the prompt, output schema,
validator and repair diagnostics. The saved first answer is read as a fixture; no
live runner, database or Provider is constructed.
"""
from __future__ import annotations

import copy
import json
import pathlib
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app.engine import ContinuityContractValidationError, ContinuityEngine
from app.provider import (CONTINUITY_PROMPT_VERSION, MAX_ISSUE_REASONING_CODEPOINTS, ProviderResult,
                          continuity_prompt)


ROOT = pathlib.Path(__file__).resolve().parents[2]
V8_CASE_04 = ROOT / "evaluation/model_compare_v8/runs/model-compare-v8-20260927-01/cases/04/flash-high"


class OfflineProvider:
    available = True
    continuity_contract_version = "v6"
    label = model_label = "v9-offline-regression"

    def __init__(self, *answers):
        self.answers = answers
        self.requests = []

    def evaluate(self, request):
        if len(self.requests) >= len(self.answers):
            raise AssertionError("Unexpected extra evaluate; repair must remain bounded")
        answer = self.answers[len(self.requests)]
        self.requests.append(copy.deepcopy(request))
        return ProviderResult(answer, input_tokens=1, output_tokens=1)


def captured_v8_04():
    request = json.loads((V8_CASE_04 / "requests/01.json").read_text(encoding="utf-8"))["business_request"]
    raw = json.loads((V8_CASE_04 / "evaluations/01.json").read_text(encoding="utf-8"))["parsed_business_json"]
    return request, raw


def with_reasoning(raw, reasoning):
    changed = copy.deepcopy(raw)
    changed["issues"][0]["reasoning"] = reasoning
    return changed


def reasoning_diagnostics(diagnostics, claim_id):
    return [d for d in diagnostics if d.get("claim_span_id") == claim_id and d.get("invalid_field") == "reasoning"]


class ReasoningLengthContractTests(unittest.TestCase):
    def setUp(self):
        guards = ExitStack()
        self.addCleanup(guards.close)
        for target in ("socket.socket.connect", "socket.create_connection", "sqlite3.connect",
                       "httpx.Client.send", "httpx.AsyncClient.send"):
            guards.enter_context(patch(target, side_effect=AssertionError("External access forbidden in offline regression")))

    def test_saved_v8_04_overlong_reasoning_has_precise_repairable_diagnostic(self):
        request, raw = captured_v8_04()
        issue = raw["issues"][0]
        observed = len(issue["reasoning"].strip())
        self.assertGreater(observed, MAX_ISSUE_REASONING_CODEPOINTS)
        with self.assertRaisesRegex(ContinuityContractValidationError, "reasoning_too_long") as caught:
            ContinuityEngine(OfflineProvider()).validate(raw, request)
        diagnostic = reasoning_diagnostics(caught.exception.diagnostics, issue["claim_span_id"])[0]
        self.assertEqual((diagnostic["observed_length"], diagnostic["limit"], diagnostic["problem"]),
                         (observed, MAX_ISSUE_REASONING_CODEPOINTS, "too_long"))
        first_attempt = ContinuityEngine(OfflineProvider())._repair_diagnostics(raw, request)
        self.assertTrue(reasoning_diagnostics(first_attempt, issue["claim_span_id"]), first_attempt)

    def test_saved_v8_04_repair_receives_complete_rejected_output_and_can_complete(self):
        request, first = captured_v8_04()
        before = copy.deepcopy(first)
        shortened = with_reasoning(first, first["issues"][0]["reasoning"].strip()[:MAX_ISSUE_REASONING_CODEPOINTS])
        provider = OfflineProvider(first, shortened)
        result = ContinuityEngine(provider).execute(request)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(provider.requests), 2)
        repair = provider.requests[1]["contract_repair"]
        self.assertEqual(repair["reason_code"], "reasoning_too_long")
        self.assertEqual(repair["rejected_issues"], before["issues"])
        self.assertTrue(reasoning_diagnostics(repair["diagnostics"], first["issues"][0]["claim_span_id"]))
        prompt = json.loads(continuity_prompt(provider.requests[1]))
        self.assertIn(str(MAX_ISSUE_REASONING_CODEPOINTS), prompt["contract_repair"]["instruction"])
        self.assertEqual(first, before, "The rejected reasoning must not be silently truncated")

    def test_repeated_overlong_reasoning_fails_with_specific_code_after_one_repair(self):
        request, raw = captured_v8_04()
        provider = OfflineProvider(raw, copy.deepcopy(raw))
        result = ContinuityEngine(provider).execute(request)
        self.assertEqual((result["status"], result["error_code"]), ("failed", "reasoning_too_long"))
        self.assertEqual(len(provider.requests), 2)

    def test_limit_boundary_counts_trimmed_code_points(self):
        request, raw = captured_v8_04()
        engine = ContinuityEngine(OfflineProvider())
        exact = "界" * MAX_ISSUE_REASONING_CODEPOINTS
        self.assertEqual(engine.validate(with_reasoning(raw, exact), request)[0]["reasoning"], exact)
        self.assertEqual(engine.validate(with_reasoning(raw, f"  {exact}\n"), request)[0]["reasoning"], exact)
        with self.assertRaisesRegex(ContinuityContractValidationError, "reasoning_too_long") as caught:
            engine.validate(with_reasoning(raw, exact + "界"), request)
        diagnostic = caught.exception.diagnostics[0]
        self.assertEqual((diagnostic["observed_length"], diagnostic["limit"]),
                         (MAX_ISSUE_REASONING_CODEPOINTS + 1, MAX_ISSUE_REASONING_CODEPOINTS))

    def test_blank_or_non_string_reasoning_remains_a_schema_rejection(self):
        request, raw = captured_v8_04()
        for value in ("   ", None, 7):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    ContinuityEngine(OfflineProvider()).validate(with_reasoning(raw, value), request)
                self.assertEqual(str(caught.exception), "schema_invalid")
                self.assertNotIsInstance(caught.exception, ContinuityContractValidationError)

    def test_limit_is_disclosed_in_rules_and_output_schema(self):
        request, _ = captured_v8_04()
        engine = ContinuityEngine(OfflineProvider())
        current = engine._request(request["claims"], request["memory"], request["draft"])
        self.assertIn(str(MAX_ISSUE_REASONING_CODEPOINTS), current["output_schema"]["issues"][0]["reasoning"])
        prompt = json.loads(continuity_prompt(current))
        self.assertEqual(prompt["prompt_version"], CONTINUITY_PROMPT_VERSION)
        self.assertTrue(any("reasoning" in rule and str(MAX_ISSUE_REASONING_CODEPOINTS) in rule for rule in prompt["rules"]))


if __name__ == "__main__":
    unittest.main()
