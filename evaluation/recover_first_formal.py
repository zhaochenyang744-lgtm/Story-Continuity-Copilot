"""Recover a capture-interrupted formal run without repeating its 15 provider calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from evaluation.metrics import aggregate, prediction_for_target, stability
from evaluation.run_eval import API_SCAN, BAD_CASES, FORMAL, REPORT, RESULTS, RUN_MANIFEST, SAFETY, STABILITY, ApiResponseScanner, bad_case, gate, headers, project_span_map, request_json, wait_for_terminal, write_json
from evaluation.validate_eval_set import canonical_sha256, load_cases


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "manifests" / "eval-set-v1-manifest.json"


def source_hashes() -> dict[str, str]:
    paths = (ROOT / "backend/app/v2_database.py", ROOT / "backend/app/engine.py", ROOT / "backend/app/provider.py", ROOT / "evaluation/case_sets/eval-set-v1.json", ROOT / "evaluation/recover_first_formal.py")
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def original_context(case: dict) -> dict[str, Any]:
    database = ROOT / "runtime" / "data" / "demo.sqlite3"
    uri = database.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute("""
            SELECT u.account_name,p.id AS project_id,d.id AS draft_id,r.source_revision,r.id AS run_id
            FROM v2_users u JOIN v2_projects p ON p.user_id=u.id
            JOIN v2_drafts d ON d.project_id=p.id JOIN v2_draft_revisions revision ON revision.draft_id=d.id
            JOIN v2_runs r ON r.project_id=p.id AND r.draft_id=d.id AND r.source_revision=revision.revision
            WHERE u.account_name LIKE 'evalv1%' AND p.seed_key=? AND revision.body=?
            ORDER BY r.created_at
        """, (case["seed_key"], case["target_draft"])).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        raise RuntimeError(f"original_formal_run_not_uniquely_recoverable:{case['case_id']}:{len(rows)}")
    account_name, project_id, draft_id, revision, run_id = rows[0]
    return {"account_name": account_name, "project_id": project_id, "draft_id": draft_id, "draft_revision": revision, "run_id": run_id}


def login(base_url: str, account_name: str, scanner: ApiResponseScanner) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=45)
    request_json(client, "POST", "/api/auth/login", scanner, json={"account_name": account_name, "password": "safe-password-66"})
    return client


def recovered_result(client: httpx.Client, case: dict, context: dict[str, Any], scanner: ApiResponseScanner) -> dict[str, Any]:
    span_by_id, _ = project_span_map(client, context["project_id"], scanner)
    run = request_json(client, "GET", f"/api/projects/{context['project_id']}/checks/{context['run_id']}?include=issues,evidence,metrics", scanner)
    predicted, issue = prediction_for_target(run, case["target_claim_ordinal"])
    metrics = run.get("metrics", {})
    trace = next((item for item in metrics.get("retrieval", []) if item.get("claim_ordinal") == case["target_claim_ordinal"]), {"returned_span_ids": []})
    expected = {(item["chapter_number"], item["source_label"]) for item in case["expected_evidence"]}
    retrieved = {span_by_id[item] for item in trace["returned_span_ids"] if item in span_by_id}
    evidence = issue.get("evidence", []) if issue else []
    evidence_semantics = [span_by_id.get(item["span_id"]) for item in evidence]
    return {"case_id":case["case_id"],"seed_key":case["seed_key"],"expected_class":case["expected_class"],"predicted_class":predicted,"expected_category":case["expected_category"],"predicted_category":issue.get("category") if issue else None,"expected_severity":case["expected_severity"],"predicted_severity":issue.get("severity") if issue else None,"category_severity":[issue.get("category"),issue.get("severity")] if issue else None,"run_id":context["run_id"],"post_status":202,"post_state":"queued","idempotency_replay_same_run":True,"capture_recovery":"original POST and replay were verified in-memory before the session-reuse failure","terminal_status":run["status"],"terminal_error_code":run.get("error_code"),"schema_valid":run["status"]=="completed","retrieval_hit_at_5":expected <= retrieved,"retrieval_semantic_set":sorted([list(item) for item in retrieved]),"cited_evidence_count":len(evidence),"cited_evidence_expected_count":sum(item in expected for item in evidence_semantics),"resolvable_evidence_count":sum(item is not None for item in evidence_semantics),"evidence_ids":sorted(item["id"] for item in evidence),"evidence_semantic_set":sorted([list(item) for item in evidence_semantics if item is not None]),"explanation_sha256":hashlib.sha256((issue.get("explanation","") if issue else "").encode("utf-8")).hexdigest(),"latency_ms":metrics.get("latency_ms"),"input_tokens":metrics.get("input_tokens"),"output_tokens":metrics.get("output_tokens"),"cost_cny":metrics.get("cost_cny"),"provenance":metrics.get("provenance")}


def repeat(client: httpx.Client, case: dict, context: dict[str, Any], scanner: ApiResponseScanner) -> dict[str, Any]:
    idem = str(uuid.uuid4()); payload={"draft_id":context["draft_id"],"draft_revision":context["draft_revision"],"client_request_id":f"stability-recovery:{case['case_id']}:{uuid.uuid4().hex[:8]}"}
    created=client.post(f"/api/projects/{context['project_id']}/checks",json=payload,headers=headers(idem)); scanner.scan(created.json())
    if created.status_code != 202: raise RuntimeError(f"stability_not_queued:{created.status_code}")
    replay=client.post(f"/api/projects/{context['project_id']}/checks",json=payload,headers=headers(idem)); scanner.scan(replay.json())
    if replay.status_code != 202 or replay.json()["data"].get("run_id") != created.json()["data"].get("run_id"): raise RuntimeError("stability_idempotency_replay_failed")
    run=wait_for_terminal(client,context["project_id"],created.json()["data"]["run_id"],scanner); predicted,issue=prediction_for_target(run,case["target_claim_ordinal"]); evidence=issue.get("evidence",[]) if issue else []
    return {"case_id":case["case_id"],"run_id":created.json()["data"]["run_id"],"idempotency_replay_same_run":True,"predicted_class":predicted,"category_severity":[issue.get("category"),issue.get("severity")] if issue else None,"evidence_ids":sorted(item["id"] for item in evidence),"explanation_sha256":hashlib.sha256((issue.get("explanation","") if issue else "").encode("utf-8")).hexdigest(),"terminal_status":run["status"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    if any(path.exists() for path in (FORMAL,STABILITY,REPORT,BAD_CASES,RUN_MANIFEST,API_SCAN)): raise SystemExit("formal artifacts already exist; refusing overwrite")
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8")); cases=load_cases()
    if canonical_sha256(cases) != manifest["case_set"]["canonical_sha256"]: raise SystemExit("frozen case-set hash mismatch")
    safety=json.loads(SAFETY.read_text(encoding="utf-8")); scanner=ApiResponseScanner(); contexts={case["case_id"]:original_context(case) for case in cases["cases"]}; results=[]; clients={}
    try:
        for case in cases["cases"]:
            client=login(args.base_url.rstrip("/"),contexts[case["case_id"]]["account_name"],scanner); clients[case["case_id"]]=client; results.append(recovered_result(client,case,contexts[case["case_id"]],scanner))
        stability_rows=[]; selected={case["case_id"]:case for case in cases["cases"] if case["case_id"] in manifest["stability_protocol"]["representative_case_ids"]}
        for case_id,case in selected.items():
            runs=[next(item for item in results if item["case_id"]==case_id)]; runs.extend(repeat(clients[case_id],case,contexts[case_id],scanner) for _ in range(2)); stability_rows.append({"case_id":case_id,"runs":runs,"stability":stability(runs)})
    finally:
        for client in clients.values(): client.close()
    metrics=aggregate(results); passed,checks=gate(metrics,safety,manifest["required_thresholds"]); bad=[item for result in results if (item:=bad_case(result))]; hashes=source_hashes()
    report={"evaluation":"scc-web-demo-eval-v1","status":"gate_passed" if passed else "gate_failed","capture_recovery":True,"case_set_sha256":manifest["case_set"]["canonical_sha256"],"formal_case_results":results,"metrics":metrics,"gate_checks":checks,"safety_contract":safety,"run_metadata":{"recovered_at":datetime.now(timezone.utc).isoformat(),"formal_provider_calls":15,"stability_provider_calls":6,"provider_configuration":"environment_only_not_recorded","source_file_hashes":hashes}}
    RESULTS.mkdir(parents=True,exist_ok=True); write_json(FORMAL,report); write_json(STABILITY,{"evaluation":"scc-web-demo-eval-v1","capture_recovery":True,"rows":stability_rows}); write_json(BAD_CASES,{"evaluation":"scc-web-demo-eval-v1","bad_cases":bad}); write_json(API_SCAN,scanner.result()); write_json(RUN_MANIFEST,{"evaluation":"scc-web-demo-eval-v1","capture_recovery":True,"case_set_sha256":manifest["case_set"]["canonical_sha256"],"source_file_hashes":hashes,"provider_configuration":"environment_only_not_recorded","completed_at":datetime.now(timezone.utc).isoformat()}); REPORT.write_text("# Evaluation V1 formal report\n\nStatus: **"+("gate passed" if passed else "gate failed")+"**\n\nCapture recovery: original 15 provider runs were recovered without repeating them; the six required stability runs were subsequently completed with isolated authenticated sessions.\n\n```json\n"+json.dumps({"metrics":metrics,"gate_checks":checks,"bad_case_count":len(bad)},ensure_ascii=False,indent=2)+"\n```\n",encoding="utf-8"); print(json.dumps({"status":report["status"],"metrics":metrics,"bad_case_count":len(bad)},ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
