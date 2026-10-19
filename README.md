# Story Continuity Copilot

AI continuity checks and a writing assistant for long-form fiction: it reads a new chapter against everything written before it, flags contradictions and claims the earlier text cannot support, answers questions about the work with the passages it read, and leaves every decision to the author.

**Current version: v1.8.1**; see [version and deployment](#version-and-deployment). [Current product and verification scope](docs/current-product.md).

## What it does

A novelist writes chapter 40 and has the heroine open a door with a key she lost in chapter 12. Story Continuity Copilot catches that kind of slip. It checks a draft or a chosen set of written chapters against the earlier text, and reports each problem as a finding the author can trace: what the new sentence says, which earlier passage it conflicts with or lacks, and how serious it is. The built-in assistant answers questions about the work, recaps where the story stands before the author starts a chapter, and proposes ways to fix a finding. Nothing is rewritten for the author, and the work's fact base only changes when the author confirms a change.

The interface is in Chinese and is built for Chinese web fiction.

## Main features

The work has five tabs: **概览 / Overview · 写作 / Writing · 章节 / Chapters · 资料 / Records · 计划 / Plans**.

- **Assistant (new in v1.8.0):** a panel beside the writing page with three uses.
  - **Ask about the work (问作品):** every sentence of an answer cites the passage, fact or plan it comes from. When the text does not say, the answer says so instead of guessing; when two places disagree, it names both.
  - **Pre-writing recap (写前回顾):** where the last chapter stopped, the latest state of the people in the scene, open threads and the plan for this chapter, each item with its source.
  - **Help me fix this (帮我改这一处):** for a check finding, at least two ways to change the text. Each is checked against the earlier chapters before it is shown, and nothing changes until the author adopts one.

  The steps the assistant takes are shown as it works. A task takes at most 8 steps and ¥0.30, and a question can have two follow-ups. Visitors can use it on the sample work three times per 24 hours.
- **Author home and settings (new in v1.8.0):**
  - **Home (`/account`):** a writing calendar, the chapter in progress, works and a feed of recent checks and fact changes.
  - **Settings (`/settings`):** four sections (general, account, usage, data): name and bio that save as you leave the box, theme and text size, password change, daily usage, and export of all works. The author's badge is the first character of their display name.
- **Writing:** rich-text and focus writing, server-side draft autosave, checks with source passages and plan comparison.
  - Findings distinguish clear conflicts, possible conflicts, state changes (shown as 「状态更新」) and insufficient evidence.
  - The author can keep a finding as intended, mark it as not a problem, apply the suggestion or edit the text. The available actions depend on the finding.
- **Chapters:** select up to eight written chapters to check against their earlier chapters, inspect check status, append chapters and revise written text. Earlier eligible decisions are reused automatically when their sentence, evidence and supporting versions still match.
- **Records:** the versioned, author-confirmed fact base, people, settings and foreshadowing, each fact traced to its source passage. Fact changes from new chapters are reviewed before they are recorded.
- **Plans:** unwritten plot, character and setting plans, as decided or considering. Only decided, unarchived plans reach the recap and plan comparison.
- **Overview:** a story route that connects written chapters, the draft, open foreshadowing and upcoming plans.
- **Sample work, tour and modes:**
  - Each account has a copy of the sample work 《灰港回声》 with labelled sample findings and a five-step tour; a visitor space lasts 24 hours by default.
  - Day and night modes; interface motion respects the system's reduced-motion setting.
  - A privacy page (`/privacy`) explains what is collected and for how long.

## How a check works

1. **Screen.** A fast model pass reads the whole chapter and flags the sentences that make claims worth checking (`continuity-screen-v1`).
2. **Triage.** The remaining sentences are scored and labelled as a possible conflict or a possible missing link, so a sentence the screen passed can still be reviewed (`continuity-triage-v4-gap-kind`).
3. **Review.** Each flagged sentence gets a careful review with model reasoning against the best-matching passages of earlier chapters and the latest confirmed state of the people it names, including people the text refers to only as 少年, 她 and so on.
4. **Second look and sweep.**
   - Key sentences the first review passed get an independent second review that watches for missing links.
   - Sentences the triage scored high but could not escalate are reviewed in small batches.

Per chapter, the check makes at most:
- 5 key reviews and 2 second looks;
- 3 escalations plus 2 reserved for possible missing links;
- a sweep of up to 6 more sentences.

This keeps time and cost bounded. The review prompt is `continuity-review-v25i-screened-stated-inability` on `deepseek-flash`. Calendar dates in the story (初六, 廿三, 三更, named months) are read as time anchors.

## Quality and evaluation

Model and prompt changes are judged by formal runs on sets written in a separate session and never seen during development, against thresholds registered before the sets were written. A set is spent once it has been run.

**Assistant.** The assistant was released on its long-text evaluation (A1c): real-length chapters (2,500–3,500 characters, two 30-chapter works and a 12-chapter safety work), three passes of every task. The fourth formal run (2026-10-19) met all 18 registered bars after the registered audit:

| Measure | Result | Registered bar |
| --- | ---: | ---: |
| Answerable questions / evidence deep in a chapter | 1.00 / 1.00 | ≥ 0.80 / 0.75 |
| Questions the text does not answer | 0.92 | ≥ 0.80 |
| Cited sentences supported by their source | 0.99 | ≥ 0.90 |
| Pre-writing recap: required points mentioned | 0.78 | ≥ 0.70 |
| Fix proposals that remove the conflict | 1.00 | ≥ 0.75 |
| Safety tasks correct in all three passes | 1.00 | = 1.00 |
| Tasks within budget (8 steps, ¥0.30) | 1.00 | = 1.00 |
| Time per task, p90 | 12.9 s | ≤ 45 s |

One bar, process lines or notes stating story content (0.0475, bar ≤ 0.05), was met after the audit. The run, its audit and the addenda are recorded in [evaluation/assistant_a1c/SPEC.md](evaluation/assistant_a1c/SPEC.md).

**Chapter check.** v1.8.0 changes to the chapter check (character knowledge, epithets, story calendar dates, missing-link triage) were developed and regression-tested on spent long-text sets. Earlier formal runs and their procedure are in [evaluation/longform/PLAN.md](evaluation/longform/PLAN.md).

## Version and deployment

Production runs **v1.8.0**, release `v180-c674227-20261019` ([deployment record](docs/deployment-2026-10-19-v180.md)), until v1.8.1 is deployed. The v1.8.1 release ID and deployment record are added at deployment.

- **v1.8.1:**
  - Settings in four sections (general, account, usage, data), with each row's label on the left and its control on the right; name and bio save as you leave the box. The old settings addresses lead to the new sections.
  - The four portrait avatars are replaced by the first character of the display name.
  - The assistant's note keeps its "there was an instruction for the assistant in the material" line only when the material it read holds one.
  - Fixes: the privacy page date, the bio counter, and a console error when the theme sweep is interrupted.
- **v1.8.0:**
  - The writing assistant (ask, pre-writing recap, help me fix this) with visible steps, follow-up questions, per-task limits and a visitor allowance.
  - Author home and settings pages: writing calendar, usage, password change, export of all works.
  - A privacy page.
  - Chapter-check reviews that follow people named only by epithet or pronoun, read story calendar dates, and look again at sentences that may skip a link in the earlier text.
  - Building the fact base from imported chapters no longer fails as a whole when a few candidates are invalid.
- **v1.7.0:**
  - A rewritten frontend and visual design: five tabs, night mode, and a sample work with a five-step tour per account.
  - Considering plans and author-managed setting categories.
  - Mark for revision, and automatic reuse of eligible decisions.
  - Author materials, revision plans and writing tips are removed.
  - Writing and checks work at window widths of 768 px and above.

Earlier releases remain in Git tags; the [documentation index](docs/README.md) lists what is kept.

## Known limitations

- The assistant reads the work through its tools within the per-task limits; on very long works an answer covers what it found, and says which chapters it read.
- Whole-book checks are not offered; one selected-chapter check covers at most eight chapters.
- Writing and checking require a window width of at least 768 px; narrower windows are browse-only.
- Evaluation sets are small and written for evaluation. No completed study with real authors is evidenced; automated tests, real-model samples and manual acceptance establish different things.

## Data and safety

- AI output does not change prose or the fact base by itself. Applying a suggestion or an assistant proposal requires the author; proposed fact changes enter the fact base only after confirmation.
- Text inside the work (chapters, facts, plans, drafts) is treated as material, never as instructions to the assistant.
- Works are isolated per account. Another account's resources return not found. Evidence must resolve within the same work; failed, cancelled or timed-out checks leave no partial findings.
- Model and email credentials stay on the server.
- **Allowances:**
  - Registered authors can check 60,000 characters per rolling 24 hours by default, and each assistant task counts as 500 of them.
  - Visitors check one chapter of at most 3,000 characters per request.
  - Separate workflow and provider-attempt limits also apply.
- Reset clears the selected work's checks, decisions and unsubmitted changes; it does not reset other works.

## Run locally

Use Windows PowerShell, Python 3.11+ and Node.js 20.9.0 or later (the installed Next.js requirement). Install from the repository root:

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend
npm ci
Set-Location ..
```

Follow [local setup](docs/local-setup.md) to start the API on 8000 and a temporary frontend copy on 3000 with matching origins.
- Do not run `next dev` (including `npm run dev`) directly in the repository's `frontend/`: it rewrites `tsconfig.json` and `next-env.d.ts`.
- Without a configured model provider, a check returns `503 provider_unavailable`.
- The assistant is off unless `CONTINUITY_ASSISTANT_ROLLOUT` is set.

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

# Evaluation package, from the repository root; no model calls
$env:PYTHONPATH = '.;backend'
& .venv\Scripts\python.exe -m unittest discover -s evaluation\tests

# Browser and deployment checks, from frontend/
$env:E2E_PYTHON = (Resolve-Path ..\.venv\Scripts\python.exe).Path
npm run test:e2e
npm run test:build-origin
```

At v1.8.0 these numbers held:
- backend 1,093 tests;
- offline evaluation 26 tests;
- browser end-to-end 286 passed, with 10 screenshot-only tests skipped;
- `npm run test:build-origin` 23 tests;
- ESLint and TypeScript clean.

The browser suite is one `v170` group on 3280/8280, run by `npm run test:e2e`. These tests use test-only providers and do not measure model quality. See [isolated browser E2E](docs/local-setup.md#isolated-browser-e2e).

## Repository layout

```text
backend/       FastAPI app, SQLite schema and migrations, seed data, tests
frontend/      Next.js app and browser end-to-end tests
evaluation/    assistant and long-text evaluations: runners, registered thresholds, held-out sets
deployment/    source packaging, release and rollback scripts
docs/          product page, setup and demo guides, deployment records
```

Built with Python, FastAPI, SQLite, Next.js, React and TypeScript; tested with unittest, Playwright, axe-core and ESLint. The model provider is a DeepSeek-compatible API configured only through environment variables.

## Documentation

- [Documentation index](docs/README.md)
- [Current product and verification scope](docs/current-product.md)
- [Demo guide](docs/demo-guide.md): a 3–5 minute sample-work walkthrough
- [Local setup](docs/local-setup.md), [operations](docs/operations.md) and [evaluation maintenance](docs/evaluation-maintenance.md)
- [Assistant evaluation (A1c)](evaluation/assistant_a1c/SPEC.md) and [long-text check plan](evaluation/longform/PLAN.md)

## Project history

The project began as a CLI proof of concept and grew through numbered stages into a v1.0 public release:
- a local web application;
- an author-confirmed fact base;
- workflow validation on real 100k- and 300k-character texts;
- a check lifecycle with retry and cancel;
- visitor isolation.

Long-text checking arrived in v1.6, the rebuilt interface in v1.7, and the writing assistant in v1.8. Earlier history is kept in the archived repository.
