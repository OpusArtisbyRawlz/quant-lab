"""
bars.volume — volume bars.

A volume bar closes once the cumulative traded ``Volume`` since the last bar
reaches a threshold. Bars therefore span more calendar time in quiet periods and
less in active periods — the point of volume sampling. The trailing rows below
the threshold form a final partial bar.

Deterministic and pure: same input + same ``threshold`` → identical bars.

BE-3: implemented and unit-tested on synthetic data, but not production-enabled.
"""

from __future__ import annotations

import pandas as pd

from .base import SamplingSpec, DEFAULT_PERIODS_PER_YEAR
from ._aggregate import assign_threshold_bars, aggregate_by_bar_id


def _threshold(spec: SamplingSpec) -> float:
    thr = spec.param("threshold")
    if thr is None:
        raise ValueError("volume bars require params['threshold'] (volume per bar)")
    thr = float(thr)
    if thr <= 0:
        raise ValueError(f"volume threshold must be positive, got {thr}")
    return thr


def build_volume_bars(
    raw_data: dict[str, pd.DataFrame], spec: SamplingSpec
) -> tuple[dict[str, pd.DataFrame], float]:
    """Accumulate ``Volume`` per ticker; emit a bar each time it crosses ``threshold``."""
    thr = _threshold(spec)
    out: dict[str, pd.DataFrame] = {}
    for ticker, df in raw_data.items():
        bar_ids = assign_threshold_bars(df["Volume"].to_numpy(dtype=float), thr)
        out[ticker] = aggregate_by_bar_id(df, bar_ids)
    periods_per_year = spec.periods_per_year or DEFAULT_PERIODS_PER_YEAR
    return out, periods_per_year
