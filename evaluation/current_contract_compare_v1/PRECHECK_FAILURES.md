# Preserved development precheck failures

This log records the first failures and fixes before the candidate freeze. No real Provider call occurred.

1. The first offline API preflight failed with HTTP 409 `author_context_snapshot_unresolvable`. The fixture was amended to create an empty author-context version 0 before checks. The failed attempt did not emit a case result.
2. The next preflight reached the Provider stub but failed with `KeyError: 'layers'`: continuity business requests use top-level `claims`, `memory` and `draft`. Selection checks now read `claims[].allowed_evidence`.
3. Initial 24-case retrieval was 23/24. A later revision of the north-door claim produced 23/24 because badge roster was outside the top three business sources. Source wording was made directly about Mira trying the named door. A later location revision produced 21/24 because the gate map/watch/later-watch combination outranked required spans. The location conflict now uses a direct same-time watch observation; later movement and unnamed companion use their own relevant SourceSpan. Final capture reports 24/24.
4. PowerShell stdout redirection wrote the first `actual-inputs.json` in the active code page, not UTF-8. That development file was replaced before freeze by `preflight.py --output`, which opens the result explicitly as UTF-8. The independent reviewer recorded the original byte-level failure in `docs/g02-citation-repair-evidence/independent-round1-comparison/review-prehandoff.md`.
5. The first scripted API score probe reported `request_equal=0` because fresh run claim IDs differ from the earlier capture. It still completed/scored 24/24. `api-score-probe-results.json` retains that observation. The second probe compares the decision-relevant draft, source bodies/excerpts, memory fields and output schema; `api-score-probe-results-v2.json` reports 24/24 content equality, completion and score pass.

These fixes do not relabel or erase the failed prechecks. The final asset manifest will bind the repaired files and evidence.
