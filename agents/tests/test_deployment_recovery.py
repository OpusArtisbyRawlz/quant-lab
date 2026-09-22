"""
Project 06 — deployment-validation recovery + reusable deployment-evaluation stage.

Verifies:
- the ported tournament reproduces the historical master_comparison EXACTLY on the
  stored base (validates the battery + DeploymentQuality port);
- the deployment stage, run on the recovered P05 PortfolioSpec base, reproduces the
  V1 incumbent, the promotion decision, and the top-3 deployable ordering exactly;
- the DATA_INTEGRITY_ISSUE note is recorded.

Data-dependent tests skip when the git-ignored raw universe is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]
_UNIV = _REPO / "data" / "raw" / "project_04_universe"
_EXP5 = _REPO / "experiments" / "completed" / "exp_005_risk_engine_final"
_MASTER = (_REPO / "experiments" / "completed"
           / "exp_006_deployment_candidate_tournament" / "master_comparison.csv")


def test_data_integrity_note_recorded():
    from agents.recovery import status
    note = status.DATA_INTEGRITY_NOTES["p06_deployment_tournament"]
    assert note["column"] == "portfolio_dd_exposure"
    assert status.DATA_INTEGRITY_ISSUE in status.MARKERS


@pytest.mark.skipif(not (_MASTER.exists() and _UNIV.exists()),
                    reason="tournament artifacts / raw universe (git-ignored) absent")
def test_port_reproduces_master_comparison_on_stored_base():
    import src.analysis.deployment_tournament as dt
    dep = pd.read_csv(_EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(_EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    wide = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index()
    dates = wide.index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)
    v2 = pd.read_csv(_EXP5 / "final_returns_v2_with_dates.csv")
    v2["date"] = pd.to_datetime(v2["date"])
    v2 = v2.set_index("date")["returns"].astype(float)
    adv = dt.build_adv_panel(list(wide.columns), dates, _UNIV)
    comp = dt.run_tournament(pr, wide, exp, v2, adv)
    stored = pd.read_csv(_MASTER)
    assert list(comp["Candidate"]) == list(stored["Candidate"])   # ordering exact
    m = comp.set_index("Candidate"); s = stored.set_index("Candidate")
    for col in ["Sharpe", "MDD", "Cost-adj Sharpe (10bps)", "DeployQuality",
                "Capacity @10% median ($)", "Ops worst Sharpe"]:
        d = (m[col].astype(float) - s.reindex(m.index)[col].astype(float)).abs()
        assert np.nanmax(d.values) < 1e-9, f"{col}: {np.nanmax(d.values)}"


@pytest.mark.skipif(not (_MASTER.exists() and _UNIV.exists()),
                    reason="tournament artifacts / raw universe (git-ignored) absent")
def test_deployment_stage_reproduces_decision_from_portfolio_spec():
    from agents.recovery.build_p04_recovery_universe import build
    from agents.experiment_runner.data_loader import load_data
    from agents.experiment_runner import deployment_stage as dstage
    build()
    m = json.loads((_REPO / "agents" / "recovery" / "historical_strategies.json").read_text())
    pf = next(s for s in m["strategies"]
              if s["strategy_id"] == "p06_deployment_tournament")["portfolio"]
    data = load_data(_REPO / "data" / "raw" / "project_04_universe_recovery").data_dict
    comp, decision = dstage.run_deployment_tournament(
        pf, data,
        v2_source=_EXP5 / "final_returns_v2_with_dates.csv", adv_data_dir=_UNIV)
    stored = pd.read_csv(_MASTER)
    # V1 incumbent + promotion + top-3 reproduce exactly (self-consistent base).
    assert abs(decision["incumbent_v1_sharpe"] - 2.0901) < 0.01
    assert decision["promoted_candidate"] == stored.iloc[0]["Candidate"] == "DD Only (floor0.3,k5)"
    assert list(comp["Candidate"].head(3)) == list(stored["Candidate"].head(3))
    assert (decision["n_candidates"], decision["n_deployable"]) == (15, 9)
