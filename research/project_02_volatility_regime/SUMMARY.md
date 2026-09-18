# Project 02 — Volatility Regime: Research Summary

Concise summary of the vendored Project 02 model. Metrics below are taken **only** from
the authoritative source (README + the vendored OOF artifact); nothing is inferred or
guessed. See [`README.md`](./README.md) for detail and [`provenance.json`](./provenance.json)
for hashes/provenance.

## What it did

A probabilistic model of the **future volatility regime** for SPY: predict the
probability that the market enters a **high-volatility** regime, defined via the ratio
of trailing realized volatilities `VolRatio = RV5_trail / RV20_trail` (target = 1 when
`VolRatio > threshold`). Two stages — regress the volatility ratio, then a logistic
classifier emits `P(high-vol regime)` — evaluated with **walk-forward, out-of-fold**
testing and **probability calibration**.

## Historical metrics (from the source README — not guessed)

| Metric | Value |
| --- | --- |
| Asset / frequency | SPY, daily |
| Full sample coverage | 2000–2026, ~6557 observations |
| Base rate of high-vol regime | ~0.163 |
| Mean predicted probability | 0.154 |
| Reported predictive power | **limited / weak edge** (probabilities modestly aligned with realized frequencies) |

The source's own conclusion: volatility clustering is real but regime *transitions*
are hard to predict; the model is a useful framework (feature engineering,
probabilistic forecasting, calibration, walk-forward eval) with a small edge.

## Vendored OOF artifact (measured from the file)

`artifacts/vol_regime_calibrated_oof.csv` — `Date, p_high_vol_calibrated`:

| Property | Value |
| --- | --- |
| Rows (excl. header) | 2898 |
| Date range | 2014-01-23 → 2025-07-31 |
| `p_high_vol_calibrated` min / mean / max | 0.0050 / 0.1756 / 0.8212 |

Note: the vendored OOF artifact spans 2014–2025 (2898 rows) — the out-of-fold segment
used downstream — whereas the source README describes the full 2000–2026 study
(~6557 obs). Both facts are recorded as-is; reconciling them is left to the
reproducibility work in `modernized/` (not done here).

## Downstream usage

The calibrated OOF probability is consumed **verbatim** as `p_high_vol_calibrated` by:
- **Project 04** (return-forecast alpha): `exposure = 1 - p_high_vol_calibrated`.
- **Project 05** (risk engine): drawdown/vol overlay input.

## Recovery status

- **status:** `recovered_source` (vendored historical snapshot; GitHub repo authoritative).
- **replayable:** *pending reproducibility verification.* Not modernized in this import.
