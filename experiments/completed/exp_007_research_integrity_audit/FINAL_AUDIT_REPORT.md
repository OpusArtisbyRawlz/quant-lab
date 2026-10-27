# FINAL AUDIT REPORT — Research-Integrity Investigation, Projects 04–07

**Experiment:** `exp_007_research_integrity_audit` · **Repo:** `760f871` · **Date:** 2026-10-27
**Scope:** forensic audit of the DD Only / Combined DD+Vol return-lineage discrepancy. No strategies optimised,
no parameters changed, no production candidate selected or promoted. All upstream artifacts preserved
read-only; outputs isolated to this directory.

---

## Executive summary

A single defect — a **double-lagged base-return recovery** in both Project-06 experiments — inflated the
historical returns of the DD Only and Combined DD+Vol challengers. The defect is fully identified, reproduced
to machine precision, corrected, and regression-tested.

- **V1 is clean.** It never passes through the faulty recovery; it reconstructs from the Project-04 inputs to
  ~1e-16 and is unchanged on every metric. All V1-only statistics (bootstrap, permutation, PSR/DSR) are VALID.
- **DD Only and Combined were built on a defective base.** Correcting it removes ~3.5–3.8pp of gross CAGR and
  ~0.12 of Sharpe from each.
- **The core drawdown result survives; the return/Sharpe edges largely do not.** DD Only remains a robust
  drawdown improver (−7pp MDD vs V1, p<0.001) and a weaker-but-significant Sharpe improver (p=0.01), with its
  CAGR advantage erased. Combined is **no longer statistically distinguishable from V1** on Sharpe, CAGR or
  (robustly) MDD.
- **Turnover, costs and the selection-aware tests hold up.** Turnover came from the real position book and is
  essentially unchanged; White's Reality Check and the Deflated Sharpe decision are unchanged.

## The defect in one line

`base_ret = portfolio_return / portfolio_dd_exposure.shift(1)` — but `portfolio_dd_exposure` was **already**
the lagged applied exposure, so the base was de-lagged twice, injecting a spurious `exp[t-1]/exp[t-2]` factor on
2,327 / 2,558 days. The *same functions* recovered the position **book** correctly (`wide/exp`, same-row) — a
self-contradiction that pinpoints the return line as the error.
(Full mechanism: `ROOT_CAUSE_ANALYSIS.md`.)

## Headline numbers (net, vs V1)

| | CAGR | Sharpe | MDD | DD improvement vs V1 | Sharpe improvement vs V1 |
|---|---:|---:|---:|---|---|
| V1 | 35.70% | 1.999 | −37.15% | — | — |
| DD Only (corrected) | 35.38% | 2.139 | −30.18% | **−6.98pp, p=0.0009 ✓** | +0.141, p=0.010 ✓ |
| Combined (corrected) | 36.82% | 2.071 | −32.32% | −4.83pp, p=0.10 ✗ | +0.073, p=0.20 ✗ |

(Was: DD Only 38.84%/2.264/−29.86%; Combined 40.59%/2.196/−31.88% — all three challenger edges previously
"significant". See `OLD_VS_CORRECTED_RESULTS.csv` and `STATISTICAL_INTEGRITY_REVALIDATION.md`.)

## Phase-10 research-integrity verdict

| Result / artifact | Classification | Basis |
|---|---|---|
| V1 historical returns (gross & net) | **VALID** | reconstructs to 1e-16; defect-free path |
| V1 Sharpe / bootstrap CI (NB01) / permutation (NB02) | **VALID** | V1-only inputs |
| PSR / DSR / MinTRL for V1 (NB05) | **VALID** | candidate=V1; saturated, insensitive to defect |
| White's Reality Check (NB06) | **VALID** | winner is raw P04 strategy; p identical corrected |
| Multiple-testing arithmetic (NB04) | **VALID** | structure unaffected (conclusions shift, see below) |
| Turnover & transaction-cost accounting | **VALID** | real-book turnover; <0.02pp cost-drag change |
| DD Only historical returns & vs-V1 **MDD / Sharpe** significance | **CORRECTED** | recomputed; improvements survive |
| DD Only vs-V1 **CAGR** claim | **INVALID** | advantage was an artifact (now ≈0, p=0.58) |
| Combined historical returns & **all** vs-V1 edges | **INVALID** | not distinguishable from V1 after correction |
| Tournament `master_comparison.csv` Group-B rows; overlay-challenge equity/significance | **CORRECTED/PROVISIONAL** | rebuilt on canonical base |
| NB03 Monte Carlo — drawdown conclusions | **VALID** | dynamic replay used canonical base |
| NB03 Monte Carlo — DD/Combined CAGR/Sharpe path stats (method B) | **PROVISIONAL** | resampled defective series |

