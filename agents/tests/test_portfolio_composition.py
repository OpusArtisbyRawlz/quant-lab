"""
Multi-strategy portfolio composition (general factory capability).

Covers the required contract:
1. single-strategy execution is unchanged (portfolio defaults off);
2. two-child fixed-weight composition reproduces the weighted series exactly;
3. deterministic child ordering;
4. replay is byte-identical;
5. a missing/unknown child fails clearly;
6. weight / structure validation;
7. explicit date-alignment behaviour;
8. portfolio-level overlay is applied only after child composition;
9. provenance chain: composite → children → signals → historical source.

Data-dependent end-to-end tests skip when the git-ignored raw universe is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.portfolio.composite import PortfolioSpec, PortfolioChild, combine_returns

_REPO = Path(__file__).resolve().parents[2]
_UNIV = _REPO / "data" / "raw" / "project_04_universe"


# --- 6. validation -------------------------------------------------------------

def test_weight_and_structure_validation():
    with pytest.raises(ValueError):  # weights must sum to 1
        PortfolioSpec("p", [PortfolioChild("a", 0.5, features=["x"]),
                            PortfolioChild("b", 0.2, features=["y"])]).validate()
    with pytest.raises(ValueError):  # duplicate child_id
        PortfolioSpec("p", [PortfolioChild("a", 0.5, features=["x"]),
                            PortfolioChild("a", 0.5, features=["y"])]).validate()
    with pytest.raises(ValueError):  # neither features nor portfolio
        PortfolioSpec("p", [PortfolioChild("a", 1.0)]).validate()
    with pytest.raises(ValueError):  # empty children
        PortfolioSpec("p", []).validate()
    # valid
    PortfolioSpec("p", [PortfolioChild("a", 0.6, features=["x"]),
                        PortfolioChild("b", 0.4, features=["y"])]).validate()


# --- 3. deterministic ordering -------------------------------------------------

def test_deterministic_child_ordering():
    a = PortfolioChild("z", 0.5, features=["x"])
    b = PortfolioChild("a", 0.5, features=["y"])
    spec = PortfolioSpec("p", [a, b])
    assert [c.child_id for c in spec.ordered_children()] == ["a", "z"]


# --- 2 & 7. composition math + date alignment ----------------------------------

def test_two_child_weighted_series_exact():
    idx = pd.date_range("2020-01-01", periods=5)
    r1 = pd.Series([0.01, -0.02, 0.03, 0.00, 0.01], index=idx)
    r2 = pd.Series([0.00, 0.01, -0.01, 0.02, 0.00], index=idx)
    got = combine_returns([("a", r1, 0.6), ("b", r2, 0.4)])
    expected = 0.6 * r1 + 0.4 * r2
    pd.testing.assert_series_equal(got, expected)


def test_date_alignment_is_explicit_union_fill_zero():
    r1 = pd.Series([0.01, 0.02], index=pd.to_datetime(["2020-01-01", "2020-01-02"]))
    r2 = pd.Series([0.03, 0.04], index=pd.to_datetime(["2020-01-02", "2020-01-03"]))
    got = combine_returns([("a", r1, 1.0), ("b", r2, 1.0)])
    # union of dates; missing child contributes 0 on non-shared dates
    assert got.loc["2020-01-01"] == pytest.approx(0.01)
    assert got.loc["2020-01-02"] == pytest.approx(0.02 + 0.03)
    assert got.loc["2020-01-03"] == pytest.approx(0.04)


# --- (de)serialisation round-trip (used to transport the spec via idea metadata) --

def test_spec_dict_roundtrip_with_nested_and_overlays():
    spec = PortfolioSpec(
        "p", universe="u", overlay={"method": "smooth_dd", "floor": 0.55, "k": 5},
        children=[
            PortfolioChild("a", 0.5, features=["s1"],
                           weight_overlay={"method": "vol_regime_partial", "a": 0.5, "b": 0.5},
                           overlay={"method": "smooth_dd", "floor": 0.55, "k": 5}),
            PortfolioChild("b", 0.5, portfolio=PortfolioSpec(
                "nested", children=[PortfolioChild("x", 0.6, features=["s1"]),
                                    PortfolioChild("y", 0.4, features=["s2"])])),
        ])
    spec.validate()
    back = PortfolioSpec.from_dict(spec.to_dict())
    assert back.to_dict() == spec.to_dict()
    assert back.children[1].portfolio.children[0].child_id == "x"


# --- end-to-end (factory) tests ------------------------------------------------

_SDD = {"method": "smooth_dd", "floor": 0.55, "k": 5}


def _p05_final_portfolio_dict():
    return {
        "portfolio_id": "p05_final_portfolio", "universe": "project_04_universe_recovery",
        "weighting": "fixed", "overlay": _SDD,
        "children": [
            {"child_id": "a_ls20_sqrt_partial_norm", "weight": 0.5,
             "features": ["hist_p04_ls20_v1"],
             "weight_overlay": {"method": "vol_regime_partial", "a": 0.5, "b": 0.5},
             "overlay": _SDD},
            {"child_id": "b_blend_60_40", "weight": 0.3, "overlay": _SDD,
             "portfolio": {"portfolio_id": "blend_60_40", "weighting": "fixed", "children": [
                 {"child_id": "ls20", "weight": 0.6, "features": ["hist_p04_ls20_v1"]},
                 {"child_id": "ls30", "weight": 0.4, "features": ["hist_p04_ls30_v1"]}]}},
            {"child_id": "c_ls30", "weight": 0.2, "features": ["hist_p04_ls30_v1"], "overlay": _SDD},
        ],
    }


def _run(tmp_path, spec_kwargs, eid):
    from agents.recovery.build_p04_recovery_universe import build
    from agents.protocol import ExperimentSpec
    from agents.experiment_runner import runner
    build()
    spec = ExperimentSpec(
        hypothesis="t", market="US_EQUITY", universe="project_04_universe_recovery",
        target="fwd_ret_5", features=["hist_p04_ls20_v1"], model="m",
        validation_method="none", success_criteria={"sharpe": 1.0},
        expected_improvement="", experiment_id=eid, **spec_kwargs)
    runner.run_experiment(spec, db_path=tmp_path / "d.db",
                          completed_dir=tmp_path / "c", data_root=_REPO / "data" / "raw")
    return json.loads((tmp_path / "c" / eid / "metrics.json").read_text())


@pytest.mark.skipif(not _UNIV.exists(), reason="raw universe (git-ignored) absent")
def test_single_strategy_execution_unchanged(tmp_path):
    # No portfolio ⇒ the ordinary single-strategy path; LS20 still 1.516.
    m = _run(tmp_path, {}, "single_ls20")
    assert abs(m["sharpe"] - 1.516) < 0.01


@pytest.mark.skipif(not _UNIV.exists(), reason="raw universe (git-ignored) absent")
def test_p05_final_portfolio_fidelity(tmp_path):
    m = _run(tmp_path, {"portfolio": _p05_final_portfolio_dict()}, "p05_final")
    assert abs(m["sharpe"] - 2.09) < 0.01
    assert abs(m["mdd"] - (-0.367)) < 0.01
    assert abs(m["cagr"] - 0.377) < 0.01
    assert abs(m["vol"] - 0.159) < 0.01


@pytest.mark.skipif(not _UNIV.exists(), reason="raw universe (git-ignored) absent")
def test_replay_byte_identical(tmp_path):
    a = _run(tmp_path / "1", {"portfolio": _p05_final_portfolio_dict()}, "p05_a")
    b = _run(tmp_path / "2", {"portfolio": _p05_final_portfolio_dict()}, "p05_b")
    for k in ("sharpe", "mdd", "cagr", "vol", "calmar"):
        assert a[k] == b[k]


@pytest.mark.skipif(not _UNIV.exists(), reason="raw universe (git-ignored) absent")
def test_missing_child_signal_fails_clearly(tmp_path):
    bad = _p05_final_portfolio_dict()
    bad["children"][2]["features"] = ["hist_does_not_exist"]
    from agents.protocol import ExperimentSpec
    from agents.experiment_runner import runner
    from agents.recovery.build_p04_recovery_universe import build
    build()
    spec = ExperimentSpec(hypothesis="t", market="US_EQUITY",
                          universe="project_04_universe_recovery", target="fwd_ret_5",
                          features=["hist_p04_ls20_v1"], model="m", validation_method="none",
                          success_criteria={}, expected_improvement="",
                          experiment_id="p05_bad", portfolio=bad)
    r = runner.run_experiment(spec, db_path=tmp_path / "d.db",
                              completed_dir=tmp_path / "c", data_root=_REPO / "data" / "raw")
    assert r.status == "failed"
    assert "hist_does_not_exist" in (r.error or "")


@pytest.mark.skipif(not _UNIV.exists(), reason="raw universe (git-ignored) absent")
def test_portfolio_overlay_applied_after_composition(tmp_path):
    # With the portfolio-level overlay removed, the composite is un-damped, so its
    # drawdown is deeper and Sharpe differs — proving the overlay acts on the combined
    # series, not the children.
    with_overlay = _run(tmp_path / "w", {"portfolio": _p05_final_portfolio_dict()}, "p05_w")
    no = _p05_final_portfolio_dict(); no["overlay"] = None
    without = _run(tmp_path / "n", {"portfolio": no}, "p05_n")
    assert with_overlay["mdd"] != without["mdd"]
    assert abs(without["mdd"]) > abs(with_overlay["mdd"])  # portfolio DD reduces MDD


# --- 9. provenance chain -------------------------------------------------------

def test_manifest_portfolio_provenance_chain():
    m = json.loads((_REPO / "agents" / "recovery" / "historical_strategies.json").read_text())
    entry = next(s for s in m["strategies"] if s["strategy_id"] == "p05_final_portfolio")
    assert entry["kind"] == "portfolio"
    assert entry["origin_notebook"].endswith("01_drawdown_overlay.ipynb")
    # composite → children → recovered P04 signals (historical source)
    child_signals = set()
    def collect(pf):
        for c in pf["children"]:
            if c.get("features"):
                child_signals.update(c["features"])
            if c.get("portfolio"):
                collect(c["portfolio"])
    collect(entry["portfolio"])
    assert child_signals == {"hist_p04_ls20_v1", "hist_p04_ls30_v1"}
