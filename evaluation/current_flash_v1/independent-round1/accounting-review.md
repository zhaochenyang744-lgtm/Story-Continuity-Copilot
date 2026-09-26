# Independent accounting and evidence audit — round 1

Date: 2026-09-26. Subject: `flash-v1-20260926-01`, product HEAD `c3bd54ab019447354e8b1387e16b9aca3258b4c9`.

**Conclusion:** the saved first run's request and token totals are independently reconciled and may be reported: 48 logical runs, 49 ChatCompletions POST observations, plus one separate `/models` observation; 144,300 prompt tokens and 8,508 completion tokens. No actual unknown-usage attempt appears in these 49 complete observations. This does **not** accept the harness for long-term reuse: two isolated offline probes expose unknown-usage misclassification and premature stop on business-quality failures. Saved input snapshots also have a reproducibility limitation. Preserve the v1 files and correct these under a new harness/run identity.

## Verified current-run evidence

`accounting-audit.py` performs a local JSON/source audit without importing the runner, reading credentials, accessing a database or making any HTTP call. It extracts only `ObservedClient` as AST for fake-response tests. Its `accounting-results.json` records **30/30 current-run checks passed** and byte hashes of the files inspected.

- The 48 saved records are unique by family, case ID and repeat ordinal: V8 24, stability 6, G01 10, G02 4, G03 4. Every saved HTTP event is exactly equal, in order, to `summary.all_attempt_metadata`, with global ordinals 1–49. No event or logical result is missing in this completed run.
- All 49 events are HTTP 200, report `deepseek-flash`, contain a nonempty fingerprint, and have complete nonnegative integer `prompt_tokens`, `completion_tokens`, and `total_tokens`. All 49 token triples add up. Recomputed totals match summary exactly. The observed fingerprint is metadata from this run, not a guaranteed immutable model version.
- There are 49 parsed business outputs corresponding one-for-one, in each case's sequence, with the 49 HTTP observations and their observed-response usage. The single two-response case is `v8-opal-nursery-conflict-timeline`, with `contract_repair` flags `[false, true]`. Its first and repair outputs both survive. No HTTP error, transport retry or unknown usage occurs in this actual run.
- The two `failed/evidence_unresolvable` G03 results are saved. `summary.failures=[]` describes no harness exception; it must not be read as no quality failure.
- The `/models` preflight is a separate file showing HTTP 200, model present, 590 ms and no recorded error. It is not included in the 49 generation requests or their token total.
- `start.json` binds the exact `frozen-inputs.json` SHA-256. Every source hash listed in the freeze matches today's bytes. The observer, post-run audit and record persistence use separate sources; the supplementary post-run audit is not part of the original frozen scorer, which is disclosed in its own method and script hash.
- Cost is correctly `unavailable`. This audit checks local dispatch observations and API-reported usage, not the provider's billing ledger. No response ID or server request ID was retained for independent billing correlation, so this evidence must not be described as a bill.
- Saved JSON scanning found no populated credential/session/raw-response/hidden-reasoning keys or API-key/Bearer-token patterns. No SQLite/database file exists in the new evaluation directory. The runner contains only a named credential lookup and a literal synthetic local test password; no actual credential was read by this audit. This is a bounded pattern scan, not a proof that arbitrary strings can never be sensitive.

## Findings requiring a new harness version

### A1 — missing or partial usage is reported as zero unknown attempts

At `run.py:148`, HTTP 200 with a missing `usage` object is converted to `{prompt_tokens: null, completion_tokens: null, total_tokens: null}`. At `run.py:451–460`, that truthy dictionary contributes zero to known sums, and `usage_unknown_attempts` checks only `usage is None`. A partially present usage dictionary has the same problem.

The independent fake observer results in `accounting-results.json` reproduce three failures:

| Fake response | Current unknown count | Required unknown count |
|---|---:|---:|
| `usage` absent | 0 | 1 |
| `usage: {}` | 0 | 1 |
| Only `prompt_tokens: 11` | 0 | 1 |

