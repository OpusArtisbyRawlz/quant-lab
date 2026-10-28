"""Phase 4 — Monte Carlo overlay-integrity validation.

Method B (what NB03 does): resample the ALREADY risk-controlled strategy returns.
Method A (this experiment): resample the *base* (pre-overlay) return, then DYNAMICALLY
re-apply the drawdown-exposure overlay rule path-by-path with 1-day lag (no look-ahead),
exactly as shipped (verified to reproduce the historical strategy to 1e-15).

Saves results to the exp_007_garch_volatility_persistence experiment directory.
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
from src.statistics import simulation as sim

ROOT = Path("/Users/rawls/quant-lab")
OUT = ROOT / "experiments/completed/exp_007_garch_volatility_persistence"
SEED, N, PPY = 20261023, 10000, 252

# ---- recover base (pre-overlay) return (same-row inverse; exp already lagged) ----
d = pd.read_csv(ROOT / "experiments/completed/exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv")
pr = d["portfolio_return"].astype(float); exp = d["portfolio_dd_exposure"].astype(float)
base_ret = (pr / exp).to_numpy()              # same-row inverse (exp already lagged; see exp_007_research_integrity_audit)
H = base_ret.size

def overlay_replay_mdd(base_paths, floor, k, *, vol_clip=None):
    """Dynamically re-apply the shipped smooth-DD overlay to each simulated base path.

    exposure_t = floor + (1-floor)*exp(-k*|dd_t|),  dd on the BASE equity (as shipped),
    applied with a 1-day lag. Optional vol multiplier (Combined): m=(rv/mean(rv))**.5
    clipped, then (m*smooth).clip(*vol_clip). Returns overlaid-path max drawdowns.
    """
    P, T = base_paths.shape
    eq = np.cumprod(1.0 + base_paths, axis=1)
    run_max = np.maximum.accumulate(eq, axis=1)
    dd = eq / run_max - 1.0
    e = floor + (1 - floor) * np.exp(-k * np.abs(dd))
    if vol_clip is not None:
        # rolling 252 realized vol, normalised by each path's own mean (flagged look-ahead)
        s = pd.DataFrame(base_paths.T)
        rv = (s.rolling(PPY).std() * np.sqrt(PPY))
        m = ((rv / rv.mean()) ** 0.5).clip(0.7, 1.3).to_numpy().T
        m = np.nan_to_num(m, nan=1.0)
        e = np.clip(m * e, vol_clip[0], vol_clip[1])
    e_lag = np.empty_like(e); e_lag[:, 0] = 1.0; e_lag[:, 1:] = e[:, :-1]
    overl = base_paths * e_lag
    oeq = np.cumprod(1.0 + overl, axis=1)
    return (oeq / np.maximum.accumulate(oeq, axis=1) - 1.0).min(axis=1)

# ---- simulate base paths (dependence-preserving block bootstrap) ----
base_paths = sim.block_bootstrap_paths(base_ret, H, N, 20.0, np.random.default_rng(SEED))

configs = {"DD Only": dict(floor=0.3, k=5, vol_clip=None),
           "Combined DD+Vol": dict(floor=0.3, k=5, vol_clip=(0.5, 1.3))}
net = {"DD Only": "dd_only_daily_returns.csv", "Combined DD+Vol": "combined_dd_vol_daily_returns.csv"}

rows = []
for name, cfg in configs.items():
    # Method A: dynamic overlay replay on simulated base paths
    mdd_A = overlay_replay_mdd(base_paths, cfg["floor"], cfg["k"], vol_clip=cfg["vol_clip"])
    # Method B: resample the realized post-overlay net returns directly (NB03 approach)
    real_net = pd.read_csv(ROOT / f"experiments/completed/exp_007_candidate_net_validation/{net[name]}")["net_return"].to_numpy()
    paths_B = sim.block_bootstrap_paths(real_net, H, N, 20.0, np.random.default_rng(SEED))
    mdd_B = sim.path_max_drawdown(paths_B)
    eq = np.cumprod(1 + real_net); hist_mdd = float((eq / np.maximum.accumulate(eq) - 1).min())
    rows.append({"strategy": name, "hist_MDD": hist_mdd,
                 "A_dynamic_med_MDD": float(np.median(mdd_A)), "A_dynamic_p5_MDD": float(np.percentile(mdd_A, 5)),
                 "A_P(MDD<-20)": float(np.mean(mdd_A < -0.2)), "A_P(MDD<-30)": float(np.mean(mdd_A < -0.3)),
                 "B_direct_med_MDD": float(np.median(mdd_B)), "B_direct_p5_MDD": float(np.percentile(mdd_B, 5)),
                 "B_P(MDD<-20)": float(np.mean(mdd_B < -0.2)), "B_P(MDD<-30)": float(np.mean(mdd_B < -0.3))})

tbl = pd.DataFrame(rows)
tbl.to_csv(OUT / "overlay_replay_A_vs_B.csv", index=False)
pd.set_option("display.width", 200, "display.max_columns", 30)
print("===== PHASE 4: DYNAMIC OVERLAY REPLAY (A) vs DIRECT RESAMPLE (B) — MDD =====")
print(tbl.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print("\nInterpretation: B resamples already risk-controlled returns; A regenerates the base path and lets")
print("the drawdown-exposure overlay act dynamically (de-risking into drawdowns) as it would live.")
print("saved to", OUT / "overlay_replay_A_vs_B.csv")
