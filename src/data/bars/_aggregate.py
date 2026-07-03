"""
bars._aggregate — shared, deterministic OHLCV aggregation for event bars.

Tick / volume / dollar bars all reduce to the same two-step recipe:

1. **Assign** each input row to an integer bar index according to an
   accumulator that resets when a threshold is crossed
   (count for tick bars, ``Volume`` for volume bars, ``Close * Volume`` for
   dollar bars).
2. **Aggregate** the rows of each bar into one OHLCV row:
   ``Open`` = first, ``High`` = max, ``Low`` = min, ``Close`` = last,
   ``Volume`` = sum, stamped at the bar's closing timestamp.

Both steps are pure and deterministic: no randomness, no I/O, no mutation of the
caller's frame. The accumulation walk is an explicit left-to-right loop so the
bar boundaries are unambiguous and reproducible (data volumes here are small).

BE-3 note: the input is daily OHLCV, so each row is treated as one atomic
observation ("one tick"). These builders are unit-tested on synthetic data but
are NOT enabled for real campaigns (see ``PRODUCTION_BAR_TYPES``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import REQUIRED_COLUMNS


def assign_threshold_bars(values: np.ndarray, threshold: float) -> np.ndarray:
    """Map a 1-D array of per-row weights to contiguous integer bar ids.

    Walking left to right, weights accumulate; the row that brings the running
    total to ``>= threshold`` closes the current bar, and accumulation resets.
    Rows after the final crossing form a trailing (partial) bar. The result is a
    non-decreasing array of bar ids starting at 0, one per input row.

    A non-positive threshold is rejected by the callers before reaching here.
    """
    bar_ids = np.empty(len(values), dtype=np.int64)
    acc = 0.0
    cur = 0
    for i, v in enumerate(values):
        acc += float(v)
        bar_ids[i] = cur
        if acc >= threshold:
            cur += 1
            acc = 0.0
    return bar_ids


def assign_imbalance_bars(signed_values: np.ndarray, threshold: float) -> np.ndarray:
    """Map a 1-D array of *signed* per-row weights to contiguous bar ids.

    Identical accumulation walk to :func:`assign_threshold_bars`, but the bar
    closes when the **absolute** running imbalance reaches ``threshold`` — the
    accumulator can move in either direction and only its magnitude triggers a
    boundary. Trailing rows below the threshold form a final (partial) bar.

    A non-positive threshold is rejected by the callers before reaching here.
    """
    bar_ids = np.empty(len(signed_values), dtype=np.int64)
    acc = 0.0
    cur = 0
    for i, v in enumerate(signed_values):
        acc += float(v)
        bar_ids[i] = cur
        if abs(acc) >= threshold:
            cur += 1
            acc = 0.0
    return bar_ids


def aggregate_by_bar_id(df: pd.DataFrame, bar_ids: np.ndarray) -> pd.DataFrame:
    """Reduce ``df`` (OHLCV, DatetimeIndex) to one OHLCV row per bar id.

    The output is indexed by each bar's **closing** timestamp (the index of the
    last constituent row), with the index name preserved. Only the required
    OHLCV columns are produced.
    """
    idx_name = df.index.name or "Date"
    work = df.copy()
    work["_bar_id"] = bar_ids
    work["_ts"] = df.index

    grouped = work.groupby("_bar_id", sort=True)
    out = pd.DataFrame({
        "Open":   grouped["Open"].first(),
        "High":   grouped["High"].max(),
        "Low":    grouped["Low"].min(),
        "Close":  grouped["Close"].last(),
        "Volume": grouped["Volume"].sum(),
    })
    out.index = pd.DatetimeIndex(grouped["_ts"].last().values, name=idx_name)
    return out[list(REQUIRED_COLUMNS)]
