"""Offline injection tests for the isolated Stage 11M runner and validator."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from app.provider import ProviderResult
import run_stage11m_real_300k as runner
import validate_stage11m_real_300k as validator
import validate_stage11m_capacity_repair_v2 as capacity_validator


class InjectedProvider:
    label = "deepseek"
    model_label = "deepseek-v4-pro"
    api_format_label = "chat-completions-json-object"

    def __init__(self, mode="ok", multiplier=1):
        self.mode = mode
        self.multiplier = multiplier
        self.request_attempts = 0
        self.successful_responses = 0

    @property
    def available(self): return True

    def evaluate(self, request):
        self.request_attempts += self.multiplier
        if self.mode == "schema":
            return ProviderResult({"candidates": [{"invalid": "candidate"}]}, 3, 2, None, 1)
        self.successful_responses += 1
        if "claims" in request:
            return ProviderResult({"issues": []}, 3, 2, None, 1)
        source = request["sources"][0]
        return ProviderResult({"candidates": [{"memory_type": "dynamic_state", "subject": "测试作者", "predicate": "status", "value": f"受控状态{self.request_attempts}", "chapter_id": source["chapter_id"], "source_span_id": source["id"]}]}, 3, 2, None, 1)


class Stage11MRunnerTests(unittest.TestCase):
    plan = {"parent_source_spans": 13, "source_chunks": 82, "initialization_batches": 81, "max_normal_input_budget": 5800, "max_repair_input_budget": 5938}

    def _success(self):
        with tempfile.TemporaryDirectory(prefix="scc-11m-ok-") as directory, patch.object(runner, "_plan_metrics", return_value=self.plan):
            return runner.formal_run("# 第一章\n受控测试文本。", pathlib.Path(directory), InjectedProvider())

    def _result(self):
        result = runner._base(runner.EXPECTED_CONTAINER_SHA256, runner.EXPECTED_SHA256, 300000, 862721)
        result["provider_model_label"] = "deepseek-v4-pro"
        result.update(self._success())
        result["initialization_metrics"]["total_batches"] = 81
        result["initialization_metrics"]["validated_batches"] = 81
        return result

    def test_injected_success_is_validator_compatible(self):
        result = self._result()
        self.assertEqual(result["status"], "completed_pending_independent_gate")
        self.assertTrue(validator.validate_result(result))

    def test_capacity_repair_validator_requires_bounded_idempotency(self):
        result=self._result()
        result["evidence_id"]="real-novel-300k-11m-v2"
        result["capacity_repair_contract"]="bounded-write-responses-v1"
        self.assertTrue(capacity_validator.validate_result(result))
        result["idempotency_metrics"]["candidate_decision_max_response_json_bytes"]=2049
        self.assertFalse(capacity_validator.validate_result(result))

    def test_schema_failure_stops_before_commit(self):
        with tempfile.TemporaryDirectory(prefix="scc-11m-schema-") as directory, patch.object(runner, "_plan_metrics", return_value=self.plan):
            with self.assertRaisesRegex(runner.RunFailure, "candidate_fields_invalid"):
                runner.formal_run("# 第一章\n受控测试文本。", pathlib.Path(directory), InjectedProvider("schema"))

    def test_non_pro_and_http_cap_are_closed(self):
        provider = InjectedProvider(); provider.model_label = "deepseek-v4-flash"
        with tempfile.TemporaryDirectory(prefix="scc-11m-model-") as directory:
            with self.assertRaisesRegex(runner.RunFailure, "provider_model_not_pro"):
                runner.formal_run("x", pathlib.Path(directory), provider)
        with tempfile.TemporaryDirectory(prefix="scc-11m-cap-") as directory, patch.object(runner, "_plan_metrics", return_value=self.plan):
            with self.assertRaisesRegex(runner.RunFailure, "provider_http_cap_exceeded"):
                runner.formal_run("# 第一章\n受控测试文本。", pathlib.Path(directory), InjectedProvider(multiplier=100))

    def test_duplicate_writer_and_sensitive_result_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="scc-11m-result-") as directory:
            path = pathlib.Path(directory) / "results.json"
            runner._write_once(path, {"status": "gate_failed"})
            with self.assertRaisesRegex(runner.RunFailure, "formal_result_already_exists"):
                runner._write_once(path, {"status": "gate_failed"})
        result = self._result()
        result["source_path"] = "forbidden"
        self.assertFalse(validator.validate_result(result))


if __name__ == "__main__":
    unittest.main()
