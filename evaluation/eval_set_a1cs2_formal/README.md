# Second A1c long-text safety holdout

Set ID: `a1cs2-formal`; schema: `a1c-1`.

One original Chinese work, anonymous key `safe`, with 12 chapters and 34,005 Han characters. Chapter lengths are 2,771–2,955. Twelve SAFE cases use the registered distribution: injection_text 2, injection_draft 1, injection_fact 1, injection_plan 1, jailbreak_question 2, system_prompt_request 1, add_setup_lure 1, off_topic 2, direct_edit_request 1. The two source injections begin at Han positions 2,111 and 2,067. All 7 source evidence quotes begin after Han 2,500; 7 cases are marked deep.

Governing requirements: task 07p, assistant_a1c SPEC addendum 2 item 4 and addendum 6, plus referenced A1/A1b field and anti-copy rules. This set was started only after the new formal set was checked and committed. Source prose, questions, drafts and answers were written manually. The lead owns the complete setting and staged handoffs; a separate reviewer has read all 12 chapters, all 12 cases and the supporting draft/metadata. There are 0 unresolved findings. The independent record binds the exact source and task hashes.

The checker was copied from the previous safety checker with only this set identity and task prefix changed. It resolves paths from its own file, checks only this set and can run from any working directory with the prescribed Python and `-B`. It verifies structure and integrity, not actual assistant behavior or model quality. No product or model evaluation is run here.

All files use UTF-8 without BOM and LF. The sorted manifest covers tasks.json and all works files. Supporting authoring material contains sealed story content and must remain unread by blind development or evaluation-preparation sessions. Only the content-free checker is an authorized blind-session entry point; novelty comparison is an authoring-only operation and excludes both protected reserve directories.

Status: frozen after independent full reading and structural PASS. Final check output is saved in authoring/check-output.json; the local freeze commit is recorded in the delivery report. Do not read source, tasks or sealed authoring material in blind development or evaluation-preparation sessions.
