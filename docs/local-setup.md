# Local setup and reproduction

## Scope

This guide reproduces the undeployed local Web App candidate. It creates a runtime database only under `runtime/data/demo.sqlite3` and does not read protected CLI PoC, Golden, held-out, or environment files.

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
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
$env:TRUSTED_HOSTS = '127.0.0.1:8000'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000'
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 starts the frontend:

```powershell
Set-Location frontend
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
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
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
$env:TRUSTED_HOSTS = '127.0.0.1:8000,testserver'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000,http://testserver'
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
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
npm run lint
npm run typecheck
npm run build
```

## Isolated browser E2E

The frozen Stage 12 and Stage 13 browser suites use test-only providers, capture mail, dedicated loopback ports, approved system-temp roots, and separate Playwright configurations. They do not use the local demo database or a real Provider/SMTP service.

- Stage 12 V2: `frontend/playwright.stage12-v2.config.ts`, `backend/tests/e2e_app.py`, ports 3072/8072, and a `%TEMP%/story-stage12-v2-*` root.
- Stage 13 V4: `frontend/playwright.stage13.config.ts`, `backend/tests/stage13_app.py`, `frontend/scripts/stage13-v4-build.ps1`, `frontend/scripts/start-stage13-v4-artifact.mjs`, ports 3084/8084, and a `%TEMP%/story-stage13-v4-impl-*` root.

Both configurations validate the complete environment profile before either test app starts. Use the exact variables documented in `frontend/stage13-harness.mjs` and `backend/tests/stage13_harness.py`; mixed ports, prefixes, dist directories, or temp roots fail closed. The Stage 13 build script creates and scans the official standalone artifact before relocation startup.

## What remains local

Runtime databases, environment files, build output, Playwright output, evaluation fixture workspaces, logs, and temporary scan products are intentionally ignored. The versioned V4 case set, manifests, validators, tests, sanitised result bundle, and post-run integrity record are sufficient to verify the published bundle's consistency. A controller workspace that retains the recorded SQLite files can additionally run `python -m evaluation.validate_v3_post_run_integrity` and `python -m evaluation.validate_v4_post_run_integrity` with the same `PYTHONPATH`; those strict audits reopen the retained SQLite files and are not clean-clone requirements.
