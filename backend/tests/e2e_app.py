"""Test-only ASGI app for browser E2E. Never imported by production startup."""

from pathlib import Path
import os
import tempfile
import threading
import uuid

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
        if request.get("task") == "context_brief":
            written=request["layers"]["written"]
            if "E2E_ANALYSIS_FAILURE" in written["draft"]["excerpt"]:raise ProviderInvalidJson()
            fail_key=f"context_brief:{written['draft']['id']}:{written['draft']['revision']}"
            if "E2E_ANALYSIS_FAIL_ONCE" in written["draft"]["excerpt"] and fail_key not in self.failed_once:
                self.failed_once.add(fail_key);raise ProviderInvalidJson()
            planned=request["layers"]["planned"]["story_plans"]
            memory=request["layers"]["confirmed"]["memory_records"]
            spans=written["source_spans"]
            source={"source_type":"author_context","source_id":planned[0]["id"]} if planned else {"source_type":"memory_record","source_id":memory[0]["id"]} if memory else {"source_type":"source_span","source_id":spans[0]["id"]}
            section="related_plan" if planned else "confirmed_fact" if memory else "recent_source"
            return ProviderResult({"summary":"写作前先守住返航目标、角色当前状态与雾港规则。","summary_sources":[source],"items":[{"section":section,"text":"本章应继续处理返航动作，并避免把创作计划误写成既成事实。","sources":[source]}]},input_tokens=40,output_tokens=18,latency_ms=25)
        if request.get("task") == "plan_alignment":
            written=request["layers"]["written"]
            if "E2E_ANALYSIS_FAILURE" in written["draft"]["excerpt"]:raise ProviderInvalidJson()
            fail_key=f"plan_alignment:{written['draft']['id']}:{written['draft']['revision']}"
            if "E2E_ANALYSIS_FAIL_ONCE" in written["draft"]["excerpt"] and fail_key not in self.failed_once:
                self.failed_once.add(fail_key);raise ProviderInvalidJson()
            claims=written["draft_claims"]
            return ProviderResult({"summary":"已按创作计划逐项对照保存草稿。","items":[{"story_plan_id":plan["id"],"status":"planned_missing" if "E2E_PLAN_MISSING" in plan["title"] else "planned_covered","explanation":"当前草稿已写出计划动作。" if "E2E_PLAN_MISSING" not in plan["title"] else "当前草稿尚未写出这一计划动作。","evidence":[] if "E2E_PLAN_MISSING" in plan["title"] else [{"source_type":"draft_claim","source_id":claims[0]["id"]}]} for plan in request["layers"]["planned"]["story_plans"]]},input_tokens=44,output_tokens=20,latency_ms=25)
        if request.get("task") == "change_impact":
            proposal=request["proposal"]
            if "E2E_CHANGE_IMPACT_BLOCK" in proposal["proposed_change"]:
                self.entered.set()
                if not self.release.wait(20):raise ProviderTimeout()
            characters=request["layers"]["identity"]["characters"]
            character=next((item for item in characters if item["id"]==proposal.get("target_id")),characters[0])
            aliases=[item for item in request["layers"]["identity"]["aliases"] if item["character_id"]==character["id"]]
            evidence=[{"source_type":"character_record","source_id":character["id"]}]+([{"source_type":"character_alias","source_id":aliases[0]["id"]}] if aliases else [])
            return ProviderResult({"summary":"该修改会影响角色身份识别与相关资料核对。","items":[{"area":"character","target_id":character["id"],"impact":"需要复核这个角色在既有章节、Memory 与计划中的身份指向。","evidence":evidence}]},input_tokens=38,output_tokens=18,latency_ms=25)
        if request.get("task") == "story_qa":
            question=request["question"]
            fail_key=f"story_qa:{request['bindings']['draft_id']}:{request['bindings']['draft_revision']}"
            if "E2E_QA_FAIL_ONCE" in question and fail_key not in self.failed_once:
                self.failed_once.add(fail_key);raise ProviderInvalidJson()
            memory=request["layers"]["confirmed"]["memory_records"]
            if not memory:return ProviderResult({"answer_status":"insufficient","answer":"没有证据。","findings":[]},input_tokens=12,output_tokens=4,latency_ms=20)
            source={"source_type":"memory_record","source_id":memory[0]["id"]}
            return ProviderResult({"answer_status":"answered","answer":"根据当前 Story Memory，这个问题已有可核对的答案。","findings":[{"layer":"confirmed","stance":"supports","text":"回答只采用作者已确认的事实。","evidence":[source]}]},input_tokens=30,output_tokens=14,latency_ms=25)
        if request.get("task") == "foreshadow_scan":
            written=request["layers"]["written"]
            if "E2E_FORESHADOW_BLOCK" in written["draft"]["excerpt"]:
                self.entered.set()
                if not self.release.wait(20):raise ProviderTimeout()
            spans=written["source_spans"]
            if not spans:return ProviderResult({"summary":"没有可采信候选。","candidates":[]},input_tokens=10,output_tokens=3,latency_ms=20)
            source=spans[0]
            return ProviderResult({"summary":"发现两条需要作者逐条判断的伏笔候选。","candidates":[
                {"title":"潮汐表的缺口","description":"已写正文中的缺口可能需要后续回收。","suggested_status":"planted","evidence":[{"source_type":"source_span","source_id":source["id"],"relation":"planted"}]},
                {"title":"北门雾钟","description":"雾钟作为重复意象仍在发展。","suggested_status":"developing","evidence":[{"source_type":"source_span","source_id":source["id"],"relation":"developing"}]},
            ]},input_tokens=34,output_tokens=18,latency_ms=25)
        if request.get("task") == "revision_plan":
            issues=request["selected_issues"]
            return ProviderResult({"summary":"已把作者选择的问题整理为可审阅修订建议。","candidates":[{
                "issue_id":issue["id"],
                "title":f"修订：{issue['claim_text'][:32]}",
                "instruction":"回到当前草稿手动核对这处叙述，并依据已写来源完成修改。",
                "priority":"high" if issue["severity"]=="high" else "medium" if issue["severity"]=="medium" else "low",
                "evidence":[{"source_type":"issue_evidence","source_id":issue["evidence"][0]["id"]}],
            } for issue in issues]},input_tokens=42,output_tokens=22,latency_ms=25)
        if request.get("task") == "memory_initialization":
            sources = request["sources"]
            return ProviderResult(
                {
                    "candidates": [
                        {"memory_type": "static_canon", "subject": "雾港钟声", "predicate": "harbor_rule", "value": "钟声响起后船只停泊", "chapter_id": sources[0]["chapter_id"], "source_span_id": sources[0]["id"]},
                        {"memory_type": "dynamic_state", "subject": "银钥匙", "predicate": "holder", "value": "林默保管", "chapter_id": sources[1]["chapter_id"], "source_span_id": sources[1]["id"]},
                        {"memory_type": "character_knowledge", "subject": "林默", "predicate": "knowledge", "value": "北堤门只在清晨开启", "chapter_id": sources[2]["chapter_id"], "source_span_id": sources[2]["id"]},
                        *([{"memory_type": "open_thread", "subject": "废弃船票", "predicate": "status", "value": "仍有效", "chapter_id": sources[0]["chapter_id"], "source_span_id": sources[0]["id"]}] if any("E2E_FACT_LIFECYCLE" in item["body"] for item in sources) else []),
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
            affected = next(item for item in request["memory"] if item["subject"] == "林默" and item["predicate"] == "knowledge")
            retired = next((item for item in request["memory"] if item["subject"] == "废弃船票"), None)
            candidates = [
                {"change_kind":"changed_fact","affected_memory_id":affected["id"],"memory_type":"character_knowledge","subject":"林默","predicate":"knowledge","value":possession,"invalidation_reason":None,"chapter_id":source["chapter_id"],"source_span_id":source["id"]},
                {"change_kind":"new_fact","affected_memory_id":None,"memory_type":"open_thread","subject":"北堤门","predicate":"status","value":"开启时间待确认","invalidation_reason":None,"chapter_id":source["chapter_id"],"source_span_id":source["id"]},
            ]
            if retired:
                candidates.insert(1, {"change_kind":"invalidated_fact","affected_memory_id":retired["id"],"memory_type":retired["memory_type"],"subject":retired["subject"],"predicate":retired["predicate"],"value":retired["value"],"invalidation_reason":"新章节明确这张船票不再有效","chapter_id":source["chapter_id"],"source_span_id":source["id"]})
            return ProviderResult(
                {"candidates": candidates}, input_tokens=72, output_tokens=32, cost_cny=0.001, latency_ms=30,
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
allowed_prefixes = (
    "story-stage12-v2-impl-",
    "story-stage12-v2-pm3-",
    "story-v130-rc-",
)
if (
    system_temp not in TEST_ROOT.parents
    or not TEST_ROOT.name.startswith(allowed_prefixes)
    or "story-continuity-web-demo" in str(TEST_ROOT).casefold()
):
    raise RuntimeError(
        "E2E_TEST_ROOT must be an approved isolated browser-test system-temp directory"
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


@app.post("/api/test/v130/projects/{project_id}/characters")
def add_v130_test_character(project_id: str):
    character_id=f"char-{uuid.uuid4()}"
    with app.state.database.connection() as connection:
        connection.execute(
            "INSERT INTO v2_characters VALUES(?,?,?,?,?,?,?,?,?,?)",
            (character_id,project_id,"顾潮","supporting","港务调查员","核对船籍","等待访谈","不知道温岚的旧称","[]","[]"),
        )
    return {"id":character_id,"name":"顾潮"}


@app.post("/api/test/stage12/projects/{project_id}/runs/{run_id}/fail-nonretryable")
def fail_stage12_run_nonretryable(project_id: str, run_id: str):
    changed = app.state.database.finish_run(
        project_id,
        run_id,
        {"status": "failed", "error_code": "schema_invalid", "retryable": False},
    )
    return {"changed": changed, "run_id": run_id, "retryable": False}
