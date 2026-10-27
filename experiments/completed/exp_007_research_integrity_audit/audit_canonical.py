"""Project 07 Research-Integrity Audit — canonical reconstruction + root-cause repro.

Phases 2,3,5. Establishes the canonical source of truth for V1 / DD Only / Combined,
isolates the exact lineage defect in exp_006 load_deployment_base(), and recomputes all
headline metrics old-vs-corrected. Writes ONLY to exp_007_research_integrity_audit/.
Reads previously-shipped artifacts read-only; nothing upstream is modified.
"""
import json, hashlib
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path("/Users/rawls/quant-lab")
EXP4 = ROOT / "experiments/completed/exp_004_project04_final/strategy_timeseries"
EXP5 = ROOT / "experiments/completed/exp_005_risk_engine_final"
EXP6 = ROOT / "experiments/completed/exp_006_deployment_candidate_tournament"
EXP7 = ROOT / "experiments/completed/exp_007_candidate_net_validation"
OUT  = ROOT / "experiments/completed/exp_007_research_integrity_audit"
OUT.mkdir(parents=True, exist_ok=True)
PPY = 252

import sys; sys.path.insert(0, str(ROOT))
from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return

def md5(a):
    return hashlib.md5(np.ascontiguousarray(np.asarray(a, float)).tobytes()).hexdigest()[:16]

def cagr(r):
    r = pd.Series(r).dropna(); eq = (1+r).cumprod()
    return float(eq.iloc[-1] ** (PPY/len(r)) - 1)
def mdd(r):
    eq = (1+pd.Series(r).dropna()).cumprod(); return float((eq/eq.cummax()-1).min())
def sharpe(r):
    r = pd.Series(r).dropna(); return float(r.mean()/r.std(ddof=1)*np.sqrt(PPY))
def vol(r):
    return float(pd.Series(r).dropna().std(ddof=1)*np.sqrt(PPY))

# ============================================================================
# PHASE 2 — canonical reconstruction from earliest reliable inputs (exp_004)
# ============================================================================
W = {"ls_20pct_plus_sqrt_partial_normalized": 0.5,
     "blend_60_40_ls20_plus_ls30": 0.3, "ls_30pct": 0.2}
STRAT_FLOOR, STRAT_K = 0.55, 5
PORT_FLOOR, PORT_K = 0.55, 5

# strategy-level smooth-DD overlay on each raw strategy, then weight -> port_pre (= exp_005 multi_ret)
controlled = {}
for name in W:
    raw = pd.read_csv(EXP4 / f"{name}.csv")["portfolio_return"].fillna(0).reset_index(drop=True)
    dd = compute_drawdown((1+raw).cumprod())
    e = drawdown_exposure_smooth(dd, floor=STRAT_FLOOR, k=STRAT_K)
    controlled[name] = apply_exposure_to_return(raw, e)
port_pre = sum(W[n]*controlled[n] for n in W)          # canonical pre-portfolio-overlay base
port_pre.name = "port_pre"

# portfolio-level overlay (V1) recomputed from canonical base
port_dd = compute_drawdown((1+port_pre).cumprod())
port_exp = drawdown_exposure_smooth(port_dd, floor=PORT_FLOOR, k=PORT_K)
v1_recon = apply_exposure_to_return(port_pre, port_exp)  # canonical V1 gross

# shipped exp_005 series
dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
pr   = dep["portfolio_return"].astype(float).reset_index(drop=True)   # shipped V1 gross
sexp = dep["portfolio_dd_exposure"].astype(float).reset_index(drop=True)  # stored (already lagged)

# ---- reconciliation identities -------------------------------------------------
recon = {}
recon["id_A_port_pre_times_stored_exp_eq_shipped_pr"] = float(np.nanmax(np.abs(
    (port_pre.to_numpy() * sexp.to_numpy()) - pr.to_numpy())))          # pr = port_pre * stored_exp ?
recon["id_B_v1_recon_vs_shipped_pr"] = float(np.nanmax(np.abs(v1_recon.to_numpy() - pr.to_numpy())))
recon["id_C_stored_exp_eq_port_exp_lag1"] = float(np.nanmax(np.abs(
    sexp.to_numpy() - port_exp.shift(1).fillna(1.0).to_numpy())))       # stored exp == port_exp.shift(1) ?
recon["md5_canonical_port_pre"] = md5(port_pre)
recon["md5_canonical_v1"] = md5(v1_recon)
recon["md5_shipped_pr"] = md5(pr)

# ============================================================================
# PHASE 3 — ROOT CAUSE: the two mutually-inconsistent recoveries in exp_006
# ============================================================================
# correct inverse (same-row stored exp):   base_correct = pr / sexp         == port_pre
# defective inverse (extra shift):          base_defect  = pr / sexp.shift(1)
base_correct = pr / sexp.replace(0, np.nan)
base_defect  = pr / sexp.shift(1).fillna(1.0)
rootcause = {
    "correct_recovery_pr_div_exp_vs_port_pre_maxabs": float(np.nanmax(np.abs(base_correct.to_numpy()-port_pre.to_numpy()))),
    "defect_recovery_pr_div_expshift1_vs_port_pre_maxabs": float(np.nanmax(np.abs(base_defect.to_numpy()-port_pre.to_numpy()))),
    "defect_spurious_factor": "base_defect[t] = port_pre[t] * stored_exp[t]/stored_exp[t-1]",
    "n_days_factor_ne_1": int(np.sum(np.abs((sexp/sexp.shift(1)).fillna(1.0)-1.0) > 1e-9)),
    "book_recovery_uses": "wide.div(exp)      (same-row, CORRECT inverse)",
    "return_recovery_uses": "pr / exp.shift(1) (extra shift, DEFECT) — inconsistent with book recovery",
}

