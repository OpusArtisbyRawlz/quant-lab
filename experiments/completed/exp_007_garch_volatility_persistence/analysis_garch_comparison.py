"""Project 07 GARCH volatility-persistence campaign (Phases 2-3-5).
Saves all results to a new, non-overwriting experiment directory.
"""
import json, warnings
from pathlib import Path
from datetime import datetime, timezone
import numpy as np, pandas as pd
from scipy import stats
from src.statistics import simulation as sim

ROOT = Path("/Users/rawls/quant-lab")
OUT = ROOT / "experiments/completed/exp_007_garch_volatility_persistence"
OUT.mkdir(parents=True, exist_ok=True)
SEED = 20261023
RNG = lambda: np.random.default_rng(SEED)

# ---------------- series construction ----------------
spy = pd.read_csv(ROOT / "data/raw/SPY.csv")
spy["Date"] = pd.to_datetime(spy["Date"], format="%d/%m/%Y")
spy_full = spy.sort_values("Date").set_index("Date")["Close"].pct_change().dropna()

EXP = ROOT / "experiments/completed/exp_007_candidate_net_validation"
files = {"V1": "v1_daily_returns.csv", "DD Only": "dd_only_daily_returns.csv",
         "Combined DD+Vol": "combined_dd_vol_daily_returns.csv"}
strat_net, strat_gross = {}, {}
for k, f in files.items():
    d = pd.read_csv(EXP / f, parse_dates=["date"]).set_index("date")
    strat_net[k] = d["net_return"]
    strat_gross[k] = d["gross_return"]

# common overlapping window across SPY and the strategies (by date)
common_idx = strat_net["V1"].index
spy_common = spy_full.reindex(common_idx).dropna()
common_idx = spy_common.index  # dates where SPY also present
print("common window:", common_idx.min().date(), "->", common_idx.max().date(), "n=", len(common_idx))

series = {
    "SPY (full 2005-2026)": spy_full,
    "SPY (common window)": spy_common,
    "V1 net": strat_net["V1"].reindex(common_idx),
    "DD Only net": strat_net["DD Only"].reindex(common_idx),
    "Combined net": strat_net["Combined DD+Vol"].reindex(common_idx),
    "V1 gross": strat_gross["V1"].reindex(common_idx),
    "DD Only gross": strat_gross["DD Only"].reindex(common_idx),
    "Combined gross": strat_gross["Combined DD+Vol"].reindex(common_idx),
}
series = {k: v.dropna() for k, v in series.items()}

# ---------------- helpers ----------------
def garch_filter(x, mu, omega, alpha, beta):
    """Conditional variance + standardized residuals in the SAME units as x."""
    eps = x - mu
    T = eps.size
    s2 = np.empty(T); s2[0] = np.var(eps)
    for t in range(1, T):
        s2[t] = omega + alpha * eps[t-1]**2 + beta * s2[t-1]
    return s2, eps / np.sqrt(s2)

def ljung_box(z, lags=10):
    z = z - z.mean(); n = z.size; denom = np.sum(z*z); q = 0.0
    for k in range(1, lags+1):
        rho = np.sum(z[k:]*z[:-k]) / denom
        q += rho*rho / (n-k)
    q *= n*(n+2)
    return float(q), float(stats.chi2.sf(q, lags))

def arch_lm(r, lags=10):
    """Engle ARCH-LM test on returns (regress eps^2 on its lags)."""
    eps2 = (r - r.mean())**2; n = eps2.size
    Y = eps2[lags:]
    X = np.column_stack([np.ones(n-lags)] + [eps2[lags-k:n-k] for k in range(1, lags+1)])
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X@beta
    r2 = 1 - np.sum(resid**2)/np.sum((Y-Y.mean())**2)
    lm = (n-lags)*r2
    return float(lm), float(stats.chi2.sf(lm, lags))

def fit_row(name, r, dist):
    r = np.asarray(r, float)
    f = sim.fit_garch(r, dist=dist, return_se=True)
    p = f["persistence"]
    finite = p < 1.0
    uncond_var = f["omega"]/(1-p) if finite else np.nan
    row = {"series": name, "dist": dist, "n": r.size,
           "mu": f["mu"], "omega": f["omega"], "alpha": f["alpha"], "beta": f["beta"],
           "persistence": p, "se_alpha": f.get("se_alpha"), "se_beta": f.get("se_beta"),
           "se_persistence": f.get("se_persistence"), "nu": f.get("nu", np.nan),
           "se_nu": f.get("se_nu", np.nan),
           "half_life_days": (np.log(0.5)/np.log(p)) if finite and p > 0 else np.nan,
           "uncond_var_daily": uncond_var,
           "uncond_vol_daily": np.sqrt(uncond_var) if finite else np.nan,
           "uncond_vol_ann": np.sqrt(uncond_var*252) if finite else np.nan,
           "loglik": f["loglik"], "converged": f["converged"]}
    # diagnostics on standardized residuals
    s2, z = garch_filter(r, f["mu"], f["omega"], f["alpha"], f["beta"])
    lb_z, lbp_z = ljung_box(z, 10)
    lb_z2, lbp_z2 = ljung_box(z**2, 10)
    row.update({"resid_LB10_p": lbp_z, "resid_sq_LB10_p": lbp_z2,
                "resid_kurtosis": float(stats.kurtosis(z, fisher=False))})
    return row, f

