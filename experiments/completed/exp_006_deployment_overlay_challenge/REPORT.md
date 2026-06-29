# exp_006 — Deployment Overlay Challenge

**Question:** Can any drawdown/risk overlay discovered in
`research/project_06_failure_analysis/notebooks/05_robustness_checks.ipynb`
beat the *current* US deployment candidate when forced through the **exact same**
deployment-validation battery?

**Design:** one independent variable — the portfolio-level risk overlay.
Everything else (base portfolio, weights, return series, dates, universe,
rebalance logic, transaction-cost model, capacity model, operational-stress
framework) is held identical to the shipped candidate. The incumbent is **not**
overwritten; all challengers are new artifacts in this folder.

## Method (how the overlay was isolated)

The shipped candidate
(`exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv`)
is a dual-layer smooth-DD product. The **portfolio-level** overlay is the
outermost scalar on both the return and the book (book gross |w| correlates
**0.984** with the stored `portfolio_dd_exposure`). It was stripped to recover
the shared base, then each challenger overlay re-applied:

```
base_return_t = portfolio_return_t / exposure_{t-1}   (lagged, look-ahead-safe)
base_book_t   = final_weight_t      / exposure_t       (contemporaneous book scaling)
candidate_return_t = base_return_t * e_cand_{t-1}
candidate_book_t   = base_book_t   * e_cand_t
```

This reproduces the incumbent return series **exactly** (max abs diff 8e-17), so
the only thing that varies between rows is the overlay. Overlays are faithful
re-implementations of the robustness notebook cells (DD-only cell 20; combined
cell 22; floor sweep cell 15; clip sweep cell 9; k-sweep cell 5). Period:
2016-01-04 → 2026-03-06, 2,558 trading days, 20-name megacap universe.

> Note on items "Rebalance k=1 / k=5": the robustness notebook has no
> rebalance-frequency overlay — its `k` is the DD-decay aggressiveness (cell 5,
> `floor=0.6`, `clip 0.3–1.5`). They are implemented as that k-sweep. Rebalance
> *frequency* (1/5/10/21d) is covered separately by the rebalance battery.

## Master comparison (ranked by deployment quality)

| Rank | Overlay | Sharpe | CAGR | MDD | Calmar | Vol | Avg Exp | Mean Turn | Capacity@10% median | Cost-adj Sharpe (10bps) | Ops worst Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **DD Only (floor0.3, k5)** | **2.352** | **0.407** | **−0.295** | **1.382** | 0.150 | 0.691 | 0.0532 | $3.25B | **2.264** | **2.170** |
| 2 | Combined DD+Vol (f0.3,k5,clip.5–1.3) | 2.281 | 0.426 | −0.315 | 1.352 | 0.161 | 0.728 | 0.0555 | $3.18B | 2.196 | 2.103 |
| 3 | Floor 0.3 (≡ Combined) | 2.281 | 0.426 | −0.315 | 1.352 | 0.161 | 0.728 | 0.0555 | $3.18B | 2.196 | 2.103 |
| 4 | Floor 0.5 | 2.183 | 0.425 | −0.355 | 1.198 | 0.169 | 0.787 | 0.0583 | $2.74B | 2.097 | 2.003 |
| 5 | Smooth DD (k5, f0.55) [config recipe] | 2.216 | 0.413 | −0.362 | 1.139 | 0.162 | 0.802 | 0.0581 | $2.60B | 2.126 | 2.029 |
| 6 | DD k=5 (f0.6, clip.3–1.5) | 2.132 | 0.426 | −0.381 | 1.118 | 0.173 | 0.828 | 0.0601 | $2.52B | 2.046 | 1.951 |
| 7 | Clip 0.5–1.2 (f0.6,k5) | 2.132 | 0.423 | −0.381 | 1.110 | 0.172 | 0.825 | 0.0596 | $2.52B | 2.046 | 1.950 |
| 8 | **Deployment (incumbent, as shipped)** | 2.090 | 0.377 | −0.367 | 1.027 | 0.159 | 0.797 | 0.0581 | $2.60B | 1.999 | 1.900 |
| 9 | Clip 0.8–1.0 (f0.6,k5) | 2.084 | 0.403 | −0.406 | 0.992 | 0.169 | 0.869 | 0.0603 | $2.31B | 1.995 | 1.896 |
| 10 | DD k=1 (f0.6, clip.3–1.5) | 1.992 | 0.428 | −0.446 | 0.960 | 0.188 | 0.942 | 0.0653 | $2.12B | 1.905 | 1.808 |
| 11 | Base (no portfolio overlay) | 1.978 | 0.421 | −0.469 | 0.897 | 0.187 | 1.000 | 0.0671 | $1.94B | 1.888 | 1.787 |

