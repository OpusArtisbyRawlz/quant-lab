"""Remediation — compile old-vs-corrected reconciliation tables (Phase 8 deliverables).

Reads the archived defective outputs and the regenerated corrected outputs and emits:
  * REGENERATED_PERFORMANCE.csv        gross/net metrics, old vs corrected, per candidate
  * STATISTICAL_TEST_RECONCILIATION.csv  each significance test, old vs corrected
No recomputation of statistics here — only reads persisted artifacts — so it is a pure
reconciliation of what the pipelines produced before and after the source fix.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
REM = Path(__file__).resolve().parents[1]
ARCH = REM / "archived_defective_outputs"
REPORTS = REM / "reports"; REPORTS.mkdir(exist_ok=True)

TOURN_NEW = ROOT / "experiments/completed/exp_006_deployment_candidate_tournament"
TOURN_OLD = ARCH / "exp_006_deployment_candidate_tournament"
NET_NEW = ROOT / "experiments/completed/exp_007_candidate_net_validation"
NET_OLD = ARCH / "exp_007_candidate_net_validation"
PPY = 252
CMAP = {"V1": "candidate_v1_baseline", "DD Only": "candidate_dd_only", "Combined DD+Vol": "candidate_combined"}
NFILE = {"V1": "v1_daily_returns.csv", "DD Only": "dd_only_daily_returns.csv", "Combined DD+Vol": "combined_dd_vol_daily_returns.csv"}


def net_econ(path):
    df = pd.read_csv(path)
    r = df["net_return"]; eq = (1 + r).cumprod()
    mdd = float((eq / eq.cummax() - 1).min()); n = len(r)
    cagr = float(eq.iloc[-1] ** (PPY / n) - 1)
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(PPY))
    return {"CAGR": cagr, "Sharpe": sharpe, "MDD": mdd,
            "Vol": float(r.std(ddof=1) * np.sqrt(PPY)), "Calmar": cagr / abs(mdd)}


def gross_metrics(base, cand):
    m = json.load(open(base / f"candidates/{cand}/metrics.json"))
    return {"CAGR": m["CAGR"], "Sharpe": m["Sharpe"], "MDD": m["MDD"],
            "Vol": m["Volatility"], "Calmar": m["Calmar"], "Sortino": m.get("Sortino")}


def regenerated_performance():
    rows = []
    for name, cand in CMAP.items():
        og, ng = gross_metrics(TOURN_OLD, cand), gross_metrics(TOURN_NEW, cand)
        on, nn = net_econ(NET_OLD / NFILE[name]), net_econ(NET_NEW / NFILE[name])
        for basis, old, new in (("gross", og, ng), ("net", on, nn)):
            for metric in ["CAGR", "Sharpe", "MDD", "Vol", "Calmar"]:
                rows.append({"candidate": name, "basis": basis, "metric": metric,
                             "old_defective": round(old[metric], 6), "corrected": round(new[metric], 6),
                             "delta": round(new[metric] - old[metric], 6)})
    df = pd.DataFrame(rows)
    df.to_csv(REPORTS / "REGENERATED_PERFORMANCE.csv", index=False)
    return df


def stat_reconciliation():
    rows = []
    fams = [("Sharpe", "net_sharpe_significance_vs_v1.csv", "dSharpe"),
            ("MDD", "net_mdd_significance_vs_v1.csv", "observed_dMDD"),
            ("CAGR", "net_cagr_significance_vs_v1.csv", "observed_dCAGR")]
    for fam, fn, eff in fams:
        old = pd.read_csv(NET_OLD / fn).set_index("challenger")
        new = pd.read_csv(NET_NEW / fn).set_index("challenger")
        for ch in ["DD Only", "Combined DD+Vol"]:
            o, n = old.loc[ch], new.loc[ch]
            rows.append({"test": f"net {fam} vs V1 (paired block bootstrap, m=2)", "challenger": ch,
                         "old_effect": round(float(o[eff]), 5), "old_raw_p": round(float(o["raw_p"]), 4),
                         "old_bonferroni": o["bonferroni_decision"], "old_bh": o["bh_decision"],
                         "corrected_effect": round(float(n[eff]), 5), "corrected_raw_p": round(float(n["raw_p"]), 4),
                         "corrected_bonferroni": n["bonferroni_decision"], "corrected_bh": n["bh_decision"]})
    # WRC old vs new
    try:
        ow = json.load(open(NET_OLD / "white_reality_check_record.json"))
        nw = json.load(open(NET_NEW / "white_reality_check_record.json"))
        rows.append({"test": "White's Reality Check (block20, gross universe)", "challenger": "best-of-family",
                     "old_effect": round(float(ow["test_statistic"]), 5), "old_raw_p": round(float(ow["p_value"]), 4),
                     "old_bonferroni": ow.get("decision"), "old_bh": "",
                     "corrected_effect": round(float(nw["test_statistic"]), 5), "corrected_raw_p": round(float(nw["p_value"]), 4),
                     "corrected_bonferroni": nw.get("decision"), "corrected_bh": ""})
    except Exception as e:
        print("WRC reconciliation skipped:", e)
    df = pd.DataFrame(rows)
    df.to_csv(REPORTS / "STATISTICAL_TEST_RECONCILIATION.csv", index=False)
    return df


if __name__ == "__main__":
    rp = regenerated_performance()
    sr = stat_reconciliation()
    print("=== REGENERATED_PERFORMANCE.csv ===")
    print(rp.to_string(index=False))
    print("\n=== STATISTICAL_TEST_RECONCILIATION.csv ===")
    print(sr.to_string(index=False))
