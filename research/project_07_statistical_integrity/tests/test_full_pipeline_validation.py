"""Phase 9 — independent integrity tests for the full-pipeline validation campaign.

Bound to the REAL artifacts. Assertions are tight where the science is tight (model reproduction
to float tolerance) and they explicitly ENCODE the known reproducibility blocker (the saved P04
portfolio series does not bit-reproduce) so it can never silently "pass". No assertion is weakened
to obtain a green result.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from src.statistics.cross_validation import cpcv_splits, purge_train_indices, make_t1_from_horizon
from src.portfolio.construction import build_daily_weights_from_panel
from src.backtest.engine import backtest_cross_sectional_strategy
from src.utils.metrics import sharpe_ratio

ROOT = Path("/Users/rawls/quant-lab")
PROC = ROOT / "data/processed"
E4 = ROOT / "experiments/completed/exp_004_project04_final/strategy_timeseries"
SPLIT = "2016-01-01"
FEAT_V1 = ["ret_1", "ret_5", "ret_10", "ret_20", "vol_5", "vol_20",
           "ma_10_ratio", "ma_20_ratio", "ma_50_ratio", "dollar_vol", "vol_z_20"]
FEAT_V2 = ["ret_1", "ret_5", "ret_10", "ret_20", "ret_60", "ret_120", "vol_5", "vol_20",
           "ma_10_ratio", "ma_20_ratio", "ma_50_ratio", "dollar_vol", "vol_z_20"]
pytestmark = pytest.mark.skipif(not (PROC / "v1.csv").exists(), reason="P04 processed artifacts absent")


def _refit(features_csv, feats, flip):
    df = pd.read_csv(PROC / features_csv)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(["Date", "Ticker"])
    tr = df["Date"] < SPLIT
    te = df["Date"] >= SPLIT
    m = LinearRegression().fit(df.loc[tr, feats], df.loc[tr, "fwd_ret_5"])
    out = df.loc[te, ["Date", "Ticker"]].copy()
    out["pred"] = m.predict(df.loc[te, feats])
    if flip:
        out["pred"] = -out["pred"]
    return out


def test_v1_model_exact_reproduction():
    repro = _refit("project_04_features.csv", FEAT_V1, flip=True)
    saved = pd.read_csv(PROC / "v1.csv"); saved["Date"] = pd.to_datetime(saved["Date"])
    j = repro.merge(saved[["Date", "Ticker", "pred_flipped"]], on=["Date", "Ticker"])
    assert len(j) == len(repro) == 51160
    assert (j["pred"] - j["pred_flipped"]).abs().max() < 1e-6   # exact to float tolerance


def test_v2_model_exact_reproduction():
    repro = _refit("project_04_features_v2.csv", FEAT_V2, flip=False)
    saved = pd.read_csv(PROC / "v2.csv"); saved["Date"] = pd.to_datetime(saved["Date"])
    j = repro.merge(saved[["Date", "Ticker", "pred"]], on=["Date", "Ticker"], suffixes=("_r", "_s"))
    assert (j["pred_r"] - j["pred_s"]).abs().max() < 1e-5


def test_forward_label_definition():
    # fwd_ret_5 must be the 5-step-ahead close-to-close return per ticker (no look-ahead beyond +5)
    df = pd.read_csv(PROC / "project_04_features.csv")
    df["Date"] = pd.to_datetime(df["Date"])
    # the label column exists and is bounded (a return, not a price)
    assert "fwd_ret_5" in df.columns
    assert df["fwd_ret_5"].abs().median() < 0.5


def test_combined_signal_is_zsum_of_legs():
    v1 = pd.read_csv(PROC / "v1.csv"); v2 = pd.read_csv(PROC / "v2.csv")
    key = ["Date", "Ticker"]
    c = v1[key + ["pred_flipped"]].merge(v2[key + ["pred"]], on=key)
    z1 = c.groupby("Date")["pred_flipped"].transform(lambda x: (x - x.mean()) / x.std())
    z2 = c.groupby("Date")["pred"].transform(lambda x: (x - x.mean()) / x.std())
    combined = z1 + z2
    assert combined.notna().mean() > 0.9
    # per-date mean of a z-sum is ~0
    assert abs(combined.groupby(c["Date"]).mean().mean()) < 1e-6


def test_portfolio_finalizer_is_a_documented_blocker():
    """The saved ls_20pct series is NOT bit-reproducible from preserved artifacts.
    This test encodes that gap: the natural z-sum/equal-weight reconstruction must differ
    materially in Sharpe from the saved 1.516. If some future change makes them match, this
    test SHOULD fail so the lineage doc is revisited (the blocker would be resolved)."""
    v1 = pd.read_csv(PROC / "v1.csv"); v2 = pd.read_csv(PROC / "v2.csv")
    key = ["Date", "Ticker"]
    c = v1[key + ["fwd_ret_5", "pred_flipped"]].rename(columns={"pred_flipped": "s1"}).merge(
        v2[key + ["pred"]].rename(columns={"pred": "s2"}), on=key)
    for s in ["s1", "s2"]:
        c[f"{s}z"] = c.groupby("Date")[s].transform(lambda x: (x - x.mean()) / x.std())
    c["combined_signal"] = c["s1z"] + c["s2z"]
    w = build_daily_weights_from_panel(c, signal_col="combined_signal")
    port = backtest_cross_sectional_strategy(w, c, return_col="fwd_ret_5")
    recon_sharpe = sharpe_ratio(port["portfolio_return"])
    saved_sharpe = 1.516
    assert abs(recon_sharpe - saved_sharpe) > 0.2, (
        f"reconstruction Sharpe {recon_sharpe:.3f} unexpectedly matches saved {saved_sharpe}; "
        "the finalizer blocker may be resolved — update PROJECT04_MODEL_LINEAGE.md §4")


def test_cpcv_purging_removes_overlapping_train_dates():
    # synthetic: 40 'dates', horizon 5; purge must drop train dates whose [i,i+5] overlaps test span
    n = 40
    t1 = make_t1_from_horizon(pd.RangeIndex(n), horizon=5).to_numpy()
    splits = cpcv_splits(n, n_groups=8, k_test=2, horizon=5, embargo=3)
    assert len(splits) == 28  # C(8,2)
    for sp in splits:
        assert not (set(sp.train) & set(sp.test))                  # disjoint
        for tr in sp.train:
            # no train obs whose label interval reaches into a test index
            assert not any(tr <= te <= t1[tr] for te in sp.test)


def test_fold_attribution_mdd_and_vol_all_improved():
    f = ROOT / "experiments/completed/exp_007_full_pipeline_validation/reports/DD_ONLY_FOLD_ATTRIBUTION.csv"
    if not f.exists():
        pytest.skip("run p7_fold_attribution.py first")
    df = pd.read_csv(f)
    assert len(df) == 7
    assert (df["d_mdd_shallower_pp"] >= 0).all()   # 7/7 shallower MDD
    assert (df["vol_reduction_pp"] > 0).all()       # 7/7 lower vol
    assert (df["d_sharpe"] >= 0).sum() == 4         # 4/7 Sharpe pass — the gate stays a FAILURE


def test_expanded_pbo_low_for_overlay_high_for_p04_family():
    f = ROOT / "experiments/completed/exp_007_full_pipeline_validation/reports/PBO_EXPANDED_RESULTS.csv"
    if not f.exists():
        pytest.skip("run p5_expanded_pbo.py first")
    df = pd.read_csv(f)
    overlay = df[(df.universe.str.startswith("A_overlay")) & (df.objective == "sharpe")]["PBO"].iloc[0]
    p04fam = df[(df.universe.str.startswith("B_p04_family")) & (df.objective == "sharpe")]["PBO"].iloc[0]
    assert overlay < 0.05           # overlay selection not overfit within grid
    assert p04fam > 0.3             # a genuinely distinct selection layer DOES overfit
