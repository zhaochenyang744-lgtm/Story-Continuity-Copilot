# Current-contract comparison V2 handoff

**Status:** implementation and bounded offline/synthetic API self-test complete. This is seen development material; independent gold acceptance and real-model quality scoring remain pending.

## Deliverables

- `cases.json` and four synthetic corpora: 24 one-to-one V1 successor cases, with per-case time scope, rationale, minimum sufficient Evidence, optional background, allowed outcomes, and V1 lineage.
- `actual-inputs.json`: 24 current business requests captured through the isolated API; 24/24 required source sets retrieved and selected.
- `contract-probe-results.json`: 24/24 minimal raw responses accepted by the current validator.
- `api-score-probe-results-v2.json`: 24 base plus two supported state-change runs, all completed; 26/26 current business content matched the preflight capture, first-raw structural check passed, and final-product structural check passed. All 26 semantic statuses are `pending_manual_review`. Raw first, absent repair, and final product are separate fields. Real Provider calls: zero.
- `test_offline.py`: five tests covering case balance, frozen capture, valid state-change variants, extra/unrelated or tampered Evidence, wrong claim/category/nature/relation, terminal status, and raw temporal errors.
- `v1-lineage.json`: one-to-one case map, with V1 manifest SHA-256 `d0da4eb5037c5ce8e724d0263255654d97fb25cc975e5e419786ea5a60c8d29c`.
- `frozen-inputs.json`: final V2 freeze manifest, SHA-256 `35b8a9559b9d5138f21795cdeb74439d010490dd5a9ee07a37cd48dbd44ca337`.

## Verification and boundaries

`evaluation/current_contract_compare_v1/freeze.py verify` and V2 `freeze.py verify` both returned `ok: true`. The V2 offline unittest suite passed 5/5. The preflight and API probe use only isolated synthetic fixtures and scripted Providers. G02 product code, V1 frozen inputs and results, V8 and older results, Provider accounts, `.env`, author data, and SMTP were not changed by this task. No commit, push, or deploy was made.

The review-ready question is whether an independent reviewer accepts each V2 gold label and time/source rationale. The current machine pass does **not** establish narrative correctness or model accuracy. Real Provider testing, if separately authorized after gold acceptance, should retain and report first raw response, every repair response, and final product separately; count terminal failures and timeouts outside no-conflict; and manually adjudicate structural passes and equivalent citation combinations.
