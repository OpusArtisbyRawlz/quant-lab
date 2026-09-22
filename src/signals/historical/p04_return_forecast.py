"""
Project 04 — ML 5-day return forecast (historical, versioned: v1).

Exposes Project 04's ORIGINAL out-of-fold return forecast (`pred`) as a factory
signal. The forecast is the authoritative historical artifact
``data/processed/v1.csv`` (the same per-(Date, Ticker) OOF predictions Project 04's
notebook produced and that downstream research consumed) — read verbatim, never
re-derived or approximated. Higher forecast ⇒ long, matching the project's
long/short construction; the cross-sectional pipeline ranks it per date.

This is a faithful port, not a substitute: the model that produced `pred` lives in
`research/project_04_return_forecast_alpha/notebooks/03_model_training*.ipynb`; this
module only surfaces its stored output under a versioned name.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

SIGNAL_NAME = "hist_p04_return_forecast_v1"

# repo root = src/signals/historical/ -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ARTIFACT = _REPO_ROOT / "data" / "processed" / "v1.csv"
# Project 04's long/short strategy trades on the SIGN-FLIPPED prediction: its
# portfolio notebook (04_portfolio_research.ipynb, cell 4) uses `pred_flipped`
# (renamed `signal_v1`), not the raw `pred`. Using `pred` would invert the strategy.
_FORECAST_COLUMN = "pred_flipped"


@lru_cache(maxsize=1)
def _forecast_lookup() -> dict[tuple[pd.Timestamp, str], float]:
    """(normalized Date, upper Ticker) -> pred, from the historical v1 artifact.
    Cached; pure read of the versioned artifact."""
    df = pd.read_csv(SOURCE_ARTIFACT, parse_dates=["Date"])
    dates = df["Date"].dt.normalize()
    tickers = df["Ticker"].astype(str).str.upper()
    return {
        (d, t): float(p)
        for d, t, p in zip(dates, tickers, df[_FORECAST_COLUMN])
        if pd.notna(p)
    }


def p04_return_forecast_series(panel: pd.DataFrame) -> pd.Series:
    """Return the P04 v1 forecast aligned to ``panel`` (index-preserving). Rows with
    no historical forecast (date/ticker outside the artifact) are NaN — the pipeline's
    per-date ranking naturally excludes them, so partial coverage degrades gracefully
    without fabricating values."""
    lut = _forecast_lookup()
    dates = pd.to_datetime(panel["Date"]).dt.normalize()
    tickers = panel["ticker"].astype(str).str.upper()
    values = [lut.get((d, t)) for d, t in zip(dates, tickers)]
    return pd.Series(values, index=panel.index, dtype="float64")
