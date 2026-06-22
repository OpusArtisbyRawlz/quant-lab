"""
CampaignManager — Milestone 10 research-campaign lifecycle agent.

Deterministic. No LLM. The CampaignManager is the *sole writer* of the
``research_campaign`` and ``campaign_state_events`` tables. It owns the campaign
state machine and guarantees that every state change is:

  * legal (validated against the allowed transition graph), and
  * audited (an immutable ``campaign_state_events`` row is appended for every
    accepted transition — mirroring M9's ``signal_lifecycle_events``).

State machine
-------------

    DRAFT ──▶ ACTIVE ──▶ COMPLETED        (goal reached / budget exhausted)
                │  ▲ │
                │  │ └─▶ ARCHIVED          (paused / shelved, may be revisited)
                │  │ └─▶ DISCARDED         (abandoned)
                ▼  │
             STALLED ─┘                    (no progress; can resume to ACTIVE)

  - DRAFT       -> ACTIVE, DISCARDED
  - ACTIVE      -> STALLED, COMPLETED, ARCHIVED, DISCARDED
  - STALLED     -> ACTIVE, COMPLETED, ARCHIVED, DISCARDED
  - COMPLETED   -> (terminal)
  - ARCHIVED    -> ACTIVE          (an archived campaign may be revived)
  - DISCARDED   -> (terminal)

A transition to the *same* state is a no-op (idempotent) and emits no event.

Progress derivation
-------------------
Campaign progress is canonically *derived* by counting campaign-tagged
experiments (``campaign_store.count_campaign_experiments``), never trusted from a
counter alone. ``budget_spent`` on the row is a refreshable cache. This keeps the
campaign layer recoverable: state can be recomputed from the experiments/ideas
that actually ran, so a crash mid-tick cannot silently corrupt progress.

This module performs *no* experiment execution and touches *no* M7 execution
hot path or human approval gate — it only governs campaign metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import campaign_store
from agents.storage.campaign_store import (
    STATE_DRAFT,
    STATE_ACTIVE,
    STATE_STALLED,
    STATE_COMPLETED,
    STATE_ARCHIVED,
    STATE_DISCARDED,
    TERMINAL_STATES,
)

# Allowed transitions: {from_state: {to_state, ...}}.
_TRANSITIONS: dict[str, set[str]] = {
    STATE_DRAFT: {STATE_ACTIVE, STATE_DISCARDED},
    STATE_ACTIVE: {STATE_STALLED, STATE_COMPLETED, STATE_ARCHIVED, STATE_DISCARDED},
    STATE_STALLED: {STATE_ACTIVE, STATE_COMPLETED, STATE_ARCHIVED, STATE_DISCARDED},
    STATE_COMPLETED: set(),
    STATE_ARCHIVED: {STATE_ACTIVE},
    STATE_DISCARDED: set(),
}

# States that stamp completed_at when entered.
_STAMP_COMPLETED_AT = {STATE_COMPLETED, STATE_ARCHIVED, STATE_DISCARDED}


class CampaignError(RuntimeError):
    """Raised on an illegal campaign operation (unknown campaign, bad transition)."""


@dataclass
class TransitionResult:
    campaign_id: str
    from_state: str
    to_state: str
    changed: bool          # False when the transition was a no-op (same state)
    event_id: int | None   # id of the emitted event row, or None for a no-op


def is_legal_transition(from_state: str, to_state: str) -> bool:
    """Return True if from_state -> to_state is an allowed transition.

    A same-state transition is considered legal (handled as an idempotent
    no-op by transition()).
    """
    if from_state == to_state:
        return True
    return to_state in _TRANSITIONS.get(from_state, set())


class CampaignManager:
    """Owns the campaign state machine. Sole writer of campaign tables."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    # -- creation ----------------------------------------------------------

    def create_campaign(
        self,
        campaign_id: str,
        theme: str,
        *,
        goal_spec: Any = None,
        scope: Any = None,
        budget_experiments: int = 0,
        exploration_fraction: float = 0.34,
        stall_patience: int = 3,
        stopping_spec: Any = None,
    ) -> dict[str, Any]:
        """Create a new campaign in DRAFT and record its genesis event.

        Raises CampaignError if a campaign with this id already exists.
        """
        if campaign_store.get_campaign(campaign_id, db_path=self.db_path):
            raise CampaignError(f"campaign already exists: {campaign_id}")
        campaign_store.insert_campaign(
            {
                "campaign_id": campaign_id,
                "theme": theme,
                "goal_spec": goal_spec,
                "scope": scope,
                "state": STATE_DRAFT,
                "budget_experiments": budget_experiments,
                "exploration_fraction": exploration_fraction,
                "stall_patience": stall_patience,
                "stopping_spec": stopping_spec,
            },
            db_path=self.db_path,
        )
        # Genesis event: a creation marker (no prior state).
        campaign_store.append_state_event(
            campaign_id,
            from_state=None,
            to_state=STATE_DRAFT,
            reason_code="created",
            evidence={"theme": theme},
            db_path=self.db_path,
        )
        return campaign_store.get_campaign(campaign_id, db_path=self.db_path)

    # -- transitions -------------------------------------------------------

    def transition(
        self,
        campaign_id: str,
        to_state: str,
        *,
        reason_code: str | None = None,
        evidence: Any = None,
    ) -> TransitionResult:
        """Move a campaign to to_state, validating legality and auditing it.

        Same-state transitions are idempotent no-ops (changed=False, no event).
        Raises CampaignError for an unknown campaign or an illegal transition.
        """
        campaign = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        if campaign is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        from_state = campaign["state"]

        if from_state == to_state:
            return TransitionResult(campaign_id, from_state, to_state, False, None)

        if not is_legal_transition(from_state, to_state):
            raise CampaignError(
                f"illegal transition for {campaign_id}: {from_state} -> {to_state}"
            )

        completed_at = (
            campaign_store._utcnow() if to_state in _STAMP_COMPLETED_AT else None
        )
        campaign_store.update_campaign_state(
            campaign_id,
            to_state,
            completed_at=completed_at,
            db_path=self.db_path,
        )
        event_id = campaign_store.append_state_event(
            campaign_id,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            evidence=evidence,
            db_path=self.db_path,
        )
        return TransitionResult(campaign_id, from_state, to_state, True, event_id)

    # Convenience wrappers ------------------------------------------------

    def activate(self, campaign_id: str, *, reason_code: str = "activated",
                 evidence: Any = None) -> TransitionResult:
        return self.transition(campaign_id, STATE_ACTIVE,
                               reason_code=reason_code, evidence=evidence)

    def mark_stalled(self, campaign_id: str, *, reason_code: str = "no_progress",
                     evidence: Any = None) -> TransitionResult:
        return self.transition(campaign_id, STATE_STALLED,
                               reason_code=reason_code, evidence=evidence)

    def complete(self, campaign_id: str, *, reason_code: str = "goal_reached",
                 evidence: Any = None) -> TransitionResult:
        return self.transition(campaign_id, STATE_COMPLETED,
                               reason_code=reason_code, evidence=evidence)

    def archive(self, campaign_id: str, *, reason_code: str = "shelved",
                evidence: Any = None) -> TransitionResult:
        return self.transition(campaign_id, STATE_ARCHIVED,
                               reason_code=reason_code, evidence=evidence)

    def discard(self, campaign_id: str, *, reason_code: str = "abandoned",
                evidence: Any = None) -> TransitionResult:
        return self.transition(campaign_id, STATE_DISCARDED,
                               reason_code=reason_code, evidence=evidence)

    # -- progress ----------------------------------------------------------

    def refresh_progress(self, campaign_id: str) -> int:
        """Recompute campaign progress from campaign-tagged experiments and
        refresh the cached budget_spent counter. Returns the derived count.

        This is the canonical progress measure; the stored counter is only a
        cache to avoid recomputing on every read.
        """
        campaign = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        if campaign is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        n = campaign_store.count_campaign_experiments(
            campaign_id, db_path=self.db_path
        )
        campaign_store.set_budget_spent(campaign_id, n, db_path=self.db_path)
        return n

    def budget_exhausted(self, campaign_id: str) -> bool:
        """True if a bounded campaign has reached or exceeded its experiment
        budget (derived progress). Unbounded campaigns (budget 0) never exhaust.
        """
        campaign = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        if campaign is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        budget = int(campaign.get("budget_experiments", 0) or 0)
        if budget <= 0:
            return False
        n = campaign_store.count_campaign_experiments(
            campaign_id, db_path=self.db_path
        )
        return n >= budget

    def is_terminal(self, campaign_id: str) -> bool:
        campaign = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        if campaign is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        return campaign["state"] in TERMINAL_STATES
