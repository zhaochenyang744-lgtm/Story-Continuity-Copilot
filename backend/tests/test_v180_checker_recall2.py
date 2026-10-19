"""07t-2: a claim's own contract fault never fails the check, and a reserved fact's source reaches the review.

1  the repair answer being unusable keeps the first answer's conflict (as a possible one) or leaves the claim undecided;
   a short draft whose every claim is undecided for such a fault still completes;
2  the passage a reserved state fact stands on is added to the claim's passages, within the input budget.
No model is called: providers are scripted in memory.
"""
from __future__ import annotations

import copy
import unittest
from unittest import mock

from app import engine as engine_module
from app import review_screening as screening
from app.engine import ContinuityEngine, SCREENED_RELATED_MEMORY_LIMIT, SOURCE_PASSAGES_PER_CLAIM
from app.provider import ProviderInvalidJson, ProviderResult, request_prompt_and_budget

from tests.test_v180_checker_recall import (
    CHAPTER_1, CHAPTER_2, CLAIM, CLAIM_TEXT, MEMORY_1, MEMORY_2, SPAN_1, SPAN_1_BODY, SPAN_2, SPAN_2_BODY,
    Legacy, Scripted, answer, direct_answer, evidence, screened_data,
)

OTHER = "claim-07t-2"


def sid(number):
    """Span ids at least five characters apart, so no id is mistaken for another by the one-character correction."""
    return f"span-{str(number) * 5}"
OTHER_TEXT = "少年点了点头，没有再说话。"


def mismatch(verdict="insufficient_evidence", claim=CLAIM):
    """The repair answer of the logged check: no issue, yet a verdict that needs one."""
    return {"issues": [], "claim_verdicts": [{"claim_span_id": claim, "verdict": verdict, "basis": "证据不足以判断。"}]}


def not_direct():
    return answer([evidence(relation="context", memory=[MEMORY_1])])


def clean(claim):
    return {"issues": [], "claim_verdicts": [{"claim_span_id": claim, "verdict": "no_issue", "basis": "没有矛盾。"}]}


def full_data(claims=None, extra_sources=()):
    """The input of a whole check (a short draft, so every sentence is reviewed): sources, not yet passages."""
    sources = [{"id": SPAN_1, "chapter_id": CHAPTER_1, "chapter_number": 1, "body": SPAN_1_BODY},
               {"id": SPAN_2, "chapter_id": CHAPTER_2, "chapter_number": 2, "body": SPAN_2_BODY}, *extra_sources]
    claims = claims or [{"id": CLAIM, "text": CLAIM_TEXT, "chapter_number": 5, "context": "draft"}]
    body = "".join(claim["text"] for claim in claims)
    return {"pipeline": "screened", "claims": claims, "sources": sources, "contexts": {"draft": body},
            "memory": copy.deepcopy(screened_data()["memory"]), "draft": {"id": "draft-07t", "revision": 1, "body": body}}


def batch_of(data):
    engine = ContinuityEngine(Scripted())
    return engine, engine._screened_request(data["claims"], data, (3, SCREENED_RELATED_MEMORY_LIMIT))


