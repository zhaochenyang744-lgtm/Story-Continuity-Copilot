"""v1.9 chapter check (triage v5, screened review v25k). On the spent lf3-lf5 formal sets the non-thinking triage
scored three missing-link sentences 1 ("agrees") and they were never reviewed; a thinking review passed a measured
value and a state said to hold until today, called an eyewitness claim a possible conflict, and reported missing links
on clean chapters for new off-page background."""
from __future__ import annotations

import json
import unittest

from app import provider
from app import review_screening as screening
from app.v2_database import parse_screened_trace_terms, screened_trace_terms

MISSED = (
    "前日西廊那三声提示铃，是唐抒槿东移遮雨布引起的。",            # cause
    "南廊小木门在青芽节午后便闩好了，因此到现在仍是关着的。",      # state still holding
    "芩昼汀亲眼看过第三天清早邵苇弦独自把旧幕搬进后台。",          # eyewitness
    "八月初五下午实地量得，戏棚台口的净宽恰好是六米四。",          # measurement
    "那块试片从次日清晨直至今天，天天都保持着干燥的状态。",        # state ever since
    "有关松籽函的图文摹写已经得到馆方许可。",                      # permission
    "岑栖砾已经从孟扉榆手中收妥六棱样尺。",                        # handoff
)
HARMLESS = (
    "近午有一阵空闲，她从后屋取出干饼，照前回一样放到门边小凳上。",
    "这是祝弥前些天送来请他修的工具。",
    "她昨天解释时，对方只顾翻筐里压坏的叶子，不肯看图。",
    "她知道表哥一直想在窗外放一盆绿色的东西。",
    "他把茶端过来，坐下喝了一口。",
)


class LinkMarkerTests(unittest.TestCase):
    def test_marked_sentences_scored_low_are_raised_to_a_gap(self):
        claims = [{"id": f"c{index}", "text": text} for index, text in enumerate(MISSED + HARMLESS)]
        scores = {claim["id"]: 1 for claim in claims}
        kinds = {claim["id"]: "none" for claim in claims}
        raised = screening.raise_link_markers(claims, scores, kinds)
        self.assertEqual(raised, len(MISSED))
        for index in range(len(MISSED)):
            self.assertEqual((scores[f"c{index}"], kinds[f"c{index}"]), (2, "gap"), MISSED[index])
        for index in range(len(MISSED), len(claims)):
            self.assertEqual((scores[f"c{index}"], kinds[f"c{index}"]), (1, "none"), claims[index]["text"])

    def test_a_higher_score_and_its_kind_are_kept(self):
        claims = [{"id": "a", "text": MISSED[0]}]
        scores, kinds = {"a": 3}, {"a": "conflict"}
        self.assertEqual(screening.raise_link_markers(claims, scores, kinds), 0)
        self.assertEqual((scores["a"], kinds["a"]), (3, "conflict"))

    def test_a_raised_sentence_competes_for_escalation_or_the_sweep(self):
        claims = [{"id": "a", "text": MISSED[2], "context": "x"}]
        scores, kinds = {"a": 0}, {"a": "none"}
        screening.raise_link_markers(claims, scores, kinds)
        self.assertIn("a", screening.triage_escalations(claims, scores, kinds))


class PromptTests(unittest.TestCase):
    def test_the_triage_says_naming_the_same_things_is_not_agreement(self):
        prompt = json.loads(provider.continuity_triage_prompt({"chapter": "x", "passages": [], "sentences": []}))
        rules = " ".join(prompt["rules"])
        self.assertIn("Describing the same people, things or events is not agreement", rules)
        self.assertIn("new off-page background", rules)
        self.assertEqual(prompt["prompt_version"], "continuity-triage-v5-stated-links")

    def test_the_screened_review_has_the_new_examples_and_the_legacy_review_does_not(self):
        def situations(pipeline):
            request = {"pipeline": pipeline, "draft": {"id": "d", "revision": 1, "body": "x"}, "claims": [], "memory": [], "output_schema": {}}
            return " ".join(example["situation"] for example in json.loads(provider.continuity_prompt(request))["decision_examples"])
        for phrase in ("exact measured value", "with their own eyes or ears", "has held ever since", "new background the earlier chapters never address"):
            self.assertIn(phrase, situations("screened"))
            self.assertNotIn(phrase, situations(None))


    def test_the_screened_second_review_says_new_background_is_not_a_gap(self):
        def rules(pipeline, second):
            request = {"pipeline": pipeline, "draft": {"id": "d", "revision": 1, "body": "x"}, "claims": [], "memory": [], "output_schema": {},
                       **({"second_review": True} if second else {})}
            return " ".join(json.loads(provider.continuity_prompt(request))["rules"])
        phrase = "New background is not a missing link either"
        self.assertIn(phrase, rules("screened", True))
        self.assertNotIn(phrase, rules("screened", False))
        self.assertNotIn(phrase, rules(None, True))


class TraceTests(unittest.TestCase):
    def test_triage_detail_survives_the_trace_column(self):
        terms = screened_trace_terms({"screen": "flagged", "review": "triage", "triage": {"score": 2, "kind": "gap", "outcome": "swept"}})
        self.assertEqual(parse_screened_trace_terms(terms),
                         {"screen": "flagged", "review": "triage", "triage": {"score": 2, "kind": "gap", "outcome": "swept"}})
        self.assertEqual(parse_screened_trace_terms("screen:passed;review:deep"), {"screen": "passed", "review": "deep"})


if __name__ == "__main__":
    unittest.main()
