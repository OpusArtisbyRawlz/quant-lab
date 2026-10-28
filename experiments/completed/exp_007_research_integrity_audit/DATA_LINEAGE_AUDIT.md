# DATA LINEAGE AUDIT — V1 / DD Only / Combined DD+Vol

**Audit:** `exp_007_research_integrity_audit` · traced from actual code + saved artifacts (not descriptions).

---

## 1. Dependency graph (source → output)

```
data/raw/project_04_universe/*            (prices, volume — 20-name megacap universe)
        │
  Project 04  →  exp_004_project04_final/
        │           strategy_timeseries/*.csv   (portfolio_return per strategy)   [SOURCE OF TRUTH]
        │           final_daily_weights via P05
        ▼
  Project 05  (01_drawdown_overlay.ipynb)
        │   per-strategy smooth-DD overlay (floor0.55,k5, lag1)  →  controlled_returns
        │   weighted blend {0.5,0.3,0.2}                          →  port_pre  ( = "multi_ret")
        │   portfolio-level smooth-DD overlay (floor0.55,k5, lag1) → V1 gross
        ▼
  exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv
        │   portfolio_return[t]      = port_pre[t]·portfolio_exp[t-1]      (V1 gross, shipped)
        │   portfolio_dd_exposure[t] = portfolio_exp[t-1]                   (ALREADY lagged)
        │   final_daily_weights.csv  = as-traded book (exposure-scaled)
        ▼
  Project 06  ── load base ──►  base_ret = pr / exp.shift(1)   ✗ DEFECT (double lag)
        │                       base_book = wide / exp          ✓ correct (same-row)
        │   tournament: V1 = pr.copy() ✓   |   DD Only/Combined/GroupB = overlay(base_ret) ✗
        │   overlay-challenge: overlay_equity_curves.csv (same defect) → WRC/DSR universe
        ▼
  exp_007_candidate_net_validation/{v1,dd_only,combined_dd_vol}_daily_returns.csv
        │   gross/turnover/exposure copied from tournament candidates; net = gross − turnover·10bps
        ▼
  Project 07 notebooks  (NB01 bootstrap, NB02 permutation, NB03 MC, NB04 MT, NB05 DSR,
                         NB06 WRC, NB07 report, NB08 ledger, NB09 net validation)
```

## 2. Source-to-output table (the 11 requested elements)

| # | Element | Source of truth | Construction | Lineage status |
|---|---|---|---|---|
| 1 | Underlying asset returns | `data/raw/project_04_universe/*` | prices → P04 forecasts | VALID |
| 2 | Prediction timestamps & weights | `exp_005.../final_daily_weights.csv` | P04/P05 pivot (Date×Ticker) | VALID |
| 3 | 3 constituent strategy returns | `exp_004.../strategy_timeseries/{ls_20pct_plus_sqrt_partial_normalized, blend_60_40_ls20_plus_ls30, ls_30pct}.csv` | `portfolio_return` column | VALID |
| 4 | V1 weighted portfolio | reconstructed `port_pre` | weights {0.5,0.3,0.2} of strategy-controlled returns | VALID (recon 1e-16) |
| 5 | V1 strategy-level overlays | P05 cell 62 | `smooth_dd(floor0.55,k5)` per strategy, lag1 | VALID |
| 6 | V1 portfolio-level overlay | P05 cell 82 | `smooth_dd(floor0.55,k5)` on port_pre, lag1 | VALID |
| 7 | DD Only extra rule | P06 | portfolio overlay `smooth_dd(floor0.3,k5)` on **base_ret** | base_ret DEFECTIVE |
| 8 | Combined DD+Vol extra rule | P06 | `(vol_mult·smooth_dd(0.3,5)).clip(0.5,1.3)` on **base_ret** | base_ret DEFECTIVE |
| 9 | Capital / gross / net exposure | `final_daily_weights.csv`; `base_book = wide/exp` | abs/sum of weights | book recovery CORRECT |
| 10 | Turnover & trading cost | `compute_turnover(book)`; 10 bps one-way | from actual position book | VALID basis (see cost audit) |
| 11 | Final gross/net series (P07) | `exp_007.../*_daily_returns.csv` | copied from P06 candidates | V1 VALID; DD/Combined CORRECTED |

## 3. `.shift()` / lag / normalization inventory

- **Exposure application:** `apply_exposure_to_return` lags exposure 1 day (`r_t·e_{t-1}`) — look-ahead-safe; used
  consistently at strategy-, portfolio- and challenger-level.
- **Stored exposure:** `portfolio_dd_exposure` is persisted *already shifted* (P05 cell 82). This is the single
  fact the P06 recovery got wrong.
- **Book scaling:** `final_daily_weights` is the as-traded (exposure-scaled) book — gross notional ∈ [0.19, 1.0],
  corr(gross-notional, stored-exposure)=0.98. Book recovery `wide/exp` is the correct same-row inverse.
- **Drawdown:** `equity/cummax − 1` (causal). No look-ahead.
- **Normalization:** blend weights sum to 1.0; no per-day renormalization that would interact with the defect.

## 4. Reconciliation of saved vs reconstructed

| series | saved | reconstructed-from-exp_004 | max |abs| diff |
|---|---|---|---:|
| V1 gross | `exp_005 portfolio_return` | `apply_exposure(port_pre, smooth_dd(0.55,5))` | 9.98e-17 |
| `port_pre` | — (not saved) | weighted strategy-controlled returns | identity `pr=port_pre·e_stored` 9.98e-17 |
| DD Only gross (shipped) | `exp_007 dd_only.gross_return` | defect path `overlay(base_defect)` | 5.52e-16 |
| Combined gross (shipped) | `exp_007 combined.gross_return` | defect path `overlay(base_defect)` | 5.89e-16 |

Saved holdings (`final_daily_weights`) and the book recovery reconcile; the only irreconcilable step is the
**return** recovery, isolated in §Root-Cause.

## 5. Canonical source of truth (this audit)

Reconstruct every candidate from `exp_004` raw strategies forward, applying each overlay layer to the **true**
`port_pre` (never dividing an already-adjusted return by a shifted exposure). Hashes of all source inputs are
in `evidence_record.json`.
