"""Offline regression for V6 trace failures and the V7 repair contract.

Saved first answers are read as fixtures; no live runner, database or Provider
is constructed. Tests exercise the real engine with a bounded in-memory stub.
"""
from __future__ import annotations

import copy
import json
import pathlib
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app.engine import ContinuityContractValidationError, ContinuityEngine
from app.provider import MAX_INPUT_BUDGET_UNITS, ProviderResult, continuity_prompt, request_prompt_and_budget


ROOT = pathlib.Path(__file__).resolve().parents[2]
LIVE = ROOT / "evaluation/current_flash_v6/runs/flash-v6-20260927-01/cases"


class OfflineProvider:
    available = True
    continuity_contract_version = "v6"
    label = model_label = "v7-offline-regression"

    def __init__(self, *answers):
        self.answers = answers
        self.requests = []

    def evaluate(self, request):
        if len(self.requests) >= len(self.answers):
            raise AssertionError("Unexpected extra evaluate; repair must remain bounded")
        answer = self.answers[len(self.requests)]
        self.requests.append(copy.deepcopy(request))
        return ProviderResult(answer, input_tokens=1, output_tokens=1)


def captured(number):
    case = LIVE / number
    request = json.loads((case / "requests/01.json").read_text(encoding="utf-8"))["business_request"]
    content = json.loads((case / "attempts/01-finish.json").read_text(encoding="utf-8"))["message_content"]
    raw = json.loads(content)
    parsed = json.loads((case / "evaluations/01.json").read_text(encoding="utf-8"))["parsed_business_json"]
    if raw != parsed:
        raise AssertionError("Saved raw/parsed fixture disagreement")
    return request, raw


def no_issue(data, basis="The supplied facts can coexist; no issue needs review."):
    return {"issues": [], "claim_verdicts": [
        {"claim_span_id": claim["id"], "verdict": "no_issue", "basis": basis}
        for claim in data["claims"]
    ]}


def diagnostic_field(diagnostic):
    return str(diagnostic.get("field", diagnostic.get("invalid_field", "")))


def repaired_badge_gap(request):
    """Repair fixture 03 without pretending that the empty register proves no gap."""
    claim = request["claims"][0]
    span = next(item for item in claim["allowed_evidence"] if "holder field blank" in item["body"])
    return {
        "claim_verdicts": [{"claim_span_id": claim["id"], "verdict": "insufficient_evidence",
                            "basis": "The register leaves the asserted holder at that time unrecorded."}],
        "issues": [{
            "claim_span_id": claim["id"], "status": "insufficient_evidence", "nature": "insufficient_evidence",
            "category": "object_state", "severity": "medium",
            "explanation": "The register does not establish the asserted holder.",
            "reasoning": "The holder field is blank; a source establishing who held the badge is missing.",
            "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
            "evidence": [{"chapter_id": span["chapter_id"], "span_id": span["id"], "relation": "context",
                          "sufficiency": "insufficient", "related_memory_ids": []}],
            "evidence_chain": [{"span_id": span["id"], "role": "missing_link"}],
            "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
        }],
    }


def temporal_case(claim, evidence, claim_anchor, evidence_anchor):
    data = {
        "draft": {"id": "draft-v7", "revision": 1, "body": claim},
        "claims": [{"id": "claim-v7", "text": claim, "allowed_evidence": [
            {"id": "span-v7", "chapter_id": "chapter-v7", "body": evidence, "prompt_excerpt": evidence}
        ]}], "memory": [],
    }
    issue = {
        "claim_span_id": "claim-v7", "status": "conflict", "nature": "confirmed_conflict",
        "category": "object_state", "severity": "high",
        "explanation": "The two asserted states conflict. 两处状态矛盾。",
        "reasoning": "The cited statement contradicts the claim at its asserted time. 两处明确状态不能同时成立。",
        "temporal_basis": {"claim_anchor": claim_anchor, "evidence_anchor": evidence_anchor,
                           "relation": "explicit_overlap"},
        "evidence": [{"chapter_id": "chapter-v7", "span_id": "span-v7", "relation": "contradicts",
                      "sufficiency": "sufficient", "related_memory_ids": []}],
        "evidence_chain": [{"span_id": "span-v7", "role": "prior_state"}],
        "suggested_revision": None, "available_actions": [], "proposed_memory_change": None,
    }
    return data, {"issues": [issue], "claim_verdicts": [
        {"claim_span_id": "claim-v7", "verdict": "reviewed_issue", "basis": "The two asserted states conflict."}
    ]}


