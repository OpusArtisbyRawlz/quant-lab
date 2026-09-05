"""
M11 PR-8 — decision-consumption policy (``decision_v1``), pure-function tests.

The evidence → {confirmed, refuted, generalises} mapping the research agents
consume. No database, no RNG — a pure function of an EvidenceView.
"""

from __future__ import annotations

from agents.research_intelligence.decision import (
    DecisionPolicy, DEFAULT_POLICY, EvidenceView,
    is_confirmed, is_refuted, does_generalise, RETIRED_REFUTED,
)


def _view(pi=0.5, mu=0.5, g=1, retired=False, retired_state=None):
    return EvidenceView("H", q_exceed_prob=pi, posterior_mean=mu, g_count=g,
                        retired=retired, retired_state=retired_state)


# --- confirmed ------------------------------------------------------------

def test_confirmed_true_for_strong_positive_posterior():
    assert is_confirmed(_view(pi=0.99, mu=0.9)) is True


def test_confirmed_false_below_pi_bar():
    assert is_confirmed(_view(pi=0.80, mu=0.9)) is False       # π < 0.90


def test_confirmed_false_for_nonpositive_mean():
    assert is_confirmed(_view(pi=0.99, mu=-0.1)) is False


def test_confirmed_false_when_retired():
    assert is_confirmed(_view(pi=0.99, mu=0.9, retired=True)) is False


# --- refuted --------------------------------------------------------------

def test_refuted_true_when_retired_refuted():
    assert is_refuted(_view(pi=0.9, retired=True, retired_state=RETIRED_REFUTED)) is True


def test_refuted_true_when_pi_below_floor():
    assert is_refuted(_view(pi=0.05)) is True
    assert is_refuted(_view(pi=0.051)) is False


def test_refuted_false_for_promising():
    assert is_refuted(_view(pi=0.9)) is False


# --- generalises ----------------------------------------------------------

def test_generalises_requires_g_count_bar():
    assert does_generalise(_view(g=2)) is True
    assert does_generalise(_view(g=1)) is False


# --- config + version -----------------------------------------------------

def test_custom_policy_thresholds_respected():
    strict = DecisionPolicy(confirm_pi=0.999)
    assert is_confirmed(_view(pi=0.99, mu=0.9), strict) is False


def test_version_is_decision_v1():
    assert DEFAULT_POLICY.version == "decision_v1"
