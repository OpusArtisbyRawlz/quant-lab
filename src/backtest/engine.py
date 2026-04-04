import pandas as pd


def backtest_cross_sectional_strategy(
    weights_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    date_col: str = "Date",
    asset_col: str = "Ticker",
    weight_col: str = "weight",
    return_col: str = "fwd_ret_5",
) -> pd.DataFrame:
    """
    Merge weights with forward returns and compute portfolio return by date.
    """
    merged = weights_df.merge(
        returns_df[[date_col, asset_col, return_col]],
        on=[date_col, asset_col],
        how="inner",
    ).copy()

    merged["weighted_return"] = merged[weight_col] * merged[return_col]

    portfolio_returns = (
        merged.groupby(date_col)["weighted_return"]
        .sum()
        .rename("portfolio_return")
        .reset_index()
    )

    portfolio_returns["equity_curve"] = (1 + portfolio_returns["portfolio_return"]).cumprod()

    return portfolio_returns