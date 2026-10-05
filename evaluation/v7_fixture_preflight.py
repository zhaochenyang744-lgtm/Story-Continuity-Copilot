"""Temporary-runtime V7 candidate preflight; this never calls a real Provider."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.provider import ProviderResult
from evaluation.v2_fixture_loader import V7_CORPUS_PATHS, fixture_runtime
from evaluation.validate_eval_set_v7_candidate import load_v7_candidate, validate_all


class DeterministicV7NoIssueProvider:
    label = "evaluation-v7-deterministic-test-provider"
    model_label = "evaluation-v7-deterministic-test-model"
    available = True

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, _: dict[str, Any]) -> ProviderResult:
        self.calls += 1
        return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1, latency_ms=1)


def _data(response: Any) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(f"v7_fixture_api_failed:{response.status_code}")
    return response.json()["data"]


def _headers() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def preflight_v7_candidate(corpus_key: str | None = None) -> dict[str, Any]:
    validation = validate_all()
    if validation["formal_run_executed"]:
        raise RuntimeError("v7_candidate_preflight_refuses_completed_formal_run")
    if corpus_key is not None and corpus_key not in V7_CORPUS_PATHS:
        raise ValueError("unknown_v7_evaluation_fixture_corpus")
    cases = [case for case in load_v7_candidate()["cases"] if corpus_key is None or case["corpus_key"] == corpus_key]
    provider = DeterministicV7NoIssueProvider(); rows = []
    for case in cases:
        with fixture_runtime(case["corpus_key"], provider, V7_CORPUS_PATHS) as runtime:
            client, identity = runtime.client, runtime.identity
            projects = _data(client.get("/api/projects"))["projects"]
            if [project["id"] for project in projects] != [identity.project_id]:
                raise RuntimeError("v7_fixture_account_project_scope_invalid")
            project = _data(client.get(f"/api/projects/{identity.project_id}"))
            saved = _data(client.patch(f"/api/projects/{identity.project_id}/drafts/{identity.draft_id}", json={"base_revision": project["current_draft"]["revision"], "body": case["target_draft"]}, headers=_headers()))
            queued = client.post(f"/api/projects/{identity.project_id}/checks", json={"draft_id": saved["id"], "draft_revision": saved["revision"], "client_request_id": f"v7-preflight:{case['case_id']}"}, headers=_headers())
            if queued.status_code != 202 or queued.json()["data"].get("status") != "queued":
                raise RuntimeError("v7_fixture_check_not_queued")
            run = _data(client.get(f"/api/projects/{identity.project_id}/checks/{queued.json()['data']['run_id']}?include=metrics"))
            if run["status"] != "completed":
                raise RuntimeError("v7_fixture_run_not_completed")
            trace = next((item for item in run["metrics"]["retrieval"] if item["claim_ordinal"] == case["target_claim_ordinal"]), None)
            if trace is None:
                raise RuntimeError("v7_fixture_retrieval_trace_missing")
            expected = {(item["chapter_number"], item["source_label"]) for item in case["expected_evidence"]}
            lineage = {(item["chapter_number"], item["source_label"]) for item in case["source_lineage"] if item["corpus_key"] == case["corpus_key"]}
            returned = {semantic for semantic, span_id in identity.semantic_spans.items() if span_id in trace["returned_span_ids"]}
            if expected != lineage:
                raise RuntimeError(f"v7_fixture_lineage_not_parseable:{case['case_id']}")
            if not expected <= returned:
                raise RuntimeError(f"v7_fixture_expected_evidence_missed:{case['case_id']}")
            with runtime.app.state.database.connection() as connection:
                counts = {"users": connection.execute("SELECT COUNT(*) FROM v2_users").fetchone()[0], "projects": connection.execute("SELECT COUNT(*) FROM v2_projects").fetchone()[0], "runs": connection.execute("SELECT COUNT(*) FROM v2_runs WHERE project_id=?", (identity.project_id,)).fetchone()[0]}
                cross_project_evidence = connection.execute("SELECT COUNT(*) FROM v2_retrieval_traces t JOIN v2_runs r ON r.id=t.run_id JOIN v2_source_spans s ON instr(t.returned_span_ids_json,s.id)>0 WHERE r.project_id<>s.project_id").fetchone()[0]
            if counts != {"users": 1, "projects": 1, "runs": 1} or cross_project_evidence != 0:
                raise RuntimeError("v7_fixture_account_project_isolation_invalid")
            rows.append({"case_id": case["case_id"], "corpus_key": case["corpus_key"], "retrieval_expected_evidence_hit_at_5": True, "evidence_parseable": True, "source_lineage_resolved": True, "account_project_isolated": True})
    if len(rows) != len(cases) or provider.calls != len(rows):
        raise RuntimeError("v7_fixture_fake_provider_call_count_invalid")
    return {"schema_version": "scc-eval-v7-fixture-preflight-v1", "status": "candidate_for_controller_review", "formal_run_executed": False, "provider_calls": 0, "real_provider_calls": 0, "fake_provider_calls": provider.calls, "quality_scored": False, "fake_provider_quality_scored": False, "temporary_runtime_only": True, "selected_corpus_key": corpus_key, "case_count": len(rows), "retrieval_expected_evidence_hit_at_5": sum(row["retrieval_expected_evidence_hit_at_5"] for row in rows), "evidence_parseable": sum(row["evidence_parseable"] for row in rows), "source_lineage_resolved": sum(row["source_lineage_resolved"] for row in rows), "account_project_isolated": sum(row["account_project_isolated"] for row in rows), "validator_status": validation["status"], "rows": rows}


if __name__ == "__main__":
    print(json.dumps(preflight_v7_candidate(), ensure_ascii=False, indent=2))
