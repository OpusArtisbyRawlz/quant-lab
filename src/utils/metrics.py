import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    """
    Annualized Sharpe ratio from a return series.
    """
    returns = pd.Series(returns).dropna()

    if returns.empty or returns.std() == 0:
        return np.nan

    return np.sqrt(periods_per_year) * returns.mean() / returns.std()


def max_drawdown(equity_curve: pd.Series) -> float:
    """
    Max drawdown from an equity curve.
    Returns a negative number.
    """
    equity_curve = pd.Series(equity_curve).dropna()

    if equity_curve.empty:
        return np.nan

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    return drawdown.min()


def annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    """
    Annualized return from periodic returns.
    """
    returns = pd.Series(returns).dropna()

    if returns.empty:
        return np.nan

    compounded = (1 + returns).prod()
    n_periods = len(returns)

    return compounded ** (periods_per_year / n_periods) - 1


def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    """
    Annualized volatility from periodic returns.
    """
    returns = pd.Series(returns).dropna()

    if returns.empty:
        return np.nan

    return returns.std() * np.sqrt(periods_per_year)


def sortino_ratio(
    returns: pd.Series,
    periods_per_year: int = 252,
    mar: float = 0.0,
) -> float:
    """
    Annualized Sortino ratio: excess return over the downside deviation.

    Downside deviation is the root-mean-square of returns that fall below the
    minimum acceptable return ``mar`` (default 0), so only harmful volatility is
    penalized. Returns ``nan`` if there is no downside or the series is empty.
    """
    returns = pd.Series(returns).dropna()

    if returns.empty:
        return np.nan

    downside = np.minimum(returns - mar, 0.0)
    downside_dev = np.sqrt((downside ** 2).mean())

    if downside_dev == 0:
        return np.nan

    return np.sqrt(periods_per_year) * (returns.mean() - mar) / downside_dev


def ulcer_index(equity_curve: pd.Series) -> float:
    """
    Ulcer Index: the root-mean-square drawdown of an equity curve.

    Unlike maximum drawdown (a single worst point), the Ulcer Index rewards both
    shallow drawdowns and quick recoveries by averaging the squared depth across
    the whole path. Expressed as a positive fraction (e.g. 0.07 = 7%).
    """
    equity_curve = pd.Series(equity_curve).dropna()

    if equity_curve.empty:
        return np.nan

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    return float(np.sqrt((drawdown ** 2).mean()))


def drawdown_stats(equity_curve: pd.Series, threshold: float = 0.05) -> dict:
    """
    Episode-level drawdown analytics from an equity curve.

    A drawdown episode runs from the bar after an all-time high until equity
    reclaims that high (recovery). The series may end while still underwater, in
    which case that episode is left-censored (no recovery) and its duration runs
    to the final bar.

    Parameters
    ----------
    equity_curve : pd.Series
        Growth-of-one equity curve.
    threshold : float, default 0.05
        Minimum trough depth (as a positive fraction) for an episode to count
        toward ``frequency`` and the duration/recovery "significant" statistics.

    Returns
    -------
    dict
        ``max_depth`` (negative), ``max_dd_duration`` (bars, peak->recovery of
        the deepest episode), ``max_dd_recovery`` (bars, trough->recovery of the
        deepest episode; nan if unrecovered), ``longest_underwater`` (bars, the
        longest single underwater stretch), ``time_underwater_frac`` (fraction of
        bars spent below a prior peak), ``frequency`` (count of episodes deeper
        than ``threshold``), and ``avg_depth`` (mean trough depth of those
        episodes, negative).
    """
    equity_curve = pd.Series(equity_curve).dropna().reset_index(drop=True)
    n = len(equity_curve)

    if n == 0:
        return {
            "max_depth": np.nan, "max_dd_duration": np.nan,
            "max_dd_recovery": np.nan, "longest_underwater": np.nan,
            "time_underwater_frac": np.nan, "frequency": 0, "avg_depth": np.nan,
        }

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    underwater = drawdown < 0

    # split the path into contiguous underwater episodes
    episodes = []  # (peak_idx, trough_idx, recovery_idx_or_None, depth)
    i = 0
    while i < n:
        if not underwater.iloc[i]:
            i += 1
            continue
        start = i                      # first underwater bar (peak was start-1)
        peak = start - 1
        while i < n and underwater.iloc[i]:
            i += 1
        end = i - 1                    # last underwater bar of this episode
        seg = drawdown.iloc[start:end + 1]
        trough_idx = int(seg.idxmin())
        depth = float(seg.min())
        recovered = end + 1 < n        # equity reclaimed the prior peak at end+1
        recovery_idx = (end + 1) if recovered else None
        episodes.append((peak, trough_idx, recovery_idx, depth))

    if not episodes:
        return {
            "max_depth": 0.0, "max_dd_duration": 0, "max_dd_recovery": 0,
            "longest_underwater": 0, "time_underwater_frac": 0.0,
            "frequency": 0, "avg_depth": 0.0,
        }

    deepest = min(episodes, key=lambda e: e[3])
    peak, trough_idx, recovery_idx, depth = deepest
    if recovery_idx is not None:
        dd_duration = recovery_idx - peak
        dd_recovery = recovery_idx - trough_idx
    else:
        dd_duration = (n - 1) - peak
        dd_recovery = np.nan

    def episode_len(e):
        peak_i, _, rec_i, _ = e
        end_i = rec_i if rec_i is not None else (n - 1)
        return end_i - peak_i

    longest_underwater = max(episode_len(e) for e in episodes)
    significant = [e for e in episodes if abs(e[3]) >= threshold]

    return {
        "max_depth": depth,
        "max_dd_duration": int(dd_duration),
        "max_dd_recovery": float(dd_recovery) if dd_recovery == dd_recovery else np.nan,
        "longest_underwater": int(longest_underwater),
        "time_underwater_frac": float(underwater.mean()),
        "frequency": int(len(significant)),
        "avg_depth": float(np.mean([e[3] for e in significant])) if significant else 0.0,
    }