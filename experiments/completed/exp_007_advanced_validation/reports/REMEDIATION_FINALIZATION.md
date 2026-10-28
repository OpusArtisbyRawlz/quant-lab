# REMEDIATION FINALIZATION — Stage A

**Experiment:** `exp_007_advanced_validation` · **Branch:** `remediation/p06-p07-return-lineage`
**Date:** 2026-10-28 · **Predecessors:** `exp_007_research_integrity_audit`, `exp_007_p06_p07_remediation`

---

## A1. Verification of the completed remediation

Reviewed `exp_007_research_integrity_audit/` and `exp_007_p06_p07_remediation/`. Confirmed:

| check | result |
|---|---|
| Double-lag defect corrected at source | ✓ same-row inverse `pr/exp` in all **8** call sites |
| All affected call sites repaired | ✓ (audit named 2; grep found 6 more — all fixed) |
| V1 historical returns unchanged | ✓ bit-identical (`equity_curve.csv`/`metrics.json`/`turnover.csv`) |
| DD Only / Combined use canonical reconstructed returns | ✓ reconstruct from exp_004 to 1e-12 / 5e-16 |
| P06 and P07 outputs regenerated | ✓ tournament, overlay, NB09, NB06, NB03 replay, GARCH |
| Original artifacts preserved | ✓ 246 defective outputs archived read-only + git history |
| Turnover/cost reconcile with the position book | ✓ `compute_turnover(book)`; changed <0.02pp |
| Full regression + integrity tests pass | ✓ P06 8, P07 269/11 skipped at remediation commit |

**Commit created (not merged):** `8a3f9e0` on `remediation/p06-p07-return-lineage`, 183 files, preserving
the original evidence. Unrelated tracks (`idea_generator` experiments), the pre-existing
`project_05_risk_engine/README.md` edit, and infra artifacts were deliberately excluded. Merge is left
for the repository's normal review.

## A2. Resolved methodological issues

### Combined warm-up discrepancy — **corrected consistently**
The prior audit left a residual: the NB03 dynamic replay reconstructed Combined with a 0.0112 max
difference vs the tournament, confined to the first 252 days. Root cause: the vol multiplier
`(rv/mean(rv))**0.5` is undefined pre-window (rolling 252-day std is NaN). The tournament let that NaN
propagate through `(m·smooth).clip` and filled the *whole combined exposure* to 1.0 only afterwards —
which disabled the (computable) DD overlay too during year 1. The MC reconstruction instead used the
multiplicative identity 1.0 for the undefined multiplier and kept the DD overlay active.

**Decision:** the undefined multiplier's neutral value is its multiplicative identity, 1.0; the DD
overlay should stay active during warm-up. This is a convention fix, not a parameter change and not a
hypothesis change (`(vol_mult·smooth_dd).clip(0.5,1.3)` is unchanged). Implemented by filling the
pre-window multiplier with 1.0 in `vol_multiplier` of both `run_tournament.py` and
`run_overlay_challenge.py`, and regenerating.

| effect of the fix | before | after |
|---|---|---|
| Combined gross CAGR | 38.74% | **38.53%** (−0.20pp; more conservative) |
| Combined gross Sharpe | 2.158 | 2.171 |
| Combined MDD | −31.92% | −31.92% (unchanged) |
| **NB03 Combined MC fidelity** | 0.0112 | **5.57e-16** |
| V1, DD Only | unchanged | unchanged (no vol term) |

The fix affects only vol-multiplier candidates' first year, lowers Combined's CAGR slightly, and
reconciles the MC fidelity to machine precision. The **PROVISIONAL** classification on Combined's
Method-A path stats is now **cleared**. WRC remains identical (p=0.0103).

### Financing and borrowing costs — reviewed
`COST_AND_CAPITAL_SENSITIVITY.csv` (prior remediation) verified:
- **No double counting:** trading drag (`turnover·bps/1e4`) and borrow drag (`short_notional·bps/1e4/252`)
  are separate terms, both subtracted from **gross** — never stacked on the already-net series.
- **Financing/leverage explicit:** V1 and DD Only cap gross notional at 1.00 (no leverage); **Combined
  reaches 1.28×** — the only candidate needing margin financing. Disclosed.
- **Combined gross notional correctly represented** (mean 0.586, max 1.283).
- **Turnover from actual position changes** (`Σ|Δw|/2` on the book), applied at execution.
- Borrow fees are **not invented**: bounded scenarios (0–300 bps/yr on short notional) only; they move
  Sharpe ≤0.06 and are near common-mode across candidates. This remains a disclosed **PROVISIONAL** gap.

## A3. Promotion gate preserved + the 4/7 fold investigation

The 6/7 Sharpe promotion gate is **unchanged**. On corrected returns the overlay-challenge gate
**fails** (`overall_pass=False`): DD Only's fixed (0.3,5) beat the incumbent OOS on Sharpe in **4/7**
folds (<6/7) and on MDD in **7/7**. We keep the three questions separate:

1. *Improves historical risk-adjusted performance?* Yes (net Sharpe +0.141, MDD −6.98pp vs V1).
2. *Statistically credible drawdown protection?* Yes (p=0.0005, FWER-robust; 7/7 OOS folds).
3. *Satisfies the predefined 6/7 production gate?* **No.** Gate preserved as a failure.

**The 3 Sharpe-miss folds** (`data/a3_fold_diagnostics.csv`):

| fold | window | regime | incumbent ann ret | DD Only ann ret | ΔSharpe | ΔMDD (shallower) | DD Only mean exp |
|---|---|---|---:|---:|---:|---:|---:|
| 0 | 2019 | down | −5.3% | **−4.0%** | −0.047 | +2.7pp | 0.48 vs 0.66 |
| 2 | 2021 | down | −14.9% | **−13.6%** | −0.071 | +4.7pp | 0.58 vs 0.73 |
| 6 | 2025–26 | up | +6.2% | +4.1% | −0.0006 (tie) | +6.2pp | 0.43 vs 0.64 |

**Reading:** in 2 of the 3 miss folds (2019, 2021) DD Only **lost less money and drew down less** than
V1, yet posted a marginally lower Sharpe — the arithmetic of a negative-mean Sharpe when de-risking
cuts volatility faster than it cuts the (negative) mean. The third (2025–26) is a dead-heat Sharpe with
a 6pp shallower drawdown. None of the misses is evidence that DD Only is economically inferior; they are
the expected signature of a drawdown-control overlay. This does **not** reopen the gate or the overlay
parameters. V1 remains the validated baseline; DD Only remains an **unpromoted risk-controlled candidate**.
Combined is **not** promoted.
