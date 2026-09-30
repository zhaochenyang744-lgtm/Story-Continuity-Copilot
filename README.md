# Story Continuity Copilot v1.4.0

The active product is **Story Continuity Copilot v1.4.0**. It adds canonical author materials and comparisons, unified planning and authoring pages, rich-text and immersive writing, and stricter AI evidence contracts to the author workflow. The author owns the prose and every canon decision.

The active online release is `ui-cbfa536-20260930`, deployed on 2026-09-30 from Git commit `cbfa536` (see [2026-09-30 update](#2026-09-30-update) below). The previous releases `longform-aac1517-20260930`, `longform-bd090fe-20260930` and `maint-e2d141c23d0c-20260913` remain on the server as rollback targets; the [maintenance deployment record](docs/maintenance-deployment.md) and the [2026-09-08 deployment record](docs/v1.4.0-deployment.md) remain historical evidence. The npm package keeps the technical version `0.1.0`; product version and package version are intentionally separate.

The canonical product description is [current product and verification scope](docs/current-product.md). The [maintenance acceptance record](docs/maintenance-acceptance.md) separates local verification from the bounded production checks. The September maintenance update adds saved-work exports, reversible author-decision reuse, full-chapter revision with fact review, and independent operations tools. The [v1.3.0 product contract](docs/v1.3.0-product.md), writing-analysis, [character-alias and change-impact](docs/v1.3.0-character-alias-impact.md), [bounded revision plan](docs/v1.3.0-revision-plan.md), and Memory-delta documents remain historical or focused technical appendices. Current source packaging uses the [maintenance release manifest](docs/maintenance-release-manifest.json); the [v1.3 allowlist](docs/v1.3.0-release-allowlist.json) records its historical release scope. Current documentation was updated after the deployed source package was frozen; it does not change that archive or image identity.

The signed Stage 14 public-production baseline remains **Story Continuity Copilot v1.0 Public Release** as a historical evidence baseline. Historical Stage numbers, release IDs, the technical package name `story-continuity-app`, component API versions, and the compact in-product wordmark `Story Continuity` remain unchanged for evidence traceability and runtime compatibility.

## 2026-09-30 update

The late-September releases are each built from a Git commit with the maintenance source packager and deployed with `deployment/release.sh`. None changes the database schema.

**Long chapters (`longform-bd090fe`, then `longform-aac1517`)**
- Continuity review uses `deepseek-flash` with high thinking. A check's review batches are dispatched in parallel (4 at a time in production, 1 locally for reproducibility), with at most four claims per batch.
- Each evidence span is sent once per request and referenced by ID; a request over the input budget is split in half instead of failing.
- One undecidable claim no longer discards the rest of the chapter. On production, a 37-claim chapter that previously failed after 240 s completed in 72.5 s ([record](evaluation/results/prod-longform-after-bd090fe-20260930.json)).
- Quota: a check the remaining provider quota cannot cover is refused before any call (HTTP 429, `provider_attempt_quota_insufficient`, with the claim count and roughly how many claims still fit). If the quota runs out mid-chapter, claims already judged are kept and the rest are reported as undecided.

**Interface (`ui-cbfa536`)**
- Quota messages speak in credits ("点数不足") instead of model calls or provider attempts.
- New outlined logo (a single continuous line of text) and favicon; three type faces only (UI, manuscript serif, identifiers); one line-icon set, including arrows and external links.
- Internal wording and debug counters are gone from author screens: Story Memory versions read "事实库第 N 版", run ids, byte counts and empty `V0` counters are not shown, and "Reset" reads "重置当前作品".
- Layout fixes: the writing page has one title and one save status, and the editor fills its card beside the issue pane; the overview export panel, Story Memory table columns, immersive issue list, planning empty states and evidence-drawer actions were corrected; the sources page groups spans under their chapter; the edit-project dialog matches the other dialogs.
- A missing project or unknown address shows a "找不到" page with a way back. Phone form fields stay at 16 px so iOS does not zoom on focus; scrolling tab rails fade the edge that hides more items.

Verification for `ui-cbfa536`: backend 456/456, evaluation 51/51, lint, typecheck and build passed locally on Windows; results that need a model (briefs, plan alignment, checks in progress or failed, imports, Memory review) were opened with the real provider and screenshotted at 1440 px and 390 px. The public site was checked by hand after deployment. Browser E2E suites were not green; see [Known limitations](#known-limitations).

## v1.3.0 workflow foundation (included in v1.4.0)

- Author Context stores editable future plans for story structure, characters, and world rules; it never proves that prose was written.
- Character aliases are author-confirmed, versioned identity records; change-impact analysis binds them with draft, source, Memory, and Author Context state and never auto-writes a proposal.
- Saved drafts and SourceSpans store written material. Story Memory stores only author-confirmed facts. AI output stays in analysis Runs and candidates until the author decides.
- Writing adds a bounded chapter brief and saved-draft plan-alignment check. Story Memory adds new, changed, and invalidated fact review with resolvable Evidence.
- Authors can select current continuity Issues, generate one bounded Evidence-backed revision suggestion per Issue, accept or edit suggestions into persistent tasks, manually revise and save the same draft, then explicitly recheck. Task progress never resolves Issues or changes canon.
- Accepted Memory decisions create one immutable Memory version and one auditable ChangeSet atomically. Rejected or empty reviews close source coverage without version growth.
- The desktop global rail can collapse persistently, wide operational surfaces use the available canvas, and the author profile prioritises real works, chapter and word totals, and continue-writing access before secondary display-name and bundled-avatar settings.
- Desktop supports authoring and review. A 390 px viewport remains browse-only with the reason shown, sources available, and no horizontal overflow.
- Writing and Checking includes a desktop immersive manuscript overlay with shared unsaved draft state, explicit save only, adjustable typography and column width, and a collapsible continuity-issue rail.

The repository is designed for local reproduction. It contains the application source, migration and seed logic, tests, sanitised V4–V8 evaluation result records, and a small set of production-workflow screenshots. It does not include runtime databases, environment files, provider credentials, raw provider responses, recorded runtime prompt bodies, chain-of-thought, or protected evaluation assets. Full V5–V8 post-run database-hash validation therefore also requires the separately retained local evaluation workspaces; the committed result files alone do not recreate those SQLite artifacts.

## v1.2.0 update

- New registered accounts receive one isolated tutorial sample instead of three preset real works. The sample is excluded from real-work counts, search, recent works, and pending-issue summaries; completing or skipping the tutorial returns the account to an empty real workspace.
- The tutorial is a five-step author workflow covering Story Memory sources, continuity issues, Evidence, and an explicit Author Decision. Business progress is stored on the backend with version binding, CSRF protection, idempotency, monotonic revisions, and cross-login restoration; transient hints and focus effects remain client-only.
- The non-login workspace uses a wider, responsive authoring layout, a compact mobile read-only mode, clearer page actions and empty states, reduced nested framing, and three locally bundled WebP narrative assets instead of large illustrative SVG compositions.
- Independent local acceptance passed the backend suite (156/156), the v1.2 browser workflow (1/1), the frozen v1.1 regression (5/5), frontend contracts (27/27), lint, typecheck, and the production build.

## Public deployment

- Active origin: [https://43-160-207-57.sslip.io](https://43-160-207-57.sslip.io)
- Active version: **Story Continuity Copilot v1.4.0**
- Production release ID: `ui-cbfa536-20260930` (Git commit `cbfa5368dc0eb06d2241b423001ba2ddf6838108`)
- Source inventory SHA256: `d3551e4a4ec75e174f358011c4ae37769b0b66b49f4df45ff35bc6f9b269bc14` (94 files)
- Deployment date: 2026-09-30; rollback target `longform-aac1517-20260930`
- The notes below describe the 2026-09-13 maintenance release (`maint-e2d141c23d0c-20260913`, inventory `e2d141c23d0ccab25ccf1fd24b7f0ea0821493a6f892c7b784680f7f492b0402`), whose schema and operations setup the later releases keep.
- Isolated migration rehearsal and live comparison before browser acceptance preserved all 67 preexisting business tables and 661 rows. Schema is 146; integrity and foreign-key checks passed. Pre-deployment and post-deployment backups were manually downloaded to the operator workstation and independently hashed.
- Public browser acceptance passed seven checks, including actual TXT/Markdown/ZIP downloads, maintenance-page chapter content, a revision guard rejecting changes, mobile read-only layout, and fresh JS/CSS loads. It did not rerun successful revision commits, decision reuse, or external AI calls online; those retain their separate local evidence.
- Three operations timers are enabled; first-run checks and a subsequent monitor cycle were observed. The user has deferred automated off-instance replication and external alert delivery as optional follow-up work; the missing-copy warning remains visible. Old images are retained, but targets without the schema146 workflow contract are rejected; no actual rollback was performed. See the [deployment scope and limitations](docs/maintenance-deployment.md).

## Product overview

The author workflow is:

1. Sign in locally, create or import a project, and select a project workspace.
2. Review outline, characters, world rules, chapters, and versioned Story Memory.
3. Submit the current draft for a continuity check.
4. Inspect each finding together with resolvable Evidence from the current project.
5. Accept, reject, or edit proposed Memory changes. A ChangeSet records the decision; only accepted changes update canon.
6. Use "重置当前作品" (project Reset) to restore the seeded review path when a fresh demonstration is needed.

Visitor demo spaces retain three independently seeded projects: **Grey Harbor Echoes**, **Paper Moon Archive**, and **Midnight Garden**. New registered accounts instead receive the isolated **Grey Harbor Echoes** tutorial sample described above. Project data, Memory, drafts, and review state remain isolated per account and per project.

## Product and safety boundaries

- The FastAPI backend covers registered and visitor authentication, recovery-email verification and password reset, projects, story context, imports, drafts, checks, Evidence, decisions, ChangeSets, Reset, quotas, and visitor cleanup.
- Every project resource is checked against the current session and project ownership. Cross-account access returns a not-found response without disclosing the resource.
- Evidence must resolve to a SourceSpan owned by the active project. Unresolvable Evidence fails closed.
- Continuity, revision-plan, and Memory Delta work use an observable Agent Run lifecycle: `queued`, `running`, `completed`, `timed_out`, `failed`, or `cancelled`. Retry and Cancel preserve lineage, and non-completed runs do not create partial Issues, revision tasks, Decisions, or Memory updates.
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
| Product Iteration v1.2.0 | Isolated first-run tutorial, durable progress, responsive authoring UI, bitmap narrative assets, local regression acceptance, and historical public deployment | v1.2.0 tests and production smoke acceptance |

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

Agent Reliability, recorded under Stage 12, independently passed the six-state Agent Run lifecycle, provenance, Retry/Cancel, and zero-partial-write Gates in V2; its V1 Provider-boundary incident remains `gate_failed`. Web App Readiness, recorded under Stage 13, independently passed its local product Gate in V4 after preserving the V2/V3 deployment-artifact failures: server-only integration boundaries, visitor isolation, limits and cleanup, real recovery contracts, two reproducible standalone builds, relocation, and the full browser matrix were verified without external Provider HTTP or SMTP. The historical v1.0 Public Release passed HTTPS/security, real SMTP/password recovery, restart persistence, backup/same-release redeploy, a real-provider two-round author workflow, visitor and registered-account isolation, quota separation, visitor cleanup, and public Cancel/Timeout/Retry atomicity checks. The previous v1.2.0 deployment acceptance covered health/readiness, rollback state, desktop/mobile rendering, new-account tutorial isolation and persistence, and the empty real-workspace result without rerunning the external Provider workflow.

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

# Isolated v1.3.0 production-standalone acceptance on 3197/8197
# Each run prints its unique last-run.json, HTML report, and Provider statistics paths.
npm run test:v130
```

`test:v130` builds from an explicit temporary source copy that excludes environment files, copies `public` and compiled static assets into the standalone artifact, waits for HTML, key JavaScript chunks, and same-origin session bootstrap, then runs all `v130-*.spec.ts` tests. The profile fails closed on wrong ports, temporary roots, dist directories, account prefixes, or mixed origins. It does not use the v1.2 evidence directory or the independent 3196/8196 acceptance services.

The backend suite includes the Agent Reliability lifecycle and Web App Readiness security contracts, recorded under Stages 12 and 13. The release-bundle validator checks that the published V4 results, frozen assets, recorded workspace metadata, documentation, and screenshots are self-consistent; it does not claim to reopen unpublished SQLite workspaces. Browser E2E requires the isolated FastAPI/Next.js processes described in [the local setup guide](docs/local-setup.md); it uses a test-only provider and a temporary database rather than the local demo database.

## Core author workflow

The [3–5 minute demo guide](docs/demo-guide.md) walks through project selection, a completed continuity review, Evidence, author confirmation, and Reset. The guide does not require provider calls.

## Known limitations

- The signed Stage 14 production baseline remains `Story Continuity Copilot v1.0 Public Release` as historical evidence. The active public deployment is the v1.4.0 maintenance update; its deployment and acceptance scope are recorded in [maintenance deployment](docs/maintenance-deployment.md). Local acceptance does not re-sign Stage 14, constitute a commercial SLA, or claim that the retained Stage 10 `gate_failed` evaluation was later passed.
- Real SMTP delivery, email verification, password reset, old-session revocation, new-password login, and used-link replay rejection have been accepted at the public origin. Email credentials and addresses remain server-only.
- V4 is a small, frozen product evaluation; it supports the stated evaluation claims only and is not a general benchmark.
- Real provider output can vary. The retained stability evidence shows variation in Evidence IDs and exact explanation hashes even where decision and category/severity were stable.
- The provider returns no cost in the retained V4 results.
- The system supports continuity review and author-controlled canon updates; it does not directly continue the novel.
- Browser E2E suites lag the current interface. `test:v130` fails the same 12 tests on `aac1517` and on `ui-cbfa536`, and several `stage*` and `v110` specs still expect the pre-v1.4 create form, textarea drafts and seeded flows. These failures predate the 2026-09-30 interface work; updating the suites is open work.
- `test:build-origin` has one known failure ("canonical HTTPS proxy exposes public health…").
- With the real model, some Story Memory change-set reviews for long appended chapters fail backend validation (`candidate_count_invalid`, `memory_type_invalid`), and a long check can occasionally fail with unresolvable evidence. Both are model-output issues, not interface faults.
- Writing and checking are desktop-only; below 1024 px the workspace is browse-only.

## Further reading

- [Local setup and reproduction](docs/local-setup.md)
- [3–5 minute demo guide](docs/demo-guide.md)
- [Product decisions and evidence](docs/product-decisions-and-validation.md)
- [Validation evidence and known limitations](docs/verification-and-limitations.md)
- [Curated verification artifacts](artifacts/README.md)
