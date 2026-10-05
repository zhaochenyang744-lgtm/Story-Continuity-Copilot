"""Flash (thinking disabled) analysis failures found by the 2026-09-29 live smoke.

- change_impact failed 3/3 as evidence_unresolvable: one item named the current draft's id as a
  "chapter" target, and one unsupplied target rejected the whole analysis.
- author_material_comparison failed as schema_invalid: plan_deviation was chosen for a setting
  material, a rule the prompt never stated.
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

    def test_setting_material_labelled_plan_deviation_is_read_as_possible_tension(self):
        def comparison(nature):
            material = {"id": "material-1", "title": "林默设定", "content": "左手缺一根小指", "nature": nature}
            return {"task": "author_material_comparison", "bindings": {"project_id": "synthetic", "comparison_id": "cmp-1", "decision_revision": 0},
                    "comparison": {"material": material, "passage": {"id": "span-1"}},
                    "layers": {"planned": {"story_plans": [material], "character_plans": [], "world_plans": []}, "confirmed": {"memory_records": []},
                               "written": {"source_spans": [{"id": "span-1", "chapter_id": "chapter-3", "chapter_number": 3, "label": "钟声", "body": "林默用双手十指握住栏杆。"}],
                                           "draft_claims": []},
                               "identity": {"characters": [], "aliases": []}, "reference": {"chapters": [], "world_entries": []}}}
        payload = {"assessment": "plan_deviation", "explanation": "设定与正文冲突。", "evidence": [
            {"source_type": "author_material", "source_id": "material-1"}, {"source_type": "source_span", "source_id": "span-1"}]}
        engine = WritingAnalysisEngine(Provider())
        self.assertEqual(engine.validate(payload, comparison("setting"))["assessment"], "possible_tension")
        self.assertEqual(engine.validate(payload, comparison("plan"))["assessment"], "plan_deviation")

    def test_prompts_state_the_target_and_plan_deviation_rules(self):
        impact_prompt = json.loads(request_prompt_and_budget({**impact_data(), "output_schema": {}})[0])
        self.assertTrue(any("The current draft is not a target" in rule for rule in impact_prompt["rules"]))
        comparison = {"task": "author_material_comparison", "comparison": {}, "bindings": {}, "layers": {}, "retrieval": {}, "output_schema": {}}
        comparison_prompt = json.loads(request_prompt_and_budget(comparison)[0])
        self.assertTrue(any("plan_deviation applies only when the material nature is plan" in rule for rule in comparison_prompt["rules"]))


if __name__ == "__main__":
    unittest.main()
