# Project 02 — Volatility Regime

**Vendored historical snapshot** of the Project 02 volatility-regime model, imported
into quant-lab so the Research Factory can replay all historical research from one
repository.

> **Canonical source (authoritative):** the external GitHub repository
> [`OpusArtisbyRawlz/spy-risk-volatility-model`](https://github.com/OpusArtisbyRawlz/spy-risk-volatility-model)
> remains the authoritative historical source and is **unchanged**. The copy here is a
> **vendored historical snapshot** for local replay/recovery — see `provenance.json`.

## Objective

Determine whether **future volatility regimes are predictable from observable market
features** — specifically, whether the relationship between short-term and
medium-term realized volatility carries information about future volatility
conditions. The model is **probabilistic** (probability of a high-volatility regime),
not a point forecast of volatility.

## Target definition

Based on the ratio of trailing realized volatilities:

```
VolRatio_t = RV5_trail / RV20_trail
target     = 1 if VolRatio > threshold   (high-volatility regime)
           = 0 otherwise
```

## Key features

- **RV5_trail** — trailing 5-day realized volatility.
- **RV20_trail** — trailing 20-day realized volatility.
- **RV5_fwd_ann** — forward 5-day realized volatility (annualized), used in the
  volatility-ratio construction / evaluation.
- **VolRatio** — `RV5_trail / RV20_trail`, the short-vs-medium volatility ratio that
  defines the regime target.

All features are built from **past information only** (no look-ahead).

## Model & calibration approach

Two-stage framework (per the source notebook + README):

1. **Regression** of the volatility ratio (continuous short-vs-medium vol relationship).
2. **Classification** — a logistic classifier maps the predicted ratio to
   `P(high-volatility regime)`.

Predicted probabilities are **calibrated** and evaluated by probability binning
(predicted vs realized high-vol frequency).

## Walk-forward / OOF validation

Evaluation uses **walk-forward out-of-sample** testing: for each window, train on
history → predict on unseen future data → store out-of-fold probabilities. This
simulates real-time forecasting and prevents look-ahead bias. The stored calibrated
OOF probabilities are the project's output artifact.

## Output artifact & downstream mapping

The notebook produces a calibrated out-of-fold high-volatility-regime probability.
The historical artifact is vendored at:

```
artifacts/vol_regime_calibrated_oof.csv    # columns: Date, p_high_vol_calibrated  (2898 rows)
```

Downstream projects consume this column **verbatim** as `p_high_vol_calibrated`:

| Consumer | Usage |
| --- | --- |
| **Project 04 — Return Forecast Alpha** | `df_vol = read_csv(vol_regime_calibrated_oof.csv)`; `exposure = 1 - p_high_vol_calibrated` (volatility-scaled exposure). |
| **Project 05 — Risk Engine** | `df_regime = read_csv(vol_regime_calibrated_oof.csv)`; uses `p_high_vol_calibrated` in the drawdown/vol overlay. |

So the mapping is `notebook calibrated OOF probability → column p_high_vol_calibrated →
consumed under the same name by P04/P05`.

## Provenance

- **Authoritative repo:** `OpusArtisbyRawlz/spy-risk-volatility-model` @ commit
  `2779bb3e92f7aafb11d806000b4906bbbaa99a4e` (branch `main`).
- **Imported notebook:** `notebooks/spy_volatility_regime_model.ipynb` — **byte-for-byte
  identical** to the source (git blob sha `43d55f84…`; sha256 `41762db3…`), verified at
  import. **Not modified** after import.
- **Imported artifact:** `artifacts/vol_regime_calibrated_oof.csv` (sha256 `110812dd…`),
  the historical output already present in quant-lab (the source repo ships no CSV),
  copied unaltered.
- Full details and hashes: [`provenance.json`](./provenance.json).

## Current recovery status

- **status:** `recovered_source` — the original implementation is present (vendored).
- **replayable:** *pending reproducibility verification.* The imported notebook is the
  historical record and is **not** modernized or refactored here. A later,
  reproducible/automated implementation that reproduces this notebook exactly (before
  any methodological change) will live in [`modernized/`](./modernized/), which is
  intentionally empty for now.

## Directory layout

```
research/project_02_volatility_regime/
  README.md                                  # this file
  SUMMARY.md                                 # concise research summary + recovered metrics
  provenance.json                            # source repo/commit + import hashes + mapping
  notebooks/spy_volatility_regime_model.ipynb  # vendored, byte-for-byte from source
  artifacts/vol_regime_calibrated_oof.csv    # historical calibrated OOF output (unaltered)
  modernized/                                # reserved — later reproducible implementation
```

## Do-not (historical faithfulness)

- Do **not** rewrite/refactor/modernize the vendored notebook — it is the historical
  record (modernization goes in `modernized/` in a later PR).
- Do **not** regenerate or alter the vendored artifact.
- The external GitHub repo remains authoritative and must not be modified or deleted.
