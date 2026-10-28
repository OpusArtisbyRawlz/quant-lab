# CPCV METHODOLOGY — Stage B4

**Module:** `src/statistics/cross_validation.py::cpcv_splits` · **Tests:** `test_cross_validation.py`
**Applications:** `scripts/b_model_level_cv.py` (model), `scripts/b_selection_pbo.py` (selection)
**Results:** `CPCV_RESULTS.csv`

---

## 1. Design
Combinatorial Purged Cross-Validation (López de Prado 2018, ch. 12): partition the timeline into `N`
contiguous groups; every combination of `k` groups is a test set (groups may be non-adjacent); the
complement trains after **purge + embargo** applied against *each* test block. Number of folds =
`C(N, k)`. Reported per the spec: n_groups, test combinations, valid folds, train/test sizes, purged
and embargoed counts, OOS performance distribution, dispersion, worst/best paths, limitations.

Two statistical objects are validated — kept explicitly separate:

## 2. Model-level CPCV (prediction generalization)
Object: P04 `features → fwd_ret_5`, representative ridge forecaster, dates as the unit, horizon 5.
`N=8, k=2 → C(8,2)=28` paths, embargo 5 dates, ~15 dates purged/split.

| metric | value |
|---|---|
| OOS rank IC — mean | 0.0354 |
| std / p05 / median / p95 | 0.0109 / 0.0198 / 0.0337 / 0.0535 |
| fraction of paths with IC > 0 | **1.00 (28/28)** |

The forecasting signal (~0.035 IC) is **positive on every combinatorial path** — modest but robust
generalization, not a single-split artifact. This validates prediction generalization of the
representative forecaster (not the exact production model).

## 3. Selection-level CPCV (strategy-robustness)
Object: the overlay candidate family (71 series; see PBO methodology). For each symmetric split the
in-sample-best candidate is chosen and scored out-of-sample; the distribution of its OOS **relative
rank** measures selection robustness. (This shares the CSCV engine with PBO — §PBO.)

| objective | OOS rank mean | p05 | p95 | fraction below OOS median |
|---|---:|---:|---:|---:|
| Sharpe | 0.974 | 0.875 | 0.986 | 0.0016 |
| Calmar | 0.964 | 0.806 | 0.986 | 0.0112 |

The in-sample-selected overlay sits in the **top ~3%** out-of-sample almost always — the overlay
effect is a persistent structure, not noise.

## 4. What CPCV here validates — and what it does NOT
- Model-level CPCV validates **prediction generalization** of a representative forecaster.
- Selection-level CPCV validates **strategy-selection robustness** across combinatorial splits.
- Both use **non-chronological** IS/OOS unions, so they are **research robustness tests, NOT
  live-trading chronological walk-forward replicas** (the predefined walk-forward promotion gate in
  `exp_006` remains the chronological OOS test of record, and it failed 4/7 on Sharpe — see
  REMEDIATION_FINALIZATION A3).
- Because the full P04 model-search and P05 overlay-form search are not reconstructable, selection-level
  CPCV covers the **overlay grid only** — it does not certify the entire research pipeline.
- Overlapping/dependent paths mean the OOS paths are **not independent**; dispersion understates true
  uncertainty. Reported, not worked around.
