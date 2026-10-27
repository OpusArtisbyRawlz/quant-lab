"""Project 07 NB03 — complete dynamic Monte Carlo overlay replay (V1 / DD Only / Combined).

Underlying pre-exposure alpha = the 3 raw Project-04 strategy returns (shared-index block
bootstrap preserves cross-strategy dependence). All exposure layers are RECOMPUTED from the
simulated states (strategy-level smooth-DD x3, then weight, then portfolio-level overlay);
historical exposure decisions are never reused. Method A = dynamic replay; Method B = direct
resample of the shipped risk-controlled returns (NB03's approach). Common seeds/blocks.

Non-overwriting: writes only to exp_007_nb03_dynamic_replay/.
"""
import json, dataclasses
from pathlib import Path
from datetime import datetime, timezone
import numpy as np, pandas as pd
from scipy import stats as scistats
from src.statistics import simulation as sim

ROOT = Path("/Users/rawls/quant-lab")
OUT = ROOT / "experiments/completed/exp_007_nb03_dynamic_replay"
OUT.mkdir(parents=True, exist_ok=True)
SEED, N, PPY = 20261027, 10000, 252
BLOCKS, CANON = [5, 10, 20, 30, 50], 20

# ---------------- underlying alpha ----------------
TS = ROOT / "experiments/completed/exp_004_project04_final/strategy_timeseries"
W = {"ls_20pct_plus_sqrt_partial_normalized": 0.5, "blend_60_40_ls20_plus_ls30": 0.3, "ls_30pct": 0.2}
raw = np.column_stack([pd.read_csv(TS / f"{n}.csv")["portfolio_return"].to_numpy() for n in W])
names = list(W); weights = np.array([W[n] for n in names]); T = raw.shape[0]

STRAT_FLOOR, STRAT_K, PORT_K = 0.55, 5, 5

def strat_overlay(paths3):
    """Apply strategy-level smooth-DD (0.55,5) to each strategy path, weight -> port_pre."""
    port = np.zeros((paths3.shape[0], paths3.shape[1]))
    for j, w in enumerate(weights):
        r = paths3[:, :, j]
        e = sim.smooth_dd_exposure(sim.drawdown_paths(r), STRAT_FLOOR, STRAT_K)
        port += w * sim.apply_lagged_exposure(r, e)
    return port

def candidate(port_pre, kind):
    dd = sim.drawdown_paths(port_pre)
    if kind == "V1":
        e = sim.smooth_dd_exposure(dd, 0.55, PORT_K)
    elif kind == "DD Only":
        e = sim.smooth_dd_exposure(dd, 0.3, PORT_K)
    elif kind == "Combined":
        m = sim.rolling_vol_multiplier(port_pre, window=252)
        e = np.clip(m * sim.smooth_dd_exposure(dd, 0.3, PORT_K), 0.5, 1.3)
    return sim.apply_lagged_exposure(port_pre, e)

# ---------------- STEP 2: historical reconstruction fidelity ----------------
hist3 = raw[None, :, :]                      # 1 path = history
port_pre_hist = strat_overlay(hist3)
EXP7 = ROOT / "experiments/completed/exp_007_candidate_net_validation"
ship = {"V1": "v1_daily_returns.csv", "DD Only": "dd_only_daily_returns.csv", "Combined": "combined_dd_vol_daily_returns.csv"}
recon = {}
for k, f in ship.items():
    r_recon = candidate(port_pre_hist, k)[0]
    r_ship = pd.read_csv(EXP7 / f)["gross_return"].to_numpy()
    recon[k] = {"max_abs_diff_vs_shipped_gross": float(np.nanmax(np.abs(r_recon - r_ship))),
                "recon_CAGR": float((1 + r_recon[~np.isnan(r_recon)]).prod() ** (PPY / np.sum(~np.isnan(r_recon))) - 1),
                "shipped_CAGR": float((1 + r_ship).prod() ** (PPY / len(r_ship)) - 1)}
json.dump(recon, open(OUT / "reconstruction_fidelity.json", "w"), indent=2)

# ---------------- STEP 3-5: dynamic replay (A) vs direct resample (B) ----------------
def wilson(p, n, z=1.96):
    if n == 0: return (np.nan, np.nan)
    d = 1 + z*z/n; c = p + z*z/(2*n); h = z*np.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c-h)/d, (c+h)/d)

