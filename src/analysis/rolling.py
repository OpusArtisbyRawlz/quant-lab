"""
Rolling performance analytics.

Pure helpers that turn a daily return series into rolling, annualised
performance windows. No I/O, no plotting — input a return Series, get a tidy
DataFrame indexed by the same dates.
"""

import numpy as np
import pandas as pd


def rolling_metrics(
    returns: pd.Series,
    window: int = 252,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """
    Rolling annualised return, volatility and Sharpe ratio.

    Parameters
    ----------
    returns : pd.Series
        Daily (periodic) return series.
    window : int, default 252
        Rolling window length in observations.
    periods_per_year : int, default 252
        Annualisation factor.

    Returns
    -------
    pd.DataFrame
        Columns ``rolling_ann_return``, ``rolling_ann_vol``,
        ``rolling_sharpe`` indexed by the input dates.
    """
    r = pd.Series(returns).astype(float)

    roll_mean = r.rolling(window).mean()
    roll_std = r.rolling(window).std()

    return pd.DataFrame(
        {
            "rolling_ann_return": roll_mean * periods_per_year,
            "rolling_ann_vol": roll_std * np.sqrt(periods_per_year),
            "rolling_sharpe": np.sqrt(periods_per_year) * roll_mean / roll_std,
        }
    )
