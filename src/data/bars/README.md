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

**Production-enablement verdict.** The alignment, realised-cadence, intraday, and
default-threshold prerequisites are all merged, so event bars can now run through
the real executor. A time-vs-event **comparison study** (`bar_comparison.py`,
`docs/BAR_ENGINE_PRODUCTION.md`) grades each type against the time baseline on
Sharpe / MDD / turnover / robustness. On the available (synthetic) evidence no
event bar is a *stable* improvement, so `PRODUCTION_BAR_TYPES` stays `{"time"}`:
promotion is now a one-line, study-backed flip rather than a leap of faith.

### Data-derived default thresholds (`defaults.py`)

Event builders need a `params["threshold"]`, but the executor hands the engine
only a bare bar-type string. When no threshold is supplied the engine derives a
**pooled default from the data** (`resolve_threshold` / `default_threshold`),
targeting `TARGET_BARS_PER_TICKER` bars per ticker:

```
tick    : Σ rows        / (n_tickers * target)   # rows per bar
volume  : Σ Volume      / (n_tickers * target)
dollar  : Σ Close*Volume/ (n_tickers * target)
```

Imbalance variants reuse their base weight's scale. An explicit threshold always
wins, so tuned runs never change. Pure and deterministic.

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

## Realised periods-per-year (`realized_periods_per_year`)

Risk-adjusted metrics annualise a per-period return series by a *periods-per-year*
factor (`sharpe = sqrt(ppy) * mean / std`). Daily time bars have a fixed cadence
of **252**; event bars close at **irregular, data-driven** timestamps, so
annualising them with 252 would misstate their metrics. Every event builder
therefore returns a **measured** cadence on `BarResult.periods_per_year`:

```python
ppy = DAYS_PER_YEAR * (Σ bar_intervals) / (Σ span_in_days)   # pooled across tickers
```

- **Time bars** keep the fixed **252** (or an explicit `SamplingSpec.periods_per_year`
  override) → the production path is byte-identical.
- **Event bars** report their realised cadence (typically well below 252, since
  each bar aggregates several daily rows). An explicit spec override always wins.
- Degenerate input (no ticker with ≥2 bars, or zero span) falls back to 252.

`event_periods_per_year(spec, bars)` is the single resolver the builders share.
The M7 executor consumes `BarResult.periods_per_year` and forwards it as a plain
float into the metrics path — it never inspects the clock, preserving
bar-agnosticism.

## Intraday input (genuine event bars)

The event builders treat **each input row as one atomic observation** and
accumulate a threshold across rows, so their finest resolution is the input
cadence. On daily OHLCV an event bar can therefore never close *within* a day.
Fed **intraday** observations (e.g. one row per minute) the same builders close
bars *inside* a session — exactly what event sampling is for — and
`realized_periods_per_year` measures the correspondingly higher cadence.

The Bar Engine itself does **no I/O**: it accepts any `ticker -> DataFrame` whose
index is a `DatetimeIndex`, daily or sub-daily alike. Intraday **ingestion** is a
separate concern in the executor's data layer
(`agents/experiment_runner/intraday_loader.py`, `load_intraday`) — the sub-daily
counterpart to the daily `load_data`. It reads timestamped CSVs into the same
shape the engine consumes; sampling stays entirely inside `BarEngine.build`, and
the daily/time production path is untouched.

## Module layout

| File | Responsibility |
| --- | --- |
| `base.py` | Vocabulary constants + immutable `SamplingSpec` / `BarResult`. |
| `validation.py` | `validate_bars` — structural checks (raise) + quality warnings (collect). |
| `time.py` | `build_time_bars` — identity pass-through clock. |
| `tick.py` / `volume.py` / `dollar.py` | Event-driven builders (BE-3). |
| `imbalance.py` | Tick/volume/dollar imbalance builders + tick rule (BE-4). |
| `align.py` | Cross-sectional alignment of irregular event bars onto a common grid. |
| `periods.py` | Realised periods-per-year cadence measured from bar-close timestamps. |
| `_aggregate.py` | Shared threshold + signed-imbalance assignment + OHLCV aggregation. |
| `defaults.py` | Data-derived default thresholds so event bars run from a bare bar-type string. |
| `builder.py` | `BarEngine.build` — total dict dispatch + production gate + spec coercion. |
| `__init__.py` | Public surface. |
