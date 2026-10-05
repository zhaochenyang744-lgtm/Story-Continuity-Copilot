"""Fact extraction reads whole chapters (long-text phase 2).

Before this change a memory delta sent at most 12 SourceSpans cut to their first 1,600 characters and
kept at most 4 candidates, so anything stated in the second half of a ~2,500-character chapter never
reached the fact library, and imports capped every batch at 4 facts.
"""
from __future__ import annotations

import json
import unittest

from app.engine import MemoryDeltaEngine, MemoryInitializationEngine
from app.provider import (MAX_INPUT_BUDGET_UNITS, MAX_MEMORY_CANDIDATES_PER_BATCH, ProviderFailure, ProviderResult,
                          memory_delta_prompt, memory_initialization_prompt, request_prompt_and_budget)


def chapter(index: int, sentences: int) -> dict:
    body = "".join(f"第{index}章第{number}句，守灯人把铜灯擦亮后挂回原处。" for number in range(sentences))
    return {"id": f"span-{index}", "chapter_id": f"chapter-{index}", "chapter_number": index,
            "chapter_title": f"第{index}章", "label": "append", "body": body}


class EchoProvider:
    """Proposes one fact per request, naming the last sentence it was shown."""
    available = True
    label = "lf-phase2-provider"
    model_label = "lf-phase2-model"

    def __init__(self, fail_on=None, duplicate=False):
        self.requests = []
        self.fail_on = fail_on
        self.duplicate = duplicate

    def evaluate(self, request):
        self.requests.append(request)
        if self.fail_on == len(self.requests):
            raise ProviderFailure()
        source = request["sources"][-1]
        tail = source["body"].rstrip("。").split("。")[-1][:40]
        subject = "铜灯" if self.duplicate else f"片段{len(self.requests)}"
        candidate = {"change_kind": "new_fact", "affected_memory_id": None, "memory_type": "dynamic_state",
                     "subject": subject, "predicate": "status", "value": tail, "invalidation_reason": None,
                     "chapter_id": source["chapter_id"], "source_span_id": source["id"]}
        return ProviderResult({"candidates": [candidate]}, input_tokens=100, output_tokens=20, latency_ms=5)


class WholeChapterDeltaTests(unittest.TestCase):
    def test_a_long_chapter_is_read_to_its_last_sentence_in_budgeted_pieces(self):
        long = chapter(7, 400)  # about 9,600 characters, far over one request's budget
        data = {"source_revision": 3, "sources": [long], "memory": []}
        engine = MemoryDeltaEngine(EchoProvider())
        batches = engine._batches(data)
        self.assertGreater(len(batches), 1)
        self.assertTrue(all(request_prompt_and_budget(batch)[1] <= MAX_INPUT_BUDGET_UNITS for batch in batches))
        pieces = [source for batch in batches for source in batch["sources"]]
        self.assertTrue(all(piece["id"] == "span-7" for piece in pieces))
        self.assertTrue(pieces[0]["body"].startswith("第7章第0句"))
        self.assertTrue(pieces[-1]["body"].endswith(long["body"][-30:]))
        covered = set()
        for piece in pieces:
            start = long["body"].find(piece["body"])
            self.assertGreaterEqual(start, 0)  # each piece is a contiguous slice of the chapter
            covered.update(range(start, start + len(piece["body"])))
        self.assertEqual(covered, set(range(len(long["body"]))))

    def test_candidates_from_every_piece_are_merged_and_traced(self):
        data = {"source_revision": 3, "sources": [chapter(7, 400), chapter(8, 30)], "memory": []}
        provider = EchoProvider()
        result = MemoryDeltaEngine(provider).execute(data)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["candidates"]), len(provider.requests))
        self.assertGreater(len(provider.requests), 1)
        sent = json.dumps([request["sources"] for request in provider.requests], ensure_ascii=False)
        self.assertIn("第7章第399句", sent)  # the old 1,600-character cut stopped near sentence 66
        self.assertIn("第8章第29句", sent)
        self.assertEqual(result["retrieval"]["batches"], len(provider.requests))
        self.assertEqual(result["retrieval"]["selected_source_span_ids"], ["span-7", "span-8"])
        self.assertFalse(result["retrieval"]["truncated"]["source_spans"])
        self.assertEqual(result["input_tokens"], 100 * len(provider.requests))

    def test_the_same_fact_found_in_overlapping_pieces_is_kept_once(self):
        data = {"source_revision": 3, "sources": [chapter(7, 400)], "memory": []}
        provider = EchoProvider(duplicate=True)
        result = MemoryDeltaEngine(provider).execute(data)
        self.assertGreater(len(provider.requests), 1)
        self.assertEqual(len(result["candidates"]), 1)

    def test_a_failed_later_batch_fails_the_run_but_reports_spent_usage(self):
        data = {"source_revision": 3, "sources": [chapter(7, 400)], "memory": []}
        result = MemoryDeltaEngine(EchoProvider(fail_on=2)).execute(data)
        self.assertEqual(result["error_code"], "provider_error")
        self.assertEqual(result["input_tokens"], 100)

    def test_a_short_chapter_still_takes_one_request(self):
        provider = EchoProvider()
        MemoryDeltaEngine(provider).execute({"source_revision": 3, "sources": [chapter(9, 20)], "memory": []})
        self.assertEqual(len(provider.requests), 1)


