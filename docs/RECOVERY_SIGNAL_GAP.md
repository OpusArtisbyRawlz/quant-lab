# Recovery signal-registration gap — analysis & plan

## Progress — Project 04 ported & executing (option A)

**P04 is done.** Its ML 5-day return forecast is ported into a **versioned historical
signal library** (`src/signals/historical/p04_return_forecast.py`, signal
`hist_p04_return_forecast_v1`) and registered through the existing signal registry
(`get_signal_series` + `KNOWN_SIGNALS`) — no substitute, no definition change. The
signal returns P04's authoritative historical forecast **`pred_flipped`** from
`data/processed/v1.csv` (the column P04's own portfolio notebook trades on), verbatim.

End-to-end validation (`p04_ls20`, isolated DB): generate → **hypothesis node + pending
idea** → **approve** → **execute** (cross-sectional LS20 over `project_04_universe`) →
**experiment** (linked to the node) → **evidence into M11** (hypothesis_state built) →
Project 07 hand-off boundary intact. Gross Sharpe ≈ **+0.36**, net ≈ **+0.32**
(direction correct after using `pred_flipped`).

**Fidelity boundary (important):** the *signal* is faithful, but the *metrics* are the
**factory's** cross-sectional engine (equal-weight LS20, its cost model, full-period
panel, its annualisation) — not P04's own signal-weighted/capped notebook backtest — so
they differ from P04's historical ~1.5 Sharpe. Recovery = replaying the faithful signal
through the factory; Project 07 is the authoritative evaluator of the factory result.
Note the factory executor applies LS **20%** (0.8/0.2) by default, so `p04_ls30` runs at
LS20 until a quantile parameter is plumbed (a follow-up) — its definition is unchanged,
only not yet fully parameterised.

Remaining (still blocked, ported next in order): **P03** (single-asset classifier —
needs the classifier execution path discussed), **P05** (smooth-drawdown overlay),
**P06** (deployment validation). See below.

---


Prepared for the historical-recovery executability decision. **No signals were
invented and no strategy definitions were changed** — this is a faithful gap analysis
of what each recovered strategy needs versus what the executor knows today.

## Part A — P03 end-to-end validation (isolated DB)

Ran the P03 recovered strategy through the new linkage + existing gate:

| Step | Result |
| --- | --- |
| generate tick | ✅ 1 hypothesis **node** created + 1 **pending** idea, idea↔node linked |
| approval (`quant idea approve`) | ✅ pending → approved (executable path created) |
| execute tick | ❌ dispatched → **failed**, reason `universe_data_missing;signal_unavailable` → idea `rejected` |
| experiment generated | ❌ none |
| experiment→node stamp | ❌ none |
| evidence into M11 | ❌ none (0 rows) |
| provenance / reporting | ✅ intact (idea metadata provenance present; report renders) |

**Conclusion:** the P6-65 hypothesis linkage and the human approval gate work exactly
as intended, **but P03 does not execute** — it is blocked at spec validation for the
same reason as P04/P05/P06 (unregistered signals), plus a universe/data-layout issue.
This corrects the earlier note that "P03 executes cleanly today" — it does not.

## Part B — the exact signal gap

The executor validates every spec's features against
`spec_validator.KNOWN_SIGNALS` (13 cross-sectional names, computed by
`src/features/price.py`):

```
low_vol_5 low_vol_20 mom_ret_5 mom_ret_10 mom_ret_20 mr_ret_5 mr_ret_10 mr_ret_20
mr_blend mom_blend mr_lowvol_blend trend_ma_10 trend_ma_20
```

The recovery manifest faithfully uses each project's **original** signal/model names.
None are registered, so **0 of 10 recovered strategies are executable today**
(`recovery.signal_gap.executable_readiness()`):

| Strategy | mapping | missing signals | nature of the gap |
| --- | --- | --- | --- |
| p03_spy_5d_direction | clean | return_5d/10d/20d, rv20, ma_distance_20, **rsi_14**, **volume_ratio** | single-asset (SPY) technical features; `return_*`≈`ret_*`, `rv20`≈`vol_20`, `ma_distance_20`≈`ma_20_ratio`, but **rsi_14 and volume_ratio are computed nowhere in `src/`**, and P03 is a single-asset logistic classifier, not the cross-sectional LS the engine runs |
| p04_ls20 / p04_ls30 / p04_blend_* | ml_model | **ml_return_forecast_5d** | an **ML model output**, not a raw signal — requires the P04 forecast model, not a registry entry |
| p05_risk_engine_smooth_dd | overlay | **smooth_drawdown_exposure** | a **risk overlay** on an equity curve — not a cross-sectional signal at all |
| p06_deployment_candidate_v1 | deployment | **deployment_candidate_v1** | a **deployment config/validation**, not a signal |
| p02_volatility_regime | ml_model | RV5_trail, RV20_trail, RV5_fwd_ann, VolRatio | the vendored vol-regime model (single-asset SPY); features exist only inside the vendored notebook |

## Part C — why this is not a trivial "register N signals" PR

A faithful registration is blocked by three distinct issues, none solvable by
appending to `KNOWN_SIGNALS` without crossing the "don't invent / don't change
definitions" line:

1. **Model/overlay/deployment "signals" (P04/P05/P06, P02).** `ml_return_forecast_5d`,
   `smooth_drawdown_exposure`, `deployment_candidate_v1`, and the P02 vol-regime
   probability are **not features** — they are model outputs / overlays / deployments.
   Making them executable means porting the original implementations (e.g. P04's ML
   forecast; the vendored P02 notebook), which is re-implementation, not registration.
2. **Missing feature computations (P03).** `rsi_14` and `volume_ratio` are not computed
   anywhere in `src/features/`; registering them means writing feature code
   (defensible — it implements the *original* features), but the rest of P03's
   definition is a single-asset logistic classifier.
3. **Engine/shape mismatch.** The executor is a **cross-sectional long/short** backtest
   over a multi-asset panel; P02/P03 are **single-asset (SPY)** models. Their universe
   (`SPY`) is not a panel directory (`data/raw/` has `SPY.csv`, `NIFTY50/`,
   `project_04_universe/`), so even with signals registered the shape differs.

## Recommended next step (needs your direction — one of)

- **(a) Port the original implementations** as first-class, registered signals/models
  — e.g. bring P04's forecast and P02's vol-regime (already vendored) into the engine,
  add `rsi_14`/`volume_ratio` features, and support single-asset universes. Faithful
  but substantial; several PRs.
- **(b) Register only the genuinely-registerable technical features** now (`rsi_14`,
  `volume_ratio`, and aliases `return_5d→ret_5`, `rv20→vol_20`, `ma_distance_20→
  ma_20_ratio`) so P03-style *feature-based* strategies can run cross-sectionally —
  but confirm first, because aliasing touches P03's signal names (borderline
  "definition change").
- **(c) Keep them non-executable** and treat recovery as provenance/replay-cataloguing
  only until the models are ported.

I did **not** implement any registration, to avoid inventing substitutes or changing
definitions. `recovery.signal_gap` makes the blocker explicit and testable; once a
path is chosen, the registration becomes mechanical and this report is the checklist.
