"""
bars.dollar — dollar (value) bars.

A dollar bar closes once the cumulative traded *value* since the last bar
reaches a threshold, where per-row value is approximated as ``Close * Volume``
(the standard proxy when only OHLCV is available). Dollar bars normalise for
price level over time better than volume bars. The trailing rows below the
threshold form a final partial bar.

Deterministic and pure: same input + same ``threshold`` → identical bars.

BE-3: implemented and unit-tested on synthetic data, but not production-enabled.
"""

from __future__ import annotations

import pandas as pd

from .base import SamplingSpec
from ._aggregate import assign_threshold_bars, aggregate_by_bar_id
from .periods import event_periods_per_year
from .defaults import resolve_threshold


def _threshold(spec: SamplingSpec, raw_data: dict[str, pd.DataFrame]) -> float:
    """Explicit ``params['threshold']`` if given, else a data-derived default."""
    thr = resolve_threshold("dollar", spec.param("threshold"), raw_data)
    if thr <= 0:
        raise ValueError(f"dollar threshold must be positive, got {thr}")
    return thr


def build_dollar_bars(
    raw_data: dict[str, pd.DataFrame], spec: SamplingSpec
) -> tuple[dict[str, pd.DataFrame], float]:
    """Accumulate ``Close * Volume`` per ticker; emit a bar each time it crosses ``threshold``."""
    thr = _threshold(spec, raw_data)
    out: dict[str, pd.DataFrame] = {}
    for ticker, df in raw_data.items():
        value = (df["Close"].to_numpy(dtype=float) * df["Volume"].to_numpy(dtype=float))
        bar_ids = assign_threshold_bars(value, thr)
        out[ticker] = aggregate_by_bar_id(df, bar_ids)
    return out, event_periods_per_year(spec, out)
