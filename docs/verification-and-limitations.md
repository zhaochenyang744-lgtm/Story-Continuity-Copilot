# Verification and known limitations

## Final retained verification record

The following results are retained evidence for the local Web Demo. They describe completed verification, not a deployment or a claim of universal reliability.

| Area | Retained result | Scope |
| --- | --- | --- |
| Backend contract and regression | 43/43 passed | Includes the 24 API endpoint templates, isolation, Reset, provider guards, Evidence, ChangeSet, and SQLite rollback paths. |
| Frozen V4 evaluation | 24/24 passed | Validators and evaluation tests for the formal V4 asset set. |
| Frontend static gates | lint, typecheck, build passed | Current Next.js frontend. |
| Production browser workflow | 22/22 passed, 0 failed, 0 skipped, 86.257 s | Independent Stage 6 Web Demo acceptance. |
| Visual review | 34/34 passed | Production Web Demo screenshots. |
| Reset demonstration | 5/5 completed | The seeded Grey Harbor review path. |
| API response scan | 745 responses across 24 endpoint templates; unresolved 0 | In-memory scan during Stage 6 acceptance. |
| V4 evaluation runs | 15 formal + 6 stability reruns; 21/21 completed | Three isolated corpora and original balanced three-class cases. |

The V4 results are stored as sanitised structured files with a post-run integrity record. The published release bundle verifies its seven result files and the recorded metadata for 15 isolated runtime databases; it does not include or reopen those databases. The controller's retained local workspace separately verifies the recorded SQLite hashes, sizes, and Run statuses. The record confirms that raw provider content was not retained.

## V4 product evaluation

| Metric | Result |
| --- | ---: |
| Accuracy | 1.0000 |
| Macro F1 | 1.0000 |
| Conflict recall | 1.0000 |
| Insufficient-evidence recall | 1.0000 |
| No-conflict FPR | 0.0000 |
| Hit@5 | 1.0000 |
| Cited Evidence precision | 1.0000 |
| Evidence resolvability | 1.0000 |
| Schema validity | 1.0000 |
| Fail-closed safety | 1.0000 |
| p50 / p95 latency | 2593 ms / 4104 ms |
| Input / output tokens | 16037 / 2183 |
| Cost | unavailable |

The reported V4 scope is deliberately narrow: it is a frozen 15-case product evaluation with 6 stability reruns, not an online A/B test, a broad literary-quality benchmark, or an estimate of production cost.

## Limitations

- Two formal V4 cases had the correct class but a category mismatch: `timeline → event_status` and `world_rule → event_status`.
- Across three stability cases, decision and category/severity stability were 3/3, while Evidence-ID-set stability was 2/3 and exact-explanation-hash stability was 1/3.
- A real provider must be explicitly configured. Without it, the product intentionally returns `503 provider_unavailable` instead of fabricating a result.
- The local runtime database is deliberately excluded from version control. Reset restores the demo path but is not a backup, collaboration, or hosted data-management system.
- The historical frozen CLI PoC and its held-out F1 0.9412 use a different protocol. That result is not combined with V4 metrics.

## Evidence references

- V4 report: `evaluation/results/eval-v4-first-formal-report.md`
- V4 results and stability: `evaluation/results/eval-v4-first-formal-results.json`, `evaluation/results/eval-v4-first-formal-stability.json`
- V4 integrity: `evaluation/results/v4-first-formal-post-run-integrity.json`
- Formal case set and freeze manifests: `evaluation/case_sets/eval-set-v4.json`, `evaluation/manifests/eval-set-v4-manifest.json`, `evaluation/manifests/eval-set-v4-freeze-integrity.json`
- Curated browser workflow screenshots: [artifacts/README.md](../artifacts/README.md)
