# PBO & SELECTION-BIAS SENSITIVITY (Phase 5)

**Experiment:** `exp_007_full_pipeline_validation` · script `scripts/p5_expanded_pbo.py`
Results: `PBO_EXPANDED_RESULTS.csv`, `data/pbo_candidate_corr.csv`, `reports/_p5_effective_n.json`.

Reassesses Probability of Backtest Overfitting (PBO, via CSCV; Bailey–López de Prado) across nested
candidate universes that all share the **same 2,558-day index (2016-01-04…2026-03-06)**, the same
return definition (daily LS on `fwd_ret_5`), and the same selection objectives (Sharpe; Calmar =
CAGR/|MDD|, the project's drawdown-aware objective). `S=16` → `C(16,8)=12,870` symmetric IS/OOS splits.

## Results [V]

| universe | objective | n cand. | **PBO** | P(selected loses OOS) | most-selected IS |
|---|---|---|---|---|---|
| **A — overlay grid (71)** | Sharpe | 71 | **0.0016** | 0.000 | `dd_f0.2_k7` |
| A — overlay grid (71) | Calmar | 71 | 0.0112 | 0.000 | `dd_f0.2_k7` |
| **B — expanded verified (83)** | Sharpe | 83 | **0.0014** | 0.000 | `dd_f0.2_k7` |
| B — expanded verified (83) | Calmar | 83 | **0.0043** | 0.000 | `dd_f0.2_k7` |
| **P04 family alone (12)** | Sharpe | 12 | **0.7689** | 0.009 | `p04_ls_20pct_plus_sqrt_partial_normalized` |
| P04 family alone (12) | Calmar | 12 | **0.4629** | 0.015 | `p04_ls_20pct_plus_sqrt_partial_normalized` |

`B` = `A` + the 12 documented Project-04 portfolio-construction trials (`exp_004` strategy_timeseries).

### Effective diversity (why the overlay PBO is so low) [V]

| universe | nominal | eff. dim (participation ratio) | eff. dim (Kaiser) | mean &#124;pairwise corr&#124; |
|---|---|---|---|---|
| A overlay grid | 71 | **1.01** | 1 | **0.993** |
| B expanded | 83 | 1.07 | 2 | 0.966 |
| P04 family | 12 | 1.08 | 1 | 0.957 |

## Interpretation — the three comparisons the phase asks for

**A. Original 71-overlay result reproduced exactly:** PBO 0.0016 (Sharpe) / 0.0112 (Calmar). [V]

**B. Expanded verified family:** adding the 12 documented P04 construction trials **does not raise**
PBO (0.0014 / 0.0043) — the low overlay-selection overfitting is **stable** under the largest
expansion we can make with preserved, comparable return series. [V]

**C. Conservative sensitivity for the unobservable search.** Two facts bound the reading:
1. **The overlay grid has effective dimension ≈ 1** (participation ratio 1.01; mean pairwise correlation
   0.993). Nominally 71 candidates, they are **effectively one strategy** observed at slightly different
   exposure scalings. A low PBO over near-identical candidates is **partly tautological** — you cannot
   overfit a choice among copies — and is therefore a **hard lower bound** on the true selection risk.
2. **A genuinely distinct selection layer overfits.** The **P04 portfolio-construction family** (ls_20
   vs ls_30 vs blends vs +sqrt/linear overlays) — a selection step that **demonstrably happened** (the
   60/40 blend and the "+sqrt_partial_normalized" tweak were chosen there) — has **PBO 0.77 (Sharpe) /
   0.46 (Calmar)**. The in-sample-best construction tweak does **not** persist OOS. This is direct
   evidence that **other, earlier selection layers in this programme carry real overfitting risk** even
   though the overlay layer does not.

## Answers

### Q4 — Does the low overlay-family PBO remain stable when the universe is expanded?
**Yes, for every verified expansion we can build** (A→B: 0.0016→0.0014 Sharpe, 0.0112→0.0043 Calmar).
**But this is not evidence of a low pipeline-wide PBO.** The overlay candidates are ~1 effective
dimension, so the stable low number mostly reflects their near-identity, and the one distinct layer we
*can* test (P04 construction) shows **high** PBO (0.46–0.77). [V]

### Separate Sharpe vs drawdown-aware selection
Reported for both. The Calmar PBO is higher than the Sharpe PBO in every universe (0.0112 vs 0.0016 for
A; 0.46 vs 0.77 inverts for the P04 family because the sqrt-normalized tweak that wins IS-Sharpe is a
near-tie on Calmar). The project's actual objective is drawdown-aware, so the **Calmar** figures are the
decision-relevant ones. [V]

## Critical limitation — PBO is a LOWER BOUND, not a programme-wide probability [U]
The historical candidate search is **not fully reconstructable**:
- The **P04 model search** — OLS-vs-ridge, which features, the V1 sign-flip decision, the V1/V2 blend —
  left only the two final fits; the rejected model variants have **no preserved return series**.
- The **P05 overlay-form search** (linear/sqrt/floor/threshold families in notebook 04) is only partly
  preserved as comparable daily series.
- The **idea_generator track** (47 auto-trials) uses **incomparable objectives** (directional AUC,
  different universes) and is excluded from the CSCV matrix by design (see `HISTORICAL_TRIAL_LEDGER.csv`).

We therefore **do not claim a definitive probability of overfitting for the whole research programme.**
The defensible statement: *overlay selection is not overfit within its (near-degenerate) grid; the
broader programme's PBO is unreconstructable and is bracketed below by the overlay number and above by
the P04-construction-layer number.* We did **not** use any of this to re-select an overlay. [stated]
