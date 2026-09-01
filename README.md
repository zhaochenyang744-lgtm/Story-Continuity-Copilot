# Story Continuity Copilot v1.2.0

Story Continuity Copilot v1.2.0 is the current repository version of a long-form fiction continuity review product. It combines versioned Story Memory with a continuity agent that returns grounded findings for an author to review. It does not write the next chapter: the author remains responsible for the text and explicitly decides whether a proposed Memory change becomes canon.

The signed Stage 14 public-production baseline remains **Story Continuity Copilot v1.0 Public Release** as a historical evidence baseline. The active public deployment now runs **Story Continuity Copilot v1.2.0**, release `v120-a35265e-20260902`, from source commit `a35265e`. Historical Stage numbers, release IDs, the technical package name `story-continuity-app`, component API versions, and the compact in-product wordmark `Story Continuity` remain unchanged for evidence traceability and runtime compatibility.

The repository is designed for local reproduction. It contains the application source, migration and seed logic, tests, sanitised V4–V8 evaluation result records, and a small set of production-workflow screenshots. It does not include runtime databases, environment files, provider credentials, raw provider responses, recorded runtime prompt bodies, chain-of-thought, or protected evaluation assets. Full V5–V8 post-run database-hash validation therefore also requires the separately retained local evaluation workspaces; the committed result files alone do not recreate those SQLite artifacts.

## v1.2.0 update

- New registered accounts receive one isolated tutorial sample instead of three preset real works. The sample is excluded from real-work counts, search, recent works, and pending-issue summaries; completing or skipping the tutorial returns the account to an empty real workspace.
- The tutorial is a five-step author workflow covering Story Memory sources, continuity issues, Evidence, and an explicit Author Decision. Business progress is stored on the backend with version binding, CSRF protection, idempotency, monotonic revisions, and cross-login restoration; transient hints and focus effects remain client-only.
- The non-login workspace uses a wider, responsive authoring layout, a compact mobile read-only mode, clearer page actions and empty states, reduced nested framing, and three locally bundled WebP narrative assets instead of large illustrative SVG compositions.
- Independent local acceptance passed the backend suite (156/156), the v1.2 browser workflow (1/1), the frozen v1.1 regression (5/5), frontend contracts (27/27), lint, typecheck, and the production build.

## Public deployment

