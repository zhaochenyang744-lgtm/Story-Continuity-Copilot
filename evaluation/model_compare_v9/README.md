# Model comparison V9

V9 re-runs the V8 development matrix after the v18 reasoning-length repair. It covers the 34 previously seen V7 business inputs under the two V8 candidate conditions, Flash thinking enabled/high (primary candidate) and Pro thinking enabled/high (quality control). Flash thinking disabled is not repeated: V8 already placed it well below both thinking arms.

The only business-request change from V7/V8 is `output_schema`, rebuilt from the current engine so it states the 800-code-point reasoning limit. `config.request_for` refuses to run unless each prepared V7 schema differs from the current one only in that reasoning description; every other field is used byte-for-byte. Prompt rules come from product code (`continuity-review-v18-reasoning-length`). Gold labels, V7/V6 scoring policy and V8 semantic criteria are unchanged.

This is still a seen-development comparison. It cannot establish unseen-sample generalization, repeat-run stability, original-budget production behavior, or database/API end-to-end behavior. Those remain separate follow-ups from the V8 acceptance.

## Commands

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
python -B -m unittest evaluation.model_compare_v9.test_offline -v
python -B -m evaluation.model_compare_v9.harness prepare --run-id prep-v9-01
python -B -m evaluation.model_compare_v9.freeze freeze
$v9ManifestHash = (Get-FileHash evaluation/model_compare_v9/frozen-inputs.json -Algorithm SHA256).Hash.ToLowerInvariant()
python -B evaluation/model_compare_v9/live_guard.py --run-id model-compare-v9-<id> --manifest-sha256 $v9ManifestHash --verify-only
```

Live launch drops `--verify-only` and requires explicit user authorization for the Provider calls. The API key comes only from the existing `CONTINUITY_API_KEY` environment variable; no key, header or `.env` file is written.

## Limits and accounting

Schedule is case-major with alternating order (high/pro, pro/high, ...): 68 condition-cases, at most two contract evaluations each, at most one transport retry per evaluation, hard ceilings of 272 POST plus one models GET, and a 1,000,000 known-total-token stop threshold. V8 used 399,528 total tokens for these two arms. Every other accounting, privacy, stop and scoring rule is inherited unchanged from the V8 harness: see `evaluation/model_compare_v8/README.md`. Cost is unknown unless the API reports it.

As in V8, `max_tokens=32768` and the experimental engine budget of 40,000 apply only inside `engine.execute`; each response also records whether it fits the original 8,000 budget. This remains an experiment, not production behavior.
