# Prerequisite #1 — Cross-Sectional Alignment for Irregular Event Bars

Branch: `feat/m11-bar-engine-alignment`
Scope: give the Bar Engine a deterministic way to align irregular, per-ticker
event bars onto a common grid for cross-sectional ranking. Pure function +
synthetic-data unit tests only. **No production enablement**; the current
time-bar path is byte-identical.

This is the first of the three prerequisites required before event bars can be
enabled for real campaigns (the other two: realized periods-per-year for
metrics; intraday data ingestion).

---

## 1. The problem

`src/pipelines/cross_sectional.py` ranks peers per shared timestamp:

```python
panel["signal_rank"] = panel.groupby("Date")["signal"].rank(pct=True)
```

Time bars share one daily grid, so each `Date` group holds one row per ticker.
Event bars (tick/volume/dollar/imbalance) close at **per-ticker, irregular**
timestamps — different tickers cross their thresholds on different days — so a
naive stack-and-group would leave ~one ticker per group and there would be no
cross-section to rank.

## 2. The solution — `align_cross_section`

New module `src/data/bars/align.py`:

```python
align_cross_section(bars: dict[str, DataFrame], *, method="asof") -> dict[str, DataFrame]
```

1. **Union grid** — the sorted union of every ticker's bar-close timestamps.
2. **As-of reindex** — each ticker is forward-filled onto the grid: at grid time
   `t` it takes its most recently *closed* bar at or before `t`. No lookahead.
   Grid points before a ticker's first bar are `NaN` (that ticker is simply not
   in the cross-section yet).

Output: every ticker shares the identical grid index, so
`build_market_panel` + `groupby("Date")` recovers a full peer group at each grid
point. `method` is a small vocabulary (`("asof",)`) so future strategies
(intersection, interpolation) slot in without changing the signature.

## 3. Architectural placement

- Alignment is **sampling-adjacent logic and lives in the Bar Engine**, not in
  the pipeline or the executor — consistent with "the Bar Engine owns all
  sampling logic."
- It is a **standalone pure function**, deliberately **not** auto-applied inside
  `BarEngine.build`. Wiring it into an execution path happens only at
  production-enablement time (a separate, gated PR), so the executor boundary and
  the `test_executor_bar_agnostic.py` guard are untouched here.
- For gap-free daily **time** bars the union grid is the existing grid and the
  forward-fill is the identity → the production path is byte-identical.

## 4. Verification report

`agents/tests/test_bar_alignment.py` (11 tests):

- **Identity** — `align_cross_section` returns time bars unchanged
  (`assert_frame_equal`), and `run_market_alpha_pipeline` is **byte-identical**
  before vs. after alignment for time bars.
- **Correctness** — hand-built irregular example (ticker A closes 04/06/08,
  B closes 05/06/07): union grid = 04..08; forward-filled Closes checked exactly;
  leading `NaN` before a ticker's first bar; full 2-ticker cross-section from the
  first overlapping grid point.
- **No lookahead** — every aligned value equals a bar that closed at or before
  its grid timestamp.
- Purity (no input mutation), determinism, unknown-method rejection, empty input.
- **On real engine output** — volume bars (which close on genuinely different
  per-ticker dates) all share one grid after alignment.

### Suite results

```
agents/tests/test_bar_alignment.py   11 passed
agents/tests/ (full)                 870 passed, 1 skipped in 10.41s
```

859 (post-BE-4) + 11 new = **870 passed, 0 regressions.**

## 5. Remaining prerequisites (still open)

2. **Realized periods-per-year for metrics** — consume
   `BarResult.periods_per_year` instead of the hardcoded 252 in `cost_model.py`.
3. **Intraday data ingestion** — genuine event bars need trade/intraday data;
   today's builders operate on one-observation-per-day daily OHLCV.

Only after all three, plus promoting a type from `IMPLEMENTED_BAR_TYPES` into
`PRODUCTION_BAR_TYPES`, is production enablement reviewable.

---

**Prerequisite #1 complete. Alignment implemented, tested, identity-safe for the
production path, and not wired into execution. Stopping for review.**
