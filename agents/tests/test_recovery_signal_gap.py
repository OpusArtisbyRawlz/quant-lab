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


def test_current_reality_all_blocked():
    """Documents today's state: no recovered strategy is executable because its
    original signals are not registered. Flips as registrations land."""
    r = signal_gap.executable_readiness()
    assert r["executable"] == []
    assert len(r["blocked"]) == len(manifest.enumerate_strategies())


def test_missing_signals_are_the_original_names():
    missing = set(signal_gap.missing_signals())
    # Original P02/P03 technical features + P04/P05/P06 model/overlay/deployment names.
    for s in ("RV5_trail", "RV20_trail", "VolRatio", "rsi_14", "volume_ratio",
              "ml_return_forecast_5d", "smooth_drawdown_exposure",
              "deployment_candidate_v1"):
        assert s in missing


def test_readiness_is_deterministic():
    assert signal_gap.executable_readiness() == signal_gap.executable_readiness()
