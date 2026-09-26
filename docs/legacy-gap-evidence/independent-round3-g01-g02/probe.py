"""Independent offline acceptance probes. No real network or original data."""
from __future__ import annotations

import copy
import json
import pathlib
import socket
import smtplib
import tempfile
import uuid

import httpx
from fastapi.testclient import TestClient
from app.config import AppPaths
from app.engine import ContinuityEngine, WritingAnalysisEngine
from app.main import create_app
from app.provider import ProviderResult
from app.stage13 import Stage13Settings


def deny_network(*args, **kwargs):
    raise AssertionError("External network disabled by independent probe")


original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def local_socketpair_connect(self, address):
    if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
        return original_connect(self, address)
    return deny_network()


def local_socketpair_connect_ex(self, address):
    if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
        return original_connect_ex(self, address)
    return deny_network()


socket.socket.connect = local_socketpair_connect
socket.socket.connect_ex = local_socketpair_connect_ex
httpx.HTTPTransport.handle_request = deny_network
smtplib.SMTP = deny_network
smtplib.SMTP_SSL = deny_network


class FakeProvider:
    available = True
    label = "independent-offline"
    model_label = "independent-fake"

    def __init__(self, payload=None):
        self.payload = payload
        self.requests = []

    def evaluate(self, request):
        self.requests.append(copy.deepcopy(request))
        if self.payload is not None:
            return ProviderResult(copy.deepcopy(self.payload), input_tokens=1, output_tokens=1)
        spans = request["layers"]["written"]["source_spans"]
        span = spans[0]
        source = {"source_type": "source_span", "source_id": span["id"]}
        return ProviderResult({"summary": "仅整理已引用的历史正文。", "summary_sources": [source], "items": [{"section": "recent_source", "text": span["body"][:200], "sources": [source]}]}, input_tokens=1, output_tokens=1)


