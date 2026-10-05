# Story Continuity Copilot v1.0 Public Release — local setup and reproduction

## Scope

This guide reproduces the signed Story Continuity Copilot v1.0 Public Release source locally. Local reproduction is not a second public deployment and creates a runtime database only under `runtime/data/demo.sqlite3`; it does not read protected CLI PoC, Golden, held-out, or environment files.

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

From `frontend`, run all current browser tests with one command. No manually started frontend or backend is needed:

```powershell
Get-ChildItem Env:CONTINUITY_* | Remove-Item
npm run test:e2e

# One group, selected groups, or matching titles within regular
npm run test:e2e -- --group v130
npm run test:e2e -- --group stage12,regular,stage13
npm run test:e2e -- --group regular --grep "controlled edit run"
npm run test:e2e -- --help
```

The runner executes the eight groups sequentially against temporary production builds, test-only providers, capture mail and temporary databases. It clears inherited model/SMTP configuration and supplies each group's complete environment profile; mixed origins, prefixes, dist directories or temp roots fail closed. Keep these loopback ports free and run only one E2E command at a time:

| Group | Frontend / backend ports | Executions / coverage |
|---|---|---|
| `v130` | 3197 / 8197 | 15 author-workflow tests |
| `v140-frontend` | 3205 / 8205 | 13 current-interface tests |
| `v140-visual` | 3211 / 8211 | 13 interface + 1 visual test |
| `regular` | 3270 / 8270 | 54 authentication, writing, imports, fact review, v1.1/v1.2 and helper tests |
| `stage12` | 3072 / 8072 | 8 Agent Run lifecycle tests; Stage 12 V2 impl profile |
| `stage13` | 3080 / 8080 | 4 visitor, recovery and isolation tests; Stage 13 impl profile |
| `maintenance` | 3260 / 8260 | 13 interface + 2 maintenance tests |
| `legacy-rich-suggestion` | 3271 / 8271 | 1 staged rich-text suggestion test |

The total is 124 executions, including the same 13 v140 frontend cases in three groups. `--group` accepts comma-separated group names; `--grep` is supported only with `--group regular`. Windows builds temporarily use Q:, R:, T: and V:; leave these drive letters available. Each group owns its temporary source, build, database and services. The unified runner cleans those resources and checks ports after each group; it retains results and diagnostic attachments under the printed `E2E_REPORT_ROOT`, with machine-readable and Markdown summaries at `E2E_SUMMARY` and `summary.md`. It leaves tracked `next-env.d.ts` and `tsconfig.json` unchanged.

Five historical acceptance files (`legacy-gap-independent.spec.ts`, `legacy-gap-independent-round2.spec.ts`, `legacy-gap-round3-brief.spec.ts`, `g02-controller.spec.ts`, and `g02-controller-post-v4.spec.ts`) are retained and excluded from daily runs. `npm run test:e2e:raw` is the direct Playwright entry and requires a manually supplied matching isolated environment. `npm run test:v130`, `npm run test:v140:frontend`, and `npm run test:v140:visual` remain available as standalone runners. Stage 13 daily tests use `tests.stage13_app` and CaptureMailer on 3080/8080; the historical V4 artifact-build/scan profile on 3084/8084 remains a separate release workflow.

These browser checks use no local demo database, real model or external SMTP service. They verify browser behavior and test-provider contracts; real provider evaluations and production delivery require their own verification.

## What remains local

Runtime databases, environment files, build output, Playwright output, evaluation fixture workspaces, logs, and temporary scan products are intentionally ignored. The versioned V4 case set, manifests, validators, tests, sanitised result bundle, and post-run integrity record are sufficient to verify the published bundle's consistency. A controller workspace that retains the recorded SQLite files can additionally run `python -m evaluation.validate_v3_post_run_integrity` and `python -m evaluation.validate_v4_post_run_integrity` with the same `PYTHONPATH`; those strict audits reopen the retained SQLite files and are not clean-clone requirements.
