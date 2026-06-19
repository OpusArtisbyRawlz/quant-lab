import pandas as pd


def add_forward_returns(panel: pd.DataFrame, horizon: int = 5) -> pd.DataFrame:

    panel = panel.copy()

    panel[f"fwd_ret_{horizon}"] = panel.groupby("ticker")["Close"].transform(
        lambda x: x.shift(-horizon) / x - 1
    )

    return panel
