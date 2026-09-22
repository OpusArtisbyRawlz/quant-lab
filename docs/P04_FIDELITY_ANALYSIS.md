# P04 fidelity analysis — why recovered Sharpe ≈ 0.36 vs original ≈ 1.5

> ## ⚠️ CORRECTION (2026-09-20) — this analysis's central conclusion was WRONG
>
> This document originally concluded that the authoritative LS20 construction (Sharpe
> **1.516**) was **"under-specified in the repo"** and that no faithful reconstruction
> from committed inputs correlated above **~0.10**. **That conclusion was incorrect.**
> The authoritative generator was in the repository the whole time, at
> `research/project_04_return_forecast_alpha/notebooks/04_portfolio_research.ipynb`
> (cells 4, 7, 9, 117-130).
>
> **Why the mistake happened.** The reconstructions here used the **v1 forecast alone**
> (`pred_flipped`), ranked and equal-weighted. The authoritative strategy does **not**
> trade `pred_flipped` alone — it trades a **combined signal**:
> `combined_signal = z(v1.pred_flipped) + z(v2.pred)` over the **v1 ∩ v2** panel, where
> `z` is the per-date z-score `(x - mean)/std`. Ranking that combined signal (top/bottom
> 20 % for LS20, 30 % for LS30) and equal-weighting reproduces the published numbers.
> The ~0.10 correlations reported below reflect the wrong (single-forecast) basket, not
> a genuine evidence gap. Only the first ~30 of the notebook's 138 cells were read
> during the original pass, so the `signal_v2` merge and the z-score/combine/rank cells
> (7/9/117-130) were missed. See `docs/P04_RECOVERY_FORENSICS.md` for the same
> correction on the forensic side.
>
> **Corrected, verified result (through the *unmodified* factory runner).** With the
> ported books `hist_p04_ls20_v1` / `hist_p04_ls30_v1` (which encode the combined-signal
> ±1 LS membership) run over the date-scoped recovery universe
> (`data/raw/project_04_universe_recovery`, 2016-01-04…2026-03-06, 2558 dates):
>
> | Strategy | Notebook (published) | Factory replay | Δ |
> | --- | --- | --- | --- |
> | LS20 | Sharpe **1.5160**, MDD **-0.6553** | Sharpe **1.5160**, MDD **-0.6553** | **0.000 / 0.000** |
> | LS30 | Sharpe **1.4176**, MDD **-0.5490** | Sharpe **1.4176**, MDD **-0.5490** | **0.000 / 0.000** |
>
> So of the two "causes" below, **cause #1 (un-reproduced construction) was a mistake of
> ours, now closed** — the construction *is* fully specified and reproduces exactly.
> **Cause #2 (date-window zero-padding) was real** and is resolved by scoping the
> recovery universe to the strategy's own 2016-2026 window (recommendation **A**, now
> implemented in `agents/recovery/build_p04_recovery_universe.py`). `max_weight=0.05` is
> confirmed a no-op for the balanced 20-name book. No engine change was needed.
>
> Everything below this banner is the **original (superseded) analysis**, preserved
> verbatim so the correction is auditable.

---

**Investigation only. No engine changes, no fixes, no methodology changes.** All
numbers are reproducible via
`research/project_04_return_forecast_alpha/fidelity_evidence.py`.

## TL;DR

The gap has **two independent causes**, both quantified:

1. **Date-window zero-padding (factory artifact, ~0.43× Sharpe).** The factory runs
   the strategy over the **full raw panel (1970–2026, 14,145 dates)**, but P04's
   forecast only covers **2016–2026 (2,558 dates)**. The ~82% of pre-forecast dates
   carry an **empty book (zero return)**, deflating Sharpe by ≈ √(active fraction) =
   √0.181 ≈ 0.43. Restricting to the active window lifts factory Sharpe **0.360 →
   0.847**.
2. **Un-reproduced authoritative construction (largest absolute gap).** The
   authoritative `LS 20%` series (`ls_20pct.csv`, **Sharpe 1.516**) does **not**
   correspond to any long/short book reconstructable from the committed inputs
   (`v1.csv` columns + `src/` functions): **every** faithful reconstruction correlates
   only **~0.10** with it and tops out at **0.53–0.85** Sharpe. Its return *convention*
   matches (overlapping 5-day, confirmed by autocorrelation), but its **basket**
   (higher mean, lower vol) does not — the exact construction that produced 1.516 is
   **under-specified in the repo**.

