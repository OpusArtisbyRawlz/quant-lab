# DD ONLY — WALK-FORWARD FOLD ATTRIBUTION (Phase 7)

**Experiment:** `exp_007_full_pipeline_validation` · script `scripts/p7_fold_attribution.py`
Data: `DD_ONLY_FOLD_ATTRIBUTION.csv`. The **6/7 Sharpe promotion gate and its failure are preserved and
unchanged.** DD Only stays an **unpromoted, risk-controlled research candidate**. Nothing here re-optimises
the overlay or the gate.

DD Only (smooth-DD floor 0.3, k 5) vs the V1 incumbent across the 7 annual walk-forward folds:
**Sharpe improves in 4/7, MDD is shallower in 7/7, realized vol is lower in 7/7.** The three Sharpe-miss
folds are **0 (2019), 2 (2021), 6 (2025)**.

## Per-fold decomposition [V]

| fold | regime | ΔSharpe | ΔAnnRet (pp) | ΔMDD shallower (pp) | vol cut (pp) | Δret on up-days (pp) | Δret on down-days (pp) | dominant channel |
|---|---|---|---|---|---|---|---|---|
| 0 | neg | −0.0475 | **+1.26** | +2.71 | +2.11 | −12.6 | **+13.8** | Sharpe-sign artifact |
| 1 | pos | +0.0084 | −28.2 | +1.15 | +1.40 | −14.2 | +6.9 | pass |
| 2 | neg | −0.0705 | **+1.27** | +4.69 | +1.69 | −12.9 | **+14.2** | Sharpe-sign artifact |
| 3 | pos | +0.1938 | +0.59 | +3.03 | +1.14 | −9.2 | +9.3 | pass |
| 4 | pos | +0.0646 | −6.97 | +1.15 | +1.54 | −14.1 | +9.4 | pass |
| 5 | pos | +0.4292 | +6.38 | +4.48 | +1.16 | −8.3 | +13.1 | pass |
| 6 | pos | −0.0006 | −2.03 | **+6.24** | +2.84 | −16.1 | +13.9 | opportunity cost |

(Δret on up/down-days = cumulative DD-Only-minus-incumbent return on days the base return was positive /
negative; "up-days" negative = upside given up, "down-days" positive = loss avoided. Added-turnover proxy
mean |Δexposure| ≤ 0.021/day in every fold — **cost is not a driver**.)

## What drives the three Sharpe misses

**Folds 0 & 2 — Sharpe-sign artifact (2 of 3 misses).** Both are **negative-return years**. DD Only
**lost less** (+1.26 pp, +1.27 pp annualised) and **drew down less** (+2.71 pp, +4.69 pp shallower), and
cut vol (+2.11 pp, +1.69 pp). Sharpe still falls because **Sharpe is a biased comparator when the mean
return is negative**: scaling a losing stream down by de-risking shrinks the (negative) numerator less
than the denominator, so the ratio becomes *more* negative even though the investor is unambiguously
better off. Economically DD Only is **superior** in these folds; the gate metric just mis-signs it.

**Fold 6 — genuine opportunity cost (1 of 3 misses).** A mildly positive year where DD Only ran the
**lowest exposure of any fold** (mean executed exposure ≈ 0.43 vs the incumbent's higher path). It gave
up **2.03 pp of return** to buy the **largest MDD improvement of all folds (+6.24 pp shallower)**; Sharpe
is a **tie** (−0.0006). This is the overlay behaving exactly as designed — trading upside for drawdown
protection — not a defect.

**Exposure is not timed to profit.** In every fold DD Only's executed exposure on up-days ≈ its exposure
on down-days (e.g. fold 0: 0.474 vs 0.476), because exposure is a function of the **drawdown state**, not
of the sign of the coming return. So the misses are **not** "systematically de-risking into rallies"; they
are the drawdown overlay responding to prior losses.

## Answers

### Q5 — Does DD Only's drawdown-protection evidence remain credible?
**Yes.** 7/7 shallower MDD and 7/7 lower vol across folds, consistent with the pooled result (ΔMDD
+6.98 pp, p = 0.0005) and the 7/7 OOS fold agreement from the earlier campaign. The protection is the
**most robust** part of DD Only's case. [V]

### Q6 — What can we legitimately conclude from 4/7 Sharpe and 7/7 MDD?
- **Legitimate:** DD Only reliably **reduces drawdown and volatility**; its Sharpe effect is **positive
  but modest and not strong enough to clear a 6/7 gate**; 2 of the 3 "failures" are a **metric artifact**
  in losing years where DD Only is actually better, and the 3rd is a **deliberate risk/return trade**.
- **Not legitimate:** treating 4/7 as a 7-trial binomial, or concluding DD Only is **inferior** to V1.
  The folds are consecutive calendar years on an **overlapping 5-day-label** series and share regime, so
  they are **not independent**; the count carries wide uncertainty and should not be over-read. [stated]
- **Gate status:** **preserved as a FAILURE.** Failing the gate does **not** prove DD Only is inferior;
  it means the predefined Sharpe bar is not met, which is a promotion decision, not an economic verdict.

We do **not** prefer V1 merely because DD Only failed the gate, and we do **not** adjust the gate or the
overlay. DD Only remains an unpromoted risk-controlled candidate pending independent forward evidence.
