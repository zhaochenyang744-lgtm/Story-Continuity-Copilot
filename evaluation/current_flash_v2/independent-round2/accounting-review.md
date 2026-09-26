# Independent accounting and evidence audit — round 2

Date: 2026-09-26. Run: `flash-v2-20260926-01`; product base: `c3bd54ab019447354e8b1387e16b9aca3258b4c9`.

**Accounting/evidence conclusion: pass for the completed eight-case run. No new blocking accounting or snapshot defect was found.** The v1 unknown-usage and business-failure-stop defects are corrected in the new harness. The actual v2 inputs are retained before the Provider implementation is called and are independently hash-bound to parsed outputs. The original v1 bytes checked against our first-round independent hashes remain unchanged. This audit makes no semantic model-quality pass claim.

## Actual run reconciliation

The independent `accounting-audit.py` reports **38/38 checks passed**. It does not import the runner or product. For dynamic controls, it extracts the relevant AST classes/functions and substitutes an in-memory fake client/base Provider. It never loads credential configuration or makes a network call.

- Eight distinct logical cases: four G02, four G03. Exactly eight business requests, eight parsed first outputs and eight HTTP events. No repairs or extra model responses occur.
- Per-case events equal `summary.all_attempt_metadata` exactly and have ordinals 1–8. All HTTP statuses are 200, all observed model names are `deepseek-flash`, all usage records have complete nonnegative integer fields, and all token triples add up.
- Independently recomputed input/output tokens are **20,844 / 5,734**. They match summary, per-response observed usage and each product's provider metrics. Unknown attempts are zero for this actual run. Cost remains unavailable.
- One separately retained `/models` HTTP 200 preflight confirms the model was present. It is excluded from the eight generation calls and their token total.
- The v2 case-definition hashes, full business-request hashes and output-schema hashes all recompute. Each parsed output points to the matching business-request hash and case ID. Project ID, draft revision and Memory version match the final product bindings.
- Every frozen source hash matches. `start.json` binds the exact frozen-manifest hash. The v2 manifest now includes `seed_data.py`, `config.py` and `database.py` as well as the new corpus and current product sources.
- No harness exceptions are recorded. Saved JSON scanning found no populated credential/session/raw-body/hidden-reasoning fields or API-key/Bearer-token patterns. This is a bounded pattern scan, not an exhaustive secrecy guarantee.

The v1 and v2 runs remain separate evaluation identities. The v1 49 generation requests and 144,300 / 8,508 token totals are unchanged and should not be merged with the new eight cases to imply a single same-input quality denominator. In particular, v2 G03 is an explicitly changed fixture.

## A1 unknown-usage repair independently verified

`run.py:120–129` now accepts only exact nonnegative integers, disallows bool/float/string/negative fields, recognizes missing fields and inconsistent totals, and returns `complete`, `partial` or `unknown`. The HTTP observer uses this at `145–171`. The summary at `439–450` preserves known component sums but exposes complete totals only when every event is complete.

The independently injected observer covers **12 controls**: absent, null, empty, prompt-only, missing-total, string, negative, bool, float, inconsistent total, valid full usage and valid all-zero usage. All expected classifications pass.

`accounting-summary-probe.py` additionally executes only the frozen summary AST against **7 independently specified matrices**. All pass:

| Matrix | Unknown attempts | Complete total available | Known input / output subtotal | Full totals |
|---|---:|---|---|---|
| Complete 11/7 response | 0 | yes | 11 / 7 | 11 / 7 |
| Missing usage | 1 | no | 0 / 0 | null / null |
| Complete response then input-only 11 | 1 | no | 22 / 7 | null / null |
| Complete response then negative input, valid output 7 | 1 | no | 11 / 14 | null / null |
| Complete response then inconsistent total | 1 | no | 22 / 14 | null / null |
| Valid zero usage | 0 | yes | 0 / 0 | 0 / 0 |
| No HTTP dispatch | 0 | no | 0 / 0 | null / null |

This fixes the reproduced v1 problem without changing any v1 result file. A `partial` event counts as an unknown attempt for full-total reporting while preserving independently known components.

## A2 business failures no longer stop the matrix

`service_failure`, `run.py:374–381`, distinguishes HTTP/service conditions from schema/evidence product failures. `auth_or_model_rejection`, `384–385`, implements immediate rejection handling; `423–428` applies the counter to the fixed matrix.

Independent AST controls cover evidence failure, schema failure, HTTP 503, HTTP 429, authentication 401, model 404, timeout and completed success. All eight expected classifications pass. Two consecutive `failed/evidence_unresolvable` records now produce **[0, 0]**, so the reproduced v1 premature stop no longer occurs.

The stop classifier intentionally observes transport error events as well as final product error codes. This audit verifies separation from business-quality failure; the actual v2 run contains no transport retry or service error, so no broader outage-handling claim is made.

## A3 full pre-call business snapshots now retained

`ObservedProvider.evaluate`, `run.py:183–204`, deep-copies the full structured business request and computes both request and schema hashes **before** calling `super().evaluate`. The saved actual requests include `bindings`, `layers.confirmed.memory_records`, `layers.planned`, `layers.written.draft`, draft claims, selected source spans, retrieval metadata and output schema. G03 additionally retains reference chapters and proposal. The eight saved requests and outputs reconcile exactly.

Two independent fake-base controls demonstrate ordering and retention:

1. At base Provider entry the snapshot already exists and its hash matches the untouched input.
2. The fake base mutates the original nested Memory value. The retained copy remains unchanged.
3. A simulated parsing failure leaves one retained business request and zero parsed outputs; a success leaves one request and one hash-linked parsed output.

Caught outer failures preserve the `business_requests` list in a create-only failure record (`429–436`). For this actual run all eight requests succeeded and all eight snapshots are on disk.

**Precision:** this is a pre-call in-memory snapshot, persisted with the completed case or caught failure. It is not a write-ahead, crash-safe pre-dispatch disk journal. A hard process termination before result persistence could lose an in-flight request; no such loss occurred in this reconciled run. Do not describe it as durable pre-call disk logging.

## Synthetic database retention and old evidence protection

`workspace-manifest.json` resolves to the explicitly named `artifacts/current_flash_v2/flash-v2-20260926-01` root. `start.json` names the same root. Every manifest entry resolves inside that directory; its file exists, byte count and SHA-256 match, and `git check-ignore` confirms exclusion. The manifest lists exactly all **eight** `.sqlite3` files in that synthetic root.

The audit only read these explicitly identified synthetic database bytes for hashing. It did not open SQL, inspect session rows, read any real business database, or mutate the retained databases. The ignored runtime material should remain outside future Git staging; the sanitized case JSON and manifest are the portable review evidence.

All v1 source/result hashes recorded by the first-round independent `accounting-results.json` still match, and every hash in the v1 frozen-input manifest still matches. This checks against evidence saved before the v2 work, not a newly generated retrospective baseline. Existing v1 failure and first/repair chains therefore remain available.

## Independent artifacts

- `accounting-audit.py` and `accounting-results.json`: 38 checks, including 12 usage controls, eight stop controls, two pre-call deep-copy controls, actual request/output accounting, old hashes, and synthetic DB size/hash/ignore verification.
- `accounting-summary-probe.py` and `accounting-summary-results.json`: seven summary accounting matrices executed from the frozen AST.

All additions are under `current_flash_v2/independent-round2/`. No implementation evidence, frozen input, product logic, Provider call, credential, real database, Git commit or deployment was changed by this audit. Semantic citation support and product-quality acceptance belong to the controller's separate review.
