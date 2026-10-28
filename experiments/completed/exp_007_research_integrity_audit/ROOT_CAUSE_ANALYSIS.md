# ROOT CAUSE ANALYSIS — Return-Lineage Defect (Projects 06/07)

**Audit:** `exp_007_research_integrity_audit` · **Repo state:** `760f871` · **Period:** 2016-01-04 → 2026-03-06 (2,558 days)
**Classification of this document:** established from code + data, reproduced to machine precision.

---

## 1. One-sentence statement

Both Project-06 experiments recovered the pre-overlay base return by dividing the shipped V1 return
by a **second** lag of the stored exposure (`pr / exp.shift(1)`), even though the stored exposure column
was **already** the lagged applied exposure — injecting a spurious multiplicative factor
`exp[t-1]/exp[t-2]` into every DD-Only / Combined return, while V1 (which never uses that recovery)
stayed exact.

## 2. The exact transformation that introduced it

`src/risk/drawdown.py`:
```python
def apply_exposure_to_return(returns, exposure):
    return returns * exposure.shift(1).fillna(1.0)   # exposure is lagged 1 day on application
```

Project 05 (`research/project_05_risk_engine/notebooks/01_drawdown_overlay.ipynb`, cell 82) persisted:
```python
pd.DataFrame({
    "portfolio_return":      multi_ret_portfolio_dd,            # = multi_ret * portfolio_exp.shift(1)
    "portfolio_dd_exposure": portfolio_exp.shift(1).fillna(1.0) # <-- the ALREADY-LAGGED exposure
}).to_csv("final_weighted_multi_strategy_portfolio_dd.csv")
```
So, writing `port_pre ≡ multi_ret` (the weighted, strategy-level-controlled base) and `e_stored ≡ portfolio_exp.shift(1)`:

> **`portfolio_return[t] = port_pre[t] · e_stored[t]`**  (same-row product; verified to 9.98e-17)

The **correct** inverse is therefore a **same-row divide**: `base[t] = portfolio_return[t] / e_stored[t] = port_pre[t]`.

Project 06 instead did (`exp_006_deployment_candidate_tournament/run_tournament.py:125`
and `exp_006_deployment_overlay_challenge/run_overlay_challenge.py:111`):
```python
base_ret = pr / exp.shift(1).fillna(1.0)     # DEFECT: a SECOND shift
```
giving `base_ret[t] = port_pre[t] · e_stored[t]/e_stored[t-1]`. The residual factor `e_stored[t]/e_stored[t-1]`
is 1 only when exposure is flat; it is ≠1 on **2,327 of 2,558 days**.

## 3. Mechanism classification

**Double-lagging / index-misalignment**, not a cost, normalization, or look-ahead error. The author's mental
model was "stored exposure is the raw, decision-time exposure, so divide by its lag to undo the application."
In fact exp_005 had *already* lagged the exposure before storing it, so the series was lagged twice on the way
back out.

**Internal contradiction that proves it:** the *same function* recovers the position book correctly with a
**same-row** divide but the return with a **shifted** divide:
```python
base_ret  = pr   / exp.shift(1)   # return  — DEFECT
base_book = wide / exp            # book    — correct same-row inverse
```
Both `pr` and `wide` are scaled by the same `e_stored[t]`; they cannot require different inverses. The book
line is right; the return line is wrong. (The overlay-challenge script even documents the two different
conventions side by side in its header comment, lines 24–25.)

## 4. Why V1 reconstructs but DD Only / Combined do not

`candidate_v1_baseline` is built with `ret = pr.copy()` — the shipped series, untouched. It never passes
through `base_ret`. DD Only, Combined and every Group-B / overlay challenger are built as
`apply_exposure_to_return(base_ret, e_challenger)` on the **defective** `base_ret`, so each inherits the
spurious factor (and their challenger exposures are computed on the drawdown of that defective base).

## 5. Minimal reproducible evidence (`reconstruction_and_rootcause.json`)

| identity / check | max |abs| diff | reading |
|---|---:|---|
| `port_pre · e_stored` vs shipped `portfolio_return` | 9.98e-17 | stored exposure is the lagged applied exposure |
| canonical V1 (from exp_004) vs shipped V1 | 9.98e-17 | V1 is defect-free, reconstructs exactly |
| **correct** recovery `pr / e_stored` vs `port_pre` | 1.63e-16 | same-row divide is the true inverse |
| **defect** recovery `pr / e_stored.shift(1)` vs `port_pre` | **9.86e-03** | the double shift is materially wrong |
| defect recovery → shipped DD Only gross | 5.52e-16 | shipped DD Only *was* built on the defect |
| defect recovery → shipped Combined gross | 5.89e-16 | shipped Combined *was* built on the defect |

A toy analytic portfolio (`test_toy_double_shift_injects_known_spurious_factor`) reproduces the exact factor
`e[t-1]/e[t-2]` on a book with a known base and known exposure.

## 6. Timeline & blast radius

- **Clean (pre-defect):** Project 04 raw strategies; Project 05 V1 construction and shipped series.
- **Defect introduced:** the two Project-06 experiments, in the shared `base_ret = pr / exp.shift(1)` idiom
  (`run_tournament.py:125`, `run_overlay_challenge.py:111`), copied between them.
- **Consumers of the defective artifacts:** tournament Group-B candidates + `master_comparison.csv`;
  overlay-challenge equity/significance; `exp_007_candidate_net_validation` DD/Combined daily returns and the
  Sharpe/CAGR/MDD-vs-V1 significance; P07 NB09; and NB03's method-B DD/Combined CAGR/Sharpe.
  See `EVIDENCE_IMPACT_MATRIX.csv`.
- **No other hidden lineage defect found:** every other P07 input traces to V1 (defect-free), the raw P04
  strategies, or the Group-C `final_returns_v2` series (used directly, no recovery).

## 7. Correction

Recover with the same-row inverse (`base = portfolio_return / portfolio_dd_exposure`), or — cleaner —
reconstruct the base directly from exp_004 as `port_pre` (done here). Regression tests in
`research/project_07_statistical_integrity/tests/test_return_lineage_audit.py` fail on the double-shift and
pass on the same-row recovery.
