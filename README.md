# Story Continuity Copilot

AI continuity checks for long-form fiction: it reads a new chapter against everything written before it, flags contradictions and claims the earlier text cannot support, cites the earlier passage for every finding, and leaves every decision to the author.

**Current version: v1.7.0**, deployed 2026-10-10; see [version and deployment](#version-and-deployment). [Current product and verification scope](docs/current-product.md).

## What it does

A novelist writes chapter 40 and has the heroine open a door with a key she lost in chapter 12. Story Continuity Copilot catches that kind of slip. It checks a draft or a chosen set of written chapters against the earlier text, and reports each problem as a finding the author can trace: what the new sentence says, which earlier passage it conflicts with or lacks, and how serious it is. Nothing is rewritten for the author, and the work's fact base only changes when the author confirms a change.

The interface is in Chinese and is built for Chinese web fiction; the evaluation sets also include English works.

## Main features

The work has five tabs: **概览 / Overview · 写作 / Writing · 章节 / Chapters · 资料 / Records · 计划 / Plans**.

- **Writing:** rich-text and focus writing, server-side draft autosave, checks with source passages, pre-writing recap and plan comparison. Findings distinguish clear conflicts, possible conflicts, state changes (shown as 「状态更新」) and insufficient evidence. The author can keep as intended, mark as not a problem, apply the suggestion or edit the text; available actions depend on the finding. A state change uses 「保留这个变化」 for keeping it. Mark for revision is a reminder, not a decision.
- **Chapters:** select up to eight written chapters to check against their earlier chapters, inspect check status, append chapters and revise written text. Review affected facts after revising a chapter before another check. Earlier eligible decisions are reused automatically when their sentence, evidence and supporting versions still match.
- **Records:** inspect the versioned, author-confirmed fact base, people, settings, foreshadowing and ask the records. Trace facts to their source passages, review fact changes from new chapters and manage setting categories. Change impact only analyses a proposed change.
- **Plans:** keep unwritten plot, character and setting plans as decided or considering; only decided, unarchived plans enter the pre-writing recap and plan comparison.
- **Overview:** a story route connects written chapters, the draft, open foreshadowing and upcoming plans. Chapter points open the corresponding text; work actions include export and reset.
- **A sample work and guided tour:** each account has one copy of Grey Harbor Echoes (《灰港回声》), labelled sample findings and a five-step tour. A visitor space lasts 24 hours by default.
- **Day and night modes:** switch from the top bar. Interface motion respects the system's reduced-motion preference.

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

Production runs **v1.7.0**, release `v170-8cd1dbd-20261010`, deployed 2026-10-10 ([deployment record](docs/deployment-2026-10-10-v170.md)). The rollback target is `v161-edd821a-20261006`.

- **v1.7.0** — a rewritten frontend and visual design, five tabs, night mode and motion disabled by reduced-motion settings. Each account has one sample work and a five-step tour. **On upgrade, old tutorial and demo works are replaced, including edited copies; authors' own works are retained.** Plans gain considering status; setting categories are author-managed. Mark for revision replaces revision plans; eligible earlier decisions are reused automatically when only other parts of the draft change. Author materials, revision plans and writing tips are removed. Pre-writing recap, plan comparison and change impact have larger input allowances and fixes for failures on ordinary works; changed plans are read directly and their target chapters reach the model. Failed fact-base building no longer consumes the day's fact-building allowance. Word import recognises short chapter headings such as 「第X章」 without heading styles. Empty grouping headings merge into the next chapter title (for example 「第一卷 风起 · 雨夜」), retaining the text; a trailing empty heading is retained at the end. Standalone TXT downloads include a UTF-8 BOM for editors such as WPS. Writing and checks work at window widths of 768 px and above. Browser tests have been rewritten.
- **v1.6.1** — server-side draft autosave, checked drafts in the chapter timeline, chapter and character counts in the works list, and check readiness on the overview. [Deployment record](docs/deployment-2026-10-06-v161.md).
- **v1.6.0** — screened checking of full chapters, selected-chapter checks, rolling character allowances, chapter check status and checkable TXT/Word imports. [Deployment record](docs/deployment-2026-10-06.md).

Earlier releases remain in Git tags and the [documentation index](docs/README.md).

## Known limitations

- The formal set's insufficient-evidence recall (0.83) and clean chapters without findings (78%) are close to their bars; results vary and model or prompt changes need a new gate. Timing and cost above are measurements from that frozen run, not service guarantees.
- An earlier real-model observation of the Grey Harbor sample draft found an occasional false world-rule conflict around the fog bell. It has not been remeasured for v1.7.0.
- To avoid invented content, the pre-writing recap renders each item as a quotation of its source; when the model cites mostly the current draft, the recap adds little.
- Whole-book checks are not offered; one selected-chapter check covers at most eight chapters. Real-model fact-change reviews of long appended chapters or checks with unresolvable evidence can fail validation.
- Writing and checking require a window width of at least 768 px; narrower windows are browse-only. The writing page uses a text/findings switch through 1023 px.
- Imports consisting only of headings, or ending in several consecutive empty headings, can still fail. The focus-writing dialog's background editor may remain visible to assistive technology.
- Evaluation sets are small (26 chapters in the long-text formal set). No completed study with real authors is evidenced. Automated checks, real-model samples and manual acceptance establish different things.

## Data and safety

- AI output does not change prose or the fact base by itself. Applying a suggestion requires the author; proposed fact changes enter the fact base only after confirmation.
- Works are isolated per account. Another account's resources return not found. A fact and its evidence remain associated with their work and versions.
- Evidence must resolve within the same work. Failed, cancelled or timed-out checks leave no partial findings.
- Model and email credentials stay on the server. Default checkable characters are 60,000 per rolling 24 hours for registered authors; visitors check one chapter of at most 3,000 characters per request. Separate workflow and provider-attempt limits also apply.
- Reset clears the selected work's checks, decisions and unsubmitted changes; it does not reset other works. Read the confirmation before proceeding.

## Run locally

Use Windows PowerShell, Python 3.11+ and Node.js 20.9.0 or later (the installed Next.js requirement). Install from the repository root:

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend
npm ci
Set-Location ..
```

Follow [local setup](docs/local-setup.md) to start the API on 8000 and a temporary frontend copy on 3000 with matching origins. Do not run `next dev` (including `npm run dev`) directly in the repository's `frontend/`: it rewrites `tsconfig.json` and `next-env.d.ts`. Without a configured model provider, a check returns `503 provider_unavailable`.

## Tests

```powershell
# Backend, from backend/
Get-ChildItem Env:CONTINUITY_* | Remove-Item
$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3000'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
$env:TRUSTED_HOSTS = '127.0.0.1:8000,testserver'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3000,http://testserver'
& ..\.venv\Scripts\python.exe -m unittest discover -s tests
& ..\.venv\Scripts\python.exe -m pytest tests/test_maintenance_package.py

# Evaluation package, from the repository root; no model calls
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m evaluation.validate_release_bundle
& .venv\Scripts\python.exe -m unittest discover -s evaluation\tests

# Browser and deployment checks, from frontend/
$env:E2E_PYTHON = (Resolve-Path ..\.venv\Scripts\python.exe).Path
npm run test:e2e
npm run test:build-origin
```

At v1.7.0: backend 594/594, evaluation 77/77, browser end-to-end 149/149, ESLint and TypeScript clean, maintenance-package tests 10/10, release-bundle validation passed. One backend test and 20 evaluation tests read local artifacts that Git ignores (`artifacts/test-records/stage11/` and `evaluation/fixture-workspaces/`); in a clone without them those tests stop with a missing-file error. `npm run test:build-origin` has two known failures: the Stage 14 model-name expectation and the current-change allowlist coverage.

The browser suite is one `v170` group on 3280/8280, run by `npm run test:e2e`. Set `E2E_PYTHON` to a backend-capable interpreter (a shared virtual environment can be used). The runner automatically sets `STORY_SAMPLE_WORK_FILE`. These tests use test-only providers and do not measure model quality. See [isolated browser E2E](docs/local-setup.md#isolated-browser-e2e).

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

- [Documentation index](docs/README.md) — current guides, release records, historical design and frozen evidence
- [Current product and verification scope](docs/current-product.md)
- [Demo guide](docs/demo-guide.md) — a 3–5 minute sample-work walkthrough
- [Local setup](docs/local-setup.md), [operations](docs/operations.md) and [evaluation maintenance](docs/evaluation-maintenance.md)
- [Evaluation README](evaluation/README.md) and [long-text gate plan](evaluation/longform/PLAN.md) — recorded model gates

### Historical records

- [v1.0 product decisions](docs/product-decisions-and-validation.md)
- [v1.0 verification and limitations](docs/verification-and-limitations.md)
- [v1.7.0 deployment](docs/deployment-2026-10-10-v170.md), [v1.6.1 deployment](docs/deployment-2026-10-06-v161.md) and [v1.6.0 deployment](docs/deployment-2026-10-06.md)

## Project history

The project began as a CLI proof of concept and developed through numbered stages into a signed **v1.0 Public Release** baseline: a local web application, an author-confirmed fact base, workflow validation on real 100k- and 300k-character texts, a six-state check lifecycle with retry and cancel, and visitor isolation and recovery. Frozen V4 evaluation results and failed V5–V8 gates remain historical evidence. Stage numbers, release IDs and the technical package name `story-continuity-app` remain traceable; the private npm package retains version `0.1.0`. Historical design and verification records are linked above.
