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
from agents.storage import portfolio_store
from agents.storage import evidence_store
from agents.storage import budget_store
from agents.storage.campaign_store import (
    STATE_DRAFT,
    STATE_ACTIVE,
    STATE_STALLED,
    STATE_COMPLETED,
    STATE_ARCHIVED,
    STATE_DISCARDED,
    TERMINAL_STATES,
)
from agents.storage.portfolio_store import (
    PORTFOLIO_ACTIVE,
    PORTFOLIO_PAUSED,
    PORTFOLIO_ARCHIVED,
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

# Phase 6 (P6-11) — trigger kinds (§3) and repeat modes (§6).
TRIGGER_MANUAL = "manual"
TRIGGER_DEPENDENCY = "dependency"
TRIGGER_SCHEDULE = "schedule"
TRIGGER_EVENT = "event"

REPEAT_ONCE = "once"
REPEAT_INTERVAL = "interval"
REPEAT_UNTIL = "until"

# Phase 6 (P6-14) — EIG aggregation modes (eig_spec.aggregate, §5). mean/sum/max are
# defined; 'promotion_headroom' is named in the design but not specified, so it is
# deferred (an unknown aggregate falls back to the default mean).
EIG_MEAN = "mean"
EIG_SUM = "sum"
EIG_MAX = "max"
DEFAULT_EIG_AGGREGATE = EIG_MEAN

# Phase 6 (P6-9) — portfolio lifecycle. Exactly the three states in the approved
# design (§7); no others are invented. ARCHIVED is terminal (a portfolio is
# dropped/rebuilt from campaign membership, not revived).
_PORTFOLIO_TRANSITIONS: dict[str, set[str]] = {
    PORTFOLIO_ACTIVE: {PORTFOLIO_PAUSED, PORTFOLIO_ARCHIVED},
    PORTFOLIO_PAUSED: {PORTFOLIO_ACTIVE, PORTFOLIO_ARCHIVED},
    PORTFOLIO_ARCHIVED: set(),
}


class CampaignError(RuntimeError):
    """Raised on an illegal campaign operation (unknown campaign, bad transition)."""


class PortfolioError(RuntimeError):
    """Raised on an illegal portfolio operation (unknown portfolio, bad transition)."""


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


def is_legal_portfolio_transition(from_state: str, to_state: str) -> bool:
    """True if a portfolio from_state -> to_state transition is allowed. A
    same-state transition is legal (handled as an idempotent no-op)."""
    if from_state == to_state:
        return True
    return to_state in _PORTFOLIO_TRANSITIONS.get(from_state, set())


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
        campaign_type: str = "strategy_evolution",
        priority: float | None = None,
        trigger_spec: Any = None,
        depends_on: Any = None,
        expected_information_gain: float | None = None,
        eig_spec: Any = None,
        repeat_spec: Any = None,
        portfolio_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new campaign in DRAFT and record its genesis event.

        ``campaign_type`` (Phase 6 P6-2) selects the HypothesisSource — WHAT to
        research; the default preserves pre-Phase-6 strategist behaviour.

        The Phase 6 P6-8 portfolio-planning fields (``priority``, ``trigger_spec``,
        ``depends_on``, ``expected_information_gain``, ``eig_spec``, ``repeat_spec``,
        ``portfolio_id``) are all optional; omitting them ⇒ current behaviour. They
        are stored here and consumed by later PRs (planner, triggers, budget, EIG).
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
            "campaign_type": campaign_type,
            # Phase 6 (P6-8) extended planning fields. Kept in the genesis event so
            # the projection is fully reconstructible from the log.
            "priority": priority,
            "trigger_spec": trigger_spec,
            "depends_on": depends_on,
            "expected_information_gain": expected_information_gain,
            "eig_spec": eig_spec,
            "repeat_spec": repeat_spec,
            "portfolio_id": portfolio_id,
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
                "campaign_type": config.get("campaign_type", "strategy_evolution"),
                # Phase 6 (P6-8) extended fields (absent ⇒ NULL/spec-default).
                "priority": config.get("priority"),
                "trigger_spec": config.get("trigger_spec"),
                "depends_on": config.get("depends_on"),
                "expected_information_gain": config.get("expected_information_gain"),
                "eig_spec": config.get("eig_spec"),
                "repeat_spec": config.get("repeat_spec"),
                "portfolio_id": config.get("portfolio_id"),
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

    def advance(self, campaign_id: str) -> str:
        """Evaluate a campaign's deterministic stop conditions after a tick and
        transition it if met — the CampaignManager owns this decision so the
        Phase-6 FactoryRunner stays a thin driver. Idempotent (a no-op on a
        terminal campaign or one that has not met a condition).

        P6-3 evaluates only **budget exhaustion** (`budget_spent ≥
        budget_experiments`) → COMPLETED, reusing the existing ``complete``
        transition. Stall detection (`stall_patience`) and rich ``stopping_spec``
        goal predicates are later PRs (P6-8). Returns the resulting authoritative
        state.
        """
        state = self.current_state(campaign_id)
        # Only a live, running campaign can be auto-completed on a stop condition
        # (COMPLETED is reachable from ACTIVE/STALLED, not DRAFT).
        if state not in (STATE_ACTIVE, STATE_STALLED):
            return state
        if self.budget_exhausted(campaign_id):
            self.complete(campaign_id, reason_code="budget_reached")
        return self.current_state(campaign_id)

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

    # -- eligibility (Phase 6 P6-11 — the SOLE owner of trigger/repeat eval) --
    #
    # These are PURE reads over stored state. The PortfolioPlanner obtains campaign
    # eligibility from here (never re-deriving it), so trigger/dependency/repeat
    # evaluation lives in exactly one place. Nothing here mutates state or fires a
    # transition — firing (DRAFT→ACTIVE on a trigger, COMPLETED→DRAFT on a repeat)
    # is a separate, clock-bearing concern deferred to a later PR.

    def dependencies_satisfied(self, campaign_id: str) -> bool:
        """True iff every dependency is in its required state (default COMPLETED,
        §4). A dependency on an unknown campaign is unsatisfied (safe exclude).
        Exact-state match — the design defines no state total-order, so no
        'past-state' inference is invented."""
        camp = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        if camp is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        for dep_id, required in campaign_store.normalized_depends_on(camp):
            state = campaign_store.reconstruct_state_from_events(
                dep_id, db_path=self.db_path
            )
            if state is None or state != required:
                return False
        return True

    def trigger_satisfied(self, campaign_id: str) -> bool:
        """Whether the campaign's trigger (§3) is satisfied.

        P6-11 evaluates the two clock-free, fully-specified kinds:
          - ``dependency`` → satisfied iff ``depends_on`` is satisfied;
          - ``manual`` (default) → satisfied (an operator/approval activates it, so
            it counts once ACTIVE; the ACTIVE gate lives in ``is_eligible``).
        ``schedule``/``event`` are deferred (they need the FactoryRunner's logical
        tick clock / a projection-predicate catalog); a campaign of those kinds is
        treated as trigger-satisfied iff already ACTIVE — its activation counts, and
        no auto-firing happens here — so nothing regresses."""
        camp = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        if camp is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        kind = campaign_store.campaign_trigger_spec(camp).get("kind", TRIGGER_MANUAL)
        if kind == TRIGGER_DEPENDENCY:
            return self.dependencies_satisfied(campaign_id)
        return True

    def repeat_eligible(self, campaign_id: str) -> bool:
        """Whether a COMPLETED campaign is allowed another repeat (§6). Pure and
        clock-free:
          - ``once`` (default) → never repeat-eligible;
          - ``interval`` → eligible while under the ``max_repeats`` cap (null =
            unbounded); the cooldown *timing* is deferred (needs the logical clock);
          - ``until`` → deferred (needs the stop predicate) → not eligible here.
        A non-COMPLETED campaign is never repeat-eligible (repeat applies at
        completion). The planner never fires re-entry — this predicate is for a
        later clock-bearing caller and for auditing which campaigns may repeat."""
        state = self.current_state(campaign_id)
        if state != STATE_COMPLETED:
            return False
        camp = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        spec = campaign_store.campaign_repeat_spec(camp)
        mode = spec.get("mode", REPEAT_ONCE)
        if mode == REPEAT_INTERVAL:
            max_repeats = spec.get("max_repeats")
            if max_repeats is None:
                return True
            completions = sum(
                1 for e in campaign_store.list_state_events(
                    campaign_id, db_path=self.db_path)
                if e["to_state"] == STATE_COMPLETED
            )
            return completions <= int(max_repeats)
        return False

    def is_eligible(self, campaign_id: str) -> bool:
        """The runnable predicate the PortfolioPlanner consumes — the single owner of
        campaign eligibility. Runnable iff ACTIVE, not budget-exhausted, dependencies
        satisfied, and trigger satisfied. Pure; no mutation."""
        if self.current_state(campaign_id) != STATE_ACTIVE:
            return False
        if self.budget_exhausted(campaign_id):
            return False
        if not self.dependencies_satisfied(campaign_id):
            return False
        if not self.trigger_satisfied(campaign_id):
            return False
        return True

    # -- EIG aggregation (Phase 6 P6-14 — derive + cache) ------------------
    #
    # Campaign-level EIG is an AGGREGATION of the already-computed M11 per-hypothesis
    # budget_allocation.evoi (§5) — not a new statistic and not a change to the M11
    # math. compute_eig is a pure read; refresh_eig caches it on the campaign row via
    # campaign_store (CampaignManager is the sole research_campaign writer), mirroring
    # refresh_progress. The cache is re-derivable each planning pass, so it is only a
    # convenience for readers (e.g. the PortfolioPlanner's eig_weighted / budget).

    def _campaign_hypothesis_ids(self, campaign_id: str) -> list[str]:
        """Distinct hypothesis_ids attributed to a campaign, via evidence_event
        (which carries both campaign_id and hypothesis_id). Sorted (deterministic)."""
        ids = {
            ev["hypothesis_id"]
            for ev in evidence_store.list_evidence(
                campaign_id=campaign_id, db_path=self.db_path)
            if ev.get("hypothesis_id")
        }
        return sorted(ids)

    def compute_eig(self, campaign_id: str) -> float:
        """Pure campaign-level EIG: aggregate ``budget_allocation.evoi`` over the
        campaign's **live** (non-retired) hypotheses (§5). Retired/absent-budget
        hypotheses are not in the set; an empty set ⇒ 0.0 (a played-out campaign
        decays to 0). ``eig_spec.aggregate`` ∈ {mean (default), sum, max}; an unknown
        or deferred value (e.g. promotion_headroom) falls back to mean. Deterministic."""
        camp = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        if camp is None:
            raise CampaignError(f"unknown campaign: {campaign_id}")
        spec = camp.get("eig_spec")
        aggregate = spec.get("aggregate", DEFAULT_EIG_AGGREGATE) \
            if isinstance(spec, dict) else DEFAULT_EIG_AGGREGATE

        evois: list[float] = []
        for hid in self._campaign_hypothesis_ids(campaign_id):
            row = budget_store.get_budget(hid, db_path=self.db_path)
            if row is None or row.get("retired"):
                continue                       # only live, allocated hypotheses
            evois.append(float(row.get("evoi") or 0.0))
        if not evois:
            return 0.0
        if aggregate == EIG_SUM:
            return float(sum(evois))
        if aggregate == EIG_MAX:
            return float(max(evois))
        return float(sum(evois) / len(evois))   # mean (default / unknown)

    def refresh_eig(self, campaign_id: str) -> float:
        """Recompute a campaign's EIG and cache it on the row. Returns the value.
        The write goes through campaign_store (CM is the sole research_campaign
        writer); no historical evidence or M11 projection is mutated."""
        eig = self.compute_eig(campaign_id)
        campaign_store.set_expected_information_gain(
            campaign_id, eig, db_path=self.db_path)
        return eig

    def refresh_all_eig(self) -> dict[str, float]:
        """Refresh cached EIG for every campaign (one planning-pass sweep). Returns
        {campaign_id: eig}, ordered by campaign_id (deterministic)."""
        out: dict[str, float] = {}
        for camp in campaign_store.list_campaigns(db_path=self.db_path):
            out[camp["campaign_id"]] = self.refresh_eig(camp["campaign_id"])
        return dict(sorted(out.items()))

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

    # ====================================================================== #
    # Phase 6 (P6-9) — Research Portfolio lifecycle / state machine.
    #
    # The approved design assigns the portfolio state machine to this existing
    # coordinator (no new agent). The CampaignManager is the sole writer of the
    # research_portfolio + portfolio_state_events tables, with exactly the
    # event-sourcing discipline used for campaigns: every accepted transition
    # appends an immutable event (the source of truth) FIRST, then refreshes the
    # rebuildable projection row. A portfolio executes nothing and holds no
    # research logic — it is a planning container over member campaigns.
    # ====================================================================== #

    # -- portfolio creation ------------------------------------------------

    def create_portfolio(
        self,
        portfolio_id: str,
        name: str,
        *,
        objective: Any = None,
        scheduling_policy: str = portfolio_store.DEFAULT_SCHEDULING_POLICY,
        concurrency_limit: int = 0,
        budget_spec: Any = None,
        stopping_spec: Any = None,
    ) -> dict[str, Any]:
        """Create a new portfolio in ACTIVE and record its genesis event.

        ``scheduling_policy``/``budget_spec`` are stored now and consumed by later
        PRs (P6-10 planner, P6-12 budget) — P6-9 does not act on them. Raises
        PortfolioError if a portfolio with this id already exists.
        """
        if portfolio_store.reconstruct_portfolio_state_from_events(
            portfolio_id, db_path=self.db_path
        ) is not None:
            raise PortfolioError(f"portfolio already exists: {portfolio_id}")

        config = {
            "name": name,
            "objective": objective,
            "scheduling_policy": scheduling_policy,
            "concurrency_limit": int(concurrency_limit),
            "budget_spec": budget_spec,
            "stopping_spec": stopping_spec,
        }
        # The genesis event is the source of truth for the config + initial state;
        # written FIRST so the portfolio exists in the log even if the projection
        # insert is interrupted (rebuild reconstructs the row from this event).
        portfolio_store.append_portfolio_event(
            portfolio_id,
            from_state=None,
            to_state=PORTFOLIO_ACTIVE,
            reason_code="created",
            evidence={"config": config},
            db_path=self.db_path,
        )
        self._write_portfolio_projection(portfolio_id, config, PORTFOLIO_ACTIVE)
        return portfolio_store.get_portfolio(portfolio_id, db_path=self.db_path)

    def _write_portfolio_projection(
        self, portfolio_id: str, config: dict[str, Any], state: str
    ) -> None:
        """(Re)materialise the research_portfolio projection row from config +
        state. Idempotent: replaces any existing row, so it is safe to replay."""
        portfolio_store.delete_portfolio_row(portfolio_id, db_path=self.db_path)
        portfolio_store.insert_portfolio(
            {
                "portfolio_id": portfolio_id,
                "name": config.get("name", ""),
                "objective": config.get("objective"),
                "scheduling_policy": config.get(
                    "scheduling_policy", portfolio_store.DEFAULT_SCHEDULING_POLICY
                ),
                "concurrency_limit": config.get("concurrency_limit", 0),
                "budget_spec": config.get("budget_spec"),
                "state": state,
                "stopping_spec": config.get("stopping_spec"),
            },
            db_path=self.db_path,
        )

    # -- portfolio transitions --------------------------------------------

    def transition_portfolio(
        self,
        portfolio_id: str,
        to_state: str,
        *,
        reason_code: str | None = None,
        evidence: Any = None,
    ) -> TransitionResult:
        """Move a portfolio to ``to_state``, validating legality and auditing it.

        Same-state transitions are idempotent no-ops (changed=False, no event).
        Raises PortfolioError for an unknown portfolio or an illegal transition.
        The authoritative current state is the event log, never the cached column.
        """
        from_state = portfolio_store.reconstruct_portfolio_state_from_events(
            portfolio_id, db_path=self.db_path
        )
        if from_state is None:
            raise PortfolioError(f"unknown portfolio: {portfolio_id}")

        if from_state == to_state:
            return TransitionResult(portfolio_id, from_state, to_state, False, None)

        if not is_legal_portfolio_transition(from_state, to_state):
            raise PortfolioError(
                f"illegal transition for {portfolio_id}: {from_state} -> {to_state}"
            )

        # Append the event FIRST (the log leads); then refresh the projection.
        event_id = portfolio_store.append_portfolio_event(
            portfolio_id,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            evidence=evidence,
            db_path=self.db_path,
        )
        portfolio_store.update_portfolio_state(
            portfolio_id, to_state, db_path=self.db_path
        )
        return TransitionResult(portfolio_id, from_state, to_state, True, event_id)

    def pause_portfolio(self, portfolio_id: str, *, reason_code: str = "paused",
                        evidence: Any = None) -> TransitionResult:
        return self.transition_portfolio(portfolio_id, PORTFOLIO_PAUSED,
                                         reason_code=reason_code, evidence=evidence)

    def resume_portfolio(self, portfolio_id: str, *, reason_code: str = "resumed",
                         evidence: Any = None) -> TransitionResult:
        return self.transition_portfolio(portfolio_id, PORTFOLIO_ACTIVE,
                                         reason_code=reason_code, evidence=evidence)

    def archive_portfolio(self, portfolio_id: str, *, reason_code: str = "archived",
                          evidence: Any = None) -> TransitionResult:
        return self.transition_portfolio(portfolio_id, PORTFOLIO_ARCHIVED,
                                         reason_code=reason_code, evidence=evidence)

    # -- portfolio reads / reconstruction ---------------------------------

    def portfolio_state(self, portfolio_id: str) -> str:
        """Authoritative portfolio state, derived from the event log."""
        state = portfolio_store.reconstruct_portfolio_state_from_events(
            portfolio_id, db_path=self.db_path
        )
        if state is None:
            raise PortfolioError(f"unknown portfolio: {portfolio_id}")
        return state

    def rebuild_portfolio_from_events(self, portfolio_id: str) -> dict[str, Any]:
        """Rebuild the research_portfolio projection row entirely from the event
        log (config from the genesis event, state from the latest event). Works
        even if the row was deleted. Raises PortfolioError if there are no events."""
        genesis = portfolio_store.portfolio_genesis_event(
            portfolio_id, db_path=self.db_path
        )
        state = portfolio_store.reconstruct_portfolio_state_from_events(
            portfolio_id, db_path=self.db_path
        )
        if genesis is None or state is None:
            raise PortfolioError(f"no events to rebuild portfolio: {portfolio_id}")
        config = (genesis.get("evidence") or {}).get("config", {})
        self._write_portfolio_projection(portfolio_id, config, state)
        return portfolio_store.get_portfolio(portfolio_id, db_path=self.db_path)

    def reconcile_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        """Repair the projection row so it agrees with the event log — the fix for
        a transition interrupted between event-append and cache-update (or a
        missing row). The event log is ground truth; the row is rewritten to match."""
        authoritative = portfolio_store.reconstruct_portfolio_state_from_events(
            portfolio_id, db_path=self.db_path
        )
        if authoritative is None:
            raise PortfolioError(f"unknown portfolio: {portfolio_id}")
        row = portfolio_store.get_portfolio(portfolio_id, db_path=self.db_path)
        cached = row["state"] if row else None
        repaired = (row is None) or (cached != authoritative)
        if repaired:
            self.rebuild_portfolio_from_events(portfolio_id)
        return {
            "portfolio_id": portfolio_id,
            "authoritative_state": authoritative,
            "cached_state": cached,
            "row_existed": row is not None,
            "repaired": repaired,
        }

    def reconcile_all_portfolios(self) -> list[dict[str, Any]]:
        """Startup reconciliation: reconcile every portfolio present in the event
        log, rebuilding any missing rows and repairing any stale caches."""
        return [
            self.reconcile_portfolio(pid)
            for pid in portfolio_store.distinct_portfolio_ids_in_events(
                db_path=self.db_path
            )
        ]

    def campaigns_in_portfolio(self, portfolio_id: str) -> list[str]:
        """Member campaign ids, via the existing research_campaign.portfolio_id
        linkage (no new membership structure)."""
        return portfolio_store.campaigns_in_portfolio(
            portfolio_id, db_path=self.db_path
        )
