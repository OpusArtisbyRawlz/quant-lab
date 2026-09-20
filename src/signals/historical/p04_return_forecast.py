"""
Project 04 — authoritative long/short return-forecast strategy (historical, v1).

This ports Project 04's ORIGINAL portfolio construction faithfully, verbatim from
the authoritative generator that was recovered *inside this repository* at
``research/project_04_return_forecast_alpha/notebooks/04_portfolio_research.ipynb``
(cells 4, 7, 9, 117-130). Nothing is re-derived, retrained, or approximated.

Authoritative recipe (exactly as the notebook builds it)
--------------------------------------------------------
1. ``signal_v1`` = ``pred_flipped`` from ``data/processed/v1.csv`` (cell 4).
2. ``signal_v2`` = ``pred``          from ``data/processed/v2.csv`` (cell 4).
3. Inner-merge on (Date, Ticker) — the strategy trades only the v1 ∩ v2 panel
   (2016-01-04 … 2026-03-06, 20 tickers).
4. Per-date z-score each: ``(x - x.mean()) / x.std()`` grouped by Date (cell 7).
5. ``combined_signal = signal_v1_z + signal_v2_z`` (cell 9).
6. Per-date percentile rank of ``combined_signal`` (cell 117).
7. Long/short membership (cells 118 / 129):
     * LS20:  +1 if rank >= 0.80, -1 if rank <= 0.20
     * LS30:  +1 if rank >= 0.70, -1 if rank <= 0.30
8. Equal weights per side, ``max_weight = 0.05`` (cell 119) — a no-op for the
   balanced 20-name book (0.05 per side < the 0.05 cap), preserved for fidelity.
9. Backtest on ``fwd_ret_5`` → LS20 Sharpe **1.5160** / MDD -0.6553,
   LS30 Sharpe **1.4176** / MDD -0.5490 (cells 120 / 130).

Why membership (±1) rather than the continuous ``combined_signal``
-----------------------------------------------------------------
The factory's cross-sectional pipeline (``apply_signal_combo``) selects the top /
bottom quantile (0.80 / 0.20) and equal-weights each side. Feeding it the ±1
membership series reproduces the notebook's baskets **exactly** for both LS20 and
LS30: pandas ``rank(pct=True)`` averages ties, so the 30 % of names flagged +1 all
receive rank ≈ 0.875 (≥ 0.80 → all longed) and the -1 names rank ≈ 0.175
(≤ 0.20 → all shorted). Verified end-to-end: LS20 → 1.5160, LS30 → 1.4176 on the
strategy's 2016-2026 window, matching ``exp_004`` / ``strategy_comparison.csv``.

This corrects the earlier v1 port (which exposed ``pred_flipped`` alone and scored
~0.53/0.36) and the earlier "under-specified / generator absent" conclusions — the
generator was in the repo all along. See docs/P04_FIDELITY_ANALYSIS.md.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

# Registered signal names (versioned: v1).
LS20_SIGNAL_NAME = "hist_p04_ls20_v1"
LS30_SIGNAL_NAME = "hist_p04_ls30_v1"

# repo root = src/signals/historical/ -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
V1_ARTIFACT = _REPO_ROOT / "data" / "processed" / "v1.csv"
V2_ARTIFACT = _REPO_ROOT / "data" / "processed" / "v2.csv"

# Authoritative source columns (04_portfolio_research.ipynb cell 4).
_V1_COLUMN = "pred_flipped"   # signal_v1
_V2_COLUMN = "pred"           # signal_v2

# LS thresholds (cells 118 / 129).
_LS20_LONG, _LS20_SHORT = 0.80, 0.20
_LS30_LONG, _LS30_SHORT = 0.70, 0.30


def _zscore(x: pd.Series) -> pd.Series:
    """Per-date z-score exactly as the notebook: (x - mean) / std (sample std)."""
    return (x - x.mean()) / x.std()


@lru_cache(maxsize=1)
def _combined() -> pd.DataFrame:
    """Authoritative combined_signal over v1 ∩ v2, with per-date percentile rank.

    Pure read of the two versioned artifacts; cached. Columns:
    Date, Ticker (upper), combined_signal, rank.
    """
    v1 = pd.read_csv(V1_ARTIFACT, parse_dates=["Date"])[["Date", "Ticker", _V1_COLUMN]]
    v2 = pd.read_csv(V2_ARTIFACT, parse_dates=["Date"])[["Date", "Ticker", _V2_COLUMN]]
    v1 = v1.rename(columns={_V1_COLUMN: "signal_v1"})
    v2 = v2.rename(columns={_V2_COLUMN: "signal_v2"})
    df = v1.merge(v2, on=["Date", "Ticker"], how="inner")  # cell 4: inner join
    df["signal_v1_z"] = df.groupby("Date")["signal_v1"].transform(_zscore)  # cell 7
    df["signal_v2_z"] = df.groupby("Date")["signal_v2"].transform(_zscore)
    df["combined_signal"] = df["signal_v1_z"] + df["signal_v2_z"]           # cell 9
    df["rank"] = df.groupby("Date")["combined_signal"].rank(pct=True)       # cell 117
    df["Date"] = df["Date"].dt.normalize()
    df["Ticker"] = df["Ticker"].astype(str).str.upper()
    return df


@lru_cache(maxsize=2)
def _membership_lookup(long_q: float, short_q: float) -> dict[tuple[pd.Timestamp, str], float]:
    """(normalized Date, upper Ticker) -> ±1 LS membership at the given thresholds."""
    df = _combined()
    lut: dict[tuple[pd.Timestamp, str], float] = {}
    for d, t, r in zip(df["Date"], df["Ticker"], df["rank"]):
        if r >= long_q:
            lut[(d, t)] = 1.0
        elif r <= short_q:
            lut[(d, t)] = -1.0
        else:
            lut[(d, t)] = 0.0
    return lut


def _membership_series(panel: pd.DataFrame, long_q: float, short_q: float) -> pd.Series:
    """±1 LS membership aligned to ``panel`` (index-preserving). Dates/tickers outside
    the v1 ∩ v2 window are NaN — the pipeline's per-date ranking excludes them, so the
    strategy trades only its authoritative 2016-2026 panel without fabricating values."""
    lut = _membership_lookup(long_q, short_q)
    dates = pd.to_datetime(panel["Date"]).dt.normalize()
    tickers = panel["ticker"].astype(str).str.upper()
    values = [lut.get((d, t)) for d, t in zip(dates, tickers)]
    return pd.Series(values, index=panel.index, dtype="float64")


def p04_ls20_series(panel: pd.DataFrame) -> pd.Series:
    """Project 04 LS20 membership (rank ≥ 0.80 long, ≤ 0.20 short)."""
    return _membership_series(panel, _LS20_LONG, _LS20_SHORT)


def p04_ls30_series(panel: pd.DataFrame) -> pd.Series:
    """Project 04 LS30 membership (rank ≥ 0.70 long, ≤ 0.30 short)."""
    return _membership_series(panel, _LS30_LONG, _LS30_SHORT)
