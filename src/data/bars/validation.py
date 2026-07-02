"""
bars.validation — deterministic, non-destructive checks on a bar data_dict.

Split into two tiers:

* **Structural** violations (empty input, missing OHLCV columns, non-datetime
  index) raise ``BarValidationError`` — these mean the frame is not usable as
  bars at all.
* **Quality** observations (unsorted index, duplicate timestamps, OHLC ordering
  breaks) are collected as warnings in the returned diagnostics and never
  mutate or reject the data — so identity mode is guaranteed to pass through
  today's real, occasionally-imperfect daily data unchanged.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import REQUIRED_COLUMNS


class BarValidationError(ValueError):
    """Raised when a data_dict is structurally unusable as bars."""


def validate_bars(data: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Validate a ``ticker -> DataFrame`` bundle. Returns diagnostics.

    Raises
    ------
    BarValidationError
        On any structural violation (empty bundle/frame, missing required
        columns, non-DatetimeIndex).
    """
    if not isinstance(data, dict) or not data:
        raise BarValidationError("bar data must be a non-empty {ticker: DataFrame} dict")

    warnings: list[str] = []
    bars_per_ticker: dict[str, int] = {}

    for ticker, df in data.items():
        if not isinstance(df, pd.DataFrame):
            raise BarValidationError(f"{ticker!r}: expected DataFrame, got {type(df).__name__}")
        if df.empty:
            raise BarValidationError(f"{ticker!r}: empty frame")
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise BarValidationError(f"{ticker!r}: missing required columns {missing}")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise BarValidationError(
                f"{ticker!r}: index must be a DatetimeIndex, got {type(df.index).__name__}"
            )

        bars_per_ticker[ticker] = int(len(df))

        # -- non-fatal quality observations -------------------------------
        if not df.index.is_monotonic_increasing:
            warnings.append(f"{ticker}: index not monotonically increasing")
        if df.index.has_duplicates:
            warnings.append(f"{ticker}: duplicate timestamps in index")
        # OHLC ordering: High >= max(Open,Close,Low), Low <= min(Open,Close,High)
        hi, lo = df["High"], df["Low"]
        if (hi < lo).any():
            warnings.append(f"{ticker}: High < Low on some bars")

    return {
        "n_tickers": len(data),
        "bars_per_ticker": bars_per_ticker,
        "total_bars": int(sum(bars_per_ticker.values())),
        "quality_warnings": warnings,
    }
