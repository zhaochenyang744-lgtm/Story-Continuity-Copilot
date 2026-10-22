"""v1.9 recap: a change of role, qualification or health comes first among a person's lasting facts and is what the recap
must write. On the spent fourth A1c pair the three lasting states missed in every pass were in Memory as status facts but
were pushed out of the candidates by newer passing moments."""
from __future__ import annotations

import unittest

from app import assistant_recap as recap

STANDING = (
    "成为有投票权的临时席位代表，接受授权范围与期限，并保留桌边先前的保留意见与授权一同收存。",
    "自昨夜起已经失声，不能正常说话，只能用纸笔沟通；就诊单上记录的也是他眼下的状况。",
    "正式注册学生，可获得所选课程的学分。",
)
PASSING = (
    "有一处已约亲口说明，自己会照时去；其余两处可交由别人代送。",
    "投出赞成票，并请谢允铎确认接下来怎样把范围准确送到实际要过这一夜的人手里。",
    "手里留着一张被住户反复修改的反对意见，纸边磨得很软，字一处也没少。",
    "把自己的住处放进需要承担暗里起床的有限范围，备注只限当次议题的试行核对，不代表全层已经答应。",
    "谈霁禾把上午该发而没发的迟到通知补入自己的记录，标明当时没有做到，不当成已经送达。",
)


class StandingTests(unittest.TestCase):
    def test_role_qualification_and_health_changes_are_standing(self):
        for value in STANDING:
            self.assertTrue(recap.is_standing({"value": value}), value)
        for value in PASSING:
            self.assertFalse(recap.is_standing({"value": value}), value)

    def test_the_newest_standing_fact_is_shown_first_even_when_older(self):
        facts = [{"id": f"p{i}", "value": v} for i, v in enumerate(PASSING)] + [{"id": f"s{i}", "value": v} for i, v in enumerate(STANDING)]
        shown, standing = recap.shown_lasting(facts, recap.LASTING_PER_PERSON)  # newest first: the passing moments are newer
        self.assertEqual([f["id"] for f in shown], ["s0", "p0", "p1"])
        self.assertEqual(standing["id"], "s0")

    def test_a_recovery_is_newer_than_the_injury_and_wins(self):
        facts = [{"id": "new", "value": "已拆掉右腕固定，恢复了握力"}, {"id": "mid", "value": "答应晚些去议事空间"},
                 {"id": "old", "value": "右腕因扭伤固定，无法握紧扳手"}]
        shown, standing = recap.shown_lasting(facts, 3)
        self.assertEqual(standing["id"], "new")
        self.assertEqual([f["id"] for f in shown], ["new", "mid", "old"])

    def test_without_a_standing_fact_the_newest_are_shown(self):
        facts = [{"id": f"p{i}", "value": v} for i, v in enumerate(PASSING)]
        shown, standing = recap.shown_lasting(facts, 3)
        self.assertIsNone(standing)
        self.assertEqual([f["id"] for f in shown], ["p0", "p1", "p2"])


class OverLimitTests(unittest.TestCase):
    def test_after_the_repair_extra_items_are_cut_keeping_the_required_people(self):
        items = [{"summary": f"s{i}", "refs": [f"R{i}"]} for i in range(1, 7)]  # six items, the limit is five
        kept = recap.within_limit(items, [{"name": "x", "refs": ["R6"]}], recap.LIMITS["character_state"])
        self.assertEqual([item["summary"] for item in kept], ["s1", "s2", "s3", "s4", "s6"])

    def test_validate_keeps_the_recap_once_the_repair_is_spent(self):
        sources = {f"R{i}": {"kind": "fact", "chapter_number": 3} for i in range(1, 7)}
        sources["R9"] = {"kind": "passage", "chapter_number": 4, "start": 0, "end": 10}
        args = {"previous_ending": [{"summary": "停在门口。", "refs": ["R9"]}], "open_threads": [], "plan": [],
                "character_state": [{"summary": f"s{i}", "refs": [f"R{i}"]} for i in range(1, 7)]}
        import re
        internal = re.compile(r"memory-")
        cleaned, errors = recap.validate(args, set(sources), sources, 5, internal, strict_ending=False,
                                         required=[{"name": "x", "refs": ["R6"]}])
        self.assertEqual(errors, [])
        self.assertEqual([item["summary"] for item in cleaned["sections"]["character_state"]], ["s1", "s2", "s3", "s4", "s6"])
        _, errors = recap.validate(args, set(sources), sources, 5, internal, strict_ending=True)
        self.assertIn("character_state 最多 5 条，现在是 6 条", errors)


if __name__ == "__main__":
    unittest.main()
