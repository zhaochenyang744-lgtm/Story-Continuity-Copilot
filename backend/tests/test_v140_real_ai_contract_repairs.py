from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient
from app.config import AppPaths
from app.engine import ContinuityContractValidationError, ContinuityEngine, MemoryInitializationEngine, WritingAnalysisEngine
from app.main import create_app
from app.provider import (
    ProviderResult,
    continuity_prompt,
    context_brief_prompt,
    foreshadow_scan_prompt,
    memory_initialization_prompt,
    plan_alignment_prompt,
)


class ResultProvider:
    available = True
    label = "contract-test"
    model_label = "contract-test-model"

    def __init__(self, payload):
        self.payload = payload

    def evaluate(self, _request):
        return ProviderResult(
            self.payload,
            input_tokens=1315,
            output_tokens=794,
            latency_ms=4369,
            cost_cny=None,
        )


def analysis_data() -> dict:
    return {
        "task": "context_brief",
        "bindings": {"project_id": "project-1"},
        "layers": {
            "planned": {"story_plans": [], "character_plans": [], "world_plans": []},
            "confirmed": {"memory_records": []},
            "written": {
                "draft": {"id": "draft-1", "excerpt": "暴风雨尚未到来。"},
                "draft_claims": [{"id": "claim-1", "ordinal": 1, "text": "暴风雨尚未到来。"}],
                "source_spans": [
                    {
                        "id": "span-1",
                        "chapter_id": "chapter-1",
                        "chapter_number": 1,
                        "chapter_title": "第一章",
                        "label": "导入章节",
                        "body": "银钥匙由林默保管。",
                    }
                ],
            },
        },
        "retrieval": {},
    }


