"""Remediation — assemble evidence_record.json + regenerated-artifact hash manifest."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path

ROOT = Path("/Users/rawls/quant-lab")
REM = ROOT / "experiments/completed/exp_007_p06_p07_remediation"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=str(ROOT)).decode().strip()
    except Exception as e:
        return f"error: {e}"


FIXED = [
    "experiments/completed/exp_006_deployment_candidate_tournament/run_tournament.py",
    "experiments/completed/exp_006_deployment_candidate_tournament/tournament_significance.py",
    "experiments/completed/exp_006_deployment_candidate_tournament/tournament_stability.py",
    "experiments/completed/exp_006_deployment_overlay_challenge/run_overlay_challenge.py",
    "experiments/completed/exp_006_deployment_overlay_challenge/statistical_significance.py",
    "experiments/completed/exp_006_deployment_overlay_challenge/walk_forward_sensitivity.py",
    "experiments/completed/exp_006_deployment_overlay_challenge/promote_deployment_candidate.py",
    "experiments/completed/exp_007_garch_volatility_persistence/analysis_overlay_replay.py",
]
INPUTS = [
    "experiments/completed/exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv",
    "experiments/completed/exp_005_risk_engine_final/final_daily_weights.csv",
    "experiments/completed/exp_005_risk_engine_final/final_returns_v2_with_dates.csv",
]
REGEN = [
    "experiments/completed/exp_006_deployment_candidate_tournament/master_comparison.csv",
    "experiments/completed/exp_006_deployment_candidate_tournament/significance_vs_v1.csv",
    "experiments/completed/exp_006_deployment_candidate_tournament/walk_forward_stability.csv",
    "experiments/completed/exp_006_deployment_overlay_challenge/overlay_comparison.csv",
    "experiments/completed/exp_006_deployment_overlay_challenge/overlay_equity_curves.csv",
    "experiments/completed/exp_006_deployment_overlay_challenge/promotion_gate_result.json",
    "experiments/completed/exp_007_candidate_net_validation/v1_daily_returns.csv",
    "experiments/completed/exp_007_candidate_net_validation/dd_only_daily_returns.csv",
    "experiments/completed/exp_007_candidate_net_validation/combined_dd_vol_daily_returns.csv",
    "experiments/completed/exp_007_candidate_net_validation/net_sharpe_significance_vs_v1.csv",
    "experiments/completed/exp_007_candidate_net_validation/net_mdd_significance_vs_v1.csv",
    "experiments/completed/exp_007_candidate_net_validation/net_cagr_significance_vs_v1.csv",
    "experiments/completed/exp_007_candidate_net_validation/white_reality_check_record.json",
    "experiments/completed/exp_007_nb03_dynamic_replay/reconstruction_fidelity.json",
    "experiments/completed/exp_007_nb03_dynamic_replay/dynamic_replay_A_vs_B.csv",
    "experiments/completed/exp_007_garch_volatility_persistence/overlay_replay_A_vs_B.csv",
]


def hashes(paths):
    out = {}
    for rel in paths:
        p = ROOT / rel
        out[rel] = sha256(p) if p.exists() else "MISSING"
    return out


def load_before_after():
    def parse(fn):
        d = {}
        f = REM / "logs" / fn
        if f.exists():
            for line in f.read_text().splitlines():
                parts = line.split()
                if len(parts) == 2:
                    d[parts[1]] = parts[0]
        return d
    return parse("source_hashes_BEFORE.txt"), parse("source_hashes_AFTER.txt")


def main():
    before, after = load_before_after()
    record = {
        "experiment": "exp_007_p06_p07_remediation",
        "purpose": "Controlled remediation of the exp_006 double-lag return-lineage defect: fix at "
                   "source, regenerate affected P06/P07 evidence, reconcile.",
        "git": {
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "head_commit": git("rev-parse", "HEAD"),
            "status_short": git("status", "--short", "--untracked-files=no"),
        },
        "defect": "base_ret = portfolio_return / portfolio_dd_exposure.shift(1)  (double lag; stored "
                  "exposure already lagged). Fix: same-row inverse base_ret = portfolio_return / "
                  "portfolio_dd_exposure, equal to canonical port_pre rebuilt from exp_004 (1e-12).",
        "fixed_source_files": FIXED,
        "source_sha256_before": before,
        "source_sha256_after": after,
        "promote_script_fixed_but_not_run": "experiments/completed/exp_006_deployment_overlay_challenge/"
                                            "promote_deployment_candidate.py (running it would promote a "
                                            "candidate — prohibited; its historical outputs classified INVALID)",
        "immutable_input_sha256": hashes(INPUTS),
        "regenerated_artifact_sha256": hashes(REGEN),
        "seeds": {
            "tournament_significance_sharpe": {"block": 21, "n_boot": 5000, "seed": 7},
            "net_mdd_and_cagr_families": {"block": 20, "n_boot": 10000, "seed": 20260820},
            "stat_bundle_bootstrap": {"block": 20, "n_boot": 10000, "seed": 20260820},
            "white_reality_check": {"block": 20, "n_resamples": 10000, "seed": 20260820},
            "dynamic_replay_mc": {"block": 20, "n_paths": 10000, "seed": 20261027},
            "garch_overlay_replay": {"block": 20, "n_paths": 10000, "seed": 20261023},
        },
        "cost_model": "net = gross - turnover*(bps/1e4); bps=10 one-way (commission+spread+slippage blended). "
                      "Borrow/financing on short book handled via bounded scenarios (not historically modelled).",
        "regression_tests": {
            "test_return_lineage_audit.py": "5 tests (analytic + canonical identities)",
            "test_remediation_source_fix.py": "8 tests (bound to the fixed source loaders/builders)",
            "p06_suite": "8 passed",
            "p07_suite": "269 passed, 11 skipped",
        },
        "reproduction": "PYTHONPATH=. venv/bin/python <script> for each file in scripts/; notebooks' "
                        "persisted artifacts regenerated by faithful transcription scripts with identical seeds.",
    }
    (REM / "evidence_record.json").write_text(json.dumps(record, indent=2))

    # manifest of everything under the remediation dir (excluding the manifest itself)
    files = sorted(p for p in REM.rglob("*") if p.is_file() and p.name != "MANIFEST_SHA256.txt")
    lines = [f"{sha256(p)}  {p.relative_to(REM)}" for p in files]
    (REM / "MANIFEST_SHA256.txt").write_text("\n".join(lines) + "\n")
    print("evidence_record.json written; manifest covers", len(files), "files")
    print("git branch:", record["git"]["branch"], "| head:", record["git"]["head_commit"][:12])


if __name__ == "__main__":
    main()
