"""
strategist.py — Milestone 10 PR-4 ResearchStrategist.

Deterministic. No LLM. The ResearchStrategist sits *above* the unchanged M7
execution core and M9 learning core. Each tick it:

  1. reads the campaign's authoritative state + budget (CampaignManager),
  2. reads M9 context evidence (signal_context_performance via context_store),
  3. reads the campaign's hypothesis frontier (HypothesisTreeManager),
  4. derives a bounded set of next moves as :class:`Proposal` objects, and
  5. (on ``apply``) writes the chosen children into the hypothesis tree and
     enqueues them as ``pending`` ideas in the existing human approval queue,
     tagged to the campaign.

It NEVER executes, schedules, approves, or evaluates anything. Every proposal
becomes a ``pending`` idea that still requires the human approval gate before
the M7 executor will run it.

Evolution operators
-------------------
The six fixed operators live on the hypothesis tree (PR-2). The strategist's
``propose`` auto-triggers the four with clean M9 evidence signatures
(``vary_bar``, ``cross_market``, ``combine``, ``negate``); ``refine`` and
``add_filter`` are fully supported by ``apply`` and may be proposed explicitly
(their auto-triggers need robustness/regime evidence that is intentionally out
of PR-4's worked-campaign scope). Every proposal carries ``bar_type`` as a
typed field — never hidden in free text — so the Hypothesis → Idea → Spec path
is bar-aware end to end.

Loop / explosion safeguards (see the module-level constants and ``propose``):
  * campaign must be ACTIVE and not budget-exhausted;
  * ``max_depth`` bounds tree depth;
  * frontier dedup: an (operator, target-dimension) move is proposed once;
  * ``negate`` children are terminal (never re-expanded);
  * one move per signal/market/universe lineage per tick (no fan-out);
  * ``max_proposals_per_tick`` caps a single tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.protocol import (
    ProposedIdea,
    SUPPORTED_BAR_TYPES,
    normalize_bar_type,
)
from agents.storage.db import DB_PATH
from agents.storage import campaign_store, hypothesis_store, context_store
from agents.campaign_manager import CampaignManager
from agents.campaign_manager.manager import STATE_ACTIVE
from agents.hypothesis_manager import (
    HypothesisTreeManager,
    OP_REFINE,
    OP_VARY_BAR,
    OP_CROSS_MARKET,
    OP_ADD_FILTER,
    OP_COMBINE,
    OP_NEGATE,
    VALID_OPERATORS,
    SINGLE_PARENT_OPERATORS,
)
from agents.idea_generator import approval_queue


class StrategistError(RuntimeError):
    """Raised on an invalid strategist operation."""


@dataclass(frozen=True)
class StrategistConfig:
    """Tunable thresholds. Mirrors LibrarianConfig where it overlaps so the
    strategist reads the *same* evidence bar the M9 librarian writes against."""
    min_n: int = 2                      # min experiments in a cell to count as evidence
    contribution_threshold: float = 0.0  # net-Sharpe bar a cell must clear to "pass"
    max_depth: int = 6                  # hard cap on hypothesis-tree depth
    max_proposals_per_tick: int = 8     # cap on a single propose() call
    exploration_fraction: float = 0.34  # cap on share of low-evidence proposals (hook for PR-8)
    attribution_method: str = context_store.DEFAULT_ATTRIBUTION
    source_model: str = "research_strategist"


@dataclass
class Proposal:
    """A single next-move the strategist recommends. Pure data; no side effects
    until ``apply`` materialises it."""
    operator: str
    parent_node_ids: list[str]   # 1 for single-parent ops; >=2 for combine
    hypothesis: str
    bar_type: str
    market: str
    universe: str
    signals: list[str]
    rationale: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.operator not in VALID_OPERATORS:
            raise StrategistError(f"unknown operator: {self.operator!r}")
        self.bar_type = normalize_bar_type(self.bar_type)


@dataclass
class ApplyResult:
    """Outcome of materialising one proposal: the new node + the pending idea."""
    proposal: Proposal
    node_id: str
    idea_id: str


class ResearchStrategist:
    """Deterministic campaign strategist. Reads M9 + campaign state; writes only
    hypothesis nodes/edges and ``pending`` ideas (via the existing queue)."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        config: StrategistConfig | None = None,
    ):
        self.db_path = db_path
        self.config = config or StrategistConfig()
        self.campaigns = CampaignManager(db_path=db_path)
        self.tree = HypothesisTreeManager(db_path=db_path)

    # ------------------------------------------------------------------ seed
    def seed(
        self,
        campaign_id: str,
        hypothesis: str,
        *,
        signals: list[str],
        market: str,
        universe: str,
        bar_type: str = "time",
        rationale: str | None = None,
        enqueue_idea: bool = True,
    ) -> ApplyResult:
        """Create the campaign's root hypothesis (generation 0) and, by default,
        enqueue it as a pending idea so the baseline gets tested. Idempotent
        guard: raises if the campaign already has nodes."""
        if hypothesis_store.list_nodes(campaign_id, db_path=self.db_path):
            raise StrategistError(
                f"campaign already seeded: {campaign_id}"
            )
        bar_type = normalize_bar_type(bar_type)
        node = self.tree.create_root(
            campaign_id, hypothesis,
            signals=list(signals), market=market, universe=universe,
            bar_type=bar_type, rationale=rationale,
        )
        idea_id = ""
        if enqueue_idea:
            idea_id = self._enqueue_idea(
                campaign_id, node["node_id"], hypothesis,
                signals=list(signals), market=market, universe=universe,
                bar_type=bar_type,
                rationale=rationale or "Campaign baseline (generation 0).",
            )
        return ApplyResult(
            proposal=Proposal(
                operator=OP_REFINE,  # placeholder; roots have no operator
                parent_node_ids=[], hypothesis=hypothesis, bar_type=bar_type,
                market=market, universe=universe, signals=list(signals),
                rationale=rationale or "seed", evidence={"seed": True},
            ),
            node_id=node["node_id"], idea_id=idea_id,
        )

    # --------------------------------------------------------------- propose
    def propose(self, campaign_id: str) -> list[Proposal]:
        """Derive the next bounded set of moves for a campaign. Read-only: no
        nodes or ideas are written. Returns [] when the campaign is not ACTIVE,
        is budget-exhausted, or has no eligible frontier."""
        if self.campaigns.current_state(campaign_id) != STATE_ACTIVE:
            return []
        if self.campaigns.budget_exhausted(campaign_id):
            return []

        nodes = hypothesis_store.list_nodes(campaign_id, db_path=self.db_path)
        if not nodes:
            return []

        scope = self._scope(campaign_id)
        proposals: list[Proposal] = []

        # --- single-lineage moves (vary_bar / cross_market / negate) --------
        # Group expandable nodes by (primary_signal, market, universe) lineage.
        groups: dict[tuple, list[dict]] = {}
        for n in nodes:
            sig = self._primary_signal(n)
            if sig is None:
                continue
            groups.setdefault((sig, n["market"], n["universe"]), []).append(n)

        for (sig, market, universe), group in groups.items():
            # Deepest *expandable confirmed* node is the lineage frontier.
            frontier = self._lineage_frontier(group)
            if frontier is not None:
                p = self._propose_for_frontier(
                    campaign_id, frontier, sig, market, universe, scope, nodes
                )
                if p is not None:
                    proposals.append(p)

            # Refuted frontier → one negate control (terminal child).
            refuted = self._refuted_frontier(group)
            if refuted is not None:
                p = self._propose_negate(refuted, sig, market, universe)
                if p is not None:
                    proposals.append(p)

        # --- combine: pairwise confirmed signals in a shared context --------
        proposals.extend(self._propose_combines(campaign_id, nodes))

        return proposals[: self.config.max_proposals_per_tick]

    def _propose_for_frontier(
        self, campaign_id, frontier, sig, market, universe, scope, nodes
    ) -> Proposal | None:
        # Priority 1: vary_bar — an untried bar type for this lineage.
        tried_bars = {
            n["bar_type"] for n in nodes
            if self._primary_signal(n) == sig
            and n["market"] == market and n["universe"] == universe
        }
        for cand in scope["bar_types"]:
            if cand not in tried_bars:
                return Proposal(
                    operator=OP_VARY_BAR,
                    parent_node_ids=[frontier["node_id"]],
                    hypothesis=(
                        f"{sig} predicts cross-sectional returns in "
                        f"{market}/{universe} on {cand} bars"
                    ),
                    bar_type=cand, market=market, universe=universe,
                    signals=list(frontier.get("signals") or [sig]),
                    rationale=(
                        f"{sig} is confirmed on {frontier['bar_type']} bars; "
                        f"test whether the {cand} sampling clock sharpens it."
                    ),
                    evidence={"trigger": "vary_bar",
                              "confirmed_bar": frontier["bar_type"]},
                )

        # Priority 2: cross_market — narrow confirmed signal, untried market.
        if self._is_narrow(sig, market, universe):
            for cand_mkt in scope["markets"]:
                if cand_mkt == market:
                    continue
                if not self._market_tried(nodes, sig, cand_mkt):
                    cand_univ = scope["universe_for"].get(cand_mkt, universe)
                    return Proposal(
                        operator=OP_CROSS_MARKET,
                        parent_node_ids=[frontier["node_id"]],
                        hypothesis=(
                            f"{sig} on {frontier['bar_type']} bars generalises "
                            f"to {cand_mkt}/{cand_univ}"
                        ),
                        bar_type=frontier["bar_type"],
                        market=cand_mkt, universe=cand_univ,
                        signals=list(frontier.get("signals") or [sig]),
                        rationale=(
                            f"{sig} is confirmed only in {market}; test "
                            f"cross-market generalisation to {cand_mkt}."
                        ),
                        evidence={"trigger": "cross_market",
                                  "confirmed_market": market},
                    )
        return None

    def _propose_negate(self, node, sig, market, universe) -> Proposal | None:
        # Already negated? (frontier dedup)
        for e in hypothesis_store.children_of(node["node_id"], db_path=self.db_path):
            if e["operator"] == OP_NEGATE:
                return None
        return Proposal(
            operator=OP_NEGATE,
            parent_node_ids=[node["node_id"]],
            hypothesis=f"{sig} does NOT predict returns in {market}/{universe} "
                       f"(falsification control)",
            bar_type=node["bar_type"], market=market, universe=universe,
            signals=list(node.get("signals") or [sig]),
            rationale=f"{sig} was refuted; record a falsification control.",
            evidence={"trigger": "negate"},
        )

    def _propose_combines(self, campaign_id, nodes) -> list[Proposal]:
        out: list[Proposal] = []
        # Confirmed nodes grouped by (market, universe, bar_type) context.
        by_ctx: dict[tuple, list[dict]] = {}
        for n in nodes:
            if n["depth"] >= self.config.max_depth:
                continue
            if n.get("origin_operator") == OP_NEGATE:
                continue
            sig = self._primary_signal(n)
            if sig is None or not self._confirmed(sig, n["market"],
                                                  n["universe"], n["bar_type"]):
                continue
            by_ctx.setdefault(
                (n["market"], n["universe"], n["bar_type"]), []
            ).append(n)

        existing_sets = self._existing_combine_sets(nodes)
        for (market, universe, bar_type), members in by_ctx.items():
            # Distinct signals only; pairwise.
            seen: dict[str, dict] = {}
            for n in members:
                seen.setdefault(self._primary_signal(n), n)
            distinct = list(seen.items())
            for i in range(len(distinct)):
                for j in range(i + 1, len(distinct)):
                    (sa, na), (sb, nb) = distinct[i], distinct[j]
                    key = frozenset({sa, sb})
                    if key in existing_sets:
                        continue
                    out.append(Proposal(
                        operator=OP_COMBINE,
                        parent_node_ids=[na["node_id"], nb["node_id"]],
                        hypothesis=(
                            f"{sa} + {sb} composite outperforms either alone in "
                            f"{market}/{universe} on {bar_type} bars"
                        ),
                        bar_type=bar_type, market=market, universe=universe,
                        signals=[sa, sb],
                        rationale=(
                            f"both {sa} and {sb} are independently confirmed in "
                            f"{market}/{universe}/{bar_type}; test a composite."
                        ),
                        evidence={"trigger": "combine"},
                    ))
        return out

    # ----------------------------------------------------------------- apply
    def apply(
        self, campaign_id: str, proposals: list[Proposal]
    ) -> list[ApplyResult]:
        """Materialise proposals: write each as a hypothesis node + edge and
        enqueue it as a ``pending`` idea tagged to the campaign. Approval is
        still required downstream — nothing here runs or approves."""
        results: list[ApplyResult] = []
        for p in proposals:
            node = self._apply_one_node(campaign_id, p)
            idea_id = self._enqueue_idea(
                campaign_id, node["node_id"], p.hypothesis,
                signals=p.signals, market=p.market, universe=p.universe,
                bar_type=p.bar_type, rationale=p.rationale,
            )
            results.append(ApplyResult(p, node["node_id"], idea_id))
        return results

    def _apply_one_node(self, campaign_id, p: Proposal) -> dict[str, Any]:
        if p.operator == OP_COMBINE:
            if len(p.parent_node_ids) < 2:
                raise StrategistError("combine requires >= 2 parent nodes")
            return self.tree.combine(
                p.parent_node_ids, p.hypothesis,
                signals=p.signals, market=p.market, universe=p.universe,
                bar_type=p.bar_type, rationale=p.rationale,
            )
        if p.operator in SINGLE_PARENT_OPERATORS:
            if len(p.parent_node_ids) != 1:
                raise StrategistError(
                    f"{p.operator} requires exactly one parent node"
                )
            return self.tree.evolve(
                p.parent_node_ids[0], p.operator, p.hypothesis,
                signals=p.signals, market=p.market, universe=p.universe,
                bar_type=p.bar_type, rationale=p.rationale,
            )
        raise StrategistError(f"cannot apply operator: {p.operator!r}")

    def run_tick(self, campaign_id: str) -> list[ApplyResult]:
        """Convenience: propose + apply in one call. Returns the applied
        results (empty when there is nothing eligible)."""
        return self.apply(campaign_id, self.propose(campaign_id))

    # ------------------------------------------------------------- internals
    def _enqueue_idea(
        self, campaign_id, node_id, hypothesis, *,
        signals, market, universe, bar_type, rationale,
    ) -> str:
        idea = ProposedIdea(
            hypothesis=hypothesis,
            suggested_signals=tuple(signals),
            source_model=self.config.source_model,
            rationale=rationale or "",
            market=market, universe=universe,
            bar_type=normalize_bar_type(bar_type),
        )
        idea_id = approval_queue.make_idea_id(idea, db_path=self.db_path)
        approval_queue.enqueue(idea, idea_id, db_path=self.db_path)
        # PR-3 write-once attribution + PR-2 node<->idea link.
        campaign_store.link_idea_to_campaign(idea_id, campaign_id, db_path=self.db_path)
        self.tree.link_idea(node_id, idea_id)
        return idea_id

    def _scope(self, campaign_id) -> dict[str, Any]:
        campaign = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        scope = (campaign or {}).get("scope") or {}
        bar_types = [
            normalize_bar_type(b) for b in (scope.get("bar_types") or SUPPORTED_BAR_TYPES)
        ]
        markets = list(scope.get("markets") or [])
        universes = list(scope.get("universes") or [])
        # Map each market to its universe positionally (best-effort) for cross_market.
        universe_for = {}
        for i, m in enumerate(markets):
            if i < len(universes):
                universe_for[m] = universes[i]
        return {"bar_types": bar_types, "markets": markets,
                "universes": universes, "universe_for": universe_for}

    @staticmethod
    def _primary_signal(node) -> str | None:
        sigs = node.get("signals") or []
        if isinstance(sigs, str):
            return sigs or None
        return sigs[0] if sigs else None

    def _expandable(self, node) -> bool:
        if node["depth"] >= self.config.max_depth:
            return False
        if node.get("origin_operator") == OP_NEGATE:
            return False
        if not node.get("experiment_id"):
            return False
        return True

    def _lineage_frontier(self, group) -> dict | None:
        """The lineage's deepest *confirmed* node, but only if it is still
        expandable. We never back off to a shallower ancestor: once the deepest
        confirmed node hits ``max_depth`` (or is a terminal negate child) the
        lineage halts rather than fanning out from an earlier generation."""
        best = None
        for n in group:
            sig = self._primary_signal(n)
            if not self._confirmed(sig, n["market"], n["universe"], n["bar_type"]):
                continue
            if best is None or n["depth"] > best["depth"]:
                best = n
        if best is None or not self._expandable(best):
            return None
        return best

    def _refuted_frontier(self, group) -> dict | None:
        for n in group:
            if not node_has_experiment(n):
                continue
            if n.get("origin_operator") == OP_NEGATE:
                continue
            sig = self._primary_signal(n)
            if self._refuted(sig, n["market"], n["universe"], n["bar_type"]):
                return n
        return None

    # -- M9 evidence reads (signal_context_performance cache) --------------
    def _cell(self, sig, market, universe, bar_type) -> dict | None:
        cells = context_store.context_performance(
            feature_name=sig, market=market, universe=universe,
            bar_type=bar_type, attribution_method=self.config.attribution_method,
            db_path=self.db_path,
        )
        return cells[0] if cells else None

    def _confirmed(self, sig, market, universe, bar_type) -> bool:
        c = self._cell(sig, market, universe, bar_type)
        if c is None:
            return False
        score = c.get("contribution_score")
        return (c.get("n_experiments", 0) >= self.config.min_n
                and score is not None
                and score > self.config.contribution_threshold)

    def _refuted(self, sig, market, universe, bar_type) -> bool:
        c = self._cell(sig, market, universe, bar_type)
        if c is None:
            return False
        score = c.get("contribution_score")
        return (c.get("n_experiments", 0) >= self.config.min_n
                and (score is None or score <= self.config.contribution_threshold))

    def _is_narrow(self, sig, market, universe) -> bool:
        """Confirmed in exactly one market (generalisation still open)."""
        n = context_store.distinct_context_count(
            sig, attribution_method=self.config.attribution_method,
            min_n=self.config.min_n, threshold=self.config.contribution_threshold,
            db_path=self.db_path,
        )
        return n >= 1 and not self._generalises(sig)

    def _generalises(self, sig) -> bool:
        cells = context_store.context_performance(
            feature_name=sig, attribution_method=self.config.attribution_method,
            db_path=self.db_path,
        )
        markets = {
            c["market"] for c in cells
            if c.get("n_experiments", 0) >= self.config.min_n
            and c.get("contribution_score") is not None
            and c["contribution_score"] > self.config.contribution_threshold
        }
        return len(markets) >= 2

    def _market_tried(self, nodes, sig, market) -> bool:
        return any(
            self._primary_signal(n) == sig and n["market"] == market
            for n in nodes
        )

    def _existing_combine_sets(self, nodes) -> set[frozenset]:
        out: set[frozenset] = set()
        for n in nodes:
            if n.get("origin_operator") == OP_COMBINE:
                sigs = n.get("signals") or []
                if isinstance(sigs, list) and len(sigs) >= 2:
                    out.add(frozenset(sigs))
        return out


def node_has_experiment(node) -> bool:
    return bool(node.get("experiment_id"))