class CandidateCapTests(unittest.TestCase):
    def candidate(self, number: int) -> dict:
        return {"change_kind": "new_fact", "affected_memory_id": None, "memory_type": "dynamic_state",
                "subject": f"物件{number}", "predicate": "status", "value": "在原处", "invalidation_reason": None,
                "chapter_id": "chapter-9", "source_span_id": "span-9"}

    def test_eight_candidates_pass_and_nine_do_not(self):
        self.assertEqual(MAX_MEMORY_CANDIDATES_PER_BATCH, 8)
        engine = MemoryDeltaEngine(EchoProvider())
        data = {"sources": [chapter(9, 5)], "memory": []}
        self.assertEqual(len(engine.validate({"candidates": [self.candidate(n) for n in range(8)]}, data)), 8)
        with self.assertRaises(ValueError):
            engine.validate({"candidates": [self.candidate(n) for n in range(9)]}, data)

    def test_prompts_ask_for_rules_and_whole_spans(self):
        init_request = MemoryInitializationEngine(EchoProvider())._request([chapter(1, 5)], 1)
        init_prompt = memory_initialization_prompt(init_request)
        self.assertIn('"max_candidates":8', init_prompt)
        self.assertIn("predicate rule", init_prompt)
        self.assertIn("including its last paragraphs", init_prompt)
        delta_request = MemoryDeltaEngine(EchoProvider())._request({"source_revision": 2, "sources": [chapter(2, 5)], "memory": []})
        delta_prompt = memory_delta_prompt(delta_request)
        self.assertIn("to its end", delta_prompt)
        self.assertIn("predicate rule", delta_prompt)
        self.assertLessEqual(request_prompt_and_budget(init_request)[1], MAX_INPUT_BUDGET_UNITS)


if __name__ == "__main__":
    unittest.main()


class BatchSizeTests(unittest.TestCase):
    def test_each_ordinary_chapter_gets_its_own_candidate_allowance(self):
        # Two 1,500-character chapters fit one request's budget, but packed together the first
        # chapter's facts crowded out the second's within the per-batch cap.
        sources = [chapter(1, 70), chapter(2, 70)]
        self.assertTrue(all(1400 < len(source["body"]) < 2000 for source in sources))
        init_batches = MemoryInitializationEngine(EchoProvider())._batches({"source_revision": 1, "sources": sources})
        self.assertEqual([len(batch["sources"]) for batch in init_batches], [1, 1])
        delta_batches = MemoryDeltaEngine(EchoProvider())._batches({"source_revision": 2, "sources": sources, "memory": []})
        self.assertEqual([len(batch["sources"]) for batch in delta_batches], [1, 1])
        short = [chapter(1, 20), chapter(2, 20)]  # two short chapters still share one request
        self.assertEqual(len(MemoryInitializationEngine(EchoProvider())._batches({"source_revision": 1, "sources": short})), 1)
