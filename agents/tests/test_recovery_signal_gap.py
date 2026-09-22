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
    # The helper never invents: for cross-sectional strategies 'registered' is exactly
    # the intersection with KNOWN_SIGNALS. Classifier strategies execute via the
    # classifier path (their features are not cross-sectional signals), so they are
    # exempt from the KNOWN_SIGNALS subset rule.
    classifier_ids = {s["strategy_id"] for s in manifest.enumerate_strategies()
                      if s.get("kind") == "classifier"}
    for g in signal_gap.signal_gap():
        if g["strategy_id"] in classifier_ids:
            continue
        assert set(g["registered"]) <= set(KNOWN_SIGNALS)
        assert set(g["missing"]).isdisjoint(KNOWN_SIGNALS)


def test_project_04_05_06_executable_after_registration():
    """P04 books, the P05 overlays + final portfolio, and the P06 deployment tournament
    (all reusing the registered base signals) are executable; P02/P03 remain blocked
    pending the single-asset classifier path."""
    r = signal_gap.executable_readiness()
    # P04/P05/P06 reuse registered signals; P03 executes via the classifier path.
    # Only P02 (single-asset vol-regime model, not yet given a classifier port) remains
    # blocked on signal registration.
    assert set(r["blocked"]) == {"p02_volatility_regime"}
    execset = set(r["executable"])
    assert {"p04_ls20", "p04_ls30", "p05_final_portfolio",
            "p06_deployment_tournament",
            "p03_logistic", "p03_random_forest", "p03_naive_baseline"} <= execset
    # everything except P02 is executable
    for g in signal_gap.signal_gap():
        if g["strategy_id"] != "p02_volatility_regime":
            assert g["executable"], g["strategy_id"]


def test_missing_signals_are_the_original_names():
    missing = set(signal_gap.missing_signals())
    # Only P02's single-asset vol-regime feature names remain unregistered.
    for s in ("RV5_trail", "RV20_trail", "VolRatio"):
        assert s in missing
    # P06 ported (reuses registered signals); P03 executes via the classifier path.
    assert "deployment_candidate_v1" not in missing
    # P04's ported books are now registered — no longer missing. P05 reuses them
    # (the overlay is applied by the executor, not a registry signal), so the old
    # 'smooth_drawdown_exposure' placeholder signal is gone.
    assert "hist_p04_ls20_v1" not in missing
    assert "hist_p04_ls30_v1" not in missing
    assert "smooth_drawdown_exposure" not in missing


def test_readiness_is_deterministic():
    assert signal_gap.executable_readiness() == signal_gap.executable_readiness()
