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

# Registered on 2026-09-30, before the next set exists and before any run of it. The numbers
# below are unchanged from the V11 reading, including insufficient_evidence_recall_min, which
# V11 failed twice (0.7500 and 0.6667). Keeping it is the point: V11 failed because the bar
# found a real defect, and lowering a bar a known defect sits under would retire the bar, not
# the defect.
PRE_REGISTRATION = {
    "registered_on": "2026-09-30",
    "applies_from": "the next held-out set authored after eval_set_v11_authoring",
    "decided_before_the_set_was_authored": True,
    "thresholds_unchanged_from_v11_reading": True,
    "protocol": {
        "runs_that_decide": 1,
        "run_shape": "one invocation of evaluation.v11_holdout.run with no --only; the first run decides",
        "infrastructure_retry": "a case whose terminal status is timed_out, or whose error_code is "
                                "provider_timeout, provider_unavailable or provider_error, is retried once and the "
                                "first attempt is recorded in infrastructure_retry; a contract, schema or budget "
                                "failure is the model's answer and is never retried",
        "denominator": "every authored case counts, including one that fails after its retry",
        "checkpoint": "per-case records are written after every case, so a failure in scoring cannot cost a run",
        "scoring": "nature-based; state_change scores as no_conflict. Untested: state_change appeared in zero of "
                   "the 72 V11 judgements, so this rule has never actually changed a result",
    },
}

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
            "pre_registered_for_v11": PRE_REGISTERED_FOR_V11, "pre_registration": PRE_REGISTRATION,
            "thresholds": THRESHOLDS,
            "checks": checks, "failed": failed, "unmeasured": unmeasured, "status": status}
