# Evaluation formal report

Execution kind: **first_valid_formal**

Status: **gate_failed**

```json
{
  "metrics": {
    "confusion_matrix": {
      "conflict": {
        "conflict": 8,
        "no_conflict": 0,
        "insufficient_evidence": 0
      },
      "no_conflict": {
        "conflict": 0,
        "no_conflict": 8,
        "insufficient_evidence": 0
      },
      "insufficient_evidence": {
        "conflict": 0,
        "no_conflict": 0,
        "insufficient_evidence": 8
      }
    },
    "accuracy": 1.0,
    "macro_f1": 1.0,
    "conflict": {
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0
    },
    "no_conflict_false_positive_rate": 0.0,
    "insufficient_evidence_recall": 1.0,
    "retrieval_expected_evidence_hit_at_5": 1.0,
    "cited_evidence_precision": 1.0,
    "evidence_resolvability_grounding": 1.0,
    "schema_validity": 1.0,
    "conflict_category_accuracy": 0.875,
    "designated_category_mismatch_regression": {
      "correct": 2,
      "total": 3
    },
    "expected_evidence_recall": 0.5625,
    "multi_direct_evidence_full_set_recall": 0.125,
    "latency_ms": {
      "p50": 1361,
      "p95": 2149
    },
    "tokens": {
      "input_total": 35468,
      "output_total": 3154
    },
    "cost": "unavailable"
  },
  "gate_checks": {
    "macro_f1": true,
    "conflict_recall": true,
    "insufficient_evidence_recall": true,
    "no_conflict_false_positive_rate": true,
    "retrieval_expected_evidence_hit_at_5": true,
    "cited_evidence_precision": true,
    "schema_validity": true,
    "evidence_resolvability_grounding": true,
    "fail_closed_safety_paths": true,
    "conflict_category_accuracy": true,
    "designated_category_mismatch_regression": false,
    "expected_evidence_recall": false,
    "multi_direct_evidence_full_set_recall": false
  },
  "bad_case_count": 7,
  "provider_execution": {
    "provider_run_records": 30,
    "actual_provider_http_attempts": 30,
    "successful_provider_responses": 30,
    "terminal_status_counts": {
      "completed": 30
    },
    "input_tokens_returned": 44302,
    "output_tokens_returned": 4001,
    "cost": "unavailable",
    "elapsed_ms": 62971
  }
}
```
