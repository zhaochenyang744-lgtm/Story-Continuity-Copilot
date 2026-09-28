"""English and ISO calendar dates are explicit time anchors, like Chinese 月/日 dates.

The V9 held-out diagnostic rerun showed confirmed conflicts written as
"At 10:00 on 14 June" being downgraded to insufficient_evidence because the
temporal guard only recognised Chinese calendar units.
"""
from __future__ import annotations

import unittest

from app.engine import _english_calendar, _explicit_temporal_overlap, _full_temporal_scope_supports_conflict


def overlap(claim, evidence, claim_anchor, evidence_anchor):
    return _full_temporal_scope_supports_conflict(claim, evidence, claim_anchor, evidence_anchor)


class EnglishCalendarDateTests(unittest.TestCase):
    def test_recognised_date_forms(self):
        for text, expected in (("on 14 June", {"月": {"6"}, "日": {"14"}}), ("June 14, 2026", {"月": {"6"}, "日": {"14"}, "年": {"2026"}}),
                               ("the 3rd of Sept", {"月": {"9"}, "日": {"3"}}), ("2026-10-09", {"月": {"10"}, "日": {"9"}, "年": {"2026"}})):
            with self.subTest(text=text):
                self.assertEqual(_english_calendar(text), expected)

    def test_ordinary_words_and_invalid_days_are_not_dates(self):
        for text in ("The guard may open the gate.", "She may 2 times knock.", "on 32 June", "Marching band", "2026-13-01"):
            with self.subTest(text=text):
                self.assertEqual(_english_calendar(text), {})
        self.assertEqual(_english_calendar("on 2 May"), {"月": {"5"}, "日": {"2"}})

    def test_same_clock_and_english_date_supports_conflict(self):
        cases = [
            ("At 10:00 on 14 June, Aven was aboard the ferry.", "At 10:00 on 14 June, Aven was in the signal hut.", "At 10:00 on 14 June", "At 10:00 on 14 June"),
            ("At 3pm on June 14, 2026, the bowl measured 18 cm.", "At 3pm on June 14, 2026, the bowl measured 28 cm.", "3pm on June 14, 2026", "3pm on June 14, 2026"),
            ("At 07:10 on 2026-04-22 the case was with Orin.", "At 07:10 on 2026-04-22 the case was with Nessa alone.", "07:10 on 2026-04-22", "07:10 on 2026-04-22"),
        ]
        for values in cases:
            with self.subTest(claim=values[0]):
                self.assertTrue(overlap(*values))

    def test_different_dates_or_missing_dates_still_do_not_overlap(self):
        cases = [
            ("At 10:00 on 14 June, Aven was aboard.", "At 10:00 on 15 June, Aven was ashore.", "At 10:00 on 14 June", "At 10:00 on 15 June"),
            ("At 10:00 on 14 June, Aven was aboard.", "At 10:00 on 14 July, Aven was ashore.", "At 10:00 on 14 June", "At 10:00 on 14 July"),
            ("On 14 June 2025, Aven was aboard.", "On 14 June 2026, Aven was ashore.", "On 14 June 2025", "On 14 June 2026"),
            # A clock with no date or shared-day wording is still not enough.
            ("At 10:00 Aven was aboard.", "At 10:00 Aven was ashore.", "At 10:00", "At 10:00"),
        ]
        for values in cases:
            with self.subTest(claim=values[0], evidence=values[1]):
                self.assertFalse(overlap(*values))

    def test_chinese_dates_behave_as_before(self):
        self.assertTrue(_explicit_temporal_overlap("6月14日10点", "6月14日10点"))
        self.assertFalse(_explicit_temporal_overlap("6月14日10点", "6月15日10点"))


if __name__ == "__main__":
    unittest.main()
