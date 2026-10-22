"""07t: the chapter check no longer loses a judgement the model already made.

A  one mistyped character in a copied id does not void the judgement;
B  a conflict still not citable after its one repair is kept as a possible conflict;
C  the facts a sentence is reviewed against include each named person's latest state;
D  the prompts name the epithet rule and carry new versions.
No model is called: providers are scripted in memory.
"""
from __future__ import annotations

import copy
import unittest

from app import provider as provider_module
from app.engine import (
    ContinuityEngine,
    _continuity_schema,
    MEMORY_PROMPT_VERSION,
    MemoryDeltaEngine,
    MemoryInitializationEngine,
    SCREENED_RELATED_MEMORY_LIMIT,
    WritingAnalysisEngine,
    _resolve_id,
)
from app.provider import ProviderResult

CHAPTER_1 = "ch-597e63a1-9386-4fa4-8a11-0e5d2f6c7b01"
CHAPTER_2 = "ch-597e63a1-9386-4fa4-8a11-0e5d2f6c7b02"
SPAN_1 = "span-3f2a9c10-77d1-4b3e-9a55-100000000001"
SPAN_2 = "span-3f2a9c10-77d1-4b3e-9a55-200000000002"
MEMORY_1 = "mem-9b1c0d2e-5a44-4c7f-8d10-aaaaaaaa0001"
MEMORY_2 = "mem-9b1c0d2e-5a44-4c7f-8d10-bbbbbbbb0002"
CLAIM = "claim-07t-1"
CLAIM_TEXT = "她说两人从来没有任何亲属关系，却叫那个少年亲哥哥。"
SPAN_1_BODY = "第一章：账房先生说，她与少年没有任何亲属关系。"
SPAN_2_BODY = "第二章：少年的母亲出现了。"


def flip(identifier: str, index: int = -1) -> str:
    """The same id with exactly one character changed."""
    current = identifier[index]
    return identifier[:index] + ("x" if current != "x" else "y") + (identifier[index + 1:] if index != -1 else "")


class Scripted:
    available = True
    continuity_contract_version = "v6"
    label = model_label = "07t-scripted"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def evaluate(self, request):
        self.requests.append(copy.deepcopy(request))
        if not self.answers:
            raise AssertionError("unexpected extra dispatch")
        return ProviderResult(self.answers.pop(0), input_tokens=1, output_tokens=1)


class Legacy(Scripted):
    """A provider that does not speak the claim_verdicts contract."""
    continuity_contract_version = None


def make_data():
    spans = [{"id": SPAN_1, "chapter_id": CHAPTER_1, "body": SPAN_1_BODY, "prompt_excerpt": SPAN_1_BODY},
             {"id": SPAN_2, "chapter_id": CHAPTER_2, "body": SPAN_2_BODY, "prompt_excerpt": SPAN_2_BODY}]
    memory = [{"id": MEMORY_1, "memory_type": "static_canon", "subject": "账房先生", "predicate": "relationship",
               "value": "她与少年没有任何亲属关系", "source_span_id": SPAN_1},
              {"id": MEMORY_2, "memory_type": "dynamic_state", "subject": "少年", "predicate": "status",
               "value": "母亲已出现", "source_span_id": SPAN_2}]
    claim = {"id": CLAIM, "text": CLAIM_TEXT, "allowed_evidence": spans}
    return {"draft": {"id": "draft-07t", "revision": 1, "body": CLAIM_TEXT}, "claims": [claim], "memory": memory}


def evidence(span=SPAN_1, chapter=CHAPTER_1, relation="contradicts", sufficiency="sufficient", memory=()):
    return {"chapter_id": chapter, "span_id": span, "relation": relation, "sufficiency": sufficiency, "related_memory_ids": list(memory)}


