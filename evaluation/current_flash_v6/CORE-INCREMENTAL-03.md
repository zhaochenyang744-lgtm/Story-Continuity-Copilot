# V6 provenance schema version correction

During V6 runner wiring, the continuity provenance still identified the provider-facing response schema as `continuity-issue-v5-temporal-basis` even though V6 requires a per-claim verdict ledger. It now identifies `continuity-issue-v6-joint-evidence-coverage`. This is a metadata correction in `ContinuityEngine.provenance`; the Issue database fields and G02 analysis path are unchanged. It supersedes the previous engine hash for independent acceptance.

Current engine SHA-256: `527f986d6441aa226f239a0e67d928200f26d77b6b90e65cbc6d14e512d7fd39`. Provider and V6 test hashes remain as recorded in `CORE-INCREMENTAL-02.md`. The same targeted offline command reports **42 tests, 0 failures/errors**. No Provider HTTP or real database access occurred.
