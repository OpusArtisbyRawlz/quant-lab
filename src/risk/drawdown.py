import pandas as pd


def compute_drawdown(equity_curve: pd.Series) -> pd.Series:
    """
    Compute drawdown series from equity curve.
    Drawdown = current value / running max - 1
    """

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    return drawdown


def drawdown_exposure(drawdown: pd.Series) -> pd.Series:
    """
    Map drawdown to exposure scaling.

    Example rule:
    - DD > -10% → 1.0
    - -20% < DD <= -10% → 0.75
    - -30% < DD <= -20% → 0.5
    - DD <= -30% → 0.25
    """

    exposure = pd.Series(index=drawdown.index, dtype=float)

    exposure[drawdown > -0.10] = 1.0
    exposure[(drawdown <= -0.10) & (drawdown > -0.20)] = 0.75
    exposure[(drawdown > -0.20) & (drawdown > -0.30)] = 0.50
    exposure[drawdown <= -0.30] = 0.25

    return exposure


def apply_exposure_to_return(returns: pd.Series, exposure: pd.Series) -> pd.Series:
    """
    Apply exposure scaling to returns

    Important: exposure must be lagged by 1 day to avoid look ahead bias
    """

    exposure_lagged = exposure.shift(1).fillna(1.0)
    return returns * exposure_lagged


import numpy as np


def drawdown_exposure_smooth(
    drawdown: pd.Series, floor: float = 0.60, k: float = 3.0
) -> pd.Series:
    """
    Smooth exposure scaling based on drawdown.

    Higher drawdown -> gradually lower exposure.

    Parameters
    ----------
    drawdown : pd.Series
        Drawdown series (negative values)

    floor : float
        Minimum allowed exposure

    k : float
        Aggressiveness of decay

    Returns
    -------
    pd.Series
        Exposure series
    """

    dd_mag = drawdown.abs()

    exp_scale = np.exp(-k * dd_mag)

    exposure = floor + (1 - floor) * exp_scale

    return exposure
