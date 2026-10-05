# Current-contract comparison V2 rubric

This is a **seen development** set derived one-to-one from V1 after the independent round-two review. It is not a blind holdout, a real-model evaluation, or a same-input comparison with V1. V1 and its frozen manifest remain unchanged. The synthetic stories, sources, and drafts here exist only for evaluation.

## Case contract

There are four works, eight axes, and one conflict, close control, and insufficiency case per axis (24 cases). Each case declares its source lineage, time scope, label reason, allowed outcomes, minimum sufficient evidence set, and optional recommended context. A sufficient alternative may be added only by revising this seen-development set and recording why; the scorer does not silently treat every retrieved source as interchangeable.

The three rule-based conflicts now have an unexpired rule **and** a source fact at the same story time as the draft claim. Static rules alone do not establish Mira's 10点 badge, the carrier's 10点 cap, or the boat's 10点 launch state. The relationship conflict uses a permanent kinship rule and the same pair's twin register. The remaining conflicts use explicit same-day observations or event order.

The knowledge and later-movement controls permit either no Issue or `state_change` when the cited evidence actually supports the transition. The `state_change` path requires the target claim, matching category, `supports/sufficient` Evidence, and its declared minimum source set. Two separate synthetic API runs exercise that path. Other controls permit no Issue only.

Five insufficiency cases have one unknown-field source as the minimum; their second source is optional background. The remaining three have one minimum source. Insufficiency citations must be `context/insufficient`, with `missing_link` chain roles and no available action or suggested revision. Unknown identity, actor, cause, birth order, reopening, or companion is never promoted to a confirmed fact.

## Score layers

1. Capture: `actual-inputs.json` records the real business request assembled by the isolated API. Retrieval and selected-source presence are checked for all 24 cases.
2. Raw first and repair: the API probe records `raw_first`, its separate structural score, and `raw_repair` for each synthetic call. `raw_repair` is `null` when no repair occurred. Raw scoring checks outcome, source IDs, relation, and temporal-basis form. These are model-contract inputs, not final product Issues. A future Provider evaluation must retain every first response and repair attempt separately.
3. Final product: `score_one` takes a product response **and its own captured business request**, checks completed status, exact target ID/text, category/nature, every Evidence source's chapter, excerpt, source body, revision and Memory binding, declared minimum and optional source policy, relation/sufficiency, and Evidence chain. An undeclared extra citation fails even when minimum citations are present. A failed or timed-out run is terminal; `possible_conflict` cannot count as confirmed.
4. Semantics: a structural pass is returned as `machine_result=pass`, `semantic_result=pending_manual_review`, and overall `result=pending_manual_review`. A human must check the draft/source meaning, actual transition, same-time scope, and whether an alternative evidence combination is truly sufficient. No synthetic pass is a raw-model accuracy claim.

The scripted API probe covers 24 base runs plus two state-change positives. It makes no real Provider calls. Positive controls only show the current product accepts and persists the shaped response. Negative controls mutate the resulting Issue to test extra unrelated Evidence, wrong relation, tampered chapter/excerpt, wrong claim and Memory links, invalid state-change categories/natures, terminal status, and possible-conflict upgrading.

## Real Provider use later

Do not reuse synthetic API counts as model quality. Before any real Provider call, an independent reviewer should accept the V2 gold semantics and the exact request capture. Then run a separately authorized, bounded call batch, retain first raw response and repair raw response, score the final product by this rubric, manually review every structural pass, and report failures/timeouts separately from no-conflict. No real Provider call is authorized or included here.
