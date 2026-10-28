# PROJECT 07 — ADVANCED VALIDATION REPORT (Stage C)

**Experiment:** `exp_007_advanced_validation` · **Branch:** `remediation/p06-p07-return-lineage`
**Date:** 2026-10-28 · validation campaign, not optimization — no parameters changed, no candidate promoted.

Builds on the corrected pipeline (`exp_007_p06_p07_remediation`, commit `8a3f9e0`). Stage A finalized the
remediation (warm-up corrected to machine precision; financing reviewed; promotion gate preserved).
Stage B added purged/embargoed CV, CPCV and PBO. This report consolidates the evidence.

---

## 1. What have we actually established?

| claim | observed point estimate | statistical significance | selection-adjusted | simulation |
|---|---|---|---|---|
| **V1 alpha is real** | net Sharpe 1.999, CAGR 35.7% | bootstrap/permutation/PSR support; White's RC p=0.0103 (selection-aware) | DSR(N=100)≈0.99999 | MC Sharpe ~2.0 |
| **model forecast skill** | OOS rank IC ~0.035 | leakage-robust (purged); positive 28/28 CPCV paths | — | — |
| **DD Only drawdown edge** | net MDD −30.2% vs V1 −37.2% | ΔMDD +6.98pp, p=0.0005; FWER-robust | 7/7 OOS folds | halves P(MDD<−30%): 0.38 vs 0.78 |
| **DD Only Sharpe edge** | +0.141 net | p=0.010; clears FWER | **fails 6/7 gate (4/7)** | Sharpe 2.04 vs 1.91 (net) |
| **DD Only CAGR edge** | −0.3pp | p=0.58 | none | — |
| **Combined incremental edge** | +1.1pp CAGR | Sharpe p=0.20, MDD p=0.10, CAGR p=0.30 — none | none | no edge |
| **overlay-selection overfitting** | — | — | **PBO 0.0016 (Sharpe) / 0.0112 (Calmar)**; lower bound | OOS rank ~0.97 |

Distinguishing the layers: V1's alpha and DD Only's drawdown protection are the **best-corroborated**
claims (significant, selection-aware, OOS-robust, simulation-supported, cost-robust). DD Only's Sharpe
edge is real but modest and fails the chronological gate. Combined has **no** surviving edge. Overlay
*selection* is **not** overfit within the grid, but that is a lower bound on true selection complexity.

## 2. Does DD Only's 4/7 Sharpe result change our conclusion?

No — and it is not grounds to reject DD Only. Alongside the **7/7 MDD** result and the new evidence
(PBO shows the overlay effect is not noise; CPCV shows the forecast and overlay generalize; the 3
Sharpe-miss folds are losing-regime de-risking where DD Only actually *lost less and drew down less*),
the coherent conclusion is: **DD Only is a credible drawdown-control variant of V1 whose Sharpe edge is
real but not strong enough to clear the predefined 6/7 production gate.** The gate is **preserved as a
failure**; we recommend *additional independent evidence* (a defined paper-trading observation window),
not a threshold change and not an overlay re-optimization.

## 3. Are we closer to paper trading?

| candidate | classification |
|---|---|
| **V1** | **Validated baseline** — alpha real, selection-aware tests pass, unchanged by the defect. Eligible for a specifically-defined paper-trading (information-collection) evaluation under existing requirements. |
| **DD Only** | **Risk-controlled candidate / promotion-gate failure / requires additional evidence** — robust drawdown + modest Sharpe improvement; fails the 6/7 gate; eligible for shadow/paper observation *for information only*, not real-capital deployment. |
| **Combined DD+Vol** | **Research candidate** — no incremental edge over V1; carries 1.28× leverage/financing; **not** eligible for promotion or paper trading without new independent evidence. |
| overlay grid winner `dd_f0.2_k7` | **Not a candidate** — surfaced by PBO diagnostics only; frozen family; not promoted. |

Shadow/paper trading for **information collection** is separated from approval for **real-capital
deployment**: nothing here authorizes the latter. No candidate is auto-selected or promoted.

## 4. Integrity gate — pass/fail/provisional

| requirement | status |
|---|---|
| Remediation verified + committed (not merged) | **PASS** (8a3f9e0) |
| Combined warm-up corrected consistently | **PASS** (MC fidelity 5.6e-16) |
| Financing/borrow reviewed; no double-count; leverage explicit | **PASS**; borrow unmodelled → **PROVISIONAL** (bounded) |
| 6/7 promotion gate preserved | **PASS** (kept as failure) |
| Purged K-fold + embargo implemented, tested, applied | **PASS** (12 tests) |
| CPCV implemented, tested, applied (model + selection) | **PASS** (non-chronological → robustness, labeled) |
| PBO (CSCV) implemented, tested, applied | **PASS**; trial ledger incomplete → **PROVISIONAL lower bound** |
| Earlier tests reconciled, not replaced | **PASS** |
| Full P06/P07 regression suite | **PASS** (296 passed, 11 skipped) |
| P04/P05 unaffected | **PASS** (checksums unchanged) |
| No params optimized / no candidate promoted | **PASS** |

## 5. What remains before promotion / real-capital deployment
1. A **defined paper-trading observation protocol** (horizon, metrics, stop rules) for V1 and DD Only —
   information collection only; approval for real capital is a separate decision.
2. An **explicit short-borrow/financing model** (and Combined's 1.28× leverage) folded into net returns
   — currently bounded scenarios only.
3. If selection robustness is to be certified pipeline-wide, **reconstruct the full P04/P05 trial
   ledger**; today's PBO is an overlay-grid lower bound.
4. The chronological **6/7 gate remains the production rule** and remains failed by DD Only — unchanged.

## 6. Confidence & limitations
Root-cause fix and V1 invariance: certain. Corrected metrics and the DD Only drawdown edge: high.
Overlay-selection PBO: low overfitting within the grid, but a **lower bound** (incomplete ledger; 71
highly-correlated candidates ~0.94 → effective dimension ≪ 71; CSCV paths dependent). Model-level CV
uses a representative, not production, forecaster. CPCV/PBO are research robustness tests, not
chronological live-trading replicas.
