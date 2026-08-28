from __future__ import annotations

from collections import Counter
from typing import Any


CLASSES = ("conflict", "no_conflict", "insufficient_evidence")


def prediction_for_target(run: dict[str, Any], ordinal: int) -> tuple[str, dict[str, Any] | None]:
    target = [item for item in run.get("issues", []) if item.get("claim_span_id", "").endswith(f"-{ordinal}")]
    if any(item.get("classification") == "conflict" for item in target):
        return "conflict", next(item for item in target if item.get("classification") == "conflict")
    if any(item.get("classification") == "insufficient_evidence" for item in target):
        return "insufficient_evidence", next(item for item in target if item.get("classification") == "insufficient_evidence")
    return "no_conflict", target[0] if target else None


def _prf(matrix: dict[str, dict[str, int]], label: str) -> dict[str, float]:
    tp = matrix[label][label]
    fp = sum(matrix[other][label] for other in CLASSES if other != label)
    fn = sum(matrix[label][other] for other in CLASSES if other != label)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def aggregate(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = {expected: {predicted: 0 for predicted in CLASSES} for expected in CLASSES}
    for result in case_results:
        matrix[result["expected_class"]][result["predicted_class"]] += 1
    total = len(case_results)
    per_class = {label: _prf(matrix, label) for label in CLASSES}
    no_conflict_total = sum(matrix["no_conflict"].values())
    metrics = {
        "confusion_matrix": matrix,
        "accuracy": sum(matrix[label][label] for label in CLASSES) / total if total else 0.0,
        "macro_f1": sum(per_class[label]["f1"] for label in CLASSES) / len(CLASSES),
        "conflict": per_class["conflict"],
        "no_conflict_false_positive_rate": (no_conflict_total - matrix["no_conflict"]["no_conflict"]) / no_conflict_total if no_conflict_total else 0.0,
        "insufficient_evidence_recall": per_class["insufficient_evidence"]["recall"],
        "retrieval_expected_evidence_hit_at_5": sum(bool(item["retrieval_hit_at_5"]) for item in case_results) / total if total else 0.0,
        "cited_evidence_precision": _ratio(sum(item["cited_evidence_expected_count"] for item in case_results), sum(item["cited_evidence_count"] for item in case_results)),
        "evidence_resolvability_grounding": _ratio(sum(item["resolvable_evidence_count"] for item in case_results), sum(item["cited_evidence_count"] for item in case_results), zero_value=1.0),
        "schema_validity": sum(bool(item["schema_valid"]) for item in case_results) / total if total else 0.0,
        "latency_ms": percentile_summary([item.get("latency_ms") for item in case_results]),
        "tokens": {"input_total": sum(item.get("input_tokens") or 0 for item in case_results), "output_total": sum(item.get("output_tokens") or 0 for item in case_results)},
        "cost": "unavailable" if any(item.get("cost_cny") is None for item in case_results) else sum(item["cost_cny"] for item in case_results),
    }
    return metrics


def _ratio(numerator: int, denominator: int, zero_value: float = 0.0) -> float:
    return numerator / denominator if denominator else zero_value


def percentile_summary(values: list[int | None]) -> dict[str, int | None]:
    clean = sorted(item for item in values if isinstance(item, int))
    if not clean:
        return {"p50": None, "p95": None}
    return {"p50": clean[round((len(clean) - 1) * 0.5)], "p95": clean[round((len(clean) - 1) * 0.95)]}


def stability(repeats: list[dict[str, Any]]) -> dict[str, Any]:
    def same(key: str) -> bool:
        return len({repr(item.get(key)) for item in repeats}) == 1
    return {"class_decision_stability": same("predicted_class"), "category_severity_stability": same("category_severity"), "evidence_id_set_stability": same("evidence_ids"), "exact_explanation_text_stability": same("explanation_sha256")}
