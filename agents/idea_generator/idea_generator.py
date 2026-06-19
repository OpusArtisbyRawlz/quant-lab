"""
idea_generator.py — turn an IdeaLLM response into ProposedIdea objects.

Responsibilities:
- Call the injected IdeaLLM (dependency injection; no provider import here).
- Parse the structured JSON. A parse failure NEVER raises out of this module;
  it is returned as a structured ParseOutcome so the caller can log an
  idea_rejected event with stage="parse". No silent failures.
- Attach advisory scores (informational only).

This module does not validate signals, dedup, or touch the DB — that is the
validator's and the queue's job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from agents.protocol import ProposedIdea
from . import scoring


@dataclass
class ParseOutcome:
    """Result of parsing one LLM response into ideas."""
    ideas: list[ProposedIdea] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


def generate_ideas(llm, prompt: str, *, n: int,
                   market: str = "", universe: str = "") -> ParseOutcome:
    """
    Ask the IdeaLLM for ideas and parse them into ProposedIdea objects.

    `market`/`universe` are research context supplied by the caller (batch
    context) and stamped onto every idea so an approved idea is self-contained
    — the LLM does not choose them.

    Returns a ParseOutcome. Malformed top-level JSON or malformed individual
    idea entries are captured in `parse_errors` rather than raised.
    """
    raw = llm.propose(prompt, n=n)
    model = getattr(llm, "model_name", "unknown")

    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        return ParseOutcome(parse_errors=[f"invalid_json: {exc}"])

    if not isinstance(doc, dict) or not isinstance(doc.get("ideas"), list):
        return ParseOutcome(parse_errors=["missing_or_invalid_'ideas'_array"])

    outcome = ParseOutcome()
    for i, entry in enumerate(doc["ideas"]):
        idea, err = _parse_one(entry, model, market, universe)
        if err:
            outcome.parse_errors.append(f"idea[{i}]: {err}")
        else:
            outcome.ideas.append(idea)
    return outcome


def _parse_one(entry, model: str, market: str = "", universe: str = "",
               ) -> tuple[ProposedIdea | None, str | None]:
    if not isinstance(entry, dict):
        return None, "not_an_object"

    hypothesis = entry.get("hypothesis")
    signals = entry.get("suggested_signals")
    if not isinstance(hypothesis, str):
        return None, "hypothesis_missing_or_not_string"
    if not isinstance(signals, list) or not all(isinstance(s, str) for s in signals):
        return None, "suggested_signals_missing_or_not_string_list"

    rationale = entry.get("rationale", "")
    rationale = rationale if isinstance(rationale, str) else ""

    signals_t = tuple(signals)
    # Advisory scores: prefer model-supplied, else compute heuristically.
    supplied = entry.get("scores")
    scores = scoring.normalise_scores(supplied) if isinstance(supplied, dict) else None
    if scores is None:
        scores = scoring.compute_scores(hypothesis, signals_t)

    idea = ProposedIdea(
        hypothesis=hypothesis.strip(),
        suggested_signals=signals_t,
        source_model=model,
        rationale=rationale.strip(),
        scores=scores,
        market=market,
        universe=universe,
    )
    return idea, None
