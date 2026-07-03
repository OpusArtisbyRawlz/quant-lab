"""
bars.imbalance — tick / volume / dollar imbalance bars.

Imbalance bars sample when the *signed* order-flow imbalance since the last bar
grows large in magnitude, so a bar closes faster when buys and sells are lopsided
than when they roughly cancel. Each row is signed by the **tick rule**:

    b_t = +1 if Close_t > Close_{t-1}
          -1 if Close_t < Close_{t-1}
          b_{t-1} if unchanged   (carry the previous sign; b_0 = +1)

and the per-row weight is:

    tick_imbalance:   b_t                    (signed count)
    volume_imbalance: b_t * Volume_t         (signed volume)
    dollar_imbalance: b_t * Close_t * Volume_t   (signed value)

A bar closes once ``|Σ weight|`` since the last bar reaches ``params['threshold']``.

BE-4 note: this is the **fixed-threshold** formulation — deterministic and pure.
The adaptive/EWMA expected-imbalance thresholding from AFML (which carries
estimation state across bars) is a deliberate non-goal here and can arrive later
as extra ``params`` without changing this call shape. Implemented and
unit-tested on synthetic data; NOT enabled for real campaigns
(see ``PRODUCTION_BAR_TYPES``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import SamplingSpec
from ._aggregate import assign_imbalance_bars, aggregate_by_bar_id
from .periods import event_periods_per_year


def tick_signs(close: np.ndarray) -> np.ndarray:
    """The tick rule: ±1 per row from the sign of the close-to-close change.

    The first row has no predecessor and is assigned ``+1``; an unchanged close
    carries the previous sign forward. Deterministic and pure.
    """
    signs = np.empty(len(close), dtype=np.int64)
    prev = 1
    for i in range(len(close)):
        if i > 0:
            d = close[i] - close[i - 1]
            if d > 0:
                prev = 1
            elif d < 0:
                prev = -1
            # d == 0 → carry previous sign
        signs[i] = prev
    return signs


def _threshold(spec: SamplingSpec) -> float:
    thr = spec.param("threshold")
    if thr is None:
        raise ValueError(
            f"{spec.type} bars require params['threshold'] (imbalance magnitude per bar)"
        )
    thr = float(thr)
    if thr <= 0:
        raise ValueError(f"{spec.type} threshold must be positive, got {thr}")
    return thr


def _weights(df: pd.DataFrame, kind: str, signs: np.ndarray) -> np.ndarray:
    """Signed per-row weight for the given imbalance kind."""
    if kind == "tick_imbalance":
        return signs.astype(float)
    volume = df["Volume"].to_numpy(dtype=float)
    if kind == "volume_imbalance":
        return signs * volume
    # dollar_imbalance
    close = df["Close"].to_numpy(dtype=float)
    return signs * close * volume


def _build_imbalance(
    raw_data: dict[str, pd.DataFrame], spec: SamplingSpec, kind: str
) -> tuple[dict[str, pd.DataFrame], float]:
    thr = _threshold(spec)
    out: dict[str, pd.DataFrame] = {}
    for ticker, df in raw_data.items():
        signs = tick_signs(df["Close"].to_numpy(dtype=float))
        weights = _weights(df, kind, signs)
        bar_ids = assign_imbalance_bars(weights, thr)
        out[ticker] = aggregate_by_bar_id(df, bar_ids)
    return out, event_periods_per_year(spec, out)


def build_tick_imbalance_bars(raw_data, spec):
    """Sample on signed tick-count imbalance."""
    return _build_imbalance(raw_data, spec, "tick_imbalance")


def build_volume_imbalance_bars(raw_data, spec):
    """Sample on signed volume imbalance."""
    return _build_imbalance(raw_data, spec, "volume_imbalance")


def build_dollar_imbalance_bars(raw_data, spec):
    """Sample on signed dollar-value imbalance."""
    return _build_imbalance(raw_data, spec, "dollar_imbalance")
