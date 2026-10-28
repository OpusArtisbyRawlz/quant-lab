# PROJECT 07 RECONCILED REPORT — P06/P07 Controlled Remediation

**Experiment:** `exp_007_p06_p07_remediation` · **Branch:** `remediation/p06-p07-return-lineage` · 2026-10-27
**Inputs preserved:** exp_004/exp_005 checksums unchanged · defective outputs archived read-only
**Mandate honoured:** no parameter optimised, no production logic altered, **no candidate promoted**

This is the single coherent, reproducible, statistically defensible set of Project-06/07 results after
fixing the return-lineage defect at source. It consolidates `SOURCE_FIX_REPORT.md`,
`REGENERATED_PERFORMANCE.csv`, `STATISTICAL_TEST_RECONCILIATION.csv`, `COST_AND_CAPITAL_SENSITIVITY.csv`,
`MONTE_CARLO_COST_AUDIT.md`, and `ARTIFACT_DEPENDENCY_STATUS.csv`.

---

## 1. Corrected performance (net of 10bps; see `REGENERATED_PERFORMANCE.csv`)

| candidate | CAGR (old→new) | Sharpe (old→new) | MDD (old→new) | Calmar new |
|---|---|---|---|---|
| **V1** | 35.70% → **35.70%** | 1.999 → **1.999** | −37.15% → **−37.15%** | 0.96 |
| **DD Only** | 38.84% → **35.40%** | 2.264 → **2.140** | −29.86% → **−30.18%** | 1.17 |
| **Combined DD+Vol** | 40.59% → **36.83%** | 2.196 → **2.072** | −31.88% → **−32.32%** | 1.14 |

V1 bit-identical. The defect inflated DD/Combined CAGR by ~3.5–3.8pp and Sharpe by ~0.12, and understated
their drawdown by ~0.3–0.4pp.

## 2. Reconciled evidence by dimension (Phase 6)

