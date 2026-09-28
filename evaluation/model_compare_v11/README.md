# Model comparison V11

V11 tests the v20 decisive-fact category rule (`continuity-review-v20-decisive-fact-category`). Ordinals 1-34 are the V7 prepared business inputs with the current engine schema, identical to V9 and scored by the unchanged V7/V6 gold. Ordinals 35-54 are `evaluation/category_controls_v1`: 20 new paired positive/negative controls written and frozen before any v20 run, scored by the same V7 issue logic against their frozen expected fields. Both conditions match V9: Flash thinking enabled/high and Pro thinking enabled/high.

The controls were authored by the implementer, not independently labeled, and are development controls rather than an independent unseen set. A single run per case cannot establish stability. See `docs/model-compare-v11-independent-acceptance/PLAN.md`.

## Commands

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
python -B -m unittest evaluation.model_compare_v11.test_offline -v
python -B -m evaluation.model_compare_v11.harness prepare --run-id prep-v11-01
python -B -m evaluation.model_compare_v11.freeze freeze
$V11ManifestHash = (Get-FileHash evaluation/model_compare_v11/frozen-inputs.json -Algorithm SHA256).Hash.ToLowerInvariant()
python -B evaluation/model_compare_v11/live_guard.py --run-id model-compare-v11-<id> --manifest-sha256 $V11ManifestHash --verify-only
```

Live launch drops `--verify-only`, requires user authorization, and reads the key only from `CONTINUITY_API_KEY`.

## Limits

108 condition-cases, at most two contract evaluations each and one transport retry per evaluation: 432 POST plus one models GET, and a 1,500,000 known-total-token stop threshold. All other accounting, privacy, stop and scoring rules are inherited unchanged from V8/V9.
