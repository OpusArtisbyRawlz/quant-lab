"""
EvidenceProjector — fold the evidence log into Bayesian posterior projections.

For a hypothesis, the projector reads its ``evidence_event`` rows, converts each
to an :class:`~agents.research_intelligence.statistics.ExperimentEvidence`, runs
the pure ``stat_v1`` engine, and writes the rebuildable projections
(``hypothesis_state`` + ``context_cell_posterior``). It is a **pure fold**: the
projection is a deterministic function of the immutable log, so a full rebuild is
idempotent and replay-stable.

It is **decision-free** — it measures (posterior + four axes) and writes
``stage='Candidate'``. Promotion, retirement, budget, and FDR admission are later
PRs that *read* these projections.

Metrics convention (read from ``evidence_event.metrics`` JSON, with fallbacks):
``net_sharpe`` (else ``sharpe``), ``T``/``n_periods`` (else policy default),
``N``/``periods_per_year`` (else policy default), ``K``/``n_configs`` (else 1),
``stability``. Richer capture into the recorder is a later enhancement and does
not change this engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from agents.storage.db import DB_PATH
from agents.storage import evidence_store, hypothesis_state_store
from .statistics import (
    DEFAULT_POLICY, StatPolicy, ExperimentEvidence, assess_hypothesis,
    credible_interval, _measure, _cell_posterior,
)

# Evidence sources folded into the development posterior. Holdout / live-paper are
# kept apart (they get their own posteriors in the holdout methodology, a later
# PR) so out-of-sample data never leaks into development-stage learning.
DEVELOPMENT_SOURCES = (
    evidence_store.SOURCE_IN_SAMPLE,
    evidence_store.SOURCE_VALIDATION,
    evidence_store.SOURCE_EMBARGO,
    evidence_store.SOURCE_WALK_FORWARD,
)


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def rows_to_evidence(rows: list[dict[str, Any]],
                     policy: StatPolicy = DEFAULT_POLICY) -> list[ExperimentEvidence]:
    """Convert ``evidence_event`` rows into ``ExperimentEvidence`` (stat_v1 input).

    The single source of truth for the row→evidence mapping, reused by both
    ``EvidenceProjector`` (development posterior) and the M11 PR-4 ``HoldoutEngine``
    (IS/OOS posteriors) so the two never drift. Deterministic and insertion-order
    independent: rows are sorted by a stable run-time proxy so the decay clock Δ is
    replay-/shuffle-stable, then Δ_i is the event-count since experiment i (the
    most recent has Δ=0). Rows without a usable performance number are skipped.
    """
    rows = sorted(
        rows,
        key=lambda r: (r.get("date_end") or "", r.get("date_start") or "",
                       r["experiment_id"]),
    )
    last = len(rows) - 1
    out: list[ExperimentEvidence] = []
    for seq, r in enumerate(rows):
        metrics = r.get("metrics") or {}
        metrics = metrics if isinstance(metrics, dict) else {}
        net = _num(metrics.get("net_sharpe"))
        if net is None:
            net = _num(metrics.get("sharpe"))
        if net is None:
            continue  # no usable performance number → skip this row
        T = (_num(metrics.get("T")) or _num(metrics.get("n_periods"))
             or policy.default_T)
        N = (_num(metrics.get("N")) or _num(metrics.get("periods_per_year"))
             or policy.default_N)
        K = int(_num(metrics.get("K")) or _num(metrics.get("n_configs")) or 1)
        out.append(ExperimentEvidence(
            experiment_id=r["experiment_id"],
            net_sharpe=net, T=T, N=N, K=K,
            delta=float(last - seq),
            market=r.get("market") or "unknown",
            universe=r.get("universe") or "unknown",
            regime=r.get("regime") or "all",
            bar_type=r.get("bar_type") or "time",
            date_start=r.get("date_start"),
            date_end=r.get("date_end"),
            stability=_num(metrics.get("stability")),
        ))
    return out


class EvidenceProjector:
    def __init__(self, db_path: Path = DB_PATH,
                 policy: StatPolicy = DEFAULT_POLICY,
                 sources: Iterable[str] = DEVELOPMENT_SOURCES) -> None:
        self.db_path = db_path
        self.policy = policy
        self.sources = frozenset(sources)

    # -- evidence_event row → ExperimentEvidence ---------------------------
    def _to_evidence(self, rows: list[dict[str, Any]]) -> list[ExperimentEvidence]:
        return rows_to_evidence(rows, self.policy)

    # -- rebuild one hypothesis -------------------------------------------
    def rebuild_hypothesis(self, hypothesis_id: str) -> dict[str, Any] | None:
        """Recompute and persist the projection for one hypothesis.

        Returns the written ``hypothesis_state`` row, or ``None`` if the
        hypothesis has no usable development evidence.
        """
        rows = [
            e for e in evidence_store.list_evidence(
                hypothesis_id=hypothesis_id, db_path=self.db_path)
            if e["evidence_source"] in self.sources
        ]
        evidence = self._to_evidence(rows)
        if not evidence:
            return None

        state = assess_hypothesis(evidence, self.policy)

        # Cell-level posteriors (recomputed the same deterministic way).
        measured = [_measure(e, self.policy) for e in evidence]
        by_cell: dict[tuple, list] = {}
        for md in measured:
            by_cell.setdefault(md.cell, []).append(md)
        cell_rows = []
        for cell in sorted(by_cell):
            cp = _cell_posterior(cell, by_cell[cell], self.policy)
            lo, hi = credible_interval(cp.mu, cp.sigma, self.policy)
            m, u, rg, bt = cell
            cell_rows.append({
                "market": m, "universe": u, "regime": rg, "bar_type": bt,
                "post_mu": cp.mu, "post_sigma": cp.sigma,
                "post_ci_low": lo, "post_ci_high": hi,
                "post_exceed_prob": cp.exceed_prob(self.policy),
                "n_eff": cp.n_eff, "m": cp.m, "method": self.policy.version,
            })

        row = {
            "hypothesis_id": hypothesis_id,
            "stage": state.stage,
            "posterior_mean": state.posterior_mean,
            "posterior_sd": state.posterior_sd,
            "ci_low": state.ci_low,
            "ci_high": state.ci_high,
            "tau2": state.tau2,
            "n_eff": state.n_eff,
            "n_supporting": state.n_supporting,
            "n_contradicting": state.n_contradicting,
            "q_stat_prob": state.quality.exceed_prob,
            "q_precision": state.quality.precision,
            "r_sign": state.reproducibility.sign,
            "r_disp": state.reproducibility.dispersion,
            "r_replicas": state.reproducibility.replica_score,
            "stability": state.reproducibility.stability,
            "g_count": state.generalisation.count,
            "g_coverage": state.generalisation.coverage,
            "v_net_sharpe": state.value.net_sharpe,
            "v_ci_low": state.value.ci_low,
            "v_ci_high": state.value.ci_high,
            "lfdr": state.lfdr,
            "method": state.method,
        }
        hypothesis_state_store.upsert_hypothesis_state(row, db_path=self.db_path)
        hypothesis_state_store.replace_cell_posteriors(
            hypothesis_id, cell_rows, db_path=self.db_path)
        return row

    # -- rebuild everything -----------------------------------------------
    def rebuild_all(self) -> list[str]:
        """Rebuild projections for every hypothesis present in the log.

        Returns the list of hypothesis_ids that produced a projection.
        """
        rebuilt: list[str] = []
        for hid in evidence_store.distinct_hypothesis_ids(db_path=self.db_path):
            if self.rebuild_hypothesis(hid) is not None:
                rebuilt.append(hid)
        return rebuilt
