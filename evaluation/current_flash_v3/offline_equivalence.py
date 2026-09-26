"""Capture corrected G03 fixtures through product API with zero external HTTP."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
from unittest.mock import patch

from evaluation.current_flash_v2 import run as v2
from evaluation.current_flash_v3 import fixture
from app.provider import ProviderResult

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN_ID = "offline-equivalence-20260926-01"
OUTPUT = HERE / "runs" / RUN_ID
WORK = ROOT / "artifacts" / "current_flash_v3" / RUN_ID
V2_CASES = v2.HERE / "runs" / "flash-v2-20260926-01" / "cases"
INPUT_FILES = [v2.HERE / "run.py", v2.HERE / "cases.json", v2.HERE / "g03-corpus.json",
               HERE / "fixture.py", HERE / "test_offline.py", HERE / "offline_equivalence.py", HERE / "PLAN.md",
               ROOT / "evaluation" / "v2_fixture_loader.py", ROOT / "backend" / "app" / "engine.py",
               ROOT / "backend" / "app" / "v2_database.py"]


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def differing_paths(left, right, prefix="$") -> list[str]:
    if type(left) is not type(right):
        return [prefix]
    if isinstance(left, dict):
        return [path for key in sorted(set(left) | set(right))
                for path in (differing_paths(left[key], right[key], f"{prefix}.{key}")
                             if key in left and key in right else [f"{prefix}.{key}"])]
    if isinstance(left, list):
        if len(left) != len(right):
            return [f"{prefix}.length"]
        return [path for i, (a, b) in enumerate(zip(left, right)) for path in differing_paths(a, b, f"{prefix}[{i}]")]
    return [] if left == right else [prefix]


def fake_evaluate(self, request):
    case = self._v3_case
    fixture.check_request(case, request)
    return ProviderResult({"summary": "离线输入捕获。", "items": []}, 1, 1, latency_ms=1)


def run() -> dict:
    v2.verify_freeze()
    if OUTPUT.exists() or WORK.exists():
        raise RuntimeError("v3_equivalence_identity_already_exists")
    OUTPUT.mkdir(parents=True, exist_ok=False)
    WORK.mkdir(parents=True, exist_ok=False)
    cases = json.loads((v2.HERE / "cases.json").read_text(encoding="utf-8"))["g03"]
    source_hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): v2.sha(p) for p in INPUT_FILES}
    v2.write_new(OUTPUT / "start.json", {"run_id": RUN_ID, "git_head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "source_hashes": source_hashes,
        "external_http_dispatches": 0, "baseline_v2_run": "flash-v2-20260926-01"})
    results = []
    env = {"CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": v2.MODEL,
           "CONTINUITY_BASE_URL": v2.BASE_URL, "CONTINUITY_API_KEY": "offline-capture-only"}
    with patch.dict(os.environ, env), patch.object(v2.DeepSeekProvider, "evaluate", fake_evaluate):
        provider = v2.ObservedProvider()
        for case in cases:
            provider.case_id = case["id"]
            provider._v3_case = case
            provider.expected_case = case
            runtime = fixture.create_case_runtime(case, provider, WORK / case["id"])
            try:
                project_id = runtime.identity.project_id
                project = runtime.client.get(f"/api/projects/{project_id}").json()["data"]
                view = v2.analysis(runtime.client, project_id, project["current_draft"], "change_impact",
                                   {"target_type": "memory", "target_id": fixture.MEMORY,
                                    "proposed_change": "改为由沈砚保管星钥。"})
                fixture.check_database(runtime.app.state.database, project_id, case)
                if len(provider.business_requests) != len(results) + 1 or provider.http_events:
                    raise RuntimeError("offline_provider_capture_count_or_external_http_mismatch")
                request = provider.business_requests[-1]["business_request"]
                fixture.check_request(case, request)
                baseline_path = next(V2_CASES.glob(f"*-{case['id']}.json"))
                baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
                baseline_request = baseline["business_requests"][0]["business_request"]
                differences = differing_paths(baseline_request, request)
                row = {"case_id": case["id"], "v2_case_file": str(baseline_path.relative_to(ROOT)).replace("\\", "/"),
                       "v2_business_request_sha256": digest(baseline_request), "v3_business_request_sha256": digest(request),
                       "exact_business_request_equal": not differences, "different_paths": differences,
                       "v3_business_request": request, "v3_fake_product_status": view["status"],
                       "external_http_dispatches": len(provider.http_events)}
                v2.write_new(OUTPUT / "cases" / f"{case['id']}.json", row)
                results.append({key: value for key, value in row.items() if key != "v3_business_request"})
            finally:
                runtime.client.close()
    manifest = v2.workspace_manifest(WORK)
    v2.write_new(OUTPUT / "workspace-manifest.json", manifest)
    summary = {"run_id": RUN_ID, "case_count": len(results), "external_http_dispatches": 0,
               "all_exact_business_requests_equal": len(results) == 4 and all(r["exact_business_request_equal"] for r in results),
               "cases": results, "database_files": len(manifest["database_files"])}
    v2.write_new(OUTPUT / "summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
