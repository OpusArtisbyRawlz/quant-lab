# PROJECT 07 — FINAL FULL-PIPELINE VALIDATION REPORT

**Experiment:** `exp_007_full_pipeline_validation` · **Branch:** `remediation/p06-p07-return-lineage`
(HEAD `9f0cef0`, prior remediation `8a3f9e0`) · **Date:** 2026-10-28
**Mandate:** full-pipeline validation & research-readiness — **no parameter tuning, no new signals, no gate
change, no candidate promotion, no live trading.** All guardrails honored (see §Guardrails).

This campaign extends `exp_007_advanced_validation` from a *representative* model + restricted overlay grid
to the **actual Project-04 model** and the **broadest verified trial universe** we can reconstruct.
Evidence tags: **[V]** verified · **[I]** inferred · **[U]** unavailable.

---

## Headline
The **actual P04 forecasting model is now reconstructed and reproduced exactly at the prediction level**
(V1 7.4e-9, V2 2.1e-6). Under leakage-controlled CPCV it shows only **weak, regime-dependent rank skill**,
and the **representative ridge used earlier overstated full-sample skill** — an important correction. V1's
alpha and DD Only's **drawdown protection** remain the best-corroborated claims. Overlay selection is not
overfit **within its near-degenerate grid**, but a genuinely distinct selection layer (P04 portfolio
construction) **is** overfit (PBO 0.46–0.77), so pipeline-wide PBO stays a **lower bound**. The shadow-trading
harness is built, tested and safety-guarded; **no candidate is promoted and no real capital is authorized.**

## Answers to the eight research questions

**Q1 — Does the original P04 model retain predictive rank information under purged CPCV?**
**Weakly and regime-dependently.** Full-sample pooled rank IC of the deployed OLS blend ≈ **0** (V1 flipped
leg **−0.012**, V2 leg **+0.014**); deployment-era (2016+) **+0.009** (71% of 28 paths positive). Flat across
embargo 0–21. The ~1.5 portfolio Sharpe draws substantially on directional beta + overlapping labels, not
strong per-name skill. [V] — `FULL_MODEL_CPCV_REPORT.md`

**Q2 — How different from the representative ridge?** **Materially on full history, similar in-era.** Ridge
full-sample rank IC **+0.030 (100% paths)** vs blend ≈ 0 → the ridge **overstated** generalizable skill ~2–3×
and hid the V1 sign-flip's failure to generalize. In the 2016+ window both ≈ **+0.0095**. The ridge is an
acceptable *directional* proxy only within the deployment era. [V]

**Q3 — How complete is our historical trial inventory?** **Partially.** 51 ledgered trials with provenance:
3 P04 model fits + 19 P04 portfolio constructions + 12 P05 overlays + 15 P06 candidates (all **documented**),
the 71-point overlay grid (**inferred/reconstructed**), and 47 parallel idea-generator auto-trials
(**documented but non-comparable**, postdate selection). **Unavailable [U]:** rejected P04 model/feature
variants (no preserved return series), the full P05 overlay-form search, and the finalizer that wrote the
saved P04 portfolio series. [V/I/U] — `HISTORICAL_TRIAL_LEDGER.csv`

**Q4 — Does the low overlay-family PBO survive universe expansion?** **Yes for every verified expansion**
(A 71 → B 83: 0.0016 → 0.0014 Sharpe; 0.0112 → 0.0043 Calmar), **but this is not a low pipeline-wide PBO.**
The overlay grid is **~1 effective dimension** (mean |corr| 0.993), so the low number is partly tautological,
and the one distinct layer we can test — P04 construction — has **PBO 0.77/0.46**. PBO remains a **lower
bound**. [V] — `PBO_SELECTION_SENSITIVITY.md`

**Q5 — Does DD Only's drawdown-protection evidence remain credible?** **Yes — the strongest DD Only claim.**
ΔMDD +6.98 pp (p = 0.0005, FWER-robust); **7/7 folds shallower MDD and lower vol**; MC halves P(MDD<−30%). [V]

