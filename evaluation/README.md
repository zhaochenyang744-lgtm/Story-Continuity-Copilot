# Evaluation assets

This directory holds the evaluation programs and sets that are still in use. The evaluation rounds, scripts and result bundles of v1.0–v1.6 (V1–V10 case sets, `current_flash_*`, `model_compare_*`, their validators and runners) were removed in v1.8.0; they remain in Git history.

Every formal set is written in a separate session, never read during development, and run once against thresholds registered before it was authored. A set is spent once it has been run. See the [evaluation maintenance policy](../docs/evaluation-maintenance.md).

## Assistant evaluation (v1.8.0)

- `assistant_a1/`, `assistant_a1b/`, `assistant_a1c/` — the runner, scorer, judge and pre-registered thresholds (`SPEC.md`, `thresholds.py`) for the built-in assistant. A1 and A1b cover short works; A1c covers real chapter lengths.
- Sets: `eval_set_a1_*`, `eval_set_a1b_*`, `eval_set_a1c_*`, `eval_set_a1cx_dev`, `eval_set_a1cs_formal`. Run with `python -m evaluation.assistant_a1.run --set <set> --runs <n> --run-id <id>`; `--dry-run` checks the set and the configuration without calling a model.

## Long-text checking

- `longform/` — format, validator, scorer, metered runner and pre-registered thresholds for whole-chapter checking ([PLAN.md](longform/PLAN.md)). Sets: `eval_set_lf1_dev`, `eval_set_lf1_import`, `eval_set_lf1_formal`, `eval_set_lf2_formal`. The first formal run failed on insufficient-evidence recall and maximum cost; the fix passed every registered threshold on the fresh 26-chapter set `lf2-formal` and decided the review prompt shipped in v1.6.0.
- `tests/test_longform.py` — offline tests of the long-text tooling.

## Chapter-check held-out sets

- `v11_holdout/` — runner and thresholds for the short-draft held-out sets: `python -m evaluation.v11_holdout.run --run-id <id>`.
- `eval_set_v11_authoring`, `eval_set_v12_authoring` — spent (V11 failed twice on insufficient-evidence recall; V12 passed with prompt v24c). `eval_set_v13_authoring` is kept as it was and is not to be opened for development.

## Results

The runners write their reports to `results/`. The recorded runs the documents above refer to (`a1-*` for the assistant, `longform-*` and `prod-longform-*` for long text, `eval-v11-*` and `eval-v12-*` for the short-draft held-out sets) are about 270 MB and are kept in the project's archived repository, not in this one; the SPEC and PLAN files quote the numbers that decided each gate.

Model runs need `CONTINUITY_*` provider variables and are never part of the unit tests; the offline suite is `python -B -m unittest discover -s evaluation/tests -t .` with `PYTHONPATH=backend;.`.
