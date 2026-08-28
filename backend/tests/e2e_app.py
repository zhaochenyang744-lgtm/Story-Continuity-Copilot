"""Test-only ASGI app for browser E2E. Never imported by production startup."""

from pathlib import Path
import os
import tempfile

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult


class BrowserTestProvider:
    label = "browser-e2e-test-provider"

    @property
    def available(self):
        return True

    def evaluate(self, request):
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
if _configured_root:
    TEST_ROOT = Path(_configured_root).resolve()
    system_temp = Path(tempfile.gettempdir()).resolve()
    if system_temp not in TEST_ROOT.parents or "story-continuity-web-demo" in str(TEST_ROOT).casefold():
        raise RuntimeError("E2E_TEST_ROOT must be a system-temp directory outside the Web Demo")
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
else:
    TEST_ROOT = Path(tempfile.mkdtemp(prefix="scc-stage5-e2e-"))
TEST_PATHS = AppPaths.from_project_root(
    TEST_ROOT,
    protected_poc_root=TEST_ROOT / "protected-poc-placeholder",
)
app = create_app(paths=TEST_PATHS, provider=BrowserTestProvider())
