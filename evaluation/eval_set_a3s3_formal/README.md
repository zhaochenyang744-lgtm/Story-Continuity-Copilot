# A3 supplementary safety set

- Set ID: `a3s3-formal`; version: `a3-1`.
- 1 Chinese work, 12 chapters, 10 injection tasks.
- Long-task modes: `trace` and `thread_audit` only; no `tidy` or route tasks.
- Materials are 1-based arrays. Quotes and author replies are authoring/scoring metadata, not assistant instructions.
- Contract: task 35, task 33 safety-set requirements, and A3 SPEC addendum 5. Earlier contradictory size and protocol statements yield to addendum 5.
- One canonical narrative file: `works/w01.md`. The next chapter opening is stored only in `works[].shared_draft`.
- `set.sha256` covers `tasks.json`, all narrative files, and all material files. Independent review records bind the same data and the self-review and novelty snapshots.
- The checker uses the Python standard library, reads this directory only, and emits identifiers and counts. It does not run the product or any model or evaluation.

From the designated repository root:

```
..\story-continuity-copilot\.venv\Scripts\python.exe -X utf8 -B -m evaluation.eval_set_a3s3_formal.check
```

An absolute path to `check.py` also works from another directory. After delivery this set is sealed. A static PASS checks the declared contract and bindings; it is not a release-gate result or a model-quality claim. The supplementary run requires three passes and the registered safety checks; those runs are outside this authoring task.
