"""No-network V4 input and product path preflight."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from evaluation.current_flash_v4 import run as runner
from app.provider import ProviderResult

HERE = pathlib.Path(__file__).resolve().parent


class OfflineHarnessTest(unittest.TestCase):
    def test_case_lineage_and_create_only(self):
        cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
        runner.validate_cases(cases)
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "result.json"
            runner.prior.write_new(path, {"first": True})
            with self.assertRaises(FileExistsError):
                runner.prior.write_new(path, {"second": True})

    def test_six_isolated_requests_and_source_rendering(self):
        cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["g02"]

        def fake_evaluate(self, request):
            claims = request["layers"]["written"]["draft_claims"]
            first = claims[0]
            citation = {"source_type": "draft_claim", "source_id": first["id"]}
            payload = {"summary": "Unsupported invented summary", "summary_sources": [citation],
                       "items": [{"section": "recent_source", "text": first["text"], "sources": [citation]}]}
            return ProviderResult(payload, 3, 2, latency_ms=1)

        with patch.dict(runner.prior.os.environ, {"CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": runner.prior.MODEL,
                                                "CONTINUITY_BASE_URL": runner.prior.BASE_URL,
                                                "CONTINUITY_API_KEY": "offline-test-only"}), \
             patch.object(runner.prior.DeepSeekProvider, "evaluate", fake_evaluate):
            provider = runner.prior.ObservedProvider()
            with tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                for case in cases:
                    with self.subTest(case=case["id"]):
                        record = runner.prior.g02_one(case, provider, root / case["id"])
                        self.assertEqual(record["product"]["status"], "completed")
                        self.assertEqual(len(record["business_requests"]), 1)
                        self.assertEqual(len(record["model_outputs"]), 1)
                        self.assertEqual(len(record["http_attempts"]), 0)
                        self.assertTrue(record["product"]["analysis"]["items"])
                        self.assertTrue(record["product"]["analysis"]["summary_sources"])
                        self.assertNotIn("Unsupported invented summary", record["product"]["analysis"]["summary"])
                        self.assertFalse(record["product"]["analysis"]["citation_transform"]["model_summary_used"])
                        request = record["business_requests"][0]["business_request"]
                        self.assertEqual(request["task"], "context_brief")
                        self.assertEqual(request["layers"]["written"]["draft_claims"][0]["text"],
                                         runner.prior.case_body(case)[:len(request["layers"]["written"]["draft_claims"][0]["text"])])
                        if case["id"] == "g02-long-sentence":
                            tail = "最后把银钥匙交给陈澈并得知弟弟还活着"
                            self.assertIn(tail, request["layers"]["written"]["draft_claims"][0]["text"])
                            self.assertIn(tail, record["product"]["analysis"]["items"][0]["text"])


if __name__ == "__main__":
    unittest.main()
