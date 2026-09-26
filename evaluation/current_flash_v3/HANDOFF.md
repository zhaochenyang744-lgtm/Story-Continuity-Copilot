# Flash v3 G03 fixture correction: offline equivalence handoff

Date: 2026-09-26. **Implementation and self-check complete; controller independent acceptance pending.** V1 and V2 frozen sources, actual case records, and existing SQLite databases were not edited. V3 created four fresh isolated G03 fixture databases and made **zero external Provider HTTP requests**. There is no new real-model output in v3: all model observations and usage remain those of the preserved v2 run.

## Correction and exact input comparison

The v2 fixture updated `v2_source_spans.body` but left the matching `v2_chapters.body` at its original corpus text. Thus the v2 captured model business input truthfully represented the selected SourceSpan layer, while its local parent chapters did not represent the same source text. This limited the earlier claim of a fully consistent project fixture. In v3, each case writes the target and second-chapter body to the chapter and its SourceSpan together, updates chapter/outline summaries, and retains deterministic IDs, `source_revision=1` and Memory version 1. A pre-dispatch check requires exact parent/span body equality, both revision bindings, and the single `author_confirmed dynamic_state / 星钥 / holder` Memory linked to chapter 1. Offline negative controls reject mismatched parent text and wrong Memory type.

[Offline comparison](runs/offline-equivalence-20260926-01/summary.json) used the real product API with a fake in-process Provider that captured its business request before returning a synthetic empty answer. For each of the four G03 cases, the **entire structured request equals the actual saved v2 request recursively, with no excluded or normalized fields**. Sorted UTF-8 JSON SHA-256 hashes also match. The differing-path lists are all empty, including identity fields. The chapter parent body and updated summaries are not serialized into this model business request; their correction changes local provenance but not what the model received in these cases. Therefore no additional paid recheck is required by the predeclared [V3 plan](PLAN.md). The fake product's `completed` status is a capture artifact and is **not** a new quality verdict.

| G03 case | Exact request equal | SHA-256 prefix |
| --- | --- | --- |
| short target | yes | `de140b22029c` |
| deep target | yes | `fb4be4f58892` |
| fact absent | yes | `87e4258a5bb6` |
| other chapter | yes | `2128c1bad9d1` |

The [four per-case comparison records](runs/offline-equivalence-20260926-01/cases/) contain the full v3 request and comparison metadata. [Start manifest](runs/offline-equivalence-20260926-01/start.json) hashes the v2 inputs and v3 fixture, tests, plan, capture code and relevant product/loader files at execution. [Workspace manifest](runs/offline-equivalence-20260926-01/workspace-manifest.json) records the four retained v3 DB paths, sizes and hashes under ignored `artifacts/current_flash_v3/offline-equivalence-20260926-01/`. The [fixture builder and checks](fixture.py), [negative-control tests](test_offline.py), and [capture script](offline_equivalence.py) are new v3 files. Offline tests: **3 passed, 4 subtests passed**.

## Limits and outstanding work

- V2's real G03 results remain the empirical outcomes for the exact model input: three `completed/supported`, one `completed/insufficient` after product guard. The v2 saved SourceSpan-layer facts and citations can be assessed against that actual model input. The original v2 SQLite chapter provenance was inconsistent and should not be described as a coherent full-chapter fixture. The v3 fresh local fixture fixes that provenance and shows exact model-input equivalence, not a second real-model replication.
- V2 G02 still has the long-sentence tail and coordinate item own-citation gaps; all four first-model summaries have citation gaps. V1 V8 gate failure, evidence-selection limitations and legacy-contract mismatch remain. Neither was rerun or repaired here.
- No product code, prompt, default model, historical result, V1/V2 artifact, commit, push, or deployment was changed. Controller independent review remains separate from this self-check. No general accuracy, release readiness, or real-author claim follows from these exposed cases.

Read-only verification from this checkout:

```powershell
.\.venv\Scripts\python.exe -m pytest -q evaluation/current_flash_v3/test_offline.py
.\.venv\Scripts\python.exe evaluation/current_flash_v2/run.py verify
Get-Content evaluation/current_flash_v3/runs/offline-equivalence-20260926-01/summary.json -Encoding utf8
```

Do not rerun `offline_equivalence.py` with the completed identity; its output and local workspace are create-only.
