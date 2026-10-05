"""Checks the exact same-run API business input before any model dispatch."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib

from evaluation.current_flash_v5.journal import digest

ROOT = pathlib.Path(__file__).resolve().parents[2]
V2 = ROOT / "evaluation/current_contract_compare_v2"
V3 = ROOT / "evaluation/current_contract_compare_v3"


def _fail(reason: str, case_id: str) -> None:
    raise RuntimeError("input_contract:" + case_id + ":" + reason)


def _same_capture(actual: dict, captured: dict) -> bool:
    current, old = copy.deepcopy(actual), copy.deepcopy(captured)
    current.pop("contract_repair", None)
    if len(current.get("claims", [])) != len(old.get("claims", [])):
        return False
    for a, b in zip(current["claims"], old["claims"]):
        a["id"] = b["id"]
    return current == old


class InputContract:
    def __init__(self):
        self.gold = {x["case_id"]: x for x in json.loads((V3 / "cases.json").read_text(encoding="utf-8"))["cases"]}
        self.capture = {x["case_id"]: x["business_request"] for x in json.loads(
            (V2 / "actual-inputs.json").read_text(encoding="utf-8"))["rows"]}
        self.corpora = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (V2 / "corpora").glob("*.json")}
        self.runtime: dict[str, dict] = {}

    def bind_runtime(self, case_id: str, snapshot: dict) -> None:
        self.runtime[case_id] = snapshot

    def runtime_binding(self, case: dict, request: dict) -> dict:
        case_id = case["case_id"]
        bound = self.runtime.get(case_id)
        if not bound:
            _fail("runtime_binding_not_saved", case_id)
        if bound["draft_body"] != case["saved_draft"]:
            _fail("saved_draft_body_database_mismatch", case_id)
        if case["family"] == "g02":
            bindings = request.get("bindings", {})
            written = request.get("layers", {}).get("written", {})
            draft = written.get("draft", {})
            if (bindings.get("project_id") != bound["project_id"] or bindings.get("draft_id") != bound["draft_id"] or
                bindings.get("draft_revision") != bound["draft_revision"] or
                bindings.get("source_revision") != bound["source_revision"] or
                bindings.get("memory_version") != bound["memory_version"] or
                draft.get("id") != bound["draft_id"] or draft.get("revision") != bound["draft_revision"] or
                draft.get("excerpt") != bound["draft_body"][:len(draft.get("excerpt", ""))]):
                _fail("saved_draft_or_version_database_binding", case_id)
            selected_spans = written.get("source_spans", [])
            selected_memory = request.get("layers", {}).get("confirmed", {}).get("memory_records", [])
        else:
            if request.get("draft", {}).get("body") != bound["draft_body"]:
                _fail("saved_draft_database_binding", case_id)
            selected_spans = [x for claim in request.get("claims", []) for x in claim.get("allowed_evidence", [])]
            selected_memory = request.get("memory", [])
        actual_spans = {x["span_id"]: x for x in bound["chapters"]}
        actual_memory = {x["id"]: x for x in bound["memory"]}
        for span in selected_spans:
            source = actual_spans.get(span.get("id"))
            if (not source or span.get("chapter_id") != source["chapter_id"] or
                span.get("body") != source["span_body"] or
                ("chapter_number" in span and span["chapter_number"] != source["chapter_number"]) or
                ("chapter_title" in span and span["chapter_title"] != source["chapter_title"]) or
                ("source_revision" in span and span["source_revision"] != source["span_revision"]) or
                source["chapter_revision"] != bound["source_revision"] or
                source["span_revision"] != bound["source_revision"]):
                _fail("selected_source_database_chapter_body_revision", case_id)
        for row in selected_memory:
            recorded = actual_memory.get(row.get("id"))
            if (not recorded or any(row.get(field) != recorded[field] for field in
                ("memory_type", "subject", "predicate", "value", "source_span_id")) or
                recorded["source_span_id"] not in actual_spans or recorded["version"] != bound["memory_version"]):
                _fail("selected_memory_database_source_binding", case_id)
        return {"database_binding": "matched_persisted_isolated_database",
                "database_selected_source_count": len(selected_spans),
                "database_selected_memory_count": len(selected_memory),
                "database_unselected_memory_sources_allowed": sum(x["source_span_id"] not in
                    {span["id"] for span in selected_spans} for x in selected_memory)}

    def __call__(self, case: dict, request: dict) -> dict:
        binding = self.runtime_binding(case, request)
        audit = self.comparison(case, request) if case["family"] == "comparison" else self.g02(case, request)
        return {**audit, **binding}

    def comparison(self, case: dict, request: dict) -> dict:
        case_id = case["case_id"]
        gold = self.gold[case_id]
        if request.get("draft", {}).get("body") != case["saved_draft"] or len(request.get("claims", [])) != 1:
            _fail("draft_or_claim_count", case_id)
        if request["claims"][0].get("text") != case["saved_draft"]:
            _fail("target_claim_text", case_id)
        old_id = gold["lineage"]["v2_case_id"]
        if not _same_capture(request, self.capture[old_id]):
            _fail("historical_capture_content_drift", case_id)
        selected = {x["id"]: x for x in request["claims"][0]["allowed_evidence"]}
        minimum = [{f"fixture-span-{case['corpus_key']}-{x['chapter_number']}" for x in group}
                   for group in gold["minimum_sufficient_evidence_sets"]]
        if not any(group <= set(selected) for group in minimum):
            _fail("minimum_source_not_selected", case_id)
        chapters = {x["chapter_number"]: x for x in self.corpora[case["corpus_key"]]["chapters"]}
        for span_id, span in selected.items():
            try:
                number = int(span_id.rsplit("-", 1)[1])
                chapter = chapters[number]
            except (ValueError, KeyError, IndexError):
                _fail("selected_source_not_in_corpus", case_id)
            if (span.get("chapter_id") != f"fixture-chapter-{case['corpus_key']}-{number}" or
                span.get("body") != chapter["body"] or span.get("prompt_excerpt") != chapter["body"] or
                span.get("label") != chapter["source_label"]):
                _fail("selected_source_body_or_chapter_drift", case_id)
        memories = {x["id"]: x for x in request.get("memory", [])}
        for row in memories.values():
            source = row.get("source_span_id")
            if source not in {f"fixture-span-{case['corpus_key']}-{n}" for n in chapters}:
                _fail("memory_source_not_in_corpus", case_id)
            number = int(source.rsplit("-", 1)[1])
            if row.get("value") != chapters[number]["body"]:
                _fail("memory_value_source_drift", case_id)
        return {"case_id": case_id, "family": "comparison", "status": "exact_content_after_claim_id_normalization",
                "historical_capture_sha256": hashlib.sha256((V2 / "actual-inputs.json").read_bytes()).hexdigest(),
                "same_run_request_sha256": digest(request), "selected_source_count": len(selected),
                "selected_memory_count": len(memories), "minimum_source_selected": True,
                "repair": bool(request.get("contract_repair"))}

    def g02(self, case: dict, request: dict) -> dict:
        case_id = case["case_id"]
        if request.get("task") != "context_brief":
            _fail("task", case_id)
        bindings = request.get("bindings", {})
        written = request.get("layers", {}).get("written", {})
        draft = written.get("draft", {})
        claims = written.get("draft_claims", [])
        spans = written.get("source_spans", [])
        memories = request.get("layers", {}).get("confirmed", {}).get("memory_records", [])
        if (bindings.get("draft_id") != draft.get("id") or bindings.get("draft_revision") != draft.get("revision") or
            not isinstance(claims, list) or not claims or len({x.get("id") for x in claims}) != len(claims)):
            _fail("draft_binding_or_claim_identity", case_id)
        if (len({x.get("id") for x in spans}) != len(spans) or
            any(x.get("source_revision") != bindings.get("source_revision") for x in spans)):
            _fail("source_identity_or_revision", case_id)
        selected_ids = request.get("retrieval", {}).get("selected_ids", {})
        if ([x["id"] for x in claims] != selected_ids.get("draft_claim") or
            [x["id"] for x in spans] != selected_ids.get("source_span") or
            [x["id"] for x in memories] != selected_ids.get("memory_record")):
            _fail("retrieval_selected_id_binding", case_id)
        body = case["saved_draft"]
        scope = request.get("retrieval", {}).get("draft_claim_scope", {})
        selected_ranges = scope.get("selected", [])
        if scope.get("body_chars") != len(body) or len(selected_ranges) != len(claims):
            _fail("draft_scope", case_id)
        for claim, selected in zip(claims, selected_ranges):
            if claim["id"] != selected.get("id") or claim["text"] != body[selected["source_start"]:selected["source_end"]]:
                _fail("claim_text_range", case_id)
        source_by_id = {x["id"]: x for x in spans}
        linked = sum(x.get("source_span_id") in source_by_id for x in memories)
        unselected = len(memories) - linked
        if case_id == "g02-body-limit":
            counts = request["retrieval"]["counts"]["draft_claim"]
            if (len(body) != 1980 or body.count("林默在雾港核对潮汐表。") != 180 or
                counts != {"available": 180, "selected": 8} or
                any(x["text"] != "林默在雾港核对潮汐表。" for x in claims)):
                _fail("long_body_scope_180_8_172", case_id)
        elif case_id == "g02-identical-text":
            if len(claims) != 2 or claims[0]["text"] != claims[1]["text"] or claims[0]["id"] == claims[1]["id"]:
                _fail("duplicate_claim_identity", case_id)
        elif case_id == "g02-long-sentence":
            if len(body) != 299 or "最后把银钥匙交给陈澈并得知弟弟还活着" not in claims[0]["text"]:
                _fail("long_sentence_tail", case_id)
        elif case_id == "g02-time-bound":
            if len(claims) != 2 or "昨日" not in claims[0]["text"] or "今日" not in claims[1]["text"]:
                _fail("time_bound_claims", case_id)
        elif case_id == "g02-dialogue-attribution":
            if (len(claims) != 2 or not claims[0]["text"].startswith("陈澈说：‘") or
                not claims[1]["text"].startswith("温岚摇头说：‘") or
                any(not x["text"].endswith("。’") for x in claims)):
                _fail("two_complete_attributed_quotations", case_id)
        return {"case_id": case_id, "family": "g02", "status": "same_run_api_input_bound",
                "same_run_request_sha256": digest(request), "saved_draft_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "draft_chars": len(body), "claim_available": scope.get("available"), "claim_selected": len(claims),
                "claim_unselected": scope.get("available", 0) - len(claims),
                "selected_source_span_count": len(spans), "selected_memory_count": len(memories),
                "memory_source_selected_count": linked, "memory_source_unselected_count": unselected,
                "dialogue_two_complete_quotes": case_id == "g02-dialogue-attribution" and len(claims) == 2}