class FirstAnswerKeptTests(unittest.TestCase):
    def run_batch(self, *answers, provider_class=Scripted, data=None):
        provider = provider_class(*answers)
        engine = ContinuityEngine(provider)
        data = data or screened_data()
        batch = engine._screened_request(data["claims"], data, (3, SCREENED_RELATED_MEMORY_LIMIT))
        return provider, engine._review_batch(batch, data, 10 ** 9)

    def test_the_logged_failure_keeps_the_first_conflict_as_a_possible_one(self):
        # fix-02, third check: the first answer cites the fact (context) -> repair -> the repair says
        # insufficient_evidence with no issue: claim_verdicts_issue_mismatch.
        with self.assertRaisesRegex(ValueError, "claim_verdicts_issue_mismatch"):
            ContinuityEngine(Scripted()).validate(mismatch(), screened_data(), allow_conservative_temporal_normalization=True)
        provider, outcome = self.run_batch(not_direct(), mismatch())
        self.assertEqual(len(provider.requests), 2)
        self.assertNotIn("undecided", outcome)
        issue = outcome["issues"][0]
        self.assertEqual((issue["status"], issue["nature"]), ("conflict", "possible_conflict"))
        self.assertEqual([(row["span_id"], row["relation"], row["related_memory_ids"]) for row in issue["evidence"]], [(SPAN_1, "context", [MEMORY_1])])
        self.assertEqual([(row["reason_code"], row["outcome"], row["provider_attempt"]) for row in outcome["normalizations"]],
                         [("kept_as_possible_after_repair", "possible_conflict", 1)])

    def test_any_unusable_repair_answer_keeps_the_first_answer(self):
        for second in (mismatch(), mismatch("reviewed_issue"), {"issues": []}, {"claim_verdicts": []}, "nonsense", {"issues": [{"claim_span_id": CLAIM}], "claim_verdicts": []}):
            with self.subTest(second=second):
                _, outcome = self.run_batch(not_direct(), second)
                self.assertEqual(outcome["issues"][0]["nature"], "possible_conflict")
                self.assertNotIn("undecided", outcome)

    def test_a_first_answer_that_fails_for_another_reason_leaves_the_claim_undecided(self):
        # Not one of the three citation faults.
        wordy = not_direct()
        wordy["issues"][0]["reasoning"] = "矛盾" * 500
        _, outcome = self.run_batch(wordy, mismatch())
        self.assertEqual(outcome["undecided"], [{"claim_span_id": CLAIM, "error_code": "claim_verdicts_issue_mismatch"}])
        self.assertNotIn("issues", outcome)
        # Nothing citable at all.
        nothing = answer([evidence(span="span-not-supplied-at-all", relation="context")], chain=[{"span_id": "span-not-supplied-at-all", "role": "prior_state"}])
        _, outcome = self.run_batch(nothing, mismatch())
        self.assertEqual(outcome["undecided"][0]["error_code"], "claim_verdicts_issue_mismatch")
        # A verdict other than reviewed_issue, or a status other than conflict.
        _, outcome = self.run_batch(answer([evidence(relation="context", memory=[MEMORY_1])], verdict="insufficient_evidence"), mismatch())
        self.assertEqual(outcome["undecided"][0]["error_code"], "claim_verdicts_issue_mismatch")

    def test_a_first_answer_whose_own_ledger_is_inconsistent_is_not_kept(self):
        first = not_direct()
        first["claim_verdicts"][0]["verdict"] = "no_issue"
        _, outcome = self.run_batch(first, mismatch())
        self.assertEqual(outcome["undecided"][0]["error_code"], "claim_verdicts_issue_mismatch")

    def test_a_provider_without_verdicts_keeps_nothing(self):
        payload = {"issues": not_direct()["issues"]}
        _, outcome = self.run_batch(payload, {"issues": "x"}, provider_class=Legacy)
        self.assertEqual(outcome["undecided"][0]["error_code"], "schema_invalid")

    def test_a_good_repair_is_used_as_before(self):
        provider, outcome = self.run_batch(not_direct(), direct_answer())
        self.assertEqual(outcome["issues"][0]["nature"], "confirmed_conflict")
        self.assertEqual(outcome["normalizations"], [])

    def test_a_repair_too_large_to_send_keeps_the_first_answer_of_a_lone_claim(self):
        real = engine_module.request_prompt_and_budget
        def sized(request):
            prompt, units = real(request)
            return prompt, units + (10 ** 7 if "contract_repair" in request else 0)
        with mock.patch.object(engine_module, "request_prompt_and_budget", sized):
            provider, outcome = self.run_batch(not_direct())
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(outcome["issues"][0]["nature"], "possible_conflict")
        # Without a first answer worth keeping it stays undecided, as before.
        wordy = not_direct()
        wordy["issues"][0]["reasoning"] = "矛盾" * 500
        with mock.patch.object(engine_module, "request_prompt_and_budget", sized):
            _, outcome = self.run_batch(wordy)
        self.assertEqual(outcome["undecided"], [{"claim_span_id": CLAIM, "error_code": "input_budget_exceeded"}])

    def test_two_issues_for_one_claim_are_that_claims_fault_in_the_screened_pipeline(self):
        issue = direct_answer()["issues"][0]
        double = {"issues": [issue, copy.deepcopy(issue)]}
        _, outcome = self.run_batch(double, double, provider_class=Legacy)
        self.assertEqual(outcome["undecided"], [{"claim_span_id": CLAIM, "error_code": "schema_invalid"}])
        # The legacy pipeline keeps its rule: the validator is not asked to refuse it.
        legacy = {**screened_data(), "pipeline": None}
        self.assertEqual(len(ContinuityEngine(Legacy()).validate({"issues": [issue]}, legacy)), 1)


