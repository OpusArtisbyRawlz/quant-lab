# BE-4 — Bar Engine: Imbalance Bars (tick / volume / dollar imbalance)

Branch: `feat/m11-bar-engine-be4`
Scope: implement the imbalance-bar family **inside the engine**, deterministic
synthetic-data unit tests only. **Not enabled for real campaigns.** Same
architectural boundaries as BE-2/BE-3; production gating stays in the engine.

---

## 1. What shipped

- `src/data/bars/imbalance.py` — `tick_signs` (the tick rule) plus
  `build_tick_imbalance_bars`, `build_volume_imbalance_bars`,
  `build_dollar_imbalance_bars`.
- `src/data/bars/_aggregate.py` — new `assign_imbalance_bars` (signed
  accumulation, closes on `|acc| >= threshold`), reusing the existing
  `aggregate_by_bar_id`.
- `base.py`: `IMPLEMENTED_BAR_TYPES` now equals the whole `BAR_TYPES`
  vocabulary. `PRODUCTION_BAR_TYPES` is unchanged (`{time}`).
- `builder.py`: three new entries in the `_BUILDERS` dispatch table.
- Tests: `agents/tests/test_imbalance_bars.py` (22 tests); minor updates to
  `test_bar_engine.py` (vocabulary now fully implemented; the
  "recognised-but-unimplemented" parametrized test skips cleanly since that set
  is now empty).

## 2. The algorithm

Sign each row by the **tick rule**:

```
b_t = +1 if Close_t > Close_{t-1}
      -1 if Close_t < Close_{t-1}
      b_{t-1} if unchanged           (b_0 = +1)
```

Per-row signed weight, then close a bar when `|Σ weight|` since the last bar
reaches `params["threshold"]`:

| Type | Weight |
| --- | --- |
| `tick_imbalance` | `b_t` |
| `volume_imbalance` | `b_t * Volume` |
| `dollar_imbalance` | `b_t * Close * Volume` |

Constituent rows aggregate to one OHLCV bar (Open=first, High=max, Low=min,
Close=last, Volume=sum) stamped at the closing timestamp; trailing rows form a
partial bar. **Fixed-threshold** formulation — pure and deterministic. Adaptive
EWMA thresholding (AFML) is a documented non-goal (it carries cross-bar state).

## 3. "Not enabled for real campaigns" — unchanged enforcement

Identical to BE-3: `BarEngine.build` honours `PRODUCTION_BAR_TYPES` by default.
The M7 executor calls it with the default, so any imbalance request on a real
campaign returns a recorded `NotImplementedError` — never a silently-wrong
backtest. Unit tests pass `allow_experimental=True`. The gate lives entirely
inside the engine; the executor call site is untouched and the
`test_executor_bar_agnostic.py` AST guard still passes.

## 4. Verification report

### 4.1 Correctness (hand-checked fixtures)

`test_imbalance_bars.py` uses a 6-row close path `10,11,10,9,12,13` with known
tick signs `+1,+1,-1,-1,+1,+1` and flat volume, so tick / volume / dollar
imbalance boundaries and their OHLCV aggregates are asserted against arithmetic
done by hand. The tick rule itself (including the carry-on-no-change case) is
unit-tested directly. Plus: production gate, OHLCV invariants (High≥Low,
monotonic unique index, positive volume), volume conservation, determinism,
no-mutation, partial-final-bar, and parameter validation.

### 4.2 Suite results

```
agents/tests/test_imbalance_bars.py   22 passed
agents/tests/ (full)                  859 passed, 1 skipped in 10.71s
```

837 (post-BE-3) + 22 new = **859 passed, 0 regressions.** The 1 skip is the
now-empty "recognised-but-unimplemented" parametrization — expected, since BE-4
completes the vocabulary. Executor and every real-campaign path behave
identically.

## 5. Boundaries preserved

No agent/executor logic changed. Edits outside `src/data/bars/` are one new test
file plus small updates to an existing test. M9, approval gate, reporting,
deterministic replay, campaign architecture, cost model: untouched.

### Deferred (future work)

- Adaptive/EWMA imbalance thresholding (AFML) as optional `params`.
- Enabling any event/imbalance bar for real campaigns — still needs
  cross-sectional alignment for irregular per-ticker bars and realised-cadence
  annualisation (`BarResult.periods_per_year` hook), plus an explicit promotion
  of the type from `IMPLEMENTED_BAR_TYPES` into `PRODUCTION_BAR_TYPES`.

---

**BE-4 complete. The full bar-type vocabulary is now implemented and
unit-tested; only time is production-enabled. Stopping for review.**
