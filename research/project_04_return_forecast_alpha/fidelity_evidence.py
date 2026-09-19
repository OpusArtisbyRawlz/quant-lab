"""
P04 fidelity evidence (READ-ONLY investigation; no engine changes, no fixes).

Reproduces the numbers in docs/P04_FIDELITY_ANALYSIS.md: the authoritative LS20
result, the factory replication, and the decomposition (date-window zero-padding vs
construction). Run:

    PYTHONPATH=. venv/bin/python research/project_04_return_forecast_alpha/fidelity_evidence.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from agents.experiment_runner.data_loader import load_data
from src.data.panel import build_market_panel
from src.features.price import add_price_features
from src.targets.forward_returns import add_forward_returns
from src.signals.combine import apply_signal_combo
from src.portfolio.construction import build_daily_weights_from_panel
from src.backtest.engine import backtest_cross_sectional_strategy
from src.utils.metrics import sharpe_ratio, max_drawdown

_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    v1 = pd.read_csv(_ROOT / "data/processed/v1.csv", parse_dates=["Date"])
    auth = pd.read_csv(_ROOT / "experiments/completed/exp_004_project04_final/"
                       "strategy_timeseries/ls_20pct.csv")["portfolio_return"]

    print("AUTHORITATIVE ls_20pct.csv:",
          f"sharpe={sharpe_ratio(auth):.3f} mean={auth.mean():.5f} std={auth.std():.5f}",
          f"lag1_autocorr={auth.autocorr(1):.3f} lag5_autocorr={auth.autocorr(5):.3f}")

    # Original committed reconstruction (equal-weight LS20 on pred_flipped, v1 window).
    w = build_daily_weights_from_panel(v1, signal_col="pred_flipped",
                                       long_quantile=0.2, short_quantile=0.2, method="equal")
    port = backtest_cross_sectional_strategy(w, v1, return_col="fwd_ret_5")
    r = port["portfolio_return"].reset_index(drop=True)
    print("ORIGINAL-src equal-weight LS20 (2016-2026):",
          f"sharpe={sharpe_ratio(r):.3f} corr_to_auth={r.corr(auth.reset_index(drop=True)):.3f}")

    # Factory replication over the full raw panel (1970-2026).
    dd = load_data(_ROOT / "data/raw/project_04_universe").data_dict
    panel = build_market_panel(dd)
    panel = add_price_features(panel).dropna().copy()
    panel = add_forward_returns(panel, horizon=5).dropna().copy()
    panel = apply_signal_combo(panel, signal_names=["hist_p04_return_forecast_v1"])
    panel["wret"] = panel["weight"] * panel["fwd_ret_5"]
    pr_full = panel.groupby("Date")["wret"].sum()
    active = panel.groupby("Date")["weight"].apply(lambda x: x.abs().sum() > 0)
    pr_active = pr_full[active.values]
    print("FACTORY-full (1970-2026, zero-padded):",
          f"sharpe={sharpe_ratio(pr_full):.3f} dates={len(pr_full)} active={int(active.sum())} "
          f"({100*active.mean():.1f}%)")
    print("FACTORY-active only (2016-2026):", f"sharpe={sharpe_ratio(pr_active):.3f}")


if __name__ == "__main__":
    main()
