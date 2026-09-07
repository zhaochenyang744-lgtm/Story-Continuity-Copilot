import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult
from app.stage13 import Stage13Settings


def idem(value=None):
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class ComparisonProvider:
    available = True
    label = "comparison-stub"
    model_label = "comparison-stub-model"

    def __init__(self, invalid=False):
        self.calls = []
        self.invalid = invalid

    def evaluate(self, request):
        self.calls.append(request)
        if request.get("task") == "context_brief":
            planned = [item for group in request["layers"]["planned"].values() for item in group]
            source = {"source_type": "author_context", "source_id": planned[0]["id"]}
            return ProviderResult(payload={"summary": "仅使用当前规范作者资料。", "summary_sources": [source], "items": [{"section": "related_plan", "text": "当前资料已绑定。", "sources": [source]}]}, input_tokens=8, output_tokens=8, latency_ms=1)
        if self.invalid:
            return ProviderResult(payload={"assessment": "aligned", "explanation": "缺少证据", "evidence": []})
        material = request["comparison"]["material"]
        span = request["comparison"]["passage"]
        assessment = "plan_deviation" if material["nature"] == "plan" else "aligned"
        return ProviderResult(payload={
            "assessment": assessment,
            "explanation": "只比较绑定的作者资料与真实正文证据。",
            "evidence": [
                {"source_type": "author_material", "source_id": material["id"]},
                {"source_type": "source_span", "source_id": span["id"]},
            ],
        }, input_tokens=10, output_tokens=12, latency_ms=1)


class UnavailableProvider:
    available = False
    label = "unavailable"
    model_label = "unavailable"

    def evaluate(self, request):
        raise AssertionError("unavailable provider must not be called")


