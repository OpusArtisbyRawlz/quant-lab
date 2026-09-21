"""
Project 05 — smooth-drawdown overlay recovery.

Verifies the P05 risk overlay replays through the *unmodified* cross-sectional runner:
the executor applies the authoritative ``src/risk`` overlay to the portfolio return
series (path-dependent, so not a cross-sectional signal) via the optional
``ExperimentSpec.overlay`` field, threaded from the recovered idea's metadata.

Fidelity targets (experiments/completed/exp_005_risk_engine_final/
all_strategies_smooth_dd_results.csv, smooth-DD column):
    ls_20pct : Sharpe 1.860, MDD -0.502, CAGR 0.424, Calmar 0.845
    ls_30pct : Sharpe 1.663, MDD -0.420, CAGR 0.299, Calmar 0.711

The end-to-end replay needs the git-ignored raw data; it skips cleanly when absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_UNIVERSE = _REPO_ROOT / "data" / "raw" / "project_04_universe"


def test_overlay_field_defaults_off_and_spec_builder_threads_it():
    from agents.protocol import ExperimentSpec
    from agents.idea_generator.spec_builder import idea_to_spec
    # Default: no overlay (existing specs unchanged).
    assert ExperimentSpec("h", "m", "u", "t", ["s"], "mo", "none", {}, "").overlay is None
    # spec_builder threads overlay from idea metadata.
    row = {"hypothesis": "h", "market": "US_EQUITY", "universe": "u",
           "suggested_signals": ["hist_p04_ls20_v1"], "bar_type": "time",
           "metadata": {"overlay": {"method": "smooth_dd", "floor": 0.55, "k": 5}}}
    spec = idea_to_spec(row)
    assert spec.overlay == {"method": "smooth_dd", "floor": 0.55, "k": 5}


def test_apply_overlay_matches_authoritative_src_risk():
    """The executor's overlay dispatch reproduces src.risk.allocation exactly."""
    from agents.experiment_runner.runner import _apply_overlay
    from src.risk import drawdown as dd
    import numpy as np
    rng = np.random.default_rng(0)
    ret = pd.Series(rng.normal(0.001, 0.02, 400))
    got = _apply_overlay(ret, {"method": "smooth_dd", "floor": 0.55, "k": 5})
    # Reference: equity -> drawdown -> smooth exposure -> lag-1 applied.
    eq = (1 + ret).cumprod()
    exp = dd.drawdown_exposure_smooth(dd.compute_drawdown(eq), floor=0.55, k=5)
    ref = dd.apply_exposure_to_return(ret, exp)
    pd.testing.assert_series_equal(got, ref)


def test_unknown_overlay_raises():
    from agents.experiment_runner.runner import _apply_overlay
    with pytest.raises(ValueError):
        _apply_overlay(pd.Series([0.0]), {"method": "nope"})


@pytest.mark.skipif(not _SOURCE_UNIVERSE.exists(),
                    reason="raw project_04 universe (git-ignored) not present")
@pytest.mark.parametrize("signal,exp_sharpe,exp_mdd,exp_cagr", [
    ("hist_p04_ls20_v1", 1.860, -0.502, 0.424),
    ("hist_p04_ls30_v1", 1.663, -0.420, 0.299),
])
def test_factory_replay_matches_notebook(tmp_path, signal, exp_sharpe, exp_mdd, exp_cagr):
    from agents.recovery.build_p04_recovery_universe import build
    from agents.protocol import ExperimentSpec
    from agents.experiment_runner import runner
    build()
    spec = ExperimentSpec(
        hypothesis="P05 smooth-DD replay", market="US_EQUITY",
        universe="project_04_universe_recovery", target="fwd_ret_5",
        features=[signal], model="cross_sectional_ls", validation_method="none",
        success_criteria={"sharpe": 1.0}, expected_improvement="",
        project="project_05_risk_engine", experiment_id=f"p05_fidelity_{signal}",
        overlay={"method": "smooth_dd", "floor": 0.55, "k": 5},
    )
    runner.run_experiment(spec, db_path=tmp_path / "m.db",
                          completed_dir=tmp_path / "completed",
                          data_root=_REPO_ROOT / "data" / "raw")
    m = json.loads((tmp_path / "completed" / f"p05_fidelity_{signal}" / "metrics.json").read_text())
    assert abs(m["sharpe"] - exp_sharpe) < 0.01, f"{signal}: sharpe {m['sharpe']}"
    assert abs(m["mdd"] - exp_mdd) < 0.01, f"{signal}: mdd {m['mdd']}"
    assert abs(m["cagr"] - exp_cagr) < 0.01, f"{signal}: cagr {m['cagr']}"
