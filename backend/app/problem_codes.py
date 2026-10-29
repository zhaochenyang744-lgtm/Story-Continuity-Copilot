"""Stable rule codes for the checks a model's result goes through (v2.1 telemetry).

A check hands the model a Chinese sentence saying what is wrong with its result. The sentence is for the model and changes
whenever the wording is improved; the code is for counting which rule fails most often, and does not. A `Problem` is that
sentence (a `str`, so everything that sends, compares or joins problems keeps working) with its code attached.

Only the code and how often it came up are ever stored, never the sentence: a sentence may quote the author's text.
"""
from __future__ import annotations

from typing import Any

OTHER = "other"


class Problem(str):
    """A problem sentence for the model, carrying the rule code it was raised under."""
    code: str

    def __new__(cls, code: str, text: str) -> "Problem":
        self = super().__new__(cls, text)
        self.code = code
        return self


def code_of(problem: Any) -> str:
    return getattr(problem, "code", OTHER)


def codes_of(problems: list[Any]) -> list[str]:
    return [code_of(problem) for problem in problems]


# Every code, with what the rule says. The usage statistics and docs/usage-stats.md name these; a code is never renamed
# or reused for another rule (add a new one instead), so releases can be compared.
CODES: dict[str, str] = {
    # -- an answer (ask, fix_issue, change) --
    "answer_args_invalid": "the answer call's arguments are not an object",
    "status_invalid": "status is none of answered, not_found, inconsistent",
    "sentences_not_list": "sentences is not an array",
    "sentences_over_limit": "more sentences than the kind allows",
    "note_not_text": "note is not text",
    "note_too_long": "note is over the length limit",
    "sentence_malformed": "a sentence is not {text, refs}",
    "ref_not_r_format": "a cited source is not an R number",
    "ref_unknown": "a cited source number was never returned by a tool",
    "sentence_empty": "a sentence has no text",
    "sentence_too_long": "a sentence is over the length limit",
    "internal_id_in_sentence": "an internal id appears in a sentence",
    "sentence_no_ref": "a sentence cites nothing",
    "label_invalid": "a label is not words of its sentence, or too long",
    "lead_misplaced": "a lead is not the first sentence",
    "refusal_cited": "a cited sentence is a refusal or rewrite advice",
    "absence_cited": "a cited sentence says what the text does not say",
    "attribution_cited": "a cited sentence restates the author's own words",
    "people_unsupported": "a fact-only sentence names someone its facts do not mention",
    "internal_id_in_note": "an internal id appears in the note",
    "ref_in_note": "an R number appears in the note",
    "status_needs_sentence": "answered or inconsistent without a sentence",
    "not_found_needs_note": "not_found without a note saying where it looked",
    "inconsistent_one_side": "inconsistent cites only one side",
    "note_untrue": "the note says something was looked at that the steps do not show",
    "change_status_mismatch": "a change was proposed but the answer is not answered",
    "withdrawn_mentioned": "the answer speaks of a proposal the check took back",
    "proposal_id_leak": "a proposal's reason carries an internal id",
    "proposal_state_change": "a state change was given edits",
    "proposal_kinds_missing": "fewer than two kinds of edit, or no edit_this",
    # -- a recap --
    "recap_args_invalid": "the recap call's arguments are not an object",
    "recap_section_invalid": "a recap section is not an array",
    "recap_ending_count": "previous_ending is not exactly one item",
    "recap_over_limit": "a recap section has more items than allowed",
    "recap_item_malformed": "a recap item is not an object",
    "summary_empty": "a recap item has no summary",
    "summary_too_long": "a recap item's summary is over 40 characters",
    "internal_id_in_summary": "an internal id appears in a summary",
    "recap_ref_unknown": "a recap item cites nothing registered",
    "recap_ref_out_of_scope": "a recap item cites this chapter, later text, the draft or a chapterless fact",
    "ending_not_previous_chapter": "previous_ending does not cite the chapter before",
    "ending_not_last_passages": "previous_ending does not cite one of that chapter's last two passages",
    "plan_ref_mixed": "a plan item cites something that is not a plan",
    "plan_only_cited": "a non-plan item cites only plans",
    "recap_person_missing": "a required person has no lasting state in the recap",
    # -- a long task's step report --
    "report_call_missing": "the step's report tool was not called with an object",
    "thread_unknown": "a thread is not one of the listed threads",
    "verdict_invalid": "a thread's verdict is none of resolved, abandoned, open",
    "refs_missing": "a finding that needs passages cites none",
    "refs_over_two": "a finding cites more than two passages",
    "ref_outside_step": "a finding cites a passage outside this step",
    "one_passage_two_threads": "one passage was taken as settling two threads",
    "state_empty": "a state has no text",
    "state_not_quoted": "a state is not the cited passages' own words",
    "conflict_malformed": "a conflict is not an object of the right shape",
    "conflict_fields_missing": "a conflict lacks a side, or its text",
    "fact_unknown": "a stale fact is not one of the listed facts",
    "value_empty": "a stale fact has no new value",
    "fact_fields_invalid": "a missing fact lacks its type, predicate, subject or value",
    "conflict_subject_missing": "a tidy conflict names neither a listed fact nor a subject, predicate and type",
    # -- an item the program dropped after the result was handed in (ToolError codes of `assistant_actions`) --
    "change_evidence_invalid": "a card's evidence does not stand",
    "change_fact_already_recorded": "the fact is already recorded",
}


def count(codes: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for code in codes:
        found[code] = found.get(code, 0) + 1
    return found
