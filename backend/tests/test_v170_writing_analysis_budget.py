"""v1.7.0: writing analyses have their own input allowance (12,000 units) and run-token allowance (16,000)."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import textwrap
import unittest

from app.engine import MAX_RUN_TOKENS, MAX_WRITING_ANALYSIS_RUN_TOKENS, WritingAnalysisEngine
from app.provider import (MAX_INPUT_BUDGET_UNITS, WRITING_ANALYSIS_INPUT_BUDGET_UNITS, ProviderResult, input_budget_units_for,
                          request_prompt_and_budget)

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _data(proposed_change: str) -> dict:
    return {"task": "change_impact", "bindings": {"project_id": "synthetic"}, "proposal": {"target_type": "memory", "target_id": "memory-B", "proposed_change": proposed_change},
            "retrieval": {"target_source": {"status": "selected"}},
            "layers": {"planned": {"story_plans": [], "character_plans": [], "world_plans": []},
                       "confirmed": {"memory_records": [{"id": "memory-B", "subject": "星钥", "predicate": "保管者", "value": "乔霁", "source_span_id": "span-B"}]},
                       "written": {"source_spans": [{"id": "span-B", "chapter_id": "chapter-B", "chapter_number": 2, "label": "保管", "body": "星钥由乔霁保管。"}], "draft_claims": []},
                       "identity": {"characters": [], "aliases": []},
                       "reference": {"chapters": [{"id": "chapter-B", "chapter_number": 2, "title": "保管"}], "world_entries": []}}}


class _Provider:
    available = True
    label = "budget-test-provider"

    def __init__(self, input_tokens: int = 10, output_tokens: int = 5):
        self.calls = 0
        self.tokens = (input_tokens, output_tokens)

    def evaluate(self, request):
        self.calls += 1
        return ProviderResult({"summary": "该修改会影响保管记录。", "items": [{"area": "memory", "target_id": "memory-B", "impact": "需要复核这条事实。",
                                                                         "evidence": [{"source_type": "memory_record", "source_id": "memory-B"}]}]},
                              input_tokens=self.tokens[0], output_tokens=self.tokens[1], latency_ms=1)


class WritingAnalysisBudgetTests(unittest.TestCase):
    def test_the_allowances_are_separate_from_the_shared_ones(self):
        self.assertEqual((MAX_INPUT_BUDGET_UNITS, MAX_RUN_TOKENS), (6000, 8000))
        self.assertEqual((WRITING_ANALYSIS_INPUT_BUDGET_UNITS, MAX_WRITING_ANALYSIS_RUN_TOKENS), (12000, 16000))
        for task in ("context_brief", "plan_alignment", "change_impact", "story_qa", "foreshadow_scan", "revision_plan"):
            self.assertEqual(input_budget_units_for({"task": task}), WRITING_ANALYSIS_INPUT_BUDGET_UNITS, task)
        for task in ("memory_initialization", "memory_delta"):
            self.assertEqual(input_budget_units_for({"task": task}), MAX_INPUT_BUDGET_UNITS, task)

    def test_an_input_between_the_old_and_the_new_allowance_is_accepted(self):
        data = _data("调整保管者。" * 1000)
        units = request_prompt_and_budget(WritingAnalysisEngine(_Provider())._request(data))[1]
        self.assertGreater(units, MAX_INPUT_BUDGET_UNITS)
        self.assertLessEqual(units, WRITING_ANALYSIS_INPUT_BUDGET_UNITS)
        provider = _Provider()
        result = WritingAnalysisEngine(provider).execute(data)
        self.assertEqual((result["status"], provider.calls), ("completed", 1))

    def test_an_input_over_12000_units_is_still_refused_without_calling_the_provider(self):
        data = _data("调整保管者。" * 4000)
        self.assertGreater(request_prompt_and_budget(WritingAnalysisEngine(_Provider())._request(data))[1], WRITING_ANALYSIS_INPUT_BUDGET_UNITS)
        provider = _Provider()
        result = WritingAnalysisEngine(provider).execute(data)
        self.assertEqual((result["status"], result["error_code"], provider.calls), ("failed", "input_budget_exceeded", 0))

    def test_the_run_token_allowance_is_16000_for_a_writing_analysis(self):
        within = WritingAnalysisEngine(_Provider(input_tokens=12000, output_tokens=3000)).execute(_data("调整保管者。"))
        self.assertEqual(within["status"], "completed", "more than the shared 8,000 but within 16,000")
        over = WritingAnalysisEngine(_Provider(input_tokens=13000, output_tokens=3500)).execute(_data("调整保管者。"))
        self.assertEqual((over["status"], over["error_code"]), ("budget_paused", "budget_paused"))


class PublishedSampleAnalysisTests(unittest.TestCase):
    def test_the_sample_work_can_run_all_three_pre_writing_analyses(self):
        # A fresh interpreter without the frozen test fixture, so the published sample work is what gets analysed.
        script = textwrap.dedent("""
            import json, pathlib, tempfile, uuid
            from fastapi.testclient import TestClient
            from app.config import AppPaths
            from app.main import create_app
            from app.provider import ProviderResult, request_prompt_and_budget

            class Provider:
                available = True
                label = "sample-budget-provider"
                def __init__(self): self.units = {}
                def evaluate(self, request):
                    task = request.get("task")
                    self.units[task] = request_prompt_and_budget(request)[1]
                    layers = request["layers"]
                    if task == "context_brief":
                        planned = layers["planned"]["story_plans"]; memory = layers["confirmed"]["memory_records"]
                        source = {"source_type": "author_context", "source_id": planned[0]["id"]} if planned else {"source_type": "memory_record", "source_id": memory[0]["id"]}
                        return ProviderResult({"summary": "写作前先守住既有约束。", "summary_sources": [source], "items": [{"section": "related_plan" if planned else "confirmed_fact", "text": "本章需要延续已绑定的上下文。", "sources": [source]}]}, input_tokens=12, output_tokens=6, latency_ms=2)
                    if task == "plan_alignment":
                        claims = layers["written"]["draft_claims"]
                        return ProviderResult({"summary": "草稿覆盖了当前计划。", "items": [{"story_plan_id": plan["id"], "status": "planned_covered", "explanation": "草稿已直接写到计划动作。", "evidence": [{"source_type": "draft_claim", "source_id": claims[0]["id"]}]} for plan in layers["planned"]["story_plans"]]}, input_tokens=13, output_tokens=7, latency_ms=2)
                    character = layers["identity"]["characters"][0]
                    return ProviderResult({"summary": "该修改会影响角色身份识别。", "items": [{"area": "character", "target_id": character["id"], "impact": "需要复核这个角色的身份指向。", "evidence": [{"source_type": "character_record", "source_id": character["id"]}]}]}, input_tokens=9, output_tokens=5, latency_ms=2)

            root = pathlib.Path(tempfile.mkdtemp(prefix="v170-analysis-budget-"))
            provider = Provider()
            app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=provider, executor=lambda fn, *args: fn(*args))
            client = TestClient(app)
            headers = lambda: {"Idempotency-Key": str(uuid.uuid4())}
            data = client.post("/api/auth/register", headers=headers(), json={
                "account_name": "b" + uuid.uuid4().hex[:8], "display_name": "B", "password": "valid-password-99",
                "recovery_email": uuid.uuid4().hex[:8] + "@example.test"}).json()["data"]
            pid = data["onboarding"]["tutorial"]["project_id"]
            project = client.get(f"/api/projects/{pid}").json()["data"]
            draft = project["current_draft"]
            character = client.get(f"/api/projects/{pid}/characters").json()["data"]["characters"][0]
            out = {}
            for kind in ("context_brief", "plan_alignment", "change_impact"):
                body = {"analysis_type": kind, "draft_id": draft["id"], "draft_revision": draft["revision"]}
                if kind == "change_impact":
                    body["proposal"] = {"target_type": "character", "target_id": character["id"], "proposed_change": "把" + character["name"] + "的身份改成港务调查员。"}
                started = client.post(f"/api/projects/{pid}/analyses", headers=headers(), json=body)
                run = client.get(f"/api/projects/{pid}/analyses/{started.json()['data']['run_id']}").json()["data"] if started.status_code == 202 else {}
                out[kind] = {"http": started.status_code, "status": run.get("status"), "error_code": run.get("error_code")}
            print(json.dumps({"runs": out, "units": provider.units}))
        """)
        env = {key: value for key, value in os.environ.items() if key != "STORY_SAMPLE_WORK_FILE"}
        env.update({"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3000", "BACKEND_ORIGIN": "http://127.0.0.1:8000",
                    "TRUSTED_HOSTS": "127.0.0.1:8000,testserver", "TRUSTED_ORIGINS": "http://127.0.0.1:3000,http://testserver", "PYTHONIOENCODING": "utf-8"})
        result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        report = json.loads(result.stdout.strip().splitlines()[-1])
        for kind in ("context_brief", "plan_alignment", "change_impact"):
            self.assertEqual(report["runs"][kind]["http"], 202, report)
            self.assertNotEqual(report["runs"][kind]["error_code"], "input_budget_exceeded", report)
            self.assertEqual(report["runs"][kind]["status"], "completed", report)
        self.assertTrue(all(units <= WRITING_ANALYSIS_INPUT_BUDGET_UNITS for units in report["units"].values()), report)


if __name__ == "__main__":
    unittest.main()
