# Project 04 — authoritative recovery result (replayed through the real factory)

**Status: RECOVERED ✅ — faithful, bit-exact replay through the unmodified factory.**

Project 04's authoritative long/short strategy was replayed end-to-end through the
*actual* historical-recovery campaign (manifest → idea → hypothesis → human approval →
experiment → evidence → M11 → Project 07 boundary → campaign report), reproducing the
published notebook metrics to six decimal places with **no execution-engine change**.

## Original vs replay

| Strategy | Notebook (authoritative) | Factory replay (exp) | Δ Sharpe | Fidelity |
| --- | --- | --- | --- | --- |
| LS20 | Sharpe **1.5159546528**, MDD **-0.6553** | Sharpe **1.515955**, MDD **-0.6553** (`exp_007`) | **< 1e-6** | **exact** |
| LS30 | Sharpe **1.4175863355**, MDD **-0.5490** | Sharpe **1.417586**, MDD **-0.5490** (`exp_008`) | **< 1e-6** | **exact** |

Source of truth: `04_portfolio_research.ipynb` cells 120 / 130
("LS 20% Sharpe: 1.5159546527611567", "LS 30% Sharpe: 1.4175863355279652") and
`experiments/completed/exp_004_project04_final/strategy_comparison.csv`.

Reported *net* Sharpe in the campaign report (LS20 1.431 / LS30 1.330) applies the
factory's turnover-based transaction-cost model on top of the gross figure above; the
notebook's published number is gross, so the gross-to-gross comparison is the exact
match shown in the table.

## What made the replay faithful

1. **Authoritative recipe (not `pred_flipped` alone).**
   `combined_signal = z(v1.pred_flipped) + z(v2.pred)` over the `v1 ∩ v2` panel, per-date
   z-score `(x-mean)/std`, ranked per date; LS20 = top/bottom 20 %, LS30 = top/bottom
   30 %; equal weights per side; `max_weight = 0.05` (a confirmed no-op for the balanced
   20-name book). Ported as the ±1 LS membership signals `hist_p04_ls20_v1` /
   `hist_p04_ls30_v1` (`src/signals/historical/p04_return_forecast.py`). Feeding the
   factory the ±1 membership reproduces the exact basket because `rank(pct=True)`
   tie-averaging maps the flagged 20 %/30 % onto the pipeline's 0.80/0.20 selection.
2. **Date-scoped universe (no engine change).** `data/raw/project_04_universe_recovery`
   (built deterministically by `agents/recovery/build_p04_recovery_universe.py`) scopes
   the panel to the strategy's own 2016-01-04…2026-03-06 window (2558 dates), removing
   the pre-forecast zero-padding that had deflated the earlier run to ~0.36. The
   factory's `fwd_ret_5` is bit-identical to the notebook's (`corr = 1.0`, max abs diff
   1e-16).

## Provenance chain (immutable)

`p04_ls20` idea `idea_004_cross_sectional_long_short` → node
`rec_p04-authoritative-recovery_p04_ls20_time` → `exp_007_idea_generator_quantile_ranking`.
`p04_ls30` idea `idea_005_cross_sectional_long_short` → node
`rec_p04-authoritative-recovery_p04_ls30_time` → `exp_008_idea_generator_quantile_ranking`.

Recorded origin provenance (per idea, immutable):

```
origin_project           project_04_return_forecast_alpha
origin_repository        OpusArtisbyRawlz/quant-lab (in-repo experiments)
origin_notebook          research/project_04_return_forecast_alpha/notebooks/04_portfolio_research.ipynb
origin_artifact          experiments/completed/exp_004_project04_final
origin_strategy_name     p04_ls20 / p04_ls30
recovery_manifest_version recovery_manifest_v1
origin_bar_type          time
```

## Campaign identifiers

| Item | Value |
| --- | --- |
| Campaign | `p04-authoritative-recovery` (type `historical_recovery`, state **COMPLETED**) |
| Scope | `{"strategy_ids": ["p04_ls20", "p04_ls30"]}` |
| Ideas (approved) | `idea_004_cross_sectional_long_short`, `idea_005_cross_sectional_long_short` |
| Hypothesis nodes | `rec_p04-authoritative-recovery_p04_ls20_time`, `…_p04_ls30_time` |
| Experiments | `exp_007_idea_generator_quantile_ranking` (LS20), `exp_008_…` (LS30) |
| Evidence events (M11) | 2 |
| M11 verdict | `reject` for both — a policy judgment on drawdown (MDD -0.66 / -0.55 exceeds the default threshold), **not** a fidelity failure; the replay is exact |
| Project 07 handoff | campaign in `pending_handoffs`; `evaluation_status = preliminary` (awaiting authoritative Project 07 evaluation — the factory never writes the verdict) |

The human approval gate held: both ideas were enqueued `pending` and only executed
after explicit approval.

## Blends

`p04_blend_{60_40,50_50,70_30,40_60}_ls20_ls30` are weighted combinations of the LS20
and LS30 **return series** (a portfolio of the two now-faithful books), not standalone
cross-sectional signals; they are cataloged in the manifest as `composition` and are
executed by composing the two ported baselines. They are out of scope for a single
signal experiment and are the natural next P04 follow-up.

## Correction of the record

Earlier P04 investigations concluded the authoritative construction was
"under-specified" / the generator was "not present in any locally reachable source."
**Both conclusions were wrong** — the generator was in the repo the whole time; the
reconstructions had used `pred_flipped` alone instead of the two-forecast
`combined_signal`, and only the first ~30 of the notebook's 138 cells were read. The
corrections are documented in `docs/P04_FIDELITY_ANALYSIS.md` and
`docs/P04_RECOVERY_FORENSICS.md` (originals preserved verbatim beneath the correction
banners).