# ---------------- Phase 2: fitted comparison (t and normal) ----------------
rows, fits = [], {}
for name, s in series.items():
    for dist in ("t", "normal"):
        row, f = fit_row(name, s.to_numpy(), dist)
        rows.append(row); fits[(name, dist)] = f
fit_tbl = pd.DataFrame(rows)
fit_tbl.to_csv(OUT / "garch_fit_comparison.csv", index=False)

# ---------------- Phase 3: raw diagnostics per series ----------------
diag_rows = []
for name, s in series.items():
    r = s.to_numpy()
    acf_r = sim._acf(r, [1,2,5,10]); acf_sq = sim._acf(r**2, [1,2,5,10])
    lm, lmp = arch_lm(r, 10)
    diag_rows.append({"series": name, "n": r.size, "kurtosis": float(stats.kurtosis(r, fisher=False)),
                      "skew": float(stats.skew(r)), "ann_vol": r.std(ddof=1)*np.sqrt(252),
                      "acf_ret_lag1": acf_r[1], "acf_sq_lag1": acf_sq[1], "acf_sq_lag5": acf_sq[5],
                      "arch_lm10_stat": lm, "arch_lm10_p": lmp})
diag_tbl = pd.DataFrame(diag_rows)
diag_tbl.to_csv(OUT / "return_diagnostics.csv", index=False)

# ---------------- Phase 3: window sensitivity (persistence over sub-windows, GARCH-t) ----------------
wins = {"full": None, "2016-2019": ("2016-01-01","2019-12-31"),
        "2020-2022": ("2020-01-01","2022-12-31"), "2023-2026": ("2023-01-01","2026-12-31")}
wrows = []
for name in ["SPY (common window)", "V1 net", "DD Only net", "Combined net"]:
    s = series[name]
    for wname, rng in wins.items():
        sub = s if rng is None else s.loc[rng[0]:rng[1]]
        if len(sub) < 250:
            continue
        f = sim.fit_garch(sub.to_numpy(), dist="t", return_se=True)
        wrows.append({"series": name, "window": wname, "n": len(sub),
                      "persistence": f["persistence"], "se_persistence": f.get("se_persistence"),
                      "alpha": f["alpha"], "beta": f["beta"], "nu": f.get("nu"),
                      "converged": f["converged"]})
win_tbl = pd.DataFrame(wrows)
win_tbl.to_csv(OUT / "window_sensitivity.csv", index=False)

# ---------------- Phase 5: GARCH-driven simulated MDD vs block bootstrap ----------------
# NOTE: this fits/resamples ALREADY risk-controlled strategy returns directly (documented limitation).
H = len(common_idx); N = 10000
risk_rows = []
for name in ["V1 net", "DD Only net", "Combined net"]:
    r = series[name].to_numpy()
    f = fits[(name, "t")]
    sel = {"model": "garch_t", "params": f}
    gp = sim.simulate_from_model(sel, H, N, RNG())
    bp = sim.block_bootstrap_paths(r, H, N, 20.0, RNG())
    gm = sim.summarize_path_metrics(gp); bm = sim.summarize_path_metrics(bp)
    eq = np.cumprod(1+r); hist_mdd = float((eq/np.maximum.accumulate(eq)-1).min())
    risk_rows.append({"strategy": name,
        "hist_CAGR": sim.path_cagr(r)[0], "hist_MDD": hist_mdd,
        "garch_med_MDD": gm["median_mdd"], "garch_p5_MDD": gm["p5_mdd"],
        "garch_P(MDD<-20)": gm["prob_mdd_below_20pct"], "garch_P(MDD<-30)": gm["prob_mdd_below_30pct"],
        "boot_med_MDD": bm["median_mdd"], "boot_p5_MDD": bm["p5_mdd"],
        "boot_P(MDD<-20)": bm["prob_mdd_below_20pct"], "boot_P(MDD<-30)": bm["prob_mdd_below_30pct"]})
risk_tbl = pd.DataFrame(risk_rows)
risk_tbl.to_csv(OUT / "risk_comparison.csv", index=False)

# ---------------- console report ----------------
pd.set_option("display.width", 200, "display.max_columns", 40)
print("\n===== PHASE 2: GARCH-t FITTED PERSISTENCE (net + SPY) =====")
show = fit_tbl[fit_tbl.dist=="t"][["series","n","alpha","beta","persistence","se_persistence",
                                   "nu","half_life_days","uncond_vol_ann","converged"]]
print(show.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print("\n===== PHASE 3: ARCH EFFECTS & STD-RESIDUAL DIAGNOSTICS (GARCH-t) =====")
dd = fit_tbl[fit_tbl.dist=="t"][["series","resid_LB10_p","resid_sq_LB10_p","resid_kurtosis"]].merge(
    diag_tbl[["series","kurtosis","acf_sq_lag1","arch_lm10_p"]], on="series")
print(dd.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print("\n===== PHASE 3: WINDOW SENSITIVITY (GARCH-t persistence) =====")
print(win_tbl.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print("\n===== PHASE 5: SIMULATED DRAWDOWN — GARCH-t vs BLOCK BOOTSTRAP =====")
print(risk_tbl.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
print("\nsaved to", OUT)
EOF_MARKER = True
