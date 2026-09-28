# V6 core offline handoff for parallel independent review

2026-09-27. Core scope is `backend/app/provider.py`, `backend/app/engine.py`, and `backend/tests/test_v6_continuity_contract.py`. No Provider, real database, SMTP, commit, push or deploy was used. The V5 baseline snapshot and all historical V5 files remain unchanged.

| File | Current SHA-256 |
|---|---|
| `backend/app/provider.py` | `ed33b19761acfec79cffa14d171389eaa9659ba4774223a4d161c58d2d32643` |
| `backend/app/engine.py` | `0f0d34335636bf05b551dbfe8ec88ffff07fabb0d7a6a577dd987ebd1ffcee59` |
| `backend/tests/test_v6_continuity_contract.py` | `c976efb224b00b4f039dc77bf2f558c724eeb60d9e7aec429016fe9049bda357` |

Offline command from repository root:

```powershell
$env:PYTHONPATH='backend'; $env:SCC_DISABLE_DEFAULT_APP='1'; .\.venv\Scripts\python.exe -m unittest tests.test_v6_continuity_contract tests.test_v140_real_ai_contract_repairs tests.test_provider_narrative_scope -q
```

Observed: **41 tests, 0 failures/errors**. V6 tests cover mixed direct/context evidence, no direct contradiction, source/chapter binding, cited versus borrowed static rule Memory, ordinary cross-source Memory association, time uncertainty, `state_change`, explained empty output, per-batch ID coverage, malformed IDs, and bounded contract repair. Three V5 request prompts checked against the new input budget: 4289, 4294 and 4252 units, below 6000.

First local invocation of the old suite lacked `PYTHONPATH=backend` and could not import `app`; no test logic ran. The first correctly invoked run found one existing prompt-string assertion (`remove the object`) after the wording revision. The prompt wording was repaired without changing its decision policy; the final 41-test command passed. These first failures are retained here, not reported as a first-pass green run.

The new Provider response requires one `claim_verdicts` row per claim in each request batch. `reviewed_issue` includes compatible non-empty `state_change`; the rows are validated and stripped before existing Issue persistence/API. The product can structurally require coverage and a cited direct contradiction plus selected premise sources. It cannot prove that a natural-language `no_issue` basis or auxiliary premise is semantically correct. The frozen V6 semantic controls and independent review must decide those questions. `timeless_rule` now requires the qualifying rule Memory's own source span to be cited by that issue; ordinary cross-source Memory association remains valid.

The shared G02 Provider/engine preservation replay is **pending independent review**. V6 evaluation adaptation, offline matrix and final source freeze are also pending. If these core hashes change, this handoff is superseded for the changed path and the independent core/G02 controls must be rerun.