(Artifact-by-artifact: `EVIDENCE_IMPACT_MATRIX.csv`.)

## Answers to the six central questions

1. **Were V1 / DD Only / Combined historical returns constructed correctly?** V1 **yes** (exact). DD Only &
   Combined **no** — both built on a double-lagged base; now corrected.
2. **Were turnover and costs from the correct positions/exposures?** **Yes** — real position-book turnover,
   essentially unchanged by the defect. (Borrow/financing on shorts remains unmodelled for all three.)
3. **Which PSR / DSR / bootstrap / Monte-Carlo / White's results remain valid?** PSR/DSR (V1), bootstrap,
   permutation, White's Reality Check, and NB03's **drawdown** conclusions all remain **VALID**. The
   challenger-vs-V1 significance tables and NB03's DD/Combined return/Sharpe path stats needed recomputation.
4. **Do the strategies retain credible alpha after reconstruction and realistic costs?** V1: **yes**
   (unchanged; ~2.0 net Sharpe, survives selection-aware tests). DD Only: **yes** as a risk-adjusted/drawdown
   improvement over V1, **not** as a return improvement. Combined: **no incremental** credible alpha over V1.
5. **Does DD Only still provide a robust improvement in maximum drawdown?** **Yes** — −30.2% vs V1's −37.2%
   net (≈7pp), p=0.0009; if anything the correction made the improvement slightly *more* conservative.
6. **Are the corrected results sufficient to continue toward paper trading, or are more validations needed?**
   Sufficient to proceed **with V1 (unchanged) and DD Only as a drawdown-control variant**, *not* to promote
   Combined. Remaining blockers below.

## Remaining deployment blockers

1. **Combined DD+Vol must not be treated as superior to V1** — its edge did not survive. (No promotion either
   way; flagged per mandate.)
2. **Regenerate the downstream P06/P07 artifacts on the canonical base** before any sign-off that cites
   DD/Combined return or Sharpe rankings (tournament Group-B rows, overlay-challenge significance, NB09 tables,
   NB03 method-B CAGR/Sharpe). The *fix* is known and tested; this audit did not overwrite them.
3. **Borrow / financing / leverage costs on the short book are still unmodelled** for every candidate — a
   pre-existing, deployment-relevant gap.
4. **Fix the recovery idiom at source** (`run_tournament.py:125`, `run_overlay_challenge.py:111`): use the
   same-row inverse, or reconstruct from exp_004. Guarded by
   `tests/test_return_lineage_audit.py` (5 tests; full P07 suite 261 passed, 11 skipped).

## Confidence

- *Root cause:* **certain** — reproduced to 1e-16, defect path reproduces the shipped series to 5e-16, and the
  internal book/return contradiction is dispositive.
- *Corrected metrics & significance flips:* **high** — "old" reproductions match the shipped files exactly;
  corrections use a single consistent canonical pipeline with fixed seeds.
- *"No other hidden lineage defect":* **high** — every other P07 input traces to V1, raw P04 strategies, or the
  directly-loaded Group-C series; none uses the faulty recovery.

**Gate status:** the research is **not** complete as previously reported for DD Only (CAGR) and Combined (all
edges). It **is** sound for V1 and for DD Only's drawdown conclusion. Clear the four blockers above before
final Project-07 sign-off.
