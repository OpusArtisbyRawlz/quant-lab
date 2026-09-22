"""
historical_recovery source — Historical Strategy Recovery.

A thin, deterministic HypothesisSource that re-proposes the historical strategies of
Projects 03-06 from the curated manifest (`agents.recovery`). It self-registers via
``@register`` — the loop is never touched — and, like every P6-5 source, only
*enumerates* candidates and enqueues them as ``pending`` ideas through the existing
approval path (the human gate is intact). It holds no research intelligence: the
"what to recover" is the operator-reviewed manifest; the "how" is the existing
Designer/executor pipeline.

Campaign ``scope`` controls the selection:
  - ``recovery_kind``: 'baseline' (default) | 'blend' | 'overlay' | 'deployment' | 'all'
  - ``strategy_ids``:  optional explicit subset (overrides recovery_kind)
  - ``bar_types``:     optional list; when it has >1 clock this is the Alternative Bar
                       sweep — each alt-bar-eligible strategy is proposed once per clock.
                       Absent ⇒ each strategy is proposed at its own manifest bar_type.

Determinism: strategies are enumerated in sorted manifest order, bar types sorted, and
already-proposed ``(bar_type, hypothesis)`` pairs are skipped, so the source converges
(each candidate once) and re-ticking the same state proposes nothing new.
"""

from __future__ import annotations

from typing import Any

from agents.protocol import normalize_bar_type
from agents import recovery
from agents.storage import campaign_store
from agents.hypothesis_manager import HypothesisTreeManager
from agents.research_loop.sources import (
    HypothesisSource,
    Proposal,
    SourceContext,
    campaign_scope,
    enqueue_proposal,
    existing_specs,
    register,
)

CAMPAIGN_TYPE_HISTORICAL_RECOVERY = "historical_recovery"
_ORIGIN = CAMPAIGN_TYPE_HISTORICAL_RECOVERY


def _selected(scope: dict[str, Any]) -> list[dict[str, Any]]:
    """The manifest strategies this campaign should recover, per scope. Deterministic
    (manifest enumeration is sorted by strategy_id)."""
    ids = scope.get("strategy_ids")
    if ids:
        wanted = set(ids)
        return [s for s in recovery.enumerate_strategies() if s["strategy_id"] in wanted]
    kind = scope.get("recovery_kind", recovery.KIND_BASELINE)
    if kind == "all":
        return recovery.enumerate_strategies()
    return recovery.strategies_for_kind(kind)


class HistoricalRecoverySource:
    def __init__(self, context: SourceContext) -> None:
        self._ctx = context
        # Reuse the existing hypothesis-tree pipeline (sole writer of hypothesis_node)
        # so recovered strategies become first-class M11 hypotheses — exactly as the
        # ResearchStrategist does. No parallel path.
        self._tree = HypothesisTreeManager(db_path=context.db_path)

    def propose(self, campaign_id: str) -> list[Proposal]:
        scope = campaign_scope(self._ctx, campaign_id)
        strategies = _selected(scope)
        if not strategies:
            return []
        sweep = scope.get("bar_types")
        sweep_clocks = sorted({normalize_bar_type(b) for b in sweep}) if sweep else None
        already = existing_specs(self._ctx, campaign_id)

        # Immutable origin provenance for every recovered hypothesis. The manifest
        # version + the campaign's own created_at (an existing, immutable value) make
        # the timestamp a pure function of stored state — replay never regenerates it.
        manifest_version = recovery.load_manifest().get("version", "unknown")
        camp = campaign_store.get_campaign(campaign_id, db_path=self._ctx.db_path) or {}
        recovery_ts = camp.get("created_at")

        out: list[Proposal] = []
        for s in strategies:
            hypothesis = s["hypothesis"]
            prov = recovery.build_provenance(
                s, manifest_version=manifest_version, recovery_timestamp=recovery_ts)
            # Alt-bar sweep applies only to strategies flagged eligible; others (and
            # the no-sweep case) use the strategy's own manifest bar_type.
            if sweep_clocks and s.get("alt_bar_eligible"):
                clocks = sweep_clocks
            else:
                clocks = [normalize_bar_type(s["bar_type"])]
            for bar_type in clocks:
                if (bar_type, hypothesis) in already:
                    continue
                rationale = (f"recover {s['strategy_id']} from {s['project']}"
                             + (f" @ {bar_type} bars" if sweep_clocks else ""))
                # Register the recovered strategy as a root hypothesis node (the
                # existing hypothesis-generation pipeline) with a DETERMINISTIC id, so
                # it enters the M11 tree and — once approved + executed — the loop
                # stamps its experiment onto the node and evidence links back to it.
                node_id = f"rec_{campaign_id}_{s['strategy_id']}_{bar_type}"
                if self._tree.get_node(node_id) is None:
                    self._tree.create_root(
                        campaign_id, hypothesis, node_id=node_id,
                        signals=list(s["signals"]),
                        market=s.get("market", ""),
                        universe=s.get("universe", ""),
                        bar_type=bar_type,
                        rationale=rationale,
                    )
                # A recovered overlay strategy (Project 05) carries its exact
                # {method, floor, k} in the idea metadata (write-once, beside
                # provenance) so spec_builder threads it to the executor's overlay
                # stage. Absent for non-overlay strategies ⇒ no overlay.
                idea_meta = {"provenance": dict(prov, origin_bar_type=bar_type)}
                if s.get("overlay"):
                    idea_meta["overlay"] = dict(s["overlay"])
                # A composite multi-strategy portfolio carries its PortfolioSpec so
                # spec_builder threads it to the executor's composition path.
                if s.get("portfolio"):
                    idea_meta["portfolio"] = dict(s["portfolio"])
                # A deployment-validation strategy carries its deployment directive.
                if s.get("deployment"):
                    idea_meta["deployment"] = dict(s["deployment"])
                # A classifier strategy carries its single-asset classifier directive.
                if s.get("classifier"):
                    idea_meta["classifier"] = dict(s["classifier"])
                proposal = enqueue_proposal(
                    self._ctx, campaign_id,
                    hypothesis=hypothesis,
                    signals=list(s["signals"]),
                    market=s.get("market", ""),
                    universe=s.get("universe", ""),
                    bar_type=bar_type,
                    rationale=rationale,
                    origin=_ORIGIN,
                    metadata=idea_meta,
                )
                # Link idea -> node so the loop's _stamp_node_experiment propagates
                # the executed experiment back onto the hypothesis node.
                self._tree.link_idea(node_id, proposal.idea_id)
                out.append(proposal)
        return out


@register(CAMPAIGN_TYPE_HISTORICAL_RECOVERY)
def _make(context: SourceContext) -> HypothesisSource:
    return HistoricalRecoverySource(context)
