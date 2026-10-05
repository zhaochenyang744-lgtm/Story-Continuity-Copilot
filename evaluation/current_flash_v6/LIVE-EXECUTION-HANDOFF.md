# V6 fixed live execution handoff

## Identity and integrity

- One authorized run: `flash-v6-20260927-01`. The original 876-file manifest SHA-256 remained `f0e2cb3d5c44a1a92000f703423a0d26ea1fab5aef750b7a3393102ea98ed696`.
- Before any Python evaluation module import, PowerShell checked `evaluation/__init__.py` against `PRELAUNCH-SUPPLEMENT.json` SHA-256 pin `4ac37fe3ac5b99e494187cd7439b71a422595cc8c0825c5b725c1703d7f990b5`. The non-sensitive check is recorded in `docs/flash-v6-independent-acceptance-evidence/PRELAUNCH-RECEIPT.json`. The live guard then verified the frozen manifest. No key content was printed or saved.
- Run evidence: `evaluation/current_flash_v6/runs/flash-v6-20260927-01/`. No quality-driven rerun or second live identity was used.

## Execution and usage ledger

| Measure | Observed |
| --- | ---: |
| Logical cases finished / planned | 34 / 34 |
| Comparison / new control inputs | 24 / 10 |
| Generation POST starts / finishes / HTTP responses | 49 / 49 / 49 |
| Generation HTTP status | 49 × 200 |
| `/models` GET starts / finishes | 1 / 1; HTTP 200 and model present |
| Usage complete / missing / partial / unknown | 49 / 0 / 0 / 0 |
| Prompt / completion tokens reported | 168,459 / 12,568 |
| Request captures / parsed evaluations / input audits | 49 / 49 / 34 |
| Isolated databases | 34 |
| Service stop / run-level first failure | false / absent |

The run used 49 of the 136 allowed generation POST attempts and the single allowed models GET. All 34 cases have `case-finish.json`, `scores.json`, a same-run input audit, and a persisted product terminal record. Fifteen cases used the one allowed contract repair; the first raw response passed machine checks in 12 cases and a repair passed in 2. Every raw and repair answer is retained independently.

## Machine result; semantic review pending

| Input group | Machine pass | Machine fail after completed product | Terminal product failure | Total |
| --- | ---: | ---: | ---: | ---: |
| Preserved 24 | 10 | 5 | 9 | 24 |
| New 10 | 4 | 1 | 5 | 10 |
| All | 14 | 6 | 14 | 34 |

The six completed-but-machine-failing cases are 06 (`required_issue_missing`), 10 (`undeclared_extra_evidence`), 13 (`premise_mislabeled_direct_contradiction`), 15 (`category_mismatch`, `undeclared_extra_evidence`), 19 (`category_mismatch`), and 31 (`category_mismatch`). Terminal errors were `claim_verdicts_invalid` in 8 cases, `claim_verdicts_issue_mismatch` in 5, and `evidence_unresolvable` in 1. In the inherited old24, final machine passes were 3/8 conflict, 7/8 no-conflict, and 0/8 insufficient-evidence. A machine pass is only a structural and declared-source-role result; all 14 machine passes remain pending independent semantic review.

## Observed contract failure pattern and next-version candidates

The current validator requires a non-empty `claim_verdicts.basis` of at most 400 characters, while the model-facing instruction says only “brief”. Fourteen saved verdicts across raw and repair outputs exceed 400; cases 17 and 27 exceeded the limit on both evaluations. Cases 05 and 20 show the same first-answer length error repaired within the fixed single repair. This is a measured field-length contract failure. A next version can put the exact 400-character limit in the model-facing schema and repair instruction, then verify that limit without weakening the validator.

Cases 03, 09, 18, and 28 emitted `insufficient_evidence` verdicts with empty Issues on both evaluations; case 12 did so on repair. The current repair payload carries `rejected_issues` but not the rejected `claim_verdicts` ledger. This limits the model's concrete view of the ledger/Issue mismatch during repair. A next version can include the complete rejected ledger and a specific correction rule requiring an insufficient-evidence Issue for that verdict. Those changes require a new freeze and separate test; this run's outputs and scores remain untouched.

Independent diagnostics in `docs/flash-v6-independent-acceptance-evidence/ROOT-LIVE-FAILURE-DIAGNOSTICS.json` identify a separate product validator gap. In new controls 25 and 26, the first answers attempted the joint evidence with matching `At 14:00 today` / `At 10:00 today` anchors, but the unchanged temporal helpers reject even identical 24-hour English anchors as non-explicit/non-overlapping. The same helper accepts `今天10点`. Those first-answer failures must not be attributed solely to model reasoning. A next version should add and test `HH:MM today` parsing with matching and non-matching times before any new live run; the current output and frozen validator remain unchanged.

This handoff reports execution and machine scoring only. The independent reviewer has identified failures that prevent current V6 quality acceptance; user acceptance and release readiness are also not established.
