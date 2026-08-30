# Stage 11M implementation record

This implementation adds a separate 300k runner and validator. It preserves the
11L runner, validator, and v1-v6 evidence unchanged. The formal runner accepts
only the frozen 300k Unicode prefix, requires `deepseek-v4-pro`, sets transport
retry to zero, enforces a 92-request cap, and writes one redacted result only.

Before any provider request it verifies the 13-parent / 82-chunk / 81-batch
plan and the frozen normal and repair input budgets. During the one formal flow
it records stage wall times, SQLite sizes, aggregate provider tokens, HTTP,
repair/retry totals, and provider cost only when returned. It uses a fresh
isolated runtime and deliberately stores none of the source text, source path,
account, credentials, prompt, or raw provider body in the result.

The runner performs initialization, explicit core decisions and commit, then
two controlled original append chapters. Each append requires a completed
Continuity run and Memory Delta run before explicit core decisions and commit.
The validator reports evidence-contract validity only; it does not make a
product-Gate decision.

## Offline preflight record

The frozen input hash, character count, and UTF-8 byte count were verified.
The preflight uses the formal import filename and project title, invokes the
V2Database preview/commit/import path, and uses the frozen worst-case repair
context (`memory_type_invalid`, attempt 2, global attempt 5, field
`memory_type`, candidate ordinal 4). It made zero provider HTTP calls.

The formal runner is the authoritative preflight path. Its measured contract is
13 parent spans, 82 chunks, 81 batches, maximum normal input 5800, and maximum
worst-case repair input 5938. The Provider HTTP cap is therefore 92
(`81 + 5 + 6`). A prior 84/83 estimate came from a non-authoritative path that
bypassed the application import flow and is not used for this stage. At this
preflight checkpoint, no 11M `results.json` existed and no Provider request had
been made.

## Locked formal outcome

The one permitted formal run completed its workflow with the locked result
hash `01d8f38393651219620c1d35c20d730b0d42749762188db07278dc642d49c469`.
It used `deepseek-v4-pro`, made 88 HTTP calls with zero transport retries, and
completed the initialization plus both controlled incremental rounds. The
independent validator correctly returns false because final SQLite size is
4,329,459,712 bytes, exceeding the frozen 50 MiB capacity limit. This is a
completed measurement with a failed product Gate; the result and isolated
runtime are retained and must not be rerun or overwritten.

## Capacity repair V2

The V2 repair keeps full SourceSpan and Evidence text on the read endpoint but
stores bounded acknowledgements for initialization creation, candidate
decisions, and initialization commit. The product client uses `view=compact`
for writes and refreshes the current initialization through GET. Compatibility
full responses remain available without placing those views in the
idempotency ledger.

Offline capacity, API replay/conflict, backend, frontend, and browser gates
passed before the new formal run. The single V2 formal result is locked at
`22d5ee5d120b3fe7d874d0ba2a8b4b86ebf54bc7d6fff6c7e6a26fc289ad1d6a`.
It used `deepseek-v4-pro`, completed 90 HTTP calls with zero transport retries,
and finished at 4,820,992 SQLite bytes. The idempotency table is 139,264 bytes;
176 initialization decision responses have a maximum payload of 103 bytes.
The V2 validator returns true. The V1 failure result and runtime remain intact.
The optional 1M-character Stage 11N pressure test is not part of this record and
has not been run.
