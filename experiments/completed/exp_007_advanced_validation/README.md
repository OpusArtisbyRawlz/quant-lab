# exp_007_advanced_validation

Stage A (remediation finalization) + Stage B (purged/embargoed CV, CPCV, PBO) + Stage C (consolidated
assessment) for Project 07. Validation campaign — no parameters changed, no overlay optimized, the 6/7
promotion gate untouched, no candidate promoted. Builds on `exp_007_p06_p07_remediation` (commit 8a3f9e0).

## Start here
- `reports/PROJECT_07_ADVANCED_VALIDATION_REPORT.md` — Stage C: the 3 questions, classifications, gate.
- `reports/REMEDIATION_FINALIZATION.md` — Stage A: A1 commit, A2 warm-up+financing, A3 fold study.

## Deliverables (`reports/`)
1. `REMEDIATION_FINALIZATION.md`
2. `PURGING_EMBARGO_VALIDATION.md`
3. `CPCV_METHODOLOGY.md`
4. `CPCV_RESULTS.csv`
5. `PBO_METHODOLOGY.md`
6. `PBO_RESULTS.csv`
7. `STRATEGY_SELECTION_INTEGRITY.md`
8. `PROJECT_07_ADVANCED_VALIDATION_REPORT.md`
9. `UPDATED_EVIDENCE_LEDGER_ENTRY.json`
10. `scripts/`, `logs/`, `data/`, `evidence_record.json`, `MANIFEST_SHA256.txt`

## New reusable modules + tests
- `src/statistics/cross_validation.py` — purging, embargo, PurgedKFold, CPCV (tests: `test_cross_validation.py`, 12).
- `src/statistics/backtest_overfitting.py` — PBO via CSCV (tests: `test_backtest_overfitting.py`, 7).

## Headlines
- Combined warm-up corrected consistently → MC fidelity 0.0112 → **5.6e-16** (caveat cleared); V1/DD Only unchanged.
- Promotion gate preserved as a **failure** (DD Only Sharpe 4/7 < 6/7; MDD 7/7); the 3 Sharpe-miss folds
  are losing-regime de-risking, not inferiority.
- Model-level purged CV: representative forecaster OOS rank IC ~0.035, leakage-robust, positive on all 28 CPCV paths.
- **PBO 0.0016 (Sharpe) / 0.0112 (Calmar)** — overlay selection not overfit *within the grid*, but a
  **lower bound** (full P04/P05 search not reconstructable). Grid IS-winner `dd_f0.2_k7` is **not** promoted.
- Full suite 296 passed, 11 skipped.

## Reproduce
```
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_advanced_validation/scripts/a3_fold_investigation.py
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_advanced_validation/scripts/b_model_level_cv.py
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_advanced_validation/scripts/b_selection_pbo.py
PYTHONPATH=. venv/bin/python -m pytest research/project_07_statistical_integrity/tests research/project_06_deployment_validation/tests -q
```
