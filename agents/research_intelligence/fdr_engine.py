"""
FdrEngine — project §7 multiple-testing control over the population (M11 PR-5).

Unlike the per-hypothesis engines, FDR is inherently **population-level**: a
discovery is relative to everything tried. The engine reads every hypothesis's
posterior lfdr (PR-2 ``hypothesis_state``) and its development evidence (PR-1
``evidence_event``), then in one pass computes the §7.1 Bayesian admission set D
and the §7.2 BH q-values, writing one ``fdr_evaluation`` row per hypothesis.

It is a **pure fold**: the result is a deterministic function of the immutable log
and the deterministic PR-2 projection, so a rebuild is idempotent and replay
stable. It **computes no promotion decision** and mutates no evidence — the
Promotion Engine *consumes* the result and never computes FDR.

Reuses stat_v1 verbatim: lfdr comes straight from ``hypothesis_state``; the
frequentist p-values reuse the per-experiment ``_measure`` weights. Nothing in the
posterior/evidence APIs is changed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import evidence_store, hypothesis_state_store, fdr_store
from .evidence_projector import DEVELOPMENT_SOURCES, rows_to_evidence
from .statistics import DEFAULT_POLICY as STAT_DEFAULT_POLICY, StatPolicy
from .fdr import (
    DEFAULT_POLICY as FDR_DEFAULT_POLICY, FdrPolicy,
    bayesian_fdr_admit, hypothesis_pvalue, benjamini_hochberg,
)


class FdrEngine:
    def __init__(self, db_path: Path = DB_PATH,
                 stat_policy: StatPolicy = STAT_DEFAULT_POLICY,
                 policy: FdrPolicy = FDR_DEFAULT_POLICY) -> None:
        self.db_path = db_path
        self.stat_policy = stat_policy
        self.policy = policy
        self.sources = frozenset(DEVELOPMENT_SOURCES)

    def _pvalue(self, hypothesis_id: str) -> float | None:
        rows = [
            e for e in evidence_store.list_evidence(
                hypothesis_id=hypothesis_id, db_path=self.db_path)
            if e["evidence_source"] in self.sources
        ]
        ev = rows_to_evidence(rows, self.stat_policy)
        if not ev:
            return None
        return hypothesis_pvalue(ev, self.stat_policy, self.policy)

    def rebuild_all(self) -> list[str]:
        """Recompute the population FDR and persist one row per hypothesis.

        Returns the hypothesis_ids written (every hypothesis with a posterior).
        Deterministic and idempotent: a re-fold reproduces identical rows and
        prunes rows for hypotheses no longer in the population.
        """
        states = hypothesis_state_store.list_hypothesis_states(db_path=self.db_path)
        current_ids = {st["hypothesis_id"] for st in states}

        # Prune projections for hypotheses that have left the population.
        for existing in fdr_store.list_fdr(db_path=self.db_path):
            if existing["hypothesis_id"] not in current_ids:
                fdr_store.delete_fdr(existing["hypothesis_id"], db_path=self.db_path)

        if not states:
            return []

        lfdr_by_id = {st["hypothesis_id"]: st["lfdr"] for st in states}
        p_by_id: dict[str, float] = {}
        for hid in sorted(current_ids):
            p = self._pvalue(hid)
            if p is not None:
                p_by_id[hid] = p

        admitted, avg_lfdr = bayesian_fdr_admit(lfdr_by_id, self.policy)
        q_by_id = benjamini_hochberg(p_by_id, self.policy)
        m_pop = len(states)
        m_bh = len(p_by_id)

        for hid in sorted(current_ids):
            p = p_by_id.get(hid)
            q = q_by_id.get(hid)
            row = {
                "hypothesis_id": hid,
                "lfdr": lfdr_by_id[hid],
                "bayes_admitted": 1 if hid in admitted else 0,
                "bayes_avg_lfdr": avg_lfdr,
                "p_value": p,
                "q_value": q,
                "bh_admitted": 1 if (q is not None and q <= self.policy.alpha) else 0,
                "population_size": m_pop,
                "bh_population": m_bh,
                "alpha": self.policy.alpha,
                "q_max": self.policy.q_max,
                "variant": self.policy.variant,
                "method": self.policy.version,
            }
            fdr_store.upsert_fdr(row, db_path=self.db_path)

        return sorted(current_ids)
