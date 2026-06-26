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
