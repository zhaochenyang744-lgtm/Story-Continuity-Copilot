# Story Continuity Copilot

Story Continuity Copilot is a long-form fiction continuity review product whose currently verified delivery is a local Web Demo. It combines versioned Story Memory with a continuity agent that returns grounded findings for an author to review. It does not write the next chapter: the author remains responsible for the text and explicitly decides whether a proposed Memory change becomes canon.

The repository is designed for local reproduction. It contains the application source, migration and seed logic, tests, sanitised V4–V8 evaluation result records, and a small set of production-workflow screenshots. It does not include runtime databases, environment files, provider credentials, raw provider responses, recorded runtime prompt bodies, chain-of-thought, or protected evaluation assets. Full V5–V8 post-run database-hash validation therefore also requires the separately retained local evaluation workspaces; the committed result files alone do not recreate those SQLite artifacts.

## What the demo does

The author workflow is:

1. Sign in locally, create or import a project, and select a project workspace.
2. Review outline, characters, world rules, chapters, and versioned Story Memory.
3. Submit the current draft for a continuity check.
4. Inspect each finding together with resolvable Evidence from the current project.
5. Accept, reject, or edit proposed Memory changes. A ChangeSet records the decision; only accepted changes update canon.
6. Use project Reset to restore the seeded review path when a fresh demonstration is needed.

Three independently seeded projects are available: **Grey Harbor Echoes**, **Paper Moon Archive**, and **Midnight Garden**. Their project data, Memory, drafts, and review state are isolated per account and per project.

## Product and safety boundaries

- The FastAPI backend exposes 24 API endpoint templates for authentication, projects, story context, drafts, checks, Evidence, decisions, ChangeSets, Reset, and import.
- Every project resource is checked against the current session and project ownership. Cross-account access returns a not-found response without disclosing the resource.
- Evidence must resolve to a SourceSpan owned by the active project. Unresolvable Evidence fails closed.
- An explicitly configured `DeepSeekProvider` supports real local checks. When no production provider is configured, a check returns `503 provider_unavailable`; it does not create a Run or substitute a static result.
- Reset is project-scoped, confirmed, idempotent, and constrained to this demo's runtime database.

## Evaluation and verification

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

V5–V8 each retain one immutable first-valid formal result bundle with `gate_failed`; later work does not overwrite or rerun them. In V8, all 30 calls completed and all core classification and Evidence measures were 1.0000, but the designated category regression was 2/3 because one `location_action` case was classified as `event_status`. This single category deviation is retained as a portfolio-level known limitation, while the Stage 10 Gate remains failed.

Stage 11 has since verified the author-controlled long-form workflow on a real 100k-character prefix and a 300k-character prefix. The accepted 300k V2 result completed initialization plus two append/review/decision/commit rounds with bounded RAG, valid Evidence lineage, no automatic canon writes, and a 4,820,992-byte final SQLite database. The first 300k V1 capacity failure remains immutable alongside the V2 pass. The optional 1M-character Stage 11N pressure test has not been run; Stages 12–14 have not started.

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
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal:

```powershell
Set-Location frontend
npm run dev
```

Open `http://127.0.0.1:3000`. The frontend rewrites same-origin `/api` requests to `http://127.0.0.1:8000` by default. See [local setup and reproduction](docs/local-setup.md) for health checks, isolated E2E startup, and provider configuration boundaries.

## Test

```powershell
# Backend contract and regression suite
Set-Location backend
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
npm run lint
npm run typecheck
npm run build
```

The backend suite includes the 24-endpoint contract coverage. The release-bundle validator checks that the published V4 results, frozen assets, recorded workspace metadata, documentation, and screenshots are self-consistent; it does not claim to reopen unpublished SQLite workspaces. Browser E2E requires the isolated FastAPI/Next.js processes described in [the local setup guide](docs/local-setup.md); it uses a test-only provider and a temporary database rather than the local demo database.

## Demo path

The [3–5 minute demo guide](docs/demo-guide.md) walks through project selection, a completed continuity review, Evidence, author confirmation, and Reset. The guide does not require provider calls.

## Known limitations

- The currently verified version is a local demo, not a deployed service or a claim of production operation. A lightweight hosted Web App is a planned later route.
- V4 is a small, frozen product evaluation; it supports the stated evaluation claims only and is not a general benchmark.
- Real provider output can vary. The retained stability evidence shows variation in Evidence IDs and exact explanation hashes even where decision and category/severity were stable.
- The provider returns no cost in the retained V4 results.
- The system supports continuity review and author-controlled canon updates; it does not directly continue the novel.

## Further reading

- [Local setup and reproduction](docs/local-setup.md)
- [3–5 minute demo guide](docs/demo-guide.md)
- [Product decisions and validation](docs/product-decisions-and-validation.md)
- [Verification and known limitations](docs/verification-and-limitations.md)
- [Curated verification artifacts](artifacts/README.md)
