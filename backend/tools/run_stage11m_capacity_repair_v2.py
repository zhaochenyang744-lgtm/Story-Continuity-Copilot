"""One-shot Stage 11M V2 capacity-repair formal regression."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_stage11m_real_300k as base

EVIDENCE_ID = "real-novel-300k-11m-v2"
REPAIR_CONTRACT = "bounded-write-responses-v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--execute-formal", action="store_true")
    args = parser.parse_args()
    if not args.execute_formal:
        print(json.dumps({"status":"formal_execution_flag_required","provider_http_calls":0}))
        return 2
    if args.results.exists():
        print(json.dumps({"status":"formal_result_already_exists","provider_http_calls":0}))
        return 3
    container_hash,sample_hash,characters,utf8_bytes,sample=base.frozen_sample(args.sample)
    result=base._base(container_hash,sample_hash,characters,utf8_bytes,EVIDENCE_ID)
    result["capacity_repair_contract"]=REPAIR_CONTRACT
    if (container_hash != base.EXPECTED_CONTAINER_SHA256 or sample_hash != base.EXPECTED_SHA256 or characters != base.EXPECTED_CHARACTERS or utf8_bytes != base.EXPECTED_UTF8_BYTES):
        result.update({"status":"gate_failed","stop_reason":"frozen_input_contract_mismatch","provider_http_calls":0})
        base._write_once(args.results,result)
        return 2
    raw=base.DeepSeekProvider()
    raw.max_retries=0
    raw.request_cap=base.HTTP_CAP
    result["provider_model_label"]=raw.model_label
    try:
        result.update(base.formal_run(sample,args.runtime_root,raw))
    except base.RunFailure as error:
        result.update({"status":"gate_failed","stop_reason":error.code,**error.details,"provider_http_calls":getattr(raw,"request_attempts",0),"provider_successful_responses":getattr(raw,"successful_responses",0),"provider_retries":0,"model_output_auto_canon":False})
    except Exception:
        result.update({"status":"gate_failed","stop_reason":"unclassified_formal_failure","provider_http_calls":getattr(raw,"request_attempts",0),"provider_successful_responses":getattr(raw,"successful_responses",0),"provider_retries":0,"model_output_auto_canon":False})
    base._write_once(args.results,result)
    print(json.dumps({"status":result["status"],"stop_reason":result["stop_reason"],"provider_http_calls":result["provider_http_calls"]}))
    return 0 if result["status"] == "completed_pending_independent_gate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
