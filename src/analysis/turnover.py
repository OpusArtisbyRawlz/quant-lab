from typing import Sequence

import pandas as pd
import numpy as np


def compute_turnover(weights: pd.DataFrame) -> pd.Series:
    """
    One-way daily portfolio turnover.

    Parameters
    ----------
    weights : pd.DataFrame
        Portfolio weights indexed by Date, columns are tickers.

    Returns
    -------
    pd.Series
        Daily one-way turnover, computed as the summed absolute change in
        weights divided by 2. The first observation has no prior weights to
        compare against and is filled with 0.
    """

    turnover = weights.diff().abs().sum(axis=1) / 2

    if len(turnover) > 0:
        turnover.iloc[0] = 0.0

    return turnover


def rolling_turnover(turnover: pd.Series, window: int = 252) -> pd.Series:
    """
    Rolling mean of daily turnover.

    Parameters
    ----------
    turnover : pd.Series
        Daily one-way turnover series.
    window : int, default 252
        Rolling window length in observations.

    Returns
    -------
    pd.Series
        Rolling mean turnover over the given window.
    """

    return turnover.rolling(window).mean()


def rolling_turnover_summary(
    turnover: pd.Series,
    windows: Sequence[int] = (63, 252),
) -> pd.DataFrame:
    """
    Rolling mean / max / p95 of one-way turnover for several windows.

    Parameters
    ----------
    turnover : pd.Series
        Daily one-way turnover series.
    windows : sequence of int, default (63, 252)
        Rolling window lengths in observations (e.g. quarter and year).

    Returns
    -------
    pd.DataFrame
        Indexed by the input dates with, for each window ``w``, columns
        ``roll{w}_mean``, ``roll{w}_max`` and ``roll{w}_p95``.
    """
    turnover = pd.Series(turnover).astype(float)

    out = {}
    for w in windows:
        roll = turnover.rolling(w)
        out[f"roll{w}_mean"] = roll.mean()
        out[f"roll{w}_max"] = roll.max()
        out[f"roll{w}_p95"] = roll.quantile(0.95)

    return pd.DataFrame(out, index=turnover.index)


def turnover_spikes(
    turnover: pd.Series,
    window: int = 63,
    n_sigma: float = 3.0,
) -> pd.DataFrame:
    """
    Identify dates where daily turnover spikes above a trailing threshold.

    A spike is a day whose turnover exceeds ``rolling_mean + n_sigma *
    rolling_std`` over the trailing ``window`` (both computed on a trailing
    window ending the prior day, so the spike day itself does not inflate its
    own threshold).

    Parameters
    ----------
    turnover : pd.Series
        Daily one-way turnover series.
    window : int, default 63
        Trailing window for the mean / std baseline.
    n_sigma : float, default 3.0
        Number of standard deviations above the rolling mean to flag.

    Returns
    -------
    pd.DataFrame
        One row per spike date with columns ``Date``, ``turnover``,
        ``roll_mean``, ``roll_std``, ``threshold`` and ``z_score``, sorted by
        descending ``z_score``.
    """
    turnover = pd.Series(turnover).astype(float)

    trailing = turnover.shift(1).rolling(window, min_periods=window)
    mu = trailing.mean()
    sd = trailing.std()
    threshold = mu + n_sigma * sd
    z = (turnover - mu) / sd

    mask = (turnover > threshold) & sd.notna() & (sd > 0)

    spikes = pd.DataFrame(
        {
            "turnover": turnover[mask],
            "roll_mean": mu[mask],
            "roll_std": sd[mask],
            "threshold": threshold[mask],
            "z_score": z[mask],
        }
    )
    spikes = spikes.reset_index()
    spikes = spikes.rename(columns={spikes.columns[0]: "Date"})
    return spikes.sort_values("z_score", ascending=False).reset_index(drop=True)


def summarize_turnover(turnover: pd.Series) -> dict:
    """
    Summary statistics for a turnover series.

    Parameters
    ----------
    turnover : pd.Series
        Daily one-way turnover series.

    Returns
    -------
    dict
        Mean, median, max, and 95th percentile of turnover.
    """

    return {
        "mean": float(turnover.mean()),
        "median": float(turnover.median()),
        "max": float(turnover.max()),
        "p95": float(np.nanpercentile(turnover, 95)),
    }


def build_turnover_report(weights: pd.DataFrame) -> pd.DataFrame:
    """
    Build a one-row turnover summary report from portfolio weights.

    Parameters
    ----------
    weights : pd.DataFrame
        Portfolio weights indexed by Date, columns are tickers.

    Returns
    -------
    pd.DataFrame
        Single-row dataframe with summary turnover metrics.
    """

    turnover = compute_turnover(weights)
    summary = summarize_turnover(turnover)

    return pd.DataFrame([summary])
