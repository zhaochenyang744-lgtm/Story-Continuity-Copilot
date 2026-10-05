"""Bounded transport fakes and read-only V7 replay; never use real HTTP or DB."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from unittest.mock import patch

import httpx
import app.engine as engine_module
from app.provider import ProviderInvalidJson, request_prompt_and_budget
from evaluation.model_compare_v8.config import *
from evaluation.model_compare_v8.harness import (FrozenInputEngine, _run_trial, experimental_budget,
    models_preflight, reserve)
from evaluation.model_compare_v8.journal import (ExperimentStopped, GenerationIncomplete, MatrixLedger,
    TrialJournal, usage_receipt)
from evaluation.model_compare_v8.provider import ExperimentProvider, body_for
from evaluation.model_compare_v8.replay import replay_all
from evaluation.model_compare_v8.score import safe_score, raw_score


class Response:
    def __init__(self, value, status=200):
        self.value, self.status_code = value, status
    def json(self):
        return self.value


class Client:
    def __init__(self, queue):
        self.queue, self.posts, self.gets = list(queue), 0, 0
    def __enter__(self):
        return self
    def __exit__(self, *unused):
        pass
    def post(self, *args, **kwargs):
        self.posts += 1
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    def get(self, *args, **kwargs):
        self.gets += 1
        return self.queue.pop(0)


def envelope(content, *, p=1000, c=100, reasoning=None, finish="stop"):
    return {"id": "offline-response", "model": "offline", "system_fingerprint": "offline",
        "usage": {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c,
                  "completion_tokens_details": {"reasoning_tokens": 10}},
        "choices": [{"finish_reason": finish, "message": {"content": content, "reasoning_content": reasoning}}]}


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".offline-", dir=HERE)
        self.root = pathlib.Path(self.temp.name)
        self.network = patch("httpx.Client", side_effect=AssertionError("real_network_forbidden"))
        self.network.start()
        self.case = cases()[1]  # Genuine compatible no-issue input.
        self.request = request_for(self.case)
        self.good = {"issues": [], "claim_verdicts": [{"claim_span_id": self.request["claims"][0]["id"],
                    "verdict": "no_issue", "basis": "The supplied facts are compatible with this claim."}]}
    def tearDown(self):
        self.network.stop()
        self.temp.cleanup()
        self.assertEqual(engine_module.MAX_RUN_TOKENS, 8000)
    def make(self, responses, name="trial"):
        client = Client(responses)
        ledger = MatrixLedger(self.root)
        journal = TrialJournal(ledger, self.root / name, {}, CONDITIONS[0])
        provider = ExperimentProvider(journal, CONDITIONS[0], self.request, "offline-key", lambda: client)
        return provider, journal, ledger, client
    def test_fixed_matrix_and_prompt_parameters(self):
        items = schedule()
        self.assertEqual(len(items), 102)
        self.assertEqual([r["condition_id"] for r in items[:9]],
            ["flash-off", "flash-high", "pro-high", "flash-high", "pro-high", "flash-off", "pro-high", "flash-off", "flash-high"])
        for case in cases():
            request = request_for(case)
            self.assertLessEqual(request_prompt_and_budget(request)[1], 6000)
            prompts = []
            for condition in CONDITIONS:
                body = body_for(request, condition)
                self.assertEqual(body["max_tokens"], 32768)
                self.assertNotIn("top_p", body)
                self.assertEqual("temperature" in body, condition["id"] == "flash-off")
                self.assertEqual("reasoning_effort" in body, condition["id"] != "flash-off")
                prompts.append(body["messages"][0]["content"])
            self.assertEqual(len(set(prompts)), 1)
            for forbidden in ("control_ids", "semantic_role", "expected_class", "minimum_sufficient_evidence_sets", "world_fact_expected"):
                self.assertNotIn(forbidden, prompts[0])
    def test_budget_restores_on_success_and_error_and_nested_rejection(self):
        with experimental_budget():
            self.assertEqual(engine_module.MAX_RUN_TOKENS, 40000)
            with self.assertRaises(RuntimeError):
                with experimental_budget():
                    pass
        with self.assertRaisesRegex(RuntimeError, "sentinel"):
            with experimental_budget():
                raise RuntimeError("sentinel")
        self.assertEqual(engine_module.MAX_RUN_TOKENS, 8000)
    def test_budget_refuses_existing_drift_and_restores_it(self):
        engine_module.MAX_RUN_TOKENS = 7999
        try:
            with self.assertRaisesRegex(RuntimeError, "drift"):
                with experimental_budget():
                    pass
            self.assertEqual(engine_module.MAX_RUN_TOKENS, 7999)
        finally:
            engine_module.MAX_RUN_TOKENS = 8000
    def test_real_usage_and_reasoning_privacy(self):
        hidden = "PRIVATE_REASONING_SENTINEL_NEVER_PERSIST"
        p, journal, ledger, client = self.make([Response(envelope(json.dumps(self.good), c=9000, reasoning=hidden))])
        with experimental_budget():
            result = FrozenInputEngine(p).execute(self.request)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(ledger.known_total_tokens, 10000)
        self.assertFalse(journal.raw_records[0]["usage"]["original_8000_compatible"])
        self.assertTrue(journal.raw_records[0]["usage"]["experimental_40000_compatible"])
        self.assertEqual(journal.raw_records[0]["reasoning"]["codepoints"], len(hidden))
        self.assertNotIn(hidden, "".join(p.read_text(encoding="utf8") for p in self.root.rglob("*.json")))
        self.assertEqual(result["input_tokens"], 1000)
        self.assertEqual(result["output_tokens"], 9000)
    def test_reasoning_detail_invalid_does_not_destroy_complete_usage(self):
        for value in (-1, "2", True, 21):
            record = usage_receipt({"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30,
                                   "completion_tokens_details": {"reasoning_tokens": value}})
            self.assertEqual(record["status"], "complete")
            self.assertEqual(record["reasoning_tokens_status"], "invalid")
            self.assertIsNone(record["reasoning_tokens"])
        record = usage_receipt({"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})
        self.assertEqual(record["reasoning_tokens_status"], "not_reported")
        self.assertEqual(record["status"], "complete")
        self.assertIsNone(usage_receipt({"prompt_tokens": 10, "completion_tokens": 20})["original_8000_compatible"])
    def test_unknown_usage_and_timeout_stop_before_retry(self):
        for index, response in enumerate((Response({"error": "unknown"}, 500), httpx.ReadTimeout("offline"))):
            p, journal, ledger, client = self.make([response], str(index))
            with self.assertRaises(ExperimentStopped):
                p.evaluate(self.request)
            with self.assertRaises(ExperimentStopped):
                journal.begin_post({})
            self.assertEqual(client.posts, 1)
            self.assertEqual(ledger.unknown_dispatches, 1)
            self.assertIsNone(ledger.summary()["tokens_total"])
    def test_all_immediate_http_stops(self):
        for status in sorted(IMMEDIATE_HTTP_STOP):
            p, journal, ledger, client = self.make([Response(envelope("{}"), status)], str(status))
            with self.assertRaises(ExperimentStopped):
                p.evaluate(self.request)
            self.assertEqual(client.posts, 1)
            self.assertEqual(ledger.stop_reason, "immediate_http_stop_" + str(status))
    def test_known_retry_aggregates_real_usage_and_preserves_last_observed(self):
        for malformed in (False, True):
            responses = [Response(envelope("{}", p=100, c=20), 429),
                         Response(envelope("not-json" if malformed else json.dumps(self.good), p=200, c=30))]
            p, journal, ledger, client = self.make(responses, str(malformed))
            if malformed:
                with self.assertRaises(ProviderInvalidJson) as caught:
                    p.evaluate(self.request)
                result = caught.exception
            else:
                result = p.evaluate(self.request)
            self.assertEqual((result.input_tokens, result.output_tokens), (300, 50))
            self.assertEqual((result.observed_response_input_tokens, result.observed_response_output_tokens), (200, 30))
            self.assertEqual(ledger.known_total_tokens, 350)
            self.assertEqual(client.posts, 2)
    def test_post_and_known_token_caps_admit_before_dispatch(self):
        for index, attr, value in ((0, "post_count", 408), (1, "known_total_tokens", 1500000)):
            p, journal, ledger, client = self.make([], str(index))
            setattr(ledger, attr, value)
            with self.assertRaises(ExperimentStopped):
                p.evaluate(self.request)
            self.assertEqual(client.posts, 0)
        p, journal, ledger, client = self.make([Response(envelope("{}", p=5, c=5), 500)], "overshoot")
        ledger.known_total_tokens = 1499999
        with self.assertRaises(ExperimentStopped):
            p.evaluate(self.request)
        self.assertEqual(client.posts, 1)
        self.assertEqual(ledger.known_total_tokens, 1500009)
    def test_length_not_full_pass_even_with_parseable_json(self):
        for index, content in enumerate((json.dumps(self.good), "not-json")):
            ledger = MatrixLedger(self.root / str(index))
            client = Client([Response(envelope(content, finish="length"))])
            journal, final = _run_trial(ledger, {}, self.case, CONDITIONS[0], "offline", lambda: client)
            folder = ledger.root / "cases/02/flash-off"
            scores = read(folder / "scores.json")
            self.assertEqual(final["status"], "generation_incomplete")
            self.assertTrue(scores["first"]["layers"]["generation"])
            self.assertTrue(scores["final"]["layers"]["generation"])
            self.assertNotEqual(scores["first"]["machine_result"], "pass")
    def test_scoring_error_preserves_trial_finish_and_raw(self):
        ledger = MatrixLedger(self.root)
        client = Client([Response(envelope(json.dumps(self.good)))])
        with patch("evaluation.model_compare_v8.harness.raw_score", side_effect=TypeError("private-message")):
            _run_trial(ledger, {}, self.case, CONDITIONS[0], "offline", lambda: client)
        folder = self.root / "cases/02/flash-off"
        self.assertEqual(read(folder / "scores.json")["first"]["machine_result"], "score_error")
        self.assertTrue((folder / "trial-finish.json").is_file())
        self.assertIsNone(ledger.stop_reason)
        self.assertNotIn("private-message", (folder / "scores.json").read_text())
        broken = {"issues": [{"evidence": [{"span_id": []}]}]}
        self.assertNotEqual(safe_score(raw_score, self.case, broken, self.request)["machine_result"], "pass")
    def test_models_exact_one_get_safe_metadata(self):
        client = Client([Response({"data": [{"id": x, "name": x, "version": "offline", "context_window": 100000,
            "max_output_tokens": 32768, "secret": "never-save"} for x in ("deepseek-flash", "deepseek-v4-pro")]})])
        models_preflight(self.root, "offline", lambda: client)
        self.assertEqual(client.gets, 1)
        self.assertNotIn("never-save", (self.root / "models-finish.json").read_text())
        with self.assertRaises(FileExistsError):
            models_preflight(self.root, "offline", lambda: client)
        self.assertEqual(client.gets, 1)
    def test_bad_shape_and_length_retain_scoring_and_generation(self):
        broken = {"issues": [{"evidence": [{"span_id": []}]}]}
        result = safe_score(raw_score, self.case, broken, self.request, "length")
        self.assertEqual(result["machine_result"], "score_error")
        self.assertEqual(result["layers"]["scoring"], ["TypeError"])
        self.assertIn("generation:finish_reason_length", result["layers"]["generation"])
        self.assertFalse(result["complete_answer"])
    def test_create_only_identity(self):
        with patch("evaluation.model_compare_v8.harness.HERE", self.root):
            reserve("prep-v8-offline", "prepare")
            with self.assertRaises(FileExistsError):
                reserve("prep-v8-offline", "prepare")
            with self.assertRaises(ValueError):
                reserve("../escape", "live")
    def test_v7_all_34_replay_has_same_19_final_pass_and_failures(self):
        result = replay_all()
        self.assertTrue(result["read_hashes_stable"])
        self.assertEqual(result["equivalent_cases"], 34, [r for r in result["cases"] if not r["equivalent"]])
        self.assertEqual(result["adapter_final_pass"], 19)
        self.assertTrue(all(r["request_chain_equal"] for r in result["cases"]))


if __name__ == "__main__":
    unittest.main()
