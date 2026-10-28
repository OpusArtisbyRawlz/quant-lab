# STATISTICAL-INTEGRITY RECONCILIATION (Phase 6)

**Experiment:** `exp_007_full_pipeline_validation`. Integrates this campaign (model lineage, full-model
CPCV, expanded PBO, fold attribution) with the prior evidence base (bootstrap, permutation, multiple-
testing / FWER, PSR, DSR, MinTRL, White's Reality Check, Monte Carlo + dynamic overlay replay, walk-forward
gate, purged K-fold, CPCV). Each major claim is separated into the six evidence layers. **No earlier report
was altered; this reconciles, it does not overwrite.**

Layers: **(1)** observed historical result · **(2)** statistical uncertainty · **(3)** selection-adjusted ·
**(4)** OOS / cross-validation · **(5)** simulation-based risk · **(6)** remaining implementation/deployment risk.

## V1 alpha is real
1. Net Sharpe ≈ 2.0, CAGR ≈ 35.7% (post-remediation; bit-identical to pre-fix — V1 never had the defect).
2. Bootstrap/permutation support; PSR high; MinTRL short relative to sample.
3. **White's Reality Check p = 0.0103** (selection-aware, winner `P04:ls_20pct`); DSR(N=100) ≈ 0.99999.
4. Model rank IC weak but **positive in the 2016+ deployment era** (+0.009, 71% CPCV paths); portfolio
   survives purged folds. **Caveat:** full-sample model rank IC ≈ 0 (Q1) — the Sharpe leans partly on
   directional beta + overlapping labels, not strong per-name skill.
5. MC Sharpe ~2.0; dynamic overlay replay fidelity 5.6e-16 after the warm-up fix.
6. **Model finalizer not bit-reproducible** (lineage §4); 20-ticker breadth; beta dependence.
→ **Best-corroborated claim**, with an honest asterisk that the *source of* the Sharpe is only weakly rank skill.

## DD Only drawdown protection
1. Net MDD −30.2% vs V1 −37.2% (ΔMDD +6.98 pp).
2. **p = 0.0005; FWER-robust.**
3. Survives multiple-testing correction; overlay selection PBO low *within grid* (but a lower bound, see below).
4. **7/7 OOS walk-forward folds shallower MDD; 7/7 lower vol** (Phase 7).
5. MC halves P(MDD < −30%): 0.38 vs 0.78.
6. Real-cost/borrow modelling still bounded-scenario; forward evidence not yet collected.
→ **Most robust DD Only claim** across all six layers.

## DD Only Sharpe edge
1. +0.141 net Sharpe.
2. p = 0.010; clears FWER.
3. Selection-aware tests pass.
4. **Fails the 6/7 gate (4/7)**; 2 of 3 misses are a negative-regime Sharpe-sign artifact, 1 is a deliberate
   risk/return trade (Phase 7).
5. MC Sharpe 2.04 vs 1.91 (net).
6. Modest magnitude; gate-fail stands; needs forward evidence.
→ **Real but modest; not gate-clearing.** Gate preserved as a failure.

## Combined DD+Vol incremental edge
1. +1.1 pp CAGR vs V1. 2. Sharpe p = 0.20, MDD p = 0.10, CAGR p = 0.30 — **none significant.**
3. none. 4. none beyond V1. 5. no simulation edge. 6. carries **1.28× leverage / financing**.
→ **No surviving edge.** Not eligible for promotion or paper trading.

## Original P04 model forecast skill (new this campaign)
1. In-sample fit only (static 2016 split). 2. per-date IC noisy (20-name cross-section).
3. — . 4. **Purged CPCV: full-sample rank IC ≈ 0 at blend level (V1-flip leg negative, V2 weakly +);
   deployment-era +0.009. Representative ridge overstated full-sample skill (0.030).** 5. — .
6. finalizer blocker; regime dependence.
→ **Weak, regime-dependent rank skill; prior ridge proxy was optimistic on full history (Q1/Q2).**

## Overlay-selection overfitting
1. IS winner `dd_f0.2_k7`. 2. — . 3. **PBO 0.0016 (Sharpe)/0.0112 (Calmar); stable under verified
   expansion (0.0014/0.0043).** 4. OOS rank of selected ≈ top. 5. — . 6. **Effective dimension ≈ 1
   (mean|corr| 0.99) → low PBO partly tautological and a LOWER BOUND; the distinct P04-construction layer
   has PBO 0.46–0.77.** → **Not overfit within the (near-degenerate) grid; pipeline-wide PBO unreconstructable.**

## Cross-cutting integrity rules honored
- **CPCV ≠ chronological validation** — labeled a robustness test throughout; not a live replica.
- **Positive CV / low PBO / significant Sharpe are each necessary-not-sufficient** — no single one is treated
  as a deployment trigger; the gate and forward-evidence requirements stand.
- **Costs/equity reconcile:** P06 cost model ≈ 2.16%/yr net drag, independently confirmed by the historical
  replay (net Sharpe 1.431 on the ls_20 base).
- **Each test addresses a distinct failure mode** (data-mining luck → WRC/PBO; small-sample → PSR/MinTRL;
  path risk → MC; time-ordering/leakage → walk-forward + purged CPCV). They **complement, not replace**, one
  another.
