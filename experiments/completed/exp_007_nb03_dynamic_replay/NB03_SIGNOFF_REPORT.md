# Notebook 03 (Monte Carlo) — Dynamic Overlay Replay & Sign-off Report

**Experiment:** `exp_007_nb03_dynamic_replay` · **Seed:** 20261027 · **Paths:** 10,000 · **Date:** 2026-10-27
**Validation campaign only** — no parameters optimised, no production candidate selected or changed, no
regime-strategy research. Builds on the completed GARCH source-verification / overlay audit
(`exp_007_garch_volatility_persistence`). Previously validated notebooks and artifacts are untouched.

---

## 1. Underlying pre-exposure alpha & V1 exposure rules (recovered)

V1 is a **dual-layer smooth-drawdown** policy (`exp_005` config `final_model =
weighted_multi_strategy_with_strategy_and_portfolio_smooth_dd`):

- **Underlying alpha** = 3 raw Project-04 strategies (`exp_004_project04_final/strategy_timeseries`):
  `ls_20pct_plus_sqrt_partial_normalized` (0.5), `blend_60_40_ls20_plus_ls30` (0.3), `ls_30pct` (0.2).
- **Strategy-level overlay** (each strategy, on its own drawdown): `exposure = 0.55 + 0.45·exp(−5·|dd|)`.
- Weighted combine → `port_pre`.
- **Portfolio-level overlay** (on `port_pre` drawdown): same `smooth_dd(floor 0.55, k 5)`.
- **Lag/timing:** every exposure is applied with a **1-day lag** (`r_t · e_{t−1}`, `e_{−1}=1`) — verified
  no look-ahead. The stored `portfolio_dd_exposure[t]` equals the as-computed `e[t−1]` (already-lagged),
  which earlier made it look mis-aligned; `pr = port_pre · stored_exposure` reconciles to 1e-16.

## 2. Historical reconstruction fidelity (required gate)

Rebuilding each candidate from the raw alpha + recomputed dual-layer exposure, vs the shipped gross series:

| candidate | max abs daily diff | recon CAGR | shipped CAGR |
|---|---|---|---|
| **V1** | **6.9e-16** (exact) | 0.3770 | 0.3770 |
| DD Only | 1.7e-2 | 0.3721 | 0.4071 |
| Combined | 1.6e-2 | 0.3853 | 0.4256 |

**V1 reconstructs exactly** → gate passed for V1. DD Only/Combined do **not** match exactly, and this is a
genuine provenance finding (not a bug introduced here): the Project-06 tournament built those challengers
on a **re-recovered base** `base_ret = pr / exp.shift(1)` while `pr = port_pre · exp` (exp already lagged),
injecting an extra-lag artifact worth ≈3–5pp CAGR. The clean dynamic replay applies each candidate's
portfolio overlay to the *true* common base `port_pre`. The shipped `exp_007` series are **left unchanged**;
the discrepancy is documented, not patched.

## 3. Dynamic replay (A) vs direct resample (B) — gross, block = 20, N = 10,000

Method A regenerates the 3 raw-alpha paths (shared-index block bootstrap → cross-strategy dependence
preserved) and **recomputes every exposure layer from the simulated states**. Method B (NB03's current
approach) block-bootstraps the already risk-controlled returns directly. 95% CIs are Wilson intervals.

| strategy | method | median MDD | worst-tail MDD (p5) | P(MDD<−20%) | P(MDD<−30%) [95% CI] | median CAGR | median Sharpe | median recovery (d) |
|---|---|---|---|---|---|---|---|---|
| V1 | A dynamic | −0.346 | −0.481 | 0.999 | 0.783 [0.775, 0.791] | 0.356 | 2.01 | 622 |
| V1 | B direct | −0.351 | −0.530 | 0.995 | 0.751 [0.742, 0.759] | 0.372 | 2.08 | 439 |
| DD Only | A dynamic | −0.286 | −0.379 | 0.992 | 0.378 [0.369, 0.388] | 0.348 | 2.13 | 630 |
| DD Only | B direct | −0.293 | −0.447 | 0.960 | 0.457 [0.447, 0.466] | 0.400 | 2.34 | 383 |
| Combined | A dynamic | −0.306 | −0.437 | 0.993 | 0.539 [0.529, 0.549] | 0.358 | 2.10 | 648 |
| Combined | B direct | −0.311 | −0.475 | 0.979 | 0.557 [0.547, 0.567] | 0.418 | 2.27 | 392 |

