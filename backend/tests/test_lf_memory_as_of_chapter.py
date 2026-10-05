"""Facts carry the chapter they hold from, and Memory can be read as of any chapter (long-text phase 2).

Checking chapter N may only use what chapters 1..N-1 established, including the state a later
chapter has since changed or retired. Memory versions copy every record forward, so the state as of
chapter N is rebuilt from each fact's lineage.
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


def idem():
    return {"Idempotency-Key": str(uuid.uuid4())}


SOURCE = "# 第一章\n林默在雾港。\n# 第二章\n北堤门只在清晨开启。\n# 第三章\n银钥匙由林默保管。"
APPENDED = "# 第四章\n林默离开了雾港。\n# 第五章\n北堤门的旧规矩废除了。银钥匙交给了守塔人，守塔人是新来的看守。"


class HistoryProvider:
    label = "lf-as-of-provider"
    model_label = "lf-as-of-model"
    available = True

    def evaluate(self, request):
        task = request.get("task")
        if task == "memory_initialization":
            by_title = {source["chapter_title"]: source for source in request["sources"]}

            def fact(title, memory_type, subject, predicate, value):
                source = by_title[title]
                return {"memory_type": memory_type, "subject": subject, "predicate": predicate, "value": value,
                        "chapter_id": source["chapter_id"], "source_span_id": source["id"]}
            return ProviderResult({"candidates": [
                fact("第一章", "dynamic_state", "林默", "location", "在雾港"),
                fact("第二章", "static_canon", "北堤门", "rule", "只在清晨开启"),
                fact("第三章", "dynamic_state", "银钥匙", "possession", "林默保管"),
            ]})
        if task == "memory_delta":
            by_title = {source["chapter_title"]: source for source in request["sources"]}
            memory = {item["subject"]: item for item in request["memory"]}
            four, five = by_title["第四章"], by_title["第五章"]

            def change(kind, source, subject, predicate, value, memory_type="dynamic_state"):
                affected = memory[subject]["id"] if kind != "new_fact" else None
                return {"change_kind": kind, "affected_memory_id": affected, "memory_type": memory_type, "subject": subject,
                        "predicate": predicate, "value": value,
                        "invalidation_reason": "第五章写明旧规矩已废除" if kind == "invalidated_fact" else None,
                        "chapter_id": source["chapter_id"], "source_span_id": source["id"]}
            return ProviderResult({"candidates": [
                change("changed_fact", four, "林默", "location", "已离开雾港"),
                change("invalidated_fact", five, "北堤门", "rule", "只在清晨开启", memory_type="static_canon"),
                change("changed_fact", five, "银钥匙", "possession", "守塔人保管"),
                change("new_fact", five, "守塔人", "identity", "新来的看守"),
            ]}, input_tokens=10, output_tokens=5, latency_ms=2)
        return ProviderResult({"issues": []}, input_tokens=8, output_tokens=4, latency_ms=2)


class MemoryAsOfChapterTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-lf-asof-"))
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                              provider=HistoryProvider(), executor=lambda fn, *args: fn(*args))
        self.client = TestClient(self.app)
        self.client.post("/api/auth/register", json={"account_name": "asof-author", "display_name": "AsOf",
                                                     "password": "safe-password-123"}, headers=idem())
        preview = self.post("/api/imports/preview", files={"file": ("base.md", SOURCE.encode(), "text/markdown")})
        self.project = self.post(f"/api/imports/{preview['import_id']}/commit", json={
            "confirm": True, "title": "AsOf", "chapter_preview_ids": [x["preview_id"] for x in preview["detected"]["chapters"]]})["project"]["id"]
        init = self.post(f"/api/projects/{self.project}/memory/initializations", json={"source_revision": 1})["initialization"]
        for candidate in init["candidates"]:
            self.post(f"/api/projects/{self.project}/memory/initializations/{init['id']}/candidates/{candidate['id']}/decision",
                      json={"decision": "accepted"})
        self.post(f"/api/projects/{self.project}/memory/initializations/{init['id']}/commit", json={"confirm": True})
        change = self.post(f"/api/projects/{self.project}/source-change-sets/preview", json={
            "mode": "append", "input_method": "paste", "base_source_revision": 1, "content": APPENDED})["source_change_set"]
        self.post(f"/api/projects/{self.project}/source-change-sets/{change['id']}/commit",
                  json={"confirm": True, "content_sha256": change["content_sha256"]})
        self.client.post(f"/api/projects/{self.project}/incremental-reviews", json={"source_revision": 2}, headers=idem())
        delta = self.client.get(f"/api/projects/{self.project}/memory/delta").json()["data"]
        self.assertEqual(len(delta["candidates"]), 4)
        for candidate in delta["candidates"]:
            self.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/candidates/{candidate['id']}/decision",
                      json={"decision": "accepted"})
        committed = self.post(f"/api/projects/{self.project}/memory/deltas/{delta['id']}/commit", json={"confirm": True})
        self.assertEqual(committed["memory_version"], 2)

    def post(self, path, **kwargs):
        response = self.client.post(path, headers=idem(), **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()["data"]

    def facts(self, chapter):
        response = self.client.get(f"/api/projects/{self.project}/memory?as_of_chapter={chapter}")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["as_of_chapter"], chapter)
        return {(row["subject"], row["value"], row["from_chapter"]) for row in data["records"]}

    def test_each_chapter_sees_only_what_came_before_it(self):
        self.assertEqual(self.facts(1), set())
        self.assertEqual(self.facts(2), {("林默", "在雾港", 1)})
        self.assertEqual(self.facts(4), {("林默", "在雾港", 1), ("北堤门", "只在清晨开启", 2), ("银钥匙", "林默保管", 3)})

    def test_a_later_change_or_retirement_does_not_reach_back(self):
        self.assertEqual(self.facts(5), {("林默", "已离开雾港", 4), ("北堤门", "只在清晨开启", 2), ("银钥匙", "林默保管", 3)})
        self.assertEqual(self.facts(6), {("林默", "已离开雾港", 4), ("银钥匙", "守塔人保管", 5), ("守塔人", "新来的看守", 5)})

    def test_current_memory_reports_the_chapter_each_fact_holds_from(self):
        records = self.client.get(f"/api/projects/{self.project}/memory").json()["data"]["records"]
        active = {(row["subject"], row["from_chapter"]) for row in records if row["valid_to"] is None}
        self.assertEqual(active, {("林默", 4), ("银钥匙", 5), ("守塔人", 5)})

    def test_bad_requests_are_rejected(self):
        self.assertEqual(self.client.get(f"/api/projects/{self.project}/memory?as_of_chapter=0").status_code, 400)
        self.assertEqual(self.client.get(f"/api/projects/{self.project}/memory?as_of_chapter=3&version=1").status_code, 400)


if __name__ == "__main__":
    unittest.main()
