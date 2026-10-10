# Story Continuity Copilot — local setup and reproduction

## Scope and prerequisites

This guide runs v1.7.0 source locally on Windows PowerShell with Python 3.11+ and Node.js 20.9.0 or later (the installed Next.js requirement). Local execution is not a public deployment. The API uses the repository's `runtime/data/demo.sqlite3`; test runners create isolated temporary data.

## Install

From the repository root:

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend
npm ci
Set-Location ..
```

## Start the application

Terminal 1, from the repository root:

```powershell
Set-Location backend
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
$env:TRUSTED_HOSTS = '127.0.0.1:8000'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000'
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Do not run `next dev`, including `npm run dev`, directly inside the repository's `frontend/`. It rewrites `tsconfig.json` and `next-env.d.ts`.** In terminal 2, start from the repository root and use a temporary frontend copy:

```powershell
$sccFrontendSource = (Resolve-Path .\frontend).Path
$sccFrontendCopy = Join-Path ([IO.Path]::GetTempPath()) ('scc-local-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sccFrontendCopy | Out-Null
Get-ChildItem -LiteralPath $sccFrontendSource -Force |
  Where-Object { $_.Name -notmatch '^(node_modules|\.next.*|test-results|playwright-report|\.env.*)$' } |
  Copy-Item -Destination $sccFrontendCopy -Recurse
Set-Location $sccFrontendCopy
npm ci
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open `http://127.0.0.1:3000`. Frontend `/api/*` requests are rewritten to the configured backend origin. Stop each terminal with Ctrl+C when done. Build and development output remain in the temporary frontend copy.

Check the API:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/readiness
```

## Provider configuration

The supported provider reads `CONTINUITY_PROVIDER` (`deepseek`), `CONTINUITY_MODEL`, `CONTINUITY_BASE_URL` and `CONTINUITY_API_KEY` from the API process environment. `CONTINUITY_REVIEW_THINKING` accepts `disabled` or `high`. Configure real credentials only through your local secret mechanism; never commit them. Model or prompt changes require separate quality verification.

Without a configured provider, `POST /api/projects/{project_id}/checks` returns `503 provider_unavailable` instead of a synthetic finding. The internal URL still uses `projects`; the author-facing term is work.

## Verification commands

Backend, from `backend/` (install `pytest` with `python -m pip install pytest` in the chosen interpreter for the maintenance-package command):

```powershell
Get-ChildItem Env:CONTINUITY_* | Remove-Item
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
$env:TRUSTED_HOSTS = '127.0.0.1:8000,testserver'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000,http://testserver'
& ..\.venv\Scripts\python.exe -m unittest discover -s tests
& ..\.venv\Scripts\python.exe -m pytest tests/test_maintenance_package.py
```

Evaluation, from the repository root in the same PowerShell session, keeping the application environment above; these validate frozen assets without making model requests:

```powershell
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_release_bundle
& .venv\Scripts\python.exe -m unittest discover -s evaluation\tests
```

Deployment checks, from `frontend/`:

```powershell
npm run test:build-origin
```

Latest measured counts and known failures are recorded in [README tests](../README.md#tests). The maintenance-package test path is relative to `backend/`.

## Isolated browser E2E

From `frontend/`, install Chromium once with `npx playwright install chromium` if it is not already available, then set the interpreter explicitly and run the single current group:

```powershell
Get-ChildItem Env:CONTINUITY_* | Remove-Item
$env:E2E_PYTHON = (Resolve-Path ..\.venv\Scripts\python.exe).Path
npm run test:e2e
```

`E2E_PYTHON` may point to a shared virtual environment containing the backend dependencies. If omitted, the runner tries the repository's `.venv/Scripts/python.exe`. Leave **3280/8280** and Windows drive **Q:** available. Do not run competing E2E commands. The sole group is `v170`; an optional diagnostic selection is `npm run test:e2e -- --group v170 --grep "title fragment"`, which is not a full-suite result.

The runner builds a temporary production frontend, starts the test-only backend with capture mail and temporary data, and automatically sets `STORY_SAMPLE_WORK_FILE` to `backend/app/seed/sample_work.json`. It sanitises inherited model/SMTP configuration, checks port availability, cleans owned services and temporary build resources, and preserves repository `tsconfig.json` and `next-env.d.ts`. It does not use 3170/8170 or 3190/8190.

Read the printed `E2E_REPORT_ROOT` and `E2E_SUMMARY` paths for logs, attachments and `summary.json`/`summary.md`. Failed tests, fixmes, tests not run and infrastructure errors are separate counts. Browser checks use no real model or external SMTP service; they verify product behaviour, not model quality or deployment.

## Local and frozen evidence

Runtime databases, environment files, build output and local reports remain outside the published evidence. Frozen evaluation assets and their published validators can verify bundle consistency. Strict post-run integrity audits requiring retained SQLite databases are not clean-clone requirements. Historical and frozen evidence is indexed in [the documentation directory](README.md).
