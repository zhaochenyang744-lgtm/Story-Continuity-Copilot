# Current Flash V5 engineering handoff

Status: **prepared for controller technical review**. This handoff does not authorize a live Provider dispatch and makes no model-quality or user-acceptance claim.

## Identity and frozen materials

- Git baseline: `7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`; branch `codex/legacy-gap-repair`.
- Freeze file: `evaluation/current_flash_v5/frozen-inputs.json`, SHA-256 `aabea4b8f99d2d4282ed627e98da98a57e46a1c526a7a45064af22acfd87682b`.
- Frozen source includes the ordered 30-case matrix, V5 runner/journal/scorer/tests/plan, current product and fixture dependencies, V2 corpora and captures, V3/V4 inputs, and final offline preparation evidence. The manifest hashes 30 isolated SQLite databases through `runs/prep-v5-03/workspace-manifest.json`.
- Verify without dispatch: `.\.venv\Scripts\python.exe -m evaluation.current_flash_v5.freeze verify`.
- Existing V1–V4 and G02 evidence, protected controller snapshot, product code, and real author workspace were not edited. V5 source and preparation evidence are new untracked files; isolated SQLite is under ignored `artifacts/current_flash_v5`.

## Preparation evidence

- `.\.venv\Scripts\python.exe -m unittest evaluation.current_flash_v5.test_offline -v`: 7 tests passed. The tests use mock HTTP and synthetic SQLite, including pre-dispatch snapshots, malformed visible content, timeout/usage accounting, G02 database binding, malformed parseable product continuation, and scoring boundaries.
- `evaluation/current_flash_v5/runs/prep-v5-03/summary.json`: 30 of 30 logical cases completed in stub mode; 30 same-run request/input audits and 30 isolated database bindings. Generation POST starts, completed transport attempts, HTTP responses, and `/models` GET starts are all zero.
- The 24 comparison requests were built through the current API and checked against V2 capture with only ephemeral claim identity normalized. The six G02 cases were built through the current API and checked against saved draft, selected SourceSpan/chapter revision, Memory, and the isolated database. Long-body counts are 180 available, 8 selected, 172 unselected; dialogue has two complete attributed quotes.
- The G02 teaching seed has empty parent chapter bodies and populated synthetic SourceSpans. The evidence binds parent identity/revision and selected SourceSpan text; it does not establish a full-chapter prose source chain.

## Live execution contract for the controller

After technical review, a later explicit live instruction may use a **fresh** run ID, for example:

```powershell
.\.venv\Scripts\python.exe -m evaluation.current_flash_v5.run live --run-id flash-v5-01
```

The run ID reserves result and workspace directories create-only before reading fixtures or `CONTINUITY_API_KEY`. Do not reuse an ID after an attempt-start record; remote receipt may be unknown. The live command verifies the freeze, then allows at most 24 comparison plus six G02 logical inputs, 108 generation POST attempts and one `/models` GET. It uses the existing `deepseek-flash` settings and only the named process environment key; no `.env` read or write is part of V5.

Every evaluation, including a contract repair, saves a business request snapshot before HTTP. Each transport attempt saves a durable start record before `client.post`, then a finish record with safe visible `message.content`, status, and classified usage when observed. This separates logical cases, evaluations, transport attempts, responses, and unknown remote receipt. Raw first response, repair response, and final persisted product remain distinct. Usage totals stay null unless complete for every observed attempt. HTTP 400/401/403/404 stops immediately; two consecutive logical cases with service errors stop the run.

The V3 accepted comparison scorer handles raw and final layers; G02 machine checks cover citation identity binding. G02 semantic support for each item/summary and the V3 declared category variant require human adjudication after real responses. A completed live run is therefore evidence for independent answer review, not a quality pass by itself.

No real Provider call was made during this preparation. The cumulative prior ledger remains 63 generation POST plus three `/models` GET, with 185382 input and 20686 output tokens; V5 adds zero to those totals.
