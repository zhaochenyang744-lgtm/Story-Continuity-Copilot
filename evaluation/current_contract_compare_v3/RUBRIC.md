# Current-contract comparison V3 rubric

V3 is a small, **seen-development metadata and scoring revision** of frozen V2. It does not introduce new stories, draft text, corpus, capture, API outcome, or real Provider call. It reads the exact V2 capture file and 26 saved synthetic API records by SHA-256. Each saved API request equals its captured business input after normalizing the ephemeral claim ID. It records a new offline rescore under a create-only run identity. V1 and V2 remain frozen.

## Gold changes

The Mira door conflict draft already states that she wore only a red badge. The blue-only door rule is therefore the single minimum source; the same-time roster is optional corroboration. `expected_evidence`, `requires_all_expected_evidence`, and `label_reason` are aligned with that minimum.

The eight insufficiency questions receive **their own** `decision_category` and rationale, separate from `category_axis`. The policy follows the core-decision definitions in the current `backend/app/provider.py`. The categories in axis order are: badge holder → `object_state`; cap actor → `relationship`; Sera's authorization → `relationship`; telegram courier → `relationship`; twin birth order → `timeline`; Tala's responsibility → `relationship`; lens grinder → `relationship`; east-pier companion → `location_action` with `relationship` as a declared human-adjudication variant. The courier's role is not automatically a knowledge question merely because Sera learned the code. A category accepted by the product validator is not by itself gold. The companion variant is structurally allowed but remains `pending_manual_adjudication`.

Each case now has `case_time_scope` containing its exact draft and minimum source text plus a case-specific note. The former V2 `time_scope` wording is retained only as `axis_time_context`; it is not a claim about every draft in the triplet.

## Score layers

`score_raw_one` applies frozen V2's targeted source/time checks, adds Evidence-chain completeness, insufficiency `missing_link`, no edit action, no proposed Memory change, and known source-bound Memory IDs. It separately calls the current `ContinuityEngine.validate` on the raw payload and reports `full_validator_result`. A raw machine pass requires both; it is still only contract/declared-gold structure, with narrative meaning pending manual review.

`score_one` reuses the frozen V2 final-product check with V3 gold metadata. It verifies against the **same run's** captured business request. First raw, repair raw if present, and final product remain distinct. The saved V2 batch has no repair response; V3 does not manufacture one.

The V3 offline rescore is intentionally historical: it preserves seven old V2 script answers with old insufficiency categories as new `category_mismatch` failures. It does not silently rewrite those answers to appear correct. Separate in-memory controls set a category intentionally to test the new gold and product validator. Those controls are human-authored synthetic variants, not API runs or model outputs. The companion category candidates still require a human judgment for any claim of category correctness.

## Output identity and audit boundary

`run.py` and `controls.py` reserve `runs/<run-id>` with `mkdir(exist_ok=False)` **before** reading captures, fixture material, or saved results. Every output is written with `open('x')`. Reusing a run ID fails before work and cannot replace a previous result. An exception after reservation writes `first-failure.json` once. The bounded tests verify this behavior in a temporary directory. The earlier V2 24-run/8-pass failure is only a documented summary; no original per-case failure file was found in the third-round bounded review, so V3 does not reconstruct one.

V3's machine scores are not model accuracy or independent semantic acceptance. Real Provider totals remain 63 generation POST + 3 `/models`, 185382 input and 20686 output tokens; V3 adds zero. No real Provider, product, database, author data, SMTP, environment, commit, push, merge, or deployment action is part of this revision.
