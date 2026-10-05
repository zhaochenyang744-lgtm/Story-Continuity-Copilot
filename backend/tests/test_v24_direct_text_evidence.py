"""Evidence selection keeps the best direct text matches.

A V11 diagnostic (hv11-031) showed retrieval ranking the decisive credit chapter first, yet the
review never saw it: spans with a Memory record are weighted 10x, Memory held only four facts for
the work, and the three evidence slots all went to record-bearing spans that merely shared names.
The review then correctly said the credit was never supplied. Two slots now always go to the
spans that match the claim's own words best.
"""
from __future__ import annotations

import unittest

from app.engine import CONTINUITY_DIRECT_TEXT_SLOTS, CONTINUITY_EVIDENCE_LIMIT, ContinuityEngine


def span(span_id: str, body: str) -> dict:
    return {"id": span_id, "chapter_id": "chapter-" + span_id, "body": body}


class DirectTextEvidenceTests(unittest.TestCase):
    def test_best_text_match_without_a_memory_record_is_not_crowded_out(self):
        claim = {"id": "claim-1", "text": "Feska Noll was the sole translator credited for Small River.",
                 "allowed_evidence": [
                     span("register", "The pen name Rell belonged to translator Odrin Vale; Feska Noll used her own name."),
                     span("collection", "The collection held Small River, Stone Sleep and Dewline."),
                     span("ledger", "Dewline remained unpublished; the press waited for a corrected file."),
                     span("margins", "A stack of margins sat on the desk of the translator."),
                     span("credit", "The approved credit for the Small River translation named Rell as its sole translator, with no co-translator."),
                 ]}
        memory = [
            {"id": "m1", "source_span_id": "register", "subject": "Pen name Rell", "predicate": "identity", "value": "Odrin Vale, translator; Feska Noll used her own name"},
            {"id": "m2", "source_span_id": "collection", "subject": "The collection", "predicate": "rule", "value": "Small River, Stone Sleep, Dewline"},
            {"id": "m3", "source_span_id": "ledger", "subject": "Dewline", "predicate": "status", "value": "unpublished translation"},
            {"id": "m4", "source_span_id": "margins", "subject": "translator margins", "predicate": "status", "value": "translator notes"},
        ]
        selected = ContinuityEngine(provider=None)._selected_evidence(claim, memory)
        ids = [item["id"] for item in selected]
        self.assertEqual((CONTINUITY_EVIDENCE_LIMIT, CONTINUITY_DIRECT_TEXT_SLOTS), (3, 2))
        self.assertEqual(len(ids), 3)
        self.assertIn("credit", ids)
        self.assertIn("register", ids)

    def test_few_spans_are_all_kept(self):
        claim = {"id": "claim-2", "text": "灯塔在夜里亮着。", "allowed_evidence": [span("a", "灯塔夜里不亮。")]}
        self.assertEqual([item["id"] for item in ContinuityEngine(provider=None)._selected_evidence(claim, [])], ["a"])


if __name__ == "__main__":
    unittest.main()
