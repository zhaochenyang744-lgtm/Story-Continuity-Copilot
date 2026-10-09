"""Flash (thinking disabled) analysis failures found by the 2026-09-29 live smoke.

- change_impact failed 3/3 as evidence_unresolvable: one item named the current draft's id as a
  "chapter" target, and one unsupplied target rejected the whole analysis.
"""
from __future__ import annotations

import json
import unittest

from app.engine import WritingAnalysisEngine
from app.provider import request_prompt_and_budget


def impact_data():
    return {"task": "change_impact", "bindings": {"project_id": "synthetic"},
            "proposal": {"target_type": "general", "target_id": None, "proposed_change": "把父亲失踪改为十年前"},
            "retrieval": {"target_source": None},
            "layers": {"planned": {"story_plans": [], "character_plans": [], "world_plans": []},
                       "confirmed": {"memory_records": [{"id": "memory-B", "subject": "父亲", "predicate": "status", "value": "三年前失踪", "source_span_id": "span-B"}]},
                       "written": {"source_spans": [{"id": "span-B", "chapter_id": "chapter-B", "chapter_number": 2, "label": "旧友", "body": "父亲在三年前的风暴中失踪。"}],
                                   "draft_claims": [{"id": "claim-1", "ordinal": 1, "text": "苏遥说她要去北岸找父亲。"}]},
                       "identity": {"characters": [], "aliases": []},
                       "reference": {"chapters": [{"id": "chapter-B", "chapter_number": 2, "title": "旧友"}], "world_entries": []}}}


class Provider:
    label = "stub"
    available = True


class FlashAnalysisContractTests(unittest.TestCase):
    def test_change_impact_drops_an_item_aimed_at_the_current_draft_and_keeps_the_rest(self):
        payload = {"summary": "第二章需要同步修改。", "items": [
            {"area": "chapter", "target_id": "chapter-B", "impact": "第二章写的是三年前。", "evidence": [{"source_type": "source_span", "source_id": "span-B"}]},
            {"area": "chapter", "target_id": "draft-current", "impact": "草稿未提年份。", "evidence": [{"source_type": "draft_claim", "source_id": "claim-1"}]}]}
        result = WritingAnalysisEngine(Provider()).validate(payload, impact_data())
        self.assertEqual((result["evidence_status"], [item["target_id"] for item in result["items"]]), ("supported", ["chapter-B"]))

    def test_change_impact_with_only_unsupplied_targets_is_insufficient_and_bad_evidence_still_fails(self):
        engine = WritingAnalysisEngine(Provider())
        only_draft = {"summary": "s", "items": [{"area": "chapter", "target_id": "draft-current", "impact": "i",
                                                  "evidence": [{"source_type": "draft_claim", "source_id": "claim-1"}]}]}
        self.assertEqual(engine.validate(only_draft, impact_data())["evidence_status"], "insufficient")
        bad_evidence = {"summary": "s", "items": [{"area": "chapter", "target_id": "chapter-B", "impact": "i",
                                                    "evidence": [{"source_type": "source_span", "source_id": "span-invented"}]}]}
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            engine.validate(bad_evidence, impact_data())
        non_string = {"summary": "s", "items": [{"area": "chapter", "target_id": ["chapter-B"], "impact": "i",
                                                  "evidence": [{"source_type": "source_span", "source_id": "span-B"}]}]}
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            engine.validate(non_string, impact_data())

    def test_prompts_state_the_target_rule(self):
        impact_prompt = json.loads(request_prompt_and_budget({**impact_data(), "output_schema": {}})[0])
        self.assertTrue(any("The current draft is not a target" in rule for rule in impact_prompt["rules"]))


if __name__ == "__main__":
    unittest.main()
