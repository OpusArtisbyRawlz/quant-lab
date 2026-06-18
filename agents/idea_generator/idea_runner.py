"""
idea_runner.py — orchestrates one idea-generation batch.

Flow:  IdeaLLM -> parse -> validate -> persist (pending | rejected) -> log.

This is the top of the M6 pipeline and it STOPS at the approval queue. It does
not call the Runner, Critic, or Ledger, does not write to `experiments`, does
not retry, schedule, loop, or touch the signal library. Human approval happens
out-of-band via approval_queue.approve_idea / reject_idea.

All proposed and rejected ideas are logged to agent_conversations with message
types idea_proposed / idea_rejected. Human decisions log idea_approved /
idea_rejected from the approval queue helpers below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agents.protocol import ProposedIdea
from agents.storage.db import DB_PATH
from agents.storage.conversation_store import log_message
from agents.storage.lessons_store import lessons_for_idea_generator
from agents.storage.ledger_store import list_experiments
from agents.experiment_runner.spec_validator import KNOWN_SIGNALS

from . import approval_queue, scoring
from .prompt import build_prompt
from .idea_generator import generate_ideas
from .idea_validator import validate_idea

_SENDER = "idea_generator"


@dataclass
class BatchOutcome:
    cycle_id: str
    pending: list[str] = field(default_factory=list)   # idea_ids enqueued pending
    rejected: list[str] = field(default_factory=list)  # idea_ids recorded rejected
    parse_errors: list[str] = field(default_factory=list)


def run_idea_batch(
    llm,
    *,
    cycle_id: str,
    n: int = 3,
    market: str = "",
    universe: str = "",
    db_path: Path = DB_PATH,
) -> BatchOutcome:
    """
    Generate, validate, and queue a batch of ideas. Pure proposal + gate; no
    execution. `llm` is any injected IdeaLLM (FakeIdeaLLM in tests).
    """
    existing = {e.get("hypothesis", "") for e in list_experiments(db_path=db_path)}
    existing.discard("")
    lessons = lessons_for_idea_generator(db_path=db_path)
    lesson_findings = {l.get("finding", "") for l in lessons}
    lesson_findings.discard("")

    prompt = build_prompt(KNOWN_SIGNALS, lessons, existing, n=n)
    parsed = generate_ideas(llm, prompt, n=n)

    outcome = BatchOutcome(cycle_id=cycle_id, parse_errors=list(parsed.parse_errors))

    # Parse failures: log + record as rejected with stage=parse. No silent loss.
    for err in parsed.parse_errors:
        placeholder = ProposedIdea(
            hypothesis="",
            suggested_signals=(),
            source_model=getattr(llm, "model_name", "unknown"),
            scores=scoring.compute_scores("", ()),
        )
        idea_id = approval_queue.make_idea_id(placeholder, db_path=db_path)
        approval_queue.record_rejected(
            placeholder, idea_id, [f"parse_error: {err}"],
            cycle_id=cycle_id, db_path=db_path,
        )
        _log_rejected(cycle_id, idea_id, placeholder, [f"parse_error: {err}"],
                      stage="parse", db_path=db_path)
        outcome.rejected.append(idea_id)

    # Track within-batch hypotheses so two identical proposals in one batch
    # don't both slip through as "not a prior idea".
    prior_idea_hypotheses = {
        i.get("hypothesis", "") for i in approval_queue.list_by_status("pending", db_path)
    } | {
        i.get("hypothesis", "") for i in approval_queue.list_by_status("approved", db_path)
    }
    prior_idea_hypotheses.discard("")

    for idea in parsed.ideas:
        result = validate_idea(
            idea,
            existing_hypotheses=existing,
            lesson_findings=lesson_findings,
            prior_idea_hypotheses=prior_idea_hypotheses,
            market=market,
            universe=universe,
        )
        idea_id = approval_queue.make_idea_id(idea, db_path=db_path)

        if result.ok:
            approval_queue.enqueue(idea, idea_id, cycle_id=cycle_id, db_path=db_path)
            _log_proposed(cycle_id, idea_id, idea, db_path=db_path)
            outcome.pending.append(idea_id)
            prior_idea_hypotheses.add(idea.hypothesis)
        else:
            approval_queue.record_rejected(
                idea, idea_id, result.reasons, cycle_id=cycle_id, db_path=db_path
            )
            _log_rejected(cycle_id, idea_id, idea, result.reasons,
                          stage="validation", db_path=db_path)
            outcome.rejected.append(idea_id)

    return outcome


# ---------------------------------------------------------------------------
# Human approval surface (minimal) — wraps the queue and logs the decision.
# ---------------------------------------------------------------------------

def approve(idea_id: str, note: str = "", db_path: Path = DB_PATH) -> bool:
    """Approve a pending idea and log idea_approved. Returns True if updated."""
    updated = approval_queue.approve_idea(idea_id, note=note, db_path=db_path)
    if updated:
        rec = approval_queue.get_idea(idea_id, db_path=db_path) or {}
        log_message(
            rec.get("cycle_id") or "manual", _SENDER, "human", "idea_approved",
            {"idea_id": idea_id, "decision": "approved", "reviewer_note": note,
             "reviewed_at": rec.get("reviewed_at")},
            db_path=db_path,
        )
    return updated


def reject(idea_id: str, note: str = "", db_path: Path = DB_PATH) -> bool:
    """Reject a pending idea and log idea_rejected. Returns True if updated."""
    updated = approval_queue.reject_idea(idea_id, note=note, db_path=db_path)
    if updated:
        rec = approval_queue.get_idea(idea_id, db_path=db_path) or {}
        log_message(
            rec.get("cycle_id") or "manual", _SENDER, "human", "idea_rejected",
            {"idea_id": idea_id, "decision": "rejected", "reviewer_note": note,
             "reviewed_at": rec.get("reviewed_at"), "stage": "human_review"},
            db_path=db_path,
        )
    return updated


# ---------------------------------------------------------------------------
# Logging payloads
# ---------------------------------------------------------------------------

def _log_proposed(cycle_id: str, idea_id: str, idea: ProposedIdea,
                  *, db_path: Path) -> None:
    log_message(
        cycle_id, _SENDER, "system", "idea_proposed",
        {
            "idea_id": idea_id,
            "hypothesis": idea.hypothesis,
            "suggested_signals": list(idea.suggested_signals),
            "rationale": idea.rationale,
            "source_model": idea.source_model,
            "scores": idea.scores or {},
            "validation": {"ok": True, "reasons": []},
        },
        db_path=db_path,
    )


def _log_rejected(cycle_id: str, idea_id: str, idea: ProposedIdea,
                  reasons: list[str], *, stage: str, db_path: Path) -> None:
    log_message(
        cycle_id, _SENDER, "system", "idea_rejected",
        {
            "idea_id": idea_id,
            "hypothesis": idea.hypothesis,
            "suggested_signals": list(idea.suggested_signals),
            "source_model": idea.source_model,
            "stage": stage,
            "validation": {"ok": False, "reasons": reasons},
        },
        db_path=db_path,
    )