`usage: null` and complete usage are controls. This is an evaluator defect, separate from the product's timeout/repair accounting. It did **not** affect the current 49 complete usage records. A new scorer should preserve known partial token components while exposing unknown components/attempts explicitly; it must not report a fully known total or zero unknown count for these cases. Include absent, null, partial, invalid-type, HTTP error, timeout and complete controls.

### A2 — two consecutive product-quality failures trigger the service outage stop

`run.py:422–430` increments `consecutive_service_errors` whenever `status == "failed"`, regardless of `error_code`. That includes schema/evidence product failures after a successful HTTP response. `accounting-stop-snapshot-probe.py` executes the exact AST condition from line 424 against synthetic terminal records: two `failed/evidence_unresolvable` records produce counters `[1, 2]` and stop the matrix. Two actual provider errors also stop, and a following completed case resets to zero.

The intended plan stops on consecutive service failures, not two model-quality failures. The fixed matrix's denominator would otherwise depend on preceding model mistakes. The actual v1 order separated its two evidence failures with completed cases, so all 48 entries executed and the current totals are unaffected. New logic should classify provider transport/authentication/model availability separately, retaining schema/evidence outcomes and continuing the authorized bounded matrix.

### A3 — the saved inputs do not reconstruct the whole actual request

`ObservedProvider.evaluate`, `run.py:174–187`, stores only claims, draft claims, source spans, retrieval metadata and proposal. It omits confirmed Story Memory, planned/other layers, bindings, the actual written-draft excerpt, and continuity Memory. It records after successful parsing, so an invalid-JSON/failed Provider call would have no saved request snapshot at all. `run.py:464–466` then removes the synthetic DB.

The record's case hash binds the high-level case specification, not the complete generated bound input. Product `input_digest`, version numbers and UUID references cannot independently reconstruct missing layer text. The frozen dependency list also omits `backend/app/seed_data.py`; the handoff transparently reports its post-run hash and clean HEAD provenance, which helps but does not replace a pre-dispatch snapshot.

Nuance: all four G02 final analyses include enriched excerpts for their eight first-response Memory citation IDs, so those saved citations remain partly auditable. This is not a claim that all G02 reference text is lost. In G03 short, absent and other-chapter, the first-response Memory citations have no final-analysis excerpt (the two failed analyses are absent; the absent-source result strips items). `target_memory_value` and proposal target ID retain the intended target, but the whole actual confirmed layer and current draft/bindings are absent. See `accounting-stop-snapshot-results.json` for exact affected IDs and per-record digest fields.

A future run should save sanitized structured input layers and identity/binding metadata before each logical Provider call, with stable request/output/HTTP associations and hashes; retain first/repair inputs even if parsing fails. This can omit raw prompt strings, HTTP bodies, secrets and hidden reasoning while preserving the synthetic evidence required for independent semantic review. Do not fabricate a retrospective full v1 snapshot or replace its original records. A v2 G02/G03 replay can close the evidence collection gap under a new ID.

## Other evidence limitations

- `stability_one`, `run.py:332–342`, saves score rows and parsed model outputs but not the final product object, unlike `v8_one`. It supports the reported repeated class labels; it is not a complete repeated-output semantic/evidence snapshot. Preserve full final product results in the next harness.
- `write_new` uses exclusive file creation (`run.py:54–57`), and run directories reject reuse (`380–385`). This protects existing files from replacement. It is not an atomic durable journal for a process crash during a request. The completed current record/event reconciliation passed; no crash-related omission is alleged here.
- Request configuration is traced through the frozen `provider.py:346–372` and `run.py:347–355`. The observer's saved event does not itself retain outgoing request body/model/URL hashes. A new sanitized request metadata record would strengthen auditability without retaining prompts or authorization headers.

## Independent artifacts

- `accounting-audit.py` → `accounting-results.json`: current 30 checks, fake missing-usage probes, snapshot inventory and evidence hashes.
- `accounting-stop-snapshot-probe.py` → `accounting-stop-snapshot-results.json`: service-stop counter reproduction and actual first-response Memory citation/excerpt inventory.

No original implementation evidence, frozen input, product source, historical V8 asset, credential, Provider call, business database, Git commit or deployment was changed by this audit.
