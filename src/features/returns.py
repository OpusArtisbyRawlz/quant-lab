import pandas as pd


def make_forward_returns(
    df: pd.DataFrame,
    price_col: str = "Close",
    id_col: str = "Ticker",
    horizon: int = 5,
) -> pd.DataFrame:
    """
    Create forward returns by asset.

    Expects a panel DataFrame with at least:
    - id_col
    - price_col

    Index should usually contain dates, or dataframe should already be sorted.
    """
    df = df.copy()
    df = df.sort_index()

    df[f"fwd_ret_{horizon}"] = (
        df.groupby(id_col)[price_col]
        .shift(-horizon)
        .div(df[price_col])
        .sub(1.0)
    )

    return df


def make_lagged_return(
    df: pd.DataFrame,
    price_col: str = "Close",
    id_col: str = "Ticker",
    lag: int = 5,
) -> pd.DataFrame:
    """
    Create lagged trailing return by asset.
    """
    df = df.copy()
    df = df.sort_index()

    df[f"ret_{lag}"] = (
        df.groupby(id_col)[price_col]
        .pct_change(lag)
    )

    return df