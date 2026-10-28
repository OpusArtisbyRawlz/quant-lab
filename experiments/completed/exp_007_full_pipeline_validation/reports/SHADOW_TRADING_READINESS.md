# SHADOW-TRADING READINESS (Phase 8/10)

**Experiment:** `exp_007_full_pipeline_validation` · harness `scripts/shadow_trader.py` ·
smoke output `data/shadow_smoke_ledger.csv`, `data/shadow_smoke_config.json`.
**SIMULATION ONLY — no broker connection, no live orders.**

## 1. What is built and verified [V]
- A self-contained **shadow-trading harness** (`shadow_trader.py`) that, given a daily weight feed and a
  per-asset return feed, logs a full hypothetical ledger: target weights, implied **orders**, modelled
  **fills** (price + slippage + commission), **positions**, gross/net **P&L**, cumulative **equity**, and
  **deviation vs the theoretical backtest**. Smoke-tested over the 2,558-day preserved book (ledger written,
  plumbing confirmed; the only steady-state deviation is the modelled cost drag the costless theory curve
  omits — ≈1.0e-2 cumulative, as expected).
- **Two hard safety guards:** `SIMULATION_ONLY = True` (not flippable from the file), and an automatic
  **refusal to run if any broker-like environment variable is present** (`BROKER`, `ALPACA`, `IB_`, `FIX_`,
  `API_SECRET`, …). The harness cannot reach a broker.
- A **frozen config object** (`ShadowConfig`) capturing commit, params, capital, cost/slippage, gross cap,
  borrow/financing stubs, and pre-registered stop rules.

## 2. Readiness checklist
| capability | status | note |
|---|---|---|
| Frozen strategy + commit pinning | **ready** | records SHA + params in config; pin at reviewed merge |
| Daily order/fill/position/P&L ledger | **ready [V]** | append-only CSV; smoke-tested |
| Deviation-vs-theory tracking | **ready [V]** | per-day normalized deviation column |
| Slippage/commission model | **ready** | 2 + 1 bps; matches P06 cost model |
| Gross-cap / exposure alerts | **ready** | fires if a day's gross > 1.30 |
| 1-day execution lag (no double-lag) | **ready** | weights pre-lagged; harness does not re-shift — the exact P06/P07 defect is avoided |
| **Live price/feature feed** | **NOT built [U]** | forward operation needs a daily vendor feed → P04 features → OLS blend; today the harness replays stored weights |
| **Per-asset cross-sectional return feed** | **partial [U]** | research stored portfolio-level returns; cross-sectional daily returns must be wired for true forward mode |
| **Short-locate / borrow feed** | **stub [U]** | logic + logging present; real locate/borrow-fee source not connected |
| **Financing-rate feed** | **stub [U]** | charged on gross>1.0; needs a real rate source (and only matters for Combined) |
| Broker execution | **intentionally absent** | out of scope; guarded against |

## 3. Gap to forward operation
To run prospectively, three feeds must be wired (code seams already exist): (1) a daily **market-data +
feature** pipeline feeding the frozen P04 OLS blend to produce each day's weights (replacing the replayed
feed); (2) a **cross-sectional per-asset return** feed for mark-to-market; (3) **borrow/financing** sources.
None require strategy changes — only data plumbing. Until wired, the harness is a faithful **replay** skeleton.

## Answer — Q7: Are V1 and DD Only operationally ready for controlled shadow/paper observation?
**Ready in logic and risk controls; not yet wired to live data.** The harness, ledger, deviation tracking,
cost model, execution-lag correctness and safety guards are built and tested **[V]**. Before a prospective
window can start, the three data feeds in §3 must be connected **[U]**. **V1 and DD Only are the two approved
candidates for such observation; Combined is excluded.** No broker execution and no real capital are enabled
or authorized by this readiness state.
