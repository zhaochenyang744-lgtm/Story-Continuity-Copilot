# Evaluation formal report

Execution kind: **first_valid_formal**

Status: **gate_failed**

```json
{
  "metrics": {
    "confusion_matrix": {
      "conflict": {
        "conflict": 7,
        "no_conflict": 5,
        "insufficient_evidence": 0
      },
      "no_conflict": {
        "conflict": 0,
        "no_conflict": 12,
        "insufficient_evidence": 0
      },
      "insufficient_evidence": {
        "conflict": 0,
        "no_conflict": 2,
        "insufficient_evidence": 10
      }
    },
    "accuracy": 0.8055555555555556,
    "macro_f1": 0.8067088542470545,
    "conflict": {
      "precision": 1.0,
      "recall": 0.5833333333333334,
      "f1": 0.7368421052631579
    },
    "no_conflict_false_positive_rate": 0.0,
    "insufficient_evidence_recall": 0.8333333333333334,
    "retrieval_expected_evidence_hit_at_5": 0.9722222222222222,
    "cited_evidence_precision": 1.0,
    "evidence_resolvability_grounding": 1.0,
    "schema_validity": 0.8055555555555556,
    "conflict_category_accuracy": 0.5833333333333334,
    "designated_category_mismatch_regression": {
      "correct": 3,
      "total": 3
    },
    "expected_evidence_recall": 0.5555555555555556,
    "multi_direct_evidence_full_set_recall": 0.5,
    "latency_ms": {
      "p50": 8160,
      "p95": 28731
    },
    "tokens": {
      "input_total": 168079,
      "output_total": 81120
    },
    "cost": "unavailable"
  },
  "gate_checks": {
    "macro_f1": true,
    "conflict_recall": false,
    "insufficient_evidence_recall": true,
    "no_conflict_false_positive_rate": true,
    "retrieval_expected_evidence_hit_at_5": true,
    "cited_evidence_precision": true,
    "schema_validity": false,
    "evidence_resolvability_grounding": true,
    "fail_closed_safety_paths": true,
    "conflict_category_accuracy": false,
    "designated_category_mismatch_regression": true,
    "expected_evidence_recall": false,
    "multi_direct_evidence_full_set_recall": false
  },
  "bad_case_count": 7,
  "provider_execution": {
    "provider_run_records": 42,
    "actual_provider_http_attempts": 47,
    "successful_provider_responses": 43,
    "terminal_status_counts": {
      "completed": 35,
      "failed": 7
    },
    "input_tokens_returned": 192460,
    "output_tokens_returned": 88042,
    "cost": "unavailable",
    "elapsed_ms": 446801
  }
}
```
