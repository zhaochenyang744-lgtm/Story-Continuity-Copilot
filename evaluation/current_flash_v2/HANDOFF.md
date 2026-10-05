# Flash v2 focused real Provider recheck: implementation handoff

Date: 2026-09-26. **Implementation and self-review complete; awaiting controller independent acceptance.** Run ID: `flash-v2-20260926-01`. Checkout `codex/legacy-gap-repair`, HEAD `c3bd54ab019447354e8b1387e16b9aca3258b4c9`. Scope was the controller-authorized G02 four plus G03 four focused recheck. V1's frozen inputs, 48 case records, and 49 HTTP attempts were not rewritten; V8 and G01 were not rerun. No product logic, prompt, default model, business DB, protected data, Agent, commit, push, or deployment was changed.

## Actual outcome and interpretation

- Eight new ChatCompletions HTTP dispatches, all HTTP 200, all with complete usage. One `/models` preflight was separate. There were no retries, contract-repair calls, transport failures, or harness exceptions. New usage: **20,844 prompt + 5,734 completion tokens**. DeepSeek response `model` was `deepseek-flash` on all eight; charged cost was not returned and is **unavailable**. The original v1 usage remains separately 144,300 prompt + 8,508 completion tokens over 49 ChatCompletions requests. Do not silently combine the two run identities into one evaluation denominator.
- G02 product terminal states: two `completed/supported` with draft `covered`, two `completed/partial` with draft `partial`. The long-sentence item's tail and an additional coordinates claim still lack adequate **own** citations. The first-model summaries all contain at least one citation gap; the final long-sentence summary retains its tail gap. The identical-text case's crescent-crack item now cites the actual chapter 9 span, but this one repeated response is not a product fix.
- G03 uses a **new** consistent two-chapter fixture and empty draft. Short, deep, and other-chapter each ended `completed/supported`; absent ended `completed/insufficient` with zero final items. The first absent model answer explicitly recognized the missing chapter source and made only a conditional Memory/proposal comparison, so do not call it a fabricated chapter fact. The three supported outcomes are narrow fixture results, not a same-input score gain over v1. The v1 short/other product failures remain historical results.
- G03 pre-dispatch validation and post-run snapshots confirm that the target Memory is `dynamic_state / 星钥 / holder`, linked to chapter 1; both chapter spans entered every model business request. The other-chapter interference text really entered the request. The deep target sentence is in the selected excerpt. Every saved business request hash was recomputed and matched its parsed output; usage totals match the eight case records and product token metrics.
- The v1 V8 gate remains failed. Current second-stage evidence selection omitted complete expected evidence from all eight expected conflict prompts, and independent review found legacy `static_canon/fixture_anchor` versus current `timeless_rule` contract mismatches. V2 did not touch V8 labels or rerun that gate.

Read the item-level [implementer review](POSTRUN_REVIEW.md) before treating the product's `supported` tag as a semantic pass. The controller's independent acceptance and any subsequent product work remain separate.

## Reproducible evidence

- [Frozen pre-run plan](PLAN.md), [case definitions](cases.json), [G03 corpus](g03-corpus.json), [input hash manifest](frozen-inputs.json), [runner](run.py), [offline tests](test_offline.py).
- [Summary and attempt metadata](runs/flash-v2-20260926-01/summary.json), [eight case records](runs/flash-v2-20260926-01/cases/), [workspace DB hash manifest](runs/flash-v2-20260926-01/workspace-manifest.json), and [model preflight](runs/flash-v2-20260926-01/models-preflight.json). Each case includes the exact structured business request passed to the Provider, its SHA-256, parsed first model JSON, terminal product result, citations, source selection, and HTTP usage. The records contain no API credential, authorization header, raw HTTP body, generated prompt, or hidden reasoning.
- Eight isolated local SQLite DBs are retained under the ignored `artifacts/current_flash_v2/flash-v2-20260926-01/` path for controller review; their paths, sizes, and SHA-256 values are in `workspace-manifest.json`. Do not alter the DBs before independent acceptance.
- Offline suite: `4 passed, 8 subtests passed`; the tests cover usage absence/partial/inconsistency, create-only outputs, product failure versus service stop, all eight isolated product paths, full business snapshots, and the pre-dispatch G03 binding condition. `run.py verify` passed before and after the real run. No new HTTP call is required to inspect the saved evidence.
- Existing dirty controller files `evaluation/README.md` and `docs/evaluation-maintenance.md` were preserved. `git status` shows only those plus untracked `evaluation/current_flash_v1/` and `evaluation/current_flash_v2/`; no tracked product source diff.

Read-only inspection from this checkout:

```powershell
.\.venv\Scripts\python.exe evaluation/current_flash_v2/run.py verify
Get-Content evaluation/current_flash_v2/runs/flash-v2-20260926-01/summary.json -Encoding utf8
Get-Content evaluation/current_flash_v2/POSTRUN_REVIEW.md -Encoding utf8
```

`freeze` and the completed run ID intentionally reject reuse. Further real replay would need a new evaluation identity and authorization. This handoff makes no claim about unseen stories, real authors, V8 gate passage, Agent behavior, release readiness, or charged API cost.