Neither cause is a substitute/approximation we introduced; #1 is a scope artifact and
#2 is missing original evidence.

## Sharpe ladder (measured)

| Variant | Window | Sharpe | Notes |
| --- | --- | --- | --- |
| **Authoritative `ls_20pct.csv`** | 2016–2026 | **1.516** | the target; committed artifact |
| Original `src` equal-weight LS20 on `pred_flipped` | 2016–2026 | 0.529 | committed functions, corr 0.10 to authoritative |
| Factory replication, **active only** | 2016–2026 | 0.847 | rank-based LS20, overlapping `fwd_ret_5` |
| **Factory as executed (recovered)** | 1970–2026 | **0.360** | full raw panel; 81.9% empty-book dates |

## Stage-by-stage comparison

| Stage | Original P04 | Factory (recovered) | Identical? | Difference / impact / est. Sharpe contribution |
| --- | --- | --- | --- | --- |
| Universe construction | 20-name book (v1.csv) | `data/raw/project_04_universe` (same 20 tickers) | **Yes** | — |
| Ticker coverage | 20 tickers | 20 tickers, 100% overlap | **Yes** | `_ticker_from_path` → AAPL… matches v1 exactly |
| Date coverage | 2016-01-04…2026-03-06 (2,558) | 1970-01-30…2026-03-06 (14,145) | **No** | **factory adds ~11,587 pre-forecast dates with empty book** → **dominant artifact**; 0.847→0.360 (Δ≈0.49) |
| Prediction alignment | `pred_flipped` per (Date,Ticker) | `hist_p04_return_forecast_v1` = `pred_flipped`, verbatim | **Yes** | forecast values bit-identical |
| Return data (`fwd_ret_5`) | v1.csv `fwd_ret_5` | recomputed `shift(-5)/close-1` | **Yes** | corr = 1.0000, max abs diff = 0.0 on 51,160 shared rows |
| Signal alignment | (see construction) | ranks `pred_flipped` per date | **Partial** | corr of resulting LS book vs authoritative ≈ **0.10** — baskets differ (see construction) |
| Quantile selection | `equal_weight_long_short`, `quantile(0.8)`/`quantile(0.2)` (≈4 long/4 short) | `signal_rank >= 0.8` / `<= 0.2` (≈5 long/4 short) | **No** | boundary-inclusive rank picks ~1 extra long; secondary (contributes to the 0.53↔0.85 spread) |
| Portfolio construction / weights | `0.5/n_long`, `-0.5/n_short` (gross 1.0) | `±1` normalized by `Σ|w|` (gross 1.0; per-side ≠ 0.5 when unbalanced) | **No** | small when balanced; part of 0.53↔0.85 spread |
| Holding period / return convention | overlapping 5-day forward | overlapping 5-day forward | **Yes** | authoritative lag-1 autocorr 0.69, lag-5 ≈ 0 — same overlapping convention |
| Rebalance schedule | daily (implied by overlapping) | daily | **Yes** | — |
| Transaction costs | gross (authoritative `ls_20pct` is gross) | net applied (turnover×cost) | **No** | small: factory gross 0.360 → net 0.320 |
| Execution timing | signal(t) → `fwd_ret_5(t)` | same | **Yes** | — |
| Return calculation | `Σ weight·fwd_ret_5` per date | `Σ weight·fwd_ret_5` per date | **Yes** | identical formula |
| Normalization | gross = 1.0 | gross = 1.0 | **Yes** | — |
| Benchmark assumptions | none (absolute LS) | none | **Yes** | — |
| Annualisation | `√252 · mean/std` | `√252 · mean/std` (periods_per_year=252) | **Yes** | identical |
| Performance metric calc | `src.utils.metrics.sharpe_ratio` | same function | **Yes** | same code path |

## Quantified diagnostics

