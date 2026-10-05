"""Validate the locked Stage 11M V2 capacity-repair result contract."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import validate_stage11m_real_300k as base

EVIDENCE_ID = "real-novel-300k-11m-v2"
REPAIR_CONTRACT = "bounded-write-responses-v1"


def validate_result(data: dict) -> bool:
    if data.get("evidence_id") != EVIDENCE_ID or data.get("capacity_repair_contract") != REPAIR_CONTRACT:
        return False
    compatible=copy.deepcopy(data)
    compatible["evidence_id"]="real-novel-300k-11m-v1"
    if not base.validate_result(compatible):
        return False
    metrics=data.get("idempotency_metrics",{})
    decisions=data.get("initialization_core_decisions")
    return (
        isinstance(decisions,int) and decisions >= 1
        and metrics.get("candidate_decision_rows") == decisions
        and isinstance(metrics.get("candidate_decision_max_response_json_bytes"),int)
        and metrics["candidate_decision_max_response_json_bytes"] <= 2048
        and isinstance(metrics.get("initialization_max_response_json_bytes"),int)
        and metrics["initialization_max_response_json_bytes"] <= 16384
        and isinstance(metrics.get("initialization_commit_max_response_json_bytes"),int)
        and metrics["initialization_commit_max_response_json_bytes"] <= 16384
        and isinstance(metrics.get("table_bytes"),int)
        and metrics["table_bytes"] <= 8 * 1024 * 1024
    )


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--results",type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.results.read_text(encoding="utf-8"))
    passed=validate_result(data)
    print(json.dumps({"validator":"stage11m-real-novel-300k-11m-v2","valid":passed}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
