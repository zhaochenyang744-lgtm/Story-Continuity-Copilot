"""Registered pass/fail thresholds for the V11 held-out format and every set after it.

These are V10's REQUIRED_THRESHOLDS carried over unchanged, by the user's decision on
2026-09-30, after the V11 first formal run had already been seen. Recording that honestly
matters more than the numbers: for V11 itself they were not pre-registered, so the V11
result is measured against a bar taken from an earlier set rather than one agreed in
advance. From the next held-out set on, this file is the pre-registered bar, and changing
a number here before a run is a decision to be dated and explained the way the V10 citation
precision change was.

The V11 scoring change is not reflected in these numbers and should be weighed when reading
a result. V10 scored an issue by its status, so a state_change counted as a conflict. V11
scores by nature, so a state_change counts as no_conflict. Against the same answers that
can only lower conflict recall and only improve the no_conflict false-positive rate, so
these two thresholds are not strictly comparable across the two formats.

`conflict_category_accuracy` and the designated-regression requirement apply to the three
cases flagged `designated_regression`, which must come back as conflict with the authored
category, through nature confirmed_conflict.
"""
from __future__ import annotations

from typing import Any

REGISTERED_ON = "2026-09-30"
CARRIED_OVER_FROM = "evaluation/build_v10_formal_assets.py REQUIRED_THRESHOLDS"
PRE_REGISTERED_FOR_V11 = False

THRESHOLDS = {
    "macro_f1_min": 0.8,
    "conflict_recall_min": 0.8,
    "insufficient_evidence_recall_min": 0.8,
    "no_conflict_false_positive_rate_max": 0.2,
    "conflict_category_accuracy_min": 0.75,
    "designated_regression_required_correct": 3,
}


def evaluate(metrics: dict[str, Any]) -> dict[str, Any]:
    """Apply the registered bar to a run's metrics; missing inputs are None, never a pass."""
    per_class = metrics.get("per_class") or {}
    designated = metrics.get("designated") or {}

    def recall(label: str) -> float | None:
        entry = per_class.get(label)
        return entry.get("recall") if isinstance(entry, dict) else None

    def check(value: float | int | None, bar: float | int, compare: str) -> bool | None:
        if value is None:
            return None
        return value >= bar if compare == "min" else value <= bar

    checks = {
        "macro_f1": check(metrics.get("macro_f1"), THRESHOLDS["macro_f1_min"], "min"),
        "conflict_recall": check(recall("conflict"), THRESHOLDS["conflict_recall_min"], "min"),
        "insufficient_evidence_recall": check(recall("insufficient_evidence"), THRESHOLDS["insufficient_evidence_recall_min"], "min"),
        "no_conflict_false_positive_rate": check(metrics.get("no_conflict_false_positive_rate"), THRESHOLDS["no_conflict_false_positive_rate_max"], "max"),
        "conflict_category_accuracy": check(metrics.get("conflict_category_accuracy"), THRESHOLDS["conflict_category_accuracy_min"], "min"),
        "designated_regressions": check(designated.get("class_and_category_correct"), THRESHOLDS["designated_regression_required_correct"], "min"),
    }
    failed = sorted(name for name, ok in checks.items() if ok is False)
    unmeasured = sorted(name for name, ok in checks.items() if ok is None)
    status = "failed:" + ",".join(failed) if failed else "unmeasured:" + ",".join(unmeasured) if unmeasured else "passed"
    return {"registered_on": REGISTERED_ON, "carried_over_from": CARRIED_OVER_FROM,
            "pre_registered_for_v11": PRE_REGISTERED_FOR_V11, "thresholds": THRESHOLDS,
            "checks": checks, "failed": failed, "unmeasured": unmeasured, "status": status}