def answer(evidence_rows, nature="confirmed_conflict", verdict="reviewed_issue", status="conflict", chain=None, temporal=None,
           suggestion=None, actions=None):
    chain = chain if chain is not None else [{"span_id": row["span_id"], "role": "prior_state"} for row in evidence_rows]
    issue = {
        "claim_span_id": CLAIM, "status": status, "nature": nature, "category": "relationship", "severity": "high",
        "explanation": "草稿的说法与已有设定矛盾。",
        "reasoning": "设定写明两人没有任何亲属关系，草稿却称亲哥哥。",
        "temporal_basis": temporal or {"claim_anchor": None, "evidence_anchor": None, "relation": "timeless_rule"},
        "evidence": evidence_rows, "evidence_chain": chain, "suggested_revision": suggestion,
        "available_actions": actions if actions is not None else [], "proposed_memory_change": None,
    }
    return {"issues": [issue], "claim_verdicts": [{"claim_span_id": CLAIM, "verdict": verdict, "basis": "依据设定判断。"}]}


def direct_answer(**overrides):
    row = {**evidence(memory=[MEMORY_1]), **overrides}
    return answer([row], temporal={"claim_anchor": None, "evidence_anchor": None, "relation": "timeless_rule"})


class IdToleranceTests(unittest.TestCase):
    def validate(self, payload, provider=None, sink=None, **kwargs):
        return ContinuityEngine(provider or Scripted()).validate(payload, make_data(), normalization_sink=sink, **kwargs)

    def test_resolve_id_rule(self):
        known = {"abcdef", "abcxef", "zzzzzz"}
        self.assertEqual(_resolve_id("abcdef", known), ("abcdef", False))
        self.assertEqual(_resolve_id("abcdeg", known), ("abcdef", True))
        # Two known ids are one character away: ambiguous, not corrected.
        self.assertEqual(_resolve_id("abcyef", known), (None, False))
        # Two characters away, a different length and a non-string correct nothing.
        self.assertEqual(_resolve_id("abcdgg", {"abcdef"}), (None, False))
        self.assertEqual(_resolve_id("abcde", {"abcdef"}), (None, False))
        self.assertEqual(_resolve_id(None, {"abcdef"}), (None, False))

    def test_a_mistyped_chapter_id_follows_the_span_and_is_recorded(self):
        payload = answer([evidence(chapter=flip(CHAPTER_1, 20), memory=[MEMORY_1])])
        sink = []
        issue = self.validate(payload, sink=sink)[0]
        self.assertEqual(issue["evidence"][0]["chapter_id"], CHAPTER_1)
        self.assertEqual([(row["reason_code"], row["outcome"]) for row in sink], [("chapter_id_replaced", "corrected")])
        self.assertEqual(set(sink[0]), {"claim_span_id", "reason_code", "outcome", "provider_attempt"})
        self.assertEqual(sink[0]["claim_span_id"], CLAIM)

    def test_a_span_id_one_character_off_is_corrected_in_evidence_and_chain(self):
        wrong = flip(SPAN_1)
        payload = answer([evidence(span=wrong, memory=[MEMORY_1])], chain=[{"span_id": wrong, "role": "prior_state"}])
        sink = []
        issue = self.validate(payload, sink=sink)[0]
        self.assertEqual(issue["evidence"][0]["span_id"], SPAN_1)
        self.assertEqual(issue["evidence_chain"], [{"span_id": SPAN_1, "role": "prior_state"}])
        self.assertEqual([row["reason_code"] for row in sink], ["id_corrected", "id_corrected"])

    def test_a_chain_id_alone_one_character_off_is_corrected(self):
        payload = answer([evidence(memory=[MEMORY_1])], chain=[{"span_id": flip(SPAN_1), "role": "prior_state"}])
        sink = []
        issue = self.validate(payload, sink=sink)[0]
        self.assertEqual(issue["evidence_chain"][0]["span_id"], SPAN_1)
        self.assertEqual([row["reason_code"] for row in sink], ["id_corrected"])

    def test_two_characters_off_or_two_candidates_are_not_corrected(self):
        two_off = flip(flip(SPAN_1), -3)
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            self.validate(answer([evidence(span=two_off)], chain=[{"span_id": two_off, "role": "prior_state"}]))
        # SPAN_1 and SPAN_2 differ only in two places, but this id is one away from neither: build one that is
        # one away from both candidates by making the allowed ids differ in one character.
        data = make_data()
        data["claims"][0]["allowed_evidence"][1]["id"] = SPAN_1[:-1] + "2"
        ambiguous = SPAN_1[:-1] + "3"
        payload = answer([evidence(span=ambiguous)], chain=[{"span_id": ambiguous, "role": "prior_state"}])
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            ContinuityEngine(Scripted()).validate(payload, data)
        # A wrong chain id with no single candidate still voids the issue.
        payload = answer([evidence(memory=[MEMORY_1])], chain=[{"span_id": two_off, "role": "prior_state"}])
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            self.validate(payload)

    def test_memory_ids_are_corrected_or_dropped_without_voiding_the_evidence(self):
        payload = answer([evidence(memory=[flip(MEMORY_1), "mem-unknown-entirely"])])
        sink = []
        issue = self.validate(payload, sink=sink)[0]
        self.assertEqual(issue["evidence"][0]["related_memory_ids"], [MEMORY_1])
        self.assertEqual(sorted(row["reason_code"] for row in sink), ["id_corrected", "id_dropped"])
        self.assertEqual({row["outcome"] for row in sink}, {"corrected", "dropped"})

    def test_exact_ids_record_nothing_and_a_failed_payload_leaves_the_sink_alone(self):
        sink = []
        self.validate(direct_answer(), sink=sink)
        self.assertEqual(sink, [])
        bad = answer([evidence(chapter="wrong", memory=[flip(MEMORY_1)])])
        bad["issues"][0]["reasoning"] = ""
        with self.assertRaises(ValueError):
            self.validate(bad, sink=sink)
        self.assertEqual(sink, [])

    def test_other_model_id_validators_use_the_same_rule(self):
        candidates = MemoryInitializationEngine(Scripted())._validate_with_normalization(
            {"candidates": [{"memory_type": "static_canon", "subject": "少年", "predicate": "identity", "value": "十五岁",
                             "chapter_id": flip(CHAPTER_1, 20), "source_span_id": flip(SPAN_1)}]},
            {"sources": [{"id": SPAN_1, "chapter_id": CHAPTER_1, "body": SPAN_1_BODY}]})
        self.assertEqual((candidates[0][0]["source_span_id"], candidates[0][0]["chapter_id"]), (SPAN_1, CHAPTER_1))
        self.assertEqual(candidates[1], {"trimmed_string": 0, "memory_type_format": 0, "extra_fields_removed": 0, "id_corrected": 2})
        delta = MemoryDeltaEngine(Scripted()).validate(
            {"candidates": [{"change_kind": "changed_fact", "affected_memory_id": flip(MEMORY_2), "memory_type": "dynamic_state", "subject": "少年",
                             "predicate": "status", "value": "母亲已经离开", "invalidation_reason": None, "chapter_id": flip(CHAPTER_2, 20),
                             "source_span_id": flip(SPAN_2)}]},
            {"sources": [{"id": SPAN_2, "chapter_id": CHAPTER_2, "body": SPAN_2_BODY}], "memory": make_data()["memory"]})
        self.assertEqual((delta[0]["affected_memory_id"], delta[0]["source_span_id"], delta[0]["chapter_id"]), (MEMORY_2, SPAN_2, CHAPTER_2))
        # A chapter that is not one character away from the span's, or a span two characters away, is still rejected.
        with self.assertRaises(ValueError):
            MemoryInitializationEngine(Scripted())._validate_with_normalization(
                {"candidates": [{"memory_type": "static_canon", "subject": "少年", "predicate": "identity", "value": "十五岁",
                                 "chapter_id": "foreign-chapter", "source_span_id": SPAN_1}]},
                {"sources": [{"id": SPAN_1, "chapter_id": CHAPTER_1, "body": SPAN_1_BODY}]})
        with self.assertRaises(ValueError):
            MemoryInitializationEngine(Scripted())._validate_with_normalization(
                {"candidates": [{"memory_type": "static_canon", "subject": "少年", "predicate": "identity", "value": "十五岁",
                                 "chapter_id": CHAPTER_1, "source_span_id": flip(flip(SPAN_1), -3)}]},
                {"sources": [{"id": SPAN_1, "chapter_id": CHAPTER_1, "body": SPAN_1_BODY}]})

    def test_analysis_sources_use_the_same_rule(self):
        maps = {"memory_record": {MEMORY_1: {"subject": "账房先生", "predicate": "relationship", "value": "无亲属关系"}}}
        cleaned = WritingAnalysisEngine._clean_source({"source_type": "memory_record", "source_id": flip(MEMORY_1)}, maps, {"memory_record"}, "project-1")
        self.assertEqual(cleaned["source_id"], MEMORY_1)
        self.assertIn(MEMORY_1, cleaned["source_path"])
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            WritingAnalysisEngine._clean_source({"source_type": "memory_record", "source_id": flip(flip(MEMORY_1), -3)}, maps, {"memory_record"}, "project-1")


