# FULL-MODEL PURGED CPCV REPORT (Phase 3)

**Experiment:** `exp_007_full_pipeline_validation` · script `scripts/p3_full_model_cpcv.py`
Results: `CPCV_MODEL_RESULTS.csv` (full sample) and `CPCV_MODEL_RESULTS_era2016.csv` (deployment era).
Tags: **[V]** verified by execution, **[I]** inferred, **[U]** unavailable.

## Method
The **actual** Project-04 OLS pipeline (exactly reproduced — see `PROJECT04_MODEL_LINEAGE.md`) is
evaluated under combinatorial purged cross-validation. Panel = inner-merge of the two feature
matrices on `(Date,Ticker)`; label `fwd_ret_5` (5-trading-day forward → **overlapping labels**).
Purging and embargo operate on the **unique-date axis** (each date's label interval `[d, d+5]`);
date splits map back to panel rows. For every split an OLS is **retrained from scratch** on the
training dates only; the V1 leg is sign-flipped and the per-date z-score combine is applied to the
held-out dates only (no transform sees test data). CPCV: `n_groups=8, k_test=2` → **28 paths**.
Deterministic (closed-form OLS/ridge; no RNG). **This is a leakage-controlled robustness test, not a
chronological walk-forward** — CPCV unions non-contiguous blocks and must not be read as live timing.

## Results — rank IC (Spearman), pooled across 28 paths [V]

**Full sample (1985-06-24 … 2026-03-06; 10,254 dates, 20 tickers):**

| model | pooled rank IC | per-path mean ± disp | frac paths > 0 | Pearson IC |
|---|---|---|---|---|
| **Actual combined blend** | **−0.0012** | −0.0012 ± 0.0129 | 0.54 | ~0 |
| Actual V1 leg (flipped) | −0.0116 | −0.0116 ± 0.0167 | 0.21 | neg |
| Actual V2 leg | +0.0141 | +0.0141 ± 0.0136 | 0.79 | pos |
| Representative ridge(α=10) | **+0.0300** | +0.0300 ± 0.0142 | 1.00 | pos |

**Deployment era (Date ≥ 2016; 2,558 dates — the window the model was actually used in):**

| model | pooled rank IC | frac paths > 0 |
|---|---|---|
| **Actual combined blend** | **+0.0094** | 0.71 |
| Actual V1 leg (flipped) | +0.0063 | 0.54 |
| Actual V2 leg | +0.0002 | 0.57 |
| Representative ridge(α=10) | +0.0096 | 0.61 |

**Embargo sensitivity** (actual combined): full-sample pooled IC = −0.0012 / −0.0012 / −0.0012 / −0.0014
at embargo 0 / 5 / 10 / 21; deployment-era = +0.0094 / +0.0094 / +0.0093 / +0.0089. **Flat in the
embargo** → purging is not hiding or creating skill; the overlapping-label leakage control is not the
binding constraint here. [V]

**Reconstructed OOS portfolios** (combined, embargo 5, per path; cross-sectional LS20 rebuilt with the
real `src` pipeline and clearly labeled a *reconstruction*): the reconstructed OOS Sharpe is weakly
positive on a majority of paths but dispersed, consistent with the low IC. Portfolio-level OOS figures
inherit the §4 finalizer blocker and are **not** the shipped series. [V/I]

## Answers

### Q1 — Does the original P04 model retain predictive rank information under purged CPCV?
**Weakly, and regime-dependently — not robustly.** [V]
- Over the **full sample** the deployed **blend nets to ≈ 0** rank IC (−0.001, 54% of paths positive).
  Its two legs disagree: the **V1 (flipped) leg is negative OOS** (−0.012, only 21% of paths positive) —
  the sign-flip calibrated on pre-2016 data **does not generalize** — while the **V2 leg is weakly
  positive** (+0.014, 79%).
- Restricted to the **2016+ deployment window**, the blend is **weakly positive** (+0.009, 71% of paths),
  i.e. it did carry a little generalizable rank skill in the era it actually traded.
- Absolute IC is small throughout (≤ ~0.014 for the real model). A ~1.5 portfolio Sharpe from such a
  small IC is consistent with the project's own note that part of the return is **directional market
  beta**, plus the **overlapping-label** construction — not strong per-name rank skill.

### Q2 — How different are the results from the representative ridge used previously?
**Materially on the full sample; close in the deployment era.** [V]
- Full sample: ridge rank IC **+0.030 (100% of paths positive)** vs the actual blend **≈ 0**. The
  representative ridge **overstated generalizable skill by ~2–3×** and masked the V1-leg sign-flip
  fragility. The earlier campaign's "OOS IC ≈ 0.035" was a ridge/full-sample figure and should be read
  as **optimistic** relative to the production model.
- Deployment era: ridge **+0.0096** vs actual blend **+0.0094** — essentially the same. The divergence
  is entirely a **pre-2016 regime** effect (regularization + no fragile flip helped the ridge there).
- **Conclusion:** the representative ridge is an acceptable *directional* proxy **only within the 2016+
  deployment window**; it is **not** a safe proxy for full-history skill, and any pipeline-skill claim
  must use the actual OLS blend, as done here.

## Limitations
- CPCV ≠ chronological validation (Q-rule honored; not a live replica). [stated]
- Portfolio-level OOS inherits the finalizer blocker (`PROJECT04_MODEL_LINEAGE.md` §4). [U]
- The universe is 20 tickers; rank IC is estimated on a thin cross-section, so per-date IC is noisy
  (dispersion ≳ mean) — the **sign and ordering** of the models are the robust content, not 3rd decimals.
