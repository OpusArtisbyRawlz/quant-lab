"""
Remaining P04 variants + P05 overlays — recovery fidelity.

Each variant/overlay is a composite PortfolioSpec (1-child weight-transform, 2-child
blend, or blend + vol-target / smooth-DD overlay) recovered through the real runner.
A representative subset is replayed end-to-end and checked against the historical
reference (strategy_comparison.csv / all_strategies_smooth_dd_results.csv); the manifest
is checked for completeness. Data-dependent tests skip when the raw universe is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_UNIV = _REPO / "data" / "raw" / "project_04_universe"
_MANIFEST = json.loads((_REPO / "agents" / "recovery" / "historical_strategies.json").read_text())
_BYID = {s["strategy_id"]: s for s in _MANIFEST["strategies"]}


def test_manifest_has_all_p04_variants_and_p05_overlays():
    p04 = {s["strategy_id"] for s in _MANIFEST["strategies"]
           if s["project"] == "project_04_return_forecast_alpha"}
    p05 = {s["strategy_id"] for s in _MANIFEST["strategies"]
           if s["project"] == "project_05_risk_engine"}
    assert {"p04_ls20_linear", "p04_ls20_sqrt", "p04_ls20_pow07", "p04_ls20_sqrt_partial",
            "p04_ls20_sqrt_partial_norm", "p04_ls30_sqrt_partial_norm",
            "p04_ls20_sqrt_partial_norm_neut", "p04_ls30_sqrt_partial_norm_neut",
            "p04_blend_70_30", "p04_blend_60_40", "p04_blend_50_50", "p04_blend_40_60",
            "p04_blend_60_40_vt_015", "p04_blend_60_40_vt_018",
            "p04_blend_60_40_vt_020", "p04_blend_60_40_vt_025"} <= p04
    assert {"p05_smooth_dd_blend_60_40", "p05_smooth_dd_ls20_sqrt_partial_norm",
            "p05_smooth_dd_ls30_sqrt_partial_norm"} <= p05


def _replay(tmp_path, sid, eid):
    from agents.recovery.build_p04_recovery_universe import build
    from agents.protocol import ExperimentSpec
    from agents.experiment_runner import runner
    build()
    s = _BYID[sid]
    spec = ExperimentSpec(
        hypothesis=s["hypothesis"], market="US_EQUITY", universe=s["universe"],
        target="fwd_ret_5", features=s["signals"], model="composite",
        validation_method="none", success_criteria={"sharpe": 1.0},
        expected_improvement="", experiment_id=eid, portfolio=s["portfolio"])
    runner.run_experiment(spec, db_path=tmp_path / "d.db",
                          completed_dir=tmp_path / "c", data_root=_REPO / "data" / "raw")
    return json.loads((tmp_path / "c" / eid / "metrics.json").read_text())


# Representative subset (one of each recipe family) — kept small for test runtime.
@pytest.mark.skipif(not _UNIV.exists(), reason="raw universe (git-ignored) absent")
@pytest.mark.parametrize("sid,sharpe,mdd", [
    ("p04_ls20_sqrt", 1.482, -0.633),                    # full vol-regime exposure
    ("p04_ls20_sqrt_partial_norm", 1.544, -0.655),       # partial + normalize
    ("p04_ls20_sqrt_partial_norm_neut", 1.098, -0.645),  # + neutralize
    ("p04_blend_50_50", 1.503, -0.604),                  # blend composite
    ("p04_blend_60_40_vt_020", 1.256, -0.614),           # blend + vol target
    ("p05_smooth_dd_blend_60_40", 1.824, -0.469),        # P05 smooth-DD on a P04 variant
])
def test_variant_replay_fidelity(tmp_path, sid, sharpe, mdd):
    m = _replay(tmp_path, sid, f"t_{sid}")
    assert abs(m["sharpe"] - sharpe) < 0.01, f"{sid}: sharpe {m['sharpe']}"
    assert abs(m["mdd"] - mdd) < 0.01, f"{sid}: mdd {m['mdd']}"
