"""No-network fixture consistency and pre-dispatch negative controls."""
from __future__ import annotations

import copy
import json
import pathlib
import tempfile
import unittest

from evaluation.current_flash_v2 import run as v2
from evaluation.current_flash_v3 import fixture

CASES = json.loads((v2.HERE / "cases.json").read_text(encoding="utf-8"))["g03"]


class FixtureRepairTest(unittest.TestCase):
    def test_all_four_parent_span_and_memory_contracts(self):
        with tempfile.TemporaryDirectory() as temporary:
            for case in CASES:
                with self.subTest(case=case["id"]):
                    runtime = fixture.create_case_runtime(case, object(), pathlib.Path(temporary) / case["id"])
                    try:
                        fixture.check_database(runtime.app.state.database, runtime.identity.project_id, case)
                    finally:
                        runtime.client.close()

    def test_parent_span_mismatch_rejected_before_provider(self):
        case = CASES[0]
        with tempfile.TemporaryDirectory() as temporary:
            runtime = fixture.create_case_runtime(case, object(), pathlib.Path(temporary) / case["id"])
            try:
                with runtime.app.state.database.connection() as connection:
                    connection.execute("UPDATE v2_chapters SET body=? WHERE id=?", ("wrong parent text", fixture.CHAPTER1))
                with self.assertRaisesRegex(RuntimeError, "fixture_chapter_span_body_mismatch"):
                    fixture.check_database(runtime.app.state.database, runtime.identity.project_id, case)
            finally:
                runtime.client.close()

    def test_memory_type_rejected_at_db_and_request_layers(self):
        case = CASES[0]
        with tempfile.TemporaryDirectory() as temporary:
            runtime = fixture.create_case_runtime(case, object(), pathlib.Path(temporary) / case["id"])
            try:
                with runtime.app.state.database.connection() as connection:
                    connection.execute("UPDATE v2_memory_records SET memory_type=? WHERE id=?", ("event_timeline", fixture.MEMORY))
                with self.assertRaisesRegex(RuntimeError, "fixture_memory_contract_mismatch"):
                    fixture.check_database(runtime.app.state.database, runtime.identity.project_id, case)
            finally:
                runtime.client.close()

        valid = {"task": "change_impact", "proposal": {"target_id": fixture.MEMORY},
                 "layers": {"confirmed": {"memory_records": [{"id": fixture.MEMORY, "subject": "星钥", "predicate": "holder",
                     "value": fixture.FACT, "source_span_id": fixture.TARGET, "memory_type": "dynamic_state"}]},
                     "written": {"source_spans": [{"id": fixture.TARGET, "chapter_id": fixture.CHAPTER1, "body": v2.g03_body(case)},
                                                   {"id": fixture.OTHER, "chapter_id": fixture.CHAPTER2, "body": case["other_body"]}]},
                     "reference": {"chapters": [{"id": fixture.CHAPTER1}, {"id": fixture.CHAPTER2}]}},
                 "retrieval": {"target_source": {"status": "selected"}}}
        fixture.check_request(case, valid)
        bad = copy.deepcopy(valid)
        bad["layers"]["confirmed"]["memory_records"][0]["memory_type"] = "event_timeline"
        with self.assertRaisesRegex(RuntimeError, "g03_memory_type_mismatch"):
            fixture.check_request(case, bad)


if __name__ == "__main__":
    unittest.main()
