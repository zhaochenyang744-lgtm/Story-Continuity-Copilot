# v1.2.0 durable tutorial progress verification

Date: 2026-09-01

Scope: local implementation and verification only. No commit, push, deployment, external Provider HTTP call, environment-file edit, or Gate declaration was performed.

## Implemented contract

- `GET /api/onboarding` returns canonical tutorial progress for the authenticated registered account while onboarding is active.
- `POST /api/onboarding/progress` is strict, CSRF-protected, UUID-idempotent, version-bound to `1.2.0`, and accepts only the four server-mapped business events.
- Progress is stored in SQLite with a monotonic step, canonical completed-event order, revision, and update timestamp.
- Duplicate business events do not increment the revision. Out-of-order events cannot reduce the step. Replaying an old idempotency key returns the current canonical progress.
- The target must be the current user's current `tutorial_seed` project. Visitors, foreign/ordinary projects, wrong versions/events, extra fields, missing keys, and cross-site writes fail closed.
- Complete, skip, and first real import hide progress. Reopen resets both the deterministic fixture and progress to step 1 while advancing the progress revision.
- Only business progress is durable. Drawer state, focus, pulse, highlight, CTA guidance claims, and the 12-second idle timer remain client-only and reset on reload.

## Verification results

- Backend focused suite: 10/10 passed (`test_v120_tutorial_progress` plus existing `test_v110_onboarding`).
- Backend full suite: 156/156 passed in 154.478 seconds.
- Frontend ESLint: passed.
- Frontend TypeScript (`tsc --noEmit`): passed.
- v1.2 browser acceptance: 1/1 passed in approximately 1.5 minutes, including hard-refresh and logout/login restoration at step 2.
- Frozen v1.1 browser compatibility: 5/5 passed.
- Frontend build/runtime contract suite: 27/27 passed.
- Production builds: current v1.2 and frozen v1.1 profiles both compiled successfully.
- Injected browser backends on ports 8194 and 8190 reported `provider_http_calls=0` and `provider_calls=0` after verification.
- Git branch remained `codex/v1.2.0`; HEAD remained `e07048f9a66de769aa59152710f89df742c50a34`.

## Preserved first-failure chain

1. Initial repository-root unittest discovery could not import `app` (15 collection errors).
2. Correct backend working directory without the required local public-mode settings produced 95 `public_app_mode_required` errors.
3. Setting only `PUBLIC_APP_MODE=0` produced 95 `public_config_required` errors.
4. With the complete isolated local configuration, the pre-change baseline passed 149/149.
5. The first new focused run passed 6/7; the invalid-target fixture had created a real project through the public API, which correctly completed onboarding before target validation. The fixture was changed to create the ordinary project directly in the isolated database, after which 7/7 passed.
6. The first two v1.2 browser attempts stopped at session bootstrap because the temporary server launch did not serve production chunks, then because the development server rejected `127.0.0.1` dev chunks and its strict CSP disallowed development `eval`. No product assertion ran in either attempt. The production `next start` process then served the built chunks and the acceptance passed 1/1.
7. The first frozen v1.1 command used a temp directory with the wrong profile prefix and failed closed with `E2E_TEST_ROOT_PROFILE_MISMATCH`; the corrected `story-v110-impl-` root passed 5/5.

These environment and fixture failures were retained as evidence and were not replaced with product-success claims.
