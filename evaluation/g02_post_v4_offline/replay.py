"""Replay saved V4 model JSON through the later G02 validator; no Provider calls."""
from __future__ import annotations

import json
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
from app.engine import WritingAnalysisEngine

V4 = ROOT / "evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases"


def replay() -> dict:
    rows = []
    for filename in ("02-g02-long-sentence.json", "05-g02-time-bound.json"):
        saved = json.loads((V4 / filename).read_text(encoding="utf-8"))
        request = saved["business_requests"][0]["business_request"]
        raw = saved["model_outputs"][0]["business_json"]
        result = WritingAnalysisEngine(object()).validate(raw, request)
        draft_claims = request["layers"]["written"]["draft_claims"]
        rendered = {source["source_id"] for item in result["items"] for source in item["sources"]
                    if source["source_type"] == "draft_claim"}
        if saved["case_id"] == "g02-time-bound":
            assert len(draft_claims) == 2 and {x["id"] for x in draft_claims} <= rendered
            assert "今日她读完陈澈的信" in result["summary"]
        else:
            tail = "最后把银钥匙交给陈澈并得知弟弟还活着"
            assert tail in result["items"][0]["text"]
            assert tail in result["items"][0]["sources"][0]["excerpt"]
        rows.append({"case_id": saved["case_id"], "source_v4_case_sha256": hashlib.sha256(
                         (V4 / filename).read_bytes()).hexdigest(),
                     "selected_claim_count": len(draft_claims), "rendered_claim_count": len(rendered),
                     "final_summary": result["summary"], "final_summary_source_count": len(result["summary_sources"]),
                     "coverage": result["draft_coverage"], "transform": result["citation_transform"]})
    return {"schema_version": "g02-post-v4-offline-replay", "provider_calls": 0,
            "engine_sha256": hashlib.sha256((ROOT / "backend/app/engine.py").read_bytes()).hexdigest(),
            "brief_citations_sha256": hashlib.sha256((ROOT / "backend/app/brief_citations.py").read_bytes()).hexdigest(),
            "rows": rows}


if __name__ == "__main__":
    result = replay()
    target = HERE / "results-v2.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"cases": len(result["rows"]), "provider_calls": 0}, ensure_ascii=False))
