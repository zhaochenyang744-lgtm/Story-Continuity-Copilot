"""Narrow round-two positive controls and scope/citation checks."""
import copy
import hashlib
import json
import pathlib

here = pathlib.Path(__file__).parent
namespace = {"__file__": str(here / "probe.py")}
prefix = (here / "probe.py").read_text(encoding="utf-8").split("\nresults = ")[0]
exec(compile(prefix, str(here / "probe.py"), "exec"), namespace)
temporal_case = namespace["temporal_case"]

temporal = [
    temporal_case("positive_same_relative_day", "今日十八点，秦渡已经知道信使身份。", "今日十八点，秦渡还不知道信使身份。", "十八点", "十八点"),
    temporal_case("positive_same_calendar_date", "九月二十五日十八点，秦渡已经知道信使身份。", "九月二十五日十八点，秦渡还不知道信使身份。", "十八点", "十八点"),
    temporal_case("positive_same_ordinal_day", "第十一天十八点，秦渡已经知道信使身份。", "第十一天十八点，秦渡还不知道信使身份。", "十八点", "十八点"),
    temporal_case("compatible_same_day_two_clock_transition", "今日十九点，秦渡已经知道信使身份。", "今日十八点，秦渡还不知道信使身份，直到十九点才从密信获知身份。", "十九点", "十九点"),
    temporal_case("positive_conflict_unrelated_recollection_in_source", "今日十八点，秦渡已经知道信使身份。", "今日十八点，秦渡还不知道信使身份。另一间屋内，陈澈回忆童年的航海经历。", "十八点", "十八点"),
]

scope_namespace = {"__file__": str(here / "coverage-semantics-probe.py")}
scope_prefix = (here / "coverage-semantics-probe.py").read_text(encoding="utf-8").split("\nengine = WritingAnalysisEngine")[0]
exec(compile(scope_prefix, str(here / "coverage-semantics-probe.py"), "exec"), scope_namespace)
data = copy.deepcopy(scope_namespace["data"])
claims = data["layers"]["written"]["draft_claims"]
engine = scope_namespace["WritingAnalysisEngine"](scope_namespace["NeverCalledProvider"]())

briefs = []
for name, source_indices in [
    ("positive_every_item_correctly_cited", [0, 1, 2]),
    ("all_ids_cited_but_each_item_uses_wrong_source", [1, 2, 0]),
]:
    items = [{"section": "recent_source", "text": claim["text"], "sources": [{"source_type": "draft_claim", "source_id": claims[source_indices[index]]["id"]}]} for index, claim in enumerate(claims)]
    payload = {"summary": "".join(claim["text"] for claim in claims), "summary_sources": [item["sources"][0] for item in items], "items": items}
    result = engine.validate(payload, copy.deepcopy(data))
    briefs.append({"case": name, "input": data, "payload": payload, "result": result, "all_item_texts_equal_their_own_source_excerpt": all(item["text"] == item["sources"][0]["excerpt"] for item in result["items"])})

engine_path = here.parents[2] / "backend" / "app" / "engine.py"
result = {"engine_sha256": hashlib.sha256(engine_path.read_bytes()).hexdigest(), "g01": temporal, "g02": briefs, "scope": "offline fake provider / validation only; original evidence untouched"}
output = here / "controls-and-scope-results.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"output": str(output), "g01": [{"case": case["name"], "validation": case["validation"]["accepted"], "nature": [issue["nature"] for issue in case["execute"].get("issues", [])], "fake_calls": case["fake_calls"]} for case in temporal], "g02": [{"case": case["case"], "coverage": case["result"]["draft_coverage"], "evidence_status": case["result"]["evidence_status"], "each_item_matches_own_excerpt": case["all_item_texts_equal_their_own_source_excerpt"]} for case in briefs]}, ensure_ascii=False, indent=2))
