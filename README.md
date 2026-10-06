# Story Continuity Copilot

AI continuity review for long-form fiction: it reads a new chapter against everything written before it, flags contradictions and claims the earlier text cannot support, cites the earlier passage for every finding, and leaves every decision to the author.

**Live site:** [43-160-207-57.sslip.io](https://43-160-207-57.sslip.io) (try it without an account via 访客体验) · **Latest release:** [v1.6.1](https://github.com/zhaochenyang744-lgtm/Story-Continuity-Copilot/releases/tag/v1.6.1) · **Product page:** [current product and verification scope](docs/current-product.md)

## What it does

A novelist writes chapter 40 and has the heroine open a door with a key she lost in chapter 12. Story Continuity Copilot catches that kind of slip. It checks a draft or a chosen set of written chapters against the earlier text, and reports each problem as a finding the author can trace: what the new sentence says, which earlier passage it conflicts with or lacks, and how serious it is. Nothing is rewritten for the author, and the work's fact base (Story Memory) only changes when the author confirms a change.

The interface is in Chinese and is built for Chinese web fiction; the evaluation sets also include English works.

## Main features

- **Checks real chapters.** Built for chapters of about 2,500 characters; one chapter takes about 40 seconds and ¥0.21 on average.
- **Every finding cites its evidence.** A finding points to the passage of an earlier chapter it rests on; a finding whose evidence cannot be traced back to the work is rejected, never shown.
- **Three kinds of findings.** Clear conflicts, possible conflicts, and insufficient evidence, where the new text settles something the earlier text leaves open and the finding names the missing link.
- **Check chosen chapters.** Tick up to eight written chapters and check them together; each is judged against the chapters before it, and the estimated characters and cost are shown before anything is spent.
- **Chapter timeline.** Every chapter and the current draft in order, marked checked, not checked, edited after its check, or basis changed (an earlier chapter was revised since).
- **Author-controlled Story Memory.** Proposed fact changes are accepted, rejected or edited one by one; only accepted changes update the fact base, and every decision is recorded.
- **Writing and import.** Rich-text and immersive writing with server-side autosave; import by paste, TXT or Word (`.docx`, split by heading styles). An imported work can be checked at once.
- **Visitor mode.** A 24-hour visitor space with three sample works and labelled sample reports, no sign-up needed.

## How a check works

1. **Screen.** A fast model pass reads the whole chapter and flags the sentences that make claims worth checking (`continuity-screen-v1`).
2. **Triage.** The remaining sentences are scored, so a sentence the screen missed can still be escalated (`continuity-triage-v3-presupposed-links`).
3. **Review.** Each flagged sentence gets a careful review with model reasoning, one sentence per request, against the best-matching passages of earlier chapters (passage index with entity and fact routing).
4. **Second look.** Key sentences the first review passed get one independent second review that watches for missing links.

Per chapter at most 5 key reviews, 2 second looks and 3 escalations, which keeps time and cost bounded. The review prompt is `continuity-review-v25g-screened-presupposed-links-bounded-knowledge-rule-category` on `deepseek-flash`.

## Quality and evaluation

Every change to the checking model or prompt is decided by one formal run on a set written in a separate session and never seen during development, against thresholds registered before the set was written. A set is spent once it has been run.

The current pipeline passed its long-text gate on `lf2-formal` (26 real-length chapters, 2026-10-05):

| Measure | Result | Registered bar |
| --- | ---: | ---: |
| Conflict recall | 1.00 | ≥ 0.80 |
| Insufficient-evidence recall | 0.83 | ≥ 0.80 |
| Category accuracy (conflicts found) | 1.00 | ≥ 0.75 |
| Designated regression cases | 3/3 | 3/3 |
| False-positive rate on trap sentences | 0 | ≤ 0.20 |
| Clean chapters with no finding | 78% | ≥ 70% |
| Time per chapter, median / p90 | 40 s / 76 s | ≤ 60 s / 90 s |
| Cost per chapter, mean / max | ¥0.21 / ¥0.46 | ≤ ¥0.30 / ¥0.60 |

Bars and procedure: [evaluation/longform/PLAN.md](evaluation/longform/PLAN.md) and `thresholds.py`.

The first long-text formal run failed on insufficient-evidence recall and maximum cost; that set was retired and the fix was judged on the new one. Earlier short-draft held-out sets (V10–V12) and their results are listed in the [evaluation README](evaluation/README.md).

## Version and deployment

The live release is **v1.6.1** (`v161-edd821a-20261006`, deployed 2026-10-06, [record](docs/deployment-2026-10-06-v161.md)); the rollback target is `v160-ef7341e-20261006`.

- **v1.6.1** — server-side draft autosave (5 s after typing stops, never overwriting a newer version saved elsewhere); checked drafts count in the chapter timeline; the works list shows chapter and character counts; check readiness on the overview.
- **v1.6.0** — the long-text release: screened checking of real chapters, checking chosen chapters, character-based quotas, the chapter timeline, checkable imports and Word import ([record](docs/deployment-2026-10-06.md)).
- **v1.5.2** — insufficient evidence is reported with the missing link instead of silence; an over-long model answer is retried claim by claim instead of failing the check ([record](docs/deployment-2026-10-04.md)).

Full notes are on the [releases page](https://github.com/zhaochenyang744-lgtm/Story-Continuity-Copilot/releases); earlier versions are kept in the Git tags and the records under `docs/`.

## Known limitations

- Insufficient-evidence recall (0.83) and the share of clean chapters with no finding (78%) are close to their bars and vary from run to run; prompt changes need a new gate.
- In about one check in nine, the 灰港回声 sample draft reports "决定先核对那声不该响起的雾钟" as a confirmed world-rule conflict.
- Whole-book checks are not offered yet; a chapter check covers at most eight chapters.
- With the real model, some fact-change reviews of long appended chapters fail backend validation, and a long check can occasionally fail on evidence that cannot be traced. Both are rejected rather than shown.
- Writing and checking need a desktop width (1024 px or more); narrower screens are browse-only.
- The evaluation sets are small (26 chapters; 36 cases per short-draft set). They support the stated claims, not general benchmarks. No study with real authors has been done yet.

## Data and safety

- AI output never writes the prose or the fact base. Findings and proposed changes stay as candidates until the author decides.
- Every work is isolated per account; another account's resources answer as not found.
- Evidence must resolve to a passage of the same work, or the finding fails closed. Failed, cancelled or timed-out checks leave no partial results.
- Model and email credentials stay on the server. Visitors get isolated, time-limited spaces with server-enforced quotas: registered authors check up to 60,000 characters per 24 hours, visitors one chapter of up to 3,000 characters at a time.

## Run locally

Windows, PowerShell, from the repository root:

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend; npm ci; Set-Location ..
```

Backend (first terminal):

```powershell
Set-Location backend
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
$env:TRUSTED_HOSTS = '127.0.0.1:8000'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000'
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend (second terminal), then open `http://127.0.0.1:3000`:

```powershell
Set-Location frontend
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
npm run dev
```

Without a configured model provider, a check returns `503 provider_unavailable` rather than a placeholder result. Provider configuration, health checks and isolated test servers are covered in [local setup and reproduction](docs/local-setup.md).

## Tests

```powershell
# Backend (from backend/, with the same environment as above plus testserver)
$env:TRUSTED_HOSTS = '127.0.0.1:8000,testserver'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000,http://testserver'
& ..\.venv\Scripts\python.exe -m unittest discover -s tests

# Evaluation package (from the repository root; no model calls)
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_release_bundle
& .venv\Scripts\python.exe -m unittest discover -s evaluation\tests

# Frontend (from frontend/)
npm run lint
npm run typecheck
Get-ChildItem Env:CONTINUITY_* | Remove-Item
npm run test:e2e
```

At v1.6.1: backend 554/554, evaluation 77/77, browser end-to-end 129/129 in eight isolated groups, ESLint and TypeScript clean. The browser tests use test-only providers, so they check the product, not model quality. The group list, ports and options are in [local setup](docs/local-setup.md#isolated-browser-e2e). `npm run test:build-origin` has one known failure ("canonical HTTPS proxy exposes public health…").

## Repository layout

```text
backend/       FastAPI app, SQLite schema and migrations, seed data, tests
frontend/      Next.js app and browser end-to-end tests
evaluation/    evaluation sets, long-text runner and thresholds (evaluation/longform/), validators, sanitised results
deployment/    source packaging, release and rollback scripts
docs/          product page, setup and demo guides, deployment records, historical records
artifacts/     curated screenshots (earlier interface)
```

Built with Python, FastAPI, SQLite, Next.js, React and TypeScript; tested with unittest, Playwright, axe-core and ESLint. The model provider is a DeepSeek-compatible API configured only through environment variables.

## Documentation

- [Current product and verification scope](docs/current-product.md) — what the product does now and what has been verified
- [Local setup and reproduction](docs/local-setup.md) — running, configuring and testing locally
- [Demo guide](docs/demo-guide.md) — a 3–5 minute walkthrough with sample works
- [Evaluation README](evaluation/README.md) and [long-text gate plan](evaluation/longform/PLAN.md)
- [Operations](docs/operations.md) — backups, restore drills and monitoring
- Deployment records: [v1.6.1](docs/deployment-2026-10-06-v161.md), [v1.6.0](docs/deployment-2026-10-06.md), [v1.5.2](docs/deployment-2026-10-04.md)

## Project history

The project began as a CLI proof of concept and was built up through a series of numbered stages into a signed **v1.0 Public Release** baseline: a local web demo, author-controlled Story Memory, workflow validation on real 100k- and 300k-character texts, a six-state run lifecycle with retry and cancel, and visitor isolation and recovery for public use. The frozen V4 evaluation and the failed V5–V8 gates remain as historical evidence; Stage numbers, release IDs and the technical package name `story-continuity-app` are kept for traceability, and the npm package version stays `0.1.0`. See the [verification record](docs/verification-and-limitations.md) and the [product decisions record](docs/product-decisions-and-validation.md).
