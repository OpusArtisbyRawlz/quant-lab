"""Phase 4 — Reconstruct the historical research trial universe from preserved artifacts.

Evidence-based only: every row is sourced from a file that exists in the repo. Trials are classified
documented (D, read from a results/metrics artifact) vs inferred (I, implied by code/config but
without a preserved independent return series). No returns are fabricated; where a field is not
recoverable it is left blank / NA.

Sources:
  P04 portfolio family   -> exp_004_project04_final/strategy_comparison.csv  (+ model notebooks)
  P04 model search       -> notebooks 03/03_v2/04 (feature-set + sign-flip + blend choices)
  P05 overlay-on-strategy-> exp_005_risk_engine_final/strategy_level_dd_results.csv
  P06 deployment family  -> exp_006_deployment_candidate_tournament/master_comparison.csv
  P06 overlay grid       -> exp_006_deployment_overlay_challenge (71 = 7 floors x 5 k x 2 forms + V1)
  idea_generator track   -> exp_0NN_idea_generator_quantile_ranking/{config,metrics}.json

Output: reports/HISTORICAL_TRIAL_LEDGER.csv
"""
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

ROOT = Path("/Users/rawls/quant-lab")
EXP = ROOT / "experiments/completed"
OUT = ROOT / "experiments/completed/exp_007_full_pipeline_validation"
rows = []


def add(**k):
    rows.append(k)


# ---- P04 model-search trials (from notebooks; inferred as distinct hypotheses) ----
add(trial_id="P04-M-V1", project="P04_model", hypothesis="OLS on 11 momentum/vol features -> fwd_ret_5",
    config="LinearRegression; feats=ret_{1,5,10,20},vol_{5,20},ma_{10,20,50}_ratio,dollar_vol,vol_z_20; split 2016; sign-FLIPPED",
    data_window="1985-2026 (test>=2016)", gross_avail="Y (v1.csv preds)", net_avail="N",
    executed="Y", influenced_selection="Y", provenance="notebooks/03_model_training.ipynb; data/processed/v1.csv",
    relationship="leg of combined signal", doc="D")
add(trial_id="P04-M-V2", project="P04_model", hypothesis="OLS on 13 features (adds ret_60,ret_120) -> fwd_ret_5",
    config="LinearRegression; V1 feats + ret_60,ret_120; split 2016; no flip",
    data_window="1985-2026 (test>=2016)", gross_avail="Y (v2.csv preds)", net_avail="N",
    executed="Y", influenced_selection="Y", provenance="notebooks/03_model_training_v2.ipynb; data/processed/v2.csv",
    relationship="leg of combined signal", doc="D")
add(trial_id="P04-M-COMBINED", project="P04_model", hypothesis="z(V1_flip)+z(V2) blend",
    config="per-date z-sum of the two OLS legs", data_window="test>=2016", gross_avail="Y", net_avail="N",
    executed="Y", influenced_selection="Y", provenance="notebooks/04_portfolio_research.ipynb",
    relationship="parent of all P04 portfolio trials", doc="D")

# ---- P04 portfolio-construction family (documented, executed) ----
sc = pd.read_csv(EXP / "exp_004_project04_final/strategy_comparison.csv")
for _, r in sc.iterrows():
    add(trial_id=f"P04-PF::{r['Strategy']}", project="P04_portfolio",
        hypothesis="portfolio construction / overlay on combined signal",
        config=f"Sharpe={r['Sharpe']}, MDD={r['MDD']}, CAGR={r['CAGR']}, Calmar={r['Calmar']}",
        data_window="2016-01..2026-03 (2558d)",
        gross_avail="Y" if "timeseries" else "Y", net_avail="N",
        executed="Y", influenced_selection="Y (blend/ls20 chosen)",
        provenance="exp_004_project04_final/strategy_comparison.csv (+12 timeseries files)",
        relationship="child of P04-M-COMBINED", doc="D")

