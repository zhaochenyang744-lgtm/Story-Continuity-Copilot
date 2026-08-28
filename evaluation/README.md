# Evaluation assets

This directory contains the code and frozen assets used to validate the local Web Demo. The current published evidence is the V4 product evaluation: 15 original balanced three-class cases across three isolated corpora, plus 6 stability reruns. Its sanitised result bundle and post-run integrity record are retained in `results/`.

Validate the published evaluation package from the repository root:

```powershell
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v2
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v3
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v4
& .venv\Scripts\python.exe -m evaluation.validate_release_bundle
& .venv\Scripts\python.exe -m unittest discover -s evaluation\tests -v
```

The release-bundle validator checks frozen assets and sanitised result files against the published record. It does not claim to reopen SQLite workspaces that are deliberately excluded from Git. A controller workspace that still retains those files can run the additional strict audits `python -m evaluation.validate_v3_post_run_integrity` and `python -m evaluation.validate_v4_post_run_integrity`. No validator performs a new provider evaluation. The retained V4 result is frozen; a new live evaluation would require separate authorisation and a new frozen result. Evaluation code deliberately does not retain provider credentials, Authorization values, prompt bodies, raw provider responses, full source chapters, or chain-of-thought.

Historical V1–V3 result bundles are excluded from the publication bundle; their source assets remain only where the evaluation test suite needs them for audit continuity. The frozen CLI PoC and its protected held-out assets are outside this repository's scope.
