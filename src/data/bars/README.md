# Bar Engine (`src/data/bars/`)

A deterministic, reusable market-sampling module. It converts raw OHLCV data
into "bars" sampled on a chosen clock (time, and — in later PRs — tick / volume /
dollar / imbalance). It is **execution-layer infrastructure, not an agent**: it
makes no decisions, holds no state, performs no I/O, and depends on nothing in
the agent, M9, or M10 layers.

```python
from src.data.bars import BarEngine, SamplingSpec

result = BarEngine.build(raw_data, SamplingSpec(type="time"))
bars = result.data                 # dict[ticker -> DataFrame]
ppy  = result.periods_per_year     # annualisation cadence (252 for daily)
```

## Design contract

The engine is a **pure, deterministic function**:

- same inputs → identical `BarResult` (verified by `test_build_is_deterministic`)
- no I/O, no randomness, no hidden/global state
- never mutates the caller's `raw_data` (verified by `test_build_does_not_mutate_input`)
- unit-testable and reusable by every research project

## Public API

| Symbol | Purpose |
| --- | --- |
| `BarEngine.build(raw_data, sampling_spec=None)` | The single entry point. Returns a `BarResult`. |
| `build(raw_data, sampling_spec=None)` | Module-level convenience wrapper. |
| `SamplingSpec(type, params, periods_per_year)` | Immutable, future-proof sampling configuration. |
| `BarResult(data, periods_per_year, sampling_spec, diagnostics)` | Immutable result bundle. |
| `validate_bars(data)` | Structural validation + non-fatal quality diagnostics. |
| `BarValidationError` | Raised on structural violations. |

`sampling_spec` accepts a `SamplingSpec`, a bare bar-type **string**, or `None`
(→ time). All three are equivalent for time bars.

### Why `SamplingSpec` and not a bare string?

The API is designed around a **configuration object** so future sampling
algorithms (run bars, range bars, renko, adaptive, information-driven, custom
research bars) slot in through `params` / new `type` values **without an API
redesign**. BE-1 stores only `bar_type` upstream (ExperimentSpec/config), but
the engine itself is already spec-shaped.

## Vocabulary

```python
BAR_TYPES = ("time","tick","volume","dollar",
             "tick_imbalance","volume_imbalance","dollar_imbalance")
IMPLEMENTED_BAR_TYPES = frozenset(BAR_TYPES)   # BE-4: whole vocabulary has a builder
PRODUCTION_BAR_TYPES  = frozenset({"time"})    # real-campaign gate
```

Dispatch is **total** over the recognised vocabulary:
- every recognised type has a builder; a non-production one still raises
  `NotImplementedError` unless `allow_experimental=True`
- an unrecognised type → rejected at `SamplingSpec` construction (`ValueError`)

### Two-tier gating: implemented vs production-enabled

`IMPLEMENTED_BAR_TYPES` is what the engine *can build*; `PRODUCTION_BAR_TYPES` is
what real callers *may build*. `BarEngine.build(...)` honours the production gate
by default, so the M7 executor (and any real campaign) can only ever produce
time bars today. The BE-3 event bars (tick / volume / dollar) are fully
implemented and unit-tested but require an explicit opt-in:

```python
BarEngine.build(raw, SamplingSpec("volume", params={"threshold": 2_000_000}))              # NotImplementedError
BarEngine.build(raw, SamplingSpec("volume", params={"threshold": 2_000_000}),
                allow_experimental=True)                                                    # runs
```

This keeps event bars out of real backtests until their cross-sectional
alignment and annualisation story lands in a later PR — without the executor
ever knowing individual bar types exist.

### Event-bar algorithms (BE-3)

Input is daily OHLCV, so each row is one atomic observation. A bar closes when an
accumulator crosses `params["threshold"]`; constituent rows aggregate to one
OHLCV bar (Open=first, High=max, Low=min, Close=last, Volume=sum, stamped at the
closing timestamp). Trailing rows below the threshold form a final partial bar.

| Type | Accumulator | `threshold` meaning |
| --- | --- | --- |
| `tick` | row count | rows per bar (int) |
| `volume` | `Volume` | traded volume per bar |
| `dollar` | `Close * Volume` | traded value per bar |

### Imbalance bars (BE-4)

Each row is signed by the **tick rule** (`b_t = sign(ΔClose)`, carrying the prior
sign on no change, `b_0 = +1`). A bar closes when the **absolute signed
imbalance** since the last bar crosses `params["threshold"]`:

| Type | Signed per-row weight |
| --- | --- |
| `tick_imbalance` | `b_t` |
| `volume_imbalance` | `b_t * Volume` |
| `dollar_imbalance` | `b_t * Close * Volume` |

This is the **fixed-threshold** formulation — pure and deterministic. Adaptive
(EWMA expected-imbalance) thresholding from AFML carries estimation state across
bars and is a deliberate non-goal; it can later arrive as extra `params` without
changing the call shape.

## BE-1 scope

BE-1 ships **identity / time sampling only**. Daily OHLCV is already
time-sampled, so time bars are a faithful, unmutated pass-through (each frame
deep-copied). This guarantees byte-identical downstream results vs. the
pre-engine pipeline — the contract that lets a later PR wire the engine into the
M7 executor with **zero behavioural change**.

Calendar down-sampling (`freq`) and all non-time bar builders are deliberate
non-goals for BE-1 and raise `NotImplementedError`.

## Cross-sectional alignment (`align_cross_section`)

The cross-sectional alpha pipeline ranks peers per shared `Date`
(`groupby("Date")`). Time bars share a daily grid so this works directly; event
bars close at **per-ticker, irregular** timestamps and would collapse each group
to ~one ticker. `align_cross_section(bars, method="asof")` fixes this:

```python
from src.data.bars import BarEngine, SamplingSpec, align_cross_section

bars = BarEngine.build(raw, SamplingSpec("volume", params={"threshold": 3_000_000}),
                       allow_experimental=True).data
aligned = align_cross_section(bars)   # every ticker now shares one union grid
```

- **Union grid** = sorted union of all tickers' bar-close timestamps.
- **As-of / forward-fill**: at grid time `t`, each ticker takes its most recently
  *closed* bar at or before `t` (no lookahead). Points before a ticker's first
  bar are `NaN`.

It is a **pure** function and, for already-aligned gap-free time bars, the
**identity** — so the current production path is unaffected. It is **not**
auto-applied inside `BarEngine.build`; it is the alignment layer the event-bar
path will use once those bars are production-enabled (a separate prerequisite).

## Module layout

| File | Responsibility |
| --- | --- |
| `base.py` | Vocabulary constants + immutable `SamplingSpec` / `BarResult`. |
| `validation.py` | `validate_bars` — structural checks (raise) + quality warnings (collect). |
| `time.py` | `build_time_bars` — identity pass-through clock. |
| `tick.py` / `volume.py` / `dollar.py` | Event-driven builders (BE-3). |
| `imbalance.py` | Tick/volume/dollar imbalance builders + tick rule (BE-4). |
| `align.py` | Cross-sectional alignment of irregular event bars onto a common grid. |
| `_aggregate.py` | Shared threshold + signed-imbalance assignment + OHLCV aggregation. |
| `builder.py` | `BarEngine.build` — total dict dispatch + production gate + spec coercion. |
| `__init__.py` | Public surface. |
