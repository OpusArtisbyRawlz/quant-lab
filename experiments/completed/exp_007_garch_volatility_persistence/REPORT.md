# Project 07 — GARCH Source Verification & Comparative Volatility Persistence

**Campaign:** `exp_007_garch_volatility_persistence` · **Seed:** 20261023 · **Date:** 2026-10-23
**Scope:** audit of Notebook 03 (Monte Carlo); no production candidate promoted or changed.

Central question: *Does volatility persistence differ materially between the US market, our raw alpha
strategy and our risk-controlled variants, and what does that imply for the reliability of our Monte
Carlo drawdown estimates?*

---

## 1. GARCH Source Verification — what 0.995 refers to

**Definitively: 0.995 is the GARCH(1,1)-Student-t persistence of the SPY US market benchmark — NOT V1 or any strategy.**

Lineage (reproduced exactly, `md5(returns)=0e12ecb3aca3a65c`):

| item | value |
|---|---|
| source file | `data/raw/SPY.csv` |
| return column | `Close` → `pct_change()` (simple daily), `dropna` |
| date range | 2005-02-28 → 2026-03-06 |
| observations | 5,288 |
| scaling | none at fit time; `fit_garch` conditions internally in percent (×100), rescales back |
| code path | NB03 cell 19: `select_return_model(markets["US (SPY)"])` → `garch_t` |

Fitted parameters (GARCH(1,1), constant mean, standardized-t innovations, scipy L-BFGS-B, **converged**):

| ω | α | β | α+β | ν | half-life | uncond. vol (ann) |
|---|---|---|---|---|---|---|
| 1.9015e-06 | 0.1430 | 0.8518 | **0.99474** | 5.446 | 131.5 d | 0.302 |

α+β = 0.99474 < 1 → stationary, finite unconditional variance and a valid 131-day half-life. The SE on
persistence is ≈0.0069 (tight). **NB03's attribution ("US (SPY)") is correct; the audit confirms it.**

---

## 2. Comparative GARCH Report (GARCH(1,1)-t, common window 2016-01-04 → 2026-03-06, n=2558)

| series | α | β | α+β | SE(α+β) | ν | half-life | uncond vol(ann) | converged |
|---|---|---|---|---|---|---|---|---|
| SPY (full, 5288) | 0.143 | 0.852 | 0.9947 | 0.007 | 5.45 | 131 d | 0.302 | ✅ |
| SPY (common) | 0.164 | 0.828 | 0.9915 | 0.011 | 5.21 | 81 d | 0.254 | ✅ |
| V1 net | 0.217 | 0.782 | **0.9990** | ~0 | 8.00 | 683 d | 0.509 | ❌ |
| DD Only net | 0.236 | 0.763 | 0.9987 | 0.011 | 8.00 | 514 d | 0.374 | ❌ |
| Combined net | 0.236 | 0.762 | 0.9984 | 0.010 | 8.00 | 434 d | 0.328 | ✅ |

Gross vs net persistence differs by <0.0005 (execution cost does not drive persistence). **GARCH-Normal
vs GARCH-t:** for SPY, t is strongly preferred (Δloglik +162 full sample); for the strategies t and
Normal give near-identical persistence (~0.999) with flipping convergence — the fits sit at a
near-unit-root boundary where the two are barely distinguishable.

> ⚠️ **The strategy persistence estimates are not reliable point values.** ν is pinned at ≈8.0 (its start
> value) for every strategy, several fits report non-convergence, and persistence is pushed onto the
> ~0.999 boundary. These are symptoms of a mis-specified / weakly-identified model (see §3), not evidence
> of a clean "higher strategy persistence."

---

## 3. Model diagnostics — is GARCH appropriate?

ARCH effects are overwhelming in every series (Engle LM(10) p ≈ 0). Standardized-residual checks after the
GARCH-t fit (Ljung-Box(10)):

| series | sq-return ACF₁ (raw) | sq **std-resid** LB(10) p | verdict |
|---|---|---|---|
| SPY (full) | 0.257 | **0.27** | GARCH(1,1)-t adequately removes clustering ✅ |
| SPY (common) | 0.422 | 0.19 | adequate ✅ |
| V1 net | 0.616 | **0.0000** | clustering **remains** → misspecified ❌ |
| DD Only net | 0.613 | 0.0000 | misspecified ❌ |
| Combined net | 0.575 | 0.0000 | misspecified ❌ |

The risk-controlled strategy returns carry squared-return autocorrelation (~0.6) far above SPY (~0.26) that
a GARCH(1,1) **cannot absorb** — the squared standardized residuals stay strongly autocorrelated. This is
expected: the drawdown/vol overlay injects its own endogenous, non-GARCH volatility dynamics.

**Window sensitivity** (GARCH-t persistence) is high and unstable, especially for strategies: SPY ranges
0.928 (2023-26) → 0.999 (2020-22); V1 net 0.875 (2016-19) → 0.999 (full), with ν jumping to ~20 in one
window. Persistence near 1 is not a stable, well-identified quantity here.

