# V7 fixed-input regression tools

This is a new evaluation version for prompt v17 and schema provenance
`continuity-issue-v7-repair-diagnostics`. The product response shape keeps the
`v6` contract marker. The 34 V6 business cases, corpus/source/Memory IDs, source
bodies, fixed gold, category policy, evidence roles and scoring rules are
unchanged. V6 scores and captured evidence remain historical records. These are
seen development inputs, not a blind benchmark. A machine pass still requires
independent semantic acceptance.

Only this directory receives new files. Isolated SQLite workspaces are under
`workspaces/<new-run-id>/`; create-only captures are under `runs/<new-run-id>/`.
No historical run directories are copied. Historical V6 prep and four V5 result
files are read-only references for input equivalence and offline controls.

From the worktree root in PowerShell, with no credentials needed for preparation:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
& .\.venv\Scripts\python.exe -B -m evaluation.current_flash_v7.build_cases
& .\.venv\Scripts\python.exe -B -m unittest evaluation.current_flash_v7.test_offline -v
& .\.venv\Scripts\python.exe -B -m evaluation.current_flash_v7.run prepare --run-id prep-v7-01
```

`build_cases` is create-only and runs once. After product stability, independent
preflight acceptance and explicit controller direction, freeze/verify:

```powershell
& .\.venv\Scripts\python.exe -B -m evaluation.current_flash_v7.freeze freeze
& .\.venv\Scripts\python.exe -B -m evaluation.current_flash_v7.freeze verify
```

The user has authorized the necessary Provider calls in this session. The root
controller starts the live run after technical acceptance; no additional user
permission is required. Use the direct-file guard, not `-m`, so
`evaluation/__init__.py` is hash-checked before it executes. Supply the exact
accepted manifest digest; do not derive a fresh digest to bypass drift detection.

```powershell
& .\.venv\Scripts\python.exe -B evaluation/current_flash_v7/live_guard.py --run-id flash-v7-20260927-01 --manifest-sha256 <accepted-sha256> --verify-only
# After the root controller's technical acceptance, same command without --verify-only.
```

The original bounds remain: two contract evaluations per case, one transport
retry per evaluation, maximum 136 generation POSTs plus one models GET. HTTP
400/401/403/404 stops immediately; two consecutive logical cases with service or
transport errors stop the matrix. Raw visible responses, parsed results, repair
inputs, usage completeness/unknowns and terminal failures remain separate.

The V7 manifest pins its own tools, local product modules (including conditional
dependencies), all package initializers, requirements, immutable fixtures/gold,
actual prep captures and exact read-only test references. It never invokes V6
freeze or requires the V6-era product hash. Final freeze is deliberately deferred
until the new product and preparation captures are stable.
