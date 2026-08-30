# Evaluation assets

This directory contains the code and frozen assets used to validate the local Web Demo. The current published evidence is the V4 product evaluation: 15 original balanced three-class cases across three isolated corpora, plus 6 stability reruns. Its sanitised result bundle and post-run integrity record are retained in `results/`.

The V5 candidate Gate was accepted by the controller and its 24 evaluation-only cases across four corpora were frozen as formal evaluation inputs. `eval-set-v5-manifest.json` has `status=approved_for_formal_run`, but this status approves the immutable input bundle only: its `real_provider_authorization_received=false`, `formal_run_executed=false`, and `provider_calls=0` fields are retained input-freeze snapshot fields, not the later execution record.

The first attempted execution used a Windows User-scope Base URL with the invalid `ttps` scheme. Its unchanged eight files and 24 isolated SQLite workspaces are retained under `results/invalid-runs/v5-invalid-config-url-scheme-typo/` and the matching fixture-workspace archive. `validate_v5_invalid_config_archive` fixes their hashes and confirms that all 30 run records ended `provider_error` before any successful Provider response. This incident is operational evidence only and is excluded from the V5 model-quality Gate.

After explicit user authorisation to correct that configuration incident, the V5 `first_valid_formal` executed the frozen 24 cases plus 6 stability calls. All 30 Provider responses completed successfully and the quality result is retained at the original fixed paths with `status=gate_failed`: macro F1 was 0.9132, conflict recall 1.0, and conflict category accuracy 0.75, while insufficient-evidence recall was 0.75, the designated category-mismatch regression was 2/3, expected-evidence recall was 0.75, and multi-direct full-set recall was 0.5. Cost was unavailable. The eight valid-result files are immutable and separate from the invalid archive; `validate_v5_first_formal_results` is the authoritative post-run validator.

## Stage 10 current status

Stages 8 and 9 are accepted product work. V5, V6, and V7 each retain one immutable first-valid formal result bundle with `gate_failed`; none is rerun or reinterpreted by later prompt changes. V8 `first_valid_formal` ran once from its frozen `deepseek-v4-pro` and `continuity-review-v6` input bundle. All 30 calls completed, but the retained result is `gate_failed` because the designated category regression was 2/3; its eight results and 24 workspaces are immutable. Stage 10 is not passed. Stage 11 has subsequently passed its primary real 100k/300k product workflow Gates without changing these evaluation results; optional Stage 11N and Stage 12 have not started.

The original candidate remains independently valid, while the formal validator fixes the accepted case set, semantic sign-off, corpus inputs, thresholds, and file hashes:

```powershell
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v5_candidate
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v5
& .venv\Scripts\python.exe -m evaluation.v5_fixture_preflight
```

The preflight's test Provider calls exercise retrieval and isolation only and are not model-quality evidence. `eval-v5-first-formal-plan.json` remains the unchanged candidate-era `not_run` plan and `eval-set-v5-manifest.json` remains an input-freeze snapshot; neither is rewritten to impersonate execution evidence. The retained `first_valid_formal` result is immutable and must not be overwritten or rerun under the same result identity.

Validate the self-contained published V1–V4 package from the repository root:

```powershell
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v2
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v3
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v4
& .venv\Scripts\python.exe -m evaluation.validate_release_bundle
```

The V5–V8 result JSON/Markdown and integrity manifests are sanitised retained records, but their 24-workspace database sets remain local runtime evidence and are excluded from Git. With those original retained workspaces present, run the full post-run validators and evaluation suite:

```powershell
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_v5_invalid_config_archive
& .venv\Scripts\python.exe -m evaluation.validate_v5_first_formal_results
& .venv\Scripts\python.exe -m evaluation.scan_v5_retained
& .venv\Scripts\python.exe -m evaluation.validate_v6_first_formal_results
& .venv\Scripts\python.exe -m evaluation.scan_v2_fixtures
& .venv\Scripts\python.exe -m evaluation.validate_v7_first_formal_results
& .venv\Scripts\python.exe -m evaluation.scan_v7_retained
& .venv\Scripts\python.exe -m evaluation.validate_v8_first_formal_results
& .venv\Scripts\python.exe -m evaluation.scan_v8_retained
& .venv\Scripts\python.exe -m unittest discover -s evaluation\tests -v
```

The release-bundle validator checks frozen assets and sanitised result files against the published record. It does not claim to reopen SQLite workspaces that are deliberately excluded from Git. A controller workspace that still retains those files can run the additional strict audits `python -m evaluation.validate_v3_post_run_integrity` and `python -m evaluation.validate_v4_post_run_integrity`. No validator performs a new provider evaluation. The retained V4 result is frozen; a new live evaluation would require separate authorisation and a new frozen result. Evaluation code deliberately does not retain provider credentials, Authorization values, prompt bodies, raw provider responses, full source chapters, or chain-of-thought.

Historical V1–V3 result bundles are excluded from the publication bundle; their source assets remain only where the evaluation test suite needs them for audit continuity. The frozen CLI PoC and its protected held-out assets are outside this repository's scope.