Ranking logic (`DeployQuality`, z-scored composite): rewards Sharpe,
cost-adjusted Sharpe, Calmar, shallower MDD, and operational resilience; it is
**not** raw Sharpe alone, so a row only rises by being deployable, not just
high-returning. Tie-breakers: lower MDD → higher Sharpe → higher Calmar.

## Statistical significance (paired circular-block bootstrap, N=5000, block=21d)

DD Only vs incumbent, resampling identical time-blocks for both series:

| Metric | Incumbent | DD Only | Δ | Boot 95% CI of Δ | P(not improved) |
|---|---|---|---|---|---|
| Sharpe | 2.090 | 2.352 | **+0.262** | [+0.133, +0.390] | 0.0002 |
| MDD | −0.367 | −0.295 | **+0.072 (shallower)** | [+0.026, +0.113] | 0.0000 |

Both confidence intervals lie **entirely** on the favorable side — the edge is
not noise.

## Regime persistence (subperiods)

DD Only beats the incumbent in **every** subperiod, on **both** Sharpe and MDD:

| Period | Sharpe (Inc→DD) | MDD (Inc→DD) |
|---|---|---|
| 2016–2018 | 1.73 → 2.00 | −0.189 → −0.166 |
| 2019–2021 | 2.28 → 2.47 | −0.298 → −0.247 |
| 2022–2024 | 2.66 → 3.03 | −0.298 → −0.248 |
| 2025–2026 | 0.35 → 0.36 | −0.205 → −0.143 |

The edge is not a single-crisis artifact. In the weak 2025–26 low-vol regime
(the one the robustness notebook flagged) DD Only still matches Sharpe and is
much shallower — precisely because it carries **no** vol-scaling term, which was
the source of the "participation drag" in that regime.

---

## Final report

**1. Which overlay performed best?**
**DD Only (smooth drawdown exposure, floor 0.3, k 5)** — rank 1 on the
deployment-quality composite and the outright leader on Sharpe, Calmar,
cost-adjusted Sharpe, operational resilience, capacity and turnover, with the
shallowest MDD of any vol-free or vol-combined overlay tested.

**2. Did any overlay significantly reduce MDD?**
Yes. DD Only cut MDD from **−0.367 to −0.295** (−7.2pp, ≈20% relative). The
whole DD-dominant family (Combined/Floor-0.3 −0.315, Floor-0.5 −0.355) beat the
incumbent. Vol-heavy / tight-clip variants (Clip 0.8–1.0 −0.406, k=1 −0.446) were
*worse*.

**3. Statistically meaningful or noise?**
Meaningful. Paired block-bootstrap 95% CIs exclude zero for both Sharpe
(+0.13…+0.39) and MDD (+0.026…+0.113), p ≈ 0; and the improvement holds in all
four subperiods. It is not a single-regime or single-sample fluke.

**4. Promote a challenger to be the new deployment candidate?**
**Yes — conditionally.** DD Only meets *every* acceptance criterion vs the
incumbent: materially lower MDD (−0.295 vs −0.367), better CAGR (0.407 vs 0.377),
better Sharpe (2.352 vs 2.090), better Calmar (1.382 vs 1.027), survives
transaction costs (cost-adj Sharpe 2.264 vs 1.999), survives capacity
($3.25B vs $2.60B median ceiling at 10% ADV, on lower turnover), and survives
operational stress (worst-case Sharpe 2.170 vs 1.900). The burden of proof is met
on the available evidence.

**5. If yes, exactly why.**
It dominates the incumbent on the full battery, the dominance is statistically
significant and regime-persistent, and it does so with *lower* gross exposure and
*lower* turnover — i.e. the gain comes from cutting risk in the right places
(drawdowns), not from leverage. The ablation logic also makes economic sense: the
clean drawdown signal outperforms the vol-blended one, which only adds
low-vol-regime drag.

**6. Caveat / why the switch must be gated (not automatic).**
`floor=0.3` was selected **in-sample**: it was the best row of the robustness
floor sweep *and sits at the lower boundary of the tested range* (0.3–0.9), a
classic mild-overfit flag — the optimum may lie beyond where it was searched, and
the whole overlay is fit and scored on the same 2016–2026 window with no true
out-of-sample period. **Recommendation:** promote DD Only to **lead challenger**
and gate the production switch behind (a) a walk-forward / expanding-window
re-fit of `floor` and `k`, and (b) confirmation that the shallower MDD survives on
held-out data. Until that gate passes, leave the current deployment candidate in
place (untouched here). The decision is evidence-based: the evidence strongly
favors DD Only and warrants the rerun, but final promotion should clear an
out-of-sample check first.
