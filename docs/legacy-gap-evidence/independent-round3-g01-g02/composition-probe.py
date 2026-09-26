"""Bounded copy/citation combinations; no provider execution."""
import copy
import hashlib
import json
import pathlib

here = pathlib.Path(__file__).parent
namespace = {"__file__": str(here / "coverage-semantics-probe.py")}
prefix = (here / "coverage-semantics-probe.py").read_text(encoding="utf-8").split("\nengine = WritingAnalysisEngine")[0]
exec(compile(prefix, str(here / "coverage-semantics-probe.py"), "exec"), namespace)
data = namespace["data"]
engine = namespace["WritingAnalysisEngine"](namespace["NeverCalledProvider"]())
claims = data["layers"]["written"]["draft_claims"]


def validate_case(name, bound_data, text, ids):
    sources = [{"source_type": "draft_claim", "source_id": value} for value in ids]
    payload = {"summary": text, "summary_sources": sources[:3], "items": [{"section": "recent_source", "text": text, "sources": sources}]}
    result = engine.validate(copy.deepcopy(payload), copy.deepcopy(bound_data))
    return {"name": name, "input": bound_data, "provider_payload": payload, "result": result, "original_item_retained": any(item["text"] == text for item in result["items"])}


joined = "草稿写明：" + claims[0]["text"] + claims[1]["text"]
cases = [
    validate_case("two_copied_claims_cite_third_only", data, joined, [claims[2]["id"]]),
    validate_case("two_copied_claims_have_both_matching_sources", data, joined, [claims[0]["id"], claims[1]["id"]]),
]
duplicate_data = copy.deepcopy(data)
duplicate_claims = [{"id": "duplicate-1", "ordinal": 1, "text": "林默走进北门。"}, {"id": "duplicate-2", "ordinal": 2, "text": "林默走进北门。"}]
duplicate_data["layers"]["written"]["draft_claims"] = duplicate_claims
duplicate_data["layers"]["written"]["draft"]["excerpt"] = "".join(item["text"] for item in duplicate_claims)
duplicate_data["retrieval"]["selected_ids"]["draft_claim"] = [item["id"] for item in duplicate_claims]
duplicate_data["retrieval"]["counts"]["draft_claim"] = {"available": 2, "selected": 2}
cases.append(validate_case("identical_text_two_ids_one_matching_id", duplicate_data, "草稿写明：林默走进北门。", ["duplicate-2"]))
cases.append(validate_case("normal_paraphrase_is_not_claimed_verified", data, "林默从北门进入。", [claims[0]["id"]]))

assert not cases[0]["original_item_retained"]
assert cases[0]["result"]["draft_coverage"]["discarded_item_indices"] == [0]
assert "draft_item_citation_mismatch" in cases[0]["result"]["draft_coverage"]["reasons"]
assert cases[1]["original_item_retained"]
assert cases[1]["result"]["draft_coverage"]["discarded_item_indices"] == []
assert cases[2]["original_item_retained"]
assert cases[2]["result"]["draft_coverage"]["discarded_item_indices"] == []
assert cases[3]["original_item_retained"]
assert cases[3]["result"]["draft_coverage"]["discarded_item_indices"] == []

result = {"scope": "direct-copy mismatches, composed copies, duplicate-text ID and one retained paraphrase only; no generic paraphrase semantic proof", "engine_sha256": hashlib.sha256((here.parents[2] / "backend" / "app" / "engine.py").read_bytes()).hexdigest(), "cases": cases}
output = here / "composition-results.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"output": str(output), "assertions_passed": 9, "cases": [{"name": case["name"], "original_retained": case["original_item_retained"], "coverage": case["result"]["draft_coverage"]} for case in cases]}, ensure_ascii=False, indent=2))
