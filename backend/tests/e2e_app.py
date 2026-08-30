"""Test-only ASGI app for browser E2E. Never imported by production startup."""

from pathlib import Path
import os
import tempfile
import threading

from app.config import AppPaths

# Importing app.main normally constructs the production ASGI app and therefore
# a production provider. The browser-test process must only construct the
# injected stub below.
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
from app.main import create_app
from app.provider import ProviderInvalidJson, ProviderResult, ProviderTimeout


class BrowserTestProvider:
    label = "browser-e2e-test-provider"

    def __init__(self):
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.failed_once = set()

    @property
    def available(self):
        return True

    def evaluate(self, request):
        self.calls += 1
        if request.get("task") == "memory_initialization":
            sources = request["sources"]
            return ProviderResult(
                {
                    "candidates": [
                        {"memory_type": "static_canon", "subject": "雾港钟声", "predicate": "harbor_rule", "value": "钟声响起后船只停泊", "chapter_id": sources[0]["chapter_id"], "source_span_id": sources[0]["id"]},
                        {"memory_type": "dynamic_state", "subject": "银钥匙", "predicate": "holder", "value": "林默保管", "chapter_id": sources[1]["chapter_id"], "source_span_id": sources[1]["id"]},
                        {"memory_type": "character_knowledge", "subject": "林默", "predicate": "knowledge", "value": "北堤门只在清晨开启", "chapter_id": sources[2]["chapter_id"], "source_span_id": sources[2]["id"]},
                    ]
                },
                input_tokens=96,
                output_tokens=40,
                cost_cny=0.002,
                latency_ms=40,
            )
        if request.get("task") == "memory_delta":
            source = request["sources"][0]
            possession = "守塔人保管银钥匙" if "第二轮" in source["body"] else "林默交给守塔人"
            return ProviderResult(
                {"candidates": [
                    {"memory_type":"dynamic_state","subject":"银钥匙","predicate":"possession","value":possession,"chapter_id":source["chapter_id"],"source_span_id":source["id"]},
                    {"memory_type":"open_thread","subject":"北堤门","predicate":"status","value":"开启时间待确认","chapter_id":source["chapter_id"],"source_span_id":source["id"]},
                ]}, input_tokens=72, output_tokens=32, cost_cny=0.001, latency_ms=30,
            )
        body = request["draft"]["body"]
        if "STAGE12_BLOCK" in body:
            self.entered.set()
            if not self.release.wait(20):
                raise ProviderTimeout()
        if "STAGE12_TIMEOUT" in body:
            raise ProviderTimeout()
        if "STAGE12_FAILURE" in body:
            raise ProviderInvalidJson()
        if "STAGE12_FAIL_ONCE" in body and request["draft"]["id"] not in self.failed_once:
            self.failed_once.add(request["draft"]["id"])
            raise ProviderInvalidJson()
        issues = []
        categories = ("object_state", "character_knowledge")
        limit = 20 if "EXTREME_ISSUES" in request["draft"]["body"] else 2
        memory_by_span = {item["source_span_id"]: item for item in request["memory"]}
        for index, claim in enumerate(request["claims"][:limit]):
            category = categories[index % len(categories)]
            evidence = next((item for item in claim["allowed_evidence"] if item["id"] in memory_by_span), None)
            memory = memory_by_span.get(evidence["id"]) if evidence else None
            if limit == 20 and index % 3 == 2:
                evidence, memory = None, None
            if not evidence or not memory:
                issues.append({"claim_span_id": claim["id"], "status": "insufficient_evidence", "category": category, "severity": "medium", "explanation": "可检索片段尚不足以支撑连续性结论，需要作者补充或确认来源。" * 4, "evidence": [], "proposed_memory_change": None})
                continue
            change = {
                "operation": "replace" if index else "add",
                "memory_type": memory["memory_type"] if index else "open_thread",
                "subject": memory["subject"] if index else "第十一章作者确认线索",
                "predicate": memory["predicate"] if index else "status",
                "value": "作者确认后的新状态" if index else "待后续章节推进",
            }
            if index:
                change["affected_memory_id"] = memory["id"]
            issues.append({
                "claim_span_id": claim["id"],
                "status": "conflict",
                "category": category,
                "severity": "high" if index % 3 == 0 else "medium",
                "explanation": ("当前草稿与作者已确认的历史事实存在需要审阅的差异。" * 8),
                "evidence": [{
                    "chapter_id": evidence["chapter_id"],
                    "span_id": evidence["id"],
                    "relation": "contradicts",
                    "sufficiency": "sufficient",
                    "related_memory_ids": [memory["id"]],
                }],
                "proposed_memory_change": change,
            })
        return ProviderResult(
            {"issues": issues},
            input_tokens=144,
            output_tokens=52,
            cost_cny=0.0042,
            latency_ms=80,
        )


_configured_root = os.environ.get("E2E_TEST_ROOT")
if not _configured_root:
    raise RuntimeError("E2E_TEST_ROOT is required for isolated browser tests")
TEST_ROOT = Path(_configured_root).resolve()
system_temp = Path(tempfile.gettempdir()).resolve()
allowed_prefixes = ("story-stage12-v2-impl-", "story-stage12-v2-pm3-")
if (
    system_temp not in TEST_ROOT.parents
    or not TEST_ROOT.name.startswith(allowed_prefixes)
    or "story-continuity-web-demo" in str(TEST_ROOT).casefold()
):
    raise RuntimeError(
        "E2E_TEST_ROOT must be an approved Stage 12 V2 system-temp directory"
    )
TEST_ROOT.mkdir(parents=True, exist_ok=True)
TEST_PATHS = AppPaths.from_project_root(
    TEST_ROOT,
    protected_poc_root=TEST_ROOT / "protected-poc-placeholder",
)
provider = BrowserTestProvider()
app = create_app(paths=TEST_PATHS, provider=provider)


@app.get("/api/test/stage12/release")
def release_stage12_provider():
    provider.release.set()
    return {"released": True, "provider_calls": provider.calls}


@app.get("/api/test/stage12/reset")
def reset_stage12_provider():
    provider.entered.clear()
    provider.release.clear()
    return {"reset": True, "provider_calls": provider.calls}


@app.get("/api/test/stage12/stats")
def stage12_provider_stats():
    return {
        "provider_mode": "injected_stub",
        "external_provider_http_enabled": False,
        "provider_calls": provider.calls,
        "provider_http_calls": 0,
        "blocked": provider.entered.is_set() and not provider.release.is_set(),
        "test_root": str(TEST_ROOT),
    }


@app.post("/api/test/stage12/projects/{project_id}/runs/{run_id}/fail-nonretryable")
def fail_stage12_run_nonretryable(project_id: str, run_id: str):
    changed = app.state.database.finish_run(
        project_id,
        run_id,
        {"status": "failed", "error_code": "schema_invalid", "retryable": False},
    )
    return {"changed": changed, "run_id": run_id, "retryable": False}
