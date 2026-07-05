"""
intraday_loader.py — ingest pre-downloaded **intraday** (sub-daily) market data.

Prerequisite #3 for enabling event bars on real campaigns. The tick / volume /
dollar / imbalance builders in ``src/data/bars/`` treat each input row as one
atomic observation and accumulate a threshold across rows. On **daily** OHLCV
that means one observation per day, so an "event" bar can never close *within* a
day — the sampling is only as fine-grained as the input. Genuine event bars need
**intraday** observations (e.g. one row per minute), so a volume bar can close
several times inside a single session when trading is heavy.

This module is the ingestion counterpart to :mod:`data_loader` (which reads
*daily* CSVs). It reads per-ticker intraday CSVs into the SAME
``ticker -> DataFrame`` shape the Bar Engine consumes, the only difference being
that the ``DatetimeIndex`` carries a full **timestamp** (date + time), not a bare
calendar date.

Boundaries
----------
* This is **I/O / ingestion**, not sampling. All sampling logic stays inside the
  Bar Engine (``BarEngine.build``); this module never aggregates or resamples —
  it just faithfully loads rows and hands them over.
* Only modules inside ``agents/experiment_runner/`` may import from ``src/``;
  this loader imports nothing from ``src`` and is safe for the agent layer.
* Purely **additive**: the daily :func:`data_loader.load_data` path is untouched,
  so the current (time-bar) production path is byte-identical.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from agents.experiment_runner.data_loader import DataBundle, _ticker_from_path

log = logging.getLogger(__name__)

# Column names accepted as the intraday timestamp, tried in priority order. A
# single column that already carries date+time is preferred; failing that a
# ``Date`` + ``Time`` pair is combined. Matching is case-insensitive.
_TIMESTAMP_COLUMNS: tuple[str, ...] = (
    "Timestamp",
    "Datetime",
    "DateTime",
    "Date_Time",
    "datetime",
    "timestamp",
)
_DATE_COLUMN = "Date"
_TIME_COLUMN = "Time"

# The index name for intraday frames — distinct from the daily loader's "Date"
# so downstream code (and a human reading diagnostics) can tell the cadence apart.
INTRADAY_INDEX_NAME = "Timestamp"


def load_intraday(universe_dir: Path) -> DataBundle:
    """Load all intraday CSV files from *universe_dir* into a ``DataBundle``.

    Each returned DataFrame has:
      - a sub-daily ``DatetimeIndex`` named ``"Timestamp"`` (sorted ascending),
      - the original OHLCV columns preserved,
      - a ``"ticker"`` column added.

    A file must carry a recognised timestamp (see ``_TIMESTAMP_COLUMNS``, or a
    ``Date`` + ``Time`` pair) and a ``Close`` column. Partial loads (some files
    empty or malformed) proceed with a warning rather than failing the batch —
    the same contract as the daily loader.

    Parameters
    ----------
    universe_dir : Path
        Directory containing per-ticker intraday CSV files.

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
            warnings=[f"Intraday universe directory not found: {universe_dir}"],
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
            df = pd.read_csv(path)
            if df.empty:
                warnings.append(f"{path.name}: file is empty, skipped.")
                continue
            if "Close" not in df.columns:
                warnings.append(f"{path.name}: missing 'Close' column, skipped.")
                continue

            ts = _parse_timestamp(df)
            if ts is None:
                warnings.append(
                    f"{path.name}: no recognised timestamp column "
                    f"(expected one of {_TIMESTAMP_COLUMNS} or a 'Date'+'Time' pair), skipped."
                )
                continue

            df = df.drop(columns=_timestamp_source_columns(df))
            df.index = pd.DatetimeIndex(ts, name=INTRADAY_INDEX_NAME)
            df = df.sort_index()
            df["ticker"] = ticker
            data_dict[ticker] = df

        except Exception as exc:  # noqa: BLE001 — record and continue, never abort the batch
            warnings.append(f"{path.name}: failed to load — {exc}")

    return DataBundle(
        data_dict=data_dict,
        tickers_loaded=list(data_dict),
        warnings=warnings,
    )


def _timestamp_source_columns(df: pd.DataFrame) -> list[str]:
    """Column names that were consumed to build the timestamp index."""
    lower = {c.lower(): c for c in df.columns}
    for name in _TIMESTAMP_COLUMNS:
        if name.lower() in lower:
            return [lower[name.lower()]]
    if _DATE_COLUMN.lower() in lower and _TIME_COLUMN.lower() in lower:
        return [lower[_DATE_COLUMN.lower()], lower[_TIME_COLUMN.lower()]]
    if _DATE_COLUMN.lower() in lower:
        return [lower[_DATE_COLUMN.lower()]]
    return []


def _parse_timestamp(df: pd.DataFrame) -> pd.Series | None:
    """Return a parsed datetime Series for the frame, or ``None`` if no source.

    Priority: a single date+time column (``_TIMESTAMP_COLUMNS``) → a ``Date`` +
    ``Time`` pair → a bare ``Date`` column (which may itself carry a time). The
    parse is deterministic and timezone-naive; malformed values raise and are
    caught by the caller as a per-file warning.
    """
    lower = {c.lower(): c for c in df.columns}

    for name in _TIMESTAMP_COLUMNS:
        col = lower.get(name.lower())
        if col is not None:
            return pd.to_datetime(df[col])

    if _DATE_COLUMN.lower() in lower and _TIME_COLUMN.lower() in lower:
        combined = (
            df[lower[_DATE_COLUMN.lower()]].astype(str).str.strip()
            + " "
            + df[lower[_TIME_COLUMN.lower()]].astype(str).str.strip()
        )
        return pd.to_datetime(combined)

    if _DATE_COLUMN.lower() in lower:
        return pd.to_datetime(df[lower[_DATE_COLUMN.lower()]])

    return None
