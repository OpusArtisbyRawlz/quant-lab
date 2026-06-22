from src.pipelines.cross_sectional import run_market_alpha_pipeline
from src.signals.combine import apply_signal_combo
from src.risk.allocation import compare_base_vs_dd_overlay
import src.risk.drawdown as dd
import src.risk.vol_target as vt


def build_strategy_return_stack(
    market_data,
    signal_names,
    target_vol=0.10,
    lookback=20,
    max_leverage=1.5,
    floor=0.55,
    k=5,
):
    champion = apply_signal_combo(
        run_market_alpha_pipeline(market_data),
        signal_names=signal_names,
    )

    compare_df, base_ret, dd_ret, dd_exposure = compare_base_vs_dd_overlay(
        champion,
        floor=floor,
        k=k,
    )

    vol_exposure = vt.volatility_target_exposure(
        base_ret,
        target_vol=target_vol,
        lookback=lookback,
        max_leverage=max_leverage,
    )

    vol_ret = dd.apply_exposure_to_return(
        base_ret,
        vol_exposure,
    )

    combined_exposure = (dd_exposure * vol_exposure).clip(0, max_leverage)

    dd_vol_ret = dd.apply_exposure_to_return(
        base_ret,
        combined_exposure,
    )

    return {
        "panel": champion,
        "base_ret": base_ret,
        "dd_ret": dd_ret,
        "vol_ret": vol_ret,
        "dd_vol_ret": dd_vol_ret,
        "dd_exposure": dd_exposure,
        "vol_exposure": vol_exposure,
        "combined_exposure": combined_exposure,
        "compare": compare_df,
    }
