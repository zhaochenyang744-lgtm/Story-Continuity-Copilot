"""Bulk accept/reject of import candidates (long-text phase 2).

A long import yields hundreds of candidates and every core one must be decided before the first
Memory version exists; one request per candidate made that impractical.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult


def idem(value=None):
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class ManyFactsProvider:
    label = "lf-bulk-provider"
    model_label = "lf-bulk-model"
    available = True

    def evaluate(self, request):
        if request.get("task") == "memory_initialization":
            candidates = []
            for source in request["sources"]:
                for number in range(6):
                    candidates.append({"memory_type": "dynamic_state", "subject": f"{source['chapter_title']}物件{number}",
                                       "predicate": "status", "value": f"第{number}号在原处",
                                       "chapter_id": source["chapter_id"], "source_span_id": source["id"]})
            return ProviderResult({"candidates": candidates[:8]})
        return ProviderResult({"issues": []})


class BulkMemoryReviewTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-lf-bulk-"))
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                              provider=ManyFactsProvider(), executor=lambda fn, *args: fn(*args))
        self.client = TestClient(self.app)
        self.client.post("/api/auth/register", json={"account_name": "bulk-author", "display_name": "Bulk",
                                                     "password": "safe-password-123"}, headers=idem())
        source = "\n".join(f"# 第{n}章\n" + "灯塔边的铜铃挂在原处。" * 120 for n in "一二三")
        preview = self.client.post("/api/imports/preview", files={"file": ("long.md", source.encode(), "text/markdown")},
                                   headers=idem()).json()["data"]
        self.project = self.client.post(f"/api/imports/{preview['import_id']}/commit", json={
            "confirm": True, "title": "Bulk", "chapter_preview_ids": [x["preview_id"] for x in preview["detected"]["chapters"]]},
            headers=idem()).json()["data"]["project"]["id"]
        self.init = self.client.post(f"/api/projects/{self.project}/memory/initializations", json={"source_revision": 1},
                                     headers=idem()).json()["data"]["initialization"]
        self.candidates = self.init["candidates"]
        self.assertGreater(len(self.candidates), 12)

    def bulk(self, decisions, key=None):
        return self.client.post(f"/api/projects/{self.project}/memory/initializations/{self.init['id']}/decisions?view=compact",
                                json={"decisions": decisions}, headers=idem(key))

    def statuses(self):
        view = self.client.get(f"/api/projects/{self.project}/memory/initialization").json()["data"]
        return {row["id"]: row["decision_status"] for row in view["candidates"]}

    def test_one_call_decides_a_group_and_the_import_can_commit(self):
        accept = [{"candidate_id": row["id"], "decision": "accepted"} for row in self.candidates[:-3]]
        reject = [{"candidate_id": row["id"], "decision": "rejected"} for row in self.candidates[-3:]]
        response = self.bulk(accept + reject)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["data"]["decided"]), len(self.candidates))
        statuses = self.statuses()
        self.assertEqual(sum(value == "accepted" for value in statuses.values()), len(self.candidates) - 3)
        self.assertEqual(sum(value == "rejected" for value in statuses.values()), 3)
        committed = self.client.post(f"/api/projects/{self.project}/memory/initializations/{self.init['id']}/commit",
                                     json={"confirm": True}, headers=idem())
        self.assertEqual(committed.status_code, 200, committed.text)
        records = self.client.get(f"/api/projects/{self.project}/memory").json()["data"]["records"]
        self.assertEqual(len(records), len(self.candidates) - 3)

    def test_a_replayed_call_is_idempotent_and_a_conflicting_one_is_refused(self):
        decisions = [{"candidate_id": row["id"], "decision": "accepted"} for row in self.candidates[:5]]
        key = str(uuid.uuid4())
        self.assertEqual(self.bulk(decisions, key).status_code, 200)
        self.assertEqual(self.bulk(decisions, key).status_code, 200)
        flipped = [{"candidate_id": row["id"], "decision": "rejected"} for row in self.candidates[:1]]
        self.assertEqual(self.bulk(flipped).status_code, 409)

    def test_one_bad_item_leaves_no_decision_behind(self):
        before = self.statuses()
        good = [{"candidate_id": row["id"], "decision": "accepted"} for row in self.candidates[:4]]
        self.assertEqual(self.bulk(good + [{"candidate_id": "memorycandidate-missing", "decision": "accepted"}]).status_code, 404)
        self.assertEqual(self.bulk(good + [good[0]]).status_code, 422)
        self.assertEqual(self.bulk([{"candidate_id": self.candidates[0]["id"], "decision": "edited"}]).status_code, 400)  # schema: edits go one at a time
        self.assertEqual(self.bulk([]).status_code, 400)
        self.assertEqual(self.statuses(), before)


if __name__ == "__main__":
    unittest.main()
