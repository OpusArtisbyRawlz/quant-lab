"""Assemble evidence_record.json + SHA256 manifest for exp_007_full_pipeline_validation."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path

ROOT = Path("/Users/rawls/quant-lab")
EXP = ROOT / "experiments/completed/exp_007_full_pipeline_validation"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*a):
    try:
        return subprocess.check_output(["git", *a], cwd=str(ROOT)).decode().strip()
    except Exception as e:
        return f"error:{e}"


INPUTS = [
    "data/processed/project_04_features.csv", "data/processed/project_04_features_v2.csv",
    "data/processed/v1.csv", "data/processed/v2.csv",
    "experiments/completed/exp_004_project04_final/strategy_timeseries/ls_20pct.csv",
    "experiments/completed/exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv",
    "experiments/completed/exp_005_risk_engine_final/final_daily_weights.csv",
]
SOURCES = [
    "research/project_04_return_forecast_alpha/notebooks/03_model_training.ipynb",
    "research/project_04_return_forecast_alpha/notebooks/03_model_training_v2.ipynb",
    "research/project_04_return_forecast_alpha/notebooks/04_portfolio_research.ipynb",
    "research/project_07_statistical_integrity/tests/test_full_pipeline_validation.py",
]


def hashes(paths):
    return {p: (sha256(ROOT / p) if (ROOT / p).exists() else "MISSING") for p in paths}


rec = {
    "experiment": "exp_007_full_pipeline_validation",
    "purpose": "Reconstruct & reproduce the ACTUAL P04 OLS model; full-model purged CPCV vs representative "
               "ridge; reconstruct the research trial universe; expanded PBO & selection-bias sensitivity; "
               "reconcile integrity evidence; DD Only fold attribution; paper/shadow-trading readiness.",
    "git": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "head_commit_before_this": git("rev-parse", "HEAD"),
            "prior_remediation_commit": "8a3f9e0", "prior_advanced_commit": "9f0cef0"},
    "key_findings": {
        "model_reproduction": {"v1_max_abs_pred_diff": 7.44e-9, "v2_max_abs_pred_diff": 2.13e-6,
                               "verdict": "EXACT at prediction level"},
        "portfolio_finalizer": "NOT bit-reproducible (empty config/metrics; exploratory finalizer) -> "
                               "saved ls_20pct classified inferred/approx (corr ~0.97). Documented blocker.",
        "cpcv_full_sample_rank_ic": {"combined": -0.0012, "v1_flipped": -0.0116, "v2": 0.0141, "ridge": 0.0300},
        "cpcv_deployment_era_rank_ic": {"combined": 0.0094, "v1_flipped": 0.0063, "v2": 0.0002, "ridge": 0.0096},
        "pbo": {"overlay71_sharpe": 0.0016, "overlay71_calmar": 0.0112,
                "expanded83_sharpe": 0.0014, "expanded83_calmar": 0.0043,
                "p04_family12_sharpe": 0.7689, "p04_family12_calmar": 0.4629,
                "overlay_effective_dim": 1.01, "mean_abs_corr": 0.993,
                "note": "overlay PBO low but ~1 effective dim -> LOWER BOUND; P04 construction layer overfits"},
        "dd_only_folds": {"sharpe_pass": "4/7", "mdd_shallower": "7/7", "vol_reduced": "7/7",
                          "miss_folds": [0, 2, 6], "miss_negative_regime_artifact": 2, "miss_opportunity_cost": 1},
        "trial_ledger_rows": 51,
        "shadow_harness": "built + smoke-tested; SIMULATION_ONLY; refuses on broker env; feeds not yet wired",
    },
    "deliverables": [
        "PROJECT04_MODEL_LINEAGE.md", "FULL_MODEL_CPCV_REPORT.md", "CPCV_MODEL_RESULTS.csv",
        "CPCV_MODEL_RESULTS_era2016.csv", "HISTORICAL_TRIAL_LEDGER.csv", "PBO_SELECTION_SENSITIVITY.md",
        "PBO_EXPANDED_RESULTS.csv", "STATISTICAL_INTEGRITY_RECONCILIATION.md", "DD_ONLY_FOLD_ATTRIBUTION.md",
        "DD_ONLY_FOLD_ATTRIBUTION.csv", "PAPER_TRADING_PROTOCOL.md", "SHADOW_TRADING_READINESS.md",
        "FINAL_VALIDATION_REPORT.md",
    ],
    "tests": {"new_file": "research/project_07_statistical_integrity/tests/test_full_pipeline_validation.py",
              "new_tests": 8, "full_suite": "304 passed, 11 skipped"},
    "input_sha256": hashes(INPUTS), "source_sha256": hashes(SOURCES),
    "guardrails": {"parameters_optimized": False, "new_signals": False, "overlay_optimized": False,
                   "gate_changed": False, "candidate_promoted": False, "pbo_used_to_tune": False,
                   "live_orders": False, "earlier_reports_altered": False, "p04_p05_inputs_modified": False,
                   "branch_merged": False},
}
(EXP / "evidence_record.json").write_text(json.dumps(rec, indent=2))
files = sorted(p for p in EXP.rglob("*") if p.is_file() and p.name != "MANIFEST_SHA256.txt"
               and "__pycache__" not in p.parts)
(EXP / "MANIFEST_SHA256.txt").write_text("\n".join(f"{sha256(p)}  {p.relative_to(EXP)}" for p in files) + "\n")
print("evidence_record.json + manifest written;", len(files), "files; head",
      rec["git"]["head_commit_before_this"][:12])
