"""Bounded transport fakes for the V10 harness; never use real HTTP or DB."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from unittest.mock import patch

import httpx
import app.engine as engine_module
from app.provider import CONTINUITY_PROMPT_VERSION, MAX_ISSUE_REASONING_CODEPOINTS, ProviderInvalidJson, request_prompt_and_budget
from evaluation.model_compare_v10.config import *
from evaluation.model_compare_v10.harness import (FrozenInputEngine, _run_trial, experimental_budget,
    models_preflight, reserve)
from evaluation.model_compare_v10.journal import (ExperimentStopped, GenerationIncomplete, MatrixLedger,
    TrialJournal, usage_receipt)
from evaluation.model_compare_v10.provider import ExperimentProvider, body_for
from evaluation.model_compare_v10.score import safe_score, raw_score


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
        self.assertEqual(len(items), 108)
        self.assertEqual([r["condition_id"] for r in items[:6]],
            ["flash-high", "pro-high", "pro-high", "flash-high", "flash-high", "pro-high"])
        for case in cases():
            request = request_for(case)
            self.assertLessEqual(request_prompt_and_budget(request)[1], 6000)
            prompts = []
            for condition in CONDITIONS:
                body = body_for(request, condition)
                self.assertEqual(body["max_tokens"], 32768)
                self.assertNotIn("top_p", body)
                self.assertNotIn("temperature", body)
                self.assertEqual((body["thinking"], body["reasoning_effort"]), ({"type": "enabled"}, "high"))
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
        for index, attr, value in ((0, "post_count", MAX_POST), (1, "known_total_tokens", KNOWN_TOKEN_CAP)):
            p, journal, ledger, client = self.make([], str(index))
            setattr(ledger, attr, value)
            with self.assertRaises(ExperimentStopped):
                p.evaluate(self.request)
            self.assertEqual(client.posts, 0)
        p, journal, ledger, client = self.make([Response(envelope("{}", p=5, c=5), 500)], "overshoot")
        ledger.known_total_tokens = KNOWN_TOKEN_CAP - 1
        with self.assertRaises(ExperimentStopped):
            p.evaluate(self.request)
        self.assertEqual(client.posts, 1)
        self.assertEqual(ledger.known_total_tokens, KNOWN_TOKEN_CAP + 9)
    def test_length_not_full_pass_even_with_parseable_json(self):
        for index, content in enumerate((json.dumps(self.good), "not-json")):
            ledger = MatrixLedger(self.root / str(index))
            client = Client([Response(envelope(content, finish="length"))])
            journal, final = _run_trial(ledger, {}, self.case, CONDITIONS[0], "offline", lambda: client)
            folder = ledger.root / "cases/02/flash-high"
            scores = read(folder / "scores.json")
            self.assertEqual(final["status"], "generation_incomplete")
            self.assertTrue(scores["first"]["layers"]["generation"])
            self.assertTrue(scores["final"]["layers"]["generation"])
            self.assertNotEqual(scores["first"]["machine_result"], "pass")
    def test_scoring_error_preserves_trial_finish_and_raw(self):
        ledger = MatrixLedger(self.root)
        client = Client([Response(envelope(json.dumps(self.good)))])
        with patch("evaluation.model_compare_v10.harness.raw_score", side_effect=TypeError("private-message")):
            _run_trial(ledger, {}, self.case, CONDITIONS[0], "offline", lambda: client)
        folder = self.root / "cases/02/flash-high"
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
        with patch("evaluation.model_compare_v10.harness.HERE", self.root):
            reserve("prep-v10-offline", "prepare")
            with self.assertRaises(FileExistsError):
                reserve("prep-v10-offline", "prepare")
            with self.assertRaises(ValueError):
                reserve("../escape", "live")
    def test_v7_inputs_differ_from_v7_only_by_current_schema(self):
        for case in cases()[:34]:
            v7 = read(PREPARED / "cases" / f"{case['ordinal']:02d}" / "requests/01.json")["business_request"]
            current = request_for(case)
            self.assertEqual({k: v for k, v in current.items() if k != "output_schema"},
                             {k: v for k, v in v7.items() if k != "output_schema"})
            self.assertIn(str(MAX_ISSUE_REASONING_CODEPOINTS), current["output_schema"]["issues"][0]["reasoning"])
    def test_prompt_is_v19_with_decisive_fact_category_rule(self):
        prompt = json.loads(body_for(self.request, CONDITIONS[0])["messages"][0]["content"])
        self.assertEqual((prompt["prompt_version"], CONTINUITY_PROMPT_VERSION), (PROMPT_VERSION, PROMPT_VERSION))
        rule = next(r for r in prompt["rules"] if r.startswith("Every emitted issue must include a valid category"))
        for phrase in ("decisive fact", "the missing link is attribution", "does not turn such a property into object_state",
                       "A rule that only defines what counts as ready, complete, or permitted is a premise"):
            self.assertIn(phrase, rule)
    def test_controls_are_new_complete_and_leak_no_gold(self):
        items = [c for c in cases() if is_control(c)]
        self.assertEqual([c["ordinal"] for c in items], list(range(35, 55)))
        seen_text = json.dumps([request_for(c) for c in cases()[:34]], ensure_ascii=False)
        for case in items:
            request = request_for(case)
            self.assertLessEqual(request_prompt_and_budget(request)[1], 6000)
            # Memory types/predicates are product enums; check free text and ids for gold leakage.
            claim = request["claims"][0]
            free_text = json.dumps([request["draft"], claim["id"], claim["text"], claim["allowed_evidence"],
                                    [(m["id"], m["subject"], m["value"]) for m in request["memory"]]], ensure_ascii=False)
            for leaked in ("expected", "rationale", "probe", case["control"]["expected"]["category"] or "no_issue",
                           case["control"]["expected"]["outcome"]):
                self.assertNotIn(leaked, free_text)
            self.assertNotIn(case["control"]["claim"], seen_text)
            self.assertEqual(request_for(case), request_for(case))
    def test_every_control_gold_is_achievable_and_wrong_category_is_caught(self):
        from app.engine import ContinuityEngine
        for case in (c for c in cases() if is_control(c)):
            with self.subTest(control=case["case_id"]):
                request = request_for(case)
                gold = gold_answer(case["control"], request)
                ContinuityEngine(ScoringStub()).validate(copy.deepcopy(gold), request)
                scored = safe_score(raw_score, case, gold, request)
                self.assertEqual(scored["machine_result"], "pass", scored)
                if gold["issues"]:
                    wrong = copy.deepcopy(gold)
                    wrong["issues"][0]["category"] = "event_status" if gold["issues"][0]["category"] != "event_status" else "relationship"
                    self.assertIn("category_mismatch", safe_score(raw_score, case, wrong, request)["errors"])
    def test_control_policy_swap_is_restored_even_on_error(self):
        import evaluation.current_flash_v7.score as v7_score
        from evaluation.model_compare_v10.score import case_policy
        original = v7_score.policy
        control = next(c for c in cases() if is_control(c))
        with self.assertRaises(RuntimeError):
            with case_policy(control):
                self.assertIsNot(v7_score.policy, original)
                raise RuntimeError("sentinel")
        self.assertIs(v7_score.policy, original)


class ScoringStub:
    continuity_contract_version = "v6"


def gold_answer(control, request):
    """Build the structurally correct answer implied by the frozen expected fields."""
    expected = control["expected"]
    claim = request["claims"][0]
    zh = control["language"] == "zh"
    if expected["outcome"] == "no_issue":
        return {"issues": [], "claim_verdicts": [{"claim_span_id": claim["id"], "verdict": "no_issue",
                                                  "basis": "材料直接支持该主张。" if zh else "The supplied record directly supports the claim."}]}
    by_label = {span["label"]: span for span in claim["allowed_evidence"]}
    labels = list(dict.fromkeys(expected["required"][-1]))
    premises = set(expected.get("premises", []))
    insufficient = expected["outcome"] == "insufficient_evidence"
    evidence, chain = [], []
    for label in labels:
        span = by_label[label]
        relation = "context" if insufficient or label in premises else "contradicts"
        rule_memory = [m["id"] for m in request["memory"] if m["source_span_id"] == span["id"]
                       and m["memory_type"] == "static_canon" and m["predicate"] == "rule"]
        evidence.append({"chapter_id": span["chapter_id"], "span_id": span["id"], "relation": relation,
                         "sufficiency": "insufficient" if insufficient else "sufficient", "related_memory_ids": rule_memory})
        chain.append({"span_id": span["id"], "role": "missing_link" if insufficient else "prior_state"})
    anchors = expected.get("anchors")
    temporal = ({"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"} if insufficient else
                {"claim_anchor": anchors[0], "evidence_anchor": anchors[1], "relation": "explicit_overlap"} if anchors else
                {"claim_anchor": None, "evidence_anchor": None, "relation": "timeless_rule"})
    text = "记录与主张不一致。" if zh else "The cited record does not support the claim."
    issue = {"claim_span_id": claim["id"], "status": "insufficient_evidence" if insufficient else "conflict",
             "nature": "insufficient_evidence" if insufficient else "confirmed_conflict",
             "category": expected["category"], "severity": "medium", "explanation": text, "reasoning": text,
             "temporal_basis": temporal, "evidence": evidence, "evidence_chain": chain,
             "suggested_revision": None, "available_actions": [] if insufficient else ["edit"], "proposed_memory_change": None}
    verdict = "insufficient_evidence" if insufficient else "reviewed_issue"
    return {"issues": [issue], "claim_verdicts": [{"claim_span_id": claim["id"], "verdict": verdict, "basis": text}]}


if __name__ == "__main__":
    unittest.main()
