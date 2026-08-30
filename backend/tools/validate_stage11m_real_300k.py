"""Validate a redacted Stage 11M result without reading its runtime SQLite."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED_HASH = "01baefc1039f5efead919c2ea1a78015336726a7e1308beecf65dae782124a48"
FORBIDDEN = {"source_text", "source_path", "prompt", "raw_provider_body", "api_key", "secret", "account", "cookie"}


def _forbidden(value: object) -> bool:
    if isinstance(value, dict): return any(key in FORBIDDEN or _forbidden(item) for key, item in value.items())
    if isinstance(value, list): return any(_forbidden(item) for item in value)
    return False


def validate_result(data: dict) -> bool:
    if _forbidden(data): return False
    common = data.get("stage") == "11M" and data.get("evidence_id") == "real-novel-300k-11m-v1" and data.get("actual_frozen_sample_sha256") == EXPECTED_HASH and data.get("expected_frozen_sample_sha256") == EXPECTED_HASH and data.get("frozen_sample_characters") == 300000 and data.get("frozen_sample_utf8_bytes") == 862721 and data.get("required_provider_model") == "deepseek-v4-pro" and data.get("provider_model_label") == "deepseek-v4-pro" and data.get("provider_max_retries") == 0 and data.get("provider_retries") == 0 and data.get("provider_http_call_cap") == 92 and isinstance(data.get("provider_http_calls"), int) and 0 <= data["provider_http_calls"] <= 92 and all(data.get(key) is False for key in ("contains_source_text", "contains_source_path", "contains_secret", "contains_prompt", "contains_raw_provider_body"))
    if not common: return False
    if data.get("status") == "gate_failed": return isinstance(data.get("stop_reason"), str) and bool(data["stop_reason"])
    if data.get("status") != "completed_pending_independent_gate": return False
    plan = data.get("plan", {})
    timings = data.get("timings_ms", {})
    sizes = data.get("sqlite_bytes", {})
    rounds = data.get("incremental_rounds", [])
    metrics = data.get("initialization_metrics", {})
    required_tables = ("v2_memory_initializations", "v2_memory_candidates", "v2_memory_candidate_decisions", "v2_runs", "v2_memory_delta_batches", "v2_memory_delta_candidates", "v2_memory_delta_decisions", "v2_source_coverage_audits", "v2_memory_records")
    return plan == {"parent_source_spans": 13, "source_chunks": 82, "initialization_batches": 81, "max_normal_input_budget": 5800, "max_repair_input_budget": 5938} and data.get("source_revisions") == [1, 2, 3] and data.get("memory_versions") == [1, 2, 3] and data.get("pending_canon_count") == 0 and data.get("lineage_unresolved_count") == 0 and data.get("model_output_auto_canon") is False and isinstance(data.get("business_table_counts"), dict) and all(data["business_table_counts"].get(table, 0) >= 1 for table in required_tables) and isinstance(metrics.get("total_batches"), int) and metrics["total_batches"] == 81 and metrics.get("validated_batches") == 81 and isinstance(metrics.get("schema_repair_attempts"), int) and 0 <= metrics["schema_repair_attempts"] <= 5 and isinstance(metrics.get("repair_events"), list) and len(metrics["repair_events"]) == metrics["schema_repair_attempts"] and data.get("initialization_provenance", {}).get("model_label") == "deepseek-v4-pro" and data.get("initialization_provenance", {}).get("provider_api_format") == "chat-completions-json-object" and data.get("initialization_provenance", {}).get("prompt_version") == "memory-initialization-v8-pro-two-repair" and data.get("initialization_provenance", {}).get("chunking_method_version") == "source-chunk-v4-5800" and all(isinstance(timings.get(key), int) and timings[key] >= 0 for key in ("import", "batch_planning", "initialization", "incremental_1", "incremental_2", "total")) and timings["initialization"] <= 900000 and timings["total"] <= 1200000 and isinstance(sizes.get("before_import"), int) and isinstance(sizes.get("after_import"), int) and isinstance(sizes.get("after_initialization"), int) and isinstance(sizes.get("final"), int) and sizes["final"] <= 50 * 1024 * 1024 and len(rounds) == 2 and all(row.get("source_revision") == index + 2 and row.get("memory_version") == index + 2 and row.get("core_decisions", 0) >= 1 and row.get("coverage_status") == "covered_with_memory_change" and row.get("run_types") == ["continuity", "memory_delta"] and row.get("retrieval_trace_count", 0) >= 1 and isinstance(row.get("incremental_run_completion_ms"), int) and row["incremental_run_completion_ms"] <= 120000 for index, row in enumerate(rounds))


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--results", type=Path, required=True); args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    passed = validate_result(data)
    print(json.dumps({"validator": "stage11m-real-novel-300k-11m-v1", "valid": passed}))
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
