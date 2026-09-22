"""
status.py — formal historical-recovery status vocabulary + data-integrity notes.

A recovered strategy advances through these markers. They are intentionally
orthogonal: a replay can be REPLAYED and FIDELITY_VERIFIED yet still carry a
DATA_INTEGRITY_ISSUE describing a historical artifact that is *not* reproducible from
preserved code/data (and which we deliberately do NOT reproduce, per recovery policy).

FOUND               the authoritative implementation was located
EXECUTABLE          it runs through the real factory pipeline
REPLAYED            a factory experiment reproduced it end-to-end
FIDELITY_VERIFIED   the reproducible components match the historical reference
DATA_INTEGRITY_ISSUE  a historical artifact is internally inconsistent / unpreserved;
                    recorded permanently, never reproduced by substituting a lost series
PROJECT07           an authoritative Project 07 verdict has been recorded
"""

from __future__ import annotations

FOUND = "FOUND"
EXECUTABLE = "EXECUTABLE"
REPLAYED = "REPLAYED"
FIDELITY_VERIFIED = "FIDELITY_VERIFIED"
DATA_INTEGRITY_ISSUE = "DATA_INTEGRITY_ISSUE"
PROJECT07 = "PROJECT07"

MARKERS = (FOUND, EXECUTABLE, REPLAYED, FIDELITY_VERIFIED, DATA_INTEGRITY_ISSUE, PROJECT07)

# Permanent, machine-readable record of historical artifacts that cannot be derived
# from preserved code or data. Keyed by recovery_id. These are NOT reproduced.
DATA_INTEGRITY_NOTES: dict[str, dict[str, str]] = {
    "p06_deployment_tournament": {
        "artifact": ("experiments/completed/exp_005_risk_engine_final/"
                     "final_weighted_multi_strategy_portfolio_dd.csv"),
        "column": "portfolio_dd_exposure",
        "issue": (
            "The stored portfolio_dd_exposure column is internally inconsistent with "
            "the portfolio_return column in the same file: dividing them yields a "
            "deployment base of Sharpe ~1.978, which matches neither the authoritative "
            "strategy-DD multi-strategy base (1.851, reproduced exactly) nor the raw "
            "weighted base (1.536). The exposure was computed from a base series that "
            "was not preserved."),
        "impact": (
            "Project 06's Group-B challengers strip this stored exposure to form their "
            "deployment base, so their absolute metrics and mid-pack ordering depend on "
            "the unpreserved series. Reproducible components — V1 incumbent (return + "
            "book, bit-exact), the promotion decision (DD Only floor0.3/k5), and the "
            "top-3 deployable ordering — are verified exactly."),
        "policy": (
            "Not reproduced. Per recovery policy we do not modify the factory or "
            "fabricate a lost series to match an internally inconsistent artifact; the "
            "recovered, self-consistent methodology is authoritative."),
    },
}
