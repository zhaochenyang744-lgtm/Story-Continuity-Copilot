# V6 offline implementation handoff

## Frozen identity and limits

- Base commit: `7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`.
- Manifest: `evaluation/current_flash_v6/frozen-inputs.json`, SHA-256 `f0e2cb3d5c44a1a92000f703423a0d26ea1fab5aef750b7a3393102ea98ed696`; 876 source and evidence files hashed. `freeze verify` and `live_guard --verify-only` both passed after freezing.
- Planned live matrix: 34 logical inputs (24 preserved comparison inputs and 10 deduplicated new inputs representing 12 semantic controls). The upper bounds are 136 generation POST attempts and one `/models` GET attempt. No live identity has been reserved or used.
- The guard checks unique `flash-v6-*` identity first, manifest SHA second, every manifest dependency hash with standard-library code third, and only then imports the product and repeats frozen parameter and input validation. Any occupied identity or changed dependency fails before product import and dispatch.

## Offline evidence

- `runs/prep-v6-02/` finished 34/34 API input captures, each bound to its own isolated SQLite database and same-run request audit. It made zero generation POSTs and zero `/models` GETs. Source selection in the lens control is L1/L2/L4, with L3 unselected and represented only by Memory.
- First failed `prep-v6-01/` and its input-v1 `cases.json`/`corpora/` are retained. The API fixture lacked Memory for some new controls; the lens fixture also selected L3 among the top three. `INPUT-ADAPTATION.md` declares the v2 adjustment before the completed preparation. No previous version result or gold was rewritten.
- Product continuity prompt is `continuity-review-v16-joint-evidence-coverage`. `backend/app/provider.py` SHA-256 `ed33b19761acfec79cff0a14d171389eaa9659ba4774223a4d161c58d2d32643`; `backend/app/engine.py` SHA-256 `527f986d6441aa226f239a0e67d928200f26d77b6b90e65cbc6d14e512d7fd39`.
- The V6 scorer checks each raw evaluation and the persisted final separately, including exact claim coverage, selected sources, declared joint sets, relation roles, time policy, uncertainty limits, category limits, and terminal failure. All structurally passing cases still require independent semantic review. Scorer SHA-256 `35c21fce0ceaffab9823d29c5b6bc048199fb144787330f2d9a242c0658f4e8e`.
- The 42 product/core regression tests and 10 V6 offline tests passed. The V6 tests include inherited case 13's rule-as-context plus named-twin contradiction and guard rejection before product import. Independent engineering, semantic, and G02 review records live under `docs/flash-v6-independent-acceptance-evidence/`; the semantic scoring-role review and input probes were included in the frozen manifest.

## Decision boundary

This is a frozen offline candidate for the controller's independent acceptance. It has no V6 real-model quality result, user acceptance, release, or deploy claim. A future authorized live run must use a newly fixed identity and the exact manifest SHA above. The live guard is `python -m evaluation.current_flash_v6.live_guard --run-id <fixed-id> --manifest-sha256 <exact-sha>`; `--verify-only` performs all preflight checks without dispatch.
