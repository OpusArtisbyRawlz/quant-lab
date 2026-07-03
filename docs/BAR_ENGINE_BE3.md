# BE-3 — Bar Engine: Tick / Volume / Dollar Sampling Algorithms

Branch: `feat/m11-bar-engine-be3`
Scope: implement the count/volume/dollar event-bar algorithms **inside the
engine**, with synthetic-data deterministic unit tests only. **Not enabled for
real campaigns.** Same architectural boundaries as BE-2.

---

## 1. What shipped

New engine modules:
- `src/data/bars/_aggregate.py` — shared threshold-assignment + OHLCV aggregation.
- `src/data/bars/tick.py` — `build_tick_bars` (every N rows → one bar).
- `src/data/bars/volume.py` — `build_volume_bars` (accumulate `Volume`).
- `src/data/bars/dollar.py` — `build_dollar_bars` (accumulate `Close * Volume`).

Engine wiring:
- `base.py`: `IMPLEMENTED_BAR_TYPES` = `{time, tick, volume, dollar}`; new
  `PRODUCTION_BAR_TYPES` = `{time}`.
- `builder.py`: replaced the single-call dispatch with a **total dict dispatch
  table** `_BUILDERS` (no `if/elif` chains) and added an `allow_experimental`
  gate.
- `__init__.py`: export `PRODUCTION_BAR_TYPES`.

Tests:
- `agents/tests/test_event_bars.py` — 23 deterministic unit tests on synthetic data.
- `agents/tests/test_bar_engine.py` — updated the BE-1 "time is the only
  implemented type" assertion to the BE-3 two-tier reality.

## 2. The algorithms (daily OHLCV input)

Each input row is one atomic observation. A bar closes when an accumulator
crosses `params["threshold"]`; its rows aggregate to one OHLCV bar
(Open=first, High=max, Low=min, Close=last, Volume=sum), stamped at the closing
timestamp. Trailing rows below the threshold form a final partial bar.

| Type | Accumulator | `threshold` |
| --- | --- | --- |
| `tick` | row count | rows per bar (int) |
| `volume` | `Volume` | volume per bar |
| `dollar` | `Close * Volume` | value per bar |

All three are **pure and deterministic**: no randomness, no I/O, no mutation of
the caller's frames (verified by tests).

## 3. "Not enabled for real campaigns" — how it's enforced

`BarEngine.build` has two gates:

1. `spec.type not in IMPLEMENTED_BAR_TYPES` → `NotImplementedError` (no builder).
2. `not allow_experimental and spec.type not in PRODUCTION_BAR_TYPES` →
   `NotImplementedError` (implemented but production-disabled).

The M7 executor calls `BarEngine.build(data_dict, spec.bar_type)` with the
**default** `allow_experimental=False`. So a real campaign that varied to
`volume`/`dollar`/`tick` gets a recorded experiment failure — never a silently
wrong event-bar backtest. Unit tests pass `allow_experimental=True` to exercise
the algorithms.

This gate lives entirely **inside the engine**. The executor call site is
unchanged from BE-2 and still never branches on a bar type — the
`test_executor_bar_agnostic.py` AST guard continues to pass.

## 4. Verification report

### 4.1 Correctness (hand-checkable fixtures)

`test_event_bars.py` includes a 6-row hand-made frame with known values so tick
(N=3, N=4), volume (threshold 250), and dollar (threshold 2300) boundaries and
their OHLCV aggregates are asserted against arithmetic done by hand. Plus:
determinism, no-mutation, OHLCV invariants (High≥Low, monotonic unique index,
positive volume), total-volume conservation, and parameter validation
(missing / non-positive threshold → `ValueError`).

### 4.2 Production gate

`test_event_bars_blocked_without_experimental_flag` asserts default `build`
**raises** for tick/volume/dollar and only runs with `allow_experimental=True`.

### 4.3 Suite results

```
agents/tests/test_event_bars.py    23 passed
agents/tests/test_bar_engine.py    21 passed
agents/tests/ (full)               837 passed in 10.32s
```

814 (post-BE-2) + 23 new = **837 passed, 0 regressions.** The executor and every
real-campaign path are behaviourally unchanged.

## 5. Boundaries preserved

No agent/executor logic changed. The only edits outside `src/data/bars/` are two
new test files and one updated assertion. M9, approval gate, reporting,
deterministic replay, campaign architecture, cost model: untouched.

### Deferred (not BE-3)

- Imbalance bars (tick/volume/dollar imbalance) — still `NotImplementedError`.
- Enabling event bars for real campaigns: needs cross-sectional alignment for
  per-ticker irregular bars and realised-cadence annualisation
  (`BarResult.periods_per_year` is the hook). That is a later PR + an explicit
  move of a type from `IMPLEMENTED_BAR_TYPES` into `PRODUCTION_BAR_TYPES`.

---

**BE-3 complete. Event-bar algorithms implemented and unit-tested; disabled for
real campaigns. Stopping for review.**
