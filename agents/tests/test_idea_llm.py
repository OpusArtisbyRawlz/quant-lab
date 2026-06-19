"""Tests for the IdeaLLM seam and JSON parsing into ProposedIdea objects."""

import json

from agents.idea_generator.llm_client import FakeIdeaLLM
from agents.idea_generator.idea_generator import generate_ideas
from agents.protocol import ProposedIdea


def test_fake_llm_is_keyless_and_deterministic():
    llm = FakeIdeaLLM()
    a = llm.propose("p", n=2)
    b = FakeIdeaLLM().propose("other", n=2)
    assert a == b  # deterministic, prompt-independent default


def test_default_parses_into_proposed_idea_with_provenance():
    llm = FakeIdeaLLM()
    out = generate_ideas(llm, "prompt", n=3)
    assert out.parse_errors == []
    assert len(out.ideas) == 1
    idea = out.ideas[0]
    assert isinstance(idea, ProposedIdea)
    assert idea.source_model == "fake-idea-llm"
    assert idea.suggested_signals == ("mom_ret_20", "low_vol_20")
    assert set(idea.scores) == {
        "novelty_score", "feasibility_score", "signal_diversity_score"
    }


def test_malformed_json_is_rejected_not_raised():
    llm = FakeIdeaLLM(responses=["this is not json"])
    out = generate_ideas(llm, "prompt", n=1)
    assert out.ideas == []
    assert any("invalid_json" in e for e in out.parse_errors)


def test_missing_ideas_array_is_rejected():
    llm = FakeIdeaLLM(responses=[json.dumps({"foo": 1})])
    out = generate_ideas(llm, "prompt", n=1)
    assert out.ideas == []
    assert any("ideas" in e for e in out.parse_errors)


def test_partial_batch_keeps_good_rejects_bad():
    payload = json.dumps({"ideas": [
        {"hypothesis": "Good one", "suggested_signals": ["mom_ret_5"]},
        {"hypothesis": "Bad", "suggested_signals": "not-a-list"},
        {"suggested_signals": ["mr_ret_5"]},  # missing hypothesis
    ]})
    out = generate_ideas(FakeIdeaLLM(responses=[payload]), "p", n=3)
    assert len(out.ideas) == 1
    assert out.ideas[0].hypothesis == "Good one"
    assert len(out.parse_errors) == 2


def test_model_supplied_scores_are_normalised():
    payload = json.dumps({"ideas": [{
        "hypothesis": "h", "suggested_signals": ["mom_ret_5"],
        "scores": {"novelty_score": 2.0, "feasibility_score": -1, "signal_diversity_score": 0.5},
    }]})
    out = generate_ideas(FakeIdeaLLM(responses=[payload]), "p", n=1)
    s = out.ideas[0].scores
    assert s["novelty_score"] == 1.0      # clamped
    assert s["feasibility_score"] == 0.0  # clamped
    assert s["signal_diversity_score"] == 0.5
