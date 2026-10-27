# PAPER-TRADING OBSERVATION PROTOCOL (Phase 8)

**Experiment:** `exp_007_full_pipeline_validation` · **Status:** specification only — **no live trading, no
broker orders, no real-capital authorization.** Purpose: collect **genuinely new, post-freeze** evidence
on V1 and DD Only after the strategies and validation criteria are frozen. This is an information-collection
protocol; approval for real capital is a **separate** decision (see `SHADOW_TRADING_READINESS.md` §Escalation).

Scope: **V1 baseline** and **DD Only** (floor 0.3, k 5). Combined DD+Vol is **excluded** (no incremental
edge; carries 1.28× leverage — `PROJECT_07_ADVANCED_VALIDATION_REPORT.md`). The **6/7 production gate is
unchanged**; paper trading neither substitutes for it nor relaxes it.

## 1. Freeze specification (recorded before day 1)
| item | value |
|---|---|
| Strategy versions | V1 (shipped dual-layer smooth-DD book); DD Only (smooth-DD floor 0.3, k 5) |
| **Code commit** | frozen at the reviewed merge of `remediation/p06-p07-return-lineage` (record the exact SHA at go-live) |
| Frozen parameters | overlay floor/k, LS quantiles (0.2/0.2), universe (20 tickers), label horizon 5d — **no changes during the window** |
| Model | the actual P04 OLS blend (V1-flip + V2), per `PROJECT04_MODEL_LINEAGE.md`; retrained **only** on the pre-freeze schedule below |
| Validation criteria | frozen at freeze date; new metrics are **observed**, not used to retune |

## 2. Capital, market & cost assumptions
- **Notional capital:** $10 M paper (scalable); report everything in normalized return terms too.
- **Universe/data:** the 20-ticker P04 universe; daily bars from the same vendor as research; corporate-action adjusted.
- **Position sizing / limits:** gross ≤ 1.0 for V1 and DD Only (DD Only ≤ 1.0 by construction); per-name cap
  from the shipped book; **gross-cap alert** if any day's target exceeds 1.30 (should never fire for these two).
- **Signal schedule:** generate signals **daily at close (T)** from data available through T; **execute at
  T+1 open**. Weights already carry a 1-day execution lag (`apply_exposure_to_return` shifts exposure) — the
  protocol must not double-lag (this is the exact defect remediated in P06/P07).
- **Order timing:** single daily rebalance to target; no intraday.
- **Slippage / costs:** 2 bps slippage + 1 bps commission per side (matches the P06 cost model that produced
  the ≈2.16%/yr net drag); revisit only with documented justification, never mid-window.
- **Borrow / shorts:** require a locate on every short each day; if unavailable, **drop the name and log the
  deviation** (do not substitute). Record borrow fees.
- **Financing:** charge a financing rate on any gross > 1.0 notional (not expected for V1/DD Only); logged
  even when zero so the field is auditable.

## 3. Daily operations
1. Ingest prices (T close) → compute features → P04 OLS blend predictions → combined signal → target weights
   → apply frozen overlay. 2. Diff vs held positions → hypothetical orders. 3. Model fills at T+1 open +
   slippage. 4. Update positions, cash, financing, borrow. 5. Mark P&L; compute **deviation vs the theoretical
   backtest** for the same day. 6. Append to the immutable ledger. All steps are the `shadow_trader.py` harness.

## 4. Monitoring, logging, evidence retention
- **Logged daily:** target weights, orders, modelled fills, positions, gross/net exposure, turnover, costs,
  borrow events, financing, gross/net P&L, equity, and **deviation** from theory. Append-only CSV + daily hash.
- **Risk monitors:** rolling drawdown, realized vol, gross exposure, tracking error vs theory, short-locate
  failures, data-gap/stale-price flags.
- **Operational monitors:** missed signal runs, late fills, feed outages — logged as deviations, not silently
  repaired.

## 5. Performance comparisons (observed, not optimized)
- Shadow vs **theoretical backtest** (tracking error, cumulative deviation).
- DD Only vs V1 on the **same prospective window** — the only genuinely out-of-sample test available: Sharpe,
  MDD, vol, Calmar, and the drawdown-protection claim (expected to be DD Only's strongest axis).
- Realized vs assumed costs/slippage/borrow.

## 6. Stop & escalation rules (pre-registered)
- **Halt & review** if: shadow drawdown breaches −25%; |annualized deviation from theory| > 150 bps
  (indicates a code/data divergence, not alpha); repeated short-locate failures; or any data-integrity breach.
- **Escalation to a real-capital *decision* (not an authorization):** only after a pre-specified minimum
  observation horizon (recommend ≥ 6–12 months of prospective data), **and** satisfaction of the existing
  production requirements, **and** resolution of the open items in `FINAL_VALIDATION_REPORT.md` §"evidence
  still required". A real-capital decision is made by a human reviewer; this protocol never triggers it
  automatically.

## 7. Separation of regimes (explicit)
**Simulation** (historical backtests, CPCV, MC) → **paper/shadow execution** (this protocol: prospective,
hypothetical fills, no broker) → **real-capital authorization** (out of scope; separate human sign-off).
Nothing in this document authorizes, or is a precondition that by itself authorizes, real trading.
