"""Phase 6 cont'd — White's Reality Check & DSR trial-universe revalidation (old vs corrected).

Rebuild the 23-series WRC/DSR universe on the CANONICAL base (port_pre) for the overlay family
and rerun reality_check + DSR; compare to the shipped (defective-base) universe.
Writes only to exp_007_research_integrity_audit/.
"""
import json
from pathlib import Path
import numpy as np, pandas as pd, sys, glob, os
ROOT = Path("/Users/rawls/quant-lab"); sys.path.insert(0, str(ROOT))
EXP4 = ROOT/"experiments/completed/exp_004_project04_final/strategy_timeseries"
EXP5 = ROOT/"experiments/completed/exp_005_risk_engine_final"
OC   = ROOT/"experiments/completed/exp_006_deployment_overlay_challenge"
OUT  = ROOT/"experiments/completed/exp_007_research_integrity_audit"
PPY = 252
from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return
from src.statistics.white_reality_check import reality_check
from src.statistics.deflated_sharpe import deflated_sharpe_ratio, probabilistic_sharpe_ratio

# ---- canonical base ----
W = {"ls_20pct_plus_sqrt_partial_normalized":0.5,"blend_60_40_ls20_plus_ls30":0.3,"ls_30pct":0.2}
ctrl={}
for n in W:
    raw=pd.read_csv(EXP4/f"{n}.csv")["portfolio_return"].fillna(0).reset_index(drop=True)
    e=drawdown_exposure_smooth(compute_drawdown((1+raw).cumprod()),0.55,5); ctrl[n]=apply_exposure_to_return(raw,e)
port_pre=sum(W[n]*ctrl[n] for n in W)
dep=pd.read_csv(EXP5/"final_weighted_multi_strategy_portfolio_dd.csv")
pr=dep["portfolio_return"].astype(float).reset_index(drop=True); sexp=dep["portfolio_dd_exposure"].astype(float).reset_index(drop=True)
base_defect=(pr/sexp.shift(1).fillna(1.0)).reset_index(drop=True)

def vol_mult(b):
    rv=pd.Series(b).rolling(252).std()*np.sqrt(PPY); return (rv/rv.mean()).pow(0.5).clip(0.7,1.3)
def overlays(base):
    base=pd.Series(base).reset_index(drop=True); dd=compute_drawdown((1+base).cumprod()); m=vol_mult(base)
    sm=lambda f,k: drawdown_exposure_smooth(dd,f,k)
    defs=[("Smooth DD (k5, floor0.55) [config recipe]",sm(0.55,5)),
          ("DD Only (floor0.3, k5)",sm(0.3,5)),
          ("Combined DD+Vol (floor0.3, k5, clip0.5-1.3)",(m*sm(0.3,5)).clip(0.5,1.3)),
          ("Floor 0.3 (m*smooth(0.3,5), clip0.5-1.3)",(m*sm(0.3,5)).clip(0.5,1.3)),
          ("Floor 0.5 (m*smooth(0.5,5), clip0.5-1.3)",(m*sm(0.5,5)).clip(0.5,1.3)),
          ("Clip 0.5-1.2 (m*smooth(0.6,5))",(m*sm(0.6,5)).clip(0.5,1.2)),
          ("Clip 0.8-1.0 (m*smooth(0.6,5))",(m*sm(0.6,5)).clip(0.8,1.0)),
          ("DD k=1 (m*smooth(0.6,1), clip0.3-1.5)",(m*sm(0.6,1)).clip(0.3,1.5)),
          ("DD k=5 (m*smooth(0.6,5), clip0.3-1.5)",(m*sm(0.6,5)).clip(0.3,1.5))]
    return {nm: apply_exposure_to_return(base, pd.Series(e).fillna(1.0)).to_numpy() for nm,e in defs}

# Family A (raw P04) — unchanged
A = {os.path.basename(f)[:-4]: pd.read_csv(f)["portfolio_return"].to_numpy()
     for f in sorted(glob.glob(str(EXP4/"*.csv")))}
A = pd.DataFrame(A)

def build_panel(base):
    ov = overlays(base)
    # incumbent (V1 as shipped) is defect-free in both universes
    inc = pr.to_numpy()
    B = {"Deployment (incumbent, as shipped)": inc}
    B.update(ov)
    B.update({"Base (no portfolio overlay)": pd.Series(base).reset_index(drop=True).to_numpy()})
    B = pd.DataFrame(B)
    perf = pd.concat([A.iloc[1:].reset_index(drop=True).add_prefix("P04:"),
                      B.iloc[1:].reset_index(drop=True).add_prefix("P06:")], axis=1)
    return perf

perf_old = build_panel(base_defect)      # matches shipped universe
perf_new = build_panel(port_pre)         # corrected

WRC_SEED, WRC_N, BLOCKS, CANON = 20260820, 10000, [5,10,20,30,50], 20
def wrc(perf):
    r = reality_check(perf, n_resamples=WRC_N, expected_block_length=float(CANON), seed=WRC_SEED)
    return r
r_old, r_new = wrc(perf_old), wrc(perf_new)

# DSR trial variance old vs corrected (per-period Sharpes across the 23 series)
pp = lambda df: (df.mean()/df.std(ddof=1))
tv_old = float(pp(perf_old).var(ddof=1)); tv_new = float(pp(perf_new).var(ddof=1))
# V1 DSR under each trial variance (candidate under test = V1 shipped, defect-free)
v1 = pr
dsr_old = float(deflated_sharpe_ratio(v1, n_trials=100, trial_sharpe_variance=tv_old).deflated_probability)
dsr_new = float(deflated_sharpe_ratio(v1, n_trials=100, trial_sharpe_variance=tv_new).deflated_probability)

wrc_out = {
  "WRC_old_defective_universe": {"best_strategy": r_old.best_strategy, "stat": float(r_old.best_statistic), "p": float(r_old.p_value)},
  "WRC_corrected_universe":     {"best_strategy": r_new.best_strategy, "stat": float(r_new.best_statistic), "p": float(r_new.p_value)},
  "DSR_V1_trial_variance_old": tv_old, "DSR_V1_trial_variance_corrected": tv_new,
  "DSR_V1_N100_old": dsr_old, "DSR_V1_N100_corrected": dsr_new,
  "n_strategies": int(perf_old.shape[1]),
}
json.dump(wrc_out, open(OUT/"wrc_dsr_old_vs_corrected.json","w"), indent=2)
print(json.dumps(wrc_out, indent=2))
print("\nsaved ->", OUT)
