# Product decisions and validation

## Problem

Long-form fiction accumulates facts that are difficult to keep consistent: event order, character state, world rules, knowledge boundaries, and previously established evidence. A review tool needs to help authors inspect these constraints without replacing authorial control.

## Evidence

- The product workflow requires project-scoped Story Memory, source chapters, drafts, review Runs, Evidence, decisions, and version lineage.
- A review claim is only useful when its Evidence resolves to a current-project SourceSpan.
- A multi-project demo needs account and project isolation to keep one work's context from appearing in another work.
- A model response can vary between runs, so author confirmation and explicit canon updates are part of the product contract rather than optional UI.

## Product decisions

1. **Review, not continuation.** The product identifies continuity risks and presents Evidence; it does not generate the next chapter.
2. **Story Memory is versioned canon.** Memory is a reviewable representation of accepted facts, not an unbounded chat history.
3. **Evidence is a requirement.** Findings are grounded in project-owned SourceSpans or fail closed.
4. **The author decides.** Proposed changes enter a ChangeSet; only accepted items update canon.
5. **Projects are isolated.** User and project scope are checked before access to story context, drafts, Runs, Evidence, decisions, and Reset.
6. **Demonstration state is recoverable.** A confirmed, idempotent project Reset restores the seeded review path.

## Implementation

The currently verified local Web Demo uses FastAPI, SQLite, Next.js, and React. Its API covers authentication, project lifecycle, story context, drafts, checks, Evidence, decisions, ChangeSets, Memory initialization and delta review, append-only source revisions, Reset, and import. The seed includes Grey Harbor Echoes, Paper Moon Archive, and Midnight Garden as independent projects.

Checks use a supported DeepSeek-compatible provider only when the process is explicitly configured. The request is queued, schema-validated, and grounded against current-project SourceSpans before persistence. Fail-closed paths cover unavailable providers, timeouts, invalid JSON, invalid schema, and unresolvable Evidence.

## Evaluation

The published repository baseline is the frozen V4 product evaluation: 15 original, balanced three-class cases over three isolated corpora plus 6 stability reruns. All 21 runs completed.

| Area | Result |
| --- | --- |
| Classification and retrieval | Accuracy, macro F1, conflict recall, insufficient-evidence recall, Hit@5, cited Evidence precision, and Evidence resolvability were all 1.0000. No-conflict FPR was 0.0000. |
| Contract and safety | Schema validity and fail-closed safety were 1.0000. |
| Latency and usage | p50 2593 ms; p95 4104 ms; 16037 input and 2183 output tokens; cost unavailable. |
| Stability | Decision 3/3; category/severity 3/3; Evidence ID set 2/3; exact explanation hash 1/3. |

The frozen CLI PoC's held-out F1 of 0.9412 is a historical result under a different protocol. It is retained as historical context only and is not a V4 Web Demo claim.

Stage 8 and Stage 9 product work are accepted. V5–V8 each retain one immutable first-valid formal result bundle with `gate_failed`, not replaced by later implementation changes. V8 completed all 30 calls; its only Bad Case was `location_action → event_status`, leaving the designated category regression at 2/3. This is retained as a portfolio-level known limitation, and Stage 10 is not reclassified as passed.

Stage 11 has verified the recurring author workflow on real 100k- and 300k-character prefixes: import and initialize Memory, explicitly review candidates, append new chapters, run bounded-RAG Continuity and Memory Delta checks, review Evidence, decide every proposed change, and advance Memory only through author commits. The first 300k run remains an immutable capacity failure; the separate V2 repair passed the frozen Capacity, Performance, and Workflow Gates. The optional 1M-character Stage 11N pressure test is deferred and is not a personal-work release blocker.

Stage 12 V2 passed the Agent Run lifecycle Gate for `queued`, `running`, `completed`, `timed_out`, `failed`, and `cancelled`, including Retry/Cancel provenance and zero partial business writes on non-completion. The V1 Provider-boundary incident remains `gate_failed`. Stage 13 V4 passed the local Web App product Gate: server-only integration boundaries, visitor isolation, limits and cleanup, recovery-email verification and password reset, reproducible standalone packaging, relocation, and full browser regression were independently verified. V2/V3 artifact failures remain historical `gate_failed` evidence.

## Safety boundaries

- Credentials are process-environment configuration, never repository content.
- The retained evidence excludes Authorization values, prompts, raw provider bodies, and chain-of-thought.
- Runtime SQLite databases, fixture workspaces, logs, and build output remain local and ignored.
- The repository does not include or operate the protected CLI PoC, Golden, held-out set, PoC databases, or PoC environment files.
- Without a configured production provider, checks return `503 provider_unavailable` and no Run is created.

## Known limitations and next directions

- Two V4 cases had the correct class but a category mismatch: `timeline → event_status` and `world_rule → event_status`.
- Exact explanation text and Evidence IDs can vary across real-provider reruns even where decision and category/severity remain stable.
- V4 is a compact product evaluation, not a broad benchmark or evidence of commercial deployment.
- The current delivery is not deployed. Stages 12 and 13 have passed their current product Gates; the remaining route is the separately authorised Stage 14 deployment, public-address acceptance, rollback verification, and release.
- The hosted route keeps Provider and SMTP credentials server-only, gives visitors isolated spaces, caps AI calls/text length/total spend, periodically clears visitor data, and implements recovery-email verification plus single-use password reset. It does not add general email identity, OAuth, subscriptions, an admin console, collaboration, cross-device sync, or AI continuation.
