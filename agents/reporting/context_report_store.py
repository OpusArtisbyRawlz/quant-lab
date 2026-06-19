"""
context_report_store — read-only reporting over Milestone 9 context-aware
signal intelligence.

Like report_store, this module never writes. Unlike report_store it issues no
SQL of its own: it composes the read APIs of agents.storage.context_store and
agents.storage.signal_store into typed reporting dataclasses. That keeps the
context grain (feature x market x universe x regime x bar_type) authoritative
and lets the report answer the M9 questions directly:

  * "Which signals work best in India / US / NIFTY50 / high_vol?" -> leaderboard
    filtered by a context.
  * "Does momentum_20 generalise or is it market/regime dependent?" ->
    generalisation report.
  * "When and why was a signal promoted/retired?" -> lifecycle audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agents.storage.db import DB_PATH
from agents.storage import context_store as cs
from agents.storage import signal_store as ss


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContextCellStat:
    """One context cell: a signal's performance in a specific context."""
    feature_name: str
    market: str
    universe: str
    regime: str
    bar_type: str
    n_experiments: int
    n_with_net: int
    avg_net_sharpe: float | None
    avg_net_calmar: float | None
    keep_rate: float | None
    contribution_score: float | None
    min_n_met: bool


@dataclass(frozen=True)
class GeneralizationStat:
    """How broadly a signal works, with its lifecycle standing."""
    feature_name: str
    lifecycle_state: str
    generalization_class: str | None
    n_context_cells: int
    distinct_markets: int
    distinct_universes: int
    distinct_regimes: int
    best_context: str | None        # "market/universe/regime" of strongest cell
    best_contribution: float | None


@dataclass(frozen=True)
class LifecycleEventStat:
    feature_name: str
    from_state: str | None
    to_state: str
    reason_code: str | None
    context_scope: str | None
    evidence_n: int | None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cell(row: dict) -> ContextCellStat:
    return ContextCellStat(
        feature_name=row["feature_name"],
        market=row["market"],
        universe=row["universe"],
        regime=row["regime"],
        bar_type=row["bar_type"],
        n_experiments=row["n_experiments"],
        n_with_net=row["n_with_net"],
        avg_net_sharpe=row["avg_net_sharpe"],
        avg_net_calmar=row["avg_net_calmar"],
        keep_rate=row["keep_rate"],
        contribution_score=row["contribution_score"],
        min_n_met=bool(row["min_n_met"]),
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def signal_context_summary(
    *,
    feature_name: str | None = None,
    market: str | None = None,
    universe: str | None = None,
    regime: str | None = None,
    bar_type: str | None = None,
    min_n: int | None = None,
    db_path: Path = DB_PATH,
) -> list[ContextCellStat]:
    """All context cells matching the given filters, strongest first."""
    rows = cs.context_performance(
        feature_name=feature_name, market=market, universe=universe,
        regime=regime, bar_type=bar_type, min_n=min_n, db_path=db_path)
    return [_cell(r) for r in rows]


def context_leaderboard(
    *,
    market: str | None = None,
    universe: str | None = None,
    regime: str | None = None,
    bar_type: str | None = None,
    min_n: int | None = None,
    top: int = 10,
    db_path: Path = DB_PATH,
) -> list[ContextCellStat]:
    """Best signals *within* a context — answers 'which signals work best in X'.

    Pass market='India' for the India leaderboard, regime='high_vol' for the
    high-volatility leaderboard, or combine them. Results are already ordered by
    contribution_score descending by context_store.
    """
    cells = signal_context_summary(
        market=market, universe=universe, regime=regime, bar_type=bar_type,
        min_n=min_n, db_path=db_path)
    return cells[:top]


def signal_generalization_report(
    db_path: Path = DB_PATH) -> list[GeneralizationStat]:
    """Per-signal breadth + lifecycle standing, for every known signal."""
    out: list[GeneralizationStat] = []
    for sig in ss.list_signals(db_path=db_path):
        feat = sig["feature_name"]
        cells = cs.context_performance(feature_name=feat, db_path=db_path)
        markets = {c["market"] for c in cells}
        universes = {c["universe"] for c in cells}
        regimes = {c["regime"] for c in cells if c["regime"] != cs.REGIME_ALL}
        scored = [c for c in cells if c["contribution_score"] is not None]
        best = max(scored, key=lambda c: c["contribution_score"], default=None)
        out.append(GeneralizationStat(
            feature_name=feat,
            lifecycle_state=sig.get("lifecycle_state", "observed"),
            generalization_class=sig.get("generalization_class"),
            n_context_cells=len(cells),
            distinct_markets=len(markets),
            distinct_universes=len(universes),
            distinct_regimes=len(regimes),
            best_context=(f"{best['market']}/{best['universe']}/{best['regime']}"
                          if best else None),
            best_contribution=(best["contribution_score"] if best else None),
        ))
    # Promoted first, then by breadth.
    order = {"promoted": 0, "candidate": 1, "observed": 2, "retired": 3}
    out.sort(key=lambda g: (order.get(g.lifecycle_state, 9),
                            -g.distinct_markets, -g.n_context_cells))
    return out


def lifecycle_audit_report(
    feature_name: str | None = None,
    db_path: Path = DB_PATH) -> list[LifecycleEventStat]:
    """Chronological lifecycle transitions, optionally for one signal."""
    rows = ss.list_lifecycle_events(feature_name=feature_name, db_path=db_path)
    return [
        LifecycleEventStat(
            feature_name=r["feature_name"],
            from_state=r["from_state"],
            to_state=r["to_state"],
            reason_code=r["reason_code"],
            context_scope=r["context_scope"],
            evidence_n=r["evidence_n"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
