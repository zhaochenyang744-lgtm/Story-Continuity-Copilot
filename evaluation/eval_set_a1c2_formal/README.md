# Second A1c formal holdout

Set ID: `a1c2-formal`; schema: `a1c-1`.

Two independently conceived original Chinese works, anonymous keys `w01` and `w02`, each with 30 chapters. The 30 tasks comprise 18 QA, four RECAP, four FIX and four follow-up tasks, with the required distribution applied to each work separately.

The governing documents are `evaluation/assistant_a1c/SPEC.md` sections 1–3, addenda 1 and 6, and its referenced A1/A1b field and anti-copy rules. No thresholds, product code or existing datasets are modified. The existing checker was copied with the new set identity and task prefix; it resolves paths from its own file and reads only this set.

The source is manually authored chapter by chapter. Scripts only support counts, repetition checks, quote positions, hashes, and structural validation. The central ledger records the author's initial setting and staged handoffs. Self-review records source evidence and an independent full-book review; automatic PASS establishes structure and integrity only.

Run `check.py` with the prescribed Python interpreter and `-B`, from any current directory. `set.sha256` covers `tasks.json` and all files under `works/`, ordered by relative path. Text is UTF-8 without BOM and uses LF.

After delivery, keep all story and task content sealed until the authorized formal run. Only the content-free checker may be run by development/review sessions that must remain blind. The additional novelty audit is an authoring operation, not a blind-session entry point. It excludes both explicitly protected reserve directories; no claim is made about their unread content.

Status: frozen after structural PASS and an independent full reading of 60 chapters and 30 tasks. Eight review findings were resolved and the affected chapters reread. Source and task hashes are bound in the independent record. This is authoring acceptance only; no product or model evaluation has been run.
