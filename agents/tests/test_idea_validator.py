"""Tests for the deterministic idea validator."""

from agents.protocol import ProposedIdea
from agents.idea_generator.idea_validator import validate_idea


def _idea(hypothesis="Momentum works in calm regimes",
          signals=("mom_ret_20", "low_vol_20")):
    return ProposedIdea(
        hypothesis=hypothesis,
        suggested_signals=tuple(signals),
        source_model="fake-idea-llm",
    )


def _validate(idea, existing=None, lessons=None, prior=None):
    return validate_idea(
        idea,
        existing_hypotheses=existing or set(),
        lesson_findings=lessons or set(),
        prior_idea_hypotheses=prior or set(),
        market="us", universe="sp500",
    )


def test_valid_idea_passes():
    assert _validate(_idea()).ok


def test_unknown_signal_rejected():
    r = _validate(_idea(signals=("not_a_signal",)))
    assert not r.ok
    assert any("unknown_signal" in x for x in r.reasons)


def test_empty_hypothesis_rejected():
    r = _validate(_idea(hypothesis="   "))
    assert not r.ok
    assert "empty_hypothesis" in r.reasons


def test_empty_signals_rejected():
    r = _validate(_idea(signals=()))
    assert not r.ok
    assert "empty_signals" in r.reasons


def test_duplicate_of_existing_experiment_rejected():
    r = _validate(_idea(), existing={"momentum works in CALM regimes"})
    assert not r.ok
    assert "duplicate_of_existing_experiment" in r.reasons


def test_duplicate_of_lesson_rejected():
    r = _validate(_idea(), lessons={"Momentum works in calm regimes"})
    assert not r.ok
    assert "duplicate_of_lesson" in r.reasons


def test_duplicate_of_prior_idea_rejected():
    r = _validate(_idea(), prior={"momentum works in calm regimes"})
    assert not r.ok
    assert "duplicate_of_prior_idea" in r.reasons


def test_reasons_are_explicit_and_multiple():
    r = _validate(_idea(hypothesis="", signals=("bogus",)))
    assert not r.ok
    assert "empty_hypothesis" in r.reasons
    assert any("unknown_signal" in x for x in r.reasons)