def screened_data():
    """A screened batch: the cited ids are passage ids (here equal to their span ids), cut from SourceSpans."""
    passages = [{"id": SPAN_1, "source_span_id": SPAN_1, "chapter_id": CHAPTER_1, "passage_start": 0, "body": SPAN_1_BODY, "prompt_excerpt": SPAN_1_BODY},
                {"id": SPAN_2, "source_span_id": SPAN_2, "chapter_id": CHAPTER_2, "passage_start": 0, "body": SPAN_2_BODY, "prompt_excerpt": SPAN_2_BODY}]
    claim = {"id": CLAIM, "text": CLAIM_TEXT, "chapter_number": 5, "context": "draft", "allowed_evidence": passages}
    return {"pipeline": "screened", "claims": [claim], "memory": make_data()["memory"], "memory_chapters": {MEMORY_1: 1, MEMORY_2: 2},
            "draft": {"id": "draft-07t", "revision": 1, "body": CLAIM_TEXT}, "contexts": {"draft": CLAIM_TEXT}}


class KeepAsPossibleTests(unittest.TestCase):
    def run_batch(self, first, second, provider_class=Scripted):
        """The batch through its first answer and its one repair, as the screened pipeline runs it."""
        provider = provider_class(first, second)
        engine = ContinuityEngine(provider)
        data = screened_data()
        batch = engine._screened_request(data["claims"], data, (3, SCREENED_RELATED_MEMORY_LIMIT))
        return provider, engine._review_batch(batch, data, 10 ** 9)

    def not_direct(self, **extra):
        """A confirmed conflict whose only citation is marked context: conflict_evidence_not_direct."""
        return answer([evidence(relation="context", memory=[MEMORY_1])], **extra)

    def test_context_only_citation_is_kept_as_a_possible_conflict_after_the_repair(self):
        provider, outcome = self.run_batch(self.not_direct(), self.not_direct())
        self.assertEqual(len(provider.requests), 2)
        self.assertNotIn("undecided", outcome)
        issue = outcome["issues"][0]
        self.assertEqual((issue["status"], issue["nature"]), ("conflict", "possible_conflict"))
        self.assertEqual([(row["span_id"], row["relation"], row["related_memory_ids"]) for row in issue["evidence"]], [(SPAN_1, "context", [MEMORY_1])])
        self.assertEqual(issue["evidence_chain"], [{"span_id": SPAN_1, "role": "prior_state"}])
        self.assertEqual(issue["evidence_status"], "sufficient")
        self.assertEqual([(row["reason_code"], row["outcome"], row["provider_attempt"]) for row in outcome["normalizations"]],
                         [("kept_as_possible_after_repair", "possible_conflict", 2)])

    def test_unresolvable_anchors_are_cleared_and_the_time_relation_becomes_unknown(self):
        temporal = {"claim_anchor": "不在原文里的锚点", "evidence_anchor": "资料里的话", "relation": "explicit_overlap"}
        payload = answer([evidence(memory=[MEMORY_1])], temporal=temporal)
        provider, outcome = self.run_batch(payload, payload)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(outcome["issues"][0]["nature"], "possible_conflict")
        self.assertEqual(outcome["normalizations"][-1]["reason_code"], "kept_as_possible_after_repair")
        # Called directly on the failing answer: the same card, with the anchors it could not resolve left out.
        data = screened_data()
        kept = ContinuityEngine(Scripted())._keep_as_possible(
            payload["issues"][0], ValueError("temporal_anchor_unresolvable"), data, {CLAIM: data["claims"][0]}, {row["id"]: row for row in data["memory"]},
            {CLAIM: "reviewed_issue"}, 2)
        self.assertEqual((kept[0]["nature"], [row["reason_code"] for row in kept[1]]), ("possible_conflict", ["kept_as_possible_after_repair"]))

    def test_only_the_resolvable_citations_are_kept(self):
        rows = [evidence(relation="context", memory=[MEMORY_1]), evidence(span="span-not-supplied-at-all", relation="context")]
        payload = answer(rows, chain=[{"span_id": SPAN_1, "role": "prior_state"}, {"span_id": "span-not-supplied-at-all", "role": "prior_state"}])
        _, outcome = self.run_batch(payload, payload)
        issue = outcome["issues"][0]
        self.assertEqual(issue["nature"], "possible_conflict")
        self.assertEqual([row["span_id"] for row in issue["evidence"]], [SPAN_1])

    def test_a_citation_that_only_names_an_existing_fact_is_located_by_that_fact(self):
        payload = answer([evidence(span="span-not-supplied-at-all", relation="context", memory=[MEMORY_2])],
                         chain=[{"span_id": "span-not-supplied-at-all", "role": "prior_state"}])
        _, outcome = self.run_batch(payload, payload)
        issue = outcome["issues"][0]
        self.assertEqual((issue["nature"], [row["span_id"] for row in issue["evidence"]]), ("possible_conflict", [SPAN_2]))

    def test_a_mistyped_id_is_recorded_together_with_the_kept_card(self):
        payload = answer([evidence(span=flip(SPAN_1), chapter="wrong", relation="context", memory=[MEMORY_1, "mem-unknown-entirely"])],
                         chain=[{"span_id": SPAN_1, "role": "prior_state"}])
        _, outcome = self.run_batch(payload, payload)
        self.assertEqual(outcome["issues"][0]["nature"], "possible_conflict")
        self.assertEqual(sorted(row["reason_code"] for row in outcome["normalizations"]),
                         ["chapter_id_replaced", "id_corrected", "id_dropped", "kept_as_possible_after_repair"])

    def test_a_non_compliant_suggested_revision_is_dropped_and_a_compliant_one_kept(self):
        bad = {"before": "文中不存在的句子", "after": "她叫那个少年先生。"}
        payload = self.not_direct(suggestion=bad, actions=["edit", "apply_suggestion"])
        _, outcome = self.run_batch(payload, payload)
        issue = outcome["issues"][0]
        self.assertEqual((issue["suggested_revision"], issue["available_actions"]), (None, ["edit"]))
        good = {"before": "叫那个少年亲哥哥", "after": "叫那个少年先生"}
        payload = self.not_direct(suggestion=good, actions=["edit", "apply_suggestion"])
        _, outcome = self.run_batch(payload, payload)
        issue = outcome["issues"][0]
        self.assertEqual((issue["suggested_revision"], issue["available_actions"]), (good, ["edit", "apply_suggestion"]))

    def test_a_citation_the_contract_does_not_know_also_qualifies_but_only_after_the_repair(self):
        broken = answer([evidence(sufficiency="mostly", memory=[MEMORY_1])])
        provider, outcome = self.run_batch(broken, broken)
        self.assertEqual((len(provider.requests), outcome["issues"][0]["nature"]), (2, "possible_conflict"))
        # A first answer that the repair turns into a compliant one is not touched.
        provider, outcome = self.run_batch(self.not_direct(), direct_answer())
        self.assertEqual(outcome["issues"][0]["nature"], "confirmed_conflict")
        self.assertEqual(outcome["normalizations"], [])

    def test_conditions_that_are_not_met_keep_the_original_rule(self):
        # No citation resolves: the claim is undecided, as before.
        nothing = answer([evidence(span="span-not-supplied-at-all", relation="context")], chain=[{"span_id": "span-not-supplied-at-all", "role": "prior_state"}])
        _, outcome = self.run_batch(nothing, nothing)
        self.assertEqual(outcome["undecided"], [{"claim_span_id": CLAIM, "error_code": "evidence_unresolvable"}])
        self.assertNotIn("issues", outcome)
        # No reviewed_issue verdict from the model (a provider without the verdict contract): not kept.
        payload = {"issues": self.not_direct()["issues"]}
        _, outcome = self.run_batch(payload, payload, provider_class=Legacy)
        self.assertEqual(outcome["undecided"], [{"claim_span_id": CLAIM, "error_code": "conflict_evidence_not_direct"}])
        # A compatible state change is never turned into a possible conflict.
        state = answer([evidence(relation="context", sufficiency="mostly", memory=[MEMORY_1])], nature="state_change",
                       temporal={"claim_anchor": None, "evidence_anchor": None, "relation": "explicit_later_transition"})
        _, outcome = self.run_batch(state, state)
        self.assertEqual(outcome["undecided"], [{"claim_span_id": CLAIM, "error_code": "evidence_unresolvable"}])
        # Only the three citation faults qualify: an unreadable reasoning does not.
        wordy = self.not_direct()
        wordy["issues"][0]["reasoning"] = "矛盾" * 500
        _, outcome = self.run_batch(wordy, wordy)
        self.assertEqual(outcome["undecided"][0]["error_code"], "reasoning_too_long")

    def test_insufficient_evidence_and_the_direct_evidence_rule_are_unchanged(self):
        data = make_data()
        engine = ContinuityEngine(Scripted())
        gap = answer([evidence(relation="context", sufficiency="insufficient")], nature="insufficient_evidence", verdict="insufficient_evidence",
                     status="insufficient_evidence", chain=[{"span_id": SPAN_1, "role": "missing_link"}],
                     temporal={"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"})
        self.assertEqual(engine.validate(gap, data, allow_conservative_temporal_normalization=True)[0]["nature"], "insufficient_evidence")
        # A first answer is never degraded: the contract still rejects an indirect confirmed conflict.
        with self.assertRaisesRegex(ValueError, "conflict_evidence_not_direct"):
            engine.validate(self.not_direct(), data)
        # And a second answer for an insufficient_evidence claim that cites a sufficient span stays a contract error.
        upgraded = answer([evidence(relation="context", sufficiency="sufficient")], nature="insufficient_evidence", verdict="insufficient_evidence",
                          status="insufficient_evidence", chain=[{"span_id": SPAN_1, "role": "missing_link"}],
                          temporal={"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"})
        with self.assertRaisesRegex(ValueError, "insufficient_evidence_upgraded"):
            engine.validate(upgraded, data, allow_conservative_temporal_normalization=True)


