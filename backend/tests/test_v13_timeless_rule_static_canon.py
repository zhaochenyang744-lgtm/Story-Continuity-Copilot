"""A timeless-rule conflict may rest on any cited static_canon Memory, whatever its predicate.

Production (zero_garden seed, 2026-09-29): the world rule was stored as static_canon with the
free-form predicate blue_light_window. Requiring predicate == "rule" rejected the model's correct
conflict as timeless_rule_unproven, and the unsatisfiable repair spent 60-75 s thinking before
the result was downgraded or failed.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from app.config import AppPaths
from app.engine import _confirmed_temporal_failure
from app.v2_database import V2Database


def conflict(span_id="span-rule", memory_ids=("mem-1",)):
    return {"nature": "confirmed_conflict", "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "timeless_rule"}}, [
        {"span_id": span_id, "relation": "contradicts", "sufficiency": "sufficient", "excerpt": "萤苔只在零点到零点十分钟发蓝光。",
         "related_memory_ids": list(memory_ids)}]


class TimelessRuleStaticCanonTests(unittest.TestCase):
    def check(self, memory_type, predicate, source_span="span-rule", cited_span="span-rule"):
        raw, evidence = conflict(cited_span)
        memory = {"mem-1": {"memory_type": memory_type, "predicate": predicate, "source_span_id": source_span}}
        return _confirmed_temporal_failure(raw, "凌晨三点，萤苔发出蓝光。", evidence, memory)

    def test_any_static_canon_predicate_grounds_a_timeless_rule(self):
        for predicate in ("rule", "blue_light_window", "entry_rule", "ring_condition"):
            with self.subTest(predicate=predicate):
                self.assertIsNone(self.check("static_canon", predicate))

    def test_mutable_memory_or_uncited_source_still_cannot_ground_it(self):
        for memory_type in ("dynamic_state", "event_timeline", "character_knowledge", "open_thread"):
            with self.subTest(memory_type=memory_type):
                self.assertEqual(self.check(memory_type, "rule"), "timeless_rule_unproven")
        self.assertEqual(self.check("static_canon", "rule", source_span="another-span"), "timeless_rule_unproven")
        raw, evidence = conflict(memory_ids=())
        self.assertEqual(_confirmed_temporal_failure(raw, "x", evidence, {}), "timeless_rule_unproven")

    def test_seeded_world_rules_use_the_controlled_rule_predicate(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v13-seed-"))
        db = V2Database(AppPaths.from_project_root(root, protected_poc_root=root / "protected")); db.initialize()
        registered, _ = db.register({"account_name": f"seed{uuid.uuid4().hex[:8]}", "display_name": "Seed",
                                     "password": "seed-local-password-123"}, str(uuid.uuid4()))
        user = registered["user"]["id"]
        with db.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            projects = [db._create_project(c, user, key, "g", "s", "demo_seed", key) for key in ("grey_harbor", "paper_moon", "zero_garden")]
        with db.connection() as c:
            rows = c.execute(f"SELECT subject,predicate FROM v2_memory_records WHERE memory_type='static_canon' AND project_id IN ({','.join('?' * len(projects))})",
                             projects).fetchall()
        predicates = {row["subject"]: row["predicate"] for row in rows}
        for subject in ("灰港雾钟", "纸月档案", "萤苔", "培育区"):
            self.assertEqual(predicates.get(subject), "rule", subject)


if __name__ == "__main__":
    unittest.main()