class WholeCheckTests(unittest.TestCase):
    def execute(self, provider, data):
        return ContinuityEngine(provider).execute(data)

    def test_the_logged_check_completes_with_a_possible_conflict(self):
        provider = Scripted(not_direct(), mismatch())
        result = self.execute(provider, full_data())
        self.assertEqual(result["status"], "completed")
        self.assertEqual([(issue["claim_span_id"], issue["nature"]) for issue in result["issues"]], [(CLAIM, "possible_conflict")])
        self.assertEqual(result["undecided_claim_count"], 0)
        self.assertEqual([row["reason_code"] for row in result["contract_normalizations"]], ["kept_as_possible_after_repair"])

    def test_a_short_draft_whose_only_claim_is_undecided_completes(self):
        # Before: the one undecided claim was "every claim", and its error code became the run's failure.
        nothing = answer([evidence(span="span-not-supplied-at-all", relation="context")], chain=[{"span_id": "span-not-supplied-at-all", "role": "prior_state"}])
        result = self.execute(Scripted(nothing, mismatch()), full_data())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["undecided_claims"], [{"claim_span_id": CLAIM, "error_code": "claim_verdicts_issue_mismatch"}])
        self.assertEqual(result["undecided_claim_count"], 1)

    def test_a_failing_claim_does_not_touch_the_others(self):
        claims = [{"id": CLAIM, "text": CLAIM_TEXT, "chapter_number": 5, "context": "draft"},
                  {"id": OTHER, "text": OTHER_TEXT, "chapter_number": 5, "context": "draft"}]
        both_first = {"issues": not_direct()["issues"], "claim_verdicts": [clean(OTHER)["claim_verdicts"][0], not_direct()["claim_verdicts"][0]]}
        both_second = {"issues": [], "claim_verdicts": [clean(OTHER)["claim_verdicts"][0], mismatch()["claim_verdicts"][0]]}
        # The two together fail; each is then reviewed alone: the clean one is clean, the other is kept as possible.
        provider = Scripted(both_first, both_second, not_direct(), mismatch(), clean(OTHER))
        result = self.execute(provider, full_data(claims))
        self.assertEqual(len(provider.requests), 5)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([(issue["claim_span_id"], issue["nature"]) for issue in result["issues"]], [(CLAIM, "possible_conflict")])
        self.assertEqual(result["undecided_claims"], [])

    def test_every_claim_undecided_for_its_own_fault_is_not_a_failure_but_provider_stops_still_are(self):
        claims = [{"id": CLAIM, "text": CLAIM_TEXT, "chapter_number": 5, "context": "draft"},
                  {"id": OTHER, "text": OTHER_TEXT, "chapter_number": 5, "context": "draft"}]
        class Contradictory(Scripted):
            def evaluate(self, request):
                self.requests.append(copy.deepcopy(request))
                rows = [{"claim_span_id": claim["id"], "verdict": "reviewed_issue", "basis": "x"} for claim in request["claims"]]
                return ProviderResult({"issues": [], "claim_verdicts": rows}, input_tokens=1, output_tokens=1)
        result = self.execute(Contradictory(), full_data(claims))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["undecided_claim_count"], 2)

        class Malformed(Scripted):
            def evaluate(self, request):
                raise ProviderInvalidJson(finish_reason="stop")
        result = self.execute(Malformed(), full_data())
        self.assertEqual((result["status"], result["error_code"]), ("failed", "invalid_json"))
        class Truncated(Scripted):
            def evaluate(self, request):
                raise ProviderInvalidJson(finish_reason="length")
        result = self.execute(Truncated(), full_data())
        self.assertEqual((result["status"], result["error_code"]), ("failed", "output_truncated"))

    def test_two_issues_for_one_claim_do_not_fail_the_check(self):
        issue = not_direct()["issues"][0]
        double = {"issues": [issue, copy.deepcopy(issue)]}
        result = self.execute(Legacy(double, double), full_data())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["undecided_claims"], [{"claim_span_id": CLAIM, "error_code": "schema_invalid"}])


