# STRATEGY SELECTION INTEGRITY — Stage B6

**Experiment:** `exp_007_advanced_validation`. Reconciles the new CPCV/PBO evidence with the earlier
statistical-integrity stack. The new tests **complement** — they do not replace — the earlier ones;
each addresses a distinct failure mode.

---

## 1. What each test establishes (and cannot)

| test | failure mode addressed | result (corrected pipeline) | what it does NOT establish |
|---|---|---|---|
| **Bootstrap CI** (NB01) | sampling uncertainty of one series' metric | V1 Sharpe CI excludes 0 | nothing about selection or multiplicity |
| **Permutation** (NB02) | is one series' mean/Sharpe > chance | V1 significant | not selection-aware |
| **PSR** | Sharpe > 0 accounting for skew/kurtosis, one series | ≈1.0 for all three | ignores number of trials |
| **DSR** (NB05) | Sharpe survives *given N trials* (one selected strategy) | V1 ≈0.99999; saturated | not a procedure-level overfit prob |
| **MinTRL** | track length needed for significance | < sample length | — |
| **White's RC** (NB06) | best-of-family vs benchmark 0, selection-aware | p=0.0103, winner raw `P04:ls_20pct` | overlays are not best-of-family; gross |
| **Monte Carlo** (NB03) | drawdown distribution under resampling | DD Only halves P(MDD<−30%) net | not a significance test |
| **Walk-forward gate** (exp_006) | chronological OOS promotion rule | **FAIL** (DD Only Sharpe 4/7 < 6/7; MDD 7/7) | the record OOS chronological test |
| **Purged/embargoed CV** (B2/B3) | label-overlap leakage in model skill | forecaster IC ~0.037, leakage-robust | exact production model |
| **CPCV** (B4) | single-split luck, path dispersion | model IC positive 28/28 paths; selection rank ~0.97 | non-chronological; robustness not live replica |
| **PBO / CSCV** (B5) | **selection-procedure** overfitting | PBO 0.0016 (Sharpe) / 0.0112 (Calmar) | lower bound; overlay grid only |

Key distinctions preserved:
- **DSR ≠ PBO ≠ White's RC ≠ PSR.** DSR deflates one strategy's Sharpe for N trials; White's RC tests
  the best-of-family against a benchmark; PSR tests one Sharpe > 0; **PBO** estimates the probability
  that the *selection rule* picks an OOS-underperformer. They agree here (all supportive) but answer
  different questions.
- A significant unadjusted pairwise p-value is **not** proof after multiple comparisons — the family
  (m=2) Bonferroni/BH corrections (NB09) already gate that: DD Only clears Sharpe & MDD; Combined
  clears nothing.

## 2. Consolidated picture
- **V1 alpha** — real: White's RC (selection-aware, p=0.0103) attributes genuine searched-strategy
  skill to the raw P04 family; PSR/DSR/bootstrap/permutation support V1's own Sharpe; the model-level
  purged CV finds a small, leakage-robust forecasting IC (~0.035) that generalizes across all CPCV
  paths. V1 ranks *low* among overlays (51/71 Sharpe) precisely because it is un-de-risked.
- **Overlay selection** — not overfit within the grid: PBO 0.002–0.011, OOS rank ~0.97. The
  drawdown-overlay improvement is a persistent structure, not noise-mining. **But** this is a lower
  bound (incomplete trial ledger) and does not re-open parameter selection.
- **DD Only** — its drawdown edge is the most strongly corroborated claim (MDD −6.98pp p=0.0005,
  FWER-robust; 7/7 OOS folds; MC halves tail-drawdown; cost-robust). Its Sharpe edge is real but weaker
  (+0.141 p=0.010) and fails the chronological 6/7 gate (4/7).
- **Combined** — no incremental edge survives on any axis after correction; carries leverage (1.28×).

## 3. Guardrails
No strategy parameters changed; no overlay optimized; the 6/7 gate untouched; the candidate family
frozen; the grid's IS-winner (`dd_f0.2_k7`) is **not** promoted. PBO/CPCV were not used to tune the
family. All prior tests retained; none replaced.
