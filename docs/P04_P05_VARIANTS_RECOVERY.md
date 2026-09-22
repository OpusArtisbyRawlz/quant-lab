# P04 variants + P05 overlays — recovery result

All remaining return-based historical strategies recovered through the real factory,
reusing the general `PortfolioSpec` composite + the (generalised) vol-regime **weight**
overlay + the smooth-DD / **vol-target** return overlays. No new architecture, no
duplicate execution path, no methodology change, no approximation.

## P04 variants (16) — FIDELITY VERIFIED

Each is a composite `PortfolioSpec`: a 1-child weight-transform (LS book × a P02
vol-regime exposure `f(1-p_high_vol)`, lag-1), a 2-child return blend, or a blend +
vol-target overlay. Verified vs `exp_004_project04_final/strategy_comparison.csv`.

| Variant | Recipe | Sharpe (f=hist) | MDD |
| --- | --- | --- | --- |
| p04_ls20_linear | ls20 × (1-p) | 1.425 = 1.425 | -0.611 |
| p04_ls20_sqrt | ls20 × √(1-p) | 1.482 = 1.482 | -0.633 |
| p04_ls20_pow07 | ls20 × (1-p)^0.7 | 1.458 = 1.458 | -0.624 |
| p04_ls20_sqrt_partial | ls20 × (0.5+0.5√(1-p)) | 1.520 = 1.520 | -0.644 |
| p04_ls20_sqrt_partial_norm | + renormalize | 1.544 = 1.544 | -0.655 |
| p04_ls30_sqrt_partial_norm | ls30 variant | 1.451 = 1.451 | -0.549 |
| p04_ls20_sqrt_partial_norm_neut | + dollar-neutralize | 1.098 = 1.098 | -0.645 |
| p04_ls30_sqrt_partial_norm_neut | ls30 + neutralize | 1.060 = 1.060 | -0.558 |
| p04_blend_70_30 | 0.7·LS20 + 0.3·LS30 | 1.515 = 1.515 | -0.625 |
| p04_blend_60_40 | 0.6/0.4 | 1.510 = 1.510 | -0.614 |
| p04_blend_50_50 | 0.5/0.5 | 1.503 = 1.503 | -0.604 |
| p04_blend_40_60 | 0.4/0.6 | 1.493 = 1.493 | -0.593 |
| p04_blend_60_40_vt_015 | blend + vol-target 0.15 | 1.270 = 1.270 | -0.507 |
| p04_blend_60_40_vt_018 | vol-target 0.18 | 1.264 = 1.264 | -0.574 |
| p04_blend_60_40_vt_020 | vol-target 0.20 | 1.256 = 1.256 | -0.614 |
| p04_blend_60_40_vt_025 | vol-target 0.25 | 1.244 = 1.244 | -0.690 |

Weight-transform and blend variants match to **1e-16** on the return series (the 12 with a
stored `strategy_timeseries`); neutralize/vol-target variants (no stored series) match the
`strategy_comparison.csv` Sharpe/MDD exactly.

## P05 overlays (10) — FIDELITY VERIFIED

Smooth-DD overlay (floor 0.55, k 5) on each recovered P04 base variant. Verified vs
`exp_005_risk_engine_final/all_strategies_smooth_dd_results.csv` (Sharpe_smooth_dd / MDD_smooth_dd).

| Overlay | Sharpe | MDD |
| --- | --- | --- |
| p05_smooth_dd_blend_40_60 | 1.787 | -0.452 |
| p05_smooth_dd_blend_50_50 | 1.808 | -0.461 |
| p05_smooth_dd_blend_60_40 | 1.824 | -0.469 |
| p05_smooth_dd_blend_70_30 | 1.838 | -0.477 |
| p05_smooth_dd_ls20_linear | 1.729 | -0.467 |
| p05_smooth_dd_ls20_pow07 | 1.773 | -0.477 |
| p05_smooth_dd_ls20_sqrt | 1.805 | -0.484 |
| p05_smooth_dd_ls20_sqrt_partial | 1.852 | -0.493 |
| p05_smooth_dd_ls20_sqrt_partial_norm | 1.881 | -0.502 |
| p05_smooth_dd_ls30_sqrt_partial_norm | 1.691 | -0.420 |

(These join the previously-recovered `p05_smooth_dd_ls20` 1.860 / `p05_smooth_dd_ls30`
1.663, completing all 12 per-strategy smooth-DD overlays.)

## Capabilities used (all pre-existing / extended, none new)
- `PortfolioSpec` composite (nested, deterministic).
- `src/risk/weight_overlay.py` — generalised to the vol-regime family (linear/sqrt/pow,
  partial, normalize, neutralize) reusing the recovered P02 OOF.
- `src/risk/drawdown` smooth-DD (P05) + a `vol_target` return overlay (P04 notebook
  cells 195/198) added to the executor's overlay dispatch.

## Recovery markers
Every P04 variant and P05 overlay above: FOUND ✅ · EXECUTABLE ✅ · REPLAYED ✅ ·
FIDELITY VERIFIED ✅ · PROJECT07 preliminary. Provenance: origin notebooks
`04_portfolio_research.ipynb` / `01_drawdown_overlay.ipynb`, children tracing to the
recovered P04 books + P02 OOF.