- Active origin: [https://43-160-207-57.sslip.io](https://43-160-207-57.sslip.io)
- Active version: **Story Continuity Copilot v1.2.0**
- Source commit: `a35265e`
- Production release ID: `v120-a35265e-20260902`
- Deployment date: 2026-09-02
- Deployment used a pre-release online SQLite backup, a server-side secret presence check, Compose preflight validation, health/readiness polling, and a retained v1.0 rollback target.
- Post-deployment acceptance verified public health/readiness, all three v1.2 WebP assets, desktop authoring routes, the 390 px mobile layout, zero browser console/page/request errors, and the complete isolated new-account tutorial lifecycle. The tutorial returned the account to zero real works after completion and used only preloaded review evidence; this acceptance did not make a new external Provider call.

## Product overview

The author workflow is:

1. Sign in locally, create or import a project, and select a project workspace.
2. Review outline, characters, world rules, chapters, and versioned Story Memory.
3. Submit the current draft for a continuity check.
4. Inspect each finding together with resolvable Evidence from the current project.
5. Accept, reject, or edit proposed Memory changes. A ChangeSet records the decision; only accepted changes update canon.
6. Use project Reset to restore the seeded review path when a fresh demonstration is needed.

Visitor demo spaces retain three independently seeded projects: **Grey Harbor Echoes**, **Paper Moon Archive**, and **Midnight Garden**. New registered accounts instead receive the isolated **Grey Harbor Echoes** tutorial sample described above. Project data, Memory, drafts, and review state remain isolated per account and per project.

## Product and safety boundaries

- The FastAPI backend covers registered and visitor authentication, recovery-email verification and password reset, projects, story context, imports, drafts, checks, Evidence, decisions, ChangeSets, Reset, quotas, and visitor cleanup.
- Every project resource is checked against the current session and project ownership. Cross-account access returns a not-found response without disclosing the resource.
- Evidence must resolve to a SourceSpan owned by the active project. Unresolvable Evidence fails closed.
- Continuity and Memory Delta work use an observable Agent Run lifecycle: `queued`, `running`, `completed`, `timed_out`, `failed`, or `cancelled`. Retry and Cancel preserve lineage, and non-completed runs do not create partial Issues, Decisions, or Memory updates.
- Public-mode configuration fails closed. Provider and SMTP credentials remain server-only; visitors receive isolated, time-limited spaces with server-enforced workflow, provider-attempt, text-length, and budget limits.
- An explicitly configured `DeepSeekProvider` supports real local checks. When no production provider is configured, a check returns `503 provider_unavailable`; it does not create a Run or substitute a static result.
- Reset is project-scoped, confirmed, idempotent, and constrained to this demo's runtime database.

## Evaluation and verification

The public product story is organised around six milestones. Historical Stage identifiers remain available as technical evidence references rather than the primary product narrative.

| Product milestone | Verified outcome | Technical evidence |
| --- | --- | --- |
| MVP Build & Web Demo | Local end-to-end author review workflow, project isolation, Reset, and reproducible browser evidence | Stages 4–7 |
| Author Workflow & Model Evaluation | Author-controlled Memory decisions and frozen V4–V8 evaluation records | Stages 8–10 |
| Long-form Workflow Validation | Real 100k- and 300k-character workflow validation with bounded retrieval and resolvable Evidence | Stage 11 |
| Agent Reliability | Six-state Agent Run lifecycle, provenance, Retry/Cancel, and zero partial business writes on non-completion | Stage 12 |
| Web App Readiness | Visitor isolation, quotas, cleanup, recovery contracts, reproducible packaging, and browser/security verification | Stage 13 |
| Public Release v1.0 | Historical signed baseline after the frozen Required Gates A–G passed at the public origin | Stage 14 |
| Product Iteration v1.2.0 | Isolated first-run tutorial, durable progress, responsive authoring UI, bitmap narrative assets, local regression acceptance, and active public deployment | v1.2.0 tests and production smoke acceptance |

The published repository baseline is the frozen **V4** set: 15 original, balanced three-class cases across three isolated corpora, plus 6 stability reruns. All 21 runs completed.

| Measure | V4 result |
| --- | ---: |
| Accuracy / macro F1 | 1.0000 / 1.0000 |
| Conflict recall / insufficient-evidence recall | 1.0000 / 1.0000 |
| No-conflict false-positive rate | 0.0000 |
| Hit@5 / cited Evidence precision / Evidence resolvability | 1.0000 / 1.0000 / 1.0000 |
| Schema validity / fail-closed safety | 1.0000 / 1.0000 |
| Latency p50 / p95 | 2593 ms / 4104 ms |
| Tokens, input / output | 16037 / 2183 |
| Cost | unavailable |

Across the three stability cases, decision stability and category/severity stability were 3/3; Evidence-ID-set stability was 2/3 and exact-explanation-hash stability was 1/3. Two cases retained a correct class with a category mismatch: `timeline → event_status` and `world_rule → event_status`.

The frozen CLI PoC has a separate historical held-out result (F1 0.9412) under a different protocol. It is not the V4 Web Demo evaluation and is not rerun by this repository.

V5–V8 each retain one immutable first-valid formal result bundle with `gate_failed`; later work does not overwrite or rerun them. In V8, all 30 calls completed and all core classification and Evidence measures were 1.0000, but the designated category regression was 2/3 because one `location_action` case was classified as `event_status`. This single category deviation is retained as a portfolio-level known limitation, while the Model Evaluation Gate recorded under Stage 10 remains failed.

Long-form Workflow Validation, recorded under Stage 11, verified the author-controlled workflow on a real 100k-character prefix and a 300k-character prefix. The accepted 300k V2 result completed initialization plus two append/review/decision/commit rounds with bounded RAG, valid Evidence lineage, no automatic canon writes, and a 4,820,992-byte final SQLite database. The first 300k V1 capacity failure remains immutable alongside the V2 pass. The optional 1M-character Stage 11N pressure test has not been run.

Agent Reliability, recorded under Stage 12, independently passed the six-state Agent Run lifecycle, provenance, Retry/Cancel, and zero-partial-write Gates in V2; its V1 Provider-boundary incident remains `gate_failed`. Web App Readiness, recorded under Stage 13, independently passed its local product Gate in V4 after preserving the V2/V3 deployment-artifact failures: server-only integration boundaries, visitor isolation, limits and cleanup, real recovery contracts, two reproducible standalone builds, relocation, and the full browser matrix were verified without external Provider HTTP or SMTP. The historical v1.0 Public Release passed HTTPS/security, real SMTP/password recovery, restart persistence, backup/same-release redeploy, a real-provider two-round author workflow, visitor and registered-account isolation, quota separation, visitor cleanup, and public Cancel/Timeout/Retry atomicity checks. The active Tencent Cloud deployment is now v1.2.0; its post-deployment acceptance covered health/readiness, rollback state, desktop/mobile rendering, new-account tutorial isolation and persistence, and the empty real-workspace result without rerunning the external Provider workflow.

Read [the verification record](docs/verification-and-limitations.md) for evidence scope and limitations, and [the product decisions record](docs/product-decisions-and-validation.md) for the rationale behind the workflow.

## Technology

- Backend: Python, FastAPI, Uvicorn, SQLite, `httpx`
- Frontend: Next.js App Router, React, TypeScript
- Verification: `unittest`, Playwright, axe-core, ESLint, TypeScript
- Provider integration: DeepSeek-compatible HTTP API, configured only through process environment variables

## Repository layout

```text
backend/       API, SQLite schema/migration, seed data, and contract tests
frontend/      Next.js workspace and browser E2E tests
evaluation/    frozen V4 case set, manifests, validators, tests, and sanitised results
docs/          local setup, demo guide, product decisions, and verification record
artifacts/     a small, curated set of production-workflow screenshots
```

## Run locally on Windows

From the repository root in PowerShell:

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -r backend\requirements.txt

Set-Location frontend
npm ci
Set-Location ..
```

Start the backend in one terminal:

```powershell
Set-Location backend
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
$env:TRUSTED_HOSTS = '127.0.0.1:8000'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000'
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal:

```powershell
Set-Location frontend
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
npm run dev
```

Open `http://127.0.0.1:3000`. The frontend rewrites same-origin `/api` requests to `http://127.0.0.1:8000` by default. See [local setup and reproduction](docs/local-setup.md) for health checks, isolated E2E startup, and provider configuration boundaries.

## Test

```powershell
# Backend contract and regression suite
Set-Location backend
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
$env:TRUSTED_HOSTS = '127.0.0.1:8000,testserver'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000,http://testserver'
& ..\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Public evaluation package checks; no provider calls
Set-Location ..
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v2
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v3
& .venv\Scripts\python.exe -m evaluation.validate_eval_set_v4
& .venv\Scripts\python.exe -m evaluation.validate_release_bundle
& .venv\Scripts\python.exe -m unittest discover -s evaluation\tests -v

# Frontend static gates
Set-Location frontend
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
npm run lint
npm run typecheck
npm run build
```

The backend suite includes the Agent Reliability lifecycle and Web App Readiness security contracts, recorded under Stages 12 and 13. The release-bundle validator checks that the published V4 results, frozen assets, recorded workspace metadata, documentation, and screenshots are self-consistent; it does not claim to reopen unpublished SQLite workspaces. Browser E2E requires the isolated FastAPI/Next.js processes described in [the local setup guide](docs/local-setup.md); it uses a test-only provider and a temporary database rather than the local demo database.

## Core author workflow

The [3–5 minute demo guide](docs/demo-guide.md) walks through project selection, a completed continuity review, Evidence, author confirmation, and Reset. The guide does not require provider calls.

## Known limitations

- The signed Stage 14 production baseline remains `Story Continuity Copilot v1.0 Public Release` as historical evidence, while the active public deployment and current repository source are v1.2.0. The v1.2.0 operational/browser acceptance does not re-sign Stage 14, constitute a commercial SLA, or claim that the retained Stage 10 `gate_failed` evaluation was later passed.
- Real SMTP delivery, email verification, password reset, old-session revocation, new-password login, and used-link replay rejection have been accepted at the public origin. Email credentials and addresses remain server-only.
- V4 is a small, frozen product evaluation; it supports the stated evaluation claims only and is not a general benchmark.
- Real provider output can vary. The retained stability evidence shows variation in Evidence IDs and exact explanation hashes even where decision and category/severity were stable.
- The provider returns no cost in the retained V4 results.
- The system supports continuity review and author-controlled canon updates; it does not directly continue the novel.

## Further reading

- [Local setup and reproduction](docs/local-setup.md)
- [3–5 minute demo guide](docs/demo-guide.md)
- [Product decisions and evidence](docs/product-decisions-and-validation.md)
- [Validation evidence and known limitations](docs/verification-and-limitations.md)
- [Curated verification artifacts](artifacts/README.md)
