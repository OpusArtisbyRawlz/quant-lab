"""Remediation — regenerate P07 NB09 (candidate net validation) on the CORRECTED base.

Faithful, reproducible transcription of
``research/project_07_statistical_integrity/notebooks/09_candidate_net_validation.ipynb``
persistence cells, run against the corrected exp_006 tournament candidate outputs.

Regenerates (in exp_007_candidate_net_validation/, defective copies already archived):
  * v1/dd_only/combined_dd_vol_daily_returns.csv   (gross/net/turnover/cost_drag/exposure)
  * net_sharpe_significance_vs_v1.csv              (paired block bootstrap, m=2 FWER)
  * net_mdd_significance_vs_v1.csv
  * net_cagr_significance_vs_v1.csv
  * evidence_records.json                          (ledger records + 3 net families)

Every seed, block length, bootstrap count and cost assumption is identical to NB09, so
the only thing that changes is the input return lineage (defect -> canonical).
A copy of each regenerated artifact is also written to the remediation data/ dir, and the
reconstructed gross/net Sharpe are validated against each candidate's metrics.json (<=1e-4).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
import sys
sys.path.insert(0, str(ROOT))

from src.utils.metrics import sharpe_ratio, max_drawdown, annualized_return
from src.statistics.bootstrap import (
    bootstrap_metric, bootstrap_confidence_interval, paired_bootstrap_difference,
)
from src.statistics.permutation import permutation_p_value
from src.statistics.deflated_sharpe import (
    probabilistic_sharpe_ratio, deflated_sharpe_ratio, minimum_track_record_length,
)
from src.statistics.significance import bonferroni, benjamini_hochberg

TOURN = ROOT / "experiments/completed/exp_006_deployment_candidate_tournament"
EXP07 = ROOT / "experiments/completed/exp_007_candidate_net_validation"
REMDATA = Path(__file__).resolve().parents[1] / "data"
REMDATA.mkdir(parents=True, exist_ok=True)

COST_BPS = 10.0
PPY = 252
CAND_DIR = {"V1": "candidate_v1_baseline", "DD Only": "candidate_dd_only",
            "Combined DD+Vol": "candidate_combined"}
FILES = {"V1": "v1_daily_returns.csv", "DD Only": "dd_only_daily_returns.csv",
         "Combined DD+Vol": "combined_dd_vol_daily_returns.csv"}
CHAL = ["DD Only", "Combined DD+Vol"]

# NB09 statistical config (verbatim)
SEED, N_BOOT, BLOCK, STAT_PPY = 20260820, 10000, 20, 252
V_TRIALS = 4.920e-4
N_SCENARIOS = [2, 5, 100]
DSR_HURDLE_PP = 0.05613


# --------------------------------------------------------------------------- #
# 1. Rebuild daily_returns from corrected tournament candidates + validate
# --------------------------------------------------------------------------- #
def build_daily_returns():
    data, validation = {}, []
    for name, cdir in CAND_DIR.items():
        eq = pd.read_csv(TOURN / f"candidates/{cdir}/equity_curve.csv", parse_dates=["Date"]).set_index("Date")["equity"]
        turn = pd.read_csv(TOURN / f"candidates/{cdir}/turnover.csv", parse_dates=["Date"]).set_index("Date")["turnover"]
        expo = pd.read_csv(TOURN / f"candidates/{cdir}/exposure.csv", parse_dates=["Date"]).iloc[:, 1]
        gross = (eq / eq.shift(1) - 1.0)
        gross.iloc[0] = eq.iloc[0] - 1.0
        turn = turn.reindex(eq.index).fillna(0.0)
        cost_drag = turn * (COST_BPS / 1e4)
        net = gross - cost_drag
        df = pd.DataFrame({"gross_return": gross.values, "turnover": turn.values,
                           "exposure": np.asarray(expo)[:len(eq)], "cost_drag": cost_drag.values,
                           "net_return": net.values}, index=eq.index)
        df.index.name = "date"
        data[name] = df

        metrics = json.load(open(TOURN / f"candidates/{cdir}/metrics.json"))
        g_sr, n_sr = sharpe_ratio(df["gross_return"]), sharpe_ratio(df["net_return"])
        validation.append({
            "candidate": name,
            "gross_sharpe_recon": g_sr, "gross_sharpe_metrics": metrics["Sharpe"],
            "gross_sharpe_absdiff": abs(g_sr - metrics["Sharpe"]),
            "net_sharpe_recon": n_sr, "costadj_sharpe_metrics": metrics["Cost-adj Sharpe (10bps)"],
            "net_sharpe_absdiff": abs(n_sr - metrics["Cost-adj Sharpe (10bps)"]),
        })
    return data, pd.DataFrame(validation)


def econ(r, ppy=PPY):
    r = pd.Series(r).dropna()
    eq = (1 + r).cumprod(); mdd = float((eq / eq.cummax() - 1).min())
    cagr = float(eq.iloc[-1] ** (ppy / len(r)) - 1)
    return {"Ann Sharpe": sharpe_ratio(r), "Ann Vol": float(r.std(ddof=1) * np.sqrt(ppy)),
            "CAGR": cagr, "MDD": mdd, "Calmar": cagr / abs(mdd)}


# --------------------------------------------------------------------------- #
# 2. Per-candidate stat bundle (NB09 cell 8)
# --------------------------------------------------------------------------- #
def sign_flip_null(r, metric_fn, n, rng):
    r = np.asarray(r, float); out = np.empty(n)
    for i in range(n):
        out[i] = metric_fn(r * (rng.integers(0, 2, size=r.size) * 2 - 1))
    return out


def stat_bundle(r):
    r = pd.Series(r).dropna()
    dist = bootstrap_metric(r.to_numpy(), sharpe_ratio, N_BOOT, BLOCK, np.random.default_rng(SEED))
    se, lo, hi = bootstrap_confidence_interval(dist, 0.95)
    obs = sharpe_ratio(r)
    p_sf = permutation_p_value(obs, sign_flip_null(r.to_numpy(), sharpe_ratio, N_BOOT, np.random.default_rng(SEED)))
    psr0 = probabilistic_sharpe_ratio(r, benchmark_sharpe=0.0)
    dsr = {N: deflated_sharpe_ratio(r, n_trials=N, trial_sharpe_variance=V_TRIALS).deflated_probability
           for N in N_SCENARIOS}
    mintrl = {"SR*0/95": minimum_track_record_length(r, benchmark_sharpe=0.0, confidence_level=0.95),
              "SR*0/99": minimum_track_record_length(r, benchmark_sharpe=0.0, confidence_level=0.99),
              "hurdle/95": minimum_track_record_length(r, benchmark_sharpe=DSR_HURDLE_PP, confidence_level=0.95),
              "hurdle/99": minimum_track_record_length(r, benchmark_sharpe=DSR_HURDLE_PP, confidence_level=0.99)}
    return {"ann_sharpe_net": obs, "boot_SE": se, "boot_CI_lo": lo, "boot_CI_hi": hi,
            "signflip_p": p_sf, "PSR0": psr0, "DSR": dsr, "MinTRL": mintrl}


# --------------------------------------------------------------------------- #
# 3. Paired Sharpe family (NB09 cells 13-14): block 21, N 5000, seed 7
# --------------------------------------------------------------------------- #
def sharpe_family(data):
    BLOCK_FA, N_FA, SEED_FA = 21, 5000, 7
    net = {k: data[k]["net_return"].to_numpy() for k in data}
    n = len(net["V1"]); n_blocks = int(np.ceil(n / BLOCK_FA))

    def block_idx(rng):
        starts = rng.integers(0, n, size=n_blocks)
        return np.concatenate([(np.arange(s, s + BLOCK_FA) % n) for s in starts])[:n]

    def paired(chal, v1):
        rng = np.random.default_rng(SEED_FA); d = np.empty(N_FA)
        for b in range(N_FA):
            idx = block_idx(rng); d[b] = sharpe_ratio(chal[idx], STAT_PPY) - sharpe_ratio(v1[idx], STAT_PPY)
        return d

    v1 = net["V1"]; praw, meta = [], []
    for name in CHAL:
        d = paired(net[name], v1)
        praw.append((int(np.sum(d <= 0)) + 1) / (len(d) + 1))
        meta.append((float(sharpe_ratio(v1, STAT_PPY)), float(sharpe_ratio(net[name], STAT_PPY)),
                     float(sharpe_ratio(net[name], STAT_PPY) - sharpe_ratio(v1, STAT_PPY)),
                     float(d.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))))
    pa = np.asarray(praw, float)
    bonf = bonferroni(pa, alpha=0.05).adjusted_pvalues
    bh = benjamini_hochberg(pa, alpha=0.05).adjusted_pvalues
    fam = {}
    for i, name in enumerate(CHAL):
        fam[name] = {"SR_V1": meta[i][0], "SR_challenger": meta[i][1], "dSharpe": meta[i][2],
                     "boot_mean_dSharpe": meta[i][3], "ci_lo": meta[i][4], "ci_hi": meta[i][5],
                     "raw_p": praw[i], "bonferroni_adj": float(bonf[i]),
                     "bonferroni_decision": "REJECT H0" if bonf[i] <= 0.05 else "fail to reject H0",
                     "bh_adj": float(bh[i]), "bh_decision": "REJECT H0" if bh[i] <= 0.05 else "fail to reject H0"}
    rows = [{"challenger": name, "pairing": "paired (same base)", "cost_bps": 10.0,
             "m": 2, "block": BLOCK_FA, "n_boot": N_FA, "seed": SEED_FA, **fam[name]} for name in CHAL]
    return fam, pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 4. Paired MDD & CAGR families (NB09 cells 27-28, 36-37): block 20, N 10000
# --------------------------------------------------------------------------- #
def _paired_family(data, metric_fn, eff_key, seed, n_boot, block):
    net = {k: data[k]["net_return"] for k in data}
    obs = {k: float(metric_fn(net[k])) for k in net}
    canon = {}
    for ch in CHAL:
        d = paired_bootstrap_difference(net[ch].to_numpy(), net["V1"].to_numpy(),
                                        metric_fn, n_boot, float(block), np.random.default_rng(seed))
        canon[ch] = {eff_key: obs[ch] - obs["V1"], "boot_mean": float(d.mean()),
                     "ci_lo": float(np.percentile(d, 2.5)), "ci_hi": float(np.percentile(d, 97.5)),
                     "raw_p": (int(np.sum(d <= 0)) + 1) / (len(d) + 1)}
    praw = np.array([canon[c]["raw_p"] for c in CHAL])
    b = bonferroni(praw, alpha=0.05); h = benjamini_hochberg(praw, alpha=0.05)
    fam = {}
    for i, c in enumerate(CHAL):
        fam[c] = {**canon[c], "bonferroni_adj": float(b.adjusted_pvalues[i]),
                  "bonferroni_decision": "REJECT H0" if b.rejected[i] else "fail to reject H0",
                  "bh_adj": float(h.adjusted_pvalues[i]),
                  "bh_decision": "REJECT H0" if h.rejected[i] else "fail to reject H0"}
    rows = [{"challenger": c, "pairing": "paired (shared block indices)", "cost_bps": 10.0,
             "m": 2, "block": block, "n_boot": n_boot, "seed": seed, **fam[c]} for c in CHAL]
    return fam, pd.DataFrame(rows), obs


def main():
    data, validation = build_daily_returns()
    print("=== daily_returns reconstruction validation (vs tournament metrics.json) ===")
    print(validation.round(6).to_string(index=False))
    assert validation["gross_sharpe_absdiff"].max() < 1e-4, "gross Sharpe mismatch"
    assert validation["net_sharpe_absdiff"].max() < 1e-4, "net Sharpe mismatch"

    # persist daily_returns (corrected) to exp_007 and remediation data/
    for name, df in data.items():
        df.to_csv(EXP07 / FILES[name])
        df.to_csv(REMDATA / FILES[name])

    # econ table (gross + net)
    econ_rows = []
    for name, df in data.items():
        for basis, col in (("gross", "gross_return"), ("net", "net_return")):
            econ_rows.append({"candidate": name, "basis": basis, **econ(df[col]),
                              "mean_turnover": float(df["turnover"].mean()),
                              "ann_cost_drag": float(df["cost_drag"].mean() * PPY)})
    econ_table = pd.DataFrame(econ_rows)
    econ_table.to_csv(REMDATA / "net_econ_table_corrected.csv", index=False)
    print("\n=== corrected gross/net econ table ===")
    print(econ_table.round(4).to_string(index=False))

    # significance families
    net_stats = {name: stat_bundle(df["net_return"]) for name, df in data.items()}
    sh_fam, sh_df = sharpe_family(data)
    mdd_fam, mdd_df, _ = _paired_family(data, lambda r: max_drawdown((1 + pd.Series(r)).cumprod()),
                                        "observed_dMDD", 20260820, 10000, 20)
    cagr_fam, cagr_df, _ = _paired_family(data, lambda r: annualized_return(pd.Series(r)),
                                          "observed_dCAGR", 20260820, 10000, 20)
    for df_, fn in ((sh_df, "net_sharpe_significance_vs_v1.csv"),
                    (mdd_df, "net_mdd_significance_vs_v1.csv"),
                    (cagr_df, "net_cagr_significance_vs_v1.csv")):
        df_.to_csv(EXP07 / fn, index=False)
        df_.to_csv(REMDATA / fn, index=False)

    print("\n=== corrected NET significance vs V1 (m=2 FWER) ===")
    for fam_name, fam in (("Sharpe", sh_fam), ("MDD", mdd_fam), ("CAGR", cagr_fam)):
        eff = {"Sharpe": "dSharpe", "MDD": "observed_dMDD", "CAGR": "observed_dCAGR"}[fam_name]
        for c in CHAL:
            r = fam[c]
            print(f"  {fam_name:7} {c:16} eff={r[eff]:+.4f} raw_p={r['raw_p']:.4f} "
                  f"bonf={r['bonferroni_adj']:.4f}->{r['bonferroni_decision'].split()[0]} "
                  f"bh={r['bh_adj']:.4f}->{r['bh_decision'].split()[0]}")

    # evidence records (structured; ledger backend not implemented in repo)
    recs = []
    for name, df in data.items():
        s = net_stats[name]
        rec = {"record_id": f"p07_nb09_net_{name.split()[0].lower()}_v1", "strategy_version": name,
               "experiment_id": "exp_007_candidate_net_validation",
               "dataset": FILES[name], "basis": "net-of-cost (10bps one-way)",
               "test_statistic_net_ann_sharpe": float(s["ann_sharpe_net"]),
               "signflip_p": float(s["signflip_p"]),
               "boot_CI": [float(s["boot_CI_lo"]), float(s["boot_CI_hi"])],
               "PSR0": float(s["PSR0"]),
               "DSR_scenarios": {str(k): float(v) for k, v in s["DSR"].items()},
               "MinTRL_obs": {k: math.ceil(v) for k, v in s["MinTRL"].items()},
               "gross_metrics": econ(df["gross_return"]), "net_metrics": econ(df["net_return"]),
               "mean_turnover": float(df["turnover"].mean()),
               "ann_cost_drag": float(df["cost_drag"].mean() * PPY),
               "decision": "INCONCLUSIVE (no winner selected; V1 not replaced)"}
        if name in CHAL:
            rec["net_family_A_sharpe_improvement"] = sh_fam[name]
            rec["net_family_MDD_improvement"] = mdd_fam[name]
            rec["net_family_CAGR_improvement"] = cagr_fam[name]
        recs.append(rec)
    out = {"ledger_backend_persisted": False, "source": "regen_nb09 on corrected base",
           "cost_model": "net=gross-turnover*(bps/1e4); bps=10 one-way",
           "trial_sharpe_variance_used": V_TRIALS, "records": recs}
    (EXP07 / "evidence_records.json").write_text(json.dumps(out, indent=2))
    (REMDATA / "evidence_records.json").write_text(json.dumps(out, indent=2))
    print("\nwrote evidence_records.json (3 records, 3 net families for challengers)")


if __name__ == "__main__":
    main()
