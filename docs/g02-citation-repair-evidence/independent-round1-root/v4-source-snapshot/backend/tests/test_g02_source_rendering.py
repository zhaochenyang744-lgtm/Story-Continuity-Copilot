"""Adversarial checks for bounded G02 source rendering."""
from __future__ import annotations

import copy
import unittest

from app.engine import WritingAnalysisEngine
from tests.test_v140_real_ai_contract_repairs import ResultProvider, analysis_data


def brief(data, text, sources, summary="模型自由摘要包含额外未引用事实。"):
    payload = {"summary": summary, "summary_sources": sources[:3],
               "items": [{"section": "recent_source", "text": text, "sources": sources}]}
    return WritingAnalysisEngine(ResultProvider(payload)).validate(payload, data)


class SourceRenderedBriefTest(unittest.TestCase):
    def test_multifact_item_keeps_both_own_sources_and_summary_is_rebuilt(self):
        data = analysis_data()
        data["layers"]["written"]["draft"]["excerpt"] = ""
        data["layers"]["written"]["draft_claims"] = []
        data["layers"]["confirmed"]["memory_records"] = [{"id": "memory-1", "memory_type": "character_knowledge",
            "subject": "温岚", "predicate": "does_not_know", "value": "廊桥钥匙的含义"}]
        span = data["layers"]["written"]["source_spans"][0]
        span["body"] = "温岚看得懂潮表上的坐标，却还不知道廊桥钥匙这个代号指向什么。"
        result = brief(data, "温岚看得懂潮表上的坐标，但尚不知道廊桥钥匙的含义。",
                       [{"source_type": "memory_record", "source_id": "memory-1"}])
        item = result["items"][0]
        self.assertEqual({source["source_type"] for source in item["sources"]}, {"source_span", "memory_record"})
        self.assertIn("看得懂潮表上的坐标", item["text"])
        self.assertIn("不知道", item["text"])
        self.assertNotIn("模型自由摘要", result["summary"])
        self.assertTrue(all(source in result["summary_sources"] for source in item["sources"]))

    def test_dialogue_negation_time_and_reversed_relation_are_not_promoted(self):
        scenarios = (
            ("林默已经知道密码。", "林默尚不知道密码。"),
            ("林默18点已经知道密码。", "林默18点尚不知道密码，直到19点才获知。"),
            ("乔霁从沈砚手中拿到星钥。", "乔霁把星钥交给沈砚。"),
            ("林默知道密码。", "林默说‘我知道密码’，但叙述者指出这是谎言。"),
        )
        for assertion, actual in scenarios:
            with self.subTest(assertion=assertion):
                data = analysis_data()
                data["layers"]["written"]["draft"]["excerpt"] = ""
                data["layers"]["written"]["draft_claims"] = []
                data["layers"]["written"]["source_spans"][0]["body"] = actual
                result = brief(data, assertion, [{"source_type": "source_span", "source_id": "span-1"}])
                self.assertEqual(result["items"][0]["sources"][0]["source_id"], "span-1")
                self.assertIn(actual, result["items"][0]["text"])
                self.assertNotEqual(result["items"][0]["text"], assertion)
                self.assertIn(actual, result["summary"])

    def test_cyclic_wrong_claim_ids_are_repaired_locally(self):
        data = analysis_data()
        claims = ["林默走进北门。", "银钥匙交给陈澈。", "温岚不知道密码。"]
        data["layers"]["written"]["draft"]["excerpt"] = "".join(claims)
        data["layers"]["written"]["draft_claims"] = [
            {"id": f"claim-{index+1}", "ordinal": index+1, "text": value} for index, value in enumerate(claims)]
        payload = {"summary": "不能采用的模型摘要。", "summary_sources": [{"source_type": "draft_claim", "source_id": "claim-1"}],
                   "items": [{"section": "recent_source", "text": value,
                              "sources": [{"source_type": "draft_claim", "source_id": f"claim-{(index+1)%3+1}"}]}
                             for index, value in enumerate(claims)]}
        result = WritingAnalysisEngine(ResultProvider(payload)).validate(payload, data)
        self.assertEqual(result["citation_transform"]["added_source_count"], 3)
        self.assertEqual([[source["source_id"] for source in item["sources"]] for item in result["items"]],
                         [["claim-1"], ["claim-2"], ["claim-3"]])
        self.assertNotIn("不能采用", result["summary"])

    def test_unrelated_model_wording_yields_useful_bound_record(self):
        data = analysis_data()
        data["layers"]["written"]["draft"]["excerpt"] = ""
        data["layers"]["written"]["draft_claims"] = []
        data["layers"]["confirmed"]["memory_records"] = [{"id": "memory-1", "memory_type": "dynamic_state",
            "subject": "星钥", "predicate": "holder", "value": "乔霁"}]
        result = brief(data, "沈砚已永久保管星钥。", [{"source_type": "memory_record", "source_id": "memory-1"}])
        self.assertTrue(result["items"])
        self.assertIn("乔霁", result["items"][0]["text"])
        self.assertNotIn("沈砚已永久保管", result["items"][0]["text"])

    def test_long_claim_suffix_limited_without_upgrading_partial_quote(self):
        data = analysis_data()
        long_claim = "林默沿长廊走，" * 100 + "但这只是传闻，林默其实没有交出星钥。"
        data["layers"]["written"]["draft"]["excerpt"] = long_claim
        data["layers"]["written"]["draft_claims"] = [{"id": "claim-long", "ordinal": 1, "text": long_claim[:540]}]
        data["retrieval"]["draft_claim_scope"] = {"available": 1, "selected": [{"id": "claim-long", "truncated": True,
            "source_chars": len(long_claim), "supplied_chars": 540}]}
        result = brief(data, "林默已交出星钥。", [{"source_type": "draft_claim", "source_id": "claim-long"}])
        self.assertEqual(result["draft_coverage"]["status"], "partial")
        self.assertIn("draft_claim_truncated", result["draft_coverage"]["reasons"])
        self.assertNotIn("已交出星钥", result["items"][0]["text"])
        self.assertNotIn("但这只是传闻", result["items"][0]["text"])


if __name__ == "__main__":
    unittest.main()
