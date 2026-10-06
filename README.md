# Story Continuity Copilot v1.6.1

The current product is **Story Continuity Copilot v1.6.1**, a patch on the v1.6.0 long-text release that adds server-side draft autosave and three fixes (see [v1.6.1](#v161)). v1.6.0 brought screened checking built for real chapters, checking chosen written chapters, character-based quotas, a chapter timeline, checkable imports including Word files, and author-facing polish (see [v1.6.0](#v160)). v1.5.2 made a check report insufficient evidence and name the missing link instead of staying silent, and retry an over-long answer claim by claim instead of failing (see [v1.5.2](#v152)). Only the three latest versions are described here; earlier releases are kept in the Git tags and the records under `docs/`. The author owns the prose and every canon decision.

The active online release is `v161-edd821a-20261006`, deployed on 2026-10-06 from Git tag `v1.6.1` (commit `edd821a`; see the [v1.6.1 deployment record](docs/deployment-2026-10-06-v161.md)). `v160-ef7341e-20261006` ([record](docs/deployment-2026-10-06.md)) and `v152-1cfee10-20261004` ([record](docs/deployment-2026-10-04.md)) remain on the server as rollback targets. The npm package keeps the technical version `0.1.0`; product version and package version are intentionally separate.

The canonical product description is [current product and verification scope](docs/current-product.md). Versioned contracts and acceptance records for earlier releases remain under `docs/` as historical appendices. Current source packaging uses the [maintenance release manifest](docs/maintenance-release-manifest.json).

The signed Stage 14 public-production baseline remains **Story Continuity Copilot v1.0 Public Release** as a historical evidence baseline. Historical Stage numbers, release IDs, the technical package name `story-continuity-app`, component API versions, and the compact in-product wordmark `Story Continuity` remain unchanged for evidence traceability and runtime compatibility.

## v1.6.1

v1.6.1 is a patch on v1.6.0: the draft now saves to the server on its own, and three faults found while accepting v1.6.0 are fixed. No schema change and no new tables.

- **Server-side autosave.** A few seconds after typing stops (5 s idle, at most once every 30 s), the draft is saved to the server in the background. The editor stays editable, and text typed during a save is kept. The device's local recovery copy remains the offline fallback. If a newer version was saved elsewhere, autosave pauses instead of overwriting it: the text stays on this device and the author is asked to reload and compare. Controlled edits, pending decisions and recovery conflicts still use the explicit save button, because their save records an author decision. The save summary shows 保存中, 已保存, 未保存 (with a note that it will save shortly), 自动保存失败 or 自动保存已暂停.
- **Chapter timeline counts checked drafts.** A draft checked before it was completed now shows as checked, and so does the chapter it becomes. Before the fix it was listed as not checked.
- **Works list shows length.** Each work shows its chapter count and character count instead of the fact-base version number.
- **Check readiness on the overview.** Any work with at least one chapter shows "可以检查". Before, works without a coverage record said a chapter still had to be written or imported.
- **Known limitation, not changed:** in about one check in nine, the 灰港回声 sample draft reports "决定先核对那声不该响起的雾钟" as a confirmed world-rule conflict (0 of 8 in a local reproduction). The formally validated review prompt v25g is kept rather than changed without a new gate.
- Verification: backend 554/554; browser E2E `npm run test:e2e` 129/129 in 8 groups (two new autosave tests: a save after typing stops, and a pause instead of an overwrite when another device saved first); evaluation 77/77; ESLint and TypeScript clean (ESLint is now part of every release check; three lint errors had shipped in v1.6.0).

## v1.6.0

v1.6.0 is the long-text release: checks are built for real chapters of about 2,500 characters instead of one-to-three-sentence drafts. It also brings the author-facing polish found in the October product review. Database schema stays at 146; startup adds two tables (character usage and sample-work seed state) and no existing table changes shape.

- **Screened checking.** A cheap non-thinking screen reads the whole chapter and flags the sentences worth a careful look; a scored triage ranks the rest; only flagged sentences get a thinking review, one sentence per request, against passages of earlier chapters (passage index with a fact route). Key sentences the first review passes get one independent second review that watches for missing links. Per chapter at most 5 key reviews, 2 second reviews and 3 escalations. Review prompt `continuity-review-v25g-screened-presupposed-links-bounded-knowledge-rule-category` with `continuity-screen-v1` and `continuity-triage-v3-presupposed-links`. Short drafts use the same review rules.
- **Formal long-text gate passed.** One run on a fresh 26-chapter formal set (`lf2-formal`, written in a separate session, never read during development) met every pre-registered bar: conflict recall 1.00, insufficient-evidence recall 0.83, category accuracy 1.00, designated regressions 3/3, trap false positives 0, clean chapters without a card 78%, per chapter median 40 s / p90 76 s, mean ¥0.21 / max ¥0.46 at DeepSeek billed rates. The first formal run (`lf1-formal` plus the short-text set V13) failed on insufficient-evidence recall and maximum cost; both sets were retired and the gate change is recorded in `evaluation/longform/PLAN.md`.
- **Check chosen chapters.** On the chapter-management page an author ticks up to eight written chapters and checks them together; each chapter is judged against earlier chapters only, and the report is grouped by chapter. The estimate (characters and expected cost) is shown before anything is spent. Visitors see a labelled sample report instead. Whole-book checks are not offered yet (about ¥25–30 for a 300,000-character book).
- **Character quotas.** Registered authors check up to 60,000 characters and run one whole-book import per rolling 24 hours; visitors check one chapter of up to 3,000 characters at a time. The workspace shows what a check will spend and what is left. Provider-dispatch counts remain only as a runaway backstop.
- **One chapter timeline.** Written chapters and the current draft are listed in order with their check status: checked, not checked, edited after its check, or basis changed (an earlier chapter was revised after the check).
- **Imports are checkable at once.** With the screened pipeline the written text is the evidence, so an imported work can be checked before its fact base is built or reviewed; confirmed facts make retrieval sharper. Word (`.docx`) files import by their Heading 1 / Heading 2 styles.
- **Author-facing polish.** Plain wording instead of version, snapshot and commit jargon; "高影响 / 中等影响 / 低影响" everywhere; genres matching the samples; an empty draft cannot be checked; the "更多" menu closes on Escape and keeps reset apart; written material opens before empty plans; finished checks shrink to a one-line record; an honest tutorial-complete page; a narrow-screen note on the home and works pages.
- **Sample works stay current.** Sample chapters now carry short bodies, and a startup step brings every account's untouched sample works up to the current seed; works the author changed are left as they are.
- Verification: backend 553/553; browser E2E `npm run test:e2e` 127/127 in 8 groups; evaluation 77/77. A copy of the production database was upgraded locally: integrity and foreign keys intact, all nine untouched sample works refreshed, tutorial works byte-identical, a second start changes nothing, and v1.5.2 opens the upgraded database (rollback needs no restore).

## v1.5.2

- Insufficient evidence is reported, never answered with silence: a claim that settles a point the supplied material leaves open returns an insufficient-evidence issue that names the missing link (review prompt `continuity-review-v24c-explicit-missing-link`). Evidence selection gives two of the three slots to the passages that match a claim's own words best. The single V12 held-out run passed every pre-registered threshold: macro F1 0.972, insufficient-evidence recall 1.0, conflict recall 0.917, no false positives, designated regressions 3/3 (`evaluation/ie_fix_v24/PLAN.md`).
- v1.5.1 went live on 2026-10-03 and was rolled back the same day. Two checks in a row of the 灰港回声 demo draft (four short claims in one batch) failed as output_truncated: thinking filled its 16,000-token cap at high and at medium effort, and the final non-thinking answer (2,000 tokens) overflowed as well, because the draft's missing link is now reported as an insufficient-evidence issue. The V11/V12 cases are one to three sentences, so the held-out run never packed a reported gap with three other verdicts.
- A batch that still ends on a length stop is now retried one claim at a time. A single claim that still overflows is reported as undecided, and the rest of the check completes; a check where every claim is undecided still fails. The truncated dispatch stays in the usage totals.
- Verification: the same demo draft with the real model completed four checks out of four (58–150 s; one of the four missed the insufficient-evidence issue), and once more on the public site after deployment (204 s); a V11 regression run gave conflict recall 1.0, insufficient-evidence recall 0.917 and no false positives; backend 471/471; browser E2E 124/124. The V12 result for the review prompt still applies, since the prompt is unchanged.

## Public deployment

- Active origin: [https://43-160-207-57.sslip.io](https://43-160-207-57.sslip.io)
- Active version: **Story Continuity Copilot v1.6.1**
- Production release ID: `v161-edd821a-20261006` (Git tag `v1.6.1`, commit `edd821a2be934da93a71fffa71b8798feef8f505`)
- Source inventory SHA256: `113b6880a3d53c3d61d84a4c013d8d6a8645e53bc30fa70216704837493d11c8` (105 files)
- Deployment date: 2026-10-06; rollback target `v160-ef7341e-20261006`; record: [v1.6.1 deployment](docs/deployment-2026-10-06-v161.md)
- Three operations timers are enabled; first-run checks and a subsequent monitor cycle were observed. The user has deferred automated off-instance replication and external alert delivery as optional follow-up work; the missing-copy warning remains visible. Old images are retained, but targets without the schema146 workflow contract are rejected; no actual rollback was performed. See the [deployment scope and limitations](docs/maintenance-deployment.md).

## Product overview

The author workflow is:

1. Sign in locally, create or import a project, and select a project workspace.
2. Review outline, characters, world rules, chapters, and versioned Story Memory.
3. Submit the current draft for a continuity check, or tick up to eight written chapters and check them together.
4. Inspect each finding together with resolvable Evidence from the current project.
5. Accept, reject, or edit proposed Memory changes. A ChangeSet records the decision; only accepted changes update canon.
6. Use "重置当前作品" (project Reset) to restore the seeded review path when a fresh demonstration is needed.

Visitor demo spaces retain three independently seeded projects: **Grey Harbor Echoes**, **Paper Moon Archive**, and **Midnight Garden**. New registered accounts instead receive an isolated **Grey Harbor Echoes** tutorial sample: a five-step guided workflow, excluded from real-work counts, whose progress is stored on the backend. Project data, Memory, drafts, and review state remain isolated per account and per project.

## Product capabilities

- Author Context stores editable future plans for story structure, characters, and world rules; it never proves that prose was written.
- Character aliases are author-confirmed, versioned identity records; change-impact analysis binds them with draft, source, Memory, and Author Context state and never auto-writes a proposal.
- Saved drafts and SourceSpans store written material. Story Memory stores only author-confirmed facts. AI output stays in analysis Runs and candidates until the author decides.
- Writing adds a bounded chapter brief and saved-draft plan-alignment check. Story Memory adds new, changed, and invalidated fact review with resolvable Evidence.
- Authors can select current continuity Issues, generate one bounded Evidence-backed revision suggestion per Issue, accept or edit suggestions into persistent tasks, manually revise and save the same draft, then explicitly recheck. Task progress never resolves Issues or changes canon.
- Accepted Memory decisions create one immutable Memory version and one auditable ChangeSet atomically. Rejected or empty reviews close source coverage without version growth.
- The desktop global rail can collapse persistently, wide operational surfaces use the available canvas, and the author profile prioritises real works, chapter and word totals, and continue-writing access before secondary display-name and bundled-avatar settings.
- Writing and review need a desktop width (1024 px or more). Narrower viewports are browse-only, with the reason shown, sources available, and no horizontal overflow.
- Writing and Checking includes a desktop immersive manuscript overlay with shared draft state, adjustable typography and column width, and a collapsible continuity-issue rail. Since v1.6.1 the draft saves to the server a few seconds after typing stops; the device's recovery copy remains the offline fallback.

The repository is designed for local reproduction. It contains the application source, migration and seed logic, tests, sanitised evaluation result records (V4–V12 and the long-text gates), and a small set of production-workflow screenshots. It does not include runtime databases, environment files, provider credentials, raw provider responses, recorded runtime prompt bodies, chain-of-thought, or protected evaluation assets. Full V5–V8 post-run database-hash validation therefore also requires the separately retained local evaluation workspaces; the committed result files alone do not recreate those SQLite artifacts.

## Product and safety boundaries

- The FastAPI backend covers registered and visitor authentication, recovery-email verification and password reset, projects, story context, imports, drafts, checks, Evidence, decisions, ChangeSets, Reset, quotas, and visitor cleanup.
- Every project resource is checked against the current session and project ownership. Cross-account access returns a not-found response without disclosing the resource.
- Evidence must resolve to a SourceSpan owned by the active project. Unresolvable Evidence fails closed.
- Continuity, revision-plan, and Memory Delta work use an observable Agent Run lifecycle: `queued`, `running`, `completed`, `timed_out`, `failed`, or `cancelled`. Retry and Cancel preserve lineage, and non-completed runs do not create partial Issues, revision tasks, Decisions, or Memory updates.
- Public-mode configuration fails closed. Provider and SMTP credentials remain server-only; visitors receive isolated, time-limited spaces with server-enforced workflow, provider-attempt, text-length, and budget limits.
- An explicitly configured `DeepSeekProvider` supports real local checks. When no production provider is configured, a check returns `503 provider_unavailable`; it does not create a Run or substitute a static result.
- Reset is project-scoped, confirmed, idempotent, and constrained to this demo's runtime database.

## Evaluation and verification

The public product story is organised around the milestones below. Historical Stage identifiers remain available as technical evidence references rather than the primary product narrative.

| Product milestone | Verified outcome | Technical evidence |
| --- | --- | --- |
| MVP Build & Web Demo | Local end-to-end author review workflow, project isolation, Reset, and reproducible browser evidence | Stages 4–7 |
| Author Workflow & Model Evaluation | Author-controlled Memory decisions and frozen V4–V8 evaluation records | Stages 8–10 |
| Long-form Workflow Validation | Real 100k- and 300k-character workflow validation with bounded retrieval and resolvable Evidence | Stage 11 |
| Agent Reliability | Six-state Agent Run lifecycle, provenance, Retry/Cancel, and zero partial business writes on non-completion | Stage 12 |
| Web App Readiness | Visitor isolation, quotas, cleanup, recovery contracts, reproducible packaging, and browser/security verification | Stage 13 |
| Public Release v1.0 | Historical signed baseline after the frozen Required Gates A–G passed at the public origin | Stage 14 |
| Product Iteration v1.4–v1.5 | Author materials, exports, decision reuse, chapter revision with fact review, parallel long-chapter checks, the new interface, explicit insufficient-evidence reporting; V10 and V12 held-out gates passed | Held-out results below; backend 471/471; browser E2E 124/124 |
| Long-text release v1.6 | Screened checking of real ~2,500-character chapters, chosen-chapter checks, character quotas, chapter timeline, Word import, server-side draft autosave; long-text formal gate passed on `lf2-formal` | Long-text results below; v1.6.1: backend 554/554, browser E2E 129/129, evaluation 77/77 |

Every model change is decided by one formal run on a set written in a separate session and never read during development, with thresholds registered before the set was authored; a set is spent once it has been run.

### Long-text gate (current)

The current product (v1.6) is judged on long-text formal sets, because real chapters are about ten times longer than the short-draft sets below: real-length chapters checked against earlier chapters, with thresholds for recall, false positives, time and cost registered before the set was written ([plan](evaluation/longform/PLAN.md)).

| Long-text formal set | Configuration | Result |
| --- | --- | --- |
| `lf1-formal` + short-text V13 (2026-10-05) | screened pipeline, first caps | Failed on insufficient-evidence recall and maximum cost; both sets retired |
| `lf2-formal` (2026-10-05, 26 chapters) | prompt v25g, caps 5/2/3, shipped in v1.6.0/v1.6.1 | Passed every registered threshold: conflict recall 1.00, insufficient-evidence recall 0.83, category accuracy 1.00, designated regressions 3/3, trap false positives 0, clean chapters without a card 78%, median 40 s / p90 76 s, mean ¥0.21 / max ¥0.46 |

### Short-draft held-out sets

From V9 to V12, model changes were judged on short-draft held-out sets: 36 cases per set (12 conflict, 12 no-conflict, 12 insufficient evidence; Chinese and English works), thresholds registered before the set is authored, and one formal run that decides. Each set is spent once it has been run.

| Held-out set | Configuration | Result |
| --- | --- | --- |
| V10 (2026-09-29) | `deepseek-flash`, high thinking, prompt v21 | Passed 13/13 checks: macro F1 0.972, conflict recall 0.917, insufficient-evidence recall 1.0, no false positives ([record](docs/eval-v10-first-formal-result.md)) |
| V11 (2026-09-30) | prompt v22 | Failed twice on insufficient-evidence recall (0.75, 0.67; bar 0.8): drafts that settled a point the source left open got no issue at all |
| V12 (2026-10-03) | prompt v24c, shipped in v1.5.1/v1.5.2 | Passed every registered threshold: macro F1 0.972, insufficient-evidence recall 1.0, conflict recall 0.917, no false positives, designated regressions 3/3 ([procedure](evaluation/ie_fix_v24/PLAN.md), [result](evaluation/results/eval-v12-v24c-first-formal.json)) |

These sets use chapters of at most 300 characters and drafts of one to three sentences.

### Earlier evidence

The frozen V4 set (15 balanced cases plus 6 stability reruns) scored 1.0 on every classification and Evidence measure and remains the packaged release-bundle baseline. V5–V8 each keep one immutable `gate_failed` formal bundle (in V8 the designated category regression was 2/3), so the Model Evaluation Gate recorded under Stage 10 stays failed. Stage 11 validated the author workflow on real 100k- and 300k-character prefixes, Stage 12 passed the Agent Run lifecycle Gates, and Stage 13 passed the web-app readiness Gate. The CLI PoC's held-out F1 0.9412 used a different protocol. See [the verification record](docs/verification-and-limitations.md) for these results and their limits, and [the product decisions record](docs/product-decisions-and-validation.md) for the rationale behind the workflow.

## Technology

- Backend: Python, FastAPI, Uvicorn, SQLite, `httpx`
- Frontend: Next.js App Router, React, TypeScript
- Verification: `unittest`, Playwright, axe-core, ESLint, TypeScript
- Provider integration: DeepSeek-compatible HTTP API, configured only through process environment variables

## Repository layout

```text
backend/       API, SQLite schema/migration, seed data, and contract tests
frontend/      Next.js workspace and browser E2E tests
evaluation/    frozen V4–V12 case sets, long-text sets and runner (`evaluation/longform/`), held-out thresholds, validators, tests, and sanitised results
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

# All current browser E2E groups; no manually started servers are needed
Get-ChildItem Env:CONTINUITY_* | Remove-Item
npm run test:e2e

# Run selected groups, or filter test titles within regular
npm run test:e2e -- --group v130
npm run test:e2e -- --group stage12,regular,stage13
npm run test:e2e -- --group regular --grep "review entry"
```

`npm run test:e2e` runs eight isolated production browser groups in sequence: `v130` (15 author-workflow tests), `v140-frontend` (13 interface tests), `v140-visual` (those 13 plus one visual test), `regular` (59 authentication, writing, autosave, import, chapter-check, fact-review, v1.1/v1.2 and helper tests), `stage12` (8 Agent Run lifecycle tests), `stage13` (4 visitor, recovery and isolation tests using the impl profile), `maintenance` (13 interface plus 2 maintenance tests), and `legacy-rich-suggestion` (1 staged rich-text suggestion test). The total is 129 executions; the 13 v140 frontend cases run in three groups. `--group` accepts a comma-separated list; `--grep` is supported only for `regular`. Use `npm run test:e2e -- --help` for the available groups and ports.

The runner clears model and SMTP configuration, builds temporary source copies without environment files, starts test-only FastAPI/Next.js services on dedicated ports, and cleans its sources, builds, databases and service processes. It prints `E2E_REPORT_ROOT` and `E2E_SUMMARY` for per-group results, logs and browser attachments retained in system temp. No local demo database, real model or external SMTP service is used. Keep the fixed ports and temporary build drives free, and run only one E2E command at a time; see [the port table and reproduction guide](docs/local-setup.md#isolated-browser-e2e).

Five historical acceptance records (`legacy-gap-independent`, `legacy-gap-independent-round2`, `legacy-gap-round3-brief`, `g02-controller`, and `g02-controller-post-v4`) remain as evidence and are excluded from daily runs. `test:e2e:raw` retains the direct Playwright entry and requires a matching manually supplied isolated environment. The standalone `test:v130`, `test:v140:frontend`, and `test:v140:visual` commands remain available; the unified entry is the daily all-group command.

The backend suite includes the Agent Reliability lifecycle and Web App Readiness security contracts, recorded under Stages 12 and 13. The release-bundle validator checks that the published V4 results, frozen assets, recorded workspace metadata, documentation, and screenshots are self-consistent; it does not claim to reopen unpublished SQLite workspaces. The browser E2E runner manages the isolated services described in [the local setup guide](docs/local-setup.md).

## Core author workflow

The [3–5 minute demo guide](docs/demo-guide.md) walks through project selection, a completed continuity review, Evidence, author confirmation, and Reset. The guide does not require provider calls.

## Known limitations

- The signed Stage 14 production baseline remains `Story Continuity Copilot v1.0 Public Release` as historical evidence. The active public deployment is v1.6.1 (`v161-edd821a-20261006`); its deployment and acceptance scope are recorded in the [v1.6.1 deployment record](docs/deployment-2026-10-06-v161.md). Local acceptance does not re-sign Stage 14, constitute a commercial SLA, or claim that the retained Stage 10 `gate_failed` evaluation was later passed.
- Real SMTP delivery, email verification, password reset, old-session revocation, new-password login, and used-link replay rejection have been accepted at the public origin. Email credentials and addresses remain server-only.
- The evaluation sets are small and frozen (V4: 15 cases; held-out sets: 36 cases each; `lf2-formal`: 26 chapters). They support the stated claims only and are not general benchmarks.
- Real provider output can vary. The retained stability evidence shows variation in Evidence IDs and exact explanation hashes even where decision and category/severity were stable.
- The system supports continuity review and author-controlled canon updates; it does not directly continue the novel.
- Current browser E2E suites run through `npm run test:e2e` with isolated production services and test-only providers. Historical acceptance records are excluded from daily runs; browser checks do not evaluate real model quality or external SMTP delivery. See the [isolated E2E instructions](docs/local-setup.md#isolated-browser-e2e).
- `test:build-origin` has one known failure ("canonical HTTPS proxy exposes public health…").
- A ~2,500-character chapter takes about 40 s (p90 76 s) and ¥0.21 on average with the screened pipeline. Insufficient-evidence recall (0.83 on the formal set) and the share of clean chapters without any card (78%) are close to their bars and vary from run to run; prompt changes need a regression run.
- Whole-book checks are not offered to authors yet; checking chosen chapters is limited to eight at a time.
- In about one check in nine, the 灰港回声 sample draft reports "决定先核对那声不该响起的雾钟" as a confirmed world-rule conflict; the formally validated review prompt is kept until a new gate justifies a change.
- With the real model, some Story Memory change-set reviews for long appended chapters fail backend validation (`candidate_count_invalid`, `memory_type_invalid`), and a long check can occasionally fail with unresolvable evidence. Both are model-output issues, not interface faults.
- Writing and checking are desktop-only; below 1024 px the workspace is browse-only.

## Further reading

- [Local setup and reproduction](docs/local-setup.md)
- [3–5 minute demo guide](docs/demo-guide.md)
- [Product decisions and evidence](docs/product-decisions-and-validation.md)
- [Validation evidence and known limitations](docs/verification-and-limitations.md)
- [Curated verification artifacts](artifacts/README.md)