class RealAiContractRepairTests(unittest.TestCase):
    def test_memory_prompt_separates_memory_type_from_predicate_in_normal_and_repair_calls(self):
        source = {
            "id": "span-1",
            "chapter_id": "chapter-1",
            "chapter_number": 1,
            "chapter_title": "第一章",
            "label": "导入章节",
            "body": "钥匙目前由守门人保管。",
        }
        request = MemoryInitializationEngine(ResultProvider({}))._request([source], 1)
        normal = json.loads(memory_initialization_prompt(request))
        self.assertEqual(
            normal["field_contract"]["memory_type"]["allowed_values"],
            ["static_canon", "dynamic_state", "event_timeline", "character_knowledge", "open_thread"],
        )
        possession = next(item for item in normal["field_contract"]["examples"] if item["predicate"] == "possession")
        self.assertEqual(possession["memory_type"], "dynamic_state")
        self.assertIn("possession", normal["field_contract"]["predicate"]["allowed_values"])
        self.assertIn("dynamic_state", normal["output_schema"]["candidates"][0]["memory_type"])

        repaired = json.loads(
            memory_initialization_prompt(
                {**request, "schema_repair": {"attempt": 1, "global_attempt": 1, "reason_code": "memory_type_invalid", "field": "memory_type", "candidate_ordinal": 1}}
            )
        )
        instruction = repaired["schema_repair"]["instruction"]
        self.assertIn("copy memory_type", instruction)
        self.assertIn("possession and rule are predicates", instruction)

    def test_context_brief_contract_declares_counts_and_accepts_current_draft_claim(self):
        data = analysis_data()
        engine = WritingAnalysisEngine(ResultProvider({}))
        prompt = json.loads(context_brief_prompt(engine._request(data)))
        self.assertTrue(any("1-3 summary_sources" in rule for rule in prompt["rules"]))
        self.assertTrue(any("current saved draft" in rule and "draft_claim" in rule for rule in prompt["rules"]))
        self.assertTrue(any("summary_sources must directly support every factual clause" in rule for rule in prompt["rules"]))
        self.assertEqual(set(prompt["output_schema"]), {"summary", "summary_sources", "items"})
        self.assertEqual(prompt["output_limits"]["summary_sources"], {"min": 1, "max": 3})
        payload = {
            "summary": "暴风雨尚未到来。",
            "summary_sources": [{"source_type": "draft_claim", "source_id": "claim-1"}],
            "items": [
                {
                    "section": "recent_source",
                    "text": "当前草稿写明暴风雨尚未到来。",
                    "sources": [{"source_type": "draft_claim", "source_id": "claim-1"}],
                }
            ],
        }
        cleaned = engine.validate(payload, data)
        self.assertEqual(cleaned["items"][0]["sources"][0]["source_path"], "/projects/project-1/workspace#draft-source")

    def test_context_brief_accepts_legal_recent_prior_chapter_source_span_when_claims_exist(self):
        data = analysis_data()
        payload = {
            "summary": "银钥匙由林默保管。",
            "summary_sources": [{"source_type": "source_span", "source_id": "span-1"}],
            "items": [
                {
                    "section": "recent_source",
                    "text": "上一章写明银钥匙由林默保管。",
                    "sources": [{"source_type": "source_span", "source_id": "span-1"}],
                }
            ],
        }
        cleaned = WritingAnalysisEngine(ResultProvider({})).validate(payload, data)
        self.assertEqual(cleaned["items"][0]["sources"][0]["source_path"], "/projects/project-1/sources#span-span-1")

    def test_schema_failure_preserves_real_provider_usage(self):
        result = WritingAnalysisEngine(ResultProvider({"summary": "missing required keys"})).execute(analysis_data())
        self.assertEqual((result["status"], result["error_code"]), ("failed", "schema_invalid"))
        self.assertEqual(
            (result["input_tokens"], result["output_tokens"], result["latency_ms"], result["cost_cny"]),
            (1315, 794, 4369, None),
        )

    def test_provider_value_error_before_result_does_not_mask_as_unbound_local(self):
        class RaisingProvider(ResultProvider):
            def evaluate(self, _request):
                raise ValueError("schema_invalid")

        result = WritingAnalysisEngine(RaisingProvider({})).execute(analysis_data())
        self.assertEqual(result, {"status": "failed", "error_code": "schema_invalid", "retryable": True})

    def test_context_brief_accepts_equivalent_independent_sources_for_summary_and_item(self):
        data = analysis_data()
        data["layers"]["confirmed"]["memory_records"] = [
            {"id": "memory-1", "subject": "银钥匙", "predicate": "possession", "value": "银钥匙由林默保管。"}
        ]
        payload = {
            "summary": "银钥匙由林默保管。",
            "summary_sources": [{"source_type": "memory_record", "source_id": "memory-1"}],
            "items": [
                {"section": "confirmed_fact", "text": "银钥匙由林默保管。", "sources": [{"source_type": "source_span", "source_id": "span-1"}]},
            ],
        }
        cleaned = WritingAnalysisEngine(ResultProvider({})).validate(payload, data)
        self.assertEqual(cleaned["summary_sources"][0]["source_type"], "source_span")
        self.assertEqual(cleaned["summary"], cleaned["items"][0]["text"])
        self.assertEqual(cleaned["items"][0]["sources"][0]["source_type"], "source_span")

    def test_context_brief_uses_nonfactual_fallback_when_one_legal_item_needs_four_sources(self):
        data = analysis_data()
        data["layers"]["written"]["source_spans"] = [
            {**data["layers"]["written"]["source_spans"][0], "id": f"span-{index}", "body": f"来源 {index}。"}
            for index in range(1, 5)
        ]
        sources = [{"source_type": "source_span", "source_id": f"span-{index}"} for index in range(1, 5)]
        long_text = "四条来源共同支持这一分项。" * 25
        payload = {"summary": "模型摘要不应被采用。", "summary_sources": sources[:3], "items": [{"section": "recent_source", "text": long_text, "sources": sources}]}
        cleaned = WritingAnalysisEngine(ResultProvider({})).validate(payload, data)
        self.assertIn("具体事实与引用见分项", cleaned["summary"])
        self.assertNotIn("四条来源共同支持", cleaned["summary"])
        self.assertEqual(len(cleaned["summary_sources"]), 3)
        self.assertEqual(cleaned["items"][0]["text"], long_text)

    def test_continuity_prompt_forbids_invented_same_time_and_requires_draft_language(self):
        request = {"draft": {"body": "第四章。"}, "claims": [], "memory": [], "output_schema": {"issues": []}}
        rules = " ".join(json.loads(continuity_prompt(request))["rules"])
        self.assertIn("dominant language of the bound draft", rules)
        self.assertIn("Never invent a same-time link", rules)
        self.assertIn("narrative position only", rules)
        self.assertIn("flashback", rules)
        self.assertIn("temporal_basis", rules)

    def test_continuity_contract_rejects_unproven_time_overlap_and_repairs_once(self):
        data = {
            "draft": {"id": "draft-1", "revision": 2, "body": "林默熟练地打开北堤门。"},
            "claims": [{"id": "claim-1", "text": "林默熟练地打开北堤门。", "allowed_evidence": [{"id": "span-1", "chapter_id": "chapter-1", "body": "林默从未去过北堤。"}]}],
            "memory": [{"id": "memory-1", "memory_type": "character_knowledge", "subject": "林默", "predicate": "knowledge", "value": "从未去过北堤", "source_span_id": "span-1"}],
        }
        first = {"issues": [{
            "claim_span_id": "claim-1", "status": "conflict", "nature": "confirmed_conflict", "category": "character_knowledge", "severity": "high",
            "explanation": "Claim conflicts with prior knowledge.", "reasoning": "Both are true at the current narrative time.",
            "temporal_basis": {"claim_anchor": "打开北堤门", "evidence_anchor": "从未去过北堤", "relation": "explicit_overlap"},
            "evidence": [{"chapter_id": "chapter-1", "span_id": "span-1", "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": ["memory-1"]}],
            "evidence_chain": [{"span_id": "span-1", "role": "prior_state"}], "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
        }]}
        second = {"issues": [{
            "claim_span_id": "claim-1", "status": "insufficient_evidence", "nature": "insufficient_evidence", "category": "character_knowledge", "severity": "medium",
            "explanation": "缺少林默学习开门方法的过程。", "reasoning": "既有材料只说明较早的未知状态，没有提供后续学习事件。",
            "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
            "evidence": [{"chapter_id": "chapter-1", "span_id": "span-1", "relation": "context", "sufficiency": "insufficient", "related_memory_ids": ["memory-1"]}],
            "evidence_chain": [{"span_id": "span-1", "role": "missing_link"}], "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
        }]}

        class RepairProvider:
            available = True
            label = "repair"
            model_label = "repair"

            def __init__(self):
                self.requests = []

            def evaluate(self, request):
                self.requests.append(request)
                return ProviderResult(first if len(self.requests) == 1 else second, input_tokens=10, output_tokens=10, latency_ms=1)

        provider = RepairProvider()
        result = ContinuityEngine(provider).execute(data)
        self.assertEqual((result["status"], result["issues"][0]["nature"], len(provider.requests)), ("completed", "insufficient_evidence", 2))
        self.assertEqual(provider.requests[1]["contract_repair"]["reason_code"], "author_language_mismatch")
        diagnostic = provider.requests[1]["contract_repair"]["diagnostics"][0]
        self.assertEqual(diagnostic["claim_span_id"], "claim-1")
        self.assertEqual(diagnostic["problem_codes"], ["author_language_mismatch", "temporal_overlap_unproven"])
        self.assertEqual(provider.requests[1]["contract_repair"]["rejected_issues"], first["issues"])
        repair_prompt = json.loads(continuity_prompt(provider.requests[1]))["contract_repair"]
        self.assertEqual(repair_prompt["diagnostics"], provider.requests[1]["contract_repair"]["diagnostics"])
        self.assertEqual(repair_prompt["rejected_issues"], first["issues"])
        self.assertIn("correct every problem_code", repair_prompt["instruction"])

    def test_continuity_contract_rejects_two_different_explicit_clock_times(self):
        data = {
            "draft": {"id": "draft-1", "revision": 2, "body": "二十点，林默打开北门。"},
            "claims": [{"id": "claim-1", "text": "二十点，林默打开北门。", "allowed_evidence": [{"id": "span-1", "chapter_id": "chapter-1", "body": "二十一点，北门仍然关闭。", "prompt_excerpt": "二十一点，北门仍然关闭。"}]}],
            "memory": [],
        }
        payload = {"issues": [{
            "claim_span_id": "claim-1", "status": "conflict", "nature": "confirmed_conflict", "category": "timeline", "severity": "high",
            "explanation": "两个状态冲突。", "reasoning": "声称两个时间属于同一时刻。",
            "temporal_basis": {"claim_anchor": "二十点", "evidence_anchor": "二十一点", "relation": "explicit_overlap"},
            "evidence": [{"chapter_id": "chapter-1", "span_id": "span-1", "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []}],
            "evidence_chain": [{"span_id": "span-1", "role": "prior_state"}], "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
        }]}
        with self.assertRaisesRegex(ContinuityContractValidationError, "temporal_overlap_unproven"):
            ContinuityEngine(ResultProvider({})).validate(payload, data)

        for claim_anchor, evidence_anchor in (
            ("2026年9月8日20点", "2026年9月8日21点"),
            ("9月8日20点", "9月9日20点"),
        ):
            payload["issues"][0]["temporal_basis"] = {"claim_anchor": claim_anchor, "evidence_anchor": evidence_anchor, "relation": "explicit_overlap"}
            data["claims"][0]["text"] = f"{claim_anchor}，林默打开北门。"
            data["claims"][0]["allowed_evidence"][0]["body"] = f"{evidence_anchor}，北门仍然关闭。"
            data["claims"][0]["allowed_evidence"][0]["prompt_excerpt"] = f"{evidence_anchor}，北门仍然关闭。"
            with self.assertRaisesRegex(ContinuityContractValidationError, "temporal_overlap_unproven"):
                ContinuityEngine(ResultProvider({})).validate(payload, data)

        payload["issues"][0]["temporal_basis"] = {"claim_anchor": "2026年9月8日20点", "evidence_anchor": "2026年9月8日20点", "relation": "explicit_overlap"}
        data["claims"][0]["text"] = "2026年9月8日20点，林默打开北门。"
        data["claims"][0]["allowed_evidence"][0]["body"] = "2026年9月8日20点，北门仍然关闭。"
        data["claims"][0]["allowed_evidence"][0]["prompt_excerpt"] = "2026年9月8日20点，北门仍然关闭。"
        self.assertEqual(ContinuityEngine(ResultProvider({})).validate(payload, data)[0]["nature"], "confirmed_conflict")

    def test_continuity_repair_diagnostics_tolerate_null_evidence(self):
        data = {
            "draft": {"id": "draft-1", "revision": 2, "body": "林默在此刻打开北门。"},
            "claims": [{"id": "claim-1", "text": "林默在此刻打开北门。", "allowed_evidence": []}],
            "memory": [],
        }
        payload = {"issues": [{
            "claim_span_id": "claim-1", "status": "conflict", "nature": "confirmed_conflict", "category": "timeline", "severity": "high",
            "explanation": "Conflicting.", "reasoning": "Same time.",
            "temporal_basis": {"claim_anchor": "此刻", "evidence_anchor": "当时", "relation": "explicit_overlap"},
            "evidence": None, "evidence_chain": [], "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
        }]}
        diagnostics = ContinuityEngine(ResultProvider({}))._repair_diagnostics(payload, data)
        self.assertEqual(diagnostics[0]["problem_codes"], ["author_language_mismatch"])
        self.assertEqual(diagnostics[0]["cited_evidence"], [])

    def test_second_unproven_temporal_response_becomes_conservative_insufficient_evidence(self):
        data = {
            "draft": {"id": "draft-1", "revision": 2, "body": "林默熟练地打开北堤门。"},
            "claims": [{"id": "claim-1", "text": "林默熟练地打开北堤门。", "allowed_evidence": [{"id": "span-1", "chapter_id": "chapter-1", "body": "林默从未去过北堤。"}]}],
            "memory": [{"id": "memory-1", "memory_type": "character_knowledge", "subject": "林默", "predicate": "knowledge", "value": "林默从未去过北堤。", "source_span_id": "span-1"}],
        }
        invalid = {"issues": [{
            "claim_span_id": "claim-1", "status": "conflict", "nature": "confirmed_conflict", "category": "character_knowledge", "severity": "high",
            "explanation": "林默的行为与较早知识状态冲突。", "reasoning": "当前叙述应视为同一时间。",
            "temporal_basis": {"claim_anchor": "熟练地打开北堤门", "evidence_anchor": "从未去过北堤", "relation": "explicit_overlap"},
            "evidence": [{"chapter_id": "chapter-1", "span_id": "span-1", "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": ["memory-1"]}],
            "evidence_chain": [{"span_id": "span-1", "role": "prior_state"}], "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
        }]}

        class RepeatingProvider:
            available = True;label = "repeat";model_label = "repeat"
            def __init__(self):self.calls = 0
            def evaluate(self, _request):self.calls += 1;return ProviderResult(invalid, input_tokens=10, output_tokens=10, latency_ms=1)

        provider = RepeatingProvider();result = ContinuityEngine(provider).execute(data);issue = result["issues"][0]
        self.assertEqual((result["status"], provider.calls, issue["status"], issue["nature"]), ("completed", 2, "insufficient_evidence", "insufficient_evidence"))
        self.assertEqual(result["contract_normalization_count"], 1)
        self.assertEqual(result["contract_normalizations"], [{"claim_span_id": "claim-1", "reason_code": "temporal_overlap_unproven", "outcome": "insufficient_evidence", "provider_attempt": 2}])
        self.assertEqual((issue["evidence"][0]["relation"], issue["evidence"][0]["sufficiency"], issue["evidence_chain"][0]["role"]), ("context", "insufficient", "missing_link"))
        self.assertEqual((issue["available_actions"], issue["suggested_revision"], issue["proposed_memory_change"]), ([], None, None))
        malformed = json.loads(json.dumps(invalid, ensure_ascii=False));malformed["issues"][0]["available_actions"] = ["not_allowed"]
        with self.assertRaisesRegex(ValueError, "schema_invalid"):
            ContinuityEngine(ResultProvider({})).validate(malformed, data, allow_conservative_temporal_normalization=True)

    def test_timeless_rule_conflict_keeps_issue_but_suppresses_unverified_auto_rewrite(self):
        data = {
            "draft": {"id": "draft-1", "revision": 2, "body": "钟声响起，他命令船队立刻出港。"},
            "claims": [{"id": "claim-1", "text": "钟声响起，他命令船队立刻出港。", "allowed_evidence": [{"id": "span-1", "chapter_id": "chapter-1", "body": "钟声响起后，所有船只必须停泊。"}]}],
            "memory": [{"id": "memory-1", "memory_type": "static_canon", "subject": "钟声", "predicate": "rule", "value": "钟声响起后，所有船只必须停泊。", "source_span_id": "span-1"}],
        }
        payload = {"issues": [{
            "claim_span_id": "claim-1", "status": "conflict", "nature": "confirmed_conflict", "category": "world_rule", "severity": "high",
            "explanation": "出港命令违反钟响后必须停泊的规则。", "reasoning": "静态规则禁止钟响后出港。",
            "temporal_basis": {"claim_anchor": "钟声响起", "evidence_anchor": "钟声响起后，所有船只必须停泊", "relation": "timeless_rule"},
            "evidence": [{"chapter_id": "chapter-1", "span_id": "span-1", "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": ["memory-1"]}],
            "evidence_chain": [{"span_id": "span-1", "role": "prior_state"}],
            "suggested_revision": {"before": "命令船队立刻出港", "after": "命令船队立刻出港" + "。"}, "available_actions": ["edit", "apply_suggestion"], "proposed_memory_change": None,
        }]}
        issue = ContinuityEngine(ResultProvider({})).validate(payload, data)[0]
        self.assertEqual(issue["nature"], "confirmed_conflict")
        self.assertIsNone(issue["suggested_revision"])
        self.assertEqual(issue["available_actions"], ["edit"])

    def test_temporal_qualification_is_persisted_in_run_metrics(self):
        class RepeatingProvider:
            available = True;label = "qualification-test";model_label = "qualification-test"
            def evaluate(self, request):
                claim = next(item for item in request["claims"] if item["allowed_evidence"]);evidence = claim["allowed_evidence"][0]
                return ProviderResult({"issues": [{
                    "claim_span_id": claim["id"], "status": "conflict", "nature": "confirmed_conflict", "category": "object_state", "severity": "high",
                    "explanation": "两项状态需要核对。", "reasoning": "当前叙述被错误当成同一时间。",
                    "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
                    "evidence": [{"chapter_id": evidence["chapter_id"], "span_id": evidence["id"], "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []}],
                    "evidence_chain": [{"span_id": evidence["id"], "role": "prior_state"}], "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
                }]}, input_tokens=10, output_tokens=10, latency_ms=1)

        root = pathlib.Path(tempfile.mkdtemp(prefix="v140-qualification-metrics-"))
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=RepeatingProvider(), executor=lambda fn, *args: fn(*args))
        client = TestClient(app);headers = {"Idempotency-Key": str(uuid.uuid4())}
        registered = client.post("/api/auth/register", headers=headers, json={"account_name": "qualificationmetrics", "display_name": "Qualification", "password": "valid-password-99"}).json()["data"]
        project_id = registered["onboarding"]["tutorial"]["project_id"]
        draft = client.get(f"/api/projects/{project_id}").json()["data"]["current_draft"]
        run_id = client.post(f"/api/projects/{project_id}/checks", headers={"Idempotency-Key": str(uuid.uuid4())}, json={"draft_id": draft["id"], "draft_revision": draft["revision"]}).json()["data"]["run_id"]
        result = client.get(f"/api/projects/{project_id}/checks/{run_id}?include=issues,evidence,metrics").json()["data"]
        self.assertEqual((result["status"], result["issues"][0]["nature"]), ("completed", "insufficient_evidence"))
        self.assertEqual(result["metrics"]["contract_normalization_count"], 1)
        self.assertEqual(result["metrics"]["contract_normalizations"][0]["reason_code"], "temporal_overlap_unproven")

    def test_current_continuity_run_repairs_legacy_shape_instead_of_accepting_it(self):
        data = {
            "draft": {"id": "draft-1", "revision": 2, "body": "当前草稿。"},
            "claims": [{"id": "claim-1", "text": "当前草稿。", "allowed_evidence": [{"id": "span-1", "chapter_id": "chapter-1", "body": "既有来源。"}]}],
            "memory": [],
        }
        legacy = {"issues": [{"claim_span_id": "claim-1", "status": "conflict", "category": "attribute", "severity": "low", "explanation": "旧格式。", "evidence": [{"chapter_id": "chapter-1", "span_id": "span-1", "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []}]}]}

        class Provider:
            available = True;label = "strict";model_label = "strict"
            def __init__(self):self.calls=[]
            def evaluate(self, request):
                self.calls.append(request)
                return ProviderResult(legacy if len(self.calls)==1 else {"issues": []}, input_tokens=1, output_tokens=1, latency_ms=1)

        provider=Provider();result=ContinuityEngine(provider).execute(data)
        self.assertEqual((result["status"],result["issues"],len(provider.calls)),("completed",[],2))
        self.assertEqual(provider.calls[1]["contract_repair"]["reason_code"],"trustworthy_review_required")

    def test_chinese_draft_allows_exact_english_dialogue_in_suggested_revision(self):
        data = {
            "draft": {"id": "draft-1", "revision": 2, "body": "林默看向门口，说：STOP。"},
            "claims": [{"id": "claim-1", "text": "林默看向门口，说：STOP。", "allowed_evidence": [{"id": "span-1", "chapter_id": "chapter-1", "body": "门口无人回应。", "prompt_excerpt": "门口无人回应。"}]}],
            "memory": [],
        }
        payload = {"issues": [{
            "claim_span_id": "claim-1", "status": "conflict", "nature": "possible_conflict", "category": "event_status", "severity": "low",
            "explanation": "这段对白与既有场景存在待复核张力。", "reasoning": "证据没有封闭人物主动说出英文对白的可能。",
            "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
            "evidence": [{"chapter_id": "chapter-1", "span_id": "span-1", "relation": "context", "sufficiency": "sufficient", "related_memory_ids": []}],
            "evidence_chain": [{"span_id": "span-1", "role": "current_context"}],
            "suggested_revision": {"before": "STOP", "after": "HALT"}, "available_actions": ["apply_suggestion"], "proposed_memory_change": None,
        }]}
        cleaned = ContinuityEngine(ResultProvider({})).validate(payload, data)
        self.assertEqual(cleaned[0]["suggested_revision"], {"before": "STOP", "after": "HALT"})

    def test_foreshadow_world_rule_cannot_establish_developing_status(self):
        data = analysis_data()
        data["task"] = "foreshadow_scan"
        data["author_records"] = {"foreshadows": []}
        data["layers"]["confirmed"]["memory_records"] = [{
            "id": "memory-rule", "memory_type": "static_canon", "subject": "钟声", "predicate": "rule", "value": "每晚九点响起", "source_span_id": "span-1",
        }]
        data["layers"]["written"]["draft_claims"] = [{"id": "claim-1", "ordinal": 1, "text": "海面传来三次无人回应的钟声。"}]
        data["layers"]["written"]["source_spans"][0]["body"] = "钟声每晚九点响起。"
        payload = {"summary": "发现钟声候选。", "candidates": [{
            "title": "三次钟声", "description": "三次无人回应的钟声可能是新线索。", "suggested_status": "developing",
            "evidence": [
                {"source_type": "draft_claim", "source_id": "claim-1", "relation": "developing", "evidence_kind": "current_clue"},
                {"source_type": "source_span", "source_id": "span-1", "relation": "developing", "evidence_kind": "background_only"},
            ],
        }]}
        cleaned = WritingAnalysisEngine(ResultProvider({})).validate(payload, data)
        candidate = cleaned["candidates"][0]
        self.assertEqual(candidate["suggested_status"], "planted")
        self.assertEqual([(item["source_type"], item["relation"]) for item in candidate["evidence"]], [("draft_claim", "planted")])
        self.assertIsNone(candidate["planted_source_span_id"])
        self.assertNotIn("每晚九点", candidate["description"])
        self.assertIn("海面传来三次无人回应的钟声", candidate["description"])

    def test_foreshadow_planted_background_span_never_becomes_planted_location(self):
        data = analysis_data()
        data["task"] = "foreshadow_scan";data["author_records"] = {"foreshadows": []}
        data["layers"]["written"]["draft_claims"] = [{"id": "claim-1", "ordinal": 1, "text": "海面传来三次无人回应的钟声。"}]
        payload = {"summary": "发现钟声候选。", "candidates": [{
            "title": "三次钟声", "description": "当前钟声是新线索。", "suggested_status": "planted",
            "evidence": [
                {"source_type": "draft_claim", "source_id": "claim-1", "relation": "planted", "evidence_kind": "current_clue"},
                {"source_type": "source_span", "source_id": "span-1", "relation": "planted", "evidence_kind": "background_only"},
            ],
        }]}
        candidate = WritingAnalysisEngine(ResultProvider({})).validate(payload, data)["candidates"][0]
        self.assertEqual(candidate["suggested_status"], "planted")
        self.assertIsNone(candidate["planted_chapter_id"])
        self.assertIsNone(candidate["planted_source_span_id"])
        self.assertEqual([item["evidence_kind"] for item in candidate["evidence"]], ["current_clue", "background_only"])

    def test_foreshadow_typed_background_without_memory_downgrades_but_mixed_specific_clue_remains_developing(self):
        data = analysis_data()
        data["task"] = "foreshadow_scan";data["author_records"] = {"foreshadows": []}
        data["layers"]["written"]["draft_claims"] = [{"id": "claim-1", "ordinal": 1, "text": "同样的三短一长回声再次出现。"}]
        background = {"summary": "候选。", "candidates": [{"title": "回声 A", "description": "当前回声是新线索。", "suggested_status": "developing", "evidence": [
            {"source_type": "draft_claim", "source_id": "claim-1", "relation": "developing", "evidence_kind": "current_clue"},
            {"source_type": "source_span", "source_id": "span-1", "relation": "developing", "evidence_kind": "background_only"},
        ]}]}
        downgraded = WritingAnalysisEngine(ResultProvider({})).validate(background, data)["candidates"][0]
        self.assertEqual(downgraded["suggested_status"], "planted")

        mixed = {"summary": "候选。", "candidates": [{"title": "回声 B", "description": "同一未解回声复现。", "suggested_status": "developing", "evidence": [
            {"source_type": "draft_claim", "source_id": "claim-1", "relation": "developing", "evidence_kind": "current_clue"},
            {"source_type": "source_span", "source_id": "span-1", "relation": "developing", "evidence_kind": "specific_prior_unresolved_clue"},
        ]}]}
        retained = WritingAnalysisEngine(ResultProvider({})).validate(mixed, data)["candidates"][0]
        self.assertEqual(retained["suggested_status"], "developing")
        self.assertEqual(retained["planted_source_span_id"], "span-1")

    def test_plan_alignment_prompt_requires_the_planned_event_not_entity_overlap(self):
        prompt = json.loads(plan_alignment_prompt({**analysis_data(), "output_schema": {}}))
        rules = " ".join(prompt["rules"])
        self.assertIn("Entity overlap or continued pre-event state is never planned_early", rules)
        self.assertIn("not yet due", rules)
        self.assertEqual(prompt["decision_examples"][0]["status"], "planned_missing")
        self.assertEqual(prompt["decision_examples"][1]["status"], "planned_early")
        self.assertIn("铺垫", prompt["decision_examples"][0]["reason"])

    def test_foreshadow_prompt_requires_draft_language_and_conservative_developing(self):
        prompt = json.loads(foreshadow_scan_prompt({**analysis_data(), "author_records": {"foreshadows": []}, "output_schema": {}}))
        rules = " ".join(prompt["rules"])
        self.assertIn("dominant language", rules)
        self.assertIn("ordinary world rule", rules)
        self.assertEqual(prompt["decision_examples"][0]["status"], "planted")
        self.assertEqual(prompt["decision_examples"][1]["status"], "developing")
        self.assertEqual(prompt["decision_examples"][0]["earlier_evidence_kind"], "background_only")
        self.assertEqual(prompt["decision_examples"][1]["earlier_evidence_kind"], "specific_prior_unresolved_clue")


if __name__ == "__main__":
    unittest.main()
