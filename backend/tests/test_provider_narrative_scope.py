"""Offline prompt/contract coverage; these tests do not measure model accuracy."""
from copy import deepcopy
import json
import unittest

from app.engine import ContinuityContractValidationError, ContinuityEngine
from app.provider import CONTINUITY_PROMPT_VERSION, MAX_INPUT_BUDGET_UNITS, change_impact_prompt, continuity_prompt, estimate_prompt_budget_units


class NoNetworkProvider:
    available = True
    label = "offline-only"
    model_label = "offline-only"
    def evaluate(self, request):
        raise AssertionError("Offline contract tests must never call a Provider")


class NarrativeScopeContractTests(unittest.TestCase):
    def fixture(self, claim, evidence):
        return {"draft": {"id": "draft-new", "revision": 4, "body": claim},
                "claims": [{"id": "claim-new", "text": claim, "allowed_evidence": [
                    {"id": "source-new", "chapter_id": "chapter-new", "body": evidence}]}],
                "memory": [], "output_schema": {}}

    def test_unseen_recollection_testimony_and_alias_texts_are_preserved(self):
        variants = [
            ("她忆起三月一日窗帘是红色的，三月二日已经换成蓝色。", "三月二日，窗帘是蓝色的。"),
            ("证人故意作伪证说仓门失火了。事实上仓门始终完好。", "仓门始终完好，未遭火灾。"),
            ("米舟保管航海手册。", "邵禾的笔名是米舟，同一个人保管航海手册。"),
            ("五月四日下午，工匠把早晨关好的百叶窗打开。", "五月四日早晨，百叶窗关闭。"),
        ]
        engine = ContinuityEngine(NoNetworkProvider())
        for claim, evidence in variants:
            with self.subTest(claim=claim):
                data = self.fixture(claim, evidence)
                prompt = continuity_prompt(data)
                parsed = json.loads(prompt)
                self.assertEqual(parsed["current_claims"][0]["text"], claim)
                self.assertEqual(parsed["current_claims"][0]["allowed_evidence"][0]["excerpt"], evidence)
                self.assertLessEqual(estimate_prompt_budget_units(prompt), MAX_INPUT_BUDGET_UNITS)
                # An author-labelled compatible case needs no forced Issue object.
                self.assertEqual(engine.validate({"issues": []}, data), [])

    def issue(self):
        return {"claim_span_id": "claim-new", "status": "conflict", "nature": "confirmed_conflict",
                "category": "attribute", "severity": "high", "explanation": "同一时点水位读数不同。",
                "reasoning": "同一水位尺在同一明确时点的两个读数不能同时成立。",
                "temporal_basis": {"claim_anchor": "六月三日九点", "evidence_anchor": "六月三日九点", "relation": "explicit_overlap"},
                "evidence": [{"chapter_id": "chapter-new", "span_id": "source-new", "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []}],
                "evidence_chain": [{"span_id": "source-new", "role": "current_context"}],
                "suggested_revision": None, "available_actions": ["edit", "false_positive"], "proposed_memory_change": None}

    def test_true_same_time_conflict_stays_actionable(self):
        data = self.fixture("六月三日九点，水位尺读数是五米。", "六月三日九点，同一水位尺读数是二米。")
        output = ContinuityEngine(NoNetworkProvider()).validate({"issues": [self.issue()]}, data)
        self.assertEqual(output[0]["nature"], "confirmed_conflict")
        self.assertEqual(output[0]["evidence"][0]["relation"], "contradicts")

    def test_adjacent_claim_anchor_is_still_rejected(self):
        data = self.fixture("水位仍是五米。", "六月三日九点，同一水位尺读数是二米。")
        data["draft"]["body"] = "六月三日九点，观察员返回。水位仍是五米。"
        with self.assertRaisesRegex(ContinuityContractValidationError, "temporal_anchor_unresolvable"):
            ContinuityEngine(NoNetworkProvider()).validate({"issues": [self.issue()]}, data)

    def test_conflict_with_supporting_evidence_stays_rejected(self):
        data = self.fixture("六月三日九点，水位尺读数是五米。", "六月三日九点，同一水位尺读数是二米。")
        issue = self.issue()
        issue["evidence"][0]["relation"] = "supports"
        with self.assertRaisesRegex(ValueError, "conflict_evidence_not_direct"):
            ContinuityEngine(NoNetworkProvider()).validate({"issues": [issue]}, data)

    def test_uncertainty_still_requires_missing_link_and_no_actions(self):
        data = self.fixture("六月三日九点，观察员说出了新的暗号。", "观察员昨日不知道新的暗号。")
        issue = self.issue()
        issue.update(status="insufficient_evidence", nature="insufficient_evidence", available_actions=[])
        issue["temporal_basis"] = {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"}
        issue["evidence"][0].update(relation="context", sufficiency="insufficient")
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            ContinuityEngine(NoNetworkProvider()).validate({"issues": [issue]}, data)
        issue["evidence_chain"][0]["role"] = "missing_link"
        self.assertEqual(ContinuityEngine(NoNetworkProvider()).validate({"issues": [issue]}, data)[0]["available_actions"], [])

    def test_prompt_identifies_new_contract_without_fixture_answers(self):
        prompt = json.loads(continuity_prompt(self.fixture("天色逐渐明亮。", "山谷里有一条溪流。")))
        self.assertEqual(prompt["prompt_version"], CONTINUITY_PROMPT_VERSION)
        rules = "\n".join(prompt["rules"])
        for boundary in ("exact current_claims[id].text", "explicitly identified lie", "same person",
                         "current draft itself is supplied written evidence", "remove the object"):
            self.assertIn(boundary, rules)
        encoded = json.dumps(prompt, ensure_ascii=False)
        for forbidden in ("乔野", "山雀", "陆薇", "青石城", "prospan", "profact", "pro-round"):
            self.assertNotIn(forbidden, encoded)

    def test_impact_keeps_absence_and_each_item_within_cited_scope(self):
        request = {"proposal": {"target_type": "memory", "target_id": "new-rule", "proposed_change": "将夜间通行条件改为持证通行。"},
                   "bindings": {"project_id": "new-project"}, "layers": {}, "retrieval": {"truncated": {"source_span": True}}, "output_schema": {}}
        result = json.loads(change_impact_prompt(request))
        self.assertTrue(result["retrieval"]["truncated"]["source_span"])
        rules = "\n".join(result["rules"])
        for constraint in ("not absence from the full manuscript", "same item's or finding's actual citations",
                           "does not establish that source chapters are unaffected", "summary_sources themselves"):
            self.assertIn(constraint, rules)
        self.assertEqual(result["proposal"], request["proposal"])


if __name__ == "__main__":
    unittest.main()
