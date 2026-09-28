"""Flash-high continuity review is opt-in; defaults and non-review tasks are unchanged."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from app.provider import (MAX_OUTPUT_BUDGET_UNITS, REVIEW_THINKING_MAX_OUTPUT_TOKENS, REVIEW_THINKING_TIMEOUT_SECONDS,
                          DeepSeekProvider, InputBudgetExceeded)
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