class V140AuthorContextTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v140-author-context-"))
        self.provider = ComparisonProvider()
        self.app = create_app(AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected"), provider=self.provider, executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
        self.client = TestClient(self.app)
        created = self.client.post("/api/auth/register", headers=idem(), json={"account_name": "v140-context", "display_name": "Author", "password": "safe-password-v140", "recovery_email": "author-v140@example.test"})
        self.assertEqual(created.status_code, 201, created.text)
        self.project_id = created.json()["data"]["onboarding"]["tutorial"]["project_id"]

    def project(self):
        return self.client.get(f"/api/projects/{self.project_id}").json()["data"]

    def source(self):
        response = self.client.get(f"/api/projects/{self.project_id}/source-revisions/1/spans")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["source_spans"][0]

    def create_material(self, **overrides):
        version = self.project()["author_context_version"]
        if "from_" in overrides:
            overrides["from"] = overrides.pop("from_")
        payload = {"base_author_context_version": version, "kind": "story", "title": "作者设定", "content": "钥匙必须留在塔顶。", "nature": "setting", "disclosure": "hidden", "knowledge": "只有作者知道", "from": 1, "to": 3, **overrides}
        response = self.client.post(f"/api/projects/{self.project_id}/author-context/materials", headers=idem(), json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["data"]

    def create_comparison(self, material):
        span = self.source()
        response = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons", headers=idem(), json={"material_id": material["id"], "material_revision": material["revision"], "source_span_id": span["id"], "source_revision": self.project()["source_revision"]})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["data"]

    def test_material_crud_idempotency_archive_restore_and_history(self):
        key = str(uuid.uuid4())
        version = self.project()["author_context_version"]
        payload = {"base_author_context_version": version, "kind": "world", "title": "月门", "content": "只在退潮时开启。", "nature": "setting", "disclosure": "revealed", "knowledge": "守门人知情", "from": 2, "to": 8}
        first = self.client.post(f"/api/projects/{self.project_id}/author-context/materials", headers=idem(key), json=payload)
        replay = self.client.post(f"/api/projects/{self.project_id}/author-context/materials", headers=idem(key), json=payload)
        self.assertEqual((first.status_code, replay.status_code, first.json()["data"]), (201, 201, replay.json()["data"]))
        conflict = self.client.post(f"/api/projects/{self.project_id}/author-context/materials", headers=idem(key), json={**payload, "title": "不同"})
        self.assertEqual((conflict.status_code, conflict.json()["error"]["code"]), (409, "idempotency_conflict"))
        material = first.json()["data"]["material"]
        archived = self.client.post(f"/api/projects/{self.project_id}/author-context/materials/{material['id']}/archive", headers=idem(), json={"base_author_context_version": first.json()["data"]["author_context_version"], "base_revision": 1, "archived": True, "confirm": True})
        self.assertEqual(archived.status_code, 200, archived.text)
        restored = self.client.post(f"/api/projects/{self.project_id}/author-context/materials/{material['id']}/archive", headers=idem(), json={"base_author_context_version": archived.json()["data"]["author_context_version"], "base_revision": 2, "archived": False, "confirm": True})
        self.assertEqual(restored.status_code, 200, restored.text)
        history = self.client.get(f"/api/projects/{self.project_id}/author-context/materials/{material['id']}/versions").json()["data"]["versions"]
        self.assertEqual([item["event"] for item in history], ["create", "archive", "restore"])
        forged = self.client.post(f"/api/projects/{self.project_id}/author-context/materials", headers=idem(), json={**payload, "base_author_context_version": restored.json()["data"]["author_context_version"], "origin": "legacy_author_intent"})
        self.assertIn(forged.status_code, {400, 422})
        boolean_range = self.client.post(f"/api/projects/{self.project_id}/author-context/materials", headers=idem(), json={**payload, "base_author_context_version": restored.json()["data"]["author_context_version"], "from": True})
        self.assertIn(boolean_range.status_code, {400, 422})

    def test_legacy_projection_scope_semantics_and_unauthorized(self):
        listed = self.client.get(f"/api/projects/{self.project_id}/author-context/materials?include_archived=true")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertTrue(all(item["id"].split(":", 1)[0] in {"story", "character", "world"} for item in listed.json()["data"]["materials"]))
        hidden = self.create_material()["material"]
        self.create_material(title="待定", content="也许出现飞船。", nature="idea")
        self.create_material(title="远期", content="第十章以后。", nature="plan", from_=10, to=12)
        basis = self.client.get(f"/api/projects/{self.project_id}/author-context/check-basis?chapter_number=1").json()["data"]
        self.assertIn(hidden["id"], {item["id"] for item in basis["included"]["materials"]})
        reasons = {item["title"]: item["exclusion_reason"] for item in basis["excluded"]["materials"]}
        self.assertEqual((reasons["待定"], reasons["远期"], basis["semantics"]["plan"]), ("idea", "out_of_range", "deviation_is_not_fact_conflict"))
        outsider = TestClient(self.app)
        outsider.post("/api/auth/register", headers=idem(), json={"account_name": "v140-outsider", "display_name": "Other", "password": "safe-password-v141", "recovery_email": "other-v140@example.test"})
        denied = outsider.get(f"/api/projects/{self.project_id}/author-context/materials")
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (404, "resource_not_found"))

    def test_manual_out_of_range_comparison_and_all_decisions(self):
        material = self.create_material(from_=50, to=60)["material"]
        comparison = self.create_comparison(material)
        self.assertFalse(comparison["applicable"])
        current = comparison
        for decision in ("prepare_text_edit", "intentional", "not_issue", "later"):
            response = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}/decisions", headers=idem(), json={"base_decision_revision": current["decision_revision"], "decision": decision, "reason": f"记录 {decision}"})
            self.assertEqual(response.status_code, 200, response.text)
            current = response.json()["data"]["comparison"]
        adjusted = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}/decisions", headers=idem(), json={"base_decision_revision": current["decision_revision"], "decision": "adjust_material", "reason": "修正资料", "base_author_context_version": self.project()["author_context_version"], "base_material_revision": material["revision"], "material_patch": {"content": "钥匙改由守门人保管。"}})
        self.assertEqual(adjusted.status_code, 200, adjusted.text)
        result = adjusted.json()["data"]["comparison"]
        self.assertEqual((len(result["decision_history"]), result["latest_decision"]["after_material"]["revision"], result["is_stale"]), (5, 2, True))
        rejected = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}/analysis", headers=idem(), json={"base_decision_revision": result["decision_revision"]})
        self.assertEqual((rejected.status_code, rejected.json()["error"]["code"]), (409, "author_comparison_stale"))

    def test_comparison_server_snapshots_stale_and_optimistic_lock(self):
        created = self.create_material(); material = created["material"]
        comparison = self.create_comparison(material)
        self.assertEqual(comparison["document"]["content"], "钥匙必须留在塔顶。")
        stale = self.client.patch(f"/api/projects/{self.project_id}/author-context/materials/{material['id']}", headers=idem(), json={"base_author_context_version": created["author_context_version"], "base_revision": 1, "content": "钥匙已经交给守门人。"})
        self.assertEqual(stale.status_code, 200, stale.text)
        viewed = self.client.get(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}").json()["data"]
        self.assertTrue(viewed["is_stale"])
        conflict = self.client.patch(f"/api/projects/{self.project_id}/author-context/materials/{material['id']}", headers=idem(), json={"base_author_context_version": stale.json()["data"]["author_context_version"], "base_revision": 1, "content": "覆盖"})
        self.assertEqual((conflict.status_code, conflict.json()["error"]["code"]), (409, "author_material_revision_conflict"))

    def test_project_source_revision_and_legacy_changes_stale_comparisons_and_block_decisions(self):
        material = self.create_material()["material"]
        comparison = self.create_comparison(material)
        with self.app.state.database.connection() as c:
            c.execute("UPDATE v2_projects SET source_revision=2 WHERE id=?", (self.project_id,))
        viewed = self.client.get(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}").json()["data"]
        self.assertTrue(viewed["is_stale"])
        rejected = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}/decisions", headers=idem(), json={"base_decision_revision": 0, "decision": "not_issue", "reason": "不能用旧来源决定"})
        self.assertEqual((rejected.status_code, rejected.json()["error"]["code"]), (409, "author_comparison_stale"))

        with self.app.state.database.connection() as c:
            c.execute("UPDATE v2_projects SET source_revision=1 WHERE id=?", (self.project_id,))
        legacy_created = self.client.post(f"/api/projects/{self.project_id}/author-intent/story-plans", headers=idem(), json={"base_author_context_version": self.project()["author_context_version"], "title": "旧规划", "summary": "从旧接口创建", "goal": "保持兼容", "status": "planned"})
        self.assertEqual(legacy_created.status_code, 201, legacy_created.text)
        legacy = next(item for item in self.client.get(f"/api/projects/{self.project_id}/author-context/materials?include_archived=true").json()["data"]["materials"] if item["origin"] == "legacy_author_intent")
        legacy_comparison = self.create_comparison(legacy)
        kind, legacy_id = legacy["id"].split(":", 1)
        table = self.app.state.database._AUTHOR_INTENT[kind]["table"]
        with self.app.state.database.connection() as c:
            column = "title" if kind == "story" else "name"
            c.execute(f"UPDATE {table} SET {column}={column}||' changed',updated_at=? WHERE id=? AND project_id=?", ("2099-01-01T00:00:00+00:00", legacy_id, self.project_id))
        legacy_view = self.client.get(f"/api/projects/{self.project_id}/author-context/comparisons/{legacy_comparison['id']}").json()["data"]
        self.assertTrue(legacy_view["is_stale"])
        denied = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{legacy_comparison['id']}/analysis", headers=idem(), json={"base_decision_revision": 0})
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (409, "author_comparison_stale"))
        repaired = self.client.patch(f"/api/projects/{self.project_id}/author-context/materials/{legacy['id']}", headers=idem(), json={"base_author_context_version": self.project()["author_context_version"], "base_revision": legacy["revision"], "content": "作者明确确认后的规范资料"})
        self.assertEqual(repaired.status_code, 200, repaired.text)
        basis = self.client.get(f"/api/projects/{self.project_id}/author-context/check-basis?chapter_number=1").json()["data"]
        self.assertIn(legacy["id"], {item["id"] for item in basis["included"]["materials"]})
        with self.app.state.database.connection() as c:
            c.execute(f"UPDATE {table} SET updated_at=? WHERE id=? AND project_id=?", ("2100-01-01T00:00:00+00:00", legacy_id, self.project_id))
        basis_again = self.client.get(f"/api/projects/{self.project_id}/author-context/check-basis?chapter_number=1").json()["data"]
        self.assertEqual(next(item["exclusion_reason"] for item in basis_again["excluded"]["materials"] if item["id"] == legacy["id"]), "stale")

    def test_analysis_reuses_memory_gate_and_rejects_out_of_range(self):
        out_of_range = self.create_material(nature="plan", from_=50, to=60)["material"]
        comparison = self.create_comparison(out_of_range)
        rejected = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}/analysis", headers=idem(), json={"base_decision_revision": 0})
        self.assertEqual((rejected.status_code, rejected.json()["error"]["code"]), (422, "author_comparison_not_applicable"))
        valid = self.create_material()["material"]
        valid_comparison = self.create_comparison(valid)
        with self.app.state.database.connection() as c:
            c.execute("DELETE FROM v2_memory_records WHERE project_id=?", (self.project_id,))
        gated = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{valid_comparison['id']}/analysis", headers=idem(), json={"base_decision_revision": 0})
        self.assertEqual((gated.status_code, gated.json()["error"]["code"]), (422, "insufficient_project_context"))

    def test_existing_writing_analysis_planned_layer_uses_canonical_takeover(self):
        old = self.client.post(f"/api/projects/{self.project_id}/author-intent/story-plans", headers=idem(), json={"base_author_context_version": self.project()["author_context_version"], "title": "旧安排", "summary": "旧值不应继续进入检查", "goal": "离港", "status": "planned"}).json()["data"]["item"]
        projected = next(item for item in self.client.get(f"/api/projects/{self.project_id}/author-context/materials").json()["data"]["materials"] if item["id"] == f"story:{old['id']}")
        patched = self.client.patch(f"/api/projects/{self.project_id}/author-context/materials/{projected['id']}", headers=idem(), json={"base_author_context_version": self.project()["author_context_version"], "base_revision": projected["revision"], "content": "规范新值：推迟离港", "nature": "plan"})
        self.assertEqual(patched.status_code, 200, patched.text)
        project = self.project()
        run = self.client.post(f"/api/projects/{self.project_id}/analyses", headers=idem(), json={"analysis_type": "context_brief", "draft_id": project["current_draft"]["id"], "draft_revision": project["current_draft"]["revision"]})
        self.assertEqual(run.status_code, 202, run.text)
        planned = self.provider.calls[-1]["layers"]["planned"]["story_plans"]
        self.assertEqual([(item["id"], item["summary"]) for item in planned], [(old["id"], "规范新值：推迟离港")])
        frozen = self.client.get(f"/api/projects/{self.project_id}/analyses/{run.json()['data']['run_id']}").json()["data"]["analysis"]
        self.assertEqual((frozen["summary_sources"][0]["source_id"], frozen["summary_sources"][0]["excerpt"]), (old["id"], "规范新值：推迟离港"))

    def test_analysis_validates_bound_evidence_and_plan_semantics(self):
        material = self.create_material(nature="plan")["material"]
        comparison = self.create_comparison(material)
        response = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}/analysis", headers=idem(), json={"base_decision_revision": 0})
        self.assertEqual(response.status_code, 202, response.text)
        run = self.client.get(f"/api/projects/{self.project_id}/analyses/{response.json()['data']['run_id']}")
        self.assertEqual(run.status_code, 200, run.text)
        data = run.json()["data"]
        self.assertEqual((data["status"], data["analysis"]["assessment"], len(self.provider.calls)), ("completed", "plan_deviation", 1))
        self.assertEqual({item["source_type"] for item in data["analysis"]["evidence"]}, {"author_material", "source_span"})

    def test_unavailable_invalid_and_cancelled_analysis_are_honest(self):
        material = self.create_material()["material"]
        comparison = self.create_comparison(material)
        started = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{comparison['id']}/analysis", headers=idem(), json={"base_decision_revision": 0})
        self.assertEqual(started.status_code, 202, started.text)
        from app.engine import WritingAnalysisEngine
        with self.assertRaisesRegex(ValueError, "evidence_unresolvable"):
            WritingAnalysisEngine(self.provider).validate({"assessment": "aligned", "explanation": "x", "evidence": []}, self.provider.calls[-1])
        self.provider.invalid = True
        second = self.create_comparison(material)
        failed = self.client.post(f"/api/projects/{self.project_id}/author-context/comparisons/{second['id']}/analysis", headers=idem(), json={"base_decision_revision": 0})
        failed_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{failed.json()['data']['run_id']}").json()["data"]
        self.assertEqual((failed_view["status"], failed_view["error_code"]), ("failed", "evidence_unresolvable"))
        self.provider.invalid = False
        retried = self.client.post(f"/api/projects/{self.project_id}/analyses/{failed.json()['data']['run_id']}/retry", headers=idem(), json={})
        self.assertEqual(retried.status_code, 202, retried.text)
        retry_id = retried.json()["data"]["run"]["run_id"]
        retry_view = self.client.get(f"/api/projects/{self.project_id}/analyses/{retry_id}").json()["data"]
        self.assertEqual(retry_view["status"], "completed")
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/author-context/comparisons/{second['id']}").json()["data"]["latest_analysis_run_id"], retry_id)

        queued = []
        cancel_root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v140-cancel-"))
        queued_app = create_app(AppPaths.from_project_root(cancel_root, protected_poc_root=cancel_root / "protected"), provider=ComparisonProvider(), executor=lambda fn, *args: queued.append((fn, args)), settings=Stage13Settings.for_test())
        client = TestClient(queued_app)
        registered = client.post("/api/auth/register", headers=idem(), json={"account_name": "v140-cancel", "display_name": "Cancel", "password": "safe-password-v142", "recovery_email": "cancel-v140@example.test"}).json()["data"]
        project_id = registered["onboarding"]["tutorial"]["project_id"]
        project = client.get(f"/api/projects/{project_id}").json()["data"]
        made = client.post(f"/api/projects/{project_id}/author-context/materials", headers=idem(), json={"base_author_context_version": project["author_context_version"], "kind": "story", "title": "安排", "content": "先去码头。", "nature": "plan", "disclosure": "unspecified"}).json()["data"]["material"]
        span = client.get(f"/api/projects/{project_id}/source-revisions/1/spans").json()["data"]["source_spans"][0]
        compared = client.post(f"/api/projects/{project_id}/author-context/comparisons", headers=idem(), json={"material_id": made["id"], "material_revision": 1, "source_span_id": span["id"], "source_revision": 1}).json()["data"]
        run = client.post(f"/api/projects/{project_id}/author-context/comparisons/{compared['id']}/analysis", headers=idem(), json={"base_decision_revision": 0})
        self.assertEqual((run.status_code, len(queued)), (202, 1))
        cancelled = client.post(f"/api/projects/{project_id}/analyses/{run.json()['data']['run_id']}/cancel", headers=idem(), json={})
        self.assertEqual((cancelled.status_code, cancelled.json()["data"]["status"]), (200, "cancelled"))

        unavailable_root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v140-unavailable-"))
        unavailable_app = create_app(AppPaths.from_project_root(unavailable_root, protected_poc_root=unavailable_root / "protected"), provider=UnavailableProvider(), executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
        unavailable = TestClient(unavailable_app)
        reg = unavailable.post("/api/auth/register", headers=idem(), json={"account_name": "v140-unavailable", "display_name": "Unavailable", "password": "safe-password-v143", "recovery_email": "unavailable-v140@example.test"}).json()["data"]
        unavailable_project = reg["onboarding"]["tutorial"]["project_id"]
        p = unavailable.get(f"/api/projects/{unavailable_project}").json()["data"]
        m = unavailable.post(f"/api/projects/{unavailable_project}/author-context/materials", headers=idem(), json={"base_author_context_version": p["author_context_version"], "kind": "story", "title": "安排", "content": "保持原状。", "nature": "setting", "disclosure": "hidden"}).json()["data"]["material"]
        s = unavailable.get(f"/api/projects/{unavailable_project}/source-revisions/1/spans").json()["data"]["source_spans"][0]
        comp = unavailable.post(f"/api/projects/{unavailable_project}/author-context/comparisons", headers=idem(), json={"material_id": m["id"], "material_revision": 1, "source_span_id": s["id"], "source_revision": 1}).json()["data"]
        denied = unavailable.post(f"/api/projects/{unavailable_project}/author-context/comparisons/{comp['id']}/analysis", headers=idem(), json={"base_decision_revision": 0})
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (503, "provider_unavailable"))


if __name__ == "__main__":
    unittest.main()
