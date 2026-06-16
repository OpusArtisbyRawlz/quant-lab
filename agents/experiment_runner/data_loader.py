"""
data_loader.py — loads pre-downloaded market data from local CSV files.

Reads from data/raw/<universe>/ directories. Each file must have at minimum
a Date column and a Close column. The ticker key in the returned data_dict
is derived from the filename:
  aapl_us_d.csv  → AAPL
  MSFT.csv       → MSFT
  spy.csv        → SPY

This module does NOT download data. Use src/data/loader.py for yfinance
downloads. This module reads what is already on disk.

Only this module (inside agents/experiment_runner/) is permitted to import
from src/ pipeline modules. Decision-making agents must not import src/ directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Suffix patterns to strip when deriving a ticker from a filename
_STRIP_SUFFIXES = ("_us_d", "_us_w", "_us_m")


@dataclass
class DataBundle:
    data_dict: dict[str, pd.DataFrame]
    tickers_loaded: list[str]
    tickers_missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_data(universe_dir: Path) -> DataBundle:
    """
    Load all CSV files from *universe_dir* into a data_dict.

    Each DataFrame in the returned dict has:
      - DatetimeIndex named "Date"
      - Original OHLCV columns preserved
      - "ticker" column added

    Partial loads (some files empty or malformed) proceed with a warning.

    Parameters
    ----------
    universe_dir : Path
        Directory containing per-ticker CSV files.

    Returns
    -------
    DataBundle
    """
    warnings: list[str] = []
    data_dict: dict[str, pd.DataFrame] = {}

    if not universe_dir.exists():
        return DataBundle(
            data_dict={},
            tickers_loaded=[],
            tickers_missing=[],
            warnings=[f"Universe directory not found: {universe_dir}"],
        )

    csv_files = sorted(universe_dir.glob("*.csv"))
    if not csv_files:
        return DataBundle(
            data_dict={},
            tickers_loaded=[],
            warnings=[f"No CSV files in {universe_dir}"],
        )

    for path in csv_files:
        ticker = _ticker_from_path(path)
        try:
            df = pd.read_csv(path, parse_dates=["Date"])
            if df.empty:
                warnings.append(f"{path.name}: file is empty, skipped.")
                continue
            if "Close" not in df.columns:
                warnings.append(f"{path.name}: missing 'Close' column, skipped.")
                continue

            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date").sort_index()
            df["ticker"] = ticker
            data_dict[ticker] = df

        except Exception as exc:
            warnings.append(f"{path.name}: failed to load — {exc}")

    return DataBundle(
        data_dict=data_dict,
        tickers_loaded=list(data_dict),
        warnings=warnings,
    )


def _ticker_from_path(path: Path) -> str:
    """Derive a ticker symbol from a CSV filename."""
    stem = path.stem
    for suffix in _STRIP_SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.upper()
