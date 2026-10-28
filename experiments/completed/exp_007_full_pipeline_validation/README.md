# exp_007_full_pipeline_validation

Full-pipeline validation & research-readiness for Project 07, building on `exp_007_advanced_validation`
(commit `9f0cef0`). Extends the earlier *representative*-model + restricted-grid analysis to the **actual
Project-04 model** and the **broadest verified trial universe**. Validation campaign — **no parameters
changed, no new signals, 6/7 gate untouched, no candidate promoted, no live trading.** Branch not merged.

## Start here
- `reports/FINAL_VALIDATION_REPORT.md` — the 8 research questions, classifications, what's still required.
- `reports/PROJECT04_MODEL_LINEAGE.md` — the actual OLS blend, exact reproduction, and the finalizer blocker.

## Deliverables (`reports/`)
1. `PROJECT04_MODEL_LINEAGE.md` — model traced; predictions reproduced exactly (V1 7.4e-9, V2 2.1e-6); the
   saved portfolio series is only approx-reproducible (documented blocker).
2. `FULL_MODEL_CPCV_REPORT.md` + `CPCV_MODEL_RESULTS.csv` + `CPCV_MODEL_RESULTS_era2016.csv` — Q1/Q2.
3. `HISTORICAL_TRIAL_LEDGER.csv` — 51 trials, provenance + documented/inferred tags (Q3).
4. `PBO_SELECTION_SENSITIVITY.md` + `PBO_EXPANDED_RESULTS.csv` — Q4 (+ `data/pbo_candidate_corr.csv`).
5. `STATISTICAL_INTEGRITY_RECONCILIATION.md` — six-layer reconciliation (Phase 6).
6. `DD_ONLY_FOLD_ATTRIBUTION.md` + `DD_ONLY_FOLD_ATTRIBUTION.csv` — Q5/Q6.
7. `PAPER_TRADING_PROTOCOL.md` + `SHADOW_TRADING_READINESS.md` — Q7 (harness: `scripts/shadow_trader.py`).
8. `evidence_record.json`, `MANIFEST_SHA256.txt`.

## New tests
`research/project_07_statistical_integrity/tests/test_full_pipeline_validation.py` (8) — exact model
reproduction, feature/label alignment, combined-signal identity, **the finalizer blocker encoded as a test**,
CPCV purge integrity, fold MDD/vol invariants, and the overlay-vs-P04-family PBO contrast. Full suite: **304
passed, 11 skipped**.

## Headlines
- Actual P04 model = **blend of two OLS fits** (V1 sign-flipped + V2), reproduced **exactly** at the
  prediction level; **portfolio finalizer not bit-reproducible** (blocker documented, not papered over).
- Purged CPCV: deployed blend has **weak, regime-dependent** rank skill (full-sample ≈ 0; 2016+ ≈ +0.009);
  the **representative ridge overstated** full-sample skill (0.030).
- Expanded PBO **stays low** (0.0014/0.0043) but the overlay grid is **~1 effective dimension** → **lower
  bound**; the distinct **P04-construction layer overfits** (PBO 0.46–0.77).
- DD Only: **7/7 shallower MDD, 7/7 lower vol**; 4/7 Sharpe (gate preserved as failure); 2/3 misses are a
  negative-regime Sharpe artifact, 1 is opportunity cost.
- Shadow-trading harness built, smoke-tested, **simulation-only**; feeds not yet wired. No promotion, no real
  capital.

## Reproduce — see `reports/FINAL_VALIDATION_REPORT.md` §Reproduce.
