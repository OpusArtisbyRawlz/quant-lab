import pandas as pd
import numpy as np


def rolling_volatility(
    returns: pd.Series,
    lookback: int = 20,
) -> pd.Series:
    """
    Annualized rolling volatility
    """

    return returns.rolling(lookback).std() * np.sqrt(252)


def volatility_target_exposure(
    returns: pd.Series,
    target_vol: float = 0.15,
    lookback: int = 20,
    max_leverage=0.15,
) -> pd.Series:
    """
    Exposure required to target a given annualized volatility.
    """

    realised_vol = rolling_volatility(
        returns,
        lookback=lookback,
    )

    exposure = target_vol / realised_vol

    exposure = exposure.clip(
        lower=0.0,
        upper=max_leverage,
    )

    return exposure.fillna(1.0)
