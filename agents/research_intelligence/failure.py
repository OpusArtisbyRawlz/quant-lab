"""
failure.py — the pure ``failure_v1`` failure-taxonomy policy (M11 PR-9, M11-5).

Maps a **failed / rejected** experiment to a single deterministic **reason code**
from a fixed taxonomy, using signals already captured on the PR-1
``evidence_event`` (critic decision, net Sharpe, sample size, robustness flags).
It is the *structured sibling* to the prose ``lessons_learned`` — reason codes, not
free text.

Pure: no database, no RNG, no wall-clock. Given the same signals it always returns
the same classification.

A single **primary** reason code is chosen by a fixed priority (most fundamental
first) so the classification is unambiguous; the full signal set (including every
robustness flag) is preserved in ``detail`` for audit.

Failure detection: an experiment is a failure iff the critic **rejected** it, or it
has **no economic edge** (net Sharpe ≤ S0). A kept, positive experiment is not a
failure (even if it carries a robustness caveat).

Reason-code priority (fixed): ``insufficient_evidence`` (too few periods to trust
anything) → ``no_edge`` (net Sharpe ≤ S0) → ``cost_fragility`` → ``subperiod_instability``
→ ``parameter_fragility`` → ``rejected_other``.

The robustness-flag vocabulary is the upstream one
(``agents/experiment_runner/robustness.py``); ``min_periods`` (the
insufficient-evidence threshold) is not enumerated in the frozen docs, so it is a
``FailurePolicy`` knob (default 252 = one year of daily periods).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Reason codes (fixed taxonomy).
REASON_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
REASON_NO_EDGE = "no_edge"
REASON_COST_FRAGILITY = "cost_fragility"
REASON_SUBPERIOD_INSTABILITY = "subperiod_instability"
REASON_PARAMETER_FRAGILITY = "parameter_fragility"
REASON_REJECTED_OTHER = "rejected_other"

REASON_CODES = (
    REASON_INSUFFICIENT_EVIDENCE, REASON_NO_EDGE, REASON_COST_FRAGILITY,
    REASON_SUBPERIOD_INSTABILITY, REASON_PARAMETER_FRAGILITY, REASON_REJECTED_OTHER,
)

# Upstream robustness-flag vocabulary (mirrored, not imported, to keep the M11
# boundary clean — see the same choice in promotion.py).
FLAG_COST_FRAGILITY = "cost_fragility"
FLAG_SUBPERIOD_INSTABILITY = "subperiod_instability"
FLAG_PARAMETER_FRAGILITY = "parameter_fragility"


@dataclass(frozen=True)
class FailurePolicy:
    version: str = "failure_v1"
    S0: float = 0.0                       # break-even (no economic edge at/below)
    min_periods: int = 252               # insufficient-evidence threshold (config)
    reject_decisions: frozenset[str] = frozenset({"reject"})


DEFAULT_POLICY = FailurePolicy()


@dataclass(frozen=True)
class FailureSignals:
    experiment_id: str
    critic_decision: str | None = None
    net_sharpe: float | None = None
    periods: int | None = None            # return periods T (sample size)
    robustness_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FailureResult:
    experiment_id: str
    is_failure: bool
    reason_code: str | None
    detail: dict[str, Any] = field(default_factory=dict)


def classify(signals: FailureSignals,
             policy: FailurePolicy = DEFAULT_POLICY) -> FailureResult:
    """Classify one experiment. Deterministic; no RNG.

    Returns ``is_failure=False`` (and ``reason_code=None``) for a non-failure.
    """
    flags = set(signals.robustness_flags or ())
    rejected = signals.critic_decision in policy.reject_decisions
    no_edge = signals.net_sharpe is not None and signals.net_sharpe <= policy.S0

    detail = {
        "critic_decision": signals.critic_decision,
        "net_sharpe": signals.net_sharpe,
        "periods": signals.periods,
        "robustness_flags": sorted(flags),
        "rejected": rejected,
    }

    if not (rejected or no_edge):
        return FailureResult(signals.experiment_id, False, None, detail)

    if signals.periods is not None and signals.periods < policy.min_periods:
        reason = REASON_INSUFFICIENT_EVIDENCE
    elif no_edge:
        reason = REASON_NO_EDGE
    elif FLAG_COST_FRAGILITY in flags:
        reason = REASON_COST_FRAGILITY
    elif FLAG_SUBPERIOD_INSTABILITY in flags:
        reason = REASON_SUBPERIOD_INSTABILITY
    elif FLAG_PARAMETER_FRAGILITY in flags:
        reason = REASON_PARAMETER_FRAGILITY
    else:
        reason = REASON_REJECTED_OTHER

    detail["reason_code"] = reason
    return FailureResult(signals.experiment_id, True, reason, detail)
