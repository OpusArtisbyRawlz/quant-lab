"""
SignalLibrarian — Milestone 9 context-aware signal intelligence agent.

Deterministic. No LLM. Runs *after* the Ledger has written an experiment's
decision and lesson. For each completed experiment it:

  1. Classifies the experiment's regime (deterministic, from stored volatility)
     and records the regime label.
  2. Decomposes the experiment into one context observation per feature, keyed
     by the full context cell (feature x market x universe x regime x bar_type),
     appended to the immutable signal_context_observation provenance table.
  3. Upserts each feature into signal_library and links the experiment.
  4. Rebuilds the signal_context_performance cache from observations.
  5. Re-evaluates each touched signal's generalization class and lifecycle
     state from its context cells, emitting an immutable lifecycle event on any
     state change (this activates the dormant signal-library lifecycle, TD-4).
  6. Distils a context-scoped research_memory row for promoted/strong signals.

Design invariants
-----------------
* No global aggregate is ever stored as a primary. Every number is derived from
  the per-context observations, so signal *quality*, *market dependency*,
  *universe dependency*, and *regime dependency* are all distinguishable and
  fully attributable.
* Promotion requires multi-context confirmation (>= 2 distinct markets or >= 2
  distinct regimes clearing the bar). A single lucky context never promotes a
  signal — the overfitting guard (Q5).
* Absolute net Sharpe is not treated as investability-grade (TD-1); promotion is
  gated on cross-context *consistency*, not an absolute threshold. Formal
  statistical confirmation is deferred to M11.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agents.storage.db import DB_PATH
from agents.storage.ledger_store import get_experiment, list_experiments
from agents.storage import signal_store, context_store, memory_store

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibrarianConfig:
    """Tunable thresholds for lifecycle/generalization decisions."""
    min_n: int = 2                 # min experiments in a cell to count as evidence
    contribution_threshold: float = 0.0   # net-Sharpe bar a cell must clear to "pass"
    promote_min_contexts: int = 2  # distinct markets OR regimes required to promote
    regime_method: str = context_store.DEFAULT_REGIME_METHOD
    bar_type: str = context_store.DEFAULT_BAR_TYPE


# Lifecycle states, lowest to highest confidence.
OBSERVED = "observed"
CANDIDATE = "candidate"
PROMOTED = "promoted"
RETIRED = "retired"


@dataclass
class SignalEvaluation:
    feature_name: str
    lifecycle_state: str
    generalization_class: str
    n_passing_cells: int
    distinct_markets: int
    distinct_regimes: int
    state_changed: bool = False


@dataclass
class LibrarianResult:
    experiment_id: str
    processed: bool
    regime: str | None = None
    features: list[str] = field(default_factory=list)
    evaluations: list[SignalEvaluation] = field(default_factory=list)
    reason: str | None = None       # set when processed is False


# Lightweight signal_type inference from a feature name (advisory only).
def _infer_signal_type(feature_name: str) -> str | None:
    f = feature_name.lower()
    if "momentum" in f or "_mom" in f or f.startswith("mom"):
        return "momentum"
    if "revers" in f or "mean_rev" in f or "meanrev" in f:
        return "mean_reversion"
    if "vol" in f:
        return "volatility"
    if "macro" in f or "rate" in f or "yield" in f:
        return "macro"
    return None


class SignalLibrarian:
    """Post-Ledger agent that maintains context-aware signal knowledge."""

    def __init__(self, config: LibrarianConfig | None = None) -> None:
        self.config = config or LibrarianConfig()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def record_experiment(self, experiment_id: str,
                          db_path: Path = DB_PATH) -> LibrarianResult:
        """Ingest one completed experiment into the context-aware library.

        Rebuilds the cache and re-evaluates every feature the experiment used.
        Safe to call more than once for the same experiment (idempotent: the
        observation table is keyed on experiment x feature, so values are
        recomputed in place rather than duplicated).
        """
        exp = get_experiment(experiment_id, db_path=db_path)
        if exp is None:
            return LibrarianResult(experiment_id, processed=False,
                                   reason="experiment_not_found")

        features = self._parse_features(exp.get("features"))
        if not features:
            return LibrarianResult(experiment_id, processed=False,
                                   reason="no_features")

        market = exp.get("market") or context_store.UNKNOWN
        universe = exp.get("universe") or context_store.UNKNOWN
        regime = context_store.classify_regime(
            exp.get("vol"), method=self.config.regime_method)
        context_store.record_regime_label(
            experiment_id, regime, method=self.config.regime_method,
            db_path=db_path)

        net_sharpe = exp.get("net_sharpe")
        net_calmar = exp.get("net_calmar")
        decision = exp.get("decision")
        kept = 1 if decision == "keep" else (0 if decision is not None else None)

        for feat in features:
            self._ensure_signal(feat, market, universe, experiment_id,
                                exp.get("project"), db_path)
            context_store.add_context_observation(
                experiment_id=experiment_id,
                feature_name=feat,
                market=market,
                universe=universe,
                regime=regime,
                bar_type=self.config.bar_type,
                attribution_method=context_store.DEFAULT_ATTRIBUTION,
                net_sharpe=net_sharpe,
                net_calmar=net_calmar,
                kept=kept,
                db_path=db_path,
            )

        # Rebuild the cache from the full observation set, then re-evaluate the
        # signals this experiment touched.
        context_store.rebuild_context_cache(db_path, min_n=self.config.min_n)
        evaluations = [self._evaluate_signal(feat, db_path) for feat in features]

        return LibrarianResult(
            experiment_id=experiment_id,
            processed=True,
            regime=regime,
            features=features,
            evaluations=evaluations,
        )

    def backfill(self, db_path: Path = DB_PATH) -> list[LibrarianResult]:
        """Replay every completed experiment through record_experiment.

        Used once after the v7 migration to populate context knowledge from the
        existing experiment corpus. Derived purely from committed experiment
        rows; mutates no experiment data.
        """
        results: list[LibrarianResult] = []
        for exp in list_experiments(db_path=db_path):
            # Only experiments with a Critic decision are "completed enough" to
            # carry an interpretable kept flag; others still contribute their
            # net metrics but with kept=NULL.
            results.append(self.record_experiment(exp["experiment_id"],
                                                  db_path=db_path))
        return results

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_features(raw) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(f) for f in raw]
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return [str(f) for f in parsed]
        return []

    @staticmethod
    def _ensure_signal(feature_name: str, market: str, universe: str,
                       experiment_id: str, project: str | None,
                       db_path: Path) -> None:
        existing = signal_store.get_signal(feature_name, db_path=db_path)
        if existing is None:
            signal_store.upsert_signal(
                {
                    "feature_name": feature_name,
                    "signal_type": _infer_signal_type(feature_name),
                    "market": market,
                    "universe": universe,
                    "project_source": project,
                    "experiment_ids": [experiment_id],
                    "lifecycle_state": OBSERVED,
                },
                db_path=db_path,
            )
        else:
            signal_store.add_experiment_to_signal(
                feature_name, experiment_id, db_path=db_path)

    def _evaluate_signal(self, feature_name: str,
                         db_path: Path) -> SignalEvaluation:
        """Recompute generalization class and lifecycle state for one signal."""
        cfg = self.config
        cells = context_store.context_performance(
            feature_name=feature_name, db_path=db_path)

        passing = [
            c for c in cells
            if c["n_experiments"] >= cfg.min_n
            and c["contribution_score"] is not None
            and c["contribution_score"] >= cfg.contribution_threshold
        ]
        markets_pass = {c["market"] for c in passing}
        universes_pass = {c["universe"] for c in passing}
        regimes_pass = {c["regime"] for c in passing if c["regime"] != context_store.REGIME_ALL}

        gen_class = self._generalization_class(
            passing, markets_pass, universes_pass, regimes_pass)
        new_state = self._lifecycle_state(
            feature_name, passing, markets_pass, regimes_pass, cells, db_path)

        current = signal_store.get_signal(feature_name, db_path=db_path) or {}
        old_state = current.get("lifecycle_state", OBSERVED)
        state_changed = new_state != old_state

        promoted_at = None
        retired_at = None
        if state_changed and new_state == PROMOTED:
            promoted_at = datetime.now(timezone.utc).isoformat()
        if state_changed and new_state == RETIRED:
            retired_at = datetime.now(timezone.utc).isoformat()

        signal_store.update_lifecycle(
            feature_name, new_state, generalization_class=gen_class,
            promoted_at=promoted_at, retired_at=retired_at, db_path=db_path)

        if state_changed:
            signal_store.log_lifecycle_event(
                feature_name, new_state, from_state=old_state,
                reason_code=self._reason_code(new_state, markets_pass, regimes_pass),
                context_scope=self._scope_str(passing),
                evidence_n=sum(c["n_experiments"] for c in passing),
                db_path=db_path,
            )
            if new_state == PROMOTED:
                self._write_promotion_memory(feature_name, gen_class, passing,
                                             db_path)

        return SignalEvaluation(
            feature_name=feature_name,
            lifecycle_state=new_state,
            generalization_class=gen_class,
            n_passing_cells=len(passing),
            distinct_markets=len(markets_pass),
            distinct_regimes=len(regimes_pass),
            state_changed=state_changed,
        )

    @staticmethod
    def _generalization_class(passing, markets_pass, universes_pass,
                              regimes_pass) -> str:
        """Label *where* a signal works, never just *whether* it works.

        universal        — clears the bar in >= 2 distinct markets.
        market_specific  — clears in a single market but generalises within it
                           (across >= 2 regimes or >= 2 universes).
        regime_specific  — confined to a single market and a single real regime.
        universe_specific— confined to a single market/universe with no regime
                           resolution ('all').
        unproven         — no context cell clears the bar yet.
        """
        if not passing:
            return "unproven"
        if len(markets_pass) >= 2:
            return "universal"
        if len(regimes_pass) >= 2 or len(universes_pass) >= 2:
            return "market_specific"
        # Single passing context within a single market.
        if regimes_pass:  # exactly one real regime
            return "regime_specific"
        return "universe_specific"

    def _lifecycle_state(self, feature_name, passing, markets_pass,
                         regimes_pass, all_cells, db_path) -> str:
        """Multi-context-confirmed promotion; conservative retirement."""
        cfg = self.config
        multi_context = (len(markets_pass) >= cfg.promote_min_contexts
                         or len(regimes_pass) >= cfg.promote_min_contexts)
        if multi_context:
            return PROMOTED
        if passing:
            return CANDIDATE

        # No passing cells. Retire only on substantial *negative* evidence and
        # only if the signal had previously earned candidate/promoted status.
        current = signal_store.get_signal(feature_name, db_path=db_path) or {}
        prior = current.get("lifecycle_state", OBSERVED)
        scored = [c for c in all_cells
                  if c["n_experiments"] >= cfg.min_n
                  and c["contribution_score"] is not None]
        if prior in (CANDIDATE, PROMOTED) and scored and all(
                c["contribution_score"] < 0 for c in scored):
            return RETIRED
        return OBSERVED

    @staticmethod
    def _reason_code(state, markets_pass, regimes_pass) -> str:
        if state == PROMOTED:
            if len(markets_pass) >= 2:
                return "confirmed_across_markets"
            return "confirmed_across_regimes"
        if state == CANDIDATE:
            return "single_context_pass"
        if state == RETIRED:
            return "negative_across_contexts"
        return "insufficient_evidence"

    @staticmethod
    def _scope_str(passing) -> str:
        if not passing:
            return "none"
        scopes = sorted(
            f"{c['market']}/{c['universe']}/{c['regime']}/{c['bar_type']}"
            for c in passing
        )
        return "; ".join(scopes[:10])

    @staticmethod
    def _write_promotion_memory(feature_name, gen_class, passing, db_path) -> None:
        best = max(passing, key=lambda c: c["contribution_score"])
        scope_key = f"{best['market']}/{best['universe']}/{best['regime']}"
        finding = (
            f"Signal '{feature_name}' promoted ({gen_class}); strongest context "
            f"{scope_key} net_sharpe~{best['contribution_score']}"
        )
        implication = (
            "Prioritise in matching contexts; probe generalisation by testing "
            "in adjacent markets/regimes before treating as universal."
        )
        memory_store.add_memory(scope_key, finding, implication=implication,
                                confidence="medium", db_path=db_path)
