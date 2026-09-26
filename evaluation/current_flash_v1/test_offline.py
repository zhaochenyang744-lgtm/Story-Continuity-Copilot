"""Small no-network checks required before freezing the real evaluation."""
from __future__ import annotations
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("current_flash_run", HERE / "run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from app.provider import ProviderResult


class OfflineHarnessTest(unittest.TestCase):
    def test_case_identity_and_no_overwrite(self):
        cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
        runner.validate_cases(cases)
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "result.json"
            runner.write_new(path, {"first_failure": True})
            with self.assertRaises(FileExistsError):
                runner.write_new(path, {"replacement": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"first_failure": True})

    def test_real_dispatch_counter_and_unknown_usage(self):
        class FakeClient:
            calls = 0
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def post(self, url, **kwargs):
                FakeClient.calls += 1
                if FakeClient.calls == 1:
                    raise runner.httpx.ReadTimeout("synthetic timeout")
                request = runner.httpx.Request("POST", url)
                return runner.httpx.Response(200, request=request, json={"model": runner.MODEL,
                    "choices": [{"finish_reason": "stop", "message": {"content": "{\"issues\":[]}"}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}})
        with patch.object(runner.httpx, "Client", FakeClient), patch.dict(runner.os.environ,
                {"CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": runner.MODEL,
                 "CONTINUITY_BASE_URL": runner.BASE_URL, "CONTINUITY_API_KEY": "synthetic-test-only"}):
            provider = runner.ObservedProvider()
            provider.case_id = "offline"
            result = provider.evaluate({"draft": {"id": "d", "revision": 1, "body": "test"},
                                        "claims": [], "memory": [], "output_schema": {"issues": []}})
        self.assertEqual(FakeClient.calls, 2)
        self.assertEqual(len(provider.http_events), 2)
        self.assertIsNone(provider.http_events[0]["usage"])
        self.assertEqual(provider.http_events[1]["usage"]["prompt_tokens"], 11)
        self.assertIsNone(result.input_tokens)  # first dispatched attempt has unknown usage
        self.assertEqual(result.observed_response_input_tokens, 11)
        self.assertEqual(provider.parsed[0]["business_json"], {"issues": []})

    def test_isolated_product_paths_with_fake_provider(self):
        class FakeProvider:
            available = True
            label = "offline-fake"
            model_label = "offline-fake"
            parsed = []
            http_events = []
            case_id = "offline"
            def evaluate(self, request):
                task = request.get("task")
                if task == "context_brief":
                    claim = request["layers"]["written"]["draft_claims"][0]
                    source = {"source_type": "draft_claim", "source_id": claim["id"]}
                    payload = {"summary": claim["text"], "summary_sources": [source],
                               "items": [{"section": "recent_source", "text": claim["text"], "sources": [source]}]}
                elif task == "change_impact":
                    payload = {"summary": "仅限直接来源。", "items": []}
                else:
                    payload = {"issues": []}
                self.parsed.append({"case_id": self.case_id, "task": task,
                                    "contract_repair": False, "business_json": payload,
                                    "usage": {}, "latency_ms": 1})
                return ProviderResult(payload, 1, 1, latency_ms=1)
        fake = FakeProvider()
        v8 = json.loads(runner.V8_CASES.read_text(encoding="utf-8"))["cases"][0]
        cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            checkpoint = runner.FormalCheckpoint(root / "checkpoint.json", "offline")
            record = runner.v8_one(v8, fake, root, checkpoint, runner.ApiResponseScanner())
            self.assertEqual(record["product"]["status"], "completed")
            for case in cases["g01"]:
                record = runner.g01_one(case, fake)
                self.assertEqual(record["product"]["status"], "completed")
            for case in cases["g02"]:
                brief = runner.g02_one(case, fake, root / case["id"])
                self.assertEqual(brief["product"]["status"], "completed")
            for case in cases["g03"]:
                impact = runner.g03_one(case, fake, root / case["id"])
                self.assertEqual(impact["product"]["status"], "completed")
                if case["mode"] == "deep":
                    self.assertIn("星钥始终由乔霁保管。", impact["input"]["target_source_body"])


if __name__ == "__main__":
    unittest.main()
