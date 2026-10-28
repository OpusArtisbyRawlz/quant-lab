# PROJECT 04 — MODEL LINEAGE & REPRODUCTION (Phase 1–2)

**Experiment:** `exp_007_full_pipeline_validation` · **Branch:** `remediation/p06-p07-return-lineage` (HEAD `9f0cef0`)
**Date:** 2026-10-28 · validation/research-readiness campaign — no parameters changed, no candidate promoted.

Every row is tagged **[V]** directly verified (re-executed or read from a preserved artifact),
**[I]** inferred from preserved code/metadata, or **[U]** unavailable / not reconstructable.

---

## 1. The actual forecasting algorithm

The production P04 alpha ("V1" in the P06/P07 tournament, WRC winner `P04:ls_20pct`) is **not a single
model**. It is a **blend of two ordinary-least-squares linear regressions** (`sklearn.linear_model.LinearRegression`,
no regularization), each mapping cross-sectional features to the 5-day forward return, combined by
per-date z-score. Source of truth: `research/project_04_return_forecast_alpha/notebooks/03_model_training.ipynb`,
`03_model_training_v2.ipynb`, `04_portfolio_research.ipynb`.

| element | specification | tag |
|---|---|---|
| Asset universe | 20 US equity tickers, `data/raw/project_04_universe` (yfinance), daily bars | **[V]** |
| Sample span | 1985-03-13 → 2026-03-06 (features_v1 175,521 rows; features_v2 174,101) | **[V]** |
| Label | `fwd_ret_5 = Close.shift(-5)/Close − 1` — **5-trading-day forward return (overlapping)** | **[V]** |
| Feature set V1 | `ret_1, ret_5, ret_10, ret_20, vol_5, vol_20, ma_10_ratio, ma_20_ratio, ma_50_ratio, dollar_vol, vol_z_20` (11) | **[V]** |
| Feature set V2 | V1 **+ `ret_60, ret_120`** (13) | **[V]** |
| Feature transforms | none at fit time (raw features); signal-level per-date z-score after prediction | **[V]** |
| Model class | OLS `LinearRegression(fit_intercept=True)` — two independent fits (V1, V2) | **[V]** |
| Hyperparameters | none (no penalty, no CV tuning) | **[V]** |
| Train / test split | **single static split**: train `Date < 2016-01-01`, test `Date ≥ 2016-01-01`. Fit once; **not** walk-forward | **[V]** |
| Prediction (V1) | predict test, then **sign-flip** (`pred_flipped = −pred`): raw OLS IC was negative → the signal is effectively **mean-reverting** | **[V]** |
| Prediction (V2) | predict test, used as-is (raw IC positive) | **[V]** |
| Cross-sectional combine | per-date `z(signal_v1=pred_flipped) + z(signal_v2=pred) = combined_signal` | **[V]** |
| Portfolio construction | `build_daily_weights_from_panel(method="equal", long_q=short_q=0.2)` → equal-weight long top 20% / short bottom 20%, gross = 1.0 | **[V]** |
| Rebalancing / return convention | daily weights × same-row `fwd_ret_5`, summed cross-sectionally; equity = `cumprod(1+Σwᵢrᵢ)` — **overlapping 5-day labels telescoped as a daily series** | **[V]** |
| Transaction costs | **none inside P04** — costs/slippage are added only at P06 (≈2.16%/yr net drag, confirmed by the historical replay in §4) | **[V]** |

## 2. Three model objects — kept explicitly distinct

1. **Original deployed-research model [V]** — the OLS V1/V2 blend above. Its saved predictions live in
   `data/processed/v1.csv` (cols incl. `pred, pred_flipped, signal_z`) and `v2.csv` (`pred, signal_z`).
2. **Representative research approximation [V]** — the `Ridge(alpha=10)` on the V2 feature set used in
   `exp_007_advanced_validation`. A *proxy*, chosen for the earlier model-level CV; **not** the production model.
   It differs from the real model in three ways: (a) L2 penalty vs none, (b) single V2 feature set vs a V1+V2
   blend, (c) no sign-flip handling of the V1 leg.
3. **Newly trained models [V]** — the per-split OLS refits produced inside this campaign's CPCV (Phase 3).
   These are fresh fits for leakage-controlled evaluation and are never represented as the historical model.

