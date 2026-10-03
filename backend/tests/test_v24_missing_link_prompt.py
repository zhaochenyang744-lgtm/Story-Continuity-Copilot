"""Continuity review v24: a gap must be reported, never answered with silence.

V11 failed insufficient_evidence recall twice on one shape: the draft settles a point the source
explicitly leaves open (one part of a combined total, every item from a sample, an outcome from an
attempt) and the review returned no issue at all. v22 told the model that "ordinary compatible new
events" may be no_issue, which did not separate a new event the draft narrates from a claim that
resolves an open point about a recorded fact. v24 draws that line, makes a no_issue basis that says
"the source does not record this" self-contradictory, and teaches the gap with three examples plus
one contrast that keeps a direct contradiction a conflict.
"""
from __future__ import annotations

import json
import unittest

from app.provider import CONTINUITY_DECISION_EXAMPLES, CONTINUITY_PROMPT_VERSION, continuity_prompt


def prompt() -> dict:
    body = "雁回把整箱十二支笛子都调成了同一个音高。"
    evidence = "乐坊只抽查了其中两支笛子，音高一致，其余十支没有试吹。"
    return json.loads(continuity_prompt({
        "draft": {"id": "draft-v24", "revision": 1, "body": body},
        "claims": [{"id": "claim-v24", "text": body, "allowed_evidence": [
            {"id": "span-v24", "chapter_id": "chapter-v24", "body": evidence, "prompt_excerpt": evidence}]}],
        "memory": [], "output_schema": {}}))


class MissingLinkPromptV24Tests(unittest.TestCase):
    def test_version_names_the_change(self):
        self.assertEqual(CONTINUITY_PROMPT_VERSION, "continuity-review-v24c-explicit-missing-link")

    def test_rules_separate_narrated_events_from_settled_open_points(self):
        rules = "\n".join(prompt()["rules"])
        self.assertIn("new events the draft itself narrates; settling a point the material leaves open is insufficient_evidence, not compatible information", rules)
        self.assertIn("report insufficient_evidence and name the missing link: compatible is not established, and silence is not allowed", rules)
        self.assertIn("A direct contradiction, or one proved by combining supplied facts, is a conflict-status issue, not a gap.", rules)
        # The v22 permission that let a settled open point pass as a compatible event is gone.
        self.assertNotIn("Ordinary compatible new events do not require an old source warrant", rules)

    def test_a_no_issue_basis_that_names_a_gap_is_self_contradictory(self):
        rules = "\n".join(prompt()["rules"])
        self.assertIn("A no_issue basis saying the sources do not record or confirm the point means insufficient_evidence.", rules)

    def test_examples_teach_the_gap_and_keep_combined_contradictions_as_conflicts(self):
        decisions = [example["decision"] for example in CONTINUITY_DECISION_EXAMPLES]
        self.assertEqual(sum(decision.startswith("insufficient_evidence") for decision in decisions), 4)
        self.assertIn("A conflict-status issue citing every premise, not insufficient_evidence.", decisions)


if __name__ == "__main__":
    unittest.main()
