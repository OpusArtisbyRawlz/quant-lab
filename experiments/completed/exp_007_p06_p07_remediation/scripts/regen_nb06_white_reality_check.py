"""Remediation — regenerate P07 NB06 (White's Reality Check) on the CORRECTED overlay panel.

Faithful transcription of 06_white_reality_check.ipynb cells 8/11/13/17/19, run against the
regenerated exp_006 overlay_equity_curves.csv. The P04 raw strategies are defect-free; only the
P06 overlay columns change (correction can only *lower* the non-winning columns), so the WRC
winner and p-value are expected to be unchanged. Identical seed/blocks/estimator to NB06.

Writes (corrected): exp_007_candidate_net_validation/white_reality_check_record.json
and a block-sensitivity table + old/new comparison into the remediation dir.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
import sys
sys.path.insert(0, str(ROOT))

from src.statistics.white_reality_check import reality_check

WRC_SEED, WRC_N, WRC_BLOCKS, WRC_CANON = 20260820, 10000, [5, 10, 20, 30, 50], 20
EXP07 = ROOT / "experiments/completed/exp_007_candidate_net_validation"
REM = Path(__file__).resolve().parents[1]
ARCH = REM / "archived_defective_outputs/exp_007_candidate_net_validation/white_reality_check_record.json"


def build_panel():
    A = {}
    for f in sorted(glob.glob(str(ROOT / "experiments/completed/exp_004_project04_final/strategy_timeseries/*.csv"))):
        A[os.path.basename(f)[:-4]] = pd.read_csv(f)["portfolio_return"].to_numpy()
    A = pd.DataFrame(A)
    eqB = pd.read_csv(ROOT / "experiments/completed/exp_006_deployment_overlay_challenge/overlay_equity_curves.csv").drop(columns=["Date"])
    B = eqB.pct_change().dropna().reset_index(drop=True)
    perf = pd.concat([A.iloc[1:].reset_index(drop=True).add_prefix("P04:"),
                      B.add_prefix("P06:")], axis=1)
    return perf


def main():
    perf = build_panel()
    C = perf.corr().values; iu = np.triu_indices_from(C, k=1)
    res = {bl: reality_check(perf, n_resamples=WRC_N, expected_block_length=float(bl), seed=WRC_SEED)
           for bl in WRC_BLOCKS}
    canon = res[WRC_CANON]

    sens = pd.DataFrame([{"block": bl, "best_strategy": r.best_strategy,
                          "observed_stat": r.best_statistic, "wrc_p": r.p_value,
                          "null_q95": r.null_q95, "null_q99": r.null_q99}
                         for bl, r in res.items()])
    sens.to_csv(REM / "data/wrc_block_sensitivity_corrected.csv", index=False)

    record = {
        "record_id": "p07_nb06_white_reality_check_v1",
        "strategy_version": "best-of-family (White RC) = " + canon.best_strategy,
        "experiment_id": "project_07_reconstructed_strategy_universe",
        "dataset": "exp_004 strategy_timeseries + exp_006 overlay_equity_curves (CORRECTED base, 23 series, gross)",
        "parameters": {"test": "white_reality_check", "statistic": "sqrt(T)*mean(d_k)", "benchmark": 0.0,
                       "n_strategies": int(perf.shape[1]), "n_resamples": WRC_N,
                       "block_canonical": WRC_CANON, "blocks_tested": WRC_BLOCKS,
                       "p_value_estimator": "add-one (k+1)/(B+1)", "returns_basis": "gross"},
        "random_seed": WRC_SEED,
        "method": "white_reality_check",
        "test_statistic": float(canon.best_statistic),
        "p_value": float(canon.p_value),
        "white_reality_check_result": float(canon.p_value),
        "n_trials": int(perf.shape[1]),
        "decision": "SIGNIFICANT" if canon.p_value < 0.05 else "NOT_SIGNIFICANT",
        "mean_pairwise_corr": round(float(C[iu].mean()), 4),
        "block_sensitivity": {str(bl): float(r.p_value) for bl, r in res.items()},
        "null_max_q95_block20": float(canon.null_q95), "null_max_q99_block20": float(canon.null_q99),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": "regenerated on corrected base; winner is a raw P04 (defect-free) strategy",
    }
    (EXP07 / "white_reality_check_record.json").write_text(json.dumps(record, indent=2))
    (REM / "data/white_reality_check_record.json").write_text(json.dumps(record, indent=2))

    old = json.load(open(ARCH)) if ARCH.exists() else {}
    print("=== White's Reality Check — OLD (defective) vs NEW (corrected) ===")
    print(f"  winner   : OLD {old.get('strategy_version','?')}")
    print(f"             NEW {record['strategy_version']}")
    print(f"  observed : OLD {old.get('test_statistic')}  NEW {record['test_statistic']:.6f}")
    print(f"  WRC p    : OLD {old.get('p_value')}  NEW {record['p_value']:.6f}")
    print(f"  mean corr: NEW {record['mean_pairwise_corr']}")
    print("\n  block sensitivity (corrected):")
    print(sens.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