class LatestStateTests(unittest.TestCase):
    NAME = "祝嵊禾"

    def fact(self, ordinal, chapter, value, predicate="knowledge", subject=None, memory_type="character_knowledge", source=None):
        return {"id": f"mem-{ordinal:03d}", "memory_type": memory_type, "subject": subject or self.NAME, "predicate": predicate,
                "value": value, "source_span_id": source or f"span-{chapter}"}

    def claim(self, text="祝嵊禾依然一个风字也不认识。", chapter_number=9, spans=()):
        return {"id": "claim-c", "text": text, "chapter_number": chapter_number, "context": "draft",
                "allowed_evidence": [{"id": f"p-{span}", "source_span_id": span, "chapter_id": f"c-{span}", "body": "风字"} for span in spans]}

    def chapters(self, memory):
        return {item["id"]: int(item["source_span_id"].split("-")[1]) for item in memory}

    def test_the_latest_state_enters_although_older_ones_with_passage_sources_fill_the_ranking(self):
        old = [self.fact(i, 1 + i % 3, f"风字相关旧状态{i}") for i in range(20)]
        latest = self.fact(99, 7, "已能独立读懂短句", predicate="knowledge")
        memory = old + [latest]
        claim = self.claim(spans=["span-1", "span-2", "span-3"])
        engine = ContinuityEngine(Scripted())
        # The old way fills the ten slots with the older facts.
        self.assertNotIn(latest["id"], [item["id"] for item in engine._related_memory(claim, memory, SCREENED_RELATED_MEMORY_LIMIT)])
        chosen = engine._related_memory(claim, memory, SCREENED_RELATED_MEMORY_LIMIT, self.chapters(memory), [])
        self.assertIn(latest["id"], [item["id"] for item in chosen])
        self.assertLessEqual(len(chosen), SCREENED_RELATED_MEMORY_LIMIT)
        self.assertEqual(len({item["id"] for item in chosen}), len(chosen))

    def test_aliases_name_the_person_and_each_predicate_keeps_its_own_latest(self):
        memory = [self.fact(1, 2, "不识风字", predicate="knowledge"), self.fact(2, 6, "能读短句", predicate="knowledge"),
                  self.fact(3, 3, "在钟楼", predicate="location", memory_type="dynamic_state"),
                  self.fact(4, 5, "在书院", predicate="location", memory_type="dynamic_state"),
                  self.fact(5, 5, "生于北地", predicate="identity", memory_type="static_canon")]
        claim = self.claim(text="小禾依然一个风字也不认识。")
        engine = ContinuityEngine(Scripted())
        aliases = [{"primary_name": self.NAME, "alias": "小禾"}]
        ids = {item["id"] for item in engine._related_memory(claim, memory, 10, self.chapters(memory), aliases)}
        self.assertEqual(ids & {"mem-002", "mem-004"}, {"mem-002", "mem-004"})
        # Without the alias the nickname names no one, and nothing is reserved.
        self.assertEqual([item for item in engine._related_memory(claim, memory, 10, self.chapters(memory), []) if item["id"] in {"mem-002", "mem-004"}], [])
        # identity is not a changing state, and an older state of a predicate is not reserved.
        self.assertNotIn("mem-005", ids)

    def test_nothing_from_the_checked_chapter_or_later_is_reserved(self):
        memory = [self.fact(1, 2, "不识风字"), self.fact(2, 9, "同章的新说法"), self.fact(3, 12, "更晚的说法")]
        latest = ContinuityEngine._latest_states(self.claim(chapter_number=9), memory, self.chapters(memory), [])
        self.assertEqual([item["id"] for item in latest], ["mem-001"])  # all state facts before chapter 9

    def test_many_people_take_at_most_half_the_slots_and_the_total_stays_within_the_limit(self):
        names = [f"人物{chr(0x4e00 + index)}{chr(0x4e10 + index)}" for index in range(9)]
        memory = [self.fact(index, 2 + index, f"最新状态{index}", predicate="status", subject=name, memory_type="dynamic_state") for index, name in enumerate(names)]
        # Older, unrelated facts that rank by their passage source.
        filler = [self.fact(100 + index, 1, f"无关旧事{index}", predicate="rule", subject=f"旁人{index}", memory_type="static_canon", source="span-1") for index in range(20)]
        claim = self.claim(text="".join(f"{name}站在门口。" for name in names), chapter_number=50, spans=["span-1"])
        memory += filler
        chapters = self.chapters(memory)
        chosen = ContinuityEngine(Scripted())._related_memory(claim, memory, 10, chapters, [])
        states = [item for item in chosen if item["predicate"] == "status"]
        self.assertEqual(len(states), 5)
        self.assertLessEqual(len(chosen), 10)
        # The most recent chapters win the reserved places when the people outnumber them.
        self.assertEqual(sorted(int(item["id"][4:]) for item in states), [4, 5, 6, 7, 8])

    def test_without_a_chapter_map_the_selection_is_exactly_the_old_one(self):
        memory = [self.fact(i, 1 + i % 3, f"风字旧{i}") for i in range(20)]
        claim = self.claim(spans=["span-1"])
        engine = ContinuityEngine(Scripted())
        old = engine._related_memory(claim, memory, 10)
        self.assertEqual(len(old), 10)
        self.assertEqual([item["id"] for item in old], [item["id"] for item in engine._related_memory(claim, memory, 10, None, None)])

    def test_the_screened_request_carries_the_latest_state_of_a_person_named_by_alias(self):
        memory = [self.fact(i, 1 + i % 3, f"风字相关旧状态{i}") for i in range(20)] + [self.fact(99, 7, "已能独立读懂短句")]
        chapters = self.chapters(memory)
        claim = self.claim(text="小禾依然一个风字也不认识。", spans=["span-1", "span-2", "span-3"])
        data = {"pipeline": "screened", "memory": memory, "memory_chapters": chapters, "draft": {"id": "d", "revision": 1},
                "contexts": {"draft": "小禾依然一个风字也不认识。"}, "aliases": [{"primary_name": self.NAME, "alias": "小禾"}]}
        request = ContinuityEngine(Scripted())._screened_request([claim], data, (3, SCREENED_RELATED_MEMORY_LIMIT))
        ids = [item["id"] for item in request["memory"]]
        self.assertIn("mem-099", ids)
        self.assertLessEqual(len(ids), SCREENED_RELATED_MEMORY_LIMIT)


