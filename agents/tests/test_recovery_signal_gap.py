"""
Recovery signal-gap analysis tests.

Codifies the current executability blocker: recovered strategies declare their
original signal names, which are not (yet) in the executor's KNOWN_SIGNALS vocabulary.
The helper reports the gap faithfully (no invented signals, no definition changes).
"""

from __future__ import annotations

from agents.experiment_runner.spec_validator import KNOWN_SIGNALS
from agents.recovery import signal_gap, manifest


def test_gap_covers_every_recovered_strategy():
    gap = signal_gap.signal_gap()
    ids = {g["strategy_id"] for g in gap}
    assert ids == {s["strategy_id"] for s in manifest.enumerate_strategies()}


def test_registered_is_subset_of_known_signals():
    # The helper never invents: 'registered' is exactly the intersection with the
    # executor's KNOWN_SIGNALS.
    for g in signal_gap.signal_gap():
        assert set(g["registered"]) <= set(KNOWN_SIGNALS)
        assert set(g["missing"]).isdisjoint(KNOWN_SIGNALS)


def test_project_04_executable_after_registration():
    """P04's ML forecast is ported (hist_p04_return_forecast_v1), so all six P04
    strategies are now executable; P02/P03/P05/P06 remain blocked pending their ports."""
    r = signal_gap.executable_readiness()
    assert set(r["executable"]) == {
        "p04_ls20", "p04_ls30",
        "p04_blend_40_60_ls20_ls30", "p04_blend_50_50_ls20_ls30",
        "p04_blend_60_40_ls20_ls30", "p04_blend_70_30_ls20_ls30",
    }
    assert set(r["blocked"]) == {
        "p02_volatility_regime", "p03_spy_5d_direction",
        "p05_risk_engine_smooth_dd", "p06_deployment_candidate_v1",
    }


def test_missing_signals_are_the_original_names():
    missing = set(signal_gap.missing_signals())
    # Still-unported P02/P03/P05/P06 original signal/overlay/deployment names.
    for s in ("RV5_trail", "RV20_trail", "VolRatio", "rsi_14", "volume_ratio",
              "smooth_drawdown_exposure", "deployment_candidate_v1"):
        assert s in missing
    # P04's forecast is now registered — no longer missing.
    assert "hist_p04_return_forecast_v1" not in missing


def test_readiness_is_deterministic():
    assert signal_gap.executable_readiness() == signal_gap.executable_readiness()