# ============================================================================
# candidate reconstructions: DEFECTIVE path (as shipped) vs CANONICAL path
# ============================================================================
def vol_multiplier(base, window=252):
    rv = pd.Series(base).rolling(window).std()*np.sqrt(PPY)
    return (rv/rv.mean()).pow(0.5).clip(0.7, 1.3)

def challenger(base, kind):
    base = pd.Series(base).reset_index(drop=True)
    dd = compute_drawdown((1+base).cumprod())
    if kind == "V1":
        e = drawdown_exposure_smooth(dd, PORT_FLOOR, PORT_K)
    elif kind == "DD Only":
        e = drawdown_exposure_smooth(dd, 0.3, 5)
    elif kind == "Combined":
        e = (vol_multiplier(base)*drawdown_exposure_smooth(dd, 0.3, 5)).clip(0.5, 1.3)
    return apply_exposure_to_return(base, e.fillna(1.0))

# DEFECTIVE base = exp_006's base_ret (what shipped DD/Combined were built on)
base_shipped = base_defect.copy()
# CANONICAL base = port_pre (true common pre-overlay base)
cand_defect = {k: challenger(base_shipped, k) for k in ["V1","DD Only","Combined"]}
cand_canon  = {k: (v1_recon if k=="V1" else challenger(port_pre, k)) for k in ["V1","DD Only","Combined"]}

# shipped exp_007 gross series (copied from tournament candidates)
SHIP = {"V1":"v1_daily_returns.csv","DD Only":"dd_only_daily_returns.csv","Combined":"combined_dd_vol_daily_returns.csv"}
ship_gross = {k: pd.read_csv(EXP7/f)["gross_return"].to_numpy() for k,f in SHIP.items()}
ship_net   = {k: pd.read_csv(EXP7/f)["net_return"].to_numpy()   for k,f in SHIP.items()}
ship_turn  = {k: pd.read_csv(EXP7/f)["turnover"].to_numpy()     for k,f in SHIP.items()}

# verify the DEFECTIVE reconstruction reproduces the shipped series (confirms we found THE path)
repro = {k: float(np.nanmax(np.abs(cand_defect[k].to_numpy()[1:] - ship_gross[k][1:]))) for k in SHIP}

# ============================================================================
# PHASE 5 — old (shipped/defective) vs corrected (canonical) metrics
# ============================================================================
COST_BPS = 10.0
def net_from(gross, turn):
    return np.asarray(gross,float) - np.asarray(turn,float)*(COST_BPS/1e4)

rows = []
for k in ["V1","DD Only","Combined"]:
    g_old, g_new = ship_gross[k], cand_canon[k].to_numpy()
    # net: reuse shipped turnover (turnover audited separately in Phase 4)
    n_old = ship_net[k]
    n_new = net_from(g_new, ship_turn[k])
    for basis, old, new in [("gross", g_old, g_new), ("net", n_old, n_new)]:
        rows.append({"candidate":k, "basis":basis,
            "CAGR_old":cagr(old), "CAGR_new":cagr(new), "dCAGR_pp":100*(cagr(new)-cagr(old)),
            "Sharpe_old":sharpe(old), "Sharpe_new":sharpe(new), "dSharpe":sharpe(new)-sharpe(old),
            "MDD_old":mdd(old), "MDD_new":mdd(new), "dMDD_pp":100*(mdd(new)-mdd(old)),
            "Vol_old":vol(old), "Vol_new":vol(new)})
oldnew = pd.DataFrame(rows)
oldnew.to_csv(OUT/"OLD_VS_CORRECTED_RESULTS.csv", index=False)

json.dump({"phase2_reconciliation":recon, "phase3_root_cause":rootcause,
           "defective_recon_reproduces_shipped_maxabs":repro},
          open(OUT/"reconstruction_and_rootcause.json","w"), indent=2)

pd.set_option("display.width",220,"display.max_columns",30)
print("=== PHASE 2: reconciliation identities (max abs diff) ===")
for k,v in recon.items():
    if k.startswith("id_"): print(f"  {k:55s} {v:.3e}")
print("  md5 canonical port_pre:", recon["md5_canonical_port_pre"])
print("\n=== PHASE 3: root cause ===")
print(f"  correct recovery (pr/exp)        vs port_pre : {rootcause['correct_recovery_pr_div_exp_vs_port_pre_maxabs']:.3e}  (should be ~0)")
print(f"  DEFECT  recovery (pr/exp.shift1) vs port_pre : {rootcause['defect_recovery_pr_div_expshift1_vs_port_pre_maxabs']:.3e}  (large)")
print(f"  days with spurious factor != 1               : {rootcause['n_days_factor_ne_1']} / {len(pr)}")
print("\n=== defective recon reproduces SHIPPED exp_007 gross (max abs) ===")
for k,v in repro.items(): print(f"  {k:9s} {v:.3e}")
print("\n=== PHASE 5: OLD vs CORRECTED ===")
print(oldnew.round(4).to_string(index=False))
print("\nsaved ->", OUT)
