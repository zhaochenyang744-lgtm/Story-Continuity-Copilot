# Third A1c long-text safety holdout

Set ID: `a1cs3-formal`; schema: `a1c-1`. One new Chinese work, 12 chapters of 2,500-3,500 Han characters, and 12 SAFE tasks. Registered safe_kind distribution: injection_text 2; injection_draft 1; injection_fact 1; injection_plan 1; jailbreak_question 2; system_prompt_request 1; add_setup_lure 1; off_topic 2; direct_edit_request 1.

The source follows a complete lead-authored bible and staged handoffs. Prose is manually authored; programs only serialize supplied literals and audit counts, overlaps, positions, bytes and hashes. Both source injections occur after Han position 1,500. Questions and gold answers are authored and checked by the lead after the relevant source exists. An author-independent full-text review is required before freeze.

The checker is copied from the second safety set with only set identity and task prefix changed. It resolves paths from its own file and checks only this directory. The sorted manifest covers tasks.json and all files under works/. Encoding is UTF-8 without BOM, with LF endings.

After delivery this set and all authoring materials are sealed. Blind development, debugging and formal-run preparation may run check.py only. Static PASS establishes structure and integrity, not model behavior, semantic acceptance or actual FIX detection. No product run, evaluation run or provider call belongs to this authoring task.

Frozen structure: 12 chapters, 34,678 source Han characters, chapter range 2,821-2,971; 12 SAFE tasks. Eight source evidence quotes are unique and begin after Han position 2,500. The two source injections start at 2,038 and 1,966. The shared draft contains 953 Han characters. Metadata uses the registered extra_facts field.

An author-independent reviewer completed all 12 chapters, the shared draft and all 12 tasks. The source and task byte hashes are recorded in authoring/independent-review.json and bound into authoring/self-review.json. One structural field-name finding was corrected and independently rechecked; unresolved findings: 0. The author ledger preserves the writer's handoff snapshot; the independent record is the completed review authority.

Status: frozen.
