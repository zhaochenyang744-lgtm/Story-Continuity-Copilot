"""Bounded no-network checks for capture, dispatch journal, and evaluation layers."""
from __future__ import annotations

import hashlib
import copy
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from evaluation.current_flash_v5 import run
import httpx
from app.provider import ProviderInvalidJson, ProviderTimeout, ProviderResult
from evaluation.current_flash_v5.inputs import InputContract
from evaluation.current_flash_v5.journal import write_x
from evaluation.current_flash_v5.journal import DurableProvider, RunJournal, usage_info
from evaluation.current_contract_compare_v3.score import score_one, score_raw_one

ROOT = pathlib.Path(__file__).resolve().parents[2]
V2 = ROOT / "evaluation/current_contract_compare_v2"
V3 = ROOT / "evaluation/current_contract_compare_v3"


class FakeClient:
    def __init__(self, responder):
        self.responder = responder

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        return self.responder(url, kwargs)


def answer(content: str, usage=None):
    envelope = {"model": "deepseek-flash", "choices": [{"message": {"content": content,
                "reasoning_content": "must-not-persist"}, "finish_reason": "stop"}]}
    if usage is not None:
        envelope["usage"] = usage
    return httpx.Response(200, json=envelope, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"))


class FlashV5OfflineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = json.loads((V2 / "actual-inputs.json").read_text(encoding="utf-8"))["rows"][0]["business_request"]

    def _provider(self, root, responder):
        journal = RunJournal(root, "offline-fake")
        case = journal.case(1, {"family": "comparison", "case_id": "ccv3-north_glass-world_rule-conflict"})
        env = mock.patch.dict("os.environ", {"CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": "deepseek-flash",
                                         "CONTINUITY_BASE_URL": "https://api.deepseek.com", "CONTINUITY_API_KEY": "fake-offline-only"})
        env.start()
        self.addCleanup(env.stop)
        return DurableProvider(case, client_factory=lambda: FakeClient(responder)), case

    def test_pre_dispatch_snapshot_and_bad_json_first_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            def responder(url, kwargs):
                case = root / "cases/01"
                self.assertTrue((case / "requests/01.json").is_file())
                self.assertTrue((case / "attempts/01-start.json").is_file())
                self.assertNotIn("fake-offline-only", (case / "requests/01.json").read_text(encoding="utf-8"))
                return answer("{broken", {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6})
            provider, case = self._provider(root, responder)
            with self.assertRaises(ProviderInvalidJson):
                provider.evaluate(self.request)
            finish = json.loads((case.root / "attempts/01-finish.json").read_text(encoding="utf-8"))
            self.assertEqual(finish["message_content"], "{broken")
            self.assertEqual(finish["usage"]["status"], "complete")
            self.assertNotIn("must-not-persist", (case.root / "attempts/01-finish.json").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((case.root / "evaluations/01.json").read_text(encoding="utf-8"))["error_type"],
                             "ProviderInvalidJson")

    def test_bounded_timeout_and_usage_four_states(self):
        self.assertEqual(usage_info({"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})["status"], "complete")
        self.assertEqual(usage_info({})["status"], "missing")
        self.assertEqual(usage_info({"usage": {"prompt_tokens": 7}})["status"], "partial")
        self.assertEqual(usage_info({"usage": {"prompt_tokens": -1, "completion_tokens": True, "total_tokens": "bad"}})["status"], "unknown")
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            def timeout(url, kwargs):
                raise httpx.ReadTimeout("offline-timeout", request=httpx.Request("POST", url))
            provider, case = self._provider(root, timeout)
            with self.assertRaises(ProviderTimeout):
                provider.evaluate(self.request)
            self.assertEqual(len(list((case.root / "attempts").glob("*-start.json"))), 2)
            ledger = run.usage_ledger(root)
            self.assertEqual(ledger["post_attempt_start_records"], 2)
            self.assertEqual(ledger["usage_counts"]["unknown"], 2)
            self.assertIsNone(ledger["prompt_tokens_total"])

    def test_partial_usage_sum_and_raw_final_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            provider, case = self._provider(root, lambda url, kwargs: answer('{"issues": []}', {"prompt_tokens": 7}))
            provider.evaluate(self.request)
            ledger = run.usage_ledger(root)
            self.assertEqual(ledger["usage_counts"]["partial"], 1)
            self.assertEqual(ledger["known_prompt_tokens_partial_sum"], 7)
            self.assertIsNone(ledger["prompt_tokens_total"])
            self.assertEqual(len(list((case.root / "requests").glob("*.json"))), 1)
            self.assertEqual(len(list((case.root / "evaluations").glob("*.json"))), 1)

    def test_unique_identity_first_failure_and_preparation_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            with mock.patch.object(run, "RESULTS", temp / "runs"), mock.patch.object(run, "WORKSPACES", temp / "work"):
                first, _ = run.reserve("prep-v5-identity")
                sentinel = first / "sentinel.json"
                sentinel.write_text("first", encoding="utf-8")
                before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
                with self.assertRaises(FileExistsError):
                    run.reserve("prep-v5-identity")
                self.assertEqual(hashlib.sha256(sentinel.read_bytes()).hexdigest(), before)
                with mock.patch("evaluation.current_flash_v5.build_cases.build", side_effect=RuntimeError("deliberate-offline-failure")):
                    with self.assertRaises(RuntimeError):
                        run.execute("prepare", "prep-v5-failure")
                self.assertTrue((temp / "runs/prep-v5-failure/first-failure.json").is_file())
                with self.assertRaises(FileExistsError):
                    run.execute("prepare", "prep-v5-failure")
        prepared = run.RESULTS / "prep-v5-03"
        summary = json.loads((prepared / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual((summary["logical_cases_finished"], summary["post_attempt_start_records"]), (30, 0))
        self.assertEqual(len(list((prepared / "cases").glob("[0-9][0-9]/input-audit/01.json"))), 30)
        body = json.loads((prepared / "cases/27/input-audit/01.json").read_text(encoding="utf-8"))
        dialogue = json.loads((prepared / "cases/30/input-audit/01.json").read_text(encoding="utf-8"))
        self.assertEqual((body["draft_chars"], body["claim_available"], body["claim_selected"], body["claim_unselected"]),
                         (1980, 180, 8, 172))
        self.assertTrue(dialogue["dialogue_two_complete_quotes"])

    def test_g02_same_database_rejects_wrong_chapter_and_memory_binding(self):
        prepared = run.RESULTS / "prep-v5-03/cases/30"
        case = next(x for x in json.loads((run.HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
                    if x["case_id"] == "g02-dialogue-attribution")
        bound = json.loads((prepared / "runtime-binding.json").read_text(encoding="utf-8"))
        request = json.loads((prepared / "requests/01.json").read_text(encoding="utf-8"))["business_request"]
        contract = InputContract()
        contract.bind_runtime(case["case_id"], bound)
        self.assertEqual(contract(case, request)["database_binding"], "matched_persisted_isolated_database")
        wrong_chapter = copy.deepcopy(request)
        wrong_chapter["layers"]["written"]["source_spans"][0]["chapter_id"] = "self-consistent-but-wrong-chapter"
        with self.assertRaisesRegex(RuntimeError, "selected_source_database_chapter_body_revision"):
            contract(case, wrong_chapter)
        wrong_memory = copy.deepcopy(request)
        wrong_memory["layers"]["confirmed"]["memory_records"][0]["source_span_id"] = bound["chapters"][-1]["span_id"]
        with self.assertRaisesRegex(RuntimeError, "selected_memory_database_source_binding"):
            contract(case, wrong_memory)

    def test_parseable_malformed_first_case_does_not_stop_next_case(self):
        source_cases = json.loads((run.HERE / "cases.json").read_text(encoding="utf-8"))
        shortened = {**source_cases, "cases": source_cases["cases"][:2]}
        original = run.StubProvider.evaluate
        def malformed_first(self, request):
            if self.journal.ordinal != 1:
                return original(self, request)
            self.journal.begin_evaluation(request)
            audit = self.input_validator(self.journal.case, request)
            write_x(self.journal.root / "input-audit/01.json", audit)
            result = ProviderResult({"issues": [None]}, input_tokens=1, output_tokens=1, latency_ms=1)
            self.journal.finish_evaluation(result)
            return result
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            (temp / "cases.json").write_text(json.dumps(shortened, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(run, "HERE", temp), mock.patch.object(run, "RESULTS", temp / "runs"), \
                 mock.patch.object(run, "WORKSPACES", temp / "work"), \
                 mock.patch("evaluation.current_flash_v5.build_cases.build", return_value=shortened), \
                 mock.patch.object(run.StubProvider, "evaluate", malformed_first):
                run.execute("prepare", "prep-v5-malformed")
            root = temp / "runs/prep-v5-malformed"
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["logical_cases_finished"], 2)
            first_case = root / "cases/01"
            self.assertTrue((first_case / "final-product-unavailable.json").exists() or
                            json.loads((first_case / "final-product.json").read_text(encoding="utf-8"))["status"] == "failed")
            self.assertTrue((root / "cases/02/final-product.json").exists())
            self.assertEqual(json.loads((root / "cases/01/evaluations/01.json").read_text(encoding="utf-8"))
                             ["parsed_business_json"], {"issues": [None]})
            from evaluation.current_flash_v5.score import score_case
            scored = score_case(shortened["cases"][0], first_case,
                                json.loads((first_case / "final-product.json").read_text(encoding="utf-8"))
                                if (first_case / "final-product.json").exists() else None, "live")
            self.assertEqual(scored["first_raw"]["machine_result"], "score_error")

    def test_state_change_manual_and_terminal_controls(self):
        cases = {x["lineage"]["v2_case_id"]: x for x in json.loads((V3 / "cases.json").read_text(encoding="utf-8"))["cases"]}
        rows = json.loads((V2 / "api-score-probe-results-v2.json").read_text(encoding="utf-8"))["rows"]
        for axis in ("character_knowledge", "location_action"):
            row = next(x for x in rows if x["variant"] == "state_change" and f"-{axis}-" in x["case_id"])
            case = cases[row["case_id"]]
            self.assertEqual(score_raw_one(case, row["raw_first"], row["business_request"])["machine_result"], "pass")
            self.assertEqual(score_one(case, row["final_product"], row["business_request"])["machine_result"], "pass")
        companion = next(x for x in rows if x["case_id"].endswith("location_action-insufficient_evidence"))
        result = score_one(cases[companion["case_id"]], companion["final_product"], companion["business_request"])
        self.assertEqual(result["category_status"], "pending_manual_adjudication")
        control = next(x for x in rows if x["case_id"].endswith("timeline-no_conflict"))
        failed = {**control["final_product"], "status": "failed", "issues": []}
        self.assertEqual(score_one(cases[control["case_id"]], failed, control["business_request"])["result"], "terminal_failure")


if __name__ == "__main__":
    unittest.main()
