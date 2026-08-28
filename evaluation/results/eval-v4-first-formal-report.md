# Evaluation formal report

Status: **gate passed**

```json
{
  "metrics": {
    "confusion_matrix": {
      "conflict": {
        "conflict": 5,
        "no_conflict": 0,
        "insufficient_evidence": 0
      },
      "no_conflict": {
        "conflict": 0,
        "no_conflict": 5,
        "insufficient_evidence": 0
      },
      "insufficient_evidence": {
        "conflict": 0,
        "no_conflict": 0,
        "insufficient_evidence": 5
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
    "latency_ms": {
      "p50": 2593,
      "p95": 4104
    },
    "tokens": {
      "input_total": 16037,
      "output_total": 2183
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
    "fail_closed_safety_paths": true
  },
  "bad_case_count": 2
}
```