class PromptTests(unittest.TestCase):
    REVIEW = "only by an epithet or role (the girl, the shopkeeper)"
    MEMORY = "only by an epithet or role (the girl, that boy, the shopkeeper)"

    def test_the_review_rules_name_the_epithet_referent_rule(self):
        rule = next(text for text in provider_module.CONTINUITY_REVIEW_RULES if self.REVIEW in text)
        self.assertIn("same paragraph or an adjacent sentence names them, it is that character", rule)
        self.assertIn("if it could mean someone else there, follow the text", rule)

    def test_both_memory_rule_sets_name_the_person_not_the_epithet(self):
        for rules in (provider_module.MEMORY_INITIALIZATION_RULES, provider_module.MEMORY_DELTA_RULES):
            rule = next(text for text in rules if self.MEMORY in text)
            self.assertIn("the candidate's subject is the name, not the epithet", rule)

    def test_prompt_versions_moved_on(self):
        self.assertEqual(provider_module.CONTINUITY_PROMPT_VERSION, "continuity-review-v24d-epithet-referents")
        self.assertEqual(provider_module.CONTINUITY_SCREENED_PROMPT_VERSION, "continuity-review-v25k-screened-offpage-second-review")
        self.assertEqual(MEMORY_PROMPT_VERSION, "memory-initialization-v11-epithet-subjects")
        self.assertEqual(MemoryDeltaEngine(Scripted()).provenance()["prompt_version"], "memory-delta-v6-epithet-subjects")

    def test_the_review_prompt_reaches_the_model(self):
        request = {"claims": [], "memory": [], "draft": {"id": "d", "revision": 1, "body": ""}, "output_schema": _continuity_schema()}
        for pipeline in (None, "screened"):
            self.assertIn(self.REVIEW, provider_module.continuity_prompt({**request, "pipeline": pipeline}))


if __name__ == "__main__":
    unittest.main()


class RelevantStateTests(LatestStateTests):
    """Review of 07t: the relevant state fact wins over a later state fact about something else."""

    def test_the_relevant_knowledge_fact_wins_over_a_later_unrelated_one(self):
        memory = [self.fact(i, 1 + i % 3, f"风字相关旧状态{i}") for i in range(20)]
        relevant = self.fact(98, 6, "已能独立读懂短句风字，不必再等别人替她念出")
        later = [self.fact(97, 8, "辨出浅刻标记指向外缘"), self.fact(96, 8, "记着绳突然绷紧那一下")]
        memory += [relevant] + later
        chosen = ContinuityEngine(Scripted())._related_memory(self.claim(spans=["span-1", "span-2", "span-3"]), memory,
                                                               SCREENED_RELATED_MEMORY_LIMIT, self.chapters(memory), [])
        self.assertIn(relevant["id"], [item["id"] for item in chosen])
