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
        if campaign_store.reconstruct_state_from_events(
            campaign_id, db_path=self.db_path
        ) is not None:
            raise CampaignError(f"campaign already exists: {campaign_id}")

        config = {
            "theme": theme,
            "goal_spec": goal_spec,
            "scope": scope,
            "budget_experiments": int(budget_experiments),
            "exploration_fraction": float(exploration_fraction),
            "stall_patience": int(stall_patience),
            "stopping_spec": stopping_spec,
        }
        # The genesis event is the source of truth for the campaign's config and
        # initial state. It is written FIRST so the campaign exists in the log
        # even if the projection insert below is interrupted (reconcile rebuilds
        # the row from this event). Its evidence carries the full config so the
        # research_campaign row is fully reconstructible from the log alone.
        campaign_store.append_state_event(
            campaign_id,
            from_state=None,
            to_state=STATE_DRAFT,
            reason_code="created",
            evidence={"config": config},
            db_path=self.db_path,
        )
        self._write_projection(campaign_id, config, STATE_DRAFT, completed_at=None)
        return campaign_store.get_campaign(campaign_id, db_path=self.db_path)

    def _write_projection(
        self,
        campaign_id: str,
        config: dict[str, Any],
        state: str,
        *,
        completed_at: str | None,
    ) -> None:
        """(Re)materialise the research_campaign projection row from config +
        derived state. Idempotent: replaces any existing row."""
        campaign_store.delete_campaign_row(campaign_id, db_path=self.db_path)
        campaign_store.insert_campaign(
            {
                "campaign_id": campaign_id,
                "theme": config.get("theme", ""),
                "goal_spec": config.get("goal_spec"),
                "scope": config.get("scope"),
                "state": state,
                "budget_experiments": config.get("budget_experiments", 0),
                "exploration_fraction": config.get("exploration_fraction", 0.34),
                "stall_patience": config.get("stall_patience", 3),
                "stopping_spec": config.get("stopping_spec"),
            },
            db_path=self.db_path,
        )
        n = campaign_store.count_campaign_experiments(
            campaign_id, db_path=self.db_path
        )
        if n:
            campaign_store.set_budget_spent(campaign_id, n, db_path=self.db_path)
        if completed_at is not None:
            campaign_store.update_campaign_state(
                campaign_id, state, completed_at=completed_at, db_path=self.db_path
            )

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
        # The authoritative current state is the event log, never the projection
        # row's cached state column.
        from_state = campaign_store.reconstruct_state_from_events(
            campaign_id, db_path=self.db_path
        )
        if from_state is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")

        if from_state == to_state:
            return TransitionResult(campaign_id, from_state, to_state, False, None)

        if not is_legal_transition(from_state, to_state):
            raise CampaignError(
                f"illegal transition for {campaign_id}: {from_state} -> {to_state}"
            )

        # Append the event FIRST (the log leads); then refresh the projection
        # cache. If interrupted between the two, reconcile() re-derives the
        # cache from the log.
        event_id = campaign_store.append_state_event(
            campaign_id,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            evidence=evidence,
            db_path=self.db_path,
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
        state = campaign_store.reconstruct_state_from_events(
            campaign_id, db_path=self.db_path
        )
        if state is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        return state in TERMINAL_STATES

    def current_state(self, campaign_id: str) -> str:
        """Authoritative campaign state, derived from the event log."""
        state = campaign_store.reconstruct_state_from_events(
            campaign_id, db_path=self.db_path
        )
        if state is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        return state

    # -- reconciliation / rebuild -----------------------------------------

    def rebuild_from_events(self, campaign_id: str) -> dict[str, Any]:
        """Rebuild the research_campaign projection row entirely from the event
        log (config from the genesis event, state from the latest event) plus
        the derived experiment count. Works even if the row was deleted. Raises
        CampaignError if the campaign has no events."""
        genesis = campaign_store.genesis_event(campaign_id, db_path=self.db_path)
        state = campaign_store.reconstruct_state_from_events(
            campaign_id, db_path=self.db_path
        )
        if genesis is None or state is None:
            raise CampaignError(f"no events to rebuild campaign: {campaign_id}")
        config = (genesis.get("evidence") or {}).get("config", {})
        completed_at = (
            campaign_store._utcnow() if state in _STAMP_COMPLETED_AT else None
        )
        self._write_projection(campaign_id, config, state, completed_at=completed_at)
        return campaign_store.get_campaign(campaign_id, db_path=self.db_path)

    def reconcile(self, campaign_id: str) -> dict[str, Any]:
        """Repair the projection row so it agrees with the event log — the fix
        for a transition interrupted between event-append and cache-update (or a
        missing/deleted row). Returns a report describing what was repaired.

        The event log is treated as ground truth; the row is rewritten to match.
        """
        authoritative = campaign_store.reconstruct_state_from_events(
            campaign_id, db_path=self.db_path
        )
        if authoritative is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        row = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        cached = row["state"] if row else None
        repaired = (row is None) or (cached != authoritative)
        if repaired:
            self.rebuild_from_events(campaign_id)
        else:
            # State agrees; still refresh the derived progress cache.
            self.refresh_progress(campaign_id)
        return {
            "campaign_id": campaign_id,
            "authoritative_state": authoritative,
            "cached_state": cached,
            "row_existed": row is not None,
            "repaired": repaired,
        }

    def reconcile_all(self) -> list[dict[str, Any]]:
        """Startup reconciliation: reconcile every campaign present in the event
        log, rebuilding any missing rows and repairing any stale caches."""
        return [
            self.reconcile(cid)
            for cid in campaign_store.distinct_campaign_ids_in_events(
                db_path=self.db_path
            )
        ]
