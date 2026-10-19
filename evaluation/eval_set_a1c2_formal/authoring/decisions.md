# Authoring decisions

- Source prose, shared drafts, questions and gold answers are manually composed. The lead owns settings and question design; each source writer receives a five-chapter handoff. The reviewer has not authored source prose.
- Numeric chapter references in the sealed design ledger are authoring locators. Final chapter titles and Han positions are bound to the actual source; no narrative text is synthesized from these locators.
- Count evidence positions by the first Han character of an exact unique quotation, one based, excluding the heading. Deduplicate by work, chapter and exact quote for the formal set, matching its checker.
- Apply the 1,500-position and 2,500-position ratios separately to each work. Interpret the latter as at least one third of all evidence quotes, rather than one third of only the deep subset.
- Count the required deep quota using answerable QA and follow-ups only; conflicting QA may have deep evidence but cannot substitute for this quota.
- Every multi-chapter question must need both cited chapters. A large chapter gap alone is insufficient. Final answers follow the actual prose; mismatching question designs are corrected instead of inserting convenient source summaries.
- The novelty comparison covers all permitted evaluation text files, including nonstandard dataset directory names, fixtures and historical results. Both explicitly forbidden reserve directories and the two new sets are pruned before traversal or reads. Symlinks and junctions are not followed. A zero overlap result is limited to that permitted corpus; the final cross-new-set comparison is recorded separately.
- Structural PASS, author self-review, independent full-book review and actual model evaluation are separate claims. No model evaluation is run by this task.
- Only tasks.json and works files belong to the sorted manifest. Supporting ledgers remain sealed with this set. Protected source/configuration hashes are compared against the initial snapshot before each commit.
