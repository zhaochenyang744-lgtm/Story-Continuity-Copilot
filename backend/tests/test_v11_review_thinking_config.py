"""Flash-high continuity review is opt-in; defaults and non-review tasks are unchanged."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from app.provider import (MAX_OUTPUT_BUDGET_UNITS, REVIEW_THINKING_MAX_OUTPUT_TOKENS, REVIEW_THINKING_RUN_TOKEN_BUDGET,
                          REVIEW_THINKING_TIMEOUT_SECONDS, DeepSeekProvider, InputBudgetExceeded)
from app.stage13 import Stage13Settings


BASE_ENV = {"CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": "deepseek-flash",
            "CONTINUITY_BASE_URL": "https://unit.invalid", "CONTINUITY_API_KEY": "unit-test"}
CONTINUITY_REQUEST = {"draft": {"id": "d", "revision": 1, "body": "Mira holds the key."},
                      "claims": [{"id": "c", "text": "Mira holds the key.", "allowed_evidence": []}],
                      "memory": [], "output_schema": {}}
MEMORY_REQUEST = {"task": "memory_initialization", "source_revision": 1, "sources": [], "output_schema": {}}


class Response:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        payload = {"issues": [], "claim_verdicts": []}
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class Client:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        pass

    def post(self, url, headers, json):
        self.sink.append(json)
        return Response()


def provider(thinking=None):
    env = dict(BASE_ENV, **({} if thinking is None else {"CONTINUITY_REVIEW_THINKING": thinking}))
    sent = []
    with patch.dict(os.environ, env, clear=True):
        instance = DeepSeekProvider(client_factory=lambda: Client(sent))
    return instance, sent


class ReviewThinkingConfigTests(unittest.TestCase):
    def test_default_body_is_unchanged_for_every_task(self):
        instance, sent = provider()
        for request in (CONTINUITY_REQUEST, MEMORY_REQUEST):
            instance.evaluate(request)
        for body in sent:
            self.assertEqual((body["thinking"], body["temperature"], body["max_tokens"]),
                             ({"type": "disabled"}, 0, MAX_OUTPUT_BUDGET_UNITS))
            self.assertNotIn("reasoning_effort", body)
        self.assertEqual(instance._request_timeout, instance.timeout_seconds)

    def test_high_enables_thinking_only_for_continuity_review(self):
        instance, sent = provider("high")
        instance.evaluate(CONTINUITY_REQUEST)
        self.assertEqual(instance._request_timeout, REVIEW_THINKING_TIMEOUT_SECONDS)
        instance.evaluate(MEMORY_REQUEST)
        self.assertEqual(instance._request_timeout, instance.timeout_seconds)
        review, memory = sent
        self.assertEqual((review["model"], review["thinking"], review["reasoning_effort"], review["max_tokens"]),
                         ("deepseek-flash", {"type": "enabled"}, "high", REVIEW_THINKING_MAX_OUTPUT_TOKENS))
        self.assertNotIn("temperature", review)
        self.assertEqual((memory["thinking"], memory["temperature"], memory["max_tokens"]),
                         ({"type": "disabled"}, 0, MAX_OUTPUT_BUDGET_UNITS))

    def test_input_budget_is_still_checked_before_any_dispatch(self):
        instance, sent = provider("high")
        oversized = {**CONTINUITY_REQUEST, "draft": {**CONTINUITY_REQUEST["draft"], "body": "界" * 6000}}
        with self.assertRaises(InputBudgetExceeded):
            instance.evaluate(oversized)
        self.assertEqual(sent, [])

    def test_run_budget_override_only_for_thinking_review(self):
        self.assertIsNone(provider()[0].continuity_run_token_budget)
        self.assertEqual(provider("high")[0].continuity_run_token_budget, REVIEW_THINKING_RUN_TOKEN_BUDGET)
        self.assertIsNone(object.__new__(DeepSeekProvider).continuity_run_token_budget)

    def test_engine_uses_provider_budget_and_names_truncation(self):
        from app.engine import MAX_RUN_TOKENS, ContinuityEngine
        from app.provider import ProviderInvalidJson, ProviderResult

        class Stub:
            available = True
            continuity_contract_version = "v6"
            label = model_label = "stub"

            def __init__(self, outcome, budget=None):
                self.outcome, self.continuity_run_token_budget = outcome, budget

            def evaluate(self, request):
                if isinstance(self.outcome, Exception):
                    raise self.outcome
                return self.outcome

        data = {"draft": {"id": "d", "revision": 1, "body": "Mira holds the key."},
                "claims": [{"id": "c", "text": "Mira holds the key.", "allowed_evidence": []}], "memory": []}
        answer = {"issues": [], "claim_verdicts": [{"claim_span_id": "c", "verdict": "no_issue", "basis": "Compatible."}]}
        large = ProviderResult(answer, input_tokens=4000, output_tokens=MAX_RUN_TOKENS)
        self.assertEqual(ContinuityEngine(Stub(large)).execute(data)["status"], "budget_paused")
        self.assertEqual(ContinuityEngine(Stub(large, REVIEW_THINKING_RUN_TOKEN_BUDGET)).execute(data)["status"], "completed")
        truncated = ProviderInvalidJson(10, 12000, None, 1, "length")
        self.assertEqual(ContinuityEngine(Stub(truncated)).execute(data)["error_code"], "output_truncated")
        malformed = ProviderInvalidJson(10, 20, None, 1, "stop")
        self.assertEqual(ContinuityEngine(Stub(malformed)).execute(data)["error_code"], "invalid_json")

    def test_repair_input_allowance_only_for_thinking_review_repairs(self):
        from app.provider import MAX_INPUT_BUDGET_UNITS, REVIEW_THINKING_REPAIR_INPUT_BUDGET_UNITS
        repair = {**CONTINUITY_REQUEST, "contract_repair": {"attempt": 2}}
        default, _ = provider()
        high, _ = provider("high")
        self.assertEqual(default.input_budget_for(repair), MAX_INPUT_BUDGET_UNITS)
        self.assertEqual(high.input_budget_for(CONTINUITY_REQUEST), MAX_INPUT_BUDGET_UNITS)
        self.assertEqual(high.input_budget_for({**MEMORY_REQUEST, "contract_repair": {}}), MAX_INPUT_BUDGET_UNITS)
        self.assertEqual(high.input_budget_for(repair), REVIEW_THINKING_REPAIR_INPUT_BUDGET_UNITS)

    def test_engine_admits_larger_repair_only_with_provider_allowance(self):
        from app.engine import ContinuityEngine
        from app.provider import ProviderResult, REVIEW_THINKING_REPAIR_INPUT_BUDGET_UNITS

        class Stub:
            available = True
            continuity_contract_version = "v6"
            label = model_label = "stub"

            def __init__(self, allowance=None):
                self.continuity_repair_input_budget_units = allowance
                self.calls = 0

            def evaluate(self, request):
                self.calls += 1
                if "contract_repair" not in request:
                    return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1)  # missing verdicts -> repair
                return ProviderResult({"issues": [], "claim_verdicts": [
                    {"claim_span_id": "c", "verdict": "no_issue", "basis": "Compatible."}]}, input_tokens=1, output_tokens=1)

        data = {"draft": {"id": "d", "revision": 1, "body": "Mira holds the key."},
                "claims": [{"id": "c", "text": "Mira holds the key.", "allowed_evidence": []}], "memory": []}
        sized = lambda request: ("", 7000 if "contract_repair" in request else 100)
        with patch("app.engine.request_prompt_and_budget", side_effect=sized):
            refused = ContinuityEngine(Stub()).execute(data)
            admitted = ContinuityEngine(Stub(REVIEW_THINKING_REPAIR_INPUT_BUDGET_UNITS)).execute(data)
        self.assertEqual((refused["status"], refused["error_code"]), ("failed", "input_budget_exceeded"))
        self.assertEqual(admitted["status"], "completed", admitted)

    def test_truncated_high_thinking_answer_is_retried_once_at_medium(self):
        from app.provider import ProviderInvalidJson, REVIEW_THINKING_TRUNCATION_FALLBACK_EFFORT

        class Scripted:
            status_code = 200

            def __init__(self, content, finish, prompt, completion):
                self.payload = {"choices": [{"finish_reason": finish, "message": {"content": content}}],
                                "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}

            def raise_for_status(self):
                pass

            def json(self):
                return self.payload

        truncated = Scripted('{"issues": [', "length", 4000, 16000)
        valid = Scripted(json.dumps({"issues": [], "claim_verdicts": []}), "stop", 4000, 3000)
        cases = (("high", [truncated, valid], "ok"), ("high", [truncated, truncated], "raise"),
                 ("high", [Scripted("not json", "stop", 10, 5)], "raise"), (None, [truncated], "raise"))
        for thinking, script, outcome in cases:
            with self.subTest(thinking=thinking, responses=len(script), outcome=outcome):
                sent, queue = [], list(script)

                class SeqClient(Client):
                    def post(self, url, headers, json):
                        self.sink.append(json)
                        return queue.pop(0)

                env = dict(BASE_ENV, **({} if thinking is None else {"CONTINUITY_REVIEW_THINKING": thinking}))
                with patch.dict(os.environ, env, clear=True):
                    instance = DeepSeekProvider(client_factory=lambda: SeqClient(sent))
                if outcome == "ok":
                    result = instance.evaluate(CONTINUITY_REQUEST)
                    self.assertEqual((result.input_tokens, result.output_tokens, result.finish_reason), (8000, 19000, "stop"))
                else:
                    with self.assertRaises(ProviderInvalidJson) as caught:
                        instance.evaluate(CONTINUITY_REQUEST)
                    if len(script) == 2:
                        self.assertEqual((caught.exception.output_tokens, caught.exception.finish_reason), (32000, "length"))
                self.assertEqual(len(sent), len(script))
                if len(sent) == 2:
                    self.assertEqual((sent[0]["reasoning_effort"], sent[1]["reasoning_effort"]),
                                     ("high", REVIEW_THINKING_TRUNCATION_FALLBACK_EFFORT))

    def test_unknown_thinking_value_fails_closed(self):
        instance, _ = provider("medium")
        self.assertFalse(instance.available)

    def test_public_mode_accepts_pro_or_flash_and_known_thinking_values_only(self):
        from tests.test_stage13_public_app import Stage13PublicAppTests
        public_env = Stage13PublicAppTests.public_env()
        for model, thinking in (("deepseek-v4-pro", None), ("deepseek-flash", "high"), ("deepseek-flash", "disabled")):
            env = dict(public_env, CONTINUITY_MODEL=model, **({} if thinking is None else {"CONTINUITY_REVIEW_THINKING": thinking}))
            with self.subTest(model=model, thinking=thinking), patch.dict(os.environ, env, clear=True):
                self.assertTrue(Stage13Settings.from_env().public_app_mode)
        for model, thinking in (("deepseek-chat", "high"), ("deepseek-flash", "medium")):
            env = dict(public_env, CONTINUITY_MODEL=model, CONTINUITY_REVIEW_THINKING=thinking)
            with self.subTest(model=model, thinking=thinking), patch.dict(os.environ, env, clear=True), \
                    self.assertRaisesRegex(RuntimeError, "provider_config_invalid"):
                Stage13Settings.from_env()


if __name__ == "__main__":
    unittest.main()
