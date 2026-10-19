# Third A1c long-text formal holdout

Set ID: `a1c3-formal`; schema: `a1c-1`.

Target structure: 2 Chinese works, anonymous keys w01 and w02; 30 chapters each, 2,500-3,500 Han characters per chapter; 30 tasks, 15 per work. Registered per-work distribution: answerable_single 2, answerable_multi 3, not_in_text 2, conflicting 2, RECAP 2, FIX 2, follow_up 2.

Governing requirements: task 07r; assistant_a1c SPEC sections 1-3, addenda 1, 2 item 4, 6 item 14 and 8 item 21; referenced A1/A1b schema, copy and narration rules. Prose is written chapter by chapter from a lead-authored story bible, with staged continuity handoffs. Questions and gold answers belong to the lead. Independent full reading is required before freeze.

The checker is copied from the second formal set with set identity and task prefix changed. It resolves paths from its own file and checks this directory only. Run with the prescribed Python and `-B` from any current directory. Static PASS establishes structure and integrity; it does not establish model behavior, semantic acceptance or actual FIX detection.

The sorted manifest covers tasks.json and every file under works/. Files use UTF-8 without BOM and LF. Story bibles, handoff ledgers and self-review are sealed content. After delivery, blind development and preparation sessions may run check.py only, and must not read source, tasks or authoring materials. The task's 3 prohibited directories are not read by authoring novelty audits.

Final source structure: w01 has 30 chapters and 84,152 Han characters (2,513-2,969 per chapter); w02 has 30 chapters and 87,018 Han characters (2,526-3,115 per chapter). Each has 15 tasks and 7 deep answerable/follow-up tasks. There are 4 QA selections and 3 FIX categories across the set.

Independent review completed all 60 chapters, both shared drafts and all 30 tasks, including all 4 follow-up first questions. Unresolved unintended conflicts and gold/evidence errors: 0. Source and task SHA-256 values are bound in authoring/independent-review.json and self-review.json. The 4 intentional contradiction pairs remain protected.

Status: frozen for the third formal run after the final structural PASS. This is an authoring and static-integrity delivery, with no product run, evaluation run or provider call.
