# Local setup and reproduction

## Scope

This guide reproduces the local Web Demo. It creates a runtime database only under `runtime/data/demo.sqlite3` and does not read protected CLI PoC, Golden, held-out, or environment files.

## Prerequisites

- Windows PowerShell
- Python 3.11 or later
- Node.js compatible with Next.js 16
- npm

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

Terminal 1 starts the API:

```powershell
Set-Location backend
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 starts the frontend:

```powershell
Set-Location frontend
npm run dev
```

Open `http://127.0.0.1:3000`. The default frontend rewrite is `/api/* → http://127.0.0.1:8000/api/*`.

Check the local API in a third terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/readiness
```

## Provider behaviour

The application never stores provider credentials in this repository. A real local check requires explicit process environment configuration for the supported DeepSeek-compatible provider. Do not place credentials in committed files.

Without a configured production provider, `POST /api/projects/{project_id}/checks` returns `503 provider_unavailable`. This is intentional fail-closed behaviour: no synthetic review is returned and no Run is created.

## Verification commands

Run backend tests from `backend` so the `app` package resolves correctly:

```powershell
Set-Location backend
& ..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Run public frozen-asset validators and evaluation tests from the repository root. These commands validate the published bundle; they do not start a provider evaluation:

```powershell
Set-Location ..
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v2
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v3
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v4
& .venv\Scripts\python.exe -m evaluation.validate_release_bundle
& .venv\Scripts\python.exe -m unittest discover -s evaluation\tests -v
```

Run frontend static checks:

```powershell
Set-Location frontend
npm run lint
npm run typecheck
npm run build
```

## Isolated browser E2E

The browser suite uses a test-only provider and a temporary database. It is separate from the local demo database and from any real provider configuration.

Terminal 1:

```powershell
Set-Location backend
& ..\.venv\Scripts\python.exe -m uvicorn tests.e2e_app:app --host 127.0.0.1 --port 8010
```

Terminal 2:

```powershell
Set-Location frontend
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8010'
npm run dev -- --port 3010
```

Terminal 3:

```powershell
Set-Location frontend
$env:E2E_BASE_URL = 'http://127.0.0.1:3010'
npm run test:e2e
```

## What remains local

Runtime databases, environment files, build output, Playwright output, evaluation fixture workspaces, logs, and temporary scan products are intentionally ignored. The versioned V4 case set, manifests, validators, tests, sanitised result bundle, and post-run integrity record are sufficient to verify the published bundle's consistency. A controller workspace that retains the recorded SQLite files can additionally run `python -m evaluation.validate_v3_post_run_integrity` and `python -m evaluation.validate_v4_post_run_integrity` with the same `PYTHONPATH`; those strict audits reopen the retained SQLite files and are not clean-clone requirements.
