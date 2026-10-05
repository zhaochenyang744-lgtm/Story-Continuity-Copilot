# Aborted by the controller

Stopped deliberately on 2026-09-28 after 18 of 108 condition-cases (20 generation POSTs). The process was killed, so `summary.json` and `not-run.json` were never written; every per-trial file written before the stop is retained unchanged.

Reason: while this run was in progress, the full backend suite showed that the v19 category rule made the continuity prompt about 900 characters longer and pushed near-budget long-form requests over the 6,000-unit input budget (5 new `input_budget_exceeded` test failures, zero Provider calls in those tests). The v19 prompt is therefore not shippable, and its results would not describe a releasable product. The rule is being rewritten under a budget-neutral length and re-frozen under a new version and run identity.

These partial results are not scored, compared, or reused.