| dimension | V1 | DD Only | Combined DD+Vol |
|---|---|---|---|
| **Observed historical** | baseline | lower CAGR than V1, **−7pp shallower MDD**, higher Sharpe | ≈V1 CAGR+1pp, modestly shallower MDD |
| **Significance of improvement vs V1** (paired block bootstrap) | — | Sharpe **+0.141 p=0.010 ✓**; MDD **+6.98pp p=0.0005 ✓**; CAGR −0.3pp p=0.58 ✗ | Sharpe +0.073 p=0.20 ✗; MDD +4.83pp p=0.098 ✗; CAGR +1.1pp p=0.30 ✗ |
| **Multiple-testing adjusted** (m=2, Bonferroni & BH) | — | Sharpe & MDD **REJECT H0 under both** | **clears nothing under either** |
| **Selection-aware (White's RC)** | — | — | winner is raw **P04:ls_20pct**, p=0.0103 (unchanged); overlays are not the best-of-family |
| **PSR / DSR** | PSR(0)≈1, DSR(N=100)≈0.99999 | saturated ≈1 (net Sharpe still ~2.1) | saturated ≈1 |
| **Simulation risk** (dynamic MC, net) | P(MDD<−30%)=0.83 | **P(MDD<−30%)=0.38**, Sharpe 2.04 | 0.61 (year-1 warm-up caveat → PROVISIONAL) |
| **Cost / financing sensitivity** | highest turnover & short notional | edge **grows** with trading cost (no break-even); borrow≤0.06 Sharpe @300bps | uses up to **1.28× gross notional** (only candidate needing margin financing) |
| **Deployment limitations** | incumbent | risk-reducer, not a return-improver | **no incremental edge over V1 on any axis** |

**Reconciled reading.** DD Only is a genuine **drawdown-and-risk-adjusted** improvement over V1 (robust
MDD and Sharpe edges that survive multiple-testing, out-of-sample folds, simulation and cost), with **no
CAGR premium**. Combined DD+Vol is **not statistically distinguishable from V1** on Sharpe, CAGR or MDD and
additionally carries a financing/leverage cost the others do not. V1 remains fully valid and unchanged.
Rankings and deployment decisions are **kept provisional** per the mandate — no winner is selected.

## 3. A new substantive finding from regeneration
The overlay-challenge **promotion gate flipped from PASS to FAIL** on the corrected base
(`promotion_gate_result.json`: `overall_pass` True→False). GATE 2b (causal walk-forward OOS) now fails
because DD Only's fixed (0.3,5) params beat the incumbent on **Sharpe in only 4/7 folds** (gate needs ≥6/7),
though MDD is shallower in **7/7**. The inflated returns had pushed DD Only over the OOS Sharpe bar; the
corrected returns reveal it as a drawdown improver whose *Sharpe* edge is real but not strong enough to
clear a promotion gate. This is consistent with — and independent corroboration of — the audit.

## 4. Final integrity gate (Phase 9) — answers + status

| # | Question | Answer | Status |
|---|---|---|---|
| 1 | Defect fixed at source? | Yes — same-row inverse in all 8 call sites; regression-guarded | **PASS** |
| 2 | Returns reconcile with canonical construction? | V1 1e-16, DD Only 5e-16 vs exp_004; Combined base exact (year-1 vol warm-up residual only) | **PASS** |
| 3 | Turnover & cost estimates valid? | Yes — turnover from the real book; changed <0.02pp; cost formula verified | **PASS** |
| 4 | Corrected net metrics? | V1 35.70%/1.999/−37.2%; DD 35.40%/2.140/−30.2%; Combined 36.83%/2.072/−32.3% | **PASS** |
| 5 | Which PSR/DSR/WRC/bootstrap/permutation hold? | All — WRC identical (0.0103), DSR/PSR saturated (V1), bootstrap/permutation V1-only | **PASS** |
| 6 | DD Only drawdown & Sharpe improvement credible? | Yes — MDD +6.98pp p=0.0005 (FWER-robust), Sharpe +0.141 p=0.010 | **PASS** |
| 7 | Combined distinguishable from V1? | No — no edge survives on any axis | **PASS (conclusive: not distinguishable)** |
| 8 | Sensitivity to borrow/financing/execution cost? | Low & near common-mode; challenger edges have no finite break-even | **PASS (robust)** |
| 9 | MC drawdown estimates still supported? | Yes — fidelity passes; DD Only halves P(MDD<−30%) net of cost | **PASS** (Combined path CAGR/Sharpe **PROVISIONAL**) |
| 10 | What remains before purging/embargo/CPCV/PBO? | see §5 | **PROVISIONAL** |

### Pass/fail/provisional for every major requirement
- Source fix implemented & tested — **PASS**
- P06 tournament + overlay regenerated on corrected base — **PASS**
- P07 NB06 (WRC) / NB09 (net validation) regenerated — **PASS**
- NB03 dynamic-replay rerun, fidelity passes — **PASS** (Combined year-1 warm-up — **PROVISIONAL**)
- Cost & capital sensitivity, break-even — **PASS**
- Full regression/integrity suite (P06 8, P07 269/11 skipped) — **PASS**
- P04/P05 unaffected — **PASS**
- `promote_deployment_candidate.py` outputs — **INVALID** (defective-historical; not regenerated; not run)
- Borrow/financing historically unmodelled — **PROVISIONAL** (bounded scenarios disclosed)

## 5. Remaining before Project-07 proceeds to purging / embargo / CPCV / PBO
1. **Decision policy:** treat DD Only as a *drawdown-control variant of V1*, not a higher-return strategy;
   do **not** treat Combined as superior to V1. No promotion in this campaign.
2. **Combined MC warm-up:** harmonise the vol-multiplier pre-window convention between the NB03 `simulation`
   module and the tournament **if** Combined is ever reconsidered; immaterial to current conclusions.
3. **Borrow/financing:** fold an explicit short-borrow/financing model (and Combined's up-to-1.28× leverage)
   into the net framework before any live go/no-go — currently bounded scenarios only.
4. **CPCV/PBO readiness:** the corrected, reconciled series are the correct inputs; purging/embargo and PBO
   were out of scope here and remain to be run on these canonical series.

## 6. Confidence
Root cause and fix: **certain** (reproduced to 1e-16; regression-guarded; V1 bit-identical). Corrected
metrics and significance flips: **high** (old reproductions matched the archived files; corrected numbers
come from one consistent seeded pipeline and independently reproduce the forensic audit). Residual
Combined MC warm-up: **fully characterised and bounded** (first 252 days only).
