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


def test_project_04_05_06_executable_after_registration():
    """P04 books, the P05 overlays + final portfolio, and the P06 deployment tournament
    (all reusing the registered base signals) are executable; P02/P03 remain blocked
    pending the single-asset classifier path."""
    r = signal_gap.executable_readiness()
    assert set(r["executable"]) == {
        "p04_ls20", "p04_ls30",
        "p04_blend_40_60_ls20_ls30", "p04_blend_50_50_ls20_ls30",
        "p04_blend_60_40_ls20_ls30", "p04_blend_70_30_ls20_ls30",
        "p05_smooth_dd_ls20", "p05_smooth_dd_ls30",
        "p05_final_portfolio", "p06_deployment_tournament",
    }
    assert set(r["blocked"]) == {
        "p02_volatility_regime", "p03_spy_5d_direction",
    }


def test_missing_signals_are_the_original_names():
    missing = set(signal_gap.missing_signals())
    # Still-unported P02/P03 single-asset classifier feature names.
    for s in ("RV5_trail", "RV20_trail", "VolRatio", "rsi_14", "volume_ratio"):
        assert s in missing
    # P06 is now ported (deployment tournament reuses registered signals).
    assert "deployment_candidate_v1" not in missing
    # P04's ported books are now registered — no longer missing. P05 reuses them
    # (the overlay is applied by the executor, not a registry signal), so the old
    # 'smooth_drawdown_exposure' placeholder signal is gone.
    assert "hist_p04_ls20_v1" not in missing
    assert "hist_p04_ls30_v1" not in missing
    assert "smooth_drawdown_exposure" not in missing


def test_readiness_is_deterministic():
    assert signal_gap.executable_readiness() == signal_gap.executable_readiness()
