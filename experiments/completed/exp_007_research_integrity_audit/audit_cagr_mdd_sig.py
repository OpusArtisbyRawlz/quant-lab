"""Phase 6 — paired CAGR & MDD significance vs V1, OLD vs CORRECTED (shipped recipe:
block=20, n_boot=10000, seed=20260820, shared block indices, net returns, m=2)."""
import json
from pathlib import Path
import numpy as np, pandas as pd, sys
ROOT=Path("/Users/rawls/quant-lab"); sys.path.insert(0,str(ROOT))
EXP4=ROOT/"experiments/completed/exp_004_project04_final/strategy_timeseries"
EXP5=ROOT/"experiments/completed/exp_005_risk_engine_final"
EXP7=ROOT/"experiments/completed/exp_007_candidate_net_validation"
OUT=ROOT/"experiments/completed/exp_007_research_integrity_audit"
PPY=252; COST_BPS=10.0
from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return
from src.analysis.turnover import compute_turnover

W={"ls_20pct_plus_sqrt_partial_normalized":0.5,"blend_60_40_ls20_plus_ls30":0.3,"ls_30pct":0.2}
ctrl={}
for n in W:
    raw=pd.read_csv(EXP4/f"{n}.csv")["portfolio_return"].fillna(0).reset_index(drop=True)
    e=drawdown_exposure_smooth(compute_drawdown((1+raw).cumprod()),0.55,5); ctrl[n]=apply_exposure_to_return(raw,e)
port_pre=sum(W[n]*ctrl[n] for n in W)
dep=pd.read_csv(EXP5/"final_weighted_multi_strategy_portfolio_dd.csv")
pr=dep["portfolio_return"].astype(float).reset_index(drop=True); sexp=dep["portfolio_dd_exposure"].astype(float).reset_index(drop=True)
wq=pd.read_csv(EXP5/"final_daily_weights.csv",parse_dates=["Date"])
wide=wq.pivot_table(index="Date",columns="Ticker",values="Weight").sort_index()
base_book=wide.div(sexp.values,axis=0)
def vm(b): rv=pd.Series(b).rolling(252).std()*np.sqrt(PPY); return (rv/rv.mean()).pow(0.5).clip(0.7,1.3)
def expo(b,k):
    b=pd.Series(b).reset_index(drop=True); dd=compute_drawdown((1+b).cumprod())
    if k=="V1": return drawdown_exposure_smooth(dd,0.55,5)
    if k=="DD Only": return drawdown_exposure_smooth(dd,0.3,5)
    if k=="Combined": return (vm(b)*drawdown_exposure_smooth(dd,0.3,5)).clip(0.5,1.3)
def gross(b,k):
    if k=="V1" and b is port_pre: return apply_exposure_to_return(port_pre,expo(port_pre,"V1")).to_numpy()
    return apply_exposure_to_return(pd.Series(b).reset_index(drop=True),expo(b,k).fillna(1.0)).to_numpy()
def turn(b,k):
    bk = wide if k=="V1" else base_book.mul(expo(b,k).fillna(1.0).values,axis=0)
    return compute_turnover(bk).reset_index(drop=True).to_numpy()

ship={"V1":"v1_daily_returns.csv","DD Only":"dd_only_daily_returns.csv","Combined":"combined_dd_vol_daily_returns.csv"}
net_old={k:pd.read_csv(EXP7/ship[k])["net_return"].to_numpy() for k in ship}
net_new={k: gross(port_pre,k) - turn(port_pre,k)*(COST_BPS/1e4) for k in ship}

def CAGR(r): r=pd.Series(r).dropna(); return float((1+r).cumprod().iloc[-1]**(PPY/len(r))-1)
def MDD(r): eq=(1+pd.Series(r).dropna()).cumprod(); return float((eq/eq.cummax()-1).min())

BLOCK,NB,SEED=20,10000,20260820
n=len(net_old["V1"]); nbl=int(np.ceil(n/BLOCK))
def shared_idx(rng):
    s=rng.integers(0,n,size=nbl); return np.concatenate([(np.arange(x,x+BLOCK)%n) for x in s])[:n]
def paired(metric, chal, v1):
    rng=np.random.default_rng(SEED); d=np.empty(NB)
    for b in range(NB):
        idx=shared_idx(rng); d[b]=metric(chal[idx])-metric(v1[idx])
    # one-sided: challenger better. For MDD, "better"=less negative=higher; for CAGR higher.
    raw_p=(int(np.sum(d<=0))+1)/(NB+1)
    return float(metric(chal)-metric(v1)), raw_p, float(np.percentile(d,2.5)), float(np.percentile(d,97.5))

rows=[]
for basis,NET in [("net_old",net_old),("net_corrected",net_new)]:
    for k in ["DD Only","Combined"]:
        for mname,mf in [("dCAGR",CAGR),("dMDD",MDD)]:
            obs,p,lo,hi=paired(mf,NET[k],NET["V1"])
            rows.append({"basis":basis,"challenger":k,"metric":mname,"observed":obs,
                         "raw_p":p,"ci_lo":lo,"ci_hi":hi,
                         "reject@bonf_m2(0.025)":p<=0.025,"reject@0.05":p<=0.05})
df=pd.DataFrame(rows)
df.to_csv(OUT/"cagr_mdd_significance_old_vs_corrected.csv",index=False)
pd.set_option("display.width",200,"display.max_columns",20)
print(df.round(4).to_string(index=False))
print("\nsaved ->",OUT)
