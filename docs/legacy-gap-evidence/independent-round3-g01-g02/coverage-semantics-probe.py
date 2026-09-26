"""Two bounded G02 probes: all short draft claims selected, no truncation."""
import copy
import hashlib
import json
import pathlib

from app.engine import WritingAnalysisEngine


class NeverCalledProvider:
    available = True
    label = "independent-coverage-validation"

    def evaluate(self, request):
        raise AssertionError("No provider execution is allowed in this probe")


sentences = ["林默走进北门。", "银钥匙已经交给陈澈。", "她此时已经知道弟弟还活着。"]
claims = [{"id": f"draft-claim-short-r2-{index}", "ordinal": index, "text": text} for index, text in enumerate(sentences, 1)]
historical = "渡口昨夜已经封锁。"
data = {
    "task": "context_brief",
    "bindings": {"project_id": "independent-coverage", "draft_id": "short", "draft_revision": 2, "source_revision": 1},
    "layers": {
        "planned": {"story_plans": [], "character_plans": [], "world_plans": []},
        "confirmed": {"memory_records": []},
        "written": {"draft": {"id": "short", "revision": 2, "excerpt": "".join(sentences)}, "draft_claims": claims, "source_spans": [{"id": "span-1", "chapter_id": "chapter-1", "chapter_number": 1, "chapter_title": "封锁", "label": "历史正文", "body": historical}]},
    },
    "retrieval": {
        "selected_ids": {"author_context": [], "memory_record": [], "source_span": ["span-1"], "draft_claim": [item["id"] for item in claims]},
        "counts": {"author_context": {"available": 0, "selected": 0}, "memory_record": {"available": 0, "selected": 0}, "source_span": {"available": 1, "selected": 1}, "draft_claim": {"available": 3, "selected": 3}},
        "truncated": {"author_context": False, "memory_record": False, "source_span": False, "draft_body": False, "draft_claim": False},
    },
}
engine = WritingAnalysisEngine(NeverCalledProvider())
cases = []
for name, text, source in [
    ("historical_only_triggers_first_claim_fallback", historical, {"source_type": "source_span", "source_id": "span-1"}),
    ("provider_cites_only_first_claim", sentences[0], {"source_type": "draft_claim", "source_id": claims[0]["id"]}),
]:
    payload = {"summary": text, "summary_sources": [source], "items": [{"section": "recent_source", "text": text, "sources": [source]}]}
    output = engine.validate(copy.deepcopy(payload), copy.deepcopy(data))
    texts = [output["summary"], *[item["text"] for item in output["items"]]]
    cited_ids = sorted({source["source_id"] for item in output["items"] for source in item["sources"] if source["source_type"] == "draft_claim"})
    cases.append({"case": name, "provider_payload": payload, "output": output, "all_input_draft_claim_ids": [item["id"] for item in claims], "output_draft_claim_ids": cited_ids, "omitted_draft_claim_ids": [item["id"] for item in claims if item["id"] not in cited_ids], "sentence_2_absent_from_output_text": all(sentences[1] not in value for value in texts), "sentence_3_absent_from_output_text": all(sentences[2] not in value for value in texts)})

here = pathlib.Path(__file__).parent
engine_path = here.parents[2] / "backend" / "app" / "engine.py"
result = {"probe": "coverage semantics only; no truncation and no provider execution", "engine_sha256": hashlib.sha256(engine_path.read_bytes()).hexdigest(), "input": data, "draft_length": len("".join(sentences)), "cases": cases}
output_path = here / "coverage-semantics-results.json"
output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"output": str(output_path), "draft_length": result["draft_length"], "all_truncation_flags_false": not any(data["retrieval"]["truncated"].values()), "cases": [{"name": item["case"], "coverage": item["output"]["draft_coverage"], "evidence_status": item["output"]["evidence_status"], "omitted_ids": item["omitted_draft_claim_ids"], "second_absent": item["sentence_2_absent_from_output_text"], "third_absent": item["sentence_3_absent_from_output_text"]} for item in cases]}, ensure_ascii=False, indent=2))