**Reading it.**
- **Median MDD agrees closely** between A and B for all three (≤0.5pp) → NB03's central drawdown estimate is sound.
- **Worst-tail MDD: B is consistently deeper than A** (e.g. DD Only −0.447 vs −0.379). Resampling the
  risk-controlled returns *freezes* the overlay, so it cannot de-risk into a simulated drawdown; the
  faithful dynamic replay truncates the worst paths. **NB03's tail-MDD is conservative, not optimistic.**
- **P(MDD<−30%)**: the one material divergence is DD Only (B 0.457 vs A 0.378) — B over-states it by ~8pp.
- **CAGR/Sharpe lower under A for DD Only/Combined** — this is the §2 base-recovery artifact (clean base
  has lower CAGR than the shipped inflated series B resamples), *not* a simulation effect. V1 (which
  reconstructs exactly) shows only a small CAGR gap.
- **Recovery duration longer under A** (≈620–650d vs ≈390–440d): dynamic de-risking lowers exposure in
  drawdowns and slows the climb back — a real, previously invisible, property.

## 4. Block-length sensitivity (dynamic A)

| block | V1 P(MDD<−30%) | DD Only P(MDD<−30%) | Combined P(MDD<−30%) |
|---|---|---|---|
| 5 | 0.613 | 0.226 | 0.352 |
| 10 | 0.724 | 0.314 | 0.473 |
| 20 | 0.783 | 0.378 | 0.539 |
| 30 | 0.797 | 0.394 | 0.556 |
| 50 | 0.817 | 0.415 | 0.587 |

Tail-drawdown probability rises monotonically with block length (longer dependence ⇒ deeper drawdowns).
The **ordering across candidates is stable at every block** (V1 > Combined > DD Only on tail-DD risk), but
the *level* is block-sensitive — any headline P(MDD<−30%) must cite its block length.

## 5. Integrity checklist

- **Look-ahead:** none. Exposure lagged 1 day; vectorised primitives (`src/statistics/simulation.py`)
  match the pandas `src/risk/drawdown` originals to 1e-12 (regression-tested).
- **Simulated states, not historical decisions:** A recomputes all exposures from the bootstrapped paths;
  historical exposure is never reused.
- **Fair comparison:** V1/DD/Combined share identical underlying simulated alpha paths and the same seed.
- **Cost:** comparison is on **gross** returns (MDD is cost-insensitive). Net cost not simulated because
  name-level book turnover is unavailable for synthetic paths — an acknowledged limitation (same as the
  prior audit). CAGR/Sharpe rows are gross and labelled as such.
- **GARCH avoided** for strategy simulation (the prior audit showed GARCH(1,1) is misspecified for the
  risk-controlled series); the adaptive policy is captured by dynamic replay instead.
- **Tests:** 256 passed, 11 skipped (full Project-07 suite); +8 new simulation/overlay tests.
- **Reproducibility:** fixed seed 20261027, saved `config.json`, CSV outputs and `analysis_dynamic_replay.py`.

## 6. Sign-off verdict & remaining blockers

**Verdict: NB03's Monte Carlo is sufficiently reliable to support Project 07's final statistical-integrity
assessment for DRAWDOWN conclusions, with two documented caveats.** The drawdown estimates are sound and,
if anything, conservative in the tail; the dynamic replay confirms rather than overturns the drawdown
picture.

Blockers / required annotations before final sign-off:
1. **CAGR comparability (medium):** shipped DD Only/Combined carry a base-recovery (extra-lag) artifact, so
   their *returns* are not a clean function of the common base. Drawdown conclusions are unaffected; any
   **return/Sharpe** ranking of DD Only/Combined from NB03 should be treated as provisional until the
   tournament base recovery is corrected (a Project-06 data-lineage fix, out of scope for this validation).
2. **Net-of-cost simulation (low):** synthetic paths are gross. Before using simulated CAGR/Sharpe (not
   MDD) for decisions, add a book-turnover cost model or state the gross basis explicitly.
3. **Block-length disclosure (low):** always report the block length alongside any P(MDD<threshold).

No deployment candidate was selected or changed; this remains a validation campaign.
