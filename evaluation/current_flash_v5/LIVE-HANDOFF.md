# Current Flash V5 live run handoff

Run `flash-v5-20260927-01` completed on 2026-09-27 UTC. This is the one authorized fixed 30-case live matrix. The result is **pending independent and manual review**; it is not a model-quality, user-acceptance, or release pass.

## Identity and immutable inputs

- Git baseline: `7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`.
- V5 frozen manifest SHA-256: `aabea4b8f99d2d4282ed627e98da98a57e46a1c526a7a45064af22acfd87682b`.
- Controller dependency supplement SHA-256: `bcc424e1a372b1e98b1d81d00f368e94075613ab559b1fceb68c7681c371747b`.
- The controller guard verified the unique identity and 280 frozen file hashes immediately before dispatch. The V5 freeze verifier passed again after the run.
- Runner command: `.\.venv\Scripts\python.exe -B docs/flash-v5-independent-acceptance-evidence/live_guard.py --run-id flash-v5-20260927-01 --dependency-manifest-sha256 bcc424e1a372b1e98b1d81d00f368e94075613ab559b1fceb68c7681c371747b`.
- Result root: `evaluation/current_flash_v5/runs/flash-v5-20260927-01`; isolated database root: `artifacts/current_flash_v5/flash-v5-20260927-01`.
- New create-only inventory: `evaluation/current_flash_v5/LIVE-INVENTORY.json`, SHA-256 `40fe43b68bcc2772b8ba76e60f4160858171800d97551a1195f275d941c3f838`. It hashes all 320 files within the live result root. The result-root `workspace-manifest.json` records the 30 isolated SQLite hashes.

## Dispatch and usage

| Measure | Observed |
|---|---:|
| Logical cases finished / planned | 30 / 30 |
| Not run | 0 |
| Generation POST attempt starts / finishes / observed HTTP responses | 33 / 33 / 33 |
| Generation HTTP status | 33 × 200 |
| `/models` GET starts / finishes | 1 / 1 (HTTP 200; model present) |
| Contract-repair evaluations | 3 |
| Transport timeout retries | 0 |
| Usage complete / missing / partial / unknown | 33 / 0 / 0 / 0 |
| Input / output tokens returned by Provider | 105167 / 13459 |
| Service-stop triggered | No |

All 33 generation attempt finish records contain visible `message.content` and parsed response metadata. Every evaluation has a separately saved request, input audit, parsed business JSON, and attempt records; each case has a runtime binding and final product. No case was rerun for quality. Monetary cost was not returned and is unavailable. The earlier cumulative ledger was 63 generation POST, three `/models` GET, 185382 input and 20686 output tokens; including this V5 run it is 96 generation POST, four `/models` GET, 290549 input and 34145 output tokens.

## Product and machine-score layers

| Set | First raw machine result | Repair raw | Final machine result | Product API status |
|---|---|---|---|---|
| 24 comparison cases | 10 pass, 14 fail | 3 repair answers, all fail | 10 pass, 6 fail, 8 terminal_failure | 16 completed, 8 failed |
| 6 G02 cases | 6 citation-binding pass | None | 6 citation-binding pass | 6 completed |

The eight comparison terminal failures are cases `01, 04, 10, 15, 16, 19, 22, 24`; the six final machine failures are `03, 06, 09, 12, 18, 21`. All three contract repairs are in cases `03, 15, 24`. These remain failed evidence, not candidates for automatic resubmission. `pass` here is the frozen machine rule result only. G02 automated checks cover citation identity binding; item and summary semantic support still require human review. The comparison scorer also leaves semantic review pending, including its declared category variant.

## Evidence anchors and limits

- `summary.json`: SHA-256 `bcfbab5e9f49a4f1b498fe2f77dc00495e76365184cb2eaa8087df2c551c46f4`.
- `workspace-manifest.json`: SHA-256 `27f16ac259bfbc649e0208177394bcda1906c2075377dc101a42eb2affa0b027`.
- Each `cases/NN/attempts` folder contains the first visible answer content and usage; `evaluations`, `scores.json`, and `final-product.json` preserve parsed first/repair/final distinctions. The controller can verify every file against `LIVE-INVENTORY.json` before independent answer review.
- G02 synthetic parent chapter bodies are empty. This run binds selected SourceSpan text, controlled Memory, saved drafts, and chapter identity/revision; it does not prove a full-chapter prose source chain.
- Existing V1–V4 evidence, product code, gold labels, prompts, and frozen V5 files were not changed. No commit, push, merge, deploy, SMTP, real author workspace, or Agent development was performed.