class V7ContinuityContractTests(unittest.TestCase):
    def setUp(self):
        guards = ExitStack()
        self.addCleanup(guards.close)
        for target in ("socket.socket.connect", "socket.create_connection", "sqlite3.connect",
                       "httpx.Client.send", "httpx.AsyncClient.send"):
            guards.enter_context(patch(target, side_effect=AssertionError("External access forbidden in offline regression")))

    def diagnostics_for(self, error, claim_id, field):
        diagnostics = getattr(error, "diagnostics", None)
        self.assertIsInstance(diagnostics, list)
        matches = [d for d in diagnostics if d.get("claim_span_id") == claim_id and field in diagnostic_field(d)]
        self.assertTrue(matches, diagnostics)
        return matches

    def assert_temporal_rejected(self, data, raw):
        engine = ContinuityEngine(OfflineProvider())
        with self.assertRaisesRegex(ContinuityContractValidationError, "temporal_overlap_unproven"):
            engine.validate(raw, data)
        diagnostics = engine._repair_diagnostics(raw, data)
        self.assertTrue(any("temporal_overlap_unproven" in d["problem_codes"] for d in diagnostics), diagnostics)

    def test_saved_26_same_day_hhmm_conflict_passes_without_repair(self):
        request, raw = captured("26")
        original = copy.deepcopy(raw)
        provider = OfflineProvider(raw)
        engine = ContinuityEngine(provider)
        self.assertEqual(engine._repair_diagnostics(raw, request), [])
        self.assertEqual(engine.validate(raw, request)[0]["nature"], "confirmed_conflict")
        result = engine.execute(request)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["issues"][0]["nature"], "confirmed_conflict")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(result["contract_normalization_count"], 0)
        self.assertEqual(raw, original)

    def test_saved_17_overlong_basis_has_precise_diagnostic(self):
        request, raw = captured("17")
        self.assertGreater(len(raw["claim_verdicts"][0]["basis"]), 400)
        with self.assertRaisesRegex(ContinuityContractValidationError, "claim_verdicts_invalid") as caught:
            ContinuityEngine(OfflineProvider()).validate(raw, request)
        diagnostic = self.diagnostics_for(caught.exception, request["claims"][0]["id"], "basis")[0]
        self.assertEqual(diagnostic["observed_length"], len(raw["claim_verdicts"][0]["basis"]))
        self.assertEqual(diagnostic["limit"], 400)

    def test_saved_03_missing_issue_diagnostic_locates_the_ledger_decision(self):
        request, raw = captured("03")
        self.assertEqual(raw["issues"], [])
        with self.assertRaisesRegex(ContinuityContractValidationError, "claim_verdicts_issue_mismatch") as caught:
            ContinuityEngine(OfflineProvider()).validate(raw, request)
        diagnostic = self.diagnostics_for(caught.exception, request["claims"][0]["id"], "verdict")[0]
        serialized = json.dumps(diagnostic, ensure_ascii=False)
        self.assertIn("insufficient_evidence", serialized)
        self.assertIn("no_issue", serialized)

    def test_saved_22_invalid_citation_remains_a_binding_rejection(self):
        request, raw = captured("22")
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            ContinuityEngine(OfflineProvider()).validate(raw, request)
        provider = OfflineProvider(raw, raw)
        result = ContinuityEngine(provider).execute(request)
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["error_code"], "evidence_unresolvable")
        self.assertLessEqual(len(provider.requests), 2)

    def test_repair_carries_complete_original_ledger_and_diagnostics_into_prompt(self):
        for number, field in (("17", "basis"), ("03", "verdict")):
            with self.subTest(case=number):
                request, first = captured(number)
                before = copy.deepcopy(first)
                second = repaired_badge_gap(request) if number == "03" else no_issue(request)
                provider = OfflineProvider(first, second)
                result = ContinuityEngine(provider).execute(request)
                self.assertEqual(result["status"], "completed", result)
                self.assertEqual(len(provider.requests), 2)
                if number == "03":
                    self.assertEqual(result["issues"][0]["nature"], "insufficient_evidence")
                    self.assertEqual(result["issues"][0]["available_actions"], [])
                repair = provider.requests[1]["contract_repair"]
                self.assertEqual(repair["rejected_claim_verdicts"], before["claim_verdicts"])
                self.assertEqual(repair["rejected_issues"], before["issues"])
                self.assertTrue(any(d.get("claim_span_id") == request["claims"][0]["id"]
                                    and field in diagnostic_field(d) for d in repair["diagnostics"]))
                prompt = json.loads(continuity_prompt(provider.requests[1]))
                self.assertEqual(prompt["contract_repair"]["rejected_claim_verdicts"], before["claim_verdicts"])
                self.assertEqual(prompt["contract_repair"]["diagnostics"], repair["diagnostics"])
                self.assertEqual(first, before, "The rejected ledger must not be silently truncated or relabeled")

    def test_repeated_ledger_failure_still_stops_after_one_repair(self):
        for number, code in (("17", "claim_verdicts_invalid"), ("03", "claim_verdicts_issue_mismatch")):
            with self.subTest(case=number):
                request, raw = captured(number)
                provider = OfflineProvider(raw, copy.deepcopy(raw))
                result = ContinuityEngine(provider).execute(request)
                self.assertEqual((result["status"], result["error_code"]), ("failed", code))
                self.assertEqual(len(provider.requests), 2)

    def test_basis_limit_is_visible_and_exactly_400_characters_are_allowed(self):
        request, _ = captured("17")
        engine = ContinuityEngine(OfflineProvider())
        current_request = engine._request(request["claims"], request["memory"], request["draft"])
        self.assertIn("400", json.dumps(current_request["output_schema"]["claim_verdicts"]))
        prompt = json.loads(continuity_prompt(current_request))
        self.assertIn("400", json.dumps(prompt["rules"]))
        self.assertEqual(engine.validate(no_issue(request, "界" * 400), request), [])
        with self.assertRaisesRegex(ContinuityContractValidationError, "claim_verdicts_invalid") as caught:
            engine.validate(no_issue(request, "界" * 401), request)
        diagnostic = self.diagnostics_for(caught.exception, request["claims"][0]["id"], "basis")[0]
        self.assertEqual((diagnostic["observed_length"], diagnostic["limit"]), (401, 400))

    def test_repair_diagnostics_cover_distinct_bad_claims_in_the_same_batch(self):
        request, _ = captured("17")
        other = copy.deepcopy(request["claims"][0])
        other["id"] = "claim-v7-second"
        request["claims"].append(other)
        request["draft"]["body"] = "\n".join(c["text"] for c in request["claims"])
        raw = no_issue(request)
        raw["claim_verdicts"][0]["basis"] = "x" * 401
        raw["claim_verdicts"][1]["verdict"] = "insufficient_evidence"
        provider = OfflineProvider(raw, no_issue(request))
        result = ContinuityEngine(provider).execute(request)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(provider.requests), 2)
        diagnostics = provider.requests[1]["contract_repair"]["diagnostics"]
        for claim, field in zip(request["claims"], ("basis", "verdict")):
            self.assertTrue(any(d.get("claim_span_id") == claim["id"] and field in diagnostic_field(d)
                                for d in diagnostics), diagnostics)

    def test_complete_multi_claim_decisions_pass_in_one_batch(self):
        data, _ = temporal_case("Mira received the badge.", "The badge exists.", None, None)
        second = copy.deepcopy(data["claims"][0])
        second.update(id="claim-v7-second", text="Mira walked toward the quay.")
        data["claims"].append(second)
        data["draft"]["body"] = "\n".join(claim["text"] for claim in data["claims"])
        raw = no_issue(data)
        provider = OfflineProvider(raw)
        engine = ContinuityEngine(provider)
        self.assertEqual(engine.validate(raw, data), [])
        self.assertEqual(engine._repair_diagnostics(raw, data), [])
        result = engine.execute(data)
        self.assertEqual((result["status"], result["issues"], len(provider.requests)), ("completed", [], 1))
        self.assertEqual([c["id"] for c in provider.requests[0]["claims"]], [c["id"] for c in data["claims"]])

    def test_length_and_missing_issue_for_one_claim_are_reported_together(self):
        request, raw = captured("03")
        raw["claim_verdicts"][0]["basis"] = "x" * 401
        provider = OfflineProvider(raw, repaired_badge_gap(request))
        result = ContinuityEngine(provider).execute(request)
        self.assertEqual((result["status"], len(provider.requests)), ("completed", 2))
        repair = provider.requests[1]["contract_repair"]
        self.assertEqual(repair["rejected_claim_verdicts"], raw["claim_verdicts"])
        own = [d for d in repair["diagnostics"] if d.get("claim_span_id") == request["claims"][0]["id"]]
        self.assertTrue(any("basis" in diagnostic_field(d) and d.get("observed_length") == 401
                            and d.get("limit") == 400 for d in own), own)
        self.assertTrue(any("verdict" in diagnostic_field(d) and
                            "claim_verdicts_issue_mismatch" in d["problem_codes"] for d in own), own)

    def test_near_budget_repair_keeps_feedback_complete_and_does_not_dispatch(self):
        data, _ = temporal_case("Mira received the badge.", "The badge exists.", None, None)
        engine = ContinuityEngine(OfflineProvider())

        def padded(count):
            candidate = copy.deepcopy(data)
            text = "Mira received the badge. " + "x" * count
            candidate["claims"][0]["text"] = text
            candidate["draft"]["body"] = text
            request = engine._request(candidate["claims"], candidate["memory"], candidate["draft"])
            return candidate, request_prompt_and_budget(request)[1]

        low, high = 0, MAX_INPUT_BUDGET_UNITS * 4
        while low < high:
            middle = (low + high + 1) // 2
            if padded(middle)[1] <= MAX_INPUT_BUDGET_UNITS - 100:
                low = middle
            else:
                high = middle - 1
        data, first_budget = padded(low)
        self.assertLessEqual(first_budget, MAX_INPUT_BUDGET_UNITS)
        self.assertGreater(first_budget, MAX_INPUT_BUDGET_UNITS - 110)
        raw = no_issue(data, "z" * 1601)
        original = copy.deepcopy(raw)
        provider = OfflineProvider(raw)
        engine = ContinuityEngine(provider)
        repair_checks = []

        def observe_budget(request):
            measured = request_prompt_and_budget(request)
            if "contract_repair" in request:
                repair_checks.append((copy.deepcopy(request), measured[1]))
            return measured

        with patch("app.engine.request_prompt_and_budget", side_effect=observe_budget):
            result = engine.execute(data)
        self.assertEqual((result["status"], result["error_code"]), ("failed", "input_budget_exceeded"))
        self.assertEqual(len(provider.requests), 1, "An oversized repair must fail before evaluate")
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (1, 1))
        self.assertEqual(len(repair_checks), 1)
        request, repair_budget = repair_checks[0]
        self.assertGreater(repair_budget, MAX_INPUT_BUDGET_UNITS)
        self.assertEqual(request["contract_repair"]["rejected_claim_verdicts"], original["claim_verdicts"])
        self.assertEqual(raw, original)

    def test_same_day_hhmm_chinese_and_am_pm_positive_controls(self):
        cases = [
            ("At 10:00 today Mira holds the badge.", "At 10:00 today Mira does not hold the badge.", "10:00", "10:00"),
            ("At 10:00 on the same day Mira holds the badge.", "At 10:00 on the same day Mira does not hold the badge.", "10:00", "10:00"),
            ("今日十八点，米拉持有徽章。", "今日十八点，米拉没有持有徽章。", "十八点", "十八点"),
            ("今天14:00，米拉持有徽章。", "今天14:00，米拉没有持有徽章。", "14:00", "14:00"),
            ("At 10am on the same day Mira holds the badge.", "At 10am on the same day Mira does not hold the badge.", "10am on the same day", "10am on the same day"),
        ]
        for values in cases:
            with self.subTest(anchor=values[2]):
                data, raw = temporal_case(*values)
                engine = ContinuityEngine(OfflineProvider())
                self.assertEqual(engine.validate(raw, data)[0]["nature"], "confirmed_conflict")
                self.assertEqual(engine._repair_diagnostics(raw, data), [])

    def test_different_minutes_hours_dates_or_missing_shared_day_are_not_overlap(self):
        cases = [
            ("At 10:01 today Mira holds the badge.", "At 10:00 today Mira does not hold the badge.", "10:01", "10:00"),
            ("At 11:00 today Mira holds the badge.", "At 10:00 today Mira does not hold the badge.", "11:00", "10:00"),
            ("At 10:00 today Mira holds the badge.", "At 10:00 yesterday Mira does not hold the badge.", "10:00", "10:00"),
            ("On 2026-09-27 at 10:00 Mira holds the badge.", "On 2026-09-28 at 10:00 Mira does not hold the badge.", "10:00", "10:00"),
            ("At 10:00 Mira holds the badge.", "At 10:00 Mira does not hold the badge.", "10:00", "10:00"),
            ("At 10am on the same day Mira holds the badge.", "At 10pm on the same day Mira does not hold the badge.", "10am on the same day", "10pm on the same day"),
        ]
        cases.extend((f"At {clock} today Mira holds the badge.",
                      f"At {clock} today Mira does not hold the badge.", clock, clock)
                     for clock in ("x14:00", "10:00pmx", "10:00 pmx"))
        for values in cases:
            with self.subTest(claim=values[0], evidence=values[1]):
                self.assert_temporal_rejected(*temporal_case(*values))

    def test_quoted_and_recalled_time_does_not_assert_current_world_state(self):
        for framed in ("At 10:00 today Mira said she held the badge.",
                       "In a flashback at 10:00 today Mira holds the badge.",
                       "今日十八点，米拉回忆自己持有徽章。"):
            chinese = framed.startswith("今日")
            evidence = "今日十八点，米拉没有持有徽章。" if chinese else "At 10:00 today Mira does not hold the badge."
            anchor = "十八点" if chinese else "10:00"
            with self.subTest(framed=framed):
                self.assert_temporal_rejected(*temporal_case(framed, evidence, anchor, anchor))

    def test_time_in_only_context_cannot_qualify_the_contradicting_span(self):
        # Chinese clock already worked before V7: this specifically catches the
        # old collector accepting a context-only match that validate rejected.
        data, raw = temporal_case("今日十点，米拉持有徽章。", "今日米拉没有持有徽章。", "十点", "十点")
        context = {"id": "context-v7", "chapter_id": "context-chapter-v7", "body": "今日十点，钟声响起。"}
        data["claims"][0]["allowed_evidence"].append(context)
        raw["issues"][0]["evidence"].append({"chapter_id": context["chapter_id"], "span_id": context["id"],
                                             "relation": "context", "sufficiency": "sufficient", "related_memory_ids": []})
        raw["issues"][0]["evidence_chain"].append({"span_id": context["id"], "role": "current_context"})
        self.assert_temporal_rejected(data, raw)

    def test_compatible_no_issue_and_reviewed_state_change_remain_valid(self):
        data, raw = temporal_case("At 11:00 today Mira received the badge.", "At 10:00 today Mira did not hold the badge.", "11:00", "10:00")
        engine = ContinuityEngine(OfflineProvider())
        self.assertEqual(engine.validate(no_issue(data), data), [])
        issue = raw["issues"][0]
        issue["nature"] = "state_change"
        issue["temporal_basis"]["relation"] = "explicit_later_transition"
        issue["evidence"][0]["relation"] = "supports"
        self.assertEqual(engine.validate(raw, data)[0]["nature"], "state_change")

    def test_citation_identity_and_chapter_guards_are_not_relaxed(self):
        data, original = temporal_case("At 10:00 today Mira holds the badge.", "At 10:00 today Mira does not hold the badge.", "10:00", "10:00")
        for field, value in (("span_id", "unselected-span"), ("chapter_id", "wrong-chapter"),
                             ("related_memory_ids", ["unknown-memory"])):
            with self.subTest(field=field):
                raw = copy.deepcopy(original)
                raw["issues"][0]["evidence"][0][field] = value
                with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
                    ContinuityEngine(OfflineProvider()).validate(raw, data)


if __name__ == "__main__":
    unittest.main()
