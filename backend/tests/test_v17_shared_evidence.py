"""Within one review request each source span is shown once, and a batch holds at most four claims.

Production, 2026-09-30: one 816-character chapter put 10 distinct spans into 113 evidence slots, because
every claim carried its own copy of every excerpt. On imported works a span is a whole chapter, and each
claim's excerpt is a window anchored on that claim's wording, so claims can need different parts of it;
the shared excerpt is the union of those windows.
"""
from __future__ import annotations

import json
import unittest

from app.engine import CONTINUITY_MAX_CLAIMS_PER_BATCH, ContinuityEngine, _share_batch_excerpts
from app.provider import continuity_prompt, request_prompt_and_budget


class Offline:
    available = True
    continuity_contract_version = "v6"
    label = model_label = "shared-evidence"

    def evaluate(self, request):
        raise AssertionError("offline")


def span(span_id: str, body: str, excerpt: str) -> dict:
    return {"id": span_id, "chapter_id": f"chapter-{span_id}", "body": body, "prompt_excerpt": excerpt}


class ShareBatchExcerptsTests(unittest.TestCase):
    def test_identical_excerpts_are_kept_as_they_are(self):
        claims = [{"id": f"c{index}", "text": "x", "allowed_evidence": [span("s", "短句。", "短句。")]} for index in (1, 2)]
        shared = _share_batch_excerpts(claims)
        self.assertEqual({item["allowed_evidence"][0]["prompt_excerpt"] for item in shared}, {"短句。"})

    def test_different_windows_of_one_span_become_their_union(self):
        body = "".join(chr(0x4E00 + index) for index in range(40))
        claims = [{"id": "c1", "text": "x", "allowed_evidence": [span("s", body, body[0:10])]},
                  {"id": "c2", "text": "y", "allowed_evidence": [span("s", body, body[5:15])]},
                  {"id": "c3", "text": "z", "allowed_evidence": [span("s", body, body[30:35])]}]
        shared = _share_batch_excerpts(claims)
        expected = body[0:15] + "…" + body[30:35]
        self.assertEqual([item["allowed_evidence"][0]["prompt_excerpt"] for item in shared], [expected] * 3)
        self.assertLessEqual(len(expected), sum(len(claim["allowed_evidence"][0]["prompt_excerpt"]) for claim in claims))

    def test_an_excerpt_not_found_in_the_body_is_still_shown(self):
        claims = [{"id": "c1", "text": "x", "allowed_evidence": [span("s", "正文。", "甲")]},
                  {"id": "c2", "text": "y", "allowed_evidence": [span("s", "正文。", "乙")]}]
        self.assertEqual({item["allowed_evidence"][0]["prompt_excerpt"] for item in _share_batch_excerpts(claims)}, {"甲…乙"})


class PromptLayoutTests(unittest.TestCase):
    def test_each_span_appears_once_and_claims_list_ids(self):
        claims = [{"id": f"c{index}", "text": f"林默第{index}次张开左手。", "allowed_evidence": [
            span("s1", "林默左手缺一根小指。", "林默左手缺一根小指。"), span("s2", "林默是记录员。", "林默是记录员。")]}
            for index in range(1, 4)]
        prompt = json.loads(continuity_prompt({"draft": {"id": "d", "revision": 1, "body": ""}, "claims": claims,
                                               "memory": [], "output_schema": {}}))
        self.assertEqual([item["id"] for item in prompt["evidence_spans"]], ["s1", "s2"])
        self.assertEqual({tuple(item["allowed_evidence"]) for item in prompt["current_claims"]}, {("s1", "s2")})

    def test_the_model_sees_what_validation_binds(self):
        body = "".join(chr(0x4E00 + index) for index in range(2000))
        claims = [{"id": f"c{index}", "text": body[index * 400:index * 400 + 6], "allowed_evidence": [
            {"id": "long", "chapter_id": "chapter-long", "body": body}]} for index in range(3)]
        data = {"draft": {"id": "d", "revision": 1, "body": ""}, "claims": claims, "memory": []}
        for batch in ContinuityEngine(Offline())._batches(data):
            shown = {item["id"]: item["excerpt"] for item in json.loads(request_prompt_and_budget(batch)[0])["evidence_spans"]}
            for claim in batch["claims"]:
                for evidence in claim["allowed_evidence"]:
                    self.assertEqual(evidence["prompt_excerpt"], shown[evidence["id"]])


class ClaimCapTests(unittest.TestCase):
    def test_no_batch_holds_more_than_the_cap(self):
        claims = [{"id": f"c{index}", "text": f"第{index}句。", "allowed_evidence": [span("s", "短句。", "短句。")]} for index in range(1, 12)]
        batches = ContinuityEngine(Offline())._batches({"draft": {"id": "d", "revision": 1, "body": ""}, "claims": claims, "memory": []})
        self.assertEqual([len(batch["claims"]) for batch in batches], [4, 4, 3])
        self.assertEqual(CONTINUITY_MAX_CLAIMS_PER_BATCH, 4)

    def test_claims_sharing_a_long_span_fit_together_again(self):
        # Before sharing, three 500-character excerpts per claim left room for one claim per request.
        body = "".join(chr(0x4E00 + index % 3000) for index in range(1600))
        spans = [{"id": f"s{index}", "chapter_id": f"chapter-{index}", "body": body[index * 400:index * 400 + 800]} for index in range(3)]
        claims = [{"id": f"c{index}", "text": body[index * 97:index * 97 + 8] + "。", "allowed_evidence": spans} for index in range(4)]
        batches = ContinuityEngine(Offline())._batches({"draft": {"id": "d", "revision": 1, "body": ""}, "claims": claims, "memory": []})
        self.assertLess(len(batches), len(claims))


if __name__ == "__main__":
    unittest.main()
