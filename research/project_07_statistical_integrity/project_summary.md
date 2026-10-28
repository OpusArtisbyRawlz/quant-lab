# Project 07 — Statistical Integrity: Project Summary

## Current status

**Scaffold complete; implementation not started.** This project contains
documentation, notebook skeletons (headings only), module interfaces (typed
signatures with `NotImplementedError` bodies), the Evidence Ledger schema, and
test skeletons. No statistical algorithm, result, or output has been produced yet.

Baseline: branched from `m11-pr3-promotion-engine`, following the frozen Project 06
baseline (tag `project-06-deployment-validation-frozen`). Projects 01–06 are
unmodified.

## Objectives

1. Quantify the sampling uncertainty of strategy performance metrics (bootstrap
   confidence intervals).
2. Obtain empirical significance under an explicit null (Monte-Carlo / permutation).
3. Penalize performance for the number of hypotheses tested and for non-normality
   (Deflated Sharpe Ratio, minimum track-record length).
4. Control the family-wise / false-discovery error across all evaluated
   hypotheses (FDR, Bonferroni, Holm).
5. Guard against data-snooping across a strategy family (White's Reality Check,
   Hansen's SPA).
6. Produce a single, auditable statistical-integrity verdict per strategy.
7. Record the full provenance of every conclusion in an append-only Evidence
   Ledger.

## Deliverables

- `src/statistics/` — seven documented modules (bootstrap, monte_carlo,
  significance, deflated_sharpe, white_reality_check, evidence, report).
- Seven analysis notebooks (`01`–`07`).
- The **Evidence Ledger** schema and interface (`evidence.py`, notebook 07).
- A consolidated statistical-integrity report (notebook 06).
- Regression tests under `tests/` (skeletons now; golden-master later).
- `README.md` and this summary.

## Dependencies

- **Upstream (read-only):** frozen Project 06 baseline; Project 05 reference
  strategy export (`experiments/completed/exp_005_risk_engine_final/`); the trial
  record (hypotheses/configurations evaluated during research).
- **Libraries:** `numpy`, `pandas`, `scipy` (existing project virtualenv);
  `pytest` for tests.
- **Internal:** `src/utils/metrics.py` for base performance metrics (reused, not
  reimplemented).

## Milestones

| ID | Milestone | Definition of done |
| --- | --- | --- |
| P07-0 | **Scaffold** (this) | Docs, notebook skeletons, typed module interfaces, ledger schema, test skeletons. No implementation. |
| P07-1 | Bootstrap | `bootstrap.py` implemented + NB 01 + tests green. |
| P07-2 | Monte-Carlo / permutation | `monte_carlo.py` + NB 02 + tests. |
| P07-3 | Deflated Sharpe | `deflated_sharpe.py` + NB 04 + tests. |
| P07-4 | Multiple testing | `significance.py` + NB 03 + tests. |
| P07-5 | Reality Check / SPA | `white_reality_check.py` + NB 05 + tests. |
| P07-6 | Evidence Ledger | `evidence.py` storage + NB 07 + tests. |
| P07-7 | Report + verdict | `report.py` + NB 06 + golden-master regression. |

Each milestone is additive, independently reviewable, and stops for approval — the
cadence used in Projects 05–06.
