"""No-network validation of v2 accounting, stop rules, snapshots and G03 fixtures."""
from __future__ import annotations
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("current_flash_v2_run", HERE / "run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from app.provider import ProviderResult


class OfflineHarnessTest(unittest.TestCase):
    def test_usage_completeness_and_partial_sums(self):
        cases = [
            (None, "unknown"), ({}, "unknown"), ({"prompt_tokens": 11}, "partial"),
            ({"prompt_tokens": 11, "completion_tokens": 7}, "partial"),
            ({"prompt_tokens": -1, "completion_tokens": 7, "total_tokens": 18}, "partial"),
            ({"prompt_tokens": None, "completion_tokens": 7, "total_tokens": 18}, "partial"),
            ({"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 19}, "partial"),
            ({"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}, "complete"),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                observed, status, invalid = runner.usage_metadata(body)
                self.assertEqual(status, expected)
                if expected == "complete":
                    self.assertEqual(observed["prompt_tokens"], 11)
                    self.assertFalse(invalid)
                else:
                    self.assertTrue(invalid)

    def test_observer_partial_usage_and_no_overwrite(self):
        class FakeResponse:
            status_code = 200
            def json(self): return {"model": runner.MODEL, "usage": {"prompt_tokens": 11}, "choices": []}
        class FakeClient:
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def post(self, *args, **kwargs): return FakeResponse()
        with patch.object(runner.httpx, "Client", FakeClient):
            provider = runner.ObservedProvider()
            provider.case_id = "offline"
            with runner.ObservedClient(provider) as client:
                client.post("offline://no-network")
        event = provider.http_events[0]
        self.assertEqual(event["usage_status"], "partial")
        self.assertEqual(event["usage"]["prompt_tokens"], 11)
        self.assertIsNone(event["usage"]["completion_tokens"])
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "first.json"
            runner.write_new(path, {"first": True})
            with self.assertRaises(FileExistsError):
                runner.write_new(path, {"second": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"first": True})

    def test_business_failure_not_a_service_stop(self):
        business = {"product": {"status": "failed", "error_code": "evidence_unresolvable"},
                    "http_attempts": [{"status": 200, "error_type": None}]}
        service = {"product": {"status": "failed", "error_code": "provider_error"},
                   "http_attempts": [{"status": 503, "error_type": None}]}
        self.assertFalse(runner.service_failure(business))
        self.assertTrue(runner.service_failure(service))
        count = 0
        for record in (business, business, service, business, service, service):
            count = count + 1 if runner.service_failure(record) else 0
            if record is business:
                self.assertEqual(count, 0)
        self.assertEqual(count, 2)

    def test_all_eight_isolated_inputs_and_actual_business_snapshots(self):
        cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
        runner.validate_cases(cases)

        def fake_evaluate(self, request):
            if request.get("task") == "context_brief":
                first = request["layers"]["written"]["draft_claims"][0]
                src = {"source_type": "draft_claim", "source_id": first["id"]}
                payload = {"summary": first["text"], "summary_sources": [src],
                           "items": [{"section": "recent_source", "text": first["text"], "sources": [src]}]}
            else:
                payload = {"summary": "仅限所列证据。", "items": []}
            return ProviderResult(payload, 1, 1, latency_ms=1)

        with patch.dict(runner.os.environ, {"CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": runner.MODEL,
                                               "CONTINUITY_BASE_URL": runner.BASE_URL, "CONTINUITY_API_KEY": "offline-test-only"}), \
             patch.object(runner.DeepSeekProvider, "evaluate", fake_evaluate):
            provider = runner.ObservedProvider()
            with tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                for case in cases["g02"]:
                    result = runner.g02_one(case, provider, root / case["id"])
                    self.assertEqual(result["product"]["status"], "completed")
                    self.assertEqual(len(result["business_requests"]), 1)
                    business = result["business_requests"][0]["business_request"]
                    self.assertIn("confirmed", business["layers"])
                    self.assertIn("planned", business["layers"])
                    self.assertIn("draft", business["layers"]["written"])
                    self.assertIn("output_schema", business)
                for case in cases["g03"]:
                    result = runner.g03_one(case, provider, root / case["id"])
                    self.assertEqual(result["product"]["status"], "completed")
                    self.assertEqual(len(result["business_requests"]), 1)
                    runner.assert_business_input(case, result["business_requests"][0]["business_request"])
                    if case["mode"] == "other_chapter":
                        spans = result["business_requests"][0]["business_request"]["layers"]["written"]["source_spans"]
                        self.assertTrue(any(case["other_body"] in x["body"] for x in spans))


if __name__ == "__main__":
    unittest.main()
