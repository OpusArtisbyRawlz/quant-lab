# PBO METHODOLOGY — Stage B5

**Module:** `src/statistics/backtest_overfitting.py::pbo_cscv` · **Tests:** `test_backtest_overfitting.py` (7)
**Application:** `scripts/b_selection_pbo.py` · **Results:** `PBO_RESULTS.csv`

---

## 1. Method — CSCV
Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation (Bailey, Borwein,
López de Prado & Zhu, 2014). Given a performance matrix `M (T × N)` of N candidates over T periods:
1. Partition T rows into `S` contiguous submatrices (S even).
2. For every combination of `S/2` submatrices as in-sample (IS), the complement is out-of-sample (OOS)
   — symmetric, `C(S, S/2)` splits.
3. Pick the IS-best candidate `n*` under a predefined objective.
4. Compute each candidate's OOS performance; take the OOS relative rank `w∈(0,1)` of `n*`.
5. Logit `λ = ln(w/(1−w))`; **PBO = P(λ ≤ 0)** = fraction of splits where the IS-winner lands at or
   below the OOS median.

Validated on known-answer cases (`test_backtest_overfitting.py`): pure noise → PBO≈0.5; a dominant
strategy → PBO<0.05; an IS/OOS sign-reversed (overfit) construction → PBO>0.8; determinism; the
logit-sign/median rule.

## 2. The trial universe (and its known incompleteness — B5 critical limitation)
Candidates = the **documented overlay search grid** reconstructed on the canonical base: floor
∈{0.2,0.25,0.3,0.35,0.4,0.5,0.6} × k∈{3,4,5,6,7}, in both forms (DD-only smooth; vol-combined
clip 0.5–1.3), plus V1 = **71 trials**, 2,558 days, S=16 → `C(16,8)=12,870` splits.

> **This is a LOWER BOUND on selection complexity.** The original Project-04 feature/model search and
> the Project-05 overlay-*form* search cannot be reconstructed from the surviving artifacts. A PBO
> computed over the overlay grid alone omits those earlier selection rounds and therefore
> **understates** the true probability of overfitting of the full research process. We do **not** claim
> a definitive pipeline-wide probability of overfitting.

## 3. Two objectives (the selection criterion matters)
Selecting the highest-Sharpe strategy is **not** the same as selecting under a drawdown-constrained
objective, so PBO is reported under both:

| objective | PBO | median logit | P(selected OOS loss) | median OOS of selected | most-selected IS candidate |
|---|---:|---:|---:|---:|---|
| Sharpe | **0.0016** | 4.26 | 0.00 | 2.38 Sharpe | `dd_f0.2_k7` (12,192/12,870) |
| Calmar (CAGR/\|MDD\|) | **0.0112** | 4.26 | 0.00 | 1.71 Calmar | `dd_f0.2_k7` (12,225/12,870) |

## 4. Reading
PBO is **very low under both objectives**: the overlay-selection procedure is **not overfit within the
grid** — the IS-best overlay stays top-ranked OOS (relative rank ~0.97), and the selected candidate
never has a negative OOS performance. The overlay effect is a persistent, monotone structure (more
aggressive de-risking — lower floor, higher k — scores best both IS and OOS in this single historical
sample), not noise-mining.

## 5. What this does and does NOT establish
- **Does:** within the overlay family, choosing a risk overlay over V1 by Sharpe/Calmar is not a
  selection artifact; the improvement generalizes across combinatorial splits.
- **Does NOT:** (a) justify promoting the grid's IS-winner `dd_f0.2_k7` — the predefined candidate
  family is frozen and **no new candidate is promoted**; the deployed DD Only is (floor 0.3, k5),
  which ranks 17/71 full-sample. (b) certify the full pipeline — the trial ledger is incomplete
  (§2). (c) replace DSR/WRC/PSR/bootstrap/permutation, which address different failure modes
  (see STRATEGY_SELECTION_INTEGRITY.md). PBO is conditional on this sample, this grid and this
  CSCV partition count; dependent overlapping candidates (mean pairwise corr ~0.94) make the
  universe effectively lower-dimensional than N=71.
