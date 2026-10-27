"""Phase 2 — Exact reproduction of the ACTUAL Project 04 forecasting model.

The production P04 alpha is a blend of two OLS (sklearn LinearRegression) models:
  V1: 11 features on project_04_features.csv, predictions SIGN-FLIPPED (raw IC was negative).
  V2: 13 features on project_04_features_v2.csv, predictions used as-is.
Both trained on a single static split (train Date<2016-01-01, test>=2016-01-01).
The shipped signal = per-date z(signal_v1=pred_flipped) + z(signal_v2=pred) -> equal-weight LS20%.

This script re-fits both OLS models from the feature CSVs and the notebook-exact feature
lists/split, then checks the re-fitted predictions against the SAVED predictions in
data/processed/v1.csv and v2.csv (the artifacts notebook 04 consumes). It also rebuilds the
combined LS20% portfolio with the real src pipeline and compares it to the saved
exp_004 strategy_timeseries/ls_20pct.csv.

No model/parameter is changed. OLS is deterministic (no RNG).
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from src.signals.ranking import standardize_signal
from src.portfolio.construction import build_daily_weights_from_panel
from src.backtest.engine import backtest_cross_sectional_strategy
from src.utils.metrics import sharpe_ratio, max_drawdown

ROOT = Path("/Users/rawls/quant-lab")
PROC = ROOT / "data/processed"
EXP004 = ROOT / "experiments/completed/exp_004_project04_final"
OUT = ROOT / "experiments/completed/exp_007_full_pipeline_validation"

SPLIT = "2016-01-01"
FEAT_V1 = ["ret_1", "ret_5", "ret_10", "ret_20", "vol_5", "vol_20",
           "ma_10_ratio", "ma_20_ratio", "ma_50_ratio", "dollar_vol", "vol_z_20"]
FEAT_V2 = ["ret_1", "ret_5", "ret_10", "ret_20", "ret_60", "ret_120", "vol_5", "vol_20",
           "ma_10_ratio", "ma_20_ratio", "ma_50_ratio", "dollar_vol", "vol_z_20"]


def fit_ols(features_csv: str, feat_cols, flip: bool):
    """Replicate notebook 03 exactly: sort, static split, OLS fit, predict test."""
    df = pd.read_csv(PROC / features_csv)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(["Date", "Ticker"]).copy()
    train = df["Date"] < SPLIT
    test = df["Date"] >= SPLIT
    m = LinearRegression()
    m.fit(df.loc[train, feat_cols], df.loc[train, "fwd_ret_5"])
    pred = m.predict(df.loc[test, feat_cols])
    dft = df.loc[test].copy()
    dft["pred"] = pred
    if flip:
        dft["pred_flipped"] = -dft["pred"]
    return m, dft


def main():
    report = {}

    # ---- V1 reproduction vs saved v1.csv ----
    _, v1_repro = fit_ols("project_04_features.csv", FEAT_V1, flip=True)
    v1_saved = pd.read_csv(PROC / "v1.csv")
    v1_saved["Date"] = pd.to_datetime(v1_saved["Date"])
    key = ["Date", "Ticker"]
    j1 = v1_repro[key + ["pred", "pred_flipped"]].merge(
        v1_saved[key + ["pred", "pred_flipped"]], on=key, suffixes=("_repro", "_saved"))
    report["v1"] = {
        "saved_rows": int(len(v1_saved)), "test_rows": int(len(v1_repro)), "matched_rows": int(len(j1)),
        "max_abs_pred_diff": float((j1["pred_repro"] - j1["pred_saved"]).abs().max()),
        "max_abs_flip_diff": float((j1["pred_flipped_repro"] - j1["pred_flipped_saved"]).abs().max()),
    }

    # ---- V2 reproduction vs saved v2.csv ----
    _, v2_repro = fit_ols("project_04_features_v2.csv", FEAT_V2, flip=False)
    v2_saved = pd.read_csv(PROC / "v2.csv")
    v2_saved["Date"] = pd.to_datetime(v2_saved["Date"])
    j2 = v2_repro[key + ["pred"]].merge(v2_saved[key + ["pred"]], on=key, suffixes=("_repro", "_saved"))
    report["v2"] = {
        "saved_rows": int(len(v2_saved)), "test_rows": int(len(v2_repro)), "matched_rows": int(len(j2)),
        "max_abs_pred_diff": float((j2["pred_repro"] - j2["pred_saved"]).abs().max()),
    }

    # ---- Combined LS20% portfolio rebuilt with real src pipeline ----
    # signal_v1 = pred_flipped (saved), signal_v2 = pred (saved); per-date z; sum; equal-weight LS20.
    c = v1_saved[key + ["fwd_ret_5", "pred_flipped"]].rename(columns={"pred_flipped": "signal_v1"}).merge(
        v2_saved[key + ["pred"]].rename(columns={"pred": "signal_v2"}), on=key, how="inner")
    for s in ["signal_v1", "signal_v2"]:
        c[f"{s}_z"] = c.groupby("Date")[s].transform(lambda x: (x - x.mean()) / x.std())
    c["combined_signal"] = c["signal_v1_z"] + c["signal_v2_z"]
    w = build_daily_weights_from_panel(c, signal_col="combined_signal", date_col="Date", asset_col="Ticker")
    port = backtest_cross_sectional_strategy(w, c, return_col="fwd_ret_5")
    repro_metrics = {"sharpe": float(sharpe_ratio(port["portfolio_return"])),
                     "mdd": float(max_drawdown(port["equity_curve"])),
                     "n_days": int(len(port))}

    # saved ls_20pct timeseries (integer-indexed; compare on sorted portfolio_return series)
    saved_ls = pd.read_csv(EXP004 / "strategy_timeseries/ls_20pct.csv")
    saved_ret = saved_ls["portfolio_return"].to_numpy()
    repro_ret = port["portfolio_return"].to_numpy()
    n = min(len(saved_ret), len(repro_ret))
    aligned_max_diff = float(np.abs(saved_ret[:n] - repro_ret[:n]).max()) if n else None
    report["combined_ls20"] = {
        "repro": repro_metrics,
        "saved_rows": int(len(saved_ls)), "repro_rows": int(len(port)),
        "saved_sharpe_ref": 1.516, "saved_mdd_ref": -0.655,
        "aligned_first_n": n, "aligned_max_abs_return_diff": aligned_max_diff,
        "return_corr": float(np.corrcoef(saved_ret[:n], repro_ret[:n])[0, 1]) if n else None,
    }

    (OUT / "data").mkdir(parents=True, exist_ok=True)
    port.to_csv(OUT / "data/p2_combined_ls20_reconstructed.csv", index=False)
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "reports/_p2_reproduction.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
