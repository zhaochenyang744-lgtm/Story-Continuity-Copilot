# Story Continuity Copilot

AI continuity checks and a writing assistant for long-form fiction: it reads a new chapter against everything written before it, flags contradictions and claims the earlier text cannot support, answers questions about the work with the passages it read, and leaves every decision to the author.

**Current version: v2.1.0**; see [version and deployment](#version-and-deployment). [Current product and verification scope](docs/current-product.md).

## What it does

A novelist writes chapter 40 and has the heroine open a door with a key she lost in chapter 12. Story Continuity Copilot catches that kind of slip. It checks a draft or a chosen set of written chapters against the earlier text, and reports each problem as a finding the author can trace: what the new sentence says, which earlier passage it conflicts with or lacks, and how serious it is. The built-in assistant answers questions about the work, recaps where the story stands before the author starts a chapter, proposes ways to fix a finding, and takes on a task that spans the whole book, such as going through every open foreshadowing thread. Nothing is rewritten for the author, and the work's fact base only changes when the author confirms a change.

The interface is in Chinese and is built for Chinese web fiction.

## Main features

The work has five tabs: **概览 / Overview · 写作 / Writing · 章节 / Chapters · 资料 / Records · 计划 / Plans**.

- **Assistant (new in v1.8.0):** a panel beside the writing page, and a drawer on the other pages.
  - **One input box (v1.9.0):** the author just writes; the box judges which use the sentence asks for (自动, the default), shows it on the task, and lets the author change it. A sentence that is not about the work starts nothing and costs nothing. Asking for a recap away from the writing page offers to go there.
  - **Long tasks (长任务, new in v2.1.0):** a request that spans many chapters ("go through every thread still open", "where has the compass been, chapter by chapter, and where do the chapters disagree").
    - Two kinds: a **thread audit** (伏笔清点: which open threads the text has in fact resolved or dropped, and which are still open) and a **trace** (梳理: where an object, a person's state or an event goes through the book, starting with where it ends up, and where the chapters disagree).
    - The assistant first shows a plan: what it will trace, the steps, the chapters each step reads, and the estimated characters and cost. It reads only written chapters. The author can narrow the chapters, change the cost cap or decline; nothing is read before 开始.
    - The task runs in the background while the author keeps writing; the panel shows the step and the cost so far, and the top bar's 助手 button shows a dot. It can be stopped at any time and keeps what it has done.
    - When two chapters disagree and the author's intent is unclear, it stops and asks, showing both sentences: which one stands, keep both (intended), or go by the latest chapter. Near the cost cap it asks whether to continue.
    - The result is a report whose every item cites its source, and a set of proposed changes grouped by kind. A group can be confirmed whole or in part, the rest left for later or turned down; marking a thread abandoned is confirmed on its own card.
  - **Change the records (改资料, new in v2.0.0):** asked in the box ("record that her left wrist was hurt in chapter 12", "the compass is with the Shens now, change the fact", "the fog-bell thread was resolved in chapter 20"), the assistant checks the text and proposes a change card: add a fact, change a fact, mark a foreshadowing thread resolved and, since v2.1.0, add a thread, reword a thread's description, or mark a thread abandoned (on its own card). Each item shows its before and after, the passage it rests on and, on a card of several items, the words of the author's sentence it answers. Nothing changes until the author confirms; items can be unticked and a fact reworded first. Applied changes can be undone and redone at any time; when a record has changed since, the author is told what an undo would take back. The records page marks what the assistant changed and keeps a log of every applied change. Prose is still changed only by the author.
  - **Ask about the work (问作品):** every sentence of an answer cites the passage, fact or plan it comes from. When the text does not say, the answer says so instead of guessing; when two places disagree, it names both. Asked for advice (where to pick up a thread, how to settle two places that disagree, whose whereabouts are open), it points only at what is already written, each point with its source, and does not invent plot.
  - **Pre-writing recap (写前回顾):** where the last chapter stopped, the latest state of the people in the scene, open threads and the plan for this chapter, each item with its source.
  - **Help me fix this (帮我改这一处):** for a check finding, at least two ways to change the text. Each is checked against the earlier chapters before it is shown, and nothing changes until the author adopts one.
  - **Check this passage (查前文矛盾):** a selected passage is checked against the earlier chapters.

  The steps the assistant takes are shown as it works, each step line written from what the step actually does. A task takes at most 8 steps and ¥0.30; a long task has its own plan and cost cap (¥2 by default). A finished answer is followed by default, and the box says which follow-up it is (at most two). Visitors can use it on the sample work three times per 24 hours.
- **Author home and settings (new in v1.8.0):**
  - **Home (`/account`):** a writing calendar, the chapter in progress, works and a feed of recent checks and fact changes.
  - **Settings (`/settings`):** four sections (general, account, usage, data): name and bio that save as you leave the box, theme and text size, password change, daily usage, and export of all works. The author's badge is the first character of their display name.
- **Look (v2.1.0):** no black frame lines; layers are told apart by background shades, buttons are filled, fields have a thin ring and shadow.
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
2. **Triage.** The remaining sentences are scored and labelled as a possible conflict or a possible missing link, so a sentence the screen passed can still be reviewed (`continuity-triage-v5-stated-links`).
3. **Review.** Each flagged sentence gets a careful review with model reasoning against the best-matching passages of earlier chapters and the latest confirmed state of the people it names, including people the text refers to only as 少年, 她 and so on.
4. **Second look and sweep.**
   - Key sentences the first review passed get an independent second review that watches for missing links.
   - Sentences the triage scored high but could not escalate are reviewed in small batches.

Per chapter, the check makes at most:
- 5 key reviews and 2 second looks;
- 3 escalations plus 2 reserved for possible missing links;
- a sweep of up to 6 more sentences.

This keeps time and cost bounded. The review prompt is `continuity-review-v25k-screened-offpage-second-review` on `deepseek-flash`. Calendar dates in the story (初六, 廿三, 三更, named months) are read as time anchors.

## Quality and evaluation

Model and prompt changes are judged by formal runs on sets written in a separate session and never seen during development, against thresholds registered before the sets were written. A set is spent once it has been run.

**Long tasks.** v2.1.0's long tasks are released on their own evaluation (A3): a formal pair of two 20-chapter works and a 12-chapter safety work whose chapters, records and requests hide instructions to the assistant, plus two supplementary safety sets, three passes of every task. Whether a step read outside the approved plan, whether a hidden instruction was carried out, whether an interrupted task resumed with no step lost or repeated, and whether confirm and undo leave the records exactly as expected are decided by program. The first formal run stopped at its cost cap and was recorded failed. The second (2026-10-28, on a new sealed pair) met 15 of 16 bars; the sixteenth, injection safety, was 0.9 on a product fault that was fixed, and two supplementary sealed safety sets then completed the gate (the second only after an audit the project owner accepted):

| Measure | Result | Registered bar |
| --- | ---: | ---: |
| Reads or card items outside the approved plan | 0 | = 0 |
| Injection tasks safe in all three passes (supplements) | 1.00 / 1.00 | = 1.00 |
| Interrupted tasks resumed exactly; confirm and undo exact | 1.00 | = 1.00 |
| Trace: states and contradictions found | 0.95 | ≥ 0.75 |
| Trace: contradictions reported that are not | 0.06 | ≤ 0.15 |
| Report and card items supported by their source | 0.99 | ≥ 0.95 |
| Card items right | 0.98 | ≥ 0.80 |
| Card items the author did not ask for | 0.01 | ≤ 0.03 |
| Asked the author when needed / did not ask needlessly | 0.92 / 0.91 | ≥ 0.70 / 0.85 |
| Tasks completed in all three passes; within budget (¥2) | 1.00 / 1.00 | ≥ 0.85 / 0.95 |
| Time per task, p90 (author's waiting excluded) | 0.4 min | ≤ 20 min |
| Long-task requests recognised by the input box | 1.00 | ≥ 0.90 |

Seven quality bars were lowered before the second pair was written (for example trace recall from 0.80 to 0.75); every quality result above would also have met the earlier bars. Safety bars were never lowered. The first supplement found a plan that ignored a range named by one end ("chapter 6 to the end"), which was fixed before the second. The runs, audits and addenda are in [evaluation/assistant_a3/SPEC.md](evaluation/assistant_a3/SPEC.md).

**Changing the records.** v2.1.0's new card kinds were measured on a sixth sealed pair (2026-10-28, three passes): 13 of 14 bars met after an audit the project owner accepted (card items right 0.90, supported 0.97, injection safety 1.00, confirm and undo exact); requests that should change nothing were answered without a card in 0.75 of cases, against a bar of 0.80, on four product faults. These were fixed, a pass over the spent pair met every bar, and a new sealed supplement met all of its twelve (card items right 1.00, no unrequested items). v2.0.0's change cards are released on their own evaluation (A2): two 20-chapter works and a 12-chapter safety work whose chapters, facts, threads and selections hide instructions to the assistant, three passes of every task. Whether a card's kind and target are right, whether an item was asked for, whether a hidden instruction was carried out, and whether confirm and undo leave the records exactly as expected are decided by program. Three earlier formal runs failed; the fourth (2026-10-24, on a new sealed pair) met all fourteen registered bars after the registered audit:

| Measure | Result | Registered bar |
| --- | ---: | ---: |
| Card items right (kind, target, content) | 0.89 | ≥ 0.85 |
| Changes supported by their quoted passage | 0.98 | ≥ 0.95 |
| Requests that should change nothing, answered without a card | 0.94 | ≥ 0.85 |
| Changes the author did not ask for, three passes / any one pass | 1 / 1 (4 / 2 before the audit) | ≤ 3 / ≤ 2 |
| Safety tasks safe in all three passes | 1.00 (0.92 before the audit) | = 1.00 |
| Confirm and undo exact | 1.00 / 1.00 | = 1.00 |
| Use picked by the input box | 1.00 | ≥ 0.90 |
| Change tasks right in all three passes | 0.83 | ≥ 0.70 |
| Tasks within budget (8 steps, ¥0.30) | 1.00 | = 1.00 |
| Time per task, p90 | 12.2 s | ≤ 45 s |
| Tasks that reached the step limit | 0.06 | ≤ 0.20 |

The audit overturned four verdicts: one where the judge read "proposed, waiting for the author's confirmation" as a claim that the records had been changed, and three where the program counted as unrequested a second item recording a point the author had asked for in the same sentence (those tasks still count as wrong). Two bars were met only after the audit, and the project owner accepted the audited result. The bar for unrequested changes (three in three passes, two in any pass; it was zero at registration) was set before the third and fourth sets were written. The runs, the audits and the addenda are recorded in [evaluation/assistant_a2/SPEC.md](evaluation/assistant_a2/SPEC.md).

**Asking, recaps and fixes.** These were released with v1.9.0 on their long-text evaluation (A1c); a development run on spent A1c sets at v2.0.0 found no regression. A1c uses real-length chapters (2,500–3,500 characters, two 30-chapter works and a 12-chapter safety work), three passes of every task. v1.9.0's gate is twenty registered bars. The fifth formal run (2026-10-22) met nineteen of them after the registered audit; the twentieth, which use the input box picks, was at 0.80 there and passed on a new sealed set of 30 items after two fixes (2026-10-22):

| Measure | Result | Registered bar |
| --- | ---: | ---: |
| Answerable questions / evidence deep in a chapter | 0.93 / 0.95 | ≥ 0.80 / 0.75 |
| Questions the text does not answer | 1.00 | ≥ 0.80 |
| Cited sentences supported by their source | 0.97 | ≥ 0.90 |
| Pre-writing recap: required points mentioned | 0.79 | ≥ 0.70 |
| Fix proposals that remove the conflict | 1.00 | ≥ 0.75 |
| Safety tasks correct in all three passes | 1.00 | = 1.00 |
| Tasks within budget (8 steps, ¥0.30) | 1.00 | = 1.00 |
| Time per task, p90 | 18.0 s | ≤ 45 s |
| Use picked by the input box (retest) | 0.98 | ≥ 0.90 |
| Advice sentences supported by their source | 0.98 | ≥ 0.90 |

The audit overturned ten verdicts, two of them on safety items; the safety bar was met only after the audit, and the project owner accepted the audited result. The runs, the audit and the addenda are recorded in [evaluation/assistant_a1c/SPEC.md](evaluation/assistant_a1c/SPEC.md).

**Fixes after the gates.** Changes made after the gates had passed, only to fix issues recorded in trials and reviews, were checked on the release code by one pass over the spent sets of all three evaluations, every bar met (2026-10-29, code 6b6a698): long tasks 16 of 16, and the second long-task safety supplement again in three passes with no audit; records 14 of 14 on the spent sixth pair and 12 of 12 on the supplement; asking, recaps and fixes 19 of 19, one of them, advice sentences supported by their source, after an audit the project owner accepted (0.89 before, the judge reading the suggestion itself as a claim about the text), and the input box's choice of use 0.97 against 0.90. These sets had been seen during development, so this is weaker evidence than a sealed set; the project owner accepted that trade-off.

**Chapter check.** v1.9.0's chapter check passed its long-text formal run on two new sealed sets, pooled (2026-10-20): 23 of 24 insufficient-evidence points found, 14 of 16 clean chapters with no finding, 6 of 6 designated items. The procedure and earlier runs are in [evaluation/longform/PLAN.md](evaluation/longform/PLAN.md).

## Version and deployment

Production runs **v2.1.0**, release `RELEASE_ID` ([deployment record](docs/DEPLOYMENT_RECORD)).

- **v2.1.0:**
  - Long tasks: a thread audit or a trace across the whole book, with a plan the author approves first, a background run that can be stopped, questions when two chapters disagree, and a report with grouped changes that can be confirmed in part.
  - The assistant can also add a thread, reword one and mark one abandoned; it says why when it changes nothing.
  - Answers list parallel points as items; citations open the whole passage with the sentence marked, and 去原文 opens the chapter; recaps give one sentence per item with its source; a question about a selected passage is answered as asked.
  - A softer look without black frame lines; the change log pages past 50 entries.
  - Registered authors' allowance raised to 100,000 characters per 24 hours; the privacy page describes what long tasks keep and the content-free usage statistics.
- **v2.0.0:**
  - The assistant proposes changes to the records (add a fact, change a fact, mark a thread resolved) on a card the author confirms; applied changes can be undone and redone, and the records page marks them and keeps a change log.
  - Properties named in the author's own words show their names.
  - The privacy page describes the change log.
- **v1.9.0:**
  - One input box for the assistant: it judges which use a sentence asks for, shows it, and lets the author change it; a sentence not about the work costs nothing; a recap asked for away from the writing page offers to go there.
  - A finished answer is followed by default, with the follow-up count shown; advice answers point only at what is already written, each with its source.
  - Pre-writing recaps write the lasting state (role, qualification, health) of the people in the scene; process lines are written from the steps themselves; fixes that fail their own check are not listed.
  - The chapter check finds more claims the earlier text cannot support and puts fewer findings on clean chapters.
  - The top bar stays on one line from 768 to 1,280 px wide.
  - Back-end code of features removed in v1.7 is deleted.
Earlier releases remain in Git tags; the [documentation index](docs/README.md) lists what is kept.

## Known limitations

- The assistant reads the work through its tools within the per-task limits; on very long works an answer covers what it found, and says which chapters it read.
- The assistant's changes to the records cover facts and foreshadowing threads. Deleting records and editing plans are done on the records and plans pages; asked to add a plan, the assistant says so.
- Long tasks cover thread audits and traces. Tidying the records (merging duplicates, settling stale facts) is not offered yet. Visitors cannot start long tasks.
- Whole-book checks are not offered; one selected-chapter check covers at most eight chapters.
- Writing and checking require a window width of at least 768 px; narrower windows are browse-only.
- Evaluation sets are small and written for evaluation. No completed study with real authors is evidenced; automated tests, real-model samples and manual acceptance establish different things.

## Data and safety

- AI output does not change prose or the fact base by itself. Applying a suggestion or an assistant proposal requires the author; proposed fact changes enter the fact base only after confirmation, and an assistant's change card applies only the items the author confirms, each of which can be undone.
- Text inside the work (chapters, facts, plans, drafts) is treated as material, never as instructions to the assistant.
- Works are isolated per account. Another account's resources return not found. Evidence must resolve within the same work; failed, cancelled or timed-out checks leave no partial findings.
- Model and email credentials stay on the server.
- **Allowances:**
  - Registered authors can check 100,000 characters per rolling 24 hours by default (60,000 before v2.1.0), and each assistant task counts as 500 of them.
  - A long task's plan counts as 500; 开始 reserves the characters the plan will read, and the finished task settles to what it actually read. A task that fails partway is not charged. Checks and assistant tasks on the sample work are not counted.
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

At v2.1.0 these numbers held:
- backend 1,609 tests;
- offline evaluation 30 tests;
- browser end-to-end 420 passed, with 25 screenshot-only tests skipped;
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
- Assistant evaluations: [asking and recaps (A1c)](evaluation/assistant_a1c/SPEC.md), [changing the records (A2)](evaluation/assistant_a2/SPEC.md), [long tasks (A3)](evaluation/assistant_a3/SPEC.md); and [long-text check plan](evaluation/longform/PLAN.md)

## Project history

The project began as a CLI proof of concept and grew through numbered stages into a v1.0 public release:
- a local web application;
- an author-confirmed fact base;
- workflow validation on real 100k- and 300k-character texts;
- a check lifecycle with retry and cancel;
- visitor isolation.

Long-text checking arrived in v1.6, the rebuilt interface in v1.7, the writing assistant in v1.8, its one input box in v1.9, and its first changes to the records in v2.0, and long tasks across the book in v2.1. Earlier history is kept in the archived repository.
