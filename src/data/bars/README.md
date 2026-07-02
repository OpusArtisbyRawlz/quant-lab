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
IMPLEMENTED_BAR_TYPES = frozenset({"time"})   # BE-1
```

Dispatch is **total** over the recognised vocabulary:
- a recognised-but-unimplemented type → `NotImplementedError` (never silently wrong)
- an unrecognised type → rejected at `SamplingSpec` construction (`ValueError`)

## BE-1 scope

BE-1 ships **identity / time sampling only**. Daily OHLCV is already
time-sampled, so time bars are a faithful, unmutated pass-through (each frame
deep-copied). This guarantees byte-identical downstream results vs. the
pre-engine pipeline — the contract that lets a later PR wire the engine into the
M7 executor with **zero behavioural change**.

Calendar down-sampling (`freq`) and all non-time bar builders are deliberate
non-goals for BE-1 and raise `NotImplementedError`.

## Module layout

| File | Responsibility |
| --- | --- |
| `base.py` | Vocabulary constants + immutable `SamplingSpec` / `BarResult`. |
| `validation.py` | `validate_bars` — structural checks (raise) + quality warnings (collect). |
| `time.py` | `build_time_bars` — identity pass-through clock. |
| `builder.py` | `BarEngine.build` dispatch + spec coercion. |
| `__init__.py` | Public surface. |
