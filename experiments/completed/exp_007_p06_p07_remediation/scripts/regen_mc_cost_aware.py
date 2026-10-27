"""Remediation Phase 5 — cost-aware Monte Carlo reconciliation on the CORRECTED base.

Re-simulates the exp_007_nb03_dynamic_replay Method-A dynamic replay (identical seed/blocks/
overlay logic, importing src.statistics.simulation; the preserved script is NOT modified), then
applies a BOUNDED net-cost sensitivity.

Limitation (reported, not worked around): the synthetic paths are return-level — there is no
position book along a simulated path, so book turnover / per-name execution cost cannot be
recovered. We therefore apply each candidate's historical mean one-way cost drag as a constant
per-day haircut (bounded proxy) under trading-cost scenarios, and separately note borrow is
near common-mode. Drawdown is essentially invariant to a small constant drag; CAGR/Sharpe shift
down by the drag. True per-path trading cost would vary with simulated turnover — flagged.

Outputs: data/mc_cost_aware_A.csv  + console.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
import sys
sys.path.insert(0, str(ROOT))
from src.statistics import simulation as sim

REM = Path(__file__).resolve().parents[1]
SEED, N, PPY, CANON = 20261027, 10000, 252, 20
TS = ROOT / "experiments/completed/exp_004_project04_final/strategy_timeseries"
W = {"ls_20pct_plus_sqrt_partial_normalized": 0.5, "blend_60_40_ls20_plus_ls30": 0.3, "ls_30pct": 0.2}
raw = np.column_stack([pd.read_csv(TS / f"{n}.csv")["portfolio_return"].to_numpy() for n in W])
weights = np.array([W[n] for n in W]); T = raw.shape[0]
# historical mean one-way cost drag per candidate at 10bps (from corrected daily_returns)
EXP07 = ROOT / "experiments/completed/exp_007_candidate_net_validation"
DAILY = {"V1": "v1_daily_returns.csv", "DD Only": "dd_only_daily_returns.csv", "Combined": "combined_dd_vol_daily_returns.csv"}
DRAG10 = {k: float(pd.read_csv(EXP07 / f)["cost_drag"].mean()) for k, f in DAILY.items()}  # per-day, 10bps


def strat_overlay(paths3):
    port = np.zeros((paths3.shape[0], paths3.shape[1]))
    for j, w in enumerate(weights):
        r = paths3[:, :, j]
        e = sim.smooth_dd_exposure(sim.drawdown_paths(r), 0.55, 5)
        port += w * sim.apply_lagged_exposure(r, e)
    return port


def candidate(port_pre, kind):
    dd = sim.drawdown_paths(port_pre)
    if kind == "V1":
        e = sim.smooth_dd_exposure(dd, 0.55, 5)
    elif kind == "DD Only":
        e = sim.smooth_dd_exposure(dd, 0.3, 5)
    else:
        m = sim.rolling_vol_multiplier(port_pre, window=252)
        e = np.clip(m * sim.smooth_dd_exposure(dd, 0.3, 5), 0.5, 1.3)
    return sim.apply_lagged_exposure(port_pre, e)


def joint_base_paths(block, seed):
    rng = np.random.default_rng(seed)
    out = np.empty((N, T, 3))
    for p in range(N):
        out[p] = raw[sim.stationary_bootstrap_indices(T, float(block), rng)]
    return out


def path_stats(paths, drag=0.0):
    p = np.asarray(paths) - drag                     # constant per-day haircut (bounded proxy)
    mdd = sim.path_max_drawdown(p); cagr = sim.path_cagr(p); shp = sim.path_sharpe(p)
    return {"median_MDD": float(np.median(mdd)), "p5_MDD_worst": float(np.percentile(mdd, 5)),
            "P(MDD<-20%)": float(np.mean(mdd < -0.2)), "P(MDD<-30%)": float(np.mean(mdd < -0.3)),
            "median_CAGR": float(np.median(cagr)), "p5_CAGR": float(np.percentile(cagr, 5)),
            "median_Sharpe": float(np.nanmedian(shp))}


def main():
    base = joint_base_paths(CANON, SEED)
    pp = strat_overlay(base)
    rows = []
    for k in ["V1", "DD Only", "Combined"]:
        A = candidate(pp, k)
        gross = path_stats(A, 0.0)
        net10 = path_stats(A, DRAG10[k])            # 10bps trading, constant-drag proxy
        net20 = path_stats(A, 2 * DRAG10[k])        # 20bps bounded upper
        for scen, st, bps in (("gross", gross, 0), ("net_10bps_proxy", net10, 10), ("net_20bps_proxy", net20, 20)):
            rows.append({"candidate": k, "scenario": scen, "trade_bps": bps,
                         "ann_cost_drag": round(DRAG10[k] * PPY * (bps / 10 if bps else 0), 4), **st})
    df = pd.DataFrame(rows)
    df.to_csv(REM / "data/mc_cost_aware_A.csv", index=False)
    pd.set_option("display.width", 200, "display.max_columns", 20)
    print("=== cost-aware dynamic-replay (Method A), block=20, N=10000, seed=20261027 ===")
    print("(net = gross - constant per-day historical mean drag; bounded proxy — true per-path turnover not recoverable)")
    print(df.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