def metrics(paths, label):
    mdd = sim.path_max_drawdown(paths); cagr = sim.path_cagr(paths); shp = sim.path_sharpe(paths)
    uw = sim.path_max_underwater_days(paths)
    p20, p30 = float(np.mean(mdd < -0.2)), float(np.mean(mdd < -0.3))
    lo20, hi20 = wilson(p20, len(mdd)); lo30, hi30 = wilson(p30, len(mdd))
    return {"method": label, "median_MDD": float(np.median(mdd)),
            "MDD_p95(worst)": float(np.percentile(mdd, 5)), "MDD_p75": float(np.percentile(mdd, 25)),
            "MDD_p25": float(np.percentile(mdd, 75)), "MDD_p05(best)": float(np.percentile(mdd, 95)),
            "P(MDD<-20%)": p20, "P(MDD<-20%)_CI": f"[{lo20:.3f},{hi20:.3f}]",
            "P(MDD<-30%)": p30, "P(MDD<-30%)_CI": f"[{lo30:.3f},{hi30:.3f}]",
            "median_CAGR": float(np.median(cagr)), "p5_CAGR": float(np.percentile(cagr, 5)),
            "median_Sharpe": float(np.nanmedian(shp)),
            "median_recovery_days": float(np.median(uw)), "p95_recovery_days": float(np.percentile(uw, 95))}

# shared-index joint block bootstrap of the 3 raw strategies (preserve dependence)
def joint_base_paths(block, seed):
    rng = np.random.default_rng(seed)
    out = np.empty((N, T, 3))
    for p in range(N):
        idx = sim.stationary_bootstrap_indices(T, float(block), rng)
        out[p] = raw[idx]
    return out

rows = []
# canonical block
base_A = joint_base_paths(CANON, SEED)
port_pre_A = strat_overlay(base_A)
for k in ["V1", "DD Only", "Combined"]:
    A = candidate(port_pre_A, k)
    rA = metrics(A, "A dynamic replay"); rA["strategy"] = k; rA["block"] = CANON
    rows.append(rA)
    # Method B: resample shipped risk-controlled gross returns directly
    rb = pd.read_csv(EXP7 / ship[k])["gross_return"].to_numpy()
    B = sim.block_bootstrap_paths(rb, T, N, float(CANON), np.random.default_rng(SEED))
    rB = metrics(B, "B direct resample"); rB["strategy"] = k; rB["block"] = CANON
    rows.append(rB)
compare = pd.DataFrame(rows)
compare.to_csv(OUT / "dynamic_replay_A_vs_B.csv", index=False)

# ---------------- STEP 6: block-length sensitivity (dynamic A, median & P(MDD<-30)) ----------------
sens = []
for block in BLOCKS:
    bp = joint_base_paths(block, SEED); pp = strat_overlay(bp)
    for k in ["V1", "DD Only", "Combined"]:
        A = candidate(pp, k); mdd = sim.path_max_drawdown(A)
        sens.append({"strategy": k, "block": block, "median_MDD": float(np.median(mdd)),
                     "P(MDD<-30%)": float(np.mean(mdd < -0.3)),
                     "MDD_p5(worst)": float(np.percentile(mdd, 5))})
sens_tbl = pd.DataFrame(sens)
sens_tbl.to_csv(OUT / "block_sensitivity.csv", index=False)

# ---------------- report to console ----------------
pd.set_option("display.width", 240, "display.max_columns", 40)
print("=== STEP 2: historical reconstruction fidelity (gross) ===")
for k, v in recon.items():
    print(f"  {k:9s} max|diff|={v['max_abs_diff_vs_shipped_gross']:.2e}  CAGR recon={v['recon_CAGR']:.4f} shipped={v['shipped_CAGR']:.4f}")
print("\n=== STEP 5: DYNAMIC REPLAY (A) vs DIRECT RESAMPLE (B), block=20 ===")
cols = ["strategy","method","median_MDD","MDD_p95(worst)","P(MDD<-20%)","P(MDD<-20%)_CI",
        "P(MDD<-30%)","P(MDD<-30%)_CI","median_CAGR","median_Sharpe","median_recovery_days"]
print(compare[cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print("\n=== STEP 6: BLOCK SENSITIVITY (dynamic A) ===")
print(sens_tbl.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

# ---------------- config + evidence ----------------
config = {"experiment": "exp_007_nb03_dynamic_replay", "seed": SEED, "n_paths": N, "horizon": T,
          "canonical_block": CANON, "blocks": BLOCKS,
          "underlying_alpha": {n: W[n] for n in W},
          "underlying_source": "exp_004_project04_final/strategy_timeseries/*.csv (portfolio_return)",
          "overlay_rules": {"strategy_level": "smooth_dd floor0.55 k5 (per strategy, lag1)",
                            "portfolio_level": {"V1": "smooth_dd floor0.55 k5",
                                                "DD Only": "smooth_dd floor0.3 k5",
                                                "Combined": "(vol_mult*smooth_dd floor0.3 k5).clip(0.5,1.3)"},
                            "lag": "exposure applied t-1 -> t (no look-ahead), matches src.risk.drawdown"},
          "method_A": "dynamic replay on recomputed exposure from simulated states",
          "method_B": "direct block-bootstrap resample of shipped risk-controlled gross returns",
          "cost": "comparison on GROSS (MDD is cost-insensitive); net cost not simulated (book turnover unavailable)",
          "non_overwriting": "exp_007_candidate_net_validation and NB03 untouched"}
json.dump(config, open(OUT / "config.json", "w"), indent=2)
print("\nsaved to", OUT)
