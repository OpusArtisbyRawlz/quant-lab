# STATISTICAL INTEGRITY REVALIDATION

**Audit:** `exp_007_research_integrity_audit` · all "old" numbers reproduce the shipped artifacts; all
"corrected" numbers use the canonical base. Data: `OLD_VS_CORRECTED_RESULTS.csv`,
`significance_old_vs_corrected.csv`, `cagr_mdd_significance_old_vs_corrected.csv`,
`wrc_dsr_old_vs_corrected.json`, `psr_dsr_old_vs_corrected.csv`.

---

## 1. Performance metrics — old vs corrected (gross and net)

| candidate | basis | CAGR old → new | Sharpe old → new | MDD old → new |
|---|---|---|---|---|
| V1 | gross | 37.70% → **37.70%** | 2.090 → **2.090** | −36.69% → **−36.69%** |
| V1 | net | 35.70% → **35.70%** | 1.999 → **1.999** | −37.15% → **−37.15%** |
| DD Only | gross | 40.71% → 37.21% (−3.50pp) | 2.352 → 2.229 | −29.47% → −29.79% |
| DD Only | net | 38.84% → 35.38% (−3.46pp) | 2.264 → 2.139 | −29.86% → −30.18% |
| Combined | gross | 42.56% → 38.74% (−3.83pp) | 2.281 → 2.158 | −31.48% → −31.92% |
| Combined | net | 40.59% → 36.82% (−3.77pp) | 2.196 → 2.071 | −31.88% → −32.32% |

V1 unchanged on every metric. The defect **inflated** DD/Combined CAGR by ~3.5–3.8pp and Sharpe by ~0.12, and
**understated** their drawdown by ~0.3–0.4pp (correction makes MDD slightly deeper).

## 2. Significance vs V1 — the decision-level impact

Paired block bootstrap, challenger − V1, net returns, m=2 family. Old reproduces the shipped
`net_*_significance_vs_v1.csv` files.

| test | challenger | OLD result | CORRECTED result | verdict |
|---|---|---|---|---|
| **ΔSharpe** (block21,Nboot5000) | DD Only | +0.265, p=0.0004 → REJECT | +0.141, p=0.010 → **REJECT** | survives (weaker) |
| | Combined | +0.197, p=0.011 → REJECT | +0.073, p=0.20 → **fail to reject** | **FLIPS** |
| **ΔCAGR** (block20,Nboot10k) | DD Only | +3.14pp, p=0.024 → reject@0.05 | −0.30pp, p=0.58 → **fail** | **FLIPS (gone)** |
| | Combined | +4.88pp, p=0.011 → REJECT | +1.13pp, p=0.29 → **fail** | **FLIPS** |
| **ΔMDD** (block20,Nboot10k) | DD Only | +7.29pp, p=0.0002 → REJECT | +6.98pp, p=0.0009 → **REJECT** | survives robustly |
| | Combined | +5.27pp, p=0.050 → borderline | +4.83pp, p=0.10 → **fail** | weak/not significant |

**Reading.** After correction:
- **DD Only** is a genuine **drawdown + risk-adjusted** improver over V1 (MDD −7pp, p<0.001; Sharpe +0.14,
  p=0.01) with **no CAGR premium** (≈0). This is the economically coherent profile of a de-risking overlay.
- **Combined DD+Vol** is **no longer statistically distinguishable from V1** on Sharpe, CAGR, or (robustly)
  MDD. Its previously reported edge was an artifact of the inflated base.

## 3. PSR / DSR / MinTRL (NB05 / NB09)

- Candidate under test for PSR/DSR is **V1** (defect-free). PSR(0)≈1.0 and DSR(N=100)≈0.99997 for all three
  both old and corrected — these saturate because observed Sharpe (~2) ≫ expected-max under the null, so they
  are **insensitive to the defect**.
- The DSR *trial-variance input* (23 per-period trial Sharpes, incl. the defective overlay family) corrects
  from `V_trials` 4.935e-4 → 3.495e-4 (overlay Sharpes less inflated ⇒ smaller spread). DSR for V1 moves
  0.99997 → 0.99999. **No decision change.** Status: VALID (with a corrected, non-material input).

## 4. White's Reality Check (NB06)

Universe = 12 raw P04 strategies + 11 overlay columns (gross, benchmark 0, shared stationary-bootstrap
indices, block 20, 10k resamples). Rebuilding the overlay columns on the canonical base:

| | best strategy | observed stat | WRC p (block 20) |
|---|---|---|---|
| OLD (defective universe) | `P04:ls_20pct` | 0.07760 | 0.01030 |
| CORRECTED universe | `P04:ls_20pct` | 0.07760 | **0.01030** |

**Identical.** The WRC winner is a raw, defect-free P04 strategy; the correction only *lowers* the non-winning
overlay columns, so neither the max statistic nor the recentred null-max distribution moves. WRC conclusion
(best searched strategy beats zero, p≈0.010) is **VALID and robust**. Dependence assumptions, common dates
and benchmark (=0) are unchanged.

## 5. Bootstrap (NB01) & Permutation (NB02)

Both operate only on the V1 shipped series (`exp_005 portfolio_return`). V1 is defect-free, so their
confidence intervals, null hypotheses and p-values are **VALID, unchanged**.

## 6. Multiple testing (NB04)

Trial counts / family structure are definitional and do not consume the defective return values; **VALID**.
Note: the Family-A correction (§2) changes *which* challengers clear the family threshold — DD Only still
clears on Sharpe/MDD; Combined no longer clears on any dimension — so the *conclusions* drawn from the
multiple-testing table change even though the correction arithmetic is unaffected.

## 7. Monte Carlo (NB03) & dynamic replay (exp_007_nb03_dynamic_replay)

- The **dynamic replay (method A)** already regenerates paths from the **canonical** `port_pre` and recomputes
  every overlay from simulated states — it does not touch the defect. Its drawdown conclusions
  (median-MDD agreement, conservative tail) are **VALID**.
- NB03's **method B** (direct resample of the shipped risk-controlled returns) resampled the **defective** DD/
  Combined series, so its DD/Combined **CAGR/Sharpe** path statistics are inflated in the same way as §1. Its
  **drawdown** read is unaffected in direction (B is conservative vs A on tail MDD regardless of level).
- No simulation needs re-running for the drawdown verdict; CAGR/Sharpe path stats for DD/Combined should be
  read off the canonical base. Status: **PROVISIONAL** for DD/Combined return/Sharpe path stats, VALID for
  drawdown.

## 8. Net effect on the central hypotheses

| hypothesis | before | after correction |
|---|---|---|
| "DD Only improves max drawdown vs V1" | supported | **still supported, robustly** (−7pp, p<0.001) |
| "DD Only improves Sharpe vs V1" | supported | still supported, weaker (p=0.01) |
| "DD Only has higher CAGR than V1" | supported | **not supported** (≈0) |
| "Combined beats V1 (Sharpe/CAGR/MDD)" | supported | **not supported on any axis** |
| "There is genuine alpha in the universe (WRC)" | supported | **unchanged** |
| "V1 survives PSR/DSR/bootstrap/permutation" | supported | **unchanged** |
