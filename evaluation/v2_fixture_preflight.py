"""Run V2 candidate retrieval checks through the production API in temporary fixtures."""
from __future__ import annotations

import argparse
import json
import uuid
from typing import Any

from evaluation.v2_fixture_loader import CORPUS_PATHS, V3_CORPUS_PATHS, V4_CORPUS_PATHS, fixture_runtime
from evaluation.validate_eval_set_v2_candidate import load_candidate
from evaluation.validate_eval_set_v3_candidate import load_v3_candidate
from evaluation.validate_eval_set_v4_candidate import load_v4_candidate
from app.provider import ProviderResult


class EmptyIssueProvider:
    """Local contract provider: retrieval runs, but it never emits an Issue."""

    label = "evaluation-fixture-provider"
    model_label = "evaluation-fixture-model"
    available = True

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, _: dict[str, Any]) -> ProviderResult:
        self.calls += 1
        return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1, latency_ms=1)


def _data(response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"fixture_api_failed:{response.status_code}")
    return response.json()["data"]


def _headers() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _preflight(cases: list[dict[str, Any]], corpus_paths: dict, corpus_key: str | None, candidate_label: str) -> dict[str, Any]:
    provider = EmptyIssueProvider()
    rows: list[dict[str, Any]] = []
    if corpus_key is not None and corpus_key not in corpus_paths:
        raise ValueError("unknown_evaluation_fixture_corpus")
    cases = [case for case in cases if corpus_key is None or case["corpus_key"] == corpus_key]
    for case in cases:
        with fixture_runtime(case["corpus_key"], provider, corpus_paths) as runtime:
            client, identity = runtime.client, runtime.identity
            projects = _data(client.get("/api/projects"))["projects"]
            if [project["id"] for project in projects] != [identity.project_id]:
                raise RuntimeError("fixture_project_scope_invalid")
            project = _data(client.get(f"/api/projects/{identity.project_id}"))
            saved = _data(client.patch(f"/api/projects/{identity.project_id}/drafts/{identity.draft_id}", json={"base_revision": project["current_draft"]["revision"], "body": case["target_draft"]}, headers=_headers()))
            queued = client.post(f"/api/projects/{identity.project_id}/checks", json={"draft_id": saved["id"], "draft_revision": saved["revision"], "client_request_id": f"fixture:{case['case_id']}"}, headers=_headers())
            if queued.status_code != 202 or queued.json()["data"].get("status") != "queued":
                raise RuntimeError("fixture_check_not_queued")
            run = _data(client.get(f"/api/projects/{identity.project_id}/checks/{queued.json()['data']['run_id']}?include=metrics"))
            if run["status"] != "completed":
                raise RuntimeError("fixture_run_not_completed")
            trace = next((item for item in run["metrics"]["retrieval"] if item["claim_ordinal"] == case["target_claim_ordinal"]), None)
            if trace is None:
                raise RuntimeError("fixture_retrieval_trace_missing")
            expected = {(item["chapter_number"], item["source_label"]) for item in case["expected_evidence"]}
            returned = {semantic for semantic, span_id in identity.semantic_spans.items() if span_id in trace["returned_span_ids"]}
            if not expected <= returned:
                raise RuntimeError(f"fixture_expected_evidence_missed:{case['case_id']}")
            with runtime.app.state.database.connection() as connection:
                run_count = connection.execute("SELECT COUNT(*) FROM v2_runs WHERE project_id=?", (identity.project_id,)).fetchone()[0]
                cross_project_evidence = connection.execute("SELECT COUNT(*) FROM v2_retrieval_traces t JOIN v2_runs r ON r.id=t.run_id JOIN v2_source_spans s ON instr(t.returned_span_ids_json,s.id)>0 WHERE r.project_id<>s.project_id").fetchone()[0]
            if run_count != 1 or cross_project_evidence != 0:
                raise RuntimeError("fixture_side_effect_or_lineage_invalid")
            rows.append({"case_id": case["case_id"], "corpus_key": case["corpus_key"], "retrieval_hit_at_5": True, "resolvable_expected_evidence": True, "isolated_project": True})
    if not rows or provider.calls != len(rows):
        raise RuntimeError("fixture_provider_call_count_invalid")
    return {"candidate_label": candidate_label, "candidate_status": "candidate_for_controller_review", "selected_corpus_key": corpus_key, "case_count": len(rows), "retrieval_expected_evidence_hit_at_5": sum(row["retrieval_hit_at_5"] for row in rows), "resolvable_expected_evidence": sum(row["resolvable_expected_evidence"] for row in rows), "fake_provider_calls": provider.calls, "real_provider_calls": 0, "rows": rows}


def preflight_candidate(corpus_key: str | None = None) -> dict[str, Any]:
    return _preflight(load_candidate()["cases"], CORPUS_PATHS, corpus_key, "v2")


def preflight_v3_candidate(corpus_key: str | None = None) -> dict[str, Any]:
    return _preflight(load_v3_candidate()["cases"], V3_CORPUS_PATHS, corpus_key, "v3")


def preflight_v4_candidate(corpus_key: str | None = None) -> dict[str, Any]:
    return _preflight(load_v4_candidate()["cases"], V4_CORPUS_PATHS, corpus_key, "v4")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", choices=sorted(CORPUS_PATHS))
    args = parser.parse_args()
    print(json.dumps(preflight_candidate(args.corpus), ensure_ascii=False, indent=2))
