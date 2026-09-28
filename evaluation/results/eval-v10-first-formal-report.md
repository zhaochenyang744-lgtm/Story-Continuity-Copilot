# Evaluation formal report

Execution kind: **first_valid_formal**

Status: **gate_passed**

```json
{
  "metrics": {
    "confusion_matrix": {
      "conflict": {
        "conflict": 11,
        "no_conflict": 0,
        "insufficient_evidence": 1
      },
      "no_conflict": {
        "conflict": 0,
        "no_conflict": 12,
        "insufficient_evidence": 0
      },
      "insufficient_evidence": {
        "conflict": 0,
        "no_conflict": 0,
        "insufficient_evidence": 12
      }
    },
    "accuracy": 0.9722222222222222,
    "macro_f1": 0.9721739130434783,
    "conflict": {
      "precision": 1.0,
      "recall": 0.9166666666666666,
      "f1": 0.9565217391304348
    },
    "no_conflict_false_positive_rate": 0.0,
    "insufficient_evidence_recall": 1.0,
    "retrieval_expected_evidence_hit_at_5": 1.0,
    "cited_evidence_precision": 1.0,
    "evidence_resolvability_grounding": 1.0,
    "schema_validity": 1.0,
    "conflict_category_accuracy": 1.0,
    "designated_category_mismatch_regression": {
      "correct": 3,
      "total": 3
    },
    "expected_evidence_recall": 1.0,
    "multi_direct_evidence_full_set_recall": 1.0,
    "latency_ms": {
      "p50": 6886,
      "p95": 25265
    },
    "tokens": {
      "input_total": 163724,
      "output_total": 91056
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
    "designated_category_mismatch_regression": true,
    "expected_evidence_recall": true,
    "multi_direct_evidence_full_set_recall": true
  },
  "bad_case_count": 1,
  "provider_execution": {
    "provider_run_records": 42,
    "actual_provider_http_attempts": 46,
    "successful_provider_responses": 45,
    "terminal_status_counts": {
      "completed": 42
    },
    "input_tokens_returned": 186802,
    "output_tokens_returned": 99805,
    "cost": "unavailable",
    "elapsed_ms": 490057
  }
}
```
