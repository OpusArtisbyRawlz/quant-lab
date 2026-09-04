"""
PromotionEngine — project lifecycle recommendations over the evidence layer.

For each hypothesis, the engine **reads** PR-2's ``hypothesis_state`` posterior
projection (posterior + four axes) and makes cheap provenance reads of the PR-1
``evidence_event`` log (independent-replica count + robustness flags), then
applies the pure ``promotion_v1`` policy and writes one row to the rebuildable
``promotion_recommendation`` projection.

It **recomputes no statistics** — the posterior and axes are consumed verbatim
from PR-2 (§ "do not recompute evidence that already exists"). It is a **pure
fold**: the recommendation is a deterministic function of the immutable log and
the deterministic PR-2 projection, so a rebuild is idempotent and replay-stable.

It is **recommendation-only**: it never mutates ``hypothesis_state``, never
changes an authoritative stage, and never touches historical evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import (
    evidence_store, hypothesis_state_store, promotion_store, holdout_store,
    fdr_store,
)
from .evidence_projector import DEVELOPMENT_SOURCES
from .promotion import (
    DEFAULT_POLICY, PromotionPolicy, PromotionInputs, recommend,
)


def _has_usable_performance(metrics: Any) -> bool:
    """Mirror EvidenceProjector: a row folds into the posterior iff it carries a
    numeric ``net_sharpe`` (else ``sharpe``). Replica counting uses the same rule
    so the promotion engine's ``m`` matches the posterior's ``m`` exactly."""
    if not isinstance(metrics, dict):
        return False
    for key in ("net_sharpe", "sharpe"):
        v = metrics.get(key)
        if v is None:
            continue
        try:
            float(v)
            return True
        except (TypeError, ValueError):
            continue
    return False


class PromotionEngine:
    def __init__(self, db_path: Path = DB_PATH,
                 policy: PromotionPolicy = DEFAULT_POLICY) -> None:
        self.db_path = db_path
        self.policy = policy
        self.sources = frozenset(DEVELOPMENT_SOURCES)

    # -- provenance from the immutable evidence log ------------------------
    def _log_provenance(self, hypothesis_id: str) -> tuple[int, bool]:
        """(replica_count, has_unresolved_critical_flag) from development-source
        evidence — read straight from the PR-1 log, no statistics recomputed."""
        rows = [
            e for e in evidence_store.list_evidence(
                hypothesis_id=hypothesis_id, db_path=self.db_path)
            if e["evidence_source"] in self.sources
        ]
        replicas: set[str] = set()
        has_critical = False
        for r in rows:
            if _has_usable_performance(r.get("metrics")):
                replicas.add(r["experiment_id"])
            flags = r.get("robustness_flags") or []
            if isinstance(flags, list) and any(
                f in self.policy.critical_robustness_flags for f in flags
            ):
                has_critical = True
        return len(replicas), has_critical

    # -- rebuild one hypothesis -------------------------------------------
    def rebuild_hypothesis(self, hypothesis_id: str) -> dict[str, Any] | None:
        """Recompute and persist the recommendation for one hypothesis.

        Returns the written ``promotion_recommendation`` row, or ``None`` if the
        hypothesis has no posterior projection to act on.
        """
        state = hypothesis_state_store.get_hypothesis_state(
            hypothesis_id, db_path=self.db_path)
        if state is None:
            return None

        replica_count, has_critical = self._log_provenance(hypothesis_id)

        # Consume the HoldoutEngine's §5 evaluation (PR-4) if present. Promotion
        # *reads* holdout evidence and never computes it: absent evaluation ⇒
        # holdout_pass stays None (unavailable), exactly as before PR-4.
        holdout = holdout_store.get_holdout(hypothesis_id, db_path=self.db_path)
        holdout_pass = None if holdout is None else bool(holdout["holdout_pass"])

        # Consume the FdrEngine's §7 evaluation (PR-5) if present. Promotion reads
        # FDR and never computes it: absent ⇒ inputs stay None (unavailable).
        fdr = fdr_store.get_fdr(hypothesis_id, db_path=self.db_path)
        bayes_fdr_admitted = None if fdr is None else bool(fdr["bayes_admitted"])
        q_value = None if fdr is None else fdr["q_value"]  # may be None even if row exists

        inputs = PromotionInputs(
            hypothesis_id=hypothesis_id,
            posterior_mean=state["posterior_mean"],
            posterior_sd=state["posterior_sd"],
            ci_low=state["ci_low"],
            ci_high=state["ci_high"],
            n_eff=state["n_eff"],
            q_exceed_prob=state["q_stat_prob"],
            q_precision=state["q_precision"],
            r_sign=state["r_sign"],
            r_disp=state["r_disp"],
            r_replicas=state["r_replicas"],
            replica_count=replica_count,
            g_count=state["g_count"],
            g_coverage=state["g_coverage"],
            v_net_sharpe=state["v_net_sharpe"],
            v_ci_low=state["v_ci_low"],
            v_ci_high=state["v_ci_high"],
            has_unresolved_critical_flag=has_critical,
            # §5 holdout (PR-4) and §7 FDR (PR-5) consumed from the sibling
            # engines; each None until that engine has evaluated this hypothesis.
            q_value=q_value,
            holdout_pass=holdout_pass,
            bayes_fdr_admitted=bayes_fdr_admitted,
        )

        reco = recommend(inputs, self.policy)

        row = {
            "hypothesis_id": hypothesis_id,
            "recommended_stage": reco.recommended_stage,
            "promotion_tier": reco.promotion_tier,
            "posterior_mean": state["posterior_mean"],
            "posterior_sd": state["posterior_sd"],
            "ci_low": state["ci_low"],
            "ci_high": state["ci_high"],
            "confidence_score": state["q_stat_prob"],
            "q_precision": state["q_precision"],
            "r_sign": state["r_sign"],
            "r_disp": state["r_disp"],
            "r_replicas": state["r_replicas"],
            "replica_count": replica_count,
            "g_count": state["g_count"],
            "g_coverage": state["g_coverage"],
            "v_net_sharpe": state["v_net_sharpe"],
            "v_ci_low": state["v_ci_low"],
            "v_ci_high": state["v_ci_high"],
            "has_critical_flag": 1 if has_critical else 0,
            "gate_detail": reco.gate_detail(),
            "method": reco.method,
        }
        promotion_store.upsert_recommendation(row, db_path=self.db_path)
        return row

    # -- rebuild everything -----------------------------------------------
    def rebuild_all(self) -> list[str]:
        """Rebuild recommendations for every hypothesis that has a posterior.

        Returns the list of hypothesis_ids that produced a recommendation.
        """
        rebuilt: list[str] = []
        for st in hypothesis_state_store.list_hypothesis_states(db_path=self.db_path):
            hid = st["hypothesis_id"]
            if self.rebuild_hypothesis(hid) is not None:
                rebuilt.append(hid)
        return rebuilt
