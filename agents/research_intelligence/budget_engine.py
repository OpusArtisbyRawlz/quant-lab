"""
BudgetEngine — project the §4 evidence budget over the population (M11 PR-7).

Like FDR, the budget is a **population-level** allocation: shares are relative to
everything live. The engine reads each hypothesis's posterior (μ_h, σ_h from PR-2
``hypothesis_state``; mean se² from the development evidence via the shared
``_measure``) and the retirement determination (PR-6 ``retirement_evaluation`` —
retired ⇒ excluded from the live set), computes EVOI, and allocates ``b_h`` with
the hard ``a_max`` ceiling, writing one ``budget_allocation`` row per hypothesis.

It is a **pure fold**: a deterministic function of the immutable log + the
deterministic upstream projections, so a rebuild is idempotent and replay-stable.
It **recomputes no posterior statistic** (μ/σ consumed verbatim; only mean se²,
which is not stored, is derived from the same per-experiment measurements the
posterior used), mutates no evidence, writes no promotion/retirement decision, and
**modifies no agent** — the existing quota consumes ``b_h`` via its ``accept`` seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import (
    evidence_store, hypothesis_state_store, retirement_store, budget_store,
)
from .evidence_projector import DEVELOPMENT_SOURCES, rows_to_evidence
from .statistics import _measure, DEFAULT_POLICY as STAT_DEFAULT_POLICY, StatPolicy
from .budget import (
    DEFAULT_POLICY as BUDGET_DEFAULT_POLICY, BudgetPolicy, evoi, nearest_gate, allocate,
)
from scipy.stats import norm


class BudgetEngine:
    def __init__(self, db_path: Path = DB_PATH,
                 stat_policy: StatPolicy = STAT_DEFAULT_POLICY,
                 policy: BudgetPolicy = BUDGET_DEFAULT_POLICY) -> None:
        self.db_path = db_path
        self.stat_policy = stat_policy
        self.policy = policy
        self.sources = frozenset(DEVELOPMENT_SOURCES)

    def _mean_se2(self, hypothesis_id: str) -> float:
        """Mean per-experiment se² for the predictive variance (§4.1), from the
        same development evidence + ``_measure`` the posterior used."""
        rows = [
            e for e in evidence_store.list_evidence(
                hypothesis_id=hypothesis_id, db_path=self.db_path)
            if e["evidence_source"] in self.sources
        ]
        ev = rows_to_evidence(rows, self.stat_policy)
        if not ev:
            return 0.0
        measured = [_measure(e, self.stat_policy) for e in ev]
        return sum(m.se * m.se for m in measured) / len(measured)

    def rebuild_all(self, window: int | None = None) -> list[str]:
        """Recompute the population budget and persist one row per hypothesis.

        ``window`` = B_window (scheduling-window experiment slots); defaults to the
        policy's ``default_window``. Returns the hypothesis_ids written; prunes rows
        for hypotheses no longer present.
        """
        window = self.policy.default_window if window is None else window
        states = hypothesis_state_store.list_hypothesis_states(db_path=self.db_path)
        current_ids = {st["hypothesis_id"] for st in states}

        for existing in budget_store.list_budgets(db_path=self.db_path):
            if existing["hypothesis_id"] not in current_ids:
                budget_store.delete_budget(existing["hypothesis_id"], db_path=self.db_path)

        if not states:
            return []

        by_id = {st["hypothesis_id"]: st for st in states}
        evoi_by_id: dict[str, float] = {}
        aux: dict[str, dict[str, float]] = {}
        live_ids: set[str] = set()
        for hid in sorted(current_ids):
            st = by_id[hid]
            retired = self._is_retired(hid)
            mu = st["posterior_mean"]
            sigma = st["posterior_sd"]
            mse2 = self._mean_se2(hid)
            e = evoi(mu, sigma, mse2, self.policy)
            evoi_by_id[hid] = e
            aux[hid] = {
                "mu": mu, "sigma": sigma, "mean_se2": mse2,
                "promise": float(norm.cdf((mu - self.policy.S_star) / sigma)) if sigma > 0 else 0.0,
                "nearest_gate": nearest_gate(mu, self.policy),
            }
            if not retired:
                live_ids.add(hid)

        allocations = allocate(evoi_by_id, live_ids, window, self.policy)
        m_live = len(live_ids)

        for hid in sorted(current_ids):
            a = allocations[hid]
            x = aux[hid]
            row = {
                "hypothesis_id": hid,
                "evoi": a.evoi,
                "share_raw": a.share_raw,
                "a_frac": a.a_frac,
                "b_experiments": a.b_experiments,
                "capped": 1 if a.capped else 0,
                "retired": 1 if a.retired else 0,
                "mu": x["mu"], "sigma": x["sigma"], "mean_se2": x["mean_se2"],
                "promise": x["promise"], "nearest_gate": x["nearest_gate"],
                "window": window,
                "population_size": m_live,
                "a_max": self.policy.a_max,
                "a_min": self.policy.a_min,
                "method": self.policy.version,
            }
            budget_store.upsert_budget(row, db_path=self.db_path)

        return sorted(current_ids)

    def _is_retired(self, hypothesis_id: str) -> bool:
        r = retirement_store.get_retirement(hypothesis_id, db_path=self.db_path)
        return bool(r["retired"]) if r is not None else False
