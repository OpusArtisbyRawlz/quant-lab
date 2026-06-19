import pandas as pd

from src.features.price import add_price_features
from src.targets.forward_returns import add_forward_returns
from src.data.panel import build_market_panel


def run_market_alpha_pipeline(
    data_dict: dict,
    horizon: int = 5,
    long_quantile: float = 0.8,
    short_quantile: float = 0.2,
    signal_type: str = "ret_5_mean_reversion",
) -> pd.DataFrame:

    panel = build_market_panel(data_dict)
    panel = add_price_features(panel)
    panel = panel.dropna().copy()

    panel = add_forward_returns(panel, horizon=horizon)

    panel = panel.dropna().copy()

    if signal_type == "ret_5_mean_reversion":
        panel["signal"] = -panel["ret_5"]

    elif signal_type == "ret_10_mean_reversion":
        panel["signal"] = -panel["ret_10"]

    elif signal_type == "ret_20_mean_reversion":
        panel["signal"] = -panel["ret_20"]

    elif signal_type == "ma_20_ratio":
        panel["signal"] = panel["ma_20_ratio"]

    else:
        raise ValueError(f"Unknown signal_type: {signal_type}")

    panel["signal_rank"] = panel.groupby("Date")["signal"].rank(pct=True)

    panel["long"] = panel["signal_rank"] >= long_quantile
    panel["short"] = panel["signal_rank"] <= short_quantile

    panel["weight"] = 0.0

    panel.loc[panel["long"], "weight"] = 1
    panel.loc[panel["short"], "weight"] = -1

    panel["weight"] = panel.groupby("Date")["weight"].transform(
        lambda x: x / x.abs().sum() if x.abs().sum() > 0 else x
    )

    return panel
