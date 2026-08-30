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
        "conflict": 1,
        "no_conflict": 1,
        "insufficient_evidence": 6
      }
    },
    "accuracy": 0.9166666666666666,
    "macro_f1": 0.9131652661064426,
    "conflict": {
      "precision": 0.8888888888888888,
      "recall": 1.0,
      "f1": 0.9411764705882353
    },
    "no_conflict_false_positive_rate": 0.0,
    "insufficient_evidence_recall": 0.75,
    "retrieval_expected_evidence_hit_at_5": 1.0,
    "cited_evidence_precision": 1.0,
    "evidence_resolvability_grounding": 1.0,
    "schema_validity": 1.0,
    "conflict_category_accuracy": 0.75,
    "designated_category_mismatch_regression": {
      "correct": 2,
      "total": 3
    },
    "expected_evidence_recall": 0.75,
    "multi_direct_evidence_full_set_recall": 0.5,
    "latency_ms": {
      "p50": 1531,
      "p95": 2655
    },
    "tokens": {
      "input_total": 26671,
      "output_total": 3246
    },
    "cost": "unavailable"
  },
  "gate_checks": {
    "macro_f1": true,
    "conflict_recall": true,
    "insufficient_evidence_recall": false,
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
  "bad_case_count": 4,
  "provider_execution": {
    "provider_run_records": 30,
    "actual_provider_http_attempts": 30,
    "successful_provider_responses": 30,
    "terminal_status_counts": {
      "completed": 30
    },
    "input_tokens_returned": 33002,
    "output_tokens_returned": 4161,
    "cost": "unavailable",
    "elapsed_ms": 66304
  }
}
```
