# Model comparison V8

This is a development comparison of 34 previously seen business inputs under three explicit conditions: Flash thinking disabled (`temperature=0`), Flash thinking enabled/high, and Pro thinking enabled/high. It uses the exact V7 prepared requests, including claim IDs, selected source text, Memory and output schema, and the unchanged v17 prompt. Thinking conditions omit temperature; no condition sets top_p. All three use `max_tokens=32768`, so Flash-off is a new common-budget baseline. Historical V7 used 2000 and is context, not a substitute arm.

The user has authorized necessary Provider calls in this conversation. The controller will launch after independent technical acceptance and freezing. This implementation phase makes no real Provider calls and opens no database. Do not launch before that acceptance. One serial process only; no resumption or overwrite of an occupied run identity.

## Commands

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
.venv\Scripts\python.exe -B -m unittest evaluation.model_compare_v8.test_offline -v
.venv\Scripts\python.exe -B -m evaluation.model_compare_v8.replay --output offline-replay-01.json
.venv\Scripts\python.exe -B -m evaluation.model_compare_v8.harness prepare --run-id prep-v8-01
```

The last two commands create new evidence and refuse overwriting it. After controller review, freeze once and record the printed hash independently:

```powershell
.venv\Scripts\python.exe -B -m evaluation.model_compare_v8.freeze freeze
$v8ManifestHash = (Get-FileHash evaluation/model_compare_v8/frozen-inputs.json -Algorithm SHA256).Hash.ToLowerInvariant()
.venv\Scripts\python.exe -B evaluation/model_compare_v8/live_guard.py --run-id model-compare-v8-20260927-01 --manifest-sha256 $v8ManifestHash --verify-only
.venv\Scripts\python.exe -B evaluation/model_compare_v8/live_guard.py --run-id model-compare-v8-20260927-01 --manifest-sha256 $v8ManifestHash
```

The direct guard checks manifest, every local dependency including `evaluation/__init__.py`, and installed runtime hashes before importing product modules. The API key comes only from the existing `CONTINUITY_API_KEY` environment variable at live launch; no `.env` files, headers, or keys are written. Do not import the harness directly to bypass the guard. `freeze.py` has its own V8 closure and never asks old freezes to accept changed product hashes.

## Execution and accounting

Schedule is case-major with rotating order: off/high/pro, high/pro/off, pro/off/high, repeated across 34 cases. There are 102 condition-cases, at most two contract evaluations each, at most one transport retry per evaluation, and hard ceilings of 408 POST plus one models GET. GET checks both requested model IDs and saves only safe model metadata. HTTP 400/401/402/403/404/422 stops the matrix immediately. Two consecutive condition-cases with any service/transport error also stop it.

Before every POST, including retries, write an admission receipt and check both POST and known-token caps. At 1,500,000 known actual total tokens no further request is dispatched. The last response may overshoot the remaining allowance; this is a stop threshold, not a reservation estimate. Any unknown, partial, invalid or missing total usage stops before all later dispatches, including a nominal retry. Thus a timeout normally stops without retry because its dispatched usage is unknown. A known-usage 429/5xx may retry once if both caps permit it. Aggregate actual usage across those attempts for ProviderResult / ProviderInvalidJson; observed fields describe the last response. The matrix ledger and per-attempt receipts remain the authoritative accounting even when engine execution terminates before aggregation.

Only during `engine.execute`, a non-reentrant context asserts the original `MAX_RUN_TOKENS=8000`, temporarily sets 40000, then restores 8000 in `finally`. No product file changes, zeroed usage, or simulated usage. The original 6000 input estimate limit, full feedback, original validator and one repair remain active. The 40000 check applies to returned evaluation usage (including known retry usage), and may still be exceeded. It does not guarantee that any response will pass the budget gate.

Each response records actual input/completion/total tokens, whether it fits original 8000 or experimental 40000, latency and finish reason. Missing usage is unknown, never zero. Reasoning tokens are a completion subcount and are not added again. Missing detail remains null; an invalid detail is flagged and left unavailable without stopping an otherwise complete total. Pricing is unknown unless the API explicitly reports a cost; no estimated price is invented. The configured 120 seconds is an HTTPX phase/read-wait timeout, not a 120-second wall-clock guarantee.

## Evidence and scoring

Prepare: `runs/prep-v8-01/cases/01/flash-off/{input,wire}.json`, repeated for 34 cases × three arms. Live: `runs/<new-id>/cases/01/flash-off/` contains:

- `trial-start.json`, `trial-finish.json`: identity, limits, engine restoration.
- `requests/01.json`, `wire/01.json`: complete business request and HTTP JSON body before dispatch. `02` is a repair.
- `attempts/01-start.json`, `01-finish.json`: admission and actual response projection; transport attempts have independent ordinals.
- `evaluations/01.json`: parsed visible answer or parse/transport failure, linked to the business request.
- `engine-final.json`, `scores.json`: experimental engine delivery and separate first/repair/final machine layers. Independent semantic judgment stays pending.

No hidden `reasoning_content` is persisted: only presence, character/byte length, SHA-256 and reported reasoning-token count. Visible content is retained in full. Repair is produced by the original engine from visible rejected issues/verdicts and diagnostics. It never uses hidden reasoning. `finish_reason != stop`, including valid JSON ending with `length`, cannot count as a complete pass and has a separate generation label. Scorer exceptions are captured as `score_error`, preserving raw evidence and trial completion; they do not become business passes or disappear as unrun trials.

Final output is the experimental engine result, not an API/database-persisted product. The adapter removes persistence-only checks such as database evidence IDs and persisted excerpt/revision fields, retaining gold, categories, selected references, minimum evidence sets, roles and temporal rules. All 34 historical V7 request/response chains are replayed with their own historical claim IDs. Offline parity requires exactly the original 19 final passes and identical per-case failure reasons; this is adapter validation, not a new model score. Original-8000 compatibility is per-response usage evidence, not a production end-to-end retest.

Run summary retains every finished and not-run condition-case, per-condition coverage and the common paired set. Formal semantic criteria and model-blinded packets are owned by the independent acceptance directory and pinned by the freeze. First raw answers are the primary capability endpoint; repair and experimental final delivery are distinct. These seen development inputs cannot establish blind-test generalization or statistical significance.

API semantics: [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/), [chat completion fields](https://api-docs.deepseek.com/api/create-chat-completion/), [model metadata](https://api-docs.deepseek.com/api/list-models/), [HTTPX timeout semantics](https://www.python-httpx.org/advanced/timeouts/).