def temporal_case(name, claim, evidence, claim_anchor=None, evidence_anchor=None):
    data = {"draft": {"id": "draft", "revision": 1, "body": claim}, "claims": [{"id": "claim-1", "text": claim, "allowed_evidence": [{"id": "span-1", "chapter_id": "chapter-1", "body": evidence, "prompt_excerpt": evidence}]}], "memory": []}
    payload = {"issues": [{"claim_span_id": "claim-1", "status": "conflict", "nature": "confirmed_conflict", "category": "character_knowledge", "severity": "high", "explanation": "这两处知情状态不能同时成立。", "reasoning": "认为两处对应同一时刻并形成确定冲突。", "temporal_basis": {"claim_anchor": claim_anchor or claim, "evidence_anchor": evidence_anchor or evidence, "relation": "explicit_overlap"}, "evidence": [{"chapter_id": "chapter-1", "span_id": "span-1", "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []}], "evidence_chain": [{"span_id": "span-1", "role": "prior_state"}], "suggested_revision": None, "available_actions": [], "proposed_memory_change": None}]}
    provider = FakeProvider(payload)
    engine = ContinuityEngine(provider)
    try:
        validation = {"accepted": True, "output": engine.validate(payload, data)}
    except ValueError as error:
        validation = {"accepted": False, "error": str(error)}
    result = engine.execute(data)
    return {"name": name, "claim": claim, "evidence": evidence, "anchors": payload["issues"][0]["temporal_basis"], "validation": validation, "execute": result, "fake_calls": len(provider.requests)}


def idem():
    return {"Idempotency-Key": str(uuid.uuid4())}


def api_brief_case(name, body):
    root = pathlib.Path(tempfile.mkdtemp(prefix="independent-g01-g02-"))
    provider = FakeProvider()
    app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=provider, executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
    with TestClient(app) as client:
        registered = client.post("/api/auth/register", headers=idem(), json={"account_name": "independent-reader", "display_name": "Independent", "password": "offline-safe-password-26", "recovery_email": "independent@example.test"})
        assert registered.status_code == 201, registered.text
        project_id = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        project = client.get(f"/api/projects/{project_id}").json()["data"]
        draft = project["current_draft"]
        saved = client.patch(f"/api/projects/{project_id}/drafts/{draft['id']}", headers=idem(), json={"base_revision": draft["revision"], "body": body})
        assert saved.status_code == 200, saved.text
        draft = client.get(f"/api/projects/{project_id}").json()["data"]["current_draft"]
        started = client.post(f"/api/projects/{project_id}/analyses", headers=idem(), json={"analysis_type": "context_brief", "draft_id": draft["id"], "draft_revision": draft["revision"]})
        assert started.status_code == 202, started.text
        run_id = started.json()["data"]["run_id"]
        view = client.get(f"/api/projects/{project_id}/analyses/{run_id}").json()["data"]
        request = provider.requests[-1]
        foreign = copy.deepcopy(provider.evaluate(request).payload)
        foreign["items"][0]["sources"] = [{"source_type": "draft_claim", "source_id": "draft-claim-other-project-r999-1"}]
        try:
            WritingAnalysisEngine(provider).validate(foreign, request)
            foreign_rejected = False
        except ValueError:
            foreign_rejected = True
        saved_again = client.patch(f"/api/projects/{project_id}/drafts/{draft['id']}", headers=idem(), json={"base_revision": draft["revision"], "body": body + "新版本补充。"})
        assert saved_again.status_code == 200, saved_again.text
        stale = client.get(f"/api/projects/{project_id}/analyses/{run_id}").json()["data"]["is_stale"]
    return {"name": name, "body": body, "body_length": len(body), "request_bindings": request["bindings"], "request_written": request["layers"]["written"], "retrieval": view["retrieval"], "status": view["status"], "analysis": view.get("analysis"), "foreign_draft_claim_rejected": foreign_rejected, "old_result_stale_after_save": stale, "temporary_runtime": str(root)}


results = {"policy": {"network": "external socket, real HTTP transport and SMTP denied; loopback socketpair allowed for Windows asyncio", "provider": "in-process fake only", "business_files_changed": False}, "g01": [], "g02": []}
results["g01"].append(temporal_case("later_hour_control", "黎青在今日二十二点认出信使。", "今日二十点，黎青还不知道信使身份。"))
results["g01"].append(temporal_case("relative_day_full_anchor_control", "今日十八点，秦渡已经知道信使身份。", "昨日十八点，秦渡还不知道信使身份。"))
results["g01"].append(temporal_case("relative_day_short_anchors", "今日十八点，秦渡已经知道信使身份。", "昨日十八点，秦渡还不知道信使身份。", "十八点", "十八点"))
results["g01"].append(temporal_case("ordinal_day_full_anchors", "第二天十八点，秦渡已经知道信使身份。", "第一天十八点，秦渡还不知道信使身份。"))
results["g01"].append(temporal_case("explicit_lie_same_time", "今日十八点，黎青故意撒谎说自己不知道信使身份。", "今日十八点，黎青已经知道信使身份。"))
results["g01"].append(temporal_case("explicit_recollection_short_anchors", "今日十八点，秦渡回忆昨日十八点尚不知道信使身份。", "今日十八点，秦渡已经知道信使身份。", "今日十八点", "今日十八点"))
results["g02"].append(api_brief_case("short_draft_omitted_by_model", "林默走进北门。银钥匙已经交给陈澈。她此时已经知道弟弟还活着。"))
results["g02"].append(api_brief_case("single_claim_truncated_below_body_limit", "林默沿着长廊向前走，" * 28 + "最后把银钥匙交给陈澈并得知弟弟还活着。"))
results["g02"].append(api_brief_case("body_limit_control", "林默在雾港核对潮汐表。" * 180))

output = pathlib.Path(__file__).with_name("probe-results.json")
output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"output": str(output), "g01": [{"name": case["name"], "validation": case["validation"]["accepted"], "status": case["execute"]["status"], "nature": [issue["nature"] for issue in case["execute"].get("issues", [])], "fake_calls": case["fake_calls"]} for case in results["g01"]], "g02": [{"name": case["name"], "status": case["status"], "evidence_status": case["analysis"]["evidence_status"], "coverage": case["analysis"]["draft_coverage"], "truncated": case["retrieval"]["truncated"], "foreign_rejected": case["foreign_draft_claim_rejected"], "stale": case["old_result_stale_after_save"]} for case in results["g02"]]}, ensure_ascii=False, indent=2))
