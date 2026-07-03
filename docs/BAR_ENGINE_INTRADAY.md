# Prerequisite #3 — Intraday Data Ingestion

Branch: `feat/m11-bar-engine-intraday`
Scope: add a sub-daily ingestion path so the event-bar builders receive genuine
intraday observations, and prove the three prerequisites compose. Loader +
synthetic-data unit tests only. **No production enablement**; the daily/time path
is byte-identical.

This is the last of the three prerequisites required before event bars can be
enabled for real campaigns (the others — cross-sectional alignment and realised
periods-per-year — landed in Prerequisites #1 and #2).

---

## 1. The problem

The tick / volume / dollar / imbalance builders accumulate a threshold across
input rows, treating **each row as one atomic observation**. Their finest
possible resolution is therefore the input cadence. Today's data is **daily**
OHLCV — one observation per day — so an "event" bar can never close *within* a
day; a volume bar is really just a multi-day roll-up. Genuine event bars need
**intraday** observations (e.g. one row per minute) so a bar can close several
times inside a single busy session.

The gap was purely one of **ingestion**: nothing loaded sub-daily data into the
`ticker -> DataFrame` shape the engine consumes. The daily
`agents/experiment_runner/data_loader.py` parses a bare `Date` column and yields
a calendar-date index.

## 2. The solution — `load_intraday`

New module `agents/experiment_runner/intraday_loader.py`:

```python
load_intraday(universe_dir: Path) -> DataBundle
```

The sub-daily counterpart to `load_data`. It reads per-ticker intraday CSVs into
the identical `ticker -> DataFrame` shape, the only difference being a full
**timestamp** (date + time) `DatetimeIndex` named `"Timestamp"` instead of a bare
date. It:

- detects the timestamp from a single date+time column (`Timestamp` / `Datetime`
  / …), a `Date` + `Time` pair, or a bare `Date` that itself carries a time —
  case-insensitive, deterministic;
- consumes those source columns, preserves OHLCV, adds a `ticker` column, sorts
  the index;
- degrades gracefully — empty / missing-`Close` / no-timestamp / malformed files
  are skipped with a warning, never aborting the batch (same contract as the
  daily loader).

## 3. Architectural placement

- Intraday loading is **I/O / ingestion, not sampling**. All sampling logic stays
  inside `BarEngine.build`; the loader never aggregates or resamples — it hands
  raw rows over. This keeps "the Bar Engine owns all sampling logic" intact.
- The engine itself already accepts any `DatetimeIndex`, daily or sub-daily, so
  **no engine code changed** — the event builders are cadence-agnostic by
  construction. The prerequisite is satisfied entirely by the new ingestion path
  plus tests that prove the composition.
- The loader lives in the executor's data layer (only `agents/experiment_runner/`
  may import from `src/`; this loader imports nothing from `src`).
- Purely **additive**: the daily `load_data` path and the time-bar production
  path are byte-identical.

## 4. Verification report

`agents/tests/test_intraday_loader.py` (14 tests) — loader unit tests:
timestamp-column / `Date`+`Time` / alias parsing, sub-daily sorted index,
OHLCV+ticker preserved, source column consumed, determinism, and the full
graceful-degradation matrix (missing dir, empty dir, missing `Close`, no
timestamp, malformed, partial batch).

`agents/tests/test_intraday_bars.py` (7 tests) — the composition, on the engine:

- **Genuine sub-daily bars** — intraday volume bars close *multiple times per
  calendar date*; the daily-data contrast closes zero times within a day.
- **#2 composes** — the realised cadence of intraday event bars is far above 252
  and matches an independent measurement.
- **#1 composes** — irregular intraday event bars align onto one shared intraday
  grid.
- **Production path** — time bars on intraday input are identity (252, frames
  unchanged).
- **End-to-end** — `load_intraday` output feeds `BarEngine.build` directly.

### Suite results

```
agents/tests/test_intraday_loader.py + test_intraday_bars.py   21 passed
agents/tests/ (full)                                           907 passed, 1 skipped
```

886 (post-#2) + 21 new = **907 passed, 0 regressions.**

## 5. Prerequisites status

1. Cross-sectional alignment for irregular event bars — **done (PR #29).**
2. Realised periods-per-year for metrics — **done (PR #30).**
3. Intraday data ingestion — **done (this PR).**

All three prerequisites are now satisfied. Production enablement — promoting a
type from `IMPLEMENTED_BAR_TYPES` into `PRODUCTION_BAR_TYPES` and letting a real
campaign request it without `allow_experimental=True` — remains a **separate,
gated PR** for review; it is deliberately not part of this change.

---

**Prerequisite #3 complete. Intraday ingestion implemented, tested, and shown to
make event bars genuinely sub-daily while composing with alignment and realised
cadence. Daily/time path untouched. Stopping for review.**
