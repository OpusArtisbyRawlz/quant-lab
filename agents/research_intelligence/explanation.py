"""
explanation.py — pure decision-record builders (M11 PR-11, M11-7).

Render a ``decision_record`` — the explainability log — for each promote / retire /
reject decision, from the rows the existing M11 projections already produced. Pure:
no database, no RNG; it **recomputes no statistic**, it re-shapes existing
projection rows (+ provenance experiment ids) into an explanation.

Decision types covered: ``promote`` (from ``promotion_recommendation``), ``retire``
(from ``retirement_evaluation``), ``reject`` (from ``failure_reason``). The design's
fourth type, ``prioritise``, awaits the Prioritizer M11 integration deferred in
PR-8, so it is not emitted here.
"""

from __future__ import annotations

from typing import Any, Sequence

DECISION_PROMOTE = "promote"
DECISION_RETIRE = "retire"
DECISION_REJECT = "reject"


def build_promotion_record(reco: dict[str, Any],
                           supporting: Sequence[str],
                           contradictory: Sequence[str]) -> dict[str, Any]:
    """Explain a promotion recommendation (subject = hypothesis)."""
    return {
        "decision_type": DECISION_PROMOTE,
        "subject_id": reco["hypothesis_id"],
        "chosen": {"stage": reco["recommended_stage"],
                   "tier": reco["promotion_tier"]},
        "evidence_used": {
            "confidence": reco.get("confidence_score"),
            "q_precision": reco.get("q_precision"),
            "reproducibility": {"sign": reco.get("r_sign"),
                                "dispersion": reco.get("r_disp"),
                                "replicas": reco.get("r_replicas")},
            "generalisation": {"count": reco.get("g_count"),
                               "coverage": reco.get("g_coverage")},
            "value": {"net_sharpe": reco.get("v_net_sharpe"),
                      "ci_low": reco.get("v_ci_low")},
            "gate_detail": reco.get("gate_detail"),
        },
        "confidence": reco.get("confidence_score"),
        "supporting_experiment_ids": list(supporting),
        "contradictory_experiment_ids": list(contradictory),
        "policy_version": reco.get("method"),
    }


def build_retirement_record(ret: dict[str, Any],
                            supporting: Sequence[str],
                            contradictory: Sequence[str]) -> dict[str, Any]:
    """Explain a retirement (subject = hypothesis). Only for retired hypotheses."""
    return {
        "decision_type": DECISION_RETIRE,
        "subject_id": ret["hypothesis_id"],
        "chosen": {"state": ret["state"], "reason": ret.get("reason")},
        "evidence_used": {
            "q_exceed_prob": ret.get("q_exceed_prob"),
            "ci_high": ret.get("ci_high"),
            "refuted": ret.get("refuted"),
            "detail": ret.get("detail"),
        },
        "confidence": ret.get("q_exceed_prob"),
        "supporting_experiment_ids": list(supporting),
        "contradictory_experiment_ids": list(contradictory),
        "policy_version": ret.get("method"),
    }


def build_rejection_record(failure: dict[str, Any]) -> dict[str, Any]:
    """Explain an experiment rejection (subject = experiment)."""
    return {
        "decision_type": DECISION_REJECT,
        "subject_id": failure["experiment_id"],
        "chosen": {"reason_code": failure["reason_code"]},
        "evidence_used": failure.get("evidence"),
        "confidence": None,
        "supporting_experiment_ids": [],
        "contradictory_experiment_ids": [],
        "policy_version": failure.get("method"),
    }
