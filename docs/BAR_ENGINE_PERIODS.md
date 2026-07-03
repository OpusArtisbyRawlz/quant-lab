# Prerequisite #2 — Realised Periods-Per-Year for Metrics

Branch: `feat/m11-bar-engine-periods`
Scope: give the Bar Engine a **measured** annualisation cadence for irregular
event bars, and thread it through the executor's metrics path. Pure function +
synthetic-data unit tests. **No production enablement**; the time-bar path is
byte-identical.

This is the second of the three prerequisites required before event bars can be
enabled for real campaigns (the others: cross-sectional alignment — done in
Prerequisite #1; intraday data ingestion — still open).

---

## 1. The problem

Risk-adjusted metrics annualise a per-period return series by a
*periods-per-year* factor:

```
sharpe = sqrt(ppy) * mean(returns) / std(returns)
annualized_vol = std(returns) * sqrt(ppy)
```

Daily time bars have a well-known cadence of **252** trading periods per year,
which was hardcoded (`CostConfig.periods_per_year = 252`) and used for every run.
Event bars (tick / volume / dollar / imbalance) close at **irregular,
data-driven** timestamps — far fewer bars in quiet stretches, more when the
market is active. Annualising, say, 40 volume bars with 252 would drastically
overstate their Sharpe. The cadence is a **property of the bars**, so the Bar
Engine — which owns all sampling logic — should measure and report it.

## 2. The solution — `realized_periods_per_year`

New module `src/data/bars/periods.py`:

```python
realized_periods_per_year(bars: dict[str, DataFrame], *, default=252.0) -> float
```

For each ticker with sorted bar-close timestamps `t_0 < … < t_{n-1}` there are
`n-1` intervals spanning `t_{n-1} - t_0` of calendar time. The panel-level
cadence **pools** these across tickers:

```
ppy = 365.25 * (Σ intervals) / (Σ span_in_days)
```

Pooling weights each ticker by the calendar span it contributes and is robust to
a ticker that produced a single bar (it adds zero intervals and zero span). When
no interval exists to measure (empty input, or every ticker has ≤1 bar) the
`default` (252) is returned.

`event_periods_per_year(spec, bars)` is the shared resolver the event builders
call: an explicit `SamplingSpec.periods_per_year` override always wins, otherwise
the cadence is measured from the produced bars.

## 3. Architectural placement

- Cadence measurement is **sampling-adjacent logic and lives in the Bar Engine**,
  consistent with "the Bar Engine owns all sampling logic."
- **Time bars keep the fixed 252** (or an explicit override) — they do *not* call
  the resolver — so the production path is byte-identical.
- **Event builders** (`tick` / `volume` / `dollar` + the three imbalance
  builders) now return `event_periods_per_year(spec, out)` instead of the 252
  placeholder, so their realised cadence rides on `BarResult.periods_per_year`.
- The **M7 executor stays bar-agnostic**: `runner.py` reads
  `bar_result.periods_per_year` and forwards it as a plain float into
  `build_metric_bundle`, `parameter_sensitivity`, and `build_robustness_report`.
  It never inspects the clock, so the `test_executor_bar_agnostic.py` AST guard
  is untouched. For time bars this float is 252 — identical to the historical
  default — so existing (time) experiments are unchanged.

## 4. Verification report

`agents/tests/test_bar_periods.py` (14 tests):

- **Correctness** — pooled bars-per-year on hand-built grids (5 bars over 1 year
  → 4/yr; two tickers pooled → 1.5/yr); ~252 business days annualises near-252
  but *not* exactly (proving it is measured, not the constant).
- **Resolver** — explicit override wins; otherwise measured.
- **Identity** — time bars report exactly 252 via `BarResult`; explicit override
  respected.
- **Event bars** — tick / volume / dollar / imbalance all report a realised
  cadence `0 < ppy < 252` that matches an independent measurement of the produced
  bars; override flows through `BarEngine.build`.
- Purity (no input mutation), determinism, degenerate-input fallback.

The runner's existing time-bar tests continue to pass unchanged, confirming the
252 path is byte-identical.

### Suite results

```
agents/tests/test_bar_periods.py     14 passed
agents/tests/ (full)                 884 passed, 1 skipped in 10.56s
```

870 (post-alignment) + 14 new = **884 passed, 0 regressions.**

## 5. Remaining prerequisite (still open)

3. **Intraday data ingestion** — genuine event bars need trade/intraday data;
   today's builders operate on one-observation-per-day daily OHLCV.

Only after this, plus promoting a type from `IMPLEMENTED_BAR_TYPES` into
`PRODUCTION_BAR_TYPES`, is production enablement reviewable.

---

**Prerequisite #2 complete. Realised cadence implemented in the Bar Engine,
tested, identity-safe for the production path, and threaded through the executor
bar-agnostically. Stopping for review.**
