"""
HypothesisSource registry — Phase 6 P6-2 (interface) + P6-5 (self-registration).

A campaign's ``campaign_type`` selects a **HypothesisSource** that proposes WHAT
research to perform for a tick; the existing agents (Designer, executor, M11) decide
HOW. The registry is a plain, data-driven mapping from ``campaign_type`` to a source
factory.

**Self-registration (P6-5).** A source module registers itself with the
``@register("<campaign_type>")`` decorator; it is never wired into the loop,
scheduler, or runner. The generate phase resolves ``registry[campaign_type]`` and
calls ``source.propose(campaign_id)`` — it is entirely **agnostic** to which source
answers or where the hypotheses originate. Adding a research source is therefore a
new *source module* + one decorator, with **no orchestration change**. The built-in
source modules are imported at the bottom of this file so importing the package
triggers their registration.

Invariants:
- **Generic interface.** Every source implements the same one-method protocol
  (`propose`) and returns uniform `Proposal` records; the loop treats them
  identically.
- **Deterministic.** A source proposes a pure function of stored state (campaign
  scope, already-linked ideas). Identical state ⇒ identical proposals ⇒ the loop
  stays replayable. Sources enumerate candidates in a total (sorted) order and never
  re-propose work already linked to the campaign.
- **No new intelligence / no bypass.** A source is a thin adapter over existing
  capability. Everything it enqueues is a ``pending`` idea, so the human approval
  gate is untouched; downstream (Designer → executor → M11) is shared and unchanged.
- **Append-only / no mutation.** Sources only *append* new pending ideas (new
  idea_ids); they never mutate prior experiments or ideas (see the replay source).

This module holds no research intelligence and is not an agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from agents.protocol import ProposedIdea, normalize_bar_type
from agents.storage.db import DB_PATH, get_connection
from agents.storage import campaign_store
from agents.idea_generator import approval_queue

# The default campaign type — the pre-Phase-6 strategist behaviour.
CAMPAIGN_TYPE_STRATEGY_EVOLUTION = "strategy_evolution"
DEFAULT_CAMPAIGN_TYPE = CAMPAIGN_TYPE_STRATEGY_EVOLUTION

# Near-term campaign types wired by their own source modules (P6-5).
CAMPAIGN_TYPE_BAR_TYPE_COMPARISON = "bar_type_comparison"
CAMPAIGN_TYPE_OVERLAY_COMBINATION = "overlay_combination"
CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY = "counterfactual_replay"


# --------------------------------------------------------------------------- #
# The generic interface
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Proposal:
    """One proposed unit of research — a uniform record every source returns.

    The loop consumes only ``idea_id`` (the ``pending`` idea a source enqueued);
    ``origin`` records which source produced it, for provenance/observability.
    """
    idea_id: str
    origin: str = ""


@runtime_checkable
class HypothesisSource(Protocol):
    """Proposes new hypotheses/ideas for a campaign tick (WHAT to research).

    The single method the whole factory relies on. Implementations must be
    deterministic in stored state.
    """

    def propose(self, campaign_id: str) -> list[Any]:
        ...


@dataclass(frozen=True)
class SourceContext:
    """Everything a source factory needs to build a source, without reaching into
    orchestration. ``strategist`` is provided for the default source; new sources
    typically need only ``db_path``."""
    db_path: Path = DB_PATH
    strategist: Any = None


# A factory turns a context into a bound source instance.
SourceFactory = Callable[[SourceContext], HypothesisSource]

# The self-registration table: campaign_type -> factory. Populated by @register.
_REGISTRY: dict[str, SourceFactory] = {}


def register(campaign_type: str) -> Callable[[SourceFactory], SourceFactory]:
    """Decorator: a source registers itself for a ``campaign_type``.

    This is the ONLY coupling point. A new source module calls ``@register(...)``
    and is picked up automatically — the loop/scheduler/runner are never edited.
    """
    def _decorate(factory: SourceFactory) -> SourceFactory:
        _REGISTRY[campaign_type] = factory
        return factory
    return _decorate


def registered_types() -> list[str]:
    """All registered campaign types, sorted (deterministic)."""
    return sorted(_REGISTRY)


def build_registry(context: SourceContext) -> dict[str, HypothesisSource]:
    """Instantiate every registered source for a context. Deterministic: the same
    registrations + context always yield the same bound sources."""
    return {ctype: factory(context) for ctype, factory in _REGISTRY.items()}


def default_registry(
    strategist: Any, *, db_path: Path = DB_PATH
) -> dict[str, HypothesisSource]:
    """Back-compat convenience (P6-2 signature): build the full registry from the
    self-registered sources, threading the strategist + db_path via a context."""
    return build_registry(SourceContext(db_path=db_path, strategist=strategist))


# --------------------------------------------------------------------------- #
# Shared, thin adapter helpers (reuse the existing enqueue path — no new schema)
# --------------------------------------------------------------------------- #

def enqueue_proposal(
    context: SourceContext,
    campaign_id: str,
    *,
    hypothesis: str,
    signals: list[str],
    market: str,
    universe: str,
    bar_type: str,
    rationale: str,
    origin: str,
) -> Proposal:
    """Enqueue one ``pending`` idea via the SAME path the strategist uses
    (``approval_queue`` + campaign attribution) and return a uniform ``Proposal``.

    No new persistence: reuses ``make_idea_id`` / ``enqueue`` /
    ``link_idea_to_campaign``. The idea is ``pending`` — the human gate is intact.
    """
    idea = ProposedIdea(
        hypothesis=hypothesis,
        suggested_signals=tuple(signals),
        source_model=origin,
        rationale=rationale,
        market=market or "unknown",
        universe=universe or "unknown",
        bar_type=normalize_bar_type(bar_type),
    )
    idea_id = approval_queue.make_idea_id(idea, db_path=context.db_path)
    approval_queue.enqueue(idea, idea_id, db_path=context.db_path)
    campaign_store.link_idea_to_campaign(idea_id, campaign_id, db_path=context.db_path)
    return Proposal(idea_id=idea_id, origin=origin)


def existing_specs(context: SourceContext, campaign_id: str) -> set[tuple[str, str]]:
    """The ``(bar_type, hypothesis)`` pairs already proposed for a campaign.

    Sources consult this to avoid re-proposing the same candidate on later ticks —
    the deterministic bound that makes an enumerating source converge (it proposes
    only the still-missing candidates) instead of re-enqueuing every tick."""
    with get_connection(context.db_path) as conn:
        rows = conn.execute(
            "SELECT bar_type, hypothesis FROM pending_ideas WHERE campaign_id=?",
            (campaign_id,),
        ).fetchall()
    return {(r["bar_type"], r["hypothesis"]) for r in rows}


def campaign_scope(context: SourceContext, campaign_id: str) -> dict[str, Any]:
    """The campaign's ``scope`` dict (already JSON-decoded), or ``{}``."""
    camp = campaign_store.get_campaign(campaign_id, db_path=context.db_path) or {}
    return camp.get("scope") or {}


# --------------------------------------------------------------------------- #
# The default source (strategy_evolution) — registers itself
# --------------------------------------------------------------------------- #

class StrategistSource:
    """Default source: the ResearchStrategist frontier expansion.

    Wraps the loop's existing strategist so ``strategy_evolution`` is byte-identical
    to the pre-Phase-6 generate phase — a pass-through, adding no new behaviour.
    """

    def __init__(self, strategist: Any) -> None:
        self._strategist = strategist

    def propose(self, campaign_id: str) -> list[Any]:
        return self._strategist.run_tick(campaign_id)


@register(CAMPAIGN_TYPE_STRATEGY_EVOLUTION)
def _make_strategist_source(context: SourceContext) -> HypothesisSource:
    return StrategistSource(context.strategist)


# --------------------------------------------------------------------------- #
# Built-in near-term sources self-register on import (P6-5). Importing the package
# is enough — the loop never names these modules.
# --------------------------------------------------------------------------- #

from agents.research_loop.sources import bar_type as _bar_type  # noqa: E402,F401
from agents.research_loop.sources import overlay as _overlay    # noqa: E402,F401
from agents.research_loop.sources import replay as _replay      # noqa: E402,F401
