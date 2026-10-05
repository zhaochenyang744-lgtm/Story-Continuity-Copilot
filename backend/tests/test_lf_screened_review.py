"""Screened continuity review (long-text phase 4).

A cheap non-thinking screen flags the sentences worth a careful look; only those are reviewed, each
against passages of earlier chapters. Short drafts skip the screen. A screen answer that fails its
contract twice makes its part reviewed whole, never silently skipped; one claim's contract failure
costs only that claim.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from app import review_screening as screening
from app.engine import ContinuityEngine, PROMPT_VERSION, RETRIEVAL_METHOD_VERSION, REVIEW_PIPELINE_ENV, SCREENED_PROMPT_VERSION
from app.provider import ProviderResult, ProviderTimeout, input_budget_units_for, request_prompt_and_budget

FILLER = "".join(f"港口第{i}天照常开工，搬运工把货箱码在三号仓库门口。" for i in range(30))
CHAPTERS = {
    1: FILLER[:500] + "林默的左手缺了一根小指，是少年时在船坞留下的伤。" + FILLER[500:],
    2: FILLER[:300] + "银钥匙由守塔人保管，任何人不得私自取用。" + FILLER[300:],
    3: "林默后来在第三章换了一把新伞。" + FILLER[:400],
}


def sources(chapters=CHAPTERS):
    return [{"id": f"span-{n}", "chapter_id": f"chapter-{n}", "chapter_number": n, "label": f"第{n}章", "body": body} for n, body in chapters.items()]


MEMORY = [
    {"id": "mem-hand", "memory_type": "static_canon", "subject": "林默", "predicate": "identity", "value": "左手缺了一根小指", "source_span_id": "span-1"},
    {"id": "mem-key", "memory_type": "dynamic_state", "subject": "银钥匙", "predicate": "possession", "value": "由守塔人保管", "source_span_id": "span-2"},
    {"id": "mem-umbrella", "memory_type": "dynamic_state", "subject": "林默", "predicate": "possession", "value": "换了一把新伞", "source_span_id": "span-3"},
]


def draft_data(sentences: list[str], chapter_number=None, context_sources=None):
    body = "".join(sentences)
    claims = [{"id": f"claim-{i}", "text": text, "context": "draft"} for i, text in enumerate(sentences, 1)]
    if chapter_number is not None:
        claims = [{**claim, "chapter_number": chapter_number} for claim in claims]
    return {"pipeline": "screened", "draft": {"id": "draft-1", "revision": 1, "body": body}, "claims": claims,
            "memory": MEMORY, "sources": context_sources or sources(), "contexts": {"draft": body}}


NEUTRAL = [f"雨停后第{i}个钟头，码头上的人渐渐散了。" for i in range(1, 9)]
HAND = "林默张开左手，五根手指都在。"


def issue(claim, span, extra_spans=()):
    cited = [span, *extra_spans]
    return {"claim_span_id": claim["id"], "status": "conflict", "nature": "possible_conflict", "category": "attribute", "severity": "medium",
            "explanation": "手部描述前后不一。", "reasoning": "早前段落写缺一根小指，此句写五指都在，时间关系未知。",
            "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
            "evidence": [{"chapter_id": item["chapter_id"], "span_id": item["id"], "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []} for item in cited],
            "evidence_chain": [{"span_id": item["id"], "role": "prior_state"} for item in cited],
            "suggested_revision": None, "available_actions": ["keep_intentional"], "proposed_memory_change": None}


class Fake:
    available = True
    continuity_contract_version = "v6"
    label = model_label = "lf-screened-fake"

    def __init__(self, flag=lambda request: [], screen_answers=None, review=None, triage_answers=None):
        self.flag, self.screen_answers, self.review = flag, list(screen_answers or []), review
        self.triage_answers = list(triage_answers or [])
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        if request.get("task") == "continuity_screen":
            if self.screen_answers:
                answer = self.screen_answers.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                return ProviderResult(answer, input_tokens=10, output_tokens=2)
            return ProviderResult({"flags": self.flag(request)}, input_tokens=10, output_tokens=2)
        if request.get("task") == "continuity_triage":
            if self.triage_answers:
                return ProviderResult(self.triage_answers.pop(0), input_tokens=5, output_tokens=1)
            return ProviderResult({"scores": [{"id": s["id"], "score": 3 if "手指" in s["text"] else 1} for s in request["sentences"]]},
                                  input_tokens=5, output_tokens=1)
        if self.review:
            return self.review(request)
        issues = []
        for claim in request["claims"]:
            hand = next((span for span in claim["allowed_evidence"] if "小指" in span["prompt_excerpt"]), None)
            if "五根手指" in claim["text"] and hand:
                issues.append(issue(claim, hand))
        verdicts = [{"claim_span_id": claim["id"], "verdict": "reviewed_issue" if any(i["claim_span_id"] == claim["id"] for i in issues) else "no_issue",
                     "basis": "依据早前段落判断。"} for claim in request["claims"]]
        return ProviderResult({"issues": issues, "claim_verdicts": verdicts}, input_tokens=100, output_tokens=20)

    def reviews(self):
        return [request for request in self.requests if request.get("task") is None]


def flag_hand(request):
    hand_fact = next((fact["id"] for fact in request["facts"] if "小指" in fact["value"]), None)
    return [{"id": sentence["id"], "kind": "conflict", "facts": [hand_fact] if hand_fact else []}
            for sentence in request["sentences"] if "手指" in sentence["text"]]


class ScreenedReviewTests(unittest.TestCase):
    def test_a_long_draft_is_screened_and_only_flagged_sentences_are_reviewed(self):
        provider = Fake(flag=flag_hand)
        result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len([r for r in provider.requests if r.get("task") == "continuity_screen"]), 1)
        reviewed = [claim["id"] for request in provider.reviews() for claim in request["claims"]]
        self.assertEqual(reviewed, ["claim-5"])
        self.assertEqual(result["screening"], {"claims": 9, "screened": True, "parts": 1, "fallback_parts": 0, "flagged": 1, "reviewed": 1,
                                               "triaged": 0, "triage_fallback_batches": 0, "escalated": 0, "deep_reviewed": 1, "safety_net": 0,
                                               "double_reviewed": 0, "second_look": 0, "second_look_found": 0})
        self.assertEqual(result["retrieval_method_version"], screening.SCREENED_RETRIEVAL_METHOD_VERSION)
        states = {row["claim_id"]: row["screen"] for row in result["retrieval_traces"]}
        self.assertEqual(states["claim-5"], "flagged")
        self.assertEqual(set(states.values()), {"flagged", "passed"})
        self.assertTrue(all(not row["returned_span_ids"] for row in result["retrieval_traces"] if row["screen"] == "passed"))
        # Screen and review usage are both counted.
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (110, 22))
        self.assertEqual([item["claim_span_id"] for item in result["issues"]], ["claim-5"])

    def test_check_flags_are_triaged_and_only_what_the_triage_flags_gets_a_thinking_review(self):
        provider = Fake(flag=lambda request: [{"id": s["id"], "kind": "check", "facts": []} for s in request["sentences"]])
        result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        triage = [r for r in provider.requests if r.get("task") == "continuity_triage"]
        self.assertEqual([len(r["sentences"]) for r in triage], [screening.TRIAGE_MAX_CLAIMS, 9 - screening.TRIAGE_MAX_CLAIMS])
        # Each passage appears once per triage request; sentences list the ones they may use.
        self.assertTrue(all(len({p["id"] for p in r["passages"]}) == len(r["passages"]) for r in triage))
        self.assertTrue(all(set(s["passages"]) <= {p["id"] for p in r["passages"]} for r in triage for s in r["sentences"]))
        self.assertEqual([claim["id"] for r in provider.reviews() for claim in r["claims"]], ["claim-5"])
        self.assertEqual((result["screening"]["triaged"], result["screening"]["escalated"], result["screening"]["deep_reviewed"]), (9, 1, 1))
        self.assertEqual([item["claim_span_id"] for item in result["issues"]], ["claim-5"])
        paths = {row["claim_id"]: row.get("review") for row in result["retrieval_traces"]}
        self.assertEqual((paths["claim-5"], paths["claim-1"]), ("escalated", "triage"))
        # Usage of the screen, both triage requests and the thinking review.
        self.assertEqual(result["input_tokens"], 10 + 2 * 5 + 100)

    def test_parallel_triage_dispatches_keep_the_callers_context(self):
        import contextvars
        marker = contextvars.ContextVar("lf_triage_marker", default=None)

        class Guarded(Fake):
            continuity_batch_concurrency = 4

            def evaluate(self, request):
                if marker.get() != "set":
                    raise AssertionError("dispatch lost the caller's context")
                return super().evaluate(request)
        provider = Guarded(flag=lambda request: [{"id": s["id"], "kind": "check", "facts": []} for s in request["sentences"]])
        token = marker.set("set")
        try:
            result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:] + NEUTRAL[:4]))
        finally:
            marker.reset(token)
        self.assertEqual(result["status"], "completed")
        self.assertGreater(len([r for r in provider.requests if r.get("task") == "continuity_triage"]), 1)

    def test_a_triage_answer_failing_twice_sends_its_claims_to_thinking_review(self):
        provider = Fake(flag=lambda request: [{"id": s["id"], "kind": "check", "facts": []} for s in request["sentences"][:3]],
                        triage_answers=[{"wrong": 1}, {"scores": [{"id": "s1", "score": 1}]}])
        result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        repair = [r for r in provider.requests if r.get("task") == "continuity_triage"][1]
        self.assertEqual(repair["triage_repair"], {"reason_code": "triage_shape_invalid"})
        # The second answer left two of the three sentences unscored, so the batch falls back.
        self.assertEqual(result["screening"]["triage_fallback_batches"], 1)
        self.assertEqual(sorted(claim["id"] for r in provider.reviews() for claim in r["claims"]), ["claim-1", "claim-2", "claim-3"])

    def test_screen_and_triage_run_without_thinking(self):
        from app.provider import DeepSeekProvider
        with mock.patch.dict(os.environ, {"CONTINUITY_REVIEW_THINKING": "high"}):
            provider = DeepSeekProvider()
        for task in ("continuity_screen", "continuity_triage"):
            body = provider.request_body({"task": task}, "{}")
            self.assertEqual((body["thinking"], body["max_tokens"]), ({"type": "disabled"}, 4000))
        deep = provider.request_body({"pipeline": "screened"}, "{}")
        self.assertEqual((deep["thinking"], deep["reasoning_effort"], deep["max_tokens"]), ({"type": "enabled"}, "high", 8000))

    def test_a_passed_conflict_or_gap_flag_gets_a_missing_link_second_look(self):
        def review(request):
            claim = request["claims"][0]
            span = claim["allowed_evidence"][0]
            verdict = lambda kind: [{"claim_span_id": claim["id"], "verdict": kind, "basis": "见引用。"}]
            if not request.get("second_look"):
                return ProviderResult({"issues": [], "claim_verdicts": verdict("no_issue")}, input_tokens=100, output_tokens=10)
            if "手指" in claim["text"]:
                gap = issue(claim, span)
                gap.update(status="insufficient_evidence", nature="insufficient_evidence", available_actions=[])
                gap["evidence"][0].update(relation="context", sufficiency="insufficient")
                gap["evidence_chain"][0]["role"] = "missing_link"
                return ProviderResult({"issues": [gap], "claim_verdicts": verdict("insufficient_evidence")}, input_tokens=100, output_tokens=10)
            # A conflict from the second look is not taken.
            return ProviderResult({"issues": [issue(claim, span)], "claim_verdicts": verdict("reviewed_issue")}, input_tokens=100, output_tokens=10)
        provider = Fake(flag=lambda request: [{"id": s["id"], "kind": "gap", "facts": []} for s in request["sentences"][3:5]], review=review)
        with mock.patch.object(screening, "SECOND_LOOK", True):
            result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        second = [r for r in provider.reviews() if r.get("second_look")]
        self.assertEqual(sorted(r["claims"][0]["id"] for r in second), ["claim-4", "claim-5"])
        self.assertEqual([(i["claim_span_id"], i["nature"]) for i in result["issues"]], [("claim-5", "insufficient_evidence")])
        self.assertEqual((result["screening"]["second_look"], result["screening"]["second_look_found"]), (2, 1))
        self.assertEqual(result["input_tokens"], 10 + 4 * 100)

    def test_a_finding_from_either_review_of_a_key_sentence_counts(self):
        def review(request):
            claim = request["claims"][0]
            span = claim["allowed_evidence"][0]
            verdict = lambda kind: [{"claim_span_id": claim["id"], "verdict": kind, "basis": "见引用。"}]
            if claim["id"].endswith("#pass2") and "手指" in claim["text"]:
                return ProviderResult({"issues": [issue(claim, span)], "claim_verdicts": verdict("reviewed_issue")}, input_tokens=1, output_tokens=1)
            return ProviderResult({"issues": [], "claim_verdicts": verdict("no_issue")}, input_tokens=1, output_tokens=1)
        provider = Fake(flag=lambda request: [{"id": s["id"], "kind": "conflict", "facts": []} for s in request["sentences"][3:5]], review=review)
        with mock.patch.object(screening, "DOUBLE_REVIEW", True):
            result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        self.assertEqual([(i["claim_span_id"], i["nature"]) for i in result["issues"]], [("claim-5", "possible_conflict")])
        self.assertEqual((result["screening"]["double_reviewed"], result["screening"]["double_found"]), (2, 1))
        # The missing-link second look is off while key sentences are reviewed twice.
        self.assertFalse([r for r in provider.reviews() if r.get("second_look")])

    def test_deep_reviews_carry_one_claim_each(self):
        provider = Fake(flag=lambda request: [{"id": s["id"], "kind": "conflict", "facts": []} for s in request["sentences"]])
        ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        self.assertTrue(provider.reviews())
        self.assertTrue(all(len(r["claims"]) == 1 for r in provider.reviews()))

    def test_evidence_is_bound_back_to_the_source_span_with_the_passage_text(self):
        provider = Fake(flag=flag_hand)
        result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        evidence = result["issues"][0]["evidence"]
        self.assertEqual([item["span_id"] for item in evidence], ["span-1"])
        self.assertIn("缺了一根小指", evidence[0]["excerpt"])
        self.assertLess(len(evidence[0]["excerpt"]), len(CHAPTERS[1]))
        self.assertEqual(result["issues"][0]["evidence_chain"], [{"span_id": "span-1", "role": "prior_state"}])
        review = provider.reviews()[0]
        self.assertEqual(review["pipeline"], "screened")
        self.assertEqual(review["draft"]["body"], "".join(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        # The cited fact's passage leads the evidence and the fact leads the related Memory.
        self.assertIn("小指", review["claims"][0]["allowed_evidence"][0]["prompt_excerpt"])
        self.assertEqual(review["memory"][0]["id"], "mem-hand")

    def test_two_passages_of_one_span_become_one_evidence_item(self):
        def review(request):
            claim = request["claims"][0]
            spans = [span for span in claim["allowed_evidence"] if span["source_span_id"] == "span-1"][:2]
            self.assertEqual(len(spans), 2)
            return ProviderResult({"issues": [issue(claim, spans[0], spans[1:])],
                                   "claim_verdicts": [{"claim_span_id": claim["id"], "verdict": "reviewed_issue", "basis": "见引用。"}]}, input_tokens=1, output_tokens=1)
        with mock.patch.object(screening, "VERIFY_PASSAGE_CHARS", 5000):
            result = ContinuityEngine(Fake(review=review)).execute(draft_data(["港口码头搬运工林默张开左手，五根手指都在。"]))
        evidence = result["issues"][0]["evidence"]
        self.assertEqual([item["span_id"] for item in evidence], ["span-1"])
        self.assertIn("…", evidence[0]["excerpt"])
        self.assertEqual(result["issues"][0]["evidence_chain"], [{"span_id": "span-1", "role": "prior_state"}])

    def test_a_short_draft_skips_the_screen(self):
        provider = Fake(flag=lambda request: self.fail("a short draft is not screened"))
        result = ContinuityEngine(provider).execute(draft_data([HAND, NEUTRAL[0]]))
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["screening"]["screened"])
        self.assertEqual({row["screen"] for row in result["retrieval_traces"]}, {"unscreened"})
        self.assertEqual(len(result["issues"]), 1)

    def test_a_screen_answer_failing_twice_reviews_its_part_whole(self):
        provider = Fake(screen_answers=[{"wrong": []}, {"flags": [{"id": "s99", "kind": "gap", "facts": []}]}])
        result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["screening"]["fallback_parts"], 1)
        self.assertEqual(result["screening"]["flagged"], 9)
        repair = [r for r in provider.requests if r.get("task") == "continuity_screen"][1]
        self.assertEqual(repair["screen_repair"], {"reason_code": "screen_shape_invalid"})
        self.assertEqual(len(result["issues"]), 1)

    def test_a_repaired_screen_answer_is_used(self):
        provider = Fake(screen_answers=[{"flags": "none"}, {"flags": [{"id": "s5", "kind": "conflict", "facts": ["f999"]}]}])
        result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        self.assertEqual(result["screening"]["fallback_parts"], 0)
        self.assertEqual([claim["id"] for request in provider.reviews() for claim in request["claims"]], ["claim-5"])

    def test_a_malformed_review_answer_costs_only_its_claims(self):
        from app.provider import ProviderInvalidJson
        calls = []
        def review(request):
            calls.append([claim["id"] for claim in request["claims"]])
            if any(claim["id"].startswith(bad) for claim in request["claims"] for bad in ("claim-5", "claim-6#")):
                raise ProviderInvalidJson(1, 1, None, 1, "stop")
            return ProviderResult({"issues": [], "claim_verdicts": [{"claim_span_id": c["id"], "verdict": "no_issue", "basis": "见引用。"} for c in request["claims"]]}, input_tokens=1, output_tokens=1)
        provider = Fake(flag=lambda request: [{"id": s["id"], "kind": "conflict", "facts": []} for s in request["sentences"][3:6]], review=review)
        result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["undecided_claims"], [{"claim_span_id": "claim-5", "error_code": "invalid_json"}])
        with mock.patch.object(screening, "DOUBLE_REVIEW", True):
            doubled = ContinuityEngine(Fake(flag=provider.flag, review=review)).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        # Reviewed twice: both reviews of claim-5 failed, so it is undecided; only claim-6's second failed, so it is decided.
        self.assertEqual(doubled["undecided_claims"], [{"claim_span_id": "claim-5", "error_code": "invalid_json"}])

    def test_a_screen_timeout_fails_the_run_as_timed_out(self):
        provider = Fake(screen_answers=[ProviderTimeout()])
        result = ContinuityEngine(provider).execute(draft_data(NEUTRAL[:4] + [HAND] + NEUTRAL[4:]))
        self.assertEqual((result["status"], result["error_code"]), ("timed_out", "provider_timeout"))
        self.assertFalse(provider.reviews())

    def test_a_claim_of_chapter_n_sees_nothing_from_chapter_n_or_later(self):
        provider = Fake(flag=lambda request: [{"id": s["id"], "kind": "check", "facts": [f["id"] for f in request["facts"]][:3]} for s in request["sentences"]])
        ContinuityEngine(provider).execute(draft_data(["林默撑着新伞走过银钥匙所在的塔下，左手五根手指都在。"], chapter_number=2))
        review = provider.reviews()[0]
        self.assertTrue(all(span["chapter_number"] < 2 for claim in review["claims"] for span in claim["allowed_evidence"]))
        self.assertEqual({item["id"] for item in review["memory"]} - {"mem-hand"}, set())

    def test_a_plain_contract_failure_costs_only_its_claim(self):
        def review(request):
            issues, verdicts = [], []
            for claim in request["claims"]:
                hand = claim["allowed_evidence"][0]
                bad = issue(claim, hand)
                if claim["id"] == "claim-2":
                    bad["severity"] = "catastrophic"  # schema_invalid, a plain ValueError
                issues.append(bad)
                verdicts.append({"claim_span_id": claim["id"], "verdict": "reviewed_issue", "basis": "见引用。"})
            return ProviderResult({"issues": issues, "claim_verdicts": verdicts}, input_tokens=1, output_tokens=1)
        sentences = ["林默张开左手，五根手指都在。", "林默的左手五根手指齐全。", "林默数了数左手，五根手指。"]
        result = ContinuityEngine(Fake(review=review)).execute(draft_data(sentences))
        self.assertEqual(result["status"], "completed")
        self.assertEqual([row["claim_span_id"] for row in result["undecided_claims"]], ["claim-2"])
        self.assertEqual(result["undecided_claims"][0]["error_code"], "schema_invalid")
        self.assertEqual([item["claim_span_id"] for item in result["issues"]], ["claim-1", "claim-3"])

    def test_screen_and_screened_review_requests_fit_their_larger_budgets(self):
        provider = Fake(flag=flag_hand)
        long_chapters = {n: body * 3 for n, body in CHAPTERS.items()}
        ContinuityEngine(provider).execute(draft_data(NEUTRAL * 3 + [HAND], context_sources=sources(long_chapters)))
        for request in provider.requests:
            self.assertLessEqual(request_prompt_and_budget(request)[1], input_budget_units_for(request))


class TemporalSettlementTests(unittest.TestCase):
    RULE = {"id": "mem-rule", "memory_type": "static_canon", "subject": "银钥匙", "predicate": "rule", "value": "任何人不得私自取用", "source_span_id": "span-2"}

    def confirmed(self, relation, related):
        def review(request):
            claim = request["claims"][0]
            span = next(s for s in claim["allowed_evidence"] if s["source_span_id"] == "span-2")
            raw = issue(claim, span)
            raw.update(nature="confirmed_conflict", category="world_rule",
                       temporal_basis={"claim_anchor": None, "evidence_anchor": None, "relation": relation})
            raw["evidence"][0]["related_memory_ids"] = related
            return ProviderResult({"issues": [raw], "claim_verdicts": [{"claim_span_id": claim["id"], "verdict": "reviewed_issue", "basis": "见引用。"}]}, input_tokens=1, output_tokens=1)
        provider = Fake(review=review)
        data = draft_data(["林默私自取用了守塔人保管的银钥匙。"])
        data["memory"] = MEMORY + [self.RULE]
        return provider, ContinuityEngine(provider).execute(data)

    def test_a_rule_cited_through_a_passage_of_its_span_proves_a_timeless_conflict(self):
        self.assertGreater(len(screening.split_passages(CHAPTERS[2], span_id="span-2", chapter_id="c", chapter_number=2)), 1)
        provider, result = self.confirmed("timeless_rule", ["mem-rule"])
        self.assertEqual(result["issues"][0]["nature"], "confirmed_conflict")
        self.assertEqual(len(provider.reviews()), 1)

    def test_an_unproved_shared_time_is_settled_as_possible_conflict_without_a_repair(self):
        provider, result = self.confirmed("explicit_overlap", [])
        self.assertEqual((result["issues"][0]["status"], result["issues"][0]["nature"]), ("conflict", "possible_conflict"))
        self.assertEqual(len(provider.reviews()), 1)
        self.assertEqual(result["contract_normalizations"][0]["outcome"], "possible_conflict")


class TemporalScopeTests(unittest.TestCase):
    def test_a_period_word_is_not_a_second_clock(self):
        from app.engine import _full_temporal_scope_supports_conflict
        claim = "九月十四日二十二时，陶铎还坐在南凹站值班室里，就着热水泡开一盒面。"
        evidence = "九月十四日二十二时，陶铎始终在北砾坡驾驶救援车，车载定位连续记录了这一时段的位置。"
        self.assertTrue(_full_temporal_scope_supports_conflict(claim, evidence, "九月十四日二十二时", "九月十四日二十二时"))

    def test_a_stated_span_starting_at_the_claims_clock_qualifies(self):
        from app.engine import _full_temporal_scope_supports_conflict
        claim = "六月三日十六时，许砚舟正蹲在潮尺巷邮务所的柜台底下掏旧挂号单。"
        evidence = "六月三日十六时，许砚舟一直在区邮务处参加退休档案核对，现场签到了十七时才离开。"
        self.assertTrue(_full_temporal_scope_supports_conflict(claim, evidence, "六月三日十六时", "六月三日十六时"))
        # A claim at another clock of the span is not proved by an anchor at the first one.
        other = "六月三日十七时，许砚舟正蹲在潮尺巷邮务所的柜台底下掏旧挂号单。"
        self.assertFalse(_full_temporal_scope_supports_conflict(other, evidence, "六月三日十七时", "六月三日十六时"))


class PipelineSwitchTests(unittest.TestCase):
    def test_provenance_follows_the_rollback_switch(self):
        engine = ContinuityEngine(Fake())
        with mock.patch.dict(os.environ, {REVIEW_PIPELINE_ENV: ""}):
            self.assertEqual((engine.provenance()["prompt_version"], engine.provenance()["retrieval_method_version"]),
                             (SCREENED_PROMPT_VERSION, screening.SCREENED_RETRIEVAL_METHOD_VERSION))
        with mock.patch.dict(os.environ, {REVIEW_PIPELINE_ENV: "legacy"}):
            self.assertEqual((engine.provenance()["prompt_version"], engine.provenance()["retrieval_method_version"]),
                             (PROMPT_VERSION, RETRIEVAL_METHOD_VERSION))


class PureHelperTests(unittest.TestCase):
    def test_triage_escalates_the_highest_scores_up_to_the_cap(self):
        claims = [{"id": f"c{i}", "context": "draft"} for i in range(10)]
        scores = {f"c{i}": score for i, score in enumerate([3, 2, 2, 2, 2, 2, 2, 1, 0, 3])}
        escalated = screening.triage_escalations(claims, scores)
        self.assertEqual(len(escalated), screening.TRIAGE_ESCALATION_CAP)
        self.assertTrue({"c0", "c9"} <= escalated)
        self.assertFalse({"c7", "c8"} & escalated)
        self.assertEqual(escalated - {"c0", "c9"}, {f"c{i}" for i in range(1, screening.TRIAGE_ESCALATION_CAP - 1)})

    def test_parse_triage_requires_a_score_for_every_sentence(self):
        ids = {"s1": "claim-1", "s2": "claim-2"}
        self.assertEqual(screening.parse_triage({"scores": [{"id": "s1", "score": 2}, {"id": "s2", "score": 0}]}, ids), {"claim-1": 2, "claim-2": 0})
        for bad in ({"scores": [{"id": "s1", "score": 2}]}, {"scores": [{"id": "s1", "score": 5}, {"id": "s2", "score": 0}]},
                    {"scores": [{"id": "s9", "score": 1}, {"id": "s2", "score": 0}]}, {"suspicious": []}):
            with self.assertRaises(screening.ScreenContractError):
                screening.parse_triage(bad, ids)

    def test_context_window_keeps_short_text_and_windows_long_text(self):
        self.assertEqual(screening.context_window("短文。", ["短文。"]), "短文。")
        text = "甲" * 5000 + "目标句。" + "乙" * 5000
        window = screening.context_window(text, ["目标句。"])
        self.assertIn("目标句。", window)
        self.assertLess(len(window), 2 * screening.VERIFY_CONTEXT_MARGIN + 10)

    def test_screen_parts_never_mix_contexts_and_stay_within_the_limit(self):
        claims = [{"id": f"c{i}", "text": "字" * 900, "context": "a" if i < 5 else "b"} for i in range(8)]
        parts = screening.screen_parts(claims)
        self.assertTrue(all(len({claim["context"] for claim in part}) == 1 for part in parts))
        self.assertTrue(all(sum(len(claim["text"]) for claim in part) <= screening.SCREEN_PART_CHARS for part in parts))
        self.assertEqual([claim["id"] for part in parts for claim in part], [f"c{i}" for i in range(8)])

    def test_parse_screen_drops_unknown_facts_and_merges_repeats(self):
        flags = screening.parse_screen({"flags": [{"id": "s1", "kind": "odd", "facts": ["f1", "f9"]}, {"id": "s1", "kind": "gap", "facts": ["f2"]}]},
                                       {"s1": "claim-1"}, {"f1": "mem-1", "f2": "mem-2"})
        self.assertEqual(flags, {"claim-1": {"kind": "check", "facts": ["mem-1", "mem-2"]}})
        with self.assertRaises(screening.ScreenContractError):
            screening.parse_screen({"flags": [{"id": "s2"}]}, {"s1": "claim-1"}, {})


if __name__ == "__main__":
    unittest.main()