## 3. Exact reproduction of the model (`scripts/p2_exact_reproduction.py`)

Re-fitting both OLS models from the preserved feature CSVs with the notebook-exact feature lists and the
`2016-01-01` split, then comparing to the **saved** predictions:

| model | test rows matched | max abs prediction diff vs saved | verdict |
|---|---|---|---|
| V1 OLS (`pred`, `pred_flipped`) | 51,160 / 51,160 | **7.44 × 10⁻⁹** | **exact (float tolerance)** **[V]** |
| V2 OLS (`pred`) | 51,160 / 51,160 | **2.13 × 10⁻⁶** | **exact (float tolerance)** **[V]** |

**The forecasting model reproduces to numerical precision.** OLS is deterministic (no seed needed).

## 4. The portfolio finalizer does NOT bit-reproduce — identified blocker

The operative downstream base is the saved `exp_004_project04_final/strategy_timeseries/ls_20pct.csv`
(Sharpe 1.516, MDD −0.655), which Project 05 ingests directly (`project_05_risk_engine/notebooks/01_drawdown_overlay.ipynb`
reads these CSVs as its base returns). Attempting to regenerate that series from the preserved predictions
and the preserved `src` pipeline (`scripts/p2_find_ls20_construction.py`):

| candidate construction on `combined_signal` | Sharpe | MDD | corr vs saved | max abs return diff |
|---|---|---|---|---|
| **saved `ls_20pct` (target)** | **1.516** | **−0.655** | — | — |
| z-sum / equal-weight LS20 | 1.115 | −0.712 | 0.965 | 0.030 |
| z-sum / signal-weight LS20 | 1.234 | −0.794 | 0.899 | 0.073 |
| rank≥.8/≤.2 ±1 / (equal≡signal) | 0.992 | −0.672 | 0.982 | 0.021 |
| V1-only / equal-weight | 0.529 | −0.815 | 0.099 | 0.169 |
| V2-only / equal-weight | −0.095 | −0.906 | 0.058 | 0.151 |

No preserved construction bit-reproduces the saved series. Every candidate is the **same long/short family**
(corr 0.965–0.982 for combined variants) but the saved series has a **materially higher Sharpe (1.516) than
any reconstruction (≤1.234)**. **Blocker [U]:** `exp_004/config.yaml`, `metrics.json`, `results_summary.md` and
`predictions.csv` are **empty (0 bytes)**; notebook 04 is an exploratory notebook with many non-final variants,
and the exact finalizer that wrote the saved timeseries is not preserved as a runnable artifact.

**Classification of the saved portfolio series: *inferred / approximately reproduced* (corr ≈ 0.97), not a
certified bit-level reconstruction.** We do **not** substitute a reconstruction and claim full fidelity. This is a
genuine reproducibility gap at the *portfolio-finalization* layer, distinct from the model layer (which is exact).

> **No contradiction with the prior 1e-12 result.** The remediation campaign's canonical match to 1e-12 was the
> *internal arithmetic consistency* of the P05 overlay (`port_pre` rebuilt from the stored exposure), which takes
> `ls_20pct.csv` as **given input**. It never re-derived `ls_20pct.csv` from the OLS model. That gap is this §4.

**Independent cross-check [V]:** the auto-generated replay `exp_007_idea_generator_quantile_ranking`
(`features=["hist_p04_ls20_v1"]`, `notes: historical_recovery`) reports gross Sharpe **1.515955**, MDD −0.65529,
net Sharpe 1.431, cost-drag 2.16%/yr — an exact match to the saved `ls_20pct` base, confirming the operative
series even though its generator code is not preserved.

## 5. Answers to the lineage questions (Final research Q1–Q2 — model layer)

- **Q1 (does the original model retain rank skill under purged CPCV?)** and **Q2 (how different from the ridge?)**
  are answered quantitatively in `FULL_MODEL_CPCV_REPORT.md` using the exactly-reproduced OLS blend from §3.
- **Reproducibility scope:** model predictions — **exact**; portfolio finalization — **approximate (corr ≈0.97),
  blocker documented**. Any portfolio-level OOS figure in this campaign is therefore a *reconstruction*, explicitly
  labeled, never represented as the shipped series.