**Q6 — What can we conclude from 4/7 Sharpe & 7/7 MDD?** DD Only **reliably cuts drawdown and vol**; its
Sharpe edge is **real but modest and below the 6/7 gate**; **2 of 3 "failures" are a negative-regime
Sharpe-sign artifact** (DD Only lost less *and* drew down less) and the 3rd is a deliberate risk/return trade.
Folds are **overlapping and regime-linked → not independent**; 4/7 is not a binomial and must not be
over-read. Gate **preserved as a failure**; failing it does **not** prove inferiority to V1. [V] —
`DD_ONLY_FOLD_ATTRIBUTION.md`

**Q7 — Are V1 and DD Only ready for controlled shadow/paper observation?** **Ready in logic, risk controls
and safety guards; not yet wired to live data.** Harness, ledger, deviation tracking, cost model and the
no-double-lag execution are built and smoke-tested [V]; three data feeds (market/feature, cross-sectional
returns, borrow/financing) must be connected before a prospective window [U]. V1 and DD Only are the two
approved candidates; **Combined excluded.** [V/U] — `PAPER_TRADING_PROTOCOL.md`, `SHADOW_TRADING_READINESS.md`

**Q8 — What evidence is still required before any real-capital decision?**
1. A completed **prospective paper/shadow window** (≥ 6–12 months) producing genuinely new post-freeze data.
2. **Live-data wiring** of the harness (feeds in §Q7) with realized-vs-assumed cost/borrow reconciliation.
3. An **explicit short-borrow/financing model** folded into net returns (and Combined's 1.28× leverage if ever
   reconsidered).
4. Either **reconstruction of the full P04/P05 search** to certify pipeline-wide PBO, or an explicit decision
   to accept the lower-bound caveat.
5. Resolution or formal acceptance of the **portfolio-finalizer reproducibility blocker** (lineage §4).
6. The **6/7 chronological gate remains the production rule and remains failed by DD Only.**
A real-capital decision is a **separate human sign-off**; nothing here triggers it. [stated]

## Classifications (unchanged from the corrected evidence)
| candidate | classification |
|---|---|
| **V1** | **Validated baseline** — alpha real & selection-aware; weak but positive in-era model rank skill; defect-free. |
| **DD Only** | **Risk-controlled candidate / gate FAILURE (4/7) / needs forward evidence** — robust drawdown + vol edge, modest Sharpe edge. Approved for information-only shadow observation. |
| **Combined DD+Vol** | **Research candidate** — no incremental edge; 1.28× leverage; not eligible. |
| overlay grid winner `dd_f0.2_k7` | **Not a candidate** — PBO diagnostic only; frozen family; not promoted. |

## Reproduce
```
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_full_pipeline_validation/scripts/p2_exact_reproduction.py
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_full_pipeline_validation/scripts/p3_full_model_cpcv.py        # full sample
ERA=2016 PYTHONPATH=. venv/bin/python experiments/completed/exp_007_full_pipeline_validation/scripts/p3_full_model_cpcv.py  # deployment era
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_full_pipeline_validation/scripts/p4_build_ledger.py
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_full_pipeline_validation/scripts/p5_expanded_pbo.py
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_full_pipeline_validation/scripts/p7_fold_attribution.py
PYTHONPATH=. venv/bin/python experiments/completed/exp_007_full_pipeline_validation/scripts/shadow_trader.py
PYTHONPATH=. venv/bin/python -m pytest research/project_07_statistical_integrity/tests research/project_06_deployment_validation/tests -q
```

## Guardrails honored [V]
No strategy parameter changed · no new alpha signal · no overlay optimized · **6/7 gate unchanged** · **no
candidate promoted** · PBO not used to re-select · P04/P05 inputs immutable (checksums) · CPCV labeled
non-chronological · PBO reported as lower bound · no live/broker orders · earlier reports not altered · the
model finalizer blocker reported, not papered over. Branch **not merged** — left for normal PR review.
