"""Local G02 browser fixture; preserve the real engine, validator, API and DB."""
from pathlib import Path
import os
import tempfile

if os.environ.get("SCC_G02_ROUND3_BROWSER") != "1":
    raise RuntimeError("This wrapper requires explicit isolated G02 browser mode")
root = Path(os.environ.get("E2E_TEST_ROOT", "")).resolve()
if Path(tempfile.gettempdir()).resolve() not in root.parents or not root.name.startswith("story-v130-rc-g02-r3-"):
    raise RuntimeError("G02 wrapper requires a fresh approved system-temp root")
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"

from tests import e2e_app as base  # noqa: E402
from app.provider import ProviderResult  # noqa: E402

original_evaluate = base.BrowserTestProvider.evaluate
fixture_calls = []
markers = {"E2E_G02_R3_CYCLE": "cycle", "E2E_G02_R3_VALID": "valid"}


def evaluate(self, request):
    excerpt = request.get("layers", {}).get("written", {}).get("draft", {}).get("excerpt", "")
    found = [mode for marker, mode in markers.items() if marker in excerpt]
    if request.get("task") != "context_brief" or not found:
        return original_evaluate(self, request)
    if len(found) != 1:
        raise RuntimeError("G02 fixture marker must select one scenario")
    mode = found[0]
    claims = request["layers"]["written"]["draft_claims"]
    if len(claims) != 3:
        raise RuntimeError(f"G02 fixture requires exactly three real claims, received {len(claims)}")
    self.calls += 1
    items = []
    for index, claim in enumerate(claims):
        cited = claims[(index + 1) % 3] if mode == "cycle" else claim
        items.append({"section": "recent_source", "text": "G02R3模型分项：" + claim["text"],
                      "sources": [{"source_type": "draft_claim", "source_id": cited["id"]}]})
    payload = {"summary": "三条合成草稿分项。",
               "summary_sources": [{"source_type": "draft_claim", "source_id": claims[0]["id"]}],
               "items": items}
    fixture_calls.append({"mode": mode, "project_id": request["bindings"]["project_id"],
                          "claim_ids": [claim["id"] for claim in claims], "payload": payload})
    return ProviderResult(payload, input_tokens=70, output_tokens=40, latency_ms=1)


base.BrowserTestProvider.evaluate = evaluate
app = base.app


@app.get("/api/test/round3/brief-fixtures")
def inspect_brief_fixtures():
    return {"wrapper": "g02-round3-real-validator-v1", "test_root": str(root), "calls": fixture_calls}
