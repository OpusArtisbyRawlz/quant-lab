import pandas as pd


def add_price_features(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()

    panel["ret_1"] = panel.groupby("ticker")["Close"].transform(
        lambda x: x.pct_change(1)
    )

    panel["ret_5"] = panel.groupby("ticker")["Close"].transform(
        lambda x: x.pct_change(5)
    )

    panel["ret_10"] = panel.groupby("ticker")["Close"].transform(
        lambda x: x.pct_change(10)
    )

    panel["ret_20"] = panel.groupby("ticker")["Close"].transform(
        lambda x: x.pct_change(20)
    )

    panel["vol_5"] = panel.groupby("ticker")["ret_1"].transform(
        lambda x: x.rolling(5).std()
    )

    panel["vol_20"] = panel.groupby("ticker")["ret_1"].transform(
        lambda x: x.rolling(20).std()
    )

    panel["ma_10"] = panel.groupby("ticker")["Close"].transform(
        lambda x: x.rolling(10).mean()
    )

    panel["ma_20"] = panel.groupby("ticker")["Close"].transform(
        lambda x: x.rolling(20).mean()
    )

    panel["ma_10_ratio"] = panel["Close"] / panel["ma_10"] - 1
    panel["ma_20_ratio"] = panel["Close"] / panel["ma_20"] - 1

    return panel
