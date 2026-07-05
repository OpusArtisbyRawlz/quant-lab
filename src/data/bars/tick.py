"""
bars.tick — tick (count) bars.

A tick bar closes after a fixed number of observations. With daily OHLCV input
each row is one observation, so a tick bar of threshold ``N`` aggregates every
``N`` consecutive rows into one OHLCV bar. The final group may hold fewer than
``N`` rows (a trailing partial bar).

Deterministic and pure: same input + same ``threshold`` → identical bars.

BE-3: implemented and unit-tested on synthetic data, but not production-enabled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import SamplingSpec
from ._aggregate import aggregate_by_bar_id
from .periods import event_periods_per_year
from .defaults import resolve_threshold


def _threshold(spec: SamplingSpec, raw_data: dict[str, pd.DataFrame]) -> int:
    """Explicit ``params['threshold']`` if given, else a data-derived default."""
    thr = int(resolve_threshold("tick", spec.param("threshold"), raw_data))
    if thr <= 0:
        raise ValueError(f"tick threshold must be a positive integer, got {thr}")
    return thr


def build_tick_bars(
    raw_data: dict[str, pd.DataFrame], spec: SamplingSpec
) -> tuple[dict[str, pd.DataFrame], float]:
    """Group every ``threshold`` rows per ticker into one OHLCV bar."""
    thr = _threshold(spec, raw_data)
    out: dict[str, pd.DataFrame] = {}
    for ticker, df in raw_data.items():
        bar_ids = np.arange(len(df), dtype=np.int64) // thr
        out[ticker] = aggregate_by_bar_id(df, bar_ids)
    return out, event_periods_per_year(spec, out)
