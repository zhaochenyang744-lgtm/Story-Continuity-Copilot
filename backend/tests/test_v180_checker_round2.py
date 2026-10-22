"""Chapter check, second round after lf3-formal (2026-10-18): traditional calendar anchors, knowledge facts kept per person."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import _explicit_temporal_overlap, _full_temporal_scope_supports_conflict, _temporal_anchor_is_explicit, _traditional_calendar


class TraditionalCalendarTests(unittest.TestCase):
    def test_days_hours_and_named_months_are_read(self):
        self.assertEqual(_traditional_calendar("霜月初六午时"), {"日": {"6"}, "shichen": {"午"}, "month_name": {"霜月"}})
        self.assertEqual(_traditional_calendar("芦季十二申时"), {"日": {"12"}, "shichen": {"申"}, "month_name": {"芦季"}})
        self.assertEqual(_traditional_calendar("那夜三更"), {"watch": {"三"}})
        self.assertEqual(_traditional_calendar("梧月廿三"), {"日": {"23"}, "month_name": {"梧月"}})

    def test_ordinary_numbers_are_not_days(self):
        for text in ("十二个人围着桌子", "十二点整", "他十五岁", "第十二章", "十一月", "更加小心", "更新了账册"):
            with self.subTest(text=text):
                self.assertEqual(_traditional_calendar(text), {})

    def test_such_an_anchor_is_explicit(self):
        self.assertTrue(_temporal_anchor_is_explicit("霜月初六午时"))
        self.assertTrue(_temporal_anchor_is_explicit("初三"))
        self.assertFalse(_temporal_anchor_is_explicit("那天"))

    def test_same_day_and_hour_overlap_and_different_ones_do_not(self):
        self.assertTrue(_explicit_temporal_overlap("霜月初六午时", "霜月初六午时"))
        self.assertFalse(_explicit_temporal_overlap("霜月初六午时", "霜月初七午时"))
        self.assertFalse(_explicit_temporal_overlap("霜月初六午时", "霜月初六申时"))
        self.assertFalse(_explicit_temporal_overlap("霜月初六", "梧月初六"))

    def test_the_word_before_a_month_is_not_part_of_it(self):
        # lf4-formal a-i07: "那个少年在四月初九辰时……" read the month as 在四月, so the same day looked different.
        self.assertEqual(_traditional_calendar("那个少年在四月初九辰时"), {"日": {"9"}, "shichen": {"辰"}})
        self.assertEqual(_traditional_calendar("在霜月初六")["month_name"], {"霜月"})
        self.assertEqual(_traditional_calendar("正月初一")["month_name"], {"正月"})
        self.assertFalse(_explicit_temporal_overlap("正月初一", "腊月初一"))
        claim = "四月初九辰时，杜弥舟初次拿起梭尾签便独自读出了每道刻口的意思。"
        evidence = "那个少年在四月初九辰时始终不认识梭尾签的缺口记号。"
        self.assertTrue(_full_temporal_scope_supports_conflict(claim, evidence, "四月初九辰时", "四月初九辰时"))

    def test_the_lf3_designated_sentence_supports_a_confirmed_conflict(self):
        # lf3-formal a-i08: the model answered confirmed_conflict with these anchors; the bound check downgraded it.
        claim = "霜月初六午时，霍尺荻在补风坞外的试航台上收拢标线绳，让它避开向坡下跑的细沙。"
        evidence = "霜月初六午时，霍尺荻一直待在补风坞内修理地锚。"
        self.assertTrue(_full_temporal_scope_supports_conflict(claim, evidence, "霜月初六午时", "霜月初六午时"))
        self.assertFalse(_full_temporal_scope_supports_conflict(claim, evidence.replace("初六", "初七"), "霜月初六午时", "霜月初七午时"))



class KnowledgeSlotTests(unittest.TestCase):
    """First A1c fix-02, fresh import: the later route-mark fact took every reserved place meant for her reading."""

    def test_the_reading_fact_is_reserved_despite_a_later_knowledge_fact_naming_the_place(self):
        from app.engine import ContinuityEngine
        name = "祝嵊禾"
        facts = [
            ("route", 29, name, "knowledge", "在路旁辨出磨浅标记指向悬汀洲外缘，欧荻衡也确认"),
            ("read", 25, name, "knowledge", "已能独立读懂短句风字，不必再等别人替她念出"),
            ("bag", 30, name, "possession", "袖袋中带着包有羽签的小袋"),
            ("fear", 28, name, "status", "看见暗边移动而害怕，手指发抖"),
            ("walk", 30, name, "location", "离开平地时走在欧荻衡旁边"),
            ("isle", 21, "悬汀洲", "location", "众人尚未抵达悬汀洲，远处淡影是否为其所在仍未确认"),
        ]
        memory = [{"id": f"mem-{key}", "memory_type": "character_knowledge" if predicate == "knowledge" else "dynamic_state",
                   "subject": subject, "predicate": predicate, "value": value, "source_span_id": f"span-{key}"}
                  for key, _, subject, predicate, value in facts]
        chapters = {f"mem-{key}": chapter for key, chapter, *_ in facts}
        claim = {"id": "c", "text": "抵达悬汀洲后，祝嵊禾依然一个风字也不认识，任何短句都必须等旁人逐字读给她听。", "chapter_number": 31, "allowed_evidence": []}
        reserved, _ = ContinuityEngine.__new__(ContinuityEngine)._related_parts(claim, memory, 10, chapters, [])
        ids = [item["id"] for item in reserved]
        self.assertIn("mem-read", ids)
        self.assertEqual(ids[0], "mem-read")


class StatedInabilityPromptTests(unittest.TestCase):
    """lf3-formal: four knowledge conflicts ('does not recognize the marks', later read at a glance) were judged missing learning events."""

    def test_the_screened_review_calls_a_stated_inability_a_conflict(self):
        import json
        from app import provider
        request = {"pipeline": "screened", "draft": {"id": "d", "revision": 1, "body": "x"}, "claims": [], "memory": [], "output_schema": {}}
        prompt = json.loads(provider.continuity_prompt(request))
        rules = " ".join(prompt["rules"])
        self.assertIn("that is a conflict about character_knowledge, not a missing link", rules)
        self.assertIn("never insufficient_evidence for a missing learning event", rules)
        self.assertNotIn("says nothing by itself about what they could learn later", rules)
        # A claimed act of telling that no passage shows is still a gap.
        self.assertIn("missing handoff, a claimed act of telling or teaching, outcome", rules)
        situations = [example["situation"] for example in prompt["decision_examples"]]
        self.assertNotIn("A claimed knowledge transfer has no supplied handoff event.", situations)
        self.assertEqual(prompt["prompt_version"], "continuity-review-v25k-screened-offpage-second-review")

    def test_the_legacy_review_is_unchanged(self):
        import json
        from app import provider
        request = {"draft": {"id": "d", "revision": 1, "body": "x"}, "claims": [], "memory": [], "output_schema": {}}
        prompt = json.loads(provider.continuity_prompt(request))
        self.assertEqual(prompt["rules"], list(provider.CONTINUITY_REVIEW_RULES))
        self.assertEqual(prompt["prompt_version"], "continuity-review-v24d-epithet-referents")


class TriageGapSlotTests(unittest.TestCase):
    """lf2-formal c-t06: 17 of 43 sentences scored 2, the cap of 3 took the first three in reading order, two missing links were never reviewed."""

    @staticmethod
    def claim(number, text, passage=""):
        return {"id": f"c{number}", "text": text, "context": "draft", "allowed_evidence": [{"id": f"p{number}", "prompt_excerpt": passage}] if passage else []}

    def test_kinds_are_read_and_a_missing_kind_is_none(self):
        from app import review_screening as RS
        kinds = {}
        scores = RS.parse_triage({"scores": [{"id": "s1", "score": 2, "kind": "gap"}, {"id": "s2", "score": 3, "kind": "conflict"},
                                             {"id": "s3", "score": 2}, {"id": "s4", "score": 1, "kind": "gap"}]},
                                 {"s1": "a", "s2": "b", "s3": "c", "s4": "d"}, kinds)
        self.assertEqual(scores, {"a": 2, "b": 3, "c": 2, "d": 1})
        self.assertEqual(kinds, {"a": "gap", "b": "conflict", "c": "none", "d": "none"})
        with self.assertRaises(RS.ScreenContractError):
            RS.parse_triage({"scores": [{"id": "s1", "score": 2, "kind": "maybe"}]}, {"s1": "a"}, {})

    def test_two_places_are_kept_for_missing_links(self):
        from app import review_screening as RS
        claims = [self.claim(n, f"句子{n}") for n in range(1, 9)]
        scores = {f"c{n}": 2 for n in range(1, 9)}
        kinds = {"c7": "gap", "c8": "gap"}
        chosen = RS.triage_escalations(claims, scores, kinds)
        self.assertEqual(len(chosen), RS.TRIAGE_ESCALATION_CAP + RS.TRIAGE_GAP_SLOTS)
        self.assertTrue({"c7", "c8"} <= chosen)
        # Without missing links the next highest take the places; with fewer candidates nothing is invented.
        self.assertEqual(len(RS.triage_escalations(claims, scores)), RS.TRIAGE_ESCALATION_CAP + RS.TRIAGE_GAP_SLOTS)
        self.assertEqual(len(RS.triage_escalations(claims[:4], scores)), 4)
        # A gap ranked last in reading order still gets a place before an earlier non-gap.
        self.assertIn("c8", RS.triage_escalations(claims, scores, {"c8": "gap"}))

    def test_equal_scores_prefer_the_sentence_sharing_more_with_its_passages(self):
        from app import review_screening as RS
        claims = [self.claim(1, "今天风很大。", "昨日下雨。"), self.claim(2, "天气晴。", "天气晴。"), self.claim(3, "他走了。", ""),
                  self.claim(4, "笛脊图出自初代井师纱泓的手笔。", "笛脊图是初代井师纱泓画的图。")]
        from unittest import mock
        with mock.patch.object(RS, "TRIAGE_ESCALATION_CAP", 1), mock.patch.object(RS, "TRIAGE_GAP_SLOTS", 0):
            self.assertEqual(RS.triage_escalations(claims, {c["id"]: 2 for c in claims}), {"c4"})

    def test_the_triage_prompt_asks_for_the_kind(self):
        import json
        from app import provider
        prompt = json.loads(provider.continuity_triage_prompt({"chapter": "x", "passages": [], "sentences": []}))
        self.assertEqual(prompt["output_schema"]["scores"][0]["kind"], "conflict|gap|none")
        self.assertEqual(prompt["prompt_version"], "continuity-triage-v5-stated-links")


class InitializationDropTests(unittest.TestCase):
    """Third A1c formal (2026-10-18): one candidate with an invalid memory_type, twice, failed the whole initialization."""

    @staticmethod
    def provider(make):
        from app.provider import ProviderResult
        class Provider:
            available = True
            label = model_label = "drop-test"
            def __init__(self): self.calls = 0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult(make(request), input_tokens=10, output_tokens=2)
        return Provider()

    @staticmethod
    def data():
        return {"source_revision": 1, "sources": [{"id": "span-1", "chapter_id": "chapter-1", "chapter_number": 1, "chapter_title": "一", "label": "import", "body": "甲" * 400}]}

    @staticmethod
    def candidate(request, memory_type="static_canon", value="已确认"):
        item = request["sources"][0]
        return {"memory_type": memory_type, "subject": "林默", "predicate": "identity", "value": value, "chapter_id": item["chapter_id"], "source_span_id": item["id"]}

    def test_an_invalid_candidate_is_dropped_once_the_repairs_are_spent(self):
        from app.engine import MemoryInitializationEngine
        provider = self.provider(lambda request: {"candidates": [self.candidate(request), self.candidate(request, "character", "坏的")]})
        result = MemoryInitializationEngine(provider).execute(self.data())
        self.assertEqual(result["status"], "completed")
        self.assertEqual([item["value"] for item in result["candidates"]], ["已确认"])
        self.assertEqual(result["normalization_kinds"].get("invalid_candidates_dropped"), 1)
        self.assertEqual(provider.calls, 3)  # the answer and its two repairs
        self.assertEqual(result["repair_events"][-1]["result"], "invalid_candidates_dropped")

    def test_nothing_valid_or_a_broken_answer_still_fails(self):
        from app.engine import MemoryInitializationEngine
        only_bad = self.provider(lambda request: {"candidates": [self.candidate(request, "character")]})
        self.assertEqual(MemoryInitializationEngine(only_bad).execute(self.data())["status"], "failed")
        broken = self.provider(lambda request: {"facts": []})
        self.assertEqual(MemoryInitializationEngine(broken).execute(self.data())["error_code"], "top_level_shape_invalid")

    def test_a_valid_answer_is_unchanged(self):
        from app.engine import MemoryInitializationEngine
        good = self.provider(lambda request: {"candidates": [self.candidate(request)]})
        result = MemoryInitializationEngine(good).execute(self.data())
        self.assertEqual((result["status"], good.calls, result["normalization_kinds"].get("invalid_candidates_dropped")), ("completed", 1, None))


if __name__ == "__main__":
    unittest.main()
