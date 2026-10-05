"""Isolated controller browser responses; production engine and persistence remain real."""
import os
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
from tests import e2e_app as base
from app.provider import ProviderResult

original = base.BrowserTestProvider.evaluate
calls = []
def evaluate(self, request):
    written = request.get("layers", {}).get("written", {})
    body = written.get("draft", {}).get("excerpt", "")
    if request.get("task") != "context_brief" or "CTRL_G02_" not in body:
        return original(self, request)
    self.calls += 1
    claims = written["draft_claims"]
    cycle = "CTRL_G02_CYCLE" in body
    items = [{"section": "recent_source", "text": c["text"], "sources": [{"source_type": "draft_claim", "source_id": claims[(i + 1) % len(claims) if cycle else i]["id"]}]} for i, c in enumerate(claims)]
    if "CTRL_G02_DIALOGUE" in body:
        items[0]["text"] = "林默已经知道密码。"
    if "CTRL_G02_TIME" in body:
        items = []
        for m in request["layers"]["confirmed"]["memory_records"]:
            items.append({"section":"confirmed_fact", "text":m["subject"] + m["value"], "sources":[{"source_type":"memory_record", "source_id":m["id"]}]})
        for s in written["source_spans"]:
            items.append({"section":"recent_source", "text":s["body"][:600], "sources":[{"source_type":"source_span", "source_id":s["id"]}]})
        items = items[:12]
    payload = {"summary": "模型编造：所有秘密已经公开。", "summary_sources": items[0]["sources"], "items": items}
    calls.append({"project_id": request["bindings"]["project_id"], "request": request, "response": payload})
    return ProviderResult(payload, input_tokens=4, output_tokens=3, latency_ms=1)
base.BrowserTestProvider.evaluate = evaluate
app = base.app
@app.get("/api/test/g02-controller/calls")
def observations():
    return {"calls": calls, "provider_http_calls": 0}
