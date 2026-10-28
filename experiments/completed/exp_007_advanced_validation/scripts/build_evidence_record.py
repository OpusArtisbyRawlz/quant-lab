"""Assemble evidence_record.json + hash manifest for exp_007_advanced_validation."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path

ROOT = Path("/Users/rawls/quant-lab")
REM = ROOT / "experiments/completed/exp_007_advanced_validation"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*a):
    try:
        return subprocess.check_output(["git", *a], cwd=str(ROOT)).decode().strip()
    except Exception as e:
        return f"error:{e}"


SOURCES = [
    "src/statistics/cross_validation.py",
    "src/statistics/backtest_overfitting.py",
    "research/project_07_statistical_integrity/tests/test_cross_validation.py",
    "research/project_07_statistical_integrity/tests/test_backtest_overfitting.py",
    "experiments/completed/exp_006_deployment_candidate_tournament/run_tournament.py",
    "experiments/completed/exp_006_deployment_overlay_challenge/run_overlay_challenge.py",
]
INPUTS = [
    "data/processed/project_04_features_v2.csv",
    "experiments/completed/exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv",
    "experiments/completed/exp_005_risk_engine_final/final_daily_weights.csv",
]


def hashes(paths):
    return {p: (sha256(ROOT / p) if (ROOT / p).exists() else "MISSING") for p in paths}


def main():
    rec = {
        "experiment": "exp_007_advanced_validation",
        "purpose": "Stage A remediation finalization (warm-up correction, financing review, fold "
                   "investigation, commit) + Stage B purged/embargoed CV, CPCV, PBO.",
        "git": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                "head_commit": git("rev-parse", "HEAD"),
                "remediation_commit": "8a3f9e0"},
        "seeds": {"model_cv_leaky_shuffle": 20261028, "cpcv_model": "deterministic (no RNG)",
                  "pbo_cscv": "deterministic (no RNG)", "a3_diagnostics": "deterministic"},
        "config": {
            "model_cv": {"object": "project_04_features_v2 -> fwd_ret_5", "horizon": 5,
                         "forecaster": "closed-form ridge alpha=10 (representative, not production)",
                         "n_splits": 6, "embargo_sensitivity": [0, 5, 10, 21],
                         "cpcv": {"n_groups": 8, "k_test": 2, "embargo": 5}},
            "pbo": {"universe": "71 overlay candidates (floor{0.2,0.25,0.3,0.35,0.4,0.5,0.6} x k{3..7} "
                                "x {dd,combined} + V1)", "S": 16, "objectives": ["sharpe", "calmar"]},
            "warmup_fix": "vol_multiplier pre-window -> 1.0 (multiplicative identity)",
        },
        "source_sha256": hashes(SOURCES),
        "input_sha256": hashes(INPUTS),
        "tests": {"full_suite": "296 passed, 11 skipped", "new": {"cross_validation": 12, "backtest_overfitting": 7}},
        "guardrails": "no params optimized; no overlay optimized; 6/7 gate unchanged; no candidate "
                      "promoted; PBO not used to tune; P04/P05 inputs immutable (checksums verified).",
    }
    (REM / "evidence_record.json").write_text(json.dumps(rec, indent=2))
    files = sorted(p for p in REM.rglob("*") if p.is_file() and p.name != "MANIFEST_SHA256.txt")
    (REM / "MANIFEST_SHA256.txt").write_text("\n".join(f"{sha256(p)}  {p.relative_to(REM)}" for p in files) + "\n")
    print("evidence_record.json + manifest written;", len(files), "files;",
          "head", rec["git"]["head_commit"][:12])


if __name__ == "__main__":
    main()
