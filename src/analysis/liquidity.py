"""
Liquidity & market-impact model.

Implements the standard capacity chain end to end::

    Daily Volume -> ADV -> Participation Rate -> Market Impact -> Slippage -> Net Returns

Each stage is a small pure function so it can be inspected and reused
independently; :func:`apply_liquidity_costs` chains them into net returns. The
market-impact stage uses a power-law model (default exponent ``0.5`` — the
standard square-root law for temporary impact), driven by **real** per-asset
average daily dollar volume rather than a flat placeholder.

No strategy is reconstructed here: the model takes an already-computed weight
path plus price/volume panels and returns the slippage drag it implies.
"""

import os
from typing import Mapping, Sequence, Union

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Stage 0: Daily Volume  (load raw OHLCV -> Close / Volume panels)
# ---------------------------------------------------------------------------
def load_price_volume(
    tickers: Sequence[str],
    data_dir: Union[str, os.PathLike] = "data/raw/project_04_universe",
    suffix: str = "_us_d.csv",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load ``Close`` and ``Volume`` panels (date x ticker) from per-ticker CSVs.

    Parameters
    ----------
    tickers : sequence of str
        Tickers to load (matched case-insensitively to ``{ticker}{suffix}``).
    data_dir : path-like
        Directory holding the per-ticker daily OHLCV CSVs.
    suffix : str, default "_us_d.csv"
        Filename suffix appended to the lower-cased ticker.

    Returns
    -------
    (close, volume) : tuple of pd.DataFrame
        Two ``date x ticker`` panels with a shared, sorted DatetimeIndex.
    """
    closes, volumes = {}, {}
    for ticker in tickers:
        path = os.path.join(str(data_dir), f"{ticker.lower()}{suffix}")
        df = pd.read_csv(path, parse_dates=["Date"]).set_index("Date").sort_index()
        closes[ticker] = df["Close"]
        volumes[ticker] = df["Volume"]

    close = pd.DataFrame(closes)
    volume = pd.DataFrame(volumes)
    return close, volume


# ---------------------------------------------------------------------------
# Stage 1: ADV  (Daily Volume -> average daily dollar volume)
# ---------------------------------------------------------------------------
def daily_dollar_volume(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """Daily traded dollar volume per asset = ``Close * Volume`` (date x ticker)."""
    close, volume = close.align(volume, join="inner")
    return close * volume


def average_daily_volume(
    dollar_volume: pd.DataFrame,
    window: int = 20,
    min_periods: int = None,
) -> pd.DataFrame:
    """
    ADV = trailing rolling mean of daily dollar volume.

    Parameters
    ----------
    dollar_volume : pd.DataFrame
        ``date x ticker`` daily dollar volume (e.g. from
        :func:`daily_dollar_volume`).
    window : int, default 20
        Trailing window in trading days (≈ one month).
    min_periods : int, optional
        Minimum observations; defaults to ``window``.

    Returns
    -------
    pd.DataFrame
        ``date x ticker`` ADV panel (dollars).
    """
    return dollar_volume.rolling(window, min_periods=min_periods or window).mean()


# ---------------------------------------------------------------------------
# Stage 2: Participation Rate  (order size / ADV)
# ---------------------------------------------------------------------------
def traded_notional(weights: pd.DataFrame, capital: float) -> pd.DataFrame:
    """Per-asset one-way traded dollar notional = ``capital * |Δweight|``."""
    dW = weights.diff().abs()
    if len(dW) > 0:
        dW.iloc[0] = 0.0
    return capital * dW


def participation_rate(
    weights: pd.DataFrame,
    capital: float,
    adv: pd.DataFrame,
) -> pd.DataFrame:
    """
    Participation rate per asset per day = traded$ / ADV.

    ``adv`` is reindexed to the weight grid and forward-filled (ADV is a slow
    trailing quantity, so carrying the last value over non-overlapping dates is
    safe). Division-by-zero / missing ADV yields ``NaN`` (ignored downstream).
    """
    traded = traded_notional(weights, capital)
    adv_aligned = adv.reindex(index=weights.index, columns=weights.columns).ffill()
    part = traded / adv_aligned
    return part.replace([np.inf, -np.inf], np.nan)


# ---------------------------------------------------------------------------
# Stage 3: Market Impact  (power-law / square-root)
# ---------------------------------------------------------------------------
def market_impact(
    participation: pd.DataFrame,
    coef: float = 0.1,
    exponent: float = 0.5,
) -> pd.DataFrame:
    """
    Temporary market impact per asset, in decimal (return) units.

    ``impact = coef * participation ** exponent`` — the reduced-form power-law
    model. ``exponent=0.5`` is the classic square-root law; ``coef`` scales the
    cost (e.g. ``coef=0.1`` ⇒ trading 1% of ADV costs ``0.1*sqrt(0.01)=0.01`` =
    100 bps on the traded notional).

    Returns a ``date x ticker`` panel of per-unit impact (fraction of price).
    """
    return coef * participation.clip(lower=0).pow(exponent)


# ---------------------------------------------------------------------------
# Stage 4: Slippage  (impact applied to the traded fraction -> return drag)
# ---------------------------------------------------------------------------
def slippage_series(
    weights: pd.DataFrame,
    participation: pd.DataFrame,
    coef: float = 0.1,
    exponent: float = 0.5,
) -> pd.Series:
    """
    Per-day portfolio slippage (a positive return drag).

    ``drag_t = Σ_asset |Δw_{a,t}| * impact_{a,t}`` where impact comes from
    :func:`market_impact`. Each asset's price impact is charged on the fraction
    of the portfolio actually traded in that asset.
    """
    dW = weights.diff().abs()
    if len(dW) > 0:
        dW.iloc[0] = 0.0
    impact = market_impact(participation, coef=coef, exponent=exponent)
    drag = (dW * impact).sum(axis=1, skipna=True)
    return drag


# ---------------------------------------------------------------------------
# Stage 5: Net Returns  (chain everything)
# ---------------------------------------------------------------------------
def apply_liquidity_costs(
    returns: pd.Series,
    weights: pd.DataFrame,
    adv: pd.DataFrame,
    capital: float,
    coef: float = 0.1,
    exponent: float = 0.5,
    base_cost_bps: float = 0.0,
) -> dict:
    """
    Run the full chain for one capital level and return net returns + diagnostics.

    Daily Volume -> ADV (input) -> Participation -> Market Impact -> Slippage ->
    Net Returns. A flat ``base_cost_bps`` (spread/commission) can be added on top
    of the modelled impact.

    Returns
    -------
    dict
        ``{
            "net_returns":    pd.Series,   # gross - slippage - base cost
            "slippage":       pd.Series,   # per-day impact drag (decimal)
            "participation":  pd.DataFrame,# date x ticker participation rate
        }``
    """
    returns = pd.Series(returns).astype(float)

    participation = participation_rate(weights, capital, adv)
    slippage = slippage_series(weights, participation, coef=coef, exponent=exponent)
    slippage = slippage.reindex(returns.index).fillna(0.0)

    turnover_oneway = (weights.diff().abs().sum(axis=1) / 2)
    if len(turnover_oneway) > 0:
        turnover_oneway.iloc[0] = 0.0
    base_drag = turnover_oneway.reindex(returns.index).fillna(0.0) * (base_cost_bps / 10000.0)

    net_returns = returns - slippage - base_drag
    return {
        "net_returns": net_returns,
        "slippage": slippage,
        "participation": participation,
    }


# ---------------------------------------------------------------------------
# Capacity ceiling: largest capital before participation breaches a cap
# ---------------------------------------------------------------------------
def capacity_ceiling(
    weights: pd.DataFrame,
    adv: pd.DataFrame,
    participation_cap: float = 0.10,
) -> dict:
    """
    Estimate the capital ceiling implied by a participation-rate cap.

    On each trading day, for every traded asset the largest capital that keeps
    participation at or below ``participation_cap`` is
    ``cap * ADV_a / |Δw_a|``. The binding (smallest) value across assets is that
    day's ceiling. The function summarises those daily ceilings.

    Parameters
    ----------
    weights : pd.DataFrame
        Wide weight matrix (date x ticker).
    adv : pd.DataFrame
        ``date x ticker`` ADV panel (dollars).
    participation_cap : float, default 0.10
        Maximum tolerable fraction of ADV (e.g. ``0.10`` = 10% of ADV).

    Returns
    -------
    dict
        ``{"participation_cap", "median_capital", "p05_capital", "min_capital"}``
        — the median, conservative (5th-percentile) and worst-case daily
        capital ceilings in dollars.
    """
    dW = weights.diff().abs()
    if len(dW) > 0:
        dW.iloc[0] = 0.0
    adv_aligned = adv.reindex(index=weights.index, columns=weights.columns).ffill()

    # Per-asset max capital before breaching the cap; only where we actually trade.
    per_asset_cap = participation_cap * adv_aligned / dW.where(dW > 0)
    daily_ceiling = per_asset_cap.min(axis=1, skipna=True).dropna()

    return {
        "participation_cap": participation_cap,
        "median_capital": float(daily_ceiling.median()),
        "p05_capital": float(daily_ceiling.quantile(0.05)),
        "min_capital": float(daily_ceiling.min()),
    }