- **Ticker overlap:** 20/20 = **100%**.
- **Forecast fidelity:** `pred_flipped` copied verbatim; `fwd_ret_5` corr **1.0000** (max abs diff 0) on 51,160 shared rows.
- **Active-date fraction (factory):** 2,558 / 14,145 = **18.1%** (81.9% empty-book, zero-return dates).
- **Zero-padding deflation:** measured 0.847 → 0.360 = **0.425×** ≈ √0.181 (matches the empty-day theory exactly).
- **Authoritative-vs-reconstruction return correlation:** **≈ 0.10** for every candidate signal (`pred_flipped`, `pred`, `signal_z`, `pred_q`) × weighting (`equal`, `signal`) — i.e. the authoritative basket is not reproducible from committed inputs.
- **Return convention:** authoritative lag-1 autocorr **0.69**, lag-5 **−0.03** → overlapping 5-day (same as factory), so the return convention is **not** the cause.
- **Vol/mean mismatch:** authoritative mean 0.00153 / std 0.01607 vs best reconstruction mean ≈0.0006 / std ≈0.019 — the authoritative book has **higher mean and lower vol**, consistent with a different (unrecovered) basket/weighting.

## Root-cause ranking (largest degradation first)

1. **Un-reproduced authoritative construction — Δ ≈ 0.67–0.99 Sharpe (1.516 → 0.85/0.53).**
   The exact LS20 pipeline that produced `ls_20pct.csv` is not reproducible from
   `v1.csv` + committed `src/` (corr ≈ 0.10). Root cause: the original construction
   (signal transform / weighting / basket) is **under-specified in the repo** — the
   committed artifacts don't fully capture how 1.516 was generated. This is the single
   largest gap and is an *evidence* gap, not something the factory did wrong.
2. **Date-window zero-padding — Δ ≈ 0.49 Sharpe (0.847 → 0.360).** Pure factory scope
   artifact: running the full raw history against a forecast that only exists 2016–2026.
3. **Quantile boundary + weighting — within the 0.53↔0.85 band.** `rank>=0.8`
   (inclusive, ~5 longs) + `Σ|w|` normalization vs `quantile` (~4 longs) + `0.5/n`.
   Secondary.
4. **Transaction costs — ≈ 0.04 Sharpe (0.360 → 0.320 net).** Smallest; expected
   (authoritative is gross).

## Recommended follow-up PRs (small, independent; NOT implemented here)

Each is faithful reproduction, never an "improvement" to P04.

| # | Change | Justification | Expected impact | Risk | Changes methodology? |
| --- | --- | --- | --- | --- | --- |
| **A** | **Scope the recovery execution to the forecast's date window (2016–2026).** Restrict the panel/return series to the dates the historical signal actually covers (config/scope only). | The strategy never traded pre-forecast; the empty-book dates are a scope artifact, not part of the strategy. | **0.360 → ~0.847** | Low | **No** — removes non-traded dates only |
| **B** | **Recover the exact exp_004 LS20 construction** (locate the original notebook/script that produced `ls_20pct.csv`, as done for P02), then port it verbatim. | Committed `v1.csv`+`src` don't reproduce 1.516 (corr ≈0.10); faithful reproduction is impossible without the original construction. | closes the 0.85 → 1.516 gap once found | Medium | **No** — recovers original |
| **C** | **Align the ported signal's quantile boundary + weighting to `equal_weight_long_short`** (only if B confirms that is canonical). | Match the original selection/weighting exactly. | small; not sufficient alone (0.53) | Low | **No** — matches original |
| **D** | **Record gross alongside net** for recovered experiments so comparisons to gross historical numbers are apples-to-apples. | Authoritative figures are gross. | reporting only | Low | **No** |

**Sequencing:** A first (largest reproducible uplift, trivial, no methodology change);
then B (the true blocker for reaching 1.5 — an evidence-recovery task); C/D as needed.

## Fidelity statement

This analysis changed nothing about P04. It confirms the recovered *signal* is
bit-faithful (`pred_flipped` verbatim, `fwd_ret_5` corr 1.0) and that the *return
convention, annualisation, and metric code are identical*. The Sharpe gap is a scope
artifact (date window) plus an evidence gap (the authoritative 1.516 construction is
not fully specified in the repo). No substitution, retraining, or approximation was
performed or is recommended.
