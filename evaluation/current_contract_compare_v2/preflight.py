"""Capture exact current API business inputs with a deterministic, no-network Provider."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
os.environ.update({"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3219",
                   "BACKEND_ORIGIN": "http://127.0.0.1:8219", "TRUSTED_HOSTS": "testserver,127.0.0.1",
                   "TRUSTED_ORIGINS": "http://testserver,http://127.0.0.1:3219"})

from app.provider import ProviderResult
from evaluation.v2_fixture_loader import fixture_runtime, load_corpus

CORPORA = {path.stem: path for path in (HERE / "corpora").glob("*.json")}


class NoIssueProvider:
    label = "compare-v2-offline-provider"
    model_label = "compare-v2-no-model"
    available = True

    def __init__(self):
        self.requests = []

    def evaluate(self, request):
        self.requests.append(copy.deepcopy(request))
        return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1, latency_ms=1)


def data(response):
    if response.status_code >= 400:
        raise RuntimeError(f"fixture_api_failed:{response.status_code}:{response.text[:200]}")
    return response.json()["data"]


def capture() -> dict:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    if len(cases) != 24 or len(CORPORA) != 4:
        raise RuntimeError("case_or_corpus_count_invalid")
    provider, rows, missing = NoIssueProvider(), [], []
    for case in cases:
        key = case["corpus_key"]
        corpus = load_corpus(key, CORPORA)
        by_location = {(x["chapter_number"], x["source_label"]): x for x in corpus["chapters"]}
        expected = {(x["chapter_number"], x["source_label"]) for x in case["expected_evidence"]}
        if len(expected) != len(case["expected_evidence"]):
            raise RuntimeError("duplicate_required_evidence:" + case["case_id"])
        for item in case["expected_evidence"]:
            chapter = by_location[(item["chapter_number"], item["source_label"])]
            from evaluation.current_contract_compare_v2.build import sha
            if sha(chapter["body"]) != item["body_sha256"]:
                raise RuntimeError("source_digest_invalid:" + case["case_id"])
        with fixture_runtime(key, provider, CORPORA) as runtime:
            client, identity = runtime.client, runtime.identity
            from datetime import datetime, timezone
            with runtime.app.state.database.connection() as connection:
                runtime.app.state.database._insert_empty_author_context_zero(
                    connection, identity.project_id, datetime.now(timezone.utc).isoformat())
            project = data(client.get(f"/api/projects/{identity.project_id}"))
            saved = data(client.patch(f"/api/projects/{identity.project_id}/drafts/{identity.draft_id}",
                                      headers={"Idempotency-Key": str(uuid.uuid4())},
                                      json={"base_revision": project["current_draft"]["revision"],
                                            "body": case["target_draft"]}))
            started = data(client.post(f"/api/projects/{identity.project_id}/checks",
                                       headers={"Idempotency-Key": str(uuid.uuid4())},
                                       json={"draft_id": saved["id"], "draft_revision": saved["revision"]}))
            run = data(client.get(f"/api/projects/{identity.project_id}/checks/{started['run_id']}?include=metrics"))
            if run["status"] != "completed" or len(provider.requests) != len(rows) + 1:
                raise RuntimeError("offline_api_contract_invalid:" + case["case_id"])
            request = provider.requests[-1]
            trace = next((x for x in run["metrics"]["retrieval"] if x["claim_ordinal"] == 1), None)
            returned = {semantic for semantic, span_id in identity.semantic_spans.items()
                        if trace and span_id in trace["returned_span_ids"]}
            selected_ids = {span["id"] for claim in request["claims"] for span in claim["allowed_evidence"]}
            selected = {semantic for semantic, span_id in identity.semantic_spans.items()
                        if span_id in selected_ids}
            hit = expected <= returned and expected <= selected
            if not hit:
                missing.append({"case_id": case["case_id"], "expected": sorted(expected),
                                "retrieval_returned": sorted(returned), "business_selected": sorted(selected)})
            rows.append({"case_id": case["case_id"], "corpus_key": key,
                         "expected_evidence": sorted(expected), "retrieval_returned": sorted(returned),
                         "business_selected": sorted(selected), "required_evidence_present": hit,
                         "business_request": request, "product_status_with_fake_provider": run["status"]})
    return {"schema_version": "current-contract-compare-v2-offline-capture",
            "fake_provider_calls": len(provider.requests), "real_provider_calls": 0,
            "required_evidence_present_count": sum(x["required_evidence_present"] for x in rows),
            "missing": missing, "rows": rows}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = capture()
    destination = pathlib.Path(args.output).resolve()
    if destination.parent != HERE.resolve():
        raise RuntimeError("output_must_be_in_comparison_directory")
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(destination), "cases": len(result["rows"]),
                      "hits": result["required_evidence_present_count"],
                      "missing": len(result["missing"]), "real_provider_calls": 0}, ensure_ascii=False))