*Guidance honoured:* a lower persistence estimate is **not** read as "lower strategy risk," and the
near-unit strategy estimates are flagged as statistically fragile rather than practically meaningful.

---

## 4. Monte Carlo & overlay integrity

**How NB03 generates strategy paths:** option **B** — it **fits/resamples the already risk-controlled
strategy returns directly** (Gaussian calibrated to the strategy's own μ/σ, and a block bootstrap of the
strategy's realized net returns; market/regime rows transplant a risk environment onto the fixed strategy
mean). It does **not** dynamically re-apply the drawdown/vol overlay. NB03 never fits GARCH to strategies —
the only GARCH fits there are the two **market** series.

**Dynamic replay validation (new, method A).** The shipped overlay is
`exposure = floor + (1−floor)·exp(−k·|dd|)`, dd on the base equity, applied with a 1-day lag
(`src/risk/drawdown.py`). Recovering the pre-overlay base return (`exp_005` base) and replaying the rule
reproduces the historical DD Only and Combined **gross** returns to 1e-15. Simulating 10,000 base paths
(block bootstrap, block=20) and replaying the overlay dynamically (A) vs resampling the post-overlay
returns (B):

| strategy | hist MDD | A median | A p5 | A P(<-30%) | B median | B p5 | B P(<-30%) |
|---|---|---|---|---|---|---|---|
| DD Only | −0.299 | −0.280 | −0.378 | 0.34 | −0.300 | −0.451 | 0.50 |
| Combined | −0.319 | −0.295 | −0.428 | 0.46 | −0.318 | −0.477 | 0.60 |

**Implication:** method B (NB03) is *more pessimistic in the tail* than a faithful dynamic replay —
resampling the risk-controlled returns freezes the overlay so it cannot de-risk into simulated drawdowns.
So NB03's strategy-MDD estimates do **not** understate drawdown risk; if anything they are conservative.
They remain a methodological approximation (endogenous risk control treated as an exogenous return stream).
*V1's dual-layer (strategy+portfolio) overlay was not dynamically replayed — more complex; flagged.*

---

## 5. Risk comparison (empirical vs model-fitted vs simulated)

| strategy | hist CAGR | hist MDD *(emp)* | GARCH-t med MDD *(model-sim)* | GARCH-t p5 MDD | bootstrap med MDD *(sim)* | bootstrap p5 MDD |
|---|---|---|---|---|---|---|
| V1 net | 0.357 | −0.372 | −0.306 | **−0.765** | −0.360 | −0.540 |
| DD Only net | 0.388 | −0.299 | −0.269 | −0.670 | −0.300 | −0.451 |
| Combined net | 0.406 | −0.319 | −0.241 | −0.635 | −0.318 | −0.477 |

Each column is labelled by type (empirical / model-fitted / simulated / robustness). The GARCH-t simulator
gives *milder medians* but *far heavier 5th-percentile* drawdowns than the bootstrap — a direct consequence
of near-unit fitted persistence, which produces rare explosive-variance paths. Given §3 (GARCH
misspecified for these series), the **block bootstrap remains the more trustworthy strategy-MDD estimator**,
and the dynamic replay (§4) the most faithful.

---

## 6. Statistical-integrity assessment & recommended next actions

**Findings / confidence.**
- *High confidence:* 0.995 is SPY's market persistence (reproduced exactly); SPY GARCH-t is well-specified
  (clean residual diagnostics, converged, tight SE).
- *High confidence:* GARCH(1,1) is **misspecified** for the risk-controlled strategy returns (residual
  squared-ACF, non-convergence, ν pinned, unstable across windows).
- *Medium confidence:* NB03's direct-resample understates nothing on the drawdown side — it is slightly
  conservative vs the dynamic replay.

**Answer to the central question.** Estimated persistence *is* higher and less stable for the
risk-controlled strategies (~0.999) than for SPY (~0.995 full / ~0.991 common). But this gap mostly
reflects **GARCH(1,1) misspecification on endogenously risk-controlled series**, not a clean risk signal —
so it should **not** be used to rank strategy risk, and it does **not** by itself invalidate NB03's
bootstrap-based drawdown estimates (which do not rely on strategy GARCH fits).

**Recommended changes before NB03 sign-off.**
1. Add a note in NB03 that the 0.995 persistence is the **SPY market** fit, and that **GARCH is not fit to
   strategy returns** (by design) — the audit supports keeping it that way.
2. Do **not** introduce GARCH(1,1) fits on the risk-controlled strategy returns into NB03 (misspecified);
   keep the dependence-preserving bootstrap as the strategy-MDD workhorse.
3. Reference the **dynamic overlay replay** (this experiment) as the faithful strategy-MDD simulator for
   DD Only / Combined, and label NB03's direct resample as a conservative approximation.
4. Add a near-unit-persistence caveat to any market-GARCH tail-drawdown reading (explosive-variance paths
   inflate the 5th-percentile MDD).
5. Extend the dynamic replay to V1's dual-layer overlay before using simulated V1 drawdowns for decisions.

No deployment candidate was selected or changed. All prior notebooks/artifacts preserved; outputs isolated
to this directory.
