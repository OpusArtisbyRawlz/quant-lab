"""
Recovery signal-gap analysis.

Pure, read-only: compares each recovered strategy's declared signals against the
executor's registered signal vocabulary (``spec_validator.KNOWN_SIGNALS``) and reports
what is missing, so "executable readiness" is explicit and testable. It invents no
signals and changes no strategy definitions — it only *reports* the gap between the
faithfully-imported original signal names and what the cross-sectional executor
currently knows.
"""

from __future__ import annotations

from typing import Any

from agents.experiment_runner.spec_validator import KNOWN_SIGNALS
from agents.recovery import manifest


def strategy_gap(strategy: dict[str, Any]) -> dict[str, Any]:
    """Registered vs missing signals for one recovered strategy (deterministic).

    Classifier strategies execute through the single-asset classifier path, not the
    cross-sectional signal registry, so KNOWN_SIGNALS does not gate them — their
    ``signals`` list holds model feature names and is reported as registered.
    """
    is_classifier = strategy.get("kind") == "classifier"
    signals = list(strategy.get("signals", []))
    if is_classifier:
        return {
            "strategy_id": strategy["strategy_id"], "project": strategy["project"],
            "mapping_status": strategy.get("mapping_status"), "signals": signals,
            "registered": signals, "missing": [], "executable": True,
        }
    registered = [s for s in signals if s in KNOWN_SIGNALS]
    missing = [s for s in signals if s not in KNOWN_SIGNALS]
    return {
        "strategy_id": strategy["strategy_id"],
        "project": strategy["project"],
        "mapping_status": strategy.get("mapping_status"),
        "signals": signals,
        "registered": registered,
        "missing": missing,
        "executable": not missing,
    }


def signal_gap() -> list[dict[str, Any]]:
    """Gap report for every recovered strategy, sorted by strategy_id."""
    return [strategy_gap(s) for s in manifest.enumerate_strategies()]


def missing_signals() -> list[str]:
    """The sorted, de-duplicated set of signal names required by recovered strategies
    but NOT registered in the executor's KNOWN_SIGNALS."""
    out: set[str] = set()
    for row in signal_gap():
        out.update(row["missing"])
    return sorted(out)


def executable_readiness() -> dict[str, Any]:
    """Summary: which recovered strategies are executable today vs blocked on missing
    signal registrations."""
    gap = signal_gap()
    executable = [g["strategy_id"] for g in gap if g["executable"]]
    blocked = [g["strategy_id"] for g in gap if not g["executable"]]
    return {
        "known_signals": sorted(KNOWN_SIGNALS),
        "executable": executable,
        "blocked": blocked,
        "missing_signals": missing_signals(),
    }
