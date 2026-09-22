"""
Versioned historical signal library — Project 04 authoritative LS20/LS30 books.

Verifies the ported P04 signals (1) are registered in the executor's vocabulary and
historical registry, (2) reproduce the authoritative combined_signal recipe exactly,
and (3) replay through the *real* cross-sectional runner to the notebook's published
metrics (LS20 Sharpe 1.5160 / MDD -0.6553, LS30 Sharpe 1.4176 / MDD -0.5490).

The fidelity replay needs the git-ignored raw data; those tests skip cleanly when the
recovery universe is absent (e.g. CI without the data tree) rather than failing.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from agents.experiment_runner.spec_validator import KNOWN_SIGNALS
from src.signals.library import get_signal_series
from src.signals.historical import (
    HISTORICAL_SIGNALS,
    P04_LS20_V1,
    P04_LS30_V1,
)
from src.signals.historical import p04_return_forecast as p04

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RECOVERY_UNIVERSE = _REPO_ROOT / "data" / "raw" / "project_04_universe_recovery"
_SOURCE_UNIVERSE = _REPO_ROOT / "data" / "raw" / "project_04_universe"


# --- registration ----------------------------------------------------------------

def test_p04_signals_registered_everywhere():
    for name in (P04_LS20_V1, P04_LS30_V1):
        assert name in KNOWN_SIGNALS          # spec validation
        assert name in HISTORICAL_SIGNALS     # historical registry
    assert P04_LS20_V1 == "hist_p04_ls20_v1"
    assert P04_LS30_V1 == "hist_p04_ls30_v1"


def test_thresholds_are_the_authoritative_values():
    # Cells 118 / 129 of 04_portfolio_research.ipynb.
    assert (p04._LS20_LONG, p04._LS20_SHORT) == (0.80, 0.20)
    assert (p04._LS30_LONG, p04._LS30_SHORT) == (0.70, 0.30)
    assert p04._V1_COLUMN == "pred_flipped" and p04._V2_COLUMN == "pred"


# --- authoritative recipe --------------------------------------------------------

@pytest.mark.skipif(not p04.V1_ARTIFACT.exists() or not p04.V2_ARTIFACT.exists(),
                    reason="v1/v2 forecast artifacts (git-ignored) not present")
def test_combined_signal_is_v1z_plus_v2z_over_intersection():
    df = p04._combined()
    # Inner join of v1 ∩ v2: 2016-01-04 … 2026-03-06, 20 tickers, 2558 dates.
    assert df["Date"].nunique() == 2558
    assert set(df["Ticker"].unique()) == {
        "AAPL", "AMZN", "BAC", "COST", "CVX", "GOOGL", "GS", "HD", "JNJ", "JPM",
        "LLY", "META", "MSFT", "NVDA", "PFE", "PG", "TSLA", "UNH", "WMT", "XOM",
    }
    # combined = z(v1) + z(v2); per-date z-scores are mean 0.
    recomputed = df["signal_v1_z"] + df["signal_v2_z"]
    assert (df["combined_signal"] - recomputed).abs().max() < 1e-12
    per_date_mean = df.groupby("Date")["combined_signal"].mean().abs().max()
    assert per_date_mean < 1e-9


@pytest.mark.skipif(not p04.V1_ARTIFACT.exists() or not p04.V2_ARTIFACT.exists(),
                    reason="v1/v2 forecast artifacts (git-ignored) not present")
def test_membership_is_pm1_and_index_aligned():
    panel = pd.DataFrame({
        "Date": pd.to_datetime(["2016-01-04"] * 20),
        "ticker": ["AAPL", "AMZN", "BAC", "COST", "CVX", "GOOGL", "GS", "HD", "JNJ",
                   "JPM", "LLY", "META", "MSFT", "NVDA", "PFE", "PG", "TSLA", "UNH",
                   "WMT", "XOM"],
    })
    for name in (P04_LS20_V1, P04_LS30_V1):
        s = get_signal_series(panel, name)
        assert list(s.index) == list(panel.index)
        assert set(s.dropna().unique()) <= {-1.0, 0.0, 1.0}
        assert (s > 0).any() and (s < 0).any()   # both sides populated


def test_out_of_window_is_nan_not_fabricated():
    panel = pd.DataFrame({"Date": pd.to_datetime(["1990-01-02"]), "ticker": ["AAPL"]})
    assert get_signal_series(panel, P04_LS20_V1).isna().all()


def test_unknown_signal_still_raises():
    with pytest.raises(ValueError):
        get_signal_series(pd.DataFrame({"Date": [], "ticker": []}), "does_not_exist")


# --- end-to-end fidelity through the real runner ---------------------------------

@pytest.mark.skipif(not _SOURCE_UNIVERSE.exists(),
                    reason="raw project_04 universe (git-ignored) not present")
@pytest.mark.parametrize("signal,exp_sharpe,exp_mdd", [
    (P04_LS20_V1, 1.5160, -0.6553),
    (P04_LS30_V1, 1.4176, -0.5490),
])
def test_factory_replay_matches_notebook(tmp_path, signal, exp_sharpe, exp_mdd):
    """Faithful replay: the ported signal, run through the *unmodified* cross-sectional
    runner over the date-scoped recovery universe, reproduces the notebook's published
    Sharpe/MDD to within tight tolerance (no engine change, no approximation)."""
    from agents.recovery.build_p04_recovery_universe import build
    from agents.protocol import ExperimentSpec
    from agents.experiment_runner import runner
    import json

    build()  # regenerate the scoped universe deterministically
    spec = ExperimentSpec(
        hypothesis="P04 authoritative replay", market="US_EQUITY",
        universe="project_04_universe_recovery", target="fwd_ret_5",
        features=[signal], model="cross_sectional_ls", validation_method="none",
        success_criteria={"sharpe_ratio": 1.0}, expected_improvement=0.0,
        project="project_04_return_forecast_alpha", experiment_id=f"fidelity_{signal}",
    )
    runner.run_experiment(
        spec, db_path=tmp_path / "m.db", completed_dir=tmp_path / "completed",
        data_root=_REPO_ROOT / "data" / "raw",
    )
    m = json.loads((tmp_path / "completed" / f"fidelity_{signal}" / "metrics.json").read_text())
    assert abs(m["sharpe"] - exp_sharpe) < 0.01, f"{signal}: sharpe {m['sharpe']}"
    assert abs(m["mdd"] - exp_mdd) < 0.01, f"{signal}: mdd {m['mdd']}"
