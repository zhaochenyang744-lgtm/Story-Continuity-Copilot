# Evaluation formal report

Status: **gate failed**

```json
{
  "metrics": {
    "confusion_matrix": {
      "conflict": {
        "conflict": 0,
        "no_conflict": 8,
        "insufficient_evidence": 0
      },
      "no_conflict": {
        "conflict": 0,
        "no_conflict": 8,
        "insufficient_evidence": 0
      },
      "insufficient_evidence": {
        "conflict": 0,
        "no_conflict": 8,
        "insufficient_evidence": 0
      }
    },
    "accuracy": 0.3333333333333333,
    "macro_f1": 0.16666666666666666,
    "conflict": {
      "precision": 0.0,
      "recall": 0.0,
      "f1": 0.0
    },
    "no_conflict_false_positive_rate": 0.0,
    "insufficient_evidence_recall": 0.0,
    "retrieval_expected_evidence_hit_at_5": 1.0,
    "cited_evidence_precision": 0.0,
    "evidence_resolvability_grounding": 1.0,
    "schema_validity": 0.0,
    "conflict_category_accuracy": 0.0,
    "designated_category_mismatch_regression": {
      "correct": 0,
      "total": 3
    },
    "expected_evidence_recall": 0.0,
    "multi_direct_evidence_full_set_recall": 0.0,
    "latency_ms": {
      "p50": null,
      "p95": null
    },
    "tokens": {
      "input_total": 0,
      "output_total": 0
    },
    "cost": "unavailable"
  },
  "gate_checks": {
    "macro_f1": false,
    "conflict_recall": false,
    "insufficient_evidence_recall": false,
    "no_conflict_false_positive_rate": true,
    "retrieval_expected_evidence_hit_at_5": true,
    "cited_evidence_precision": false,
    "schema_validity": false,
    "evidence_resolvability_grounding": true,
    "fail_closed_safety_paths": true,
    "conflict_category_accuracy": false,
    "designated_category_mismatch_regression": false,
    "expected_evidence_recall": false,
    "multi_direct_evidence_full_set_recall": false
  },
  "bad_case_count": 24
}
```
