"""Identify the exact portfolio construction behind the saved exp_004 ls_20pct.csv.

Tests candidate constructions on the SAVED predictions (v1.csv pred_flipped, v2.csv pred)
and compares each to the saved strategy_timeseries/ls_20pct.csv (Sharpe 1.516, MDD -0.655).
Aligns by position after sorting by Date (saved file is integer-indexed, dateless).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd
from src.portfolio.construction import build_daily_weights_from_panel
from src.backtest.engine import backtest_cross_sectional_strategy
from src.utils.metrics import sharpe_ratio, max_drawdown

ROOT = Path("/Users/rawls/quant-lab"); PROC = ROOT / "data/processed"
EXP004 = ROOT / "experiments/completed/exp_004_project04_final"
key = ["Date", "Ticker"]

v1 = pd.read_csv(PROC / "v1.csv"); v1["Date"] = pd.to_datetime(v1["Date"])
v2 = pd.read_csv(PROC / "v2.csv"); v2["Date"] = pd.to_datetime(v2["Date"])
saved = pd.read_csv(EXP004 / "strategy_timeseries/ls_20pct.csv")["portfolio_return"].to_numpy()

c = v1[key + ["fwd_ret_5", "pred_flipped"]].rename(columns={"pred_flipped": "signal_v1"}).merge(
    v2[key + ["pred"]].rename(columns={"pred": "signal_v2"}), on=key, how="inner")
for s in ["signal_v1", "signal_v2"]:
    c[f"{s}_z"] = c.groupby("Date")[s].transform(lambda x: (x - x.mean()) / x.std())
c["combined_signal"] = c["signal_v1_z"] + c["signal_v2_z"]
# rank-threshold ±1 signal (notebook 04 ls_signal_20 style)
c["rank"] = c.groupby("Date")["combined_signal"].rank(pct=True)
c["ls_signal_20"] = 0.0
c.loc[c["rank"] >= 0.8, "ls_signal_20"] = 1.0
c.loc[c["rank"] <= 0.2, "ls_signal_20"] = -1.0


def evaluate(sig_col, method, label, scale=1.0):
    w = build_daily_weights_from_panel(c, signal_col=sig_col, method=method)
    port = backtest_cross_sectional_strategy(w, c, return_col="fwd_ret_5")
    r = port["portfolio_return"].to_numpy() * scale
    n = min(len(r), len(saved))
    corr = float(np.corrcoef(r[:n], saved[:n])[0, 1])
    md = float(np.abs(r[:n] - saved[:n]).max())
    print(f"{label:48s} Sharpe={sharpe_ratio(port['portfolio_return']):.3f} "
          f"MDD={max_drawdown(port['equity_curve']):.3f} corr={corr:.4f} maxdiff={md:.5f}")


print(f"{'SAVED ls_20pct (target)':48s} Sharpe=1.516 MDD=-0.655")
evaluate("combined_signal", "equal", "combined z-sum / equal-weight LS20")
evaluate("combined_signal", "signal", "combined z-sum / signal-weight LS20")
evaluate("ls_signal_20", "equal", "combined rank>=.8/<=.2 ±1 / equal-weight")
evaluate("ls_signal_20", "signal", "combined rank>=.8/<=.2 ±1 / signal-weight")
# single-model variants
c["sv1z"] = c["signal_v1_z"]; c["sv2z"] = c["signal_v2_z"]
evaluate("sv1z", "equal", "V1-only (flipped) / equal-weight LS20")
evaluate("sv2z", "equal", "V2-only / equal-weight LS20")
