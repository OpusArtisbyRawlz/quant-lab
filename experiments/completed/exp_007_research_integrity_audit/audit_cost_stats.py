"""Phase 4 (turnover/cost) + Phase 6 (statistical-integrity revalidation).

Recompute book turnover, 10bps cost drag, net metrics, paired block-bootstrap
significance vs V1, PSR and DSR — OLD (defective base) vs CORRECTED (canonical base).
Writes only to exp_007_research_integrity_audit/.
"""
import json
from pathlib import Path
import numpy as np, pandas as pd, sys

ROOT = Path("/Users/rawls/quant-lab"); sys.path.insert(0, str(ROOT))
EXP5 = ROOT/"experiments/completed/exp_005_risk_engine_final"
EXP6 = ROOT/"experiments/completed/exp_006_deployment_candidate_tournament"
EXP7 = ROOT/"experiments/completed/exp_007_candidate_net_validation"
OUT  = ROOT/"experiments/completed/exp_007_research_integrity_audit"
PPY, COST_BPS = 252, 10.0

from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return
from src.analysis.turnover import compute_turnover
from src.utils.metrics import sharpe_ratio
from src.statistics.deflated_sharpe import probabilistic_sharpe_ratio, deflated_sharpe_ratio

# ---- rebuild canonical base (port_pre) and both exposures -------------------
W = {"ls_20pct_plus_sqrt_partial_normalized":0.5,"blend_60_40_ls20_plus_ls30":0.3,"ls_30pct":0.2}
EXP4 = ROOT/"experiments/completed/exp_004_project04_final/strategy_timeseries"
ctrl = {}
for n in W:
    raw = pd.read_csv(EXP4/f"{n}.csv")["portfolio_return"].fillna(0).reset_index(drop=True)
    e = drawdown_exposure_smooth(compute_drawdown((1+raw).cumprod()), 0.55, 5)
    ctrl[n] = apply_exposure_to_return(raw, e)
port_pre = sum(W[n]*ctrl[n] for n in W)

dep = pd.read_csv(EXP5/"final_weighted_multi_strategy_portfolio_dd.csv")
pr   = dep["portfolio_return"].astype(float).reset_index(drop=True)
sexp = dep["portfolio_dd_exposure"].astype(float).reset_index(drop=True)
base_defect = (pr / sexp.shift(1).fillna(1.0)).reset_index(drop=True)   # exp_006 defect

wq = pd.read_csv(EXP5/"final_daily_weights.csv", parse_dates=["Date"])
wide = wq.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index()
dates = wide.index
base_book = wide.div(sexp.values, axis=0)        # correct same-row inverse (as in exp_006)

def vol_mult(base):
    rv = pd.Series(base).rolling(252).std()*np.sqrt(PPY)
    return (rv/rv.mean()).pow(0.5).clip(0.7,1.3)

def exposure_for(base, kind):
    base = pd.Series(base).reset_index(drop=True)
    dd = compute_drawdown((1+base).cumprod())
    if kind=="V1":       return drawdown_exposure_smooth(dd,0.55,5)
    if kind=="DD Only":  return drawdown_exposure_smooth(dd,0.3,5)
    if kind=="Combined": return (vol_mult(base)*drawdown_exposure_smooth(dd,0.3,5)).clip(0.5,1.3)

# ---- PHASE 4: turnover & cost drag, OLD vs CORRECTED ------------------------
def book_turnover(kind, base):
    if kind=="V1":
        bk = wide                                   # V1 uses shipped book directly (defect-free)
    else:
        e = exposure_for(base, kind).fillna(1.0)
        bk = base_book.mul(e.values, axis=0)
    return compute_turnover(bk).reset_index(drop=True)

turn_old = {k: book_turnover(k, base_defect) for k in ["V1","DD Only","Combined"]}
turn_new = {k: book_turnover(k, port_pre)    for k in ["V1","DD Only","Combined"]}
ship_turn = {k: pd.read_csv(EXP7/f)["turnover"].to_numpy()
             for k,f in {"V1":"v1_daily_returns.csv","DD Only":"dd_only_daily_returns.csv","Combined":"combined_dd_vol_daily_returns.csv"}.items()}

turn_rows=[]
for k in ["V1","DD Only","Combined"]:
    turn_rows.append({"candidate":k,
        "mean_turn_shipped":float(np.mean(ship_turn[k])),
        "mean_turn_old_recompute":float(turn_old[k].mean()),
        "mean_turn_corrected":float(turn_new[k].mean()),
        "ann_costdrag_old_pp":100*float(turn_old[k].mean())*COST_BPS/1e4*PPY,
        "ann_costdrag_corrected_pp":100*float(turn_new[k].mean())*COST_BPS/1e4*PPY})
