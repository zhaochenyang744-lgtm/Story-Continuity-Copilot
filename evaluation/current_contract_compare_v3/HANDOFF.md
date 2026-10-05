# Current-contract comparison V3 handoff

**Status:** scoped R3-1 through R3-4 implementation and self-test complete; controller independent re-review and human semantic/category acceptance remain separate. V3 is an incremental seen-development revision. V1/V2 are unchanged.

## Delivered

- `cases.json`: 24 V2 successor IDs with unchanged story/draft/source inputs. The Mira red-badge conflict now needs only `badge_rule`; `badge_roster` is optional. All eight insufficiency questions have independent category rationale. The east-pier companion permits two declared category candidates only with `pending_manual_adjudication`. Per-case time scope is separate from the old axis context.
- `score.py`: new raw-first gate checks the five R3-3 omissions and calls the current complete product validator; final scoring reuses V2's capture-bound product checks. Raw first, repair if present, and final remain separate. Machine pass still leaves story semantics pending manual review.
- `runs/final-offline-rescore`: **offline** rescore of the exact frozen V2 capture file and 26 saved synthetic results. The saved per-run request equals the capture after ephemeral claim-ID normalization. Historical results are unchanged: 19/26 raw and 19/26 final structure passes under V3 gold; seven old insufficiency categories are recorded as mismatches. No repair response existed; none was fabricated. New API runs: zero.
- `runs/targeted-controls-02`: 20/20 in-memory controls. Badge-rule-only raw/final pass; eight revised insufficiency category controls pass; the companion's second declared category is structurally accepted but manually pending; both supported state changes pass. Five isolated raw contract mutations fail with their intended error and full product-validator rejection. Extra unrelated final Evidence, wrong insufficiency relation, and terminal failure are rejected. These are scripted controls, not model outputs or API runs.
- `run.py` and `controls.py`: reserve a unique run directory before reading input; write every output create-only. Repeat identity is rejected, and a post-reservation exception retains `first-failure.json`. `test_v3.py` verifies these behaviors in an isolated temporary directory.
- `HISTORY_GAP.md`: the V2 early 24-completed/8-pass first-response chain remains unverified beyond its written summary. V3 does not reconstruct it. `targeted-controls-01` is retained but superseded by `-02` for isolated negative-control evidence because its initial mutations had a category confound.

## Verification

V3 tests: 4/4 passed. V1, V2, and V3 `freeze.py verify`: passed. V3 freeze manifest SHA-256: `0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf`. The V3 runner additionally checked every file in the third-round 21-file V2 preservation list and the exact V2 cases/capture/saved-result hashes. The product code and V1/V2 protected files were not modified by V3.

No new real Provider call or synthetic API run was made. The real cumulative ledger remains 63 generation POST + 3 `/models`, 185382 input and 20686 output tokens. No product, prompt, real database, SMTP, `.env`/key, Agent or author research, commit, push, merge, or deployment action was performed.

**Next review:** assess the eight insufficiency category rationales, particularly the declared human-adjudication companion variant, and verify the single-rule minimum plus five raw-contract controls against this freeze. These structural results do not establish model accuracy, blind generalization, release readiness, or user acceptance.
