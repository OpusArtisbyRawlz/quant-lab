# Project 05 — risk-overlay recovery result (replayed through the real factory)

**Status: smooth-DD overlay RECOVERED ✅ — faithful replay through the unmodified
cross-sectional runner, fidelity verified.**

Project 05's smooth-drawdown exposure overlay was replayed end-to-end through the
*actual* historical-recovery campaign (manifest → idea → hypothesis → human approval →
experiment → evidence → M11 → Project 07 boundary), reproducing the historical notebook
metrics exactly. The overlay is applied by the existing executor via the authoritative
`src/risk` code — no new engine, no parallel path, no approximation.

## Original vs replay

| Strategy | Notebook (authoritative) | Factory replay (exp) | Fidelity |
| --- | --- | --- | --- |
| LS20 + smooth-DD | Sharpe **1.860**, MDD **-0.502**, CAGR **0.424**, Calmar **0.845** | Sharpe **1.8603**, MDD **-0.5015**, CAGR **0.4239**, Calmar **0.8452** (`exp_009`) | **exact** |
| LS30 + smooth-DD | Sharpe **1.663**, MDD **-0.420**, CAGR **0.299**, Calmar **0.711** | Sharpe **1.6630**, MDD **-0.4201**, CAGR **0.2994**, Calmar **0.7126** (`exp_010`) | **exact** |

Source of truth: `experiments/completed/exp_005_risk_engine_final/all_strategies_smooth_dd_results.csv`
(smooth-DD columns) and `research/project_05_risk_engine/notebooks/01_drawdown_overlay.ipynb`.

## The authoritative overlay (ported verbatim, not re-derived)

`src/risk/drawdown.py` + `src/risk/allocation.py` (`compare_base_vs_dd_overlay`):

```
strategy_ret = Σ(weight · fwd_ret_5) per date            # == the factory's _portfolio_returns
equity       = (1 + strategy_ret).cumprod()
drawdown     = equity / equity.cummax() - 1
exposure     = floor + (1 - floor) · exp(-k · |drawdown|)  # floor=0.55, k=5
strategy_ret_dd = strategy_ret · exposure.shift(1).fillna(1.0)   # lag-1, no look-ahead
```

The overlay reads the book's *own* realised drawdown, so it is path-dependent and cannot
be expressed as a cross-sectional signal. It post-processes exactly the series the factory
already produces.

## The minimal fix (precise mismatch → precise fix)

The executor built `portfolio_returns` and went straight to metrics — there was no stage
to apply an equity-curve overlay. The minimal, faithful wiring (default-off; every existing
spec unchanged):

1. `ExperimentSpec.overlay: dict | None = None` — a typed, serialised field (never hidden
   in `notes`), e.g. `{"method": "smooth_dd", "floor": 0.55, "k": 5}`.
2. `runner._apply_overlay` — dispatches to the authoritative `src/risk` code; applied to
   `portfolio_returns` after the cross-sectional book is built.
3. `spec_builder.idea_to_spec` threads the overlay from the recovered idea's metadata
   (write-once, beside provenance), so a recovered overlay strategy carries its exact
   `{method, floor, k}` to the executor.
4. The recovery source copies the manifest `overlay` block into the idea metadata.

No new signal was registered — the overlay is not a signal; the base books
(`hist_p04_ls20_v1` / `hist_p04_ls30_v1`) were already registered by the P04 recovery.

## Campaign identifiers

| Item | Value |
| --- | --- |
| Campaign | `p05-risk-overlay-recovery` (type `historical_recovery`, state **COMPLETED**) |
| Scope | `{"strategy_ids": ["p05_smooth_dd_ls20", "p05_smooth_dd_ls30"]}` |
| Ideas (approved) | `idea_006_smooth_drawdown_exposure_overlay`, `idea_007_smooth_drawdown_exposure_overlay` |
| Hypothesis nodes | `rec_p05-risk-overlay-recovery_p05_smooth_dd_ls20_time`, `…_ls30_time` |
| Experiments | `exp_009…` (LS20+smooth-DD), `exp_010…` (LS30+smooth-DD) |
| Evidence events (M11) | 2 (this campaign) |
| Project 07 handoff | in `pending_handoffs`; `evaluation_status = preliminary` |
| Provenance | `origin_notebook = 01_drawdown_overlay.ipynb`, `origin_artifact = exp_005_risk_engine_final` |

## Recovery markers

| Strategy | FOUND | EXECUTABLE | REPLAYED | FIDELITY VERIFIED | M11 | PROJECT07 |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| p05_smooth_dd_ls20 | ✅ | ✅ | ✅ | ✅ | ✅ | preliminary |
| p05_smooth_dd_ls30 | ✅ | ✅ | ✅ | ✅ | ✅ | preliminary |

## Scope of this recovery

This PR recovers the P05 smooth-DD overlay **mechanism** and applies it to the two P04
base books that are already ported (LS20, LS30). The remaining P05 catalogue entries are
**not blocked on the overlay mechanism** — they are blocked only on porting their P04
*base* books first:

- The other 10 per-strategy smooth-DD / step-DD rows need their P04 base variants
  (`ls20+sqrt_partial_normalized`, `blend_60_40`, …) ported as signals — that is P04-variant
  recovery, not P05.
- The final `weighted_multi_strategy_with_strategy_and_portfolio_smooth_dd` model
  (Sharpe 2.09) is a *portfolio composition* of three books with two overlay layers; it
  needs multi-strategy portfolio support, a separate step.

The overlay path proven here is what makes all of those mechanical once their bases exist.
