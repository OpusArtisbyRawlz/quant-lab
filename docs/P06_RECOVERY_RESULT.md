# Project 06 — deployment-validation recovery result

**Status: RECOVERED through the recovered methodology; reproducible components FIDELITY
VERIFIED; one permanent DATA INTEGRITY ISSUE recorded (not reproduced).**

Project 06 was replayed through the real factory (`exp_012`) using the recovered P05
final PortfolioSpec as its deployment base and the reusable deployment-evaluation stage
(`agents/experiment_runner/deployment_stage.py` + `src/analysis/deployment_tournament.py`,
which reuse the existing `src/analysis` battery — no new engine, no duplicate execution
path). Recovery pipeline: manifest → idea `idea_009` → hypothesis node → approval →
experiment (deployment tournament) → evidence → M11 → Project 07 `preliminary`.

## Reproducible components — FIDELITY VERIFIED

| Component | Historical | Factory replay | Verdict |
| --- | --- | --- | --- |
| V1 incumbent return | Sharpe 2.0901 | **2.0901** (`exp_012`) | exact |
| V1 incumbent book | `final_daily_weights.csv` | max abs weight diff **0.0** | exact |
| Promotion decision | V2 = **DD Only (floor0.3, k5)** | **DD Only (floor0.3, k5)** | exact |
| Top-3 deployable ordering | DD Only → Combined → Floor 0.3 | identical | exact |
| Candidate set | 15 candidates, 9 deployable | 15 / 9 | exact |
| Battery/tournament port | `master_comparison.csv` | reproduced to **1e-16 on the stored base** | exact |

The deployment-evaluation battery (Sharpe, Sortino, Calmar, MDD, Ulcer, turnover,
transaction-cost stress, capacity ceiling, operational stress, DeploymentQuality) reuses
the authoritative `src/analysis` modules verbatim; fed the stored base it reproduces the
historical `master_comparison.csv` exactly.

## DATA INTEGRITY ISSUE (permanent note — not reproduced)

The historical tournament forms its Group-B deployment base by dividing the stored
`portfolio_return` by the stored **`portfolio_dd_exposure`** column of
`exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv`. That column
is **internally inconsistent** with the `portfolio_return` beside it:

- `portfolio_return / portfolio_dd_exposure.shift(1)` → deployment base **Sharpe ≈ 1.978**;
- authoritative strategy-DD multi-strategy base (reproduced exactly) = **1.851**;
- raw weighted base = **1.536**;
- the stored exposure does not equal `smooth_dd(drawdown(·))` of the stored equity, the
  authoritative base, or the raw base (max abs diff ≈ 0.099).

The exposure was computed from a base series that **was not preserved** in the recovered
artifacts. Consequently the Group-B challengers' **absolute** metrics and **mid-pack**
ordering depend on an unpreserved series and are **not** byte-reproducible.

**Policy (per recovery directive):** we do **not** modify the factory or fabricate a lost
series to match an internally inconsistent historical artifact. The recovered,
self-consistent methodology is authoritative. Reproducibility is **not** downgraded for
this — the issue is recorded in `agents/recovery/status.py::DATA_INTEGRITY_NOTES`.

## Provenance chain

historical notebook/README (`research/project_06_deployment_validation/`) → deployment
base = recovered P05 `PortfolioSpec` (`hist_p04_ls20_v1`/`hist_p04_ls30_v1` + recovered
P02 OOF) → experiment `exp_012` → deployment evaluation (`master_comparison.csv`,
`deployment_decision.json`) → Project 07 `preliminary`. Origin artifact:
`exp_006_deployment_candidate_tournament`.

## Recovery markers

| Object | FOUND | EXECUTABLE | REPLAYED | FIDELITY VERIFIED | DATA INTEGRITY ISSUE | PROJECT07 |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| p06_deployment_tournament | ✅ | ✅ | ✅ (`exp_012`) | ✅ (reproducible components) | ⚠️ Group-B base (stored exposure) | preliminary |