class SourcePassageTests(unittest.TestCase):
    NAME = "祝嵊禾"
    PASSAGE_KEYS = {"id", "chapter_id", "body", "prompt_excerpt", "source_span_id", "chapter_number", "passage_start"}

    def build(self, claim_spans=(), claim_text="祝嵊禾依然一个风字也不认识。", chapter_number=9, facts=None, aliases=None, with_index=True):
        """Eight chapters, one passage each; the facts say what is in chapters 2-4; the claim's own passages are `claim_spans`."""
        sources = [{"id": sid(n), "chapter_id": f"ch-{n}", "chapter_number": n, "body": f"第{n}章：祝嵊禾的风字课，编号{n}。"} for n in range(1, 9)]
        facts = facts if facts is not None else [
            {"id": "mem-a", "memory_type": "character_knowledge", "subject": self.NAME, "predicate": "knowledge", "value": "已能独立读懂短句风字", "source_span_id": sid(4)}]
        index = screening.build_index(sources, facts)
        claim = {"id": "claim-c", "text": claim_text, "chapter_number": chapter_number, "context": "draft",
                 "allowed_evidence": [screening.passage_entry(index.passages[n - 1]) for n in claim_spans]}
        data = {"pipeline": "screened", "memory": facts, "memory_chapters": screening.memory_chapters(sources, facts), "draft": {"id": "d", "revision": 1},
                "contexts": {"draft": claim_text}, "aliases": aliases or [], **({"passage_index": index} if with_index else {})}
        return claim, data, index

    def request(self, claim, data):
        return ContinuityEngine(Scripted())._screened_request([claim], data, (8, SCREENED_RELATED_MEMORY_LIMIT))

    def ids(self, request):
        return [span["id"] for span in request["claims"][0]["allowed_evidence"]]

    def test_the_source_of_a_reserved_fact_joins_the_claims_passages_in_the_same_shape(self):
        claim, data, index = self.build(claim_spans=[1])
        request = self.request(claim, data)
        self.assertEqual(self.ids(request), [sid(1), sid(4)])
        added = request["claims"][0]["allowed_evidence"][-1]
        self.assertEqual(set(added), self.PASSAGE_KEYS)
        self.assertEqual(added, screening.passage_entry(index.passages[3]))
        self.assertEqual(added["prompt_excerpt"], added["body"])
        self.assertIn("mem-a", [row["id"] for row in request["memory"]])

    def test_without_the_index_or_without_a_reserved_fact_nothing_is_added(self):
        claim, data, _ = self.build(claim_spans=[1], with_index=False)
        self.assertEqual(self.ids(self.request(claim, data)), [sid(1)])
        claim, data, _ = self.build(claim_spans=[1], claim_text="今天天气很好。", facts=[])
        self.assertEqual(self.ids(self.request(claim, data)), [sid(1)])
        # A fact about someone the claim does not name is not reserved, and so adds no passage.
        other = [{"id": "mem-z", "memory_type": "character_knowledge", "subject": "旁人", "predicate": "knowledge", "value": "不识风字", "source_span_id": sid(4)}]
        claim, data, _ = self.build(claim_spans=[1], facts=other)
        self.assertEqual(self.ids(self.request(claim, data)), [sid(1)])

    def test_a_passage_the_claim_already_has_is_not_added_twice(self):
        claim, data, _ = self.build(claim_spans=[1, 4])
        self.assertEqual(self.ids(self.request(claim, data)), [sid(1), sid(4)])

    def test_nothing_from_the_checked_chapter_or_later_is_added(self):
        late = [{"id": "mem-late", "memory_type": "character_knowledge", "subject": self.NAME, "predicate": "knowledge", "value": "能读风字", "source_span_id": sid(6)}]
        claim, data, index = self.build(claim_spans=[1], facts=late, chapter_number=6)
        self.assertEqual(self.ids(self.request(claim, data)), [sid(1)])
        # Even asked directly with a reserved fact from a later chapter.
        reserved = [late[0]]
        self.assertEqual(ContinuityEngine._source_passages(claim, reserved, index), [])
        later_claim = {**claim, "chapter_number": 7}
        self.assertEqual([row["id"] for row in ContinuityEngine._source_passages(later_claim, reserved, index)], [sid(6)])

    def test_the_slots_go_to_the_reserved_facts_closest_to_the_claim(self):
        # First A1c fix-02: the fact that she can now read short passages was reserved last (a later "knowledge" fact
        # about a route mark, tied on shared words, took the person's best and latest places), so its passage never came.
        facts = [
            {"id": "mem-route", "memory_type": "character_knowledge", "subject": self.NAME, "predicate": "knowledge", "value": "辨出浅刻标记指向悬汀洲外缘", "source_span_id": sid(7)},
            {"id": "mem-bag", "memory_type": "character_state", "subject": self.NAME, "predicate": "possession", "value": "袖袋里带着空白羽签", "source_span_id": sid(6)},
            {"id": "mem-promise", "memory_type": "character_state", "subject": self.NAME, "predicate": "status", "value": "答应先自己试着看路标", "source_span_id": sid(5)},
            {"id": "mem-read", "memory_type": "character_knowledge", "subject": self.NAME, "predicate": "knowledge", "value": "已能独立读懂短句风字", "source_span_id": sid(4)},
        ]
        claim, data, index = self.build(claim_spans=[1], claim_text="抵达悬汀洲后，祝嵊禾依然一个风字也不认识，短句都要旁人读。", facts=facts)
        reserved, _ = ContinuityEngine(Scripted())._related_parts(claim, facts, SCREENED_RELATED_MEMORY_LIMIT, data["memory_chapters"], [])
        self.assertNotEqual(reserved[0]["id"], "mem-read")
        self.assertIn(sid(4), self.ids(self.request(claim, data))[1:])

    def test_at_most_two_are_added_in_the_order_of_the_reserved_facts(self):
        names = ["祝嵊禾", "冯明远", "苏锦书"]
        facts = [{"id": f"mem-{n}", "memory_type": "character_knowledge", "subject": name, "predicate": "knowledge", "value": f"{name}的风字进境", "source_span_id": sid(n)}
                 for n, name in zip((2, 3, 4), names)]
        claim, data, index = self.build(claim_spans=[1], claim_text="祝嵊禾、冯明远和苏锦书都不认识风字。", facts=facts)
        request = self.request(claim, data)
        added = self.ids(request)[1:]
        self.assertEqual(len(added), SOURCE_PASSAGES_PER_CLAIM)
        reserved, _ = ContinuityEngine(Scripted())._related_parts(claim, [f for f in facts], SCREENED_RELATED_MEMORY_LIMIT, data["memory_chapters"], [])
        expected = [screening.fact_evidence(index, fact["id"])["id"] for fact in reserved][:2]
        self.assertEqual(added, expected)

    def test_a_request_over_budget_drops_the_last_added_passage_first_and_never_fails(self):
        names = ["祝嵊禾", "冯明远"]
        facts = [{"id": f"mem-{n}", "memory_type": "character_knowledge", "subject": name, "predicate": "knowledge", "value": f"{name}的风字进境", "source_span_id": sid(n)}
                 for n, name in zip((2, 3), names)]
        claim, data, index = self.build(claim_spans=[1], claim_text="祝嵊禾和冯明远都不认识风字。", facts=facts)
        sizes = {}
        for count in (0, 1, 2):
            with mock.patch.object(engine_module, "SOURCE_PASSAGES_PER_CLAIM", count):
                sizes[count] = request_prompt_and_budget(self.request(claim, data))[1]
        self.assertLess(sizes[0], sizes[1])
        self.assertLess(sizes[1], sizes[2])
        for budget, wanted in ((sizes[2], 2), (sizes[2] - 1, 1), (sizes[1], 1), (sizes[1] - 1, 0), (sizes[0], 0)):
            with self.subTest(budget=budget), mock.patch.object(engine_module, "input_budget_units_for", lambda request, repair=None, budget=budget: budget):
                request = self.request(claim, data)
                self.assertEqual(len(self.ids(request)) - 1, wanted)
                self.assertLessEqual(request_prompt_and_budget(request)[1], budget)
        # The request does not fit even without them: it is returned as it is (the caller splits or reduces it), nothing is raised.
        with mock.patch.object(engine_module, "input_budget_units_for", lambda request, repair=None: sizes[0] - 1):
            self.assertEqual(self.ids(self.request(claim, data)), [sid(1)])

    def test_the_review_can_cite_the_added_passage_as_direct_evidence(self):
        claim, data, _ = self.build(claim_spans=[1])
        engine = ContinuityEngine(Scripted())
        request = self.request(claim, data)
        claim_id = claim["id"]
        direct = {"issues": [{"claim_span_id": claim_id, "status": "conflict", "nature": "confirmed_conflict", "category": "character_knowledge", "severity": "high",
                              "explanation": "草稿说祝嵊禾不识风字，但此前她已能读懂短句风字。", "reasoning": "第四章写明她已能独立读懂短句风字，与草稿矛盾。",
                              "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
                              "evidence": [{"chapter_id": "ch-4", "span_id": sid(4), "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": ["mem-a"]}],
                              "evidence_chain": [{"span_id": sid(4), "role": "prior_state"}], "suggested_revision": None,
                              "available_actions": ["edit", "keep_intentional", "false_positive"], "proposed_memory_change": None}],
                  "claim_verdicts": [{"claim_span_id": claim_id, "verdict": "reviewed_issue", "basis": "依据第四章。"}]}
        engine.provider = Scripted(direct)
        outcome = engine._review_batch(request, {**data, "claims": [claim]}, 10 ** 9)
        self.assertEqual(len(engine.provider.requests), 1)
        self.assertEqual([(row["span_id"], row["relation"]) for row in outcome["issues"][0]["evidence"]], [(sid(4), "contradicts")])
        self.assertNotIn("kept_as_possible_after_repair", [row["reason_code"] for row in outcome["normalizations"]])
        # Without the added passage the same citation is not citable at all.
        claim, data, _ = self.build(claim_spans=[1], with_index=False)
        engine.provider = Scripted(direct, direct)
        outcome = engine._review_batch(self.request(claim, data), {**data, "claims": [claim]}, 10 ** 9)
        self.assertIn("undecided", outcome)

    def test_a_whole_check_sends_the_added_passage(self):
        provider = Scripted(clean(CLAIM))
        data = full_data()
        data["memory"] = [{"id": "mem-late", "memory_type": "character_knowledge", "subject": "少年", "predicate": "knowledge", "value": "母亲已出现", "source_span_id": SPAN_2}]
        data["claims"] = [{"id": CLAIM, "text": "少年依然不知道母亲已出现。", "chapter_number": 5, "context": "draft"}]
        # Retrieval alone brings the first chapter's passage; the second chapter's is the fact's source.
        own = [{"id": SPAN_1, "source_span_id": SPAN_1, "chapter_id": CHAPTER_1, "passage_start": 0, "body": SPAN_1_BODY, "prompt_excerpt": SPAN_1_BODY, "chapter_number": 1}]
        with mock.patch.object(screening, "claim_evidence", return_value=own):
            result = ContinuityEngine(provider).execute(data)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([span["id"] for span in provider.requests[0]["claims"][0]["allowed_evidence"]], [SPAN_1, SPAN_2])
        with mock.patch.object(screening, "claim_evidence", return_value=own):
            provider = Scripted(clean(CLAIM))
            ContinuityEngine(provider).execute({**data, "memory": data["memory"][:0]})
        self.assertEqual([span["id"] for span in provider.requests[0]["claims"][0]["allowed_evidence"]], [SPAN_1])


if __name__ == "__main__":
    unittest.main()
