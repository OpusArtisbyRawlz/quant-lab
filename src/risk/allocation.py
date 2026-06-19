import pandas as pd

from src.risk import drawdown as dd
from src.utils.metrics import (
    sharpe_ratio,
    max_drawdown,
    annualized_return,
)


def compare_base_vs_dd_overlay(
    panel,
    floor=0.55,
    k=5,
):
    strategy_ret = panel["weight"] * panel["fwd_ret_5"]

    strategy_ret = strategy_ret.groupby(panel["Date"]).sum()

    equity = (1 + strategy_ret).cumprod()
    drawdown = dd.compute_drawdown(equity)

    exposure = dd.drawdown_exposure_smooth(
        drawdown,
        floor=floor,
        k=k,
    )

    strategy_ret_dd = dd.apply_exposure_to_return(
        strategy_ret,
        exposure,
    )

    result = pd.DataFrame(
        [
            {
                "Version": "Base",
                "Sharpe": sharpe_ratio(strategy_ret),
                "MDD": max_drawdown((1 + strategy_ret).cumprod()),
                "CAGR": annualized_return(strategy_ret),
                "Calmar": annualized_return(strategy_ret)
                / abs(max_drawdown((1 + strategy_ret).cumprod())),
                "Avg Exposure": 1.0,
            },
            {
                "Version": "DD Overlay",
                "Sharpe": sharpe_ratio(strategy_ret_dd),
                "MDD": max_drawdown((1 + strategy_ret_dd).cumprod()),
                "CAGR": annualized_return(strategy_ret_dd),
                "Calmar": annualized_return(strategy_ret_dd)
                / abs(max_drawdown((1 + strategy_ret_dd).cumprod())),
                "Avg Exposure": exposure.mean(),
            },
        ]
    ).round(3)

    return result, strategy_ret, strategy_ret_dd, exposure