# ---- P05 overlay-on-strategy (documented) ----
p5 = pd.read_csv(EXP / "exp_005_risk_engine_final/strategy_level_dd_results.csv")
for _, r in p5.iterrows():
    add(trial_id=f"P05-OV::{r['Strategy']}", project="P05_overlay",
        hypothesis="smooth-DD overlay applied to a P04 strategy",
        config=f"Sharpe_base={r['Sharpe_base']}->smooth_dd={r['Sharpe_smooth_dd']}; avg_exp={r['Avg_Exposure']}",
        data_window="2016-01..2026-03 (2558d)", gross_avail="Y", net_avail="N",
        executed="Y", influenced_selection="Y (overlay form chosen)",
        provenance="exp_005_risk_engine_final/strategy_level_dd_results.csv",
        relationship="overlay of a P04 strategy", doc="D")

# ---- P06 deployment candidates (documented) ----
mc = pd.read_csv(EXP / "exp_006_deployment_candidate_tournament/master_comparison.csv")
for _, r in mc.iterrows():
    add(trial_id=f"P06-CAND::{r['Candidate']}", project="P06_candidate",
        hypothesis="deployment candidate (overlay variant of V1 base)",
        config=f"{r['Overlay']}; Sharpe={round(float(r['Sharpe']),3)}; MDD={round(float(r['MDD']),3)}",
        data_window="2016-01..2026-03 (2558d)",
        gross_avail="Y", net_avail="Y" if pd.notna(r.get("Cost-adj Sharpe (10bps)")) else "partial",
        executed="Y", influenced_selection="Y",
        provenance="exp_006_deployment_candidate_tournament/master_comparison.csv",
        relationship="overlay of P05 deployment base", doc="D", is_v1=str(r.get("is_v1")))

# ---- P06 overlay grid (71; mostly inferred reconstruction for PBO) ----
add(trial_id="P06-GRID::floor{0.2..0.6}xk{3..7}x{dd,comb}+V1", project="P06_overlay_grid",
    hypothesis="overlay hyperparameter search (floor,k,form)",
    config="7 floors x 5 k x 2 forms + V1 = 71; effective independent dim ~1.0 (mean|corr|0.99)",
    data_window="2016-01..2026-03 (2558d)", gross_avail="Y (reconstructed)", net_avail="N",
    executed="Y (reconstructable)", influenced_selection="Y (DD Only floor0.3,k5 selected)",
    provenance="exp_006_deployment_overlay_challenge + exp_007 PBO reconstruction",
    relationship="grid around the chosen DD Only point", doc="I")

# ---- idea_generator track (parallel, auto, postdates P04-P06 selection) ----
ig = sorted(EXP.glob("exp_*_idea_generator_quantile_ranking"))
n_ig = 0
models = {}
for d in ig:
    try:
        cfg = json.loads((d / "config.json").read_text()) if (d / "config.json").exists() else {}
        met = json.loads((d / "metrics.json").read_text()) if (d / "metrics.json").exists() else {}
    except Exception:
        cfg, met = {}, {}
    n_ig += 1
    mdl = cfg.get("model") or met.get("model") or "unknown"
    models[mdl] = models.get(mdl, 0) + 1
add(trial_id=f"IDEAGEN::{n_ig} auto-trials", project="idea_generator",
    hypothesis="LLM-proposed ideas auto-executed (quantile_ranking, random_forest, recovery replays)",
    config=f"models={models}", data_window="generated 2026-09-20+",
    gross_avail="Y (per-exp metrics.json)", net_avail="partial",
    executed="Y", influenced_selection="N (postdates P04-P06 selection; separate objective)",
    provenance="experiments/completed/exp_0NN_idea_generator_quantile_ranking (untracked)",
    relationship="parallel research track; NOT PBO-comparable with overlay family", doc="D")

df = pd.DataFrame(rows)
df.to_csv(OUT / "reports/HISTORICAL_TRIAL_LEDGER.csv", index=False)
print(f"ledger rows: {len(df)}")
print(df.groupby("project").size().to_string())
print(f"\nidea_generator models: {models}  (total {n_ig} auto-trials)")
