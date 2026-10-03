"""Pre-registered bar for the long-form formal set, approved by the user on 2026-10-04.

Drafted and approved on 2026-10-04, before any long-form set exists (no set authored, no
long-form run made). The numbers were approved unchanged from the draft. From here on, a number changes only before a run, dated and explained, as with
evaluation/v11_holdout/thresholds.py (which stays the bar for the short-text held-out set V13).

Protocol (same spirit as V11/V12): one formal run decides; a target is retried once only for an
infrastructure failure (terminal timed_out, or provider_timeout / provider_unavailable /
provider_error) and the first attempt is recorded; every authored target and point counts; no
replay; production price and concurrency. A run stopped by its budget cap fails the cost bar.

Scoring is by position and nature (see score.py): a labelled point is found when an issue
anchored on one of its sentences has the right class; confirmed_conflict and possible_conflict
are conflict; state_change is never a card.
"""
from __future__ import annotations

from typing import Any

DRAFTED_ON = "2026-10-04"
APPROVED = True
APPROVED_ON: str | None = "2026-10-04"
FORMAL_BUDGET_CNY = 25.0

QUALITY = {
    # Same bars as the short-text sets, now per labelled point inside ~2,500-character chapters.
    "conflict_recall_min": 0.80,               # 24 conflicts -> at least 20 found
    "insufficient_evidence_recall_min": 0.80,  # 12 gaps -> at least 10 reported as gaps
    "conflict_category_accuracy_min": 0.75,    # among conflicts found
    "designated_confirmed_required": 3,        # all 3 as confirmed_conflict with the right category
    "trap_false_positive_rate_max": 0.20,      # traps (consistent sentences that look suspicious)
    # New for long text: a card on no labelled point. Authors self-check for accidental
    # contradictions, so these bars allow some real-but-unplanned findings.
    "spurious_cards_per_target_max": 0.50,
    "clean_target_zero_card_rate_min": 0.70,
    # Completion: every target finishes and almost every sentence is decided.
    "completed_targets_all": True,
    "undecided_sentence_rate_max": 0.02,
}

COST_TIME = {
    # Single chapter (each formal target checked alone), production price 2.0/8.0 CNY per M tokens,
    # CONTINUITY_REVIEW_CONCURRENCY=4. Only the check is counted, not import or Memory setup.
    "single_chapter_median_seconds_max": 60,
    "single_chapter_p90_seconds_max": 90,
    "single_chapter_mean_cost_cny_max": 0.30,
    "single_chapter_max_cost_cny_max": 0.60,
    # Multi-chapter selections are measured in phase 5, once a real multi-chapter check exists,
    # on the formal set's selections (cost and time only; that run's quality is diagnostic).
    "selection_5_seconds_max": 180,
    "selection_5_cost_cny_max": 1.50,
    "selection_8_seconds_max": 270,
    "selection_8_cost_cny_max": 2.40,
}

# Targets for development, not gates: phase 3 retrieval and phase 4 screening are tuned on the
# dev set against these, offline and free.
DEV_TARGETS = {
    "retrieval_recall_all_evidence_at_10_min": 0.90,
    "screening_item_recall_min": 0.95,
    "screening_flagged_text_share_max": 0.40,
}

# Acceptance for the ~300,000-character import work; reported, never a gate.
IMPORT_ACCEPTANCE = {
    "whole_book_check_completes": True,
    "planted_item_recall_min": 0.70,
    "cost_cny_per_chapter_max": 0.30,
}


def evaluate(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the bar to a run report; a missing value is None, never a pass."""
    q = report.get("quality") or {}
    ct = report.get("cost_time") or {}
    single = ct.get("single_chapter") or {}

    def at_least(value, bar):
        return None if value is None else value >= bar

    def at_most(value, bar):
        return None if value is None else value <= bar

    timing_valid = ct.get("timing_valid") is True
    seconds, cost = single.get("seconds") or {}, single.get("cost_cny") or {}
    checks = {
        "conflict_recall": at_least(q.get("conflict_recall"), QUALITY["conflict_recall_min"]),
        "insufficient_evidence_recall": at_least(q.get("insufficient_evidence_recall"), QUALITY["insufficient_evidence_recall_min"]),
        "conflict_category_accuracy": at_least(q.get("conflict_category_accuracy"), QUALITY["conflict_category_accuracy_min"]),
        "designated": at_least((q.get("designated") or {}).get("confirmed_with_category"), QUALITY["designated_confirmed_required"]),
        "trap_false_positive_rate": at_most(q.get("trap_false_positive_rate"), QUALITY["trap_false_positive_rate_max"]),
        "spurious_cards_per_target": at_most(q.get("spurious_cards_per_target"), QUALITY["spurious_cards_per_target_max"]),
        "clean_target_zero_card_rate": at_least(q.get("clean_target_zero_card_rate"), QUALITY["clean_target_zero_card_rate_min"]),
        "completed_targets": None if q.get("targets") is None else q.get("completed_targets") == q.get("targets"),
        "undecided_sentence_rate": at_most(q.get("undecided_sentence_rate"), QUALITY["undecided_sentence_rate_max"]),
        "single_chapter_median_seconds": at_most(seconds.get("median"), COST_TIME["single_chapter_median_seconds_max"]) if timing_valid else None,
        "single_chapter_p90_seconds": at_most(seconds.get("p90"), COST_TIME["single_chapter_p90_seconds_max"]) if timing_valid else None,
        "single_chapter_mean_cost": at_most(cost.get("mean"), COST_TIME["single_chapter_mean_cost_cny_max"]),
        "single_chapter_max_cost": at_most(cost.get("max"), COST_TIME["single_chapter_max_cost_cny_max"]),
        "not_stopped_by_budget": report.get("stopped_early") is None,
    }
    return {"approved_bar": APPROVED, "checks": checks, "passed": APPROVED and all(value is True for value in checks.values())}


def evaluate_selections(report: dict[str, Any]) -> dict[str, Any]:
    """Phase-5 selection bar; a sequential sum is not a multi-chapter run and cannot pass."""
    ct = report.get("cost_time") or {}
    real = ct.get("selection_mode") == "together" and ct.get("timing_valid") is True
    checks = {}
    for row in ct.get("selections") or []:
        size = row.get("chapters")
        if size not in (5, 8):
            continue
        checks[row["id"]] = {
            "seconds": (row["seconds"] <= COST_TIME[f"selection_{size}_seconds_max"]) if real and row.get("seconds") is not None else None,
            "cost": (row["cost_cny"] <= COST_TIME[f"selection_{size}_cost_cny_max"]) if row.get("cost_cny") is not None else None,
        }
    return {"approved_bar": APPROVED, "checks": checks,
            "passed": APPROVED and bool(checks) and all(v is True for c in checks.values() for v in c.values())}
