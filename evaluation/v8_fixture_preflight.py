"""Temporary-runtime V8 candidate preflight; it has no real Provider path."""
from __future__ import annotations

import json
import pathlib
import sys
import uuid
from typing import Any

# The preflight is a repository-root CLI as well as a test helper.  Resolve
# backend explicitly without reading an environment file or relying on tests.
ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_PATH = ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.provider import ProviderResult
from evaluation.v2_fixture_loader import V8_CORPUS_PATHS, fixture_runtime
from evaluation.validate_eval_set_v8_candidate import load_v8_candidate, validate_all


class DeterministicV8NoIssueProvider:
    label = "evaluation-v8-deterministic-test-provider"; model_label = "evaluation-v8-deterministic-test-model"; available = True
    def __init__(self) -> None: self.calls = 0
    def evaluate(self, _: dict[str, Any]) -> ProviderResult:
        self.calls += 1; return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1, latency_ms=1)


def _data(response: Any) -> dict[str, Any]:
    if response.status_code >= 400: raise RuntimeError(f"v8_fixture_api_failed:{response.status_code}")
    return response.json()["data"]


def preflight_v8_candidate(corpus_key: str | None = None) -> dict[str, Any]:
    validation = validate_all()
    if corpus_key is not None and corpus_key not in V8_CORPUS_PATHS: raise ValueError("unknown_v8_evaluation_fixture_corpus")
    cases = [case for case in load_v8_candidate()["cases"] if corpus_key is None or case["corpus_key"] == corpus_key]
    provider, rows = DeterministicV8NoIssueProvider(), []
    for case in cases:
        with fixture_runtime(case["corpus_key"], provider, V8_CORPUS_PATHS) as runtime:
            client, identity = runtime.client, runtime.identity
            if [project["id"] for project in _data(client.get("/api/projects"))["projects"]] != [identity.project_id]: raise RuntimeError("v8_fixture_account_project_scope_invalid")
            project = _data(client.get(f"/api/projects/{identity.project_id}"))
            headers = {"Idempotency-Key": str(uuid.uuid4())}
            saved = _data(client.patch(f"/api/projects/{identity.project_id}/drafts/{identity.draft_id}", json={"base_revision": project["current_draft"]["revision"], "body": case["target_draft"]}, headers=headers))
            queued = client.post(f"/api/projects/{identity.project_id}/checks", json={"draft_id": saved["id"], "draft_revision": saved["revision"], "client_request_id": f"v8-preflight:{case['case_id']}"}, headers=headers)
            if queued.status_code != 202 or queued.json()["data"].get("status") != "queued": raise RuntimeError("v8_fixture_check_not_queued")
            run = _data(client.get(f"/api/projects/{identity.project_id}/checks/{queued.json()['data']['run_id']}?include=metrics"))
            trace = next((item for item in run["metrics"]["retrieval"] if item["claim_ordinal"] == 1), None)
            expected = {(item["chapter_number"], item["source_label"]) for item in case["expected_evidence"]}
            lineage = {(item["chapter_number"], item["source_label"]) for item in case["source_lineage"]}
            returned = {semantic for semantic, span_id in identity.semantic_spans.items() if trace and span_id in trace["returned_span_ids"]}
            with runtime.app.state.database.connection() as connection:
                counts = {"users": connection.execute("SELECT COUNT(*) FROM v2_users").fetchone()[0], "projects": connection.execute("SELECT COUNT(*) FROM v2_projects").fetchone()[0], "runs": connection.execute("SELECT COUNT(*) FROM v2_runs WHERE project_id=?", (identity.project_id,)).fetchone()[0]}
                cross = connection.execute("SELECT COUNT(*) FROM v2_retrieval_traces t JOIN v2_runs r ON r.id=t.run_id JOIN v2_source_spans s ON instr(t.returned_span_ids_json,s.id)>0 WHERE r.project_id<>s.project_id").fetchone()[0]
            if run["status"] != "completed" or trace is None or expected != lineage or not expected <= returned or counts != {"users": 1, "projects": 1, "runs": 1} or cross != 0: raise RuntimeError(f"v8_fixture_preflight_contract_invalid:{case['case_id']}")
            rows.append({"case_id": case["case_id"], "corpus_key": case["corpus_key"], "retrieval_expected_evidence_hit_at_5": True, "evidence_parseable": True, "source_lineage_resolved": True, "account_project_isolated": True})
    if len(rows) != len(cases) or provider.calls != len(rows): raise RuntimeError("v8_fixture_fake_provider_call_count_invalid")
    return {"schema_version": "scc-eval-v8-fixture-preflight-v1", "status": validation["status"], "formal_run_executed": False, "provider_calls": 0, "real_provider_calls": 0, "fake_provider_calls": provider.calls, "quality_scored": False, "fake_provider_quality_scored": False, "temporary_runtime_only": True, "selected_corpus_key": corpus_key, "case_count": len(rows), "retrieval_expected_evidence_hit_at_5": len(rows), "evidence_parseable": len(rows), "source_lineage_resolved": len(rows), "account_project_isolated": len(rows), "validator_status": validation["status"], "rows": rows}


if __name__ == "__main__": print(json.dumps(preflight_v8_candidate(), ensure_ascii=False, indent=2))
