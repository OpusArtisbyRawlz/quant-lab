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