turn_df = pd.DataFrame(turn_rows)

# ---- canonical gross/net return series --------------------------------------
def ret_for(kind, base):
    if kind=="V1" and base is port_pre:
        e = exposure_for(port_pre,"V1")
        return apply_exposure_to_return(port_pre, e)
    return apply_exposure_to_return(pd.Series(base).reset_index(drop=True), exposure_for(base,kind).fillna(1.0))

gross_new = {k: ret_for(k, port_pre).to_numpy() for k in ["V1","DD Only","Combined"]}
ship = {"V1":"v1_daily_returns.csv","DD Only":"dd_only_daily_returns.csv","Combined":"combined_dd_vol_daily_returns.csv"}
gross_old = {k: pd.read_csv(EXP7/ship[k])["gross_return"].to_numpy() for k in ship}
net_old   = {k: pd.read_csv(EXP7/ship[k])["net_return"].to_numpy()   for k in ship}
# corrected net uses CORRECTED turnover + corrected gross
net_new   = {k: gross_new[k] - turn_new[k].to_numpy()*(COST_BPS/1e4) for k in ship}

# ---- PHASE 6: paired block-bootstrap significance vs V1 (NB09 cell13 recipe) -
BLOCK, N_BOOT, SEED = 21, 5000, 7
n = len(gross_old["V1"]); n_blocks = int(np.ceil(n/BLOCK))
def block_idx(rng):
    starts = rng.integers(0, n, size=n_blocks)
    return np.concatenate([(np.arange(s,s+BLOCK)%n) for s in starts])[:n]
def paired_p(chal, v1):
    rng = np.random.default_rng(SEED); d = np.empty(N_BOOT)
    for b in range(N_BOOT):
        idx = block_idx(rng); d[b] = sharpe_ratio(chal[idx],PPY)-sharpe_ratio(v1[idx],PPY)
    raw_p = (int(np.sum(d<=0))+1)/(len(d)+1)
    return raw_p, float(d.mean()), float(np.percentile(d,2.5)), float(np.percentile(d,97.5))

sig_rows=[]
for basis, G in [("gross_old",gross_old),("gross_corrected",gross_new),
                 ("net_old",net_old),("net_corrected",net_new)]:
    v1 = G["V1"]
    for k in ["DD Only","Combined"]:
        p,m,lo,hi = paired_p(G[k], v1)
        sig_rows.append({"basis":basis,"challenger":k,
            "SR_V1":sharpe_ratio(v1,PPY),"SR_chal":sharpe_ratio(G[k],PPY),
            "dSharpe":sharpe_ratio(G[k],PPY)-sharpe_ratio(v1,PPY),
            "raw_p":p,"ci_lo":lo,"ci_hi":hi,
            "reject@0.05_raw": p<=0.05, "reject@bonf_m2": p<=0.025})
sig_df = pd.DataFrame(sig_rows)

# ---- PSR / DSR old vs corrected ---------------------------------------------
V_TRIALS = 4.920e-4
psr_rows=[]
for k in ["V1","DD Only","Combined"]:
    for basis, old, new in [("net", net_old[k], net_new[k])]:
        psr_rows.append({"candidate":k,
            "PSR0_old":float(probabilistic_sharpe_ratio(pd.Series(old),benchmark_sharpe=0.0)),
            "PSR0_new":float(probabilistic_sharpe_ratio(pd.Series(new),benchmark_sharpe=0.0)),
            "DSR_N100_old":float(deflated_sharpe_ratio(pd.Series(old),n_trials=100,trial_sharpe_variance=V_TRIALS).deflated_probability),
            "DSR_N100_new":float(deflated_sharpe_ratio(pd.Series(new),n_trials=100,trial_sharpe_variance=V_TRIALS).deflated_probability)})
psr_df = pd.DataFrame(psr_rows)

turn_df.to_csv(OUT/"COST_AND_TURNOVER_AUDIT.csv", index=False)
sig_df.to_csv(OUT/"significance_old_vs_corrected.csv", index=False)
psr_df.to_csv(OUT/"psr_dsr_old_vs_corrected.csv", index=False)

pd.set_option("display.width",220,"display.max_columns",30)
print("=== PHASE 4: turnover & cost drag ===")
print(turn_df.round(4).to_string(index=False))
print("\n=== PHASE 6: paired significance vs V1 (block=21, Nboot=5000, seed=7) ===")
print(sig_df.round(4).to_string(index=False))
print("\n=== PSR / DSR (net) old vs corrected ===")
print(psr_df.round(4).to_string(index=False))
print("\nsaved ->", OUT)